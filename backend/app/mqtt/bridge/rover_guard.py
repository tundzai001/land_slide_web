"""Recover configured rovers emitting RTCM outside an adjustment session."""
import asyncio
import logging
import time
from typing import Any, Dict

logger = logging.getLogger(__name__)


class IdleRoverGuardMixin:
    IDLE_ROVER_POLL_SECONDS = 5.0
    IDLE_ROVER_RETRY_SECONDS = 60.0
    _TERMINAL_ADJUSTMENT_PHASES = {
        "COMPLETED", "ERROR", "FAILED_QUALITY_GATE", "PARTIAL_FAILED", "STOPPED", "CANCELLED",
    }

    @staticmethod
    def _cluster_contains_rover(cluster: dict, info: dict) -> bool:
        identities = {str(info["station_id"]), str(info["station_code"]).strip().casefold()}
        return bool(identities.intersection(
            str(value).strip().casefold()
            for value in [*cluster.get("stations", []), *cluster.get("rovers", [])]
        ))

    def _rover_has_active_adjustment(self, info: dict) -> bool:
        manager = self.round_robin_manager
        for run_id, session in manager._sessions.items():
            if not any(self._cluster_contains_rover(cluster, info) for cluster in session.get("clusters", [])):
                continue
            phase = str(self.adjustment_phase.get(run_id)
                        or self.adjustment_run_contexts.get(run_id, {}).get("status") or "").upper()
            task = manager.running_tasks.get(run_id)
            # No phase yet means startup/preflight. A live task also covers
            # cancellation/finally while the receiver and CORS route restore.
            if (session.get("idle_recovery_reserved")
                    or session.get("seed_topology_snapshots")
                    or (task is not None and not task.done())
                    or phase not in self._TERMINAL_ADJUSTMENT_PHASES):
                return True
        return False

    async def _evaluate_idle_rover(self, manager: Any, info: Dict[str, Any], key: str) -> None:
        async with manager._idle_rover_recovery_lock:
            if self._rover_has_active_adjustment(info):
                self._idle_rover_rtcm_seen.pop(key, None)
                return
            health = manager.get_gnss_stream_health(info["station_code"])
            if not health.get("valid_rtcm_recent"):
                self._idle_rover_rtcm_seen.pop(key, None)
                return
            frames = int(health.get("valid_rtcm_frames") or 0)
            previous = self._idle_rover_rtcm_seen.get(key)
            self._idle_rover_rtcm_seen[key] = frames
            # Require new CRC-valid frames across two polls, so an old
            # rotation's final packet cannot trigger a recovery command.
            if previous is None or frames <= previous:
                return
            if time.monotonic() < self._idle_rover_retry_at.get(key, 0):
                return
            try:
                client = await manager._find_client_info(info["station_code"], log_missing=False)
                if not client or not str(client.get("Mountpoint") or "").strip():
                    raise RuntimeError("no active AICaster control session/mountpoint")
                logger.warning(
                    "Idle rover %s is emitting verified RTCM outside adjustment; restoring ROVER",
                    info["station_code"],
                )
                await manager.restore_rover_stream(info["station_code"], client_info=client)
            except Exception as exc:
                logger.error("Idle rover %s recovery not verified; retry after cooldown: %s",
                             info["station_code"], exc)
            else:
                self._idle_rover_rtcm_seen.pop(key, None)
                logger.info("Idle rover %s recovered: receiver ACK and fresh GGA/AGRICA verified, RTCM stopped",
                            info["station_code"])
            finally:
                self._idle_rover_retry_at[key] = time.monotonic() + self.IDLE_ROVER_RETRY_SECONDS

    async def _check_idle_rover_streams(self) -> None:
        manager = self.round_robin_manager
        checked = set()
        for info in list(self.topic_map.values()):
            if info.get("type") != "gnss" or not info.get("station_code"):
                continue
            key = str(info["station_code"]).strip().casefold()
            if key in checked:
                continue
            checked.add(key)
            # Fixed CORS bases and arbitrary MQTT devices are not recovery
            # targets. Only configured project-cluster rovers are eligible.
            if not any(self._cluster_contains_rover(cluster, info)
                       for cluster in info.get("project_gnss_clusters") or []):
                continue
            await self._evaluate_idle_rover(manager, info, key)

    async def _idle_rover_guard_loop(self) -> None:
        while not self._stopping:
            try:
                await self._check_idle_rover_streams()
            except Exception:
                logger.exception("Idle rover stream check failed")
            await asyncio.sleep(self.IDLE_ROVER_POLL_SECONDS)
