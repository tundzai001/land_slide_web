"""GNSS payload parsing and adjustment ingestion."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.websocket import manager

logger = logging.getLogger(__name__)


class GnssPayloadMixin:
    def _monitoring_paused_for_adjustment(self, project_id: int, station_id: int) -> bool:
        contexts = getattr(self, "adjustment_run_contexts", {})
        for run_id, session in self.round_robin_manager._sessions.items():
            if (self.adjustment_phase.get(run_id) not in {"STARTING", "COLLECTING_BASELINE", "FREE_NETWORK", "PAUSED"}
                    and not session.get("seed_topology_snapshots")):
                continue
            context = contexts.get(run_id) or {}
            if int(context.get("project_id") or session.get("monitoring_project_id") or run_id) != int(project_id):
                continue
            if any(int(station_id) in cluster.get("stations", ()) for cluster in session.get("clusters", ())):
                return True
        return False

    def _format_station_seed_delta(self, rolling, stability_win: int) -> str:
        delta = rolling.get("delta_neu_m")
        if delta and len(delta) == 3:
            return f"dN/E/U={float(delta[0]) * 1000:.1f}/{float(delta[1]) * 1000:.1f}/{float(delta[2]) * 1000:.1f}mm"
        return f"waiting for two {stability_win}s windows"

    def _format_station_seed_state(self, is_open: bool, waiting_id: int, counts: dict, durations: dict, warmup_counts: dict, warmup_durations: dict, seed_status: dict) -> str:
        w_id_str = str(waiting_id)
        if is_open:
            c = int(counts.get(waiting_id, counts.get(w_id_str, 0)) or 0)
            d = int(durations.get(waiting_id, durations.get(w_id_str, 0)) or 0)
            return f"solver={c}/{int(seed_status.get('solver_min_distinct_epochs') or 0)} epochs, {d}/{int(seed_status.get('solver_min_duration_seconds') or 0)}s"
        wc = int(warmup_counts.get(waiting_id, warmup_counts.get(w_id_str, 0)) or 0)
        wd = int(warmup_durations.get(waiting_id, warmup_durations.get(w_id_str, 0)) or 0)
        return f"fixed-base warm-up={wc}/{int(seed_status.get('seed_warmup_min_distinct_epochs') or 0)} epochs, {wd}/{int(seed_status.get('seed_warmup_min_duration_seconds') or 0)}s"

    def _format_cluster_seed_progress(self, cluster_status: dict, seed_status: dict) -> list[str]:
        parts = []
        rolling_by_station = cluster_status.get("rolling_stability_by_station") or {}
        open_by_station = cluster_status.get("solver_window_open_by_station") or {}
        count_by_station = cluster_status.get("solver_sample_counts_by_station") or {}
        duration_by_station = cluster_status.get("solver_durations_by_station_seconds") or {}
        warmup_count_by_station = cluster_status.get("sample_counts_by_station") or {}
        warmup_duration_by_station = cluster_status.get("durations_by_station_seconds") or {}
        reset_by_station = cluster_status.get("solver_window_reset_counts_by_station") or {}
        drift_by_station = cluster_status.get("solver_drift_failure_counts_by_station") or {}

        for waiting_station_id in (cluster_status.get("warming_station_ids") or ()):
            rolling = rolling_by_station.get(waiting_station_id) or rolling_by_station.get(str(waiting_station_id)) or {}
            delta_text = self._format_station_seed_delta(rolling, seed_status.get("stability_window_seconds", 10))
            is_open = bool(open_by_station.get(waiting_station_id) or open_by_station.get(str(waiting_station_id)))
            state_text = self._format_station_seed_state(
                is_open, waiting_station_id, count_by_station, duration_by_station,
                warmup_count_by_station, warmup_duration_by_station, seed_status
            )
            reset_count = int(reset_by_station.get(waiting_station_id, reset_by_station.get(str(waiting_station_id), 0)) or 0)
            drift_count = int(drift_by_station.get(waiting_station_id, drift_by_station.get(str(waiting_station_id), 0)) or 0)
            parts.append(f"ID {waiting_station_id}: {state_text}, {delta_text}, resets={reset_count}, rolling-advisory-strikes={drift_count}")
        return parts

    def _collect_seed_progress_parts(self, seed_status: dict) -> list[str]:
        parts = []
        for cluster_status in seed_status.get("clusters") or ():
            parts.extend(self._format_cluster_seed_progress(cluster_status, seed_status))
        return parts

    def _build_invalid_fix_parts(self, seed_status: dict, invalid_fix_ids: list) -> list[str]:
        position_type_parts = []
        for item in seed_status.get("clusters") or ():
            position_types = item.get("latest_position_type_by_station") or {}
            for invalid_station_id in invalid_fix_ids:
                val = position_types.get(invalid_station_id, position_types.get(str(invalid_station_id)))
                if val is not None:
                    position_type_parts.append(f"ID {invalid_station_id}=type {val}")
        return position_type_parts

    def _build_seed_waiting_parts(self, seed_status: dict, seed_progress_parts: list[str]) -> list[str]:
        waiting_parts = []
        if seed_status["missing_station_ids"]:
            silent_ids = seed_status.get("silent_station_ids") or []
            invalid_fix_ids = seed_status.get("invalid_fix_station_ids") or []
            if silent_ids:
                waiting_parts.append(f"no AGRICA station IDs {silent_ids}")
            if invalid_fix_ids:
                type_parts = self._build_invalid_fix_parts(seed_status, invalid_fix_ids)
                waiting_parts.append("AGRICA not RTK Fixed: " + (", ".join(dict.fromkeys(type_parts)) or str(invalid_fix_ids)))
        if seed_status.get("warming_station_ids"):
            waiting_parts.append(" | ".join(seed_progress_parts) or f"stations still building a stable seed window {seed_status['warming_station_ids']}")
        return waiting_parts

    async def _broadcast_seed_diagnostic(self, proj_id: int, public_project_id: int, station_id: int, seed_status: dict | None, seed_progress_parts: list[str]):
        diagnostic = self.round_robin_manager.get_last_ingest_diagnostic(proj_id)
        if not diagnostic:
            return
        if seed_status:
            diagnostic = {**diagnostic, "seed_status": seed_status}
            if seed_status["missing_station_ids"] or seed_status.get("warming_station_ids"):
                waiting_parts = self._build_seed_waiting_parts(seed_status, seed_progress_parts)
                msg = f"{diagnostic['message']} Offline discovery {seed_status['step_count']}/{seed_status['max_steps']}; waiting for {'; '.join(waiting_parts)}."
                diagnostic = {**diagnostic, "message": msg}

        diag_msg = str(diagnostic.get("message") or "")
        is_fragment = diag_msg.startswith("Buffered AGRICA fragment")
        if not is_fragment or self._diag_should_log(f"gnss_adjustment_fragment:{proj_id}:{station_id}", 2):
            cluster_name = (self.adjustment_run_contexts.get(proj_id) or {}).get("cluster_name")
            await manager.broadcast({
                "type": "gnss_adjustment_debug",
                "project_id": public_project_id,
                "run_id": proj_id,
                "cluster_name": cluster_name,
                **diagnostic,
            })

    async def _broadcast_valid_baselines(self, valid_obs: list, proj_id: int, public_project_id: int, station_id: int):
        for obs in valid_obs:
            try:
                b_from = self.round_robin_manager.get_active_base_for_station(proj_id, station_id)
                cluster_name = (self.adjustment_run_contexts.get(proj_id) or {}).get("cluster_name")
                await manager.broadcast({
                    "type": "gnss_baseline_collected",
                    "project_id": public_project_id,
                    "run_id": proj_id,
                    "cluster_name": cluster_name,
                    "station_id": station_id,
                    "from": b_from,
                    "rover_name": obs.rover_name,
                    "baseline_neu": obs.baseline_neu,
                    "std_neu": obs.std_neu,
                    "rover_llh": obs.rover_llh,
                    "base_llh": obs.base_llh,
                    "full_data": obs.full_data,
                })
            except Exception as exc:
                logger.exception("Could not broadcast GNSS baseline: %s", exc)

    async def _transition_to_free_network(self, proj_id: int, public_project_id: int, seed_status: dict | None):
        skipped_ids = (seed_status or {}).get("skipped_station_ids", [])
        active_session = self.round_robin_manager._sessions.get(proj_id) or {}
        expected_station_ids = sorted({
            int(st_id) for cl in active_session.get("clusters") or () for st_id in cl.get("stations") or ()
        })
        roster = getattr(self, "adjustment_run_rosters", {}).get(proj_id) or {}
        roster["participating_station_ids"] = expected_station_ids
        roster["skipped_seed_station_ids"] = sorted({*roster.get("skipped_seed_station_ids", []), *skipped_ids})
        if hasattr(self, "adjustment_run_rosters"):
            self.adjustment_run_rosters[proj_id] = roster
        self.adjustment_phase[proj_id] = "FREE_NETWORK"
        if proj_id in self.adjustment_run_contexts:
            self.adjustment_run_contexts[proj_id]["status"] = "FREE_NETWORK"

        msg = (
            f"Skipped offline/degraded station IDs {skipped_ids} after {self.round_robin_manager.SEED_COLLECTION_MAX_STEPS} seed steps. Starting Round-Robin with the remaining rovers."
            if skipped_ids
            else f"All selected rovers completed the fixed-base seed window ({self.round_robin_manager.SEED_SOLVER_MIN_DURATION_SECONDS}s stationary solver data each). Starting Round-Robin."
        )
        cluster_name = (self.adjustment_run_contexts.get(proj_id) or {}).get("cluster_name")
        await manager.broadcast({
            "type": "gnss_adjustment_progress",
            "project_id": public_project_id,
            "run_id": proj_id,
            "cluster_name": cluster_name,
            "phase": "FREE_NETWORK",
            "expected_station_ids": expected_station_ids,
            "roster": roster,
            "message": msg,
        })
        await self.round_robin_manager.start_cycle(proj_id)

    async def _handle_collecting_baseline_seed(self, proj_id: int):
        seed_status = self.round_robin_manager.get_seed_collection_status(proj_id)
        if seed_status["fallback_ready"]:
            seed_status = self.round_robin_manager.skip_missing_seed_stations(proj_id)
        seed_progress_parts = self._collect_seed_progress_parts(seed_status)
        if seed_status.get("stability_timeout"):
            msg = (
                f"Fixed-base baselines did not produce a complete time-based stable solver window within {seed_status['stability_timeout_seconds']}s. "
                f"No network solution was published. Last station state: {' | '.join(seed_progress_parts) or 'no rolling diagnostics'}"
            )
            await self._handle_round_robin_adjustment_error(proj_id, msg)
        return seed_status, seed_progress_parts

    async def _handle_agrica_stream(self, raw_payload: str, info: dict, phase: str | None, proj_id: int, public_project_id: int, station_id: int):
        if phase not in {"COLLECTING_BASELINE", "FREE_NETWORK"}:
            return
        valid_obs = self.round_robin_manager.add_agrica_payload(raw_payload, info)
        seed_status = None
        seed_progress_parts = []
        if phase == "COLLECTING_BASELINE":
            seed_status, seed_progress_parts = await self._handle_collecting_baseline_seed(proj_id)

        await self._broadcast_seed_diagnostic(proj_id, public_project_id, station_id, seed_status, seed_progress_parts)
        await self._broadcast_valid_baselines(valid_obs, proj_id, public_project_id, station_id)

        if phase == "COLLECTING_BASELINE" and self.round_robin_manager.has_complete_seed_observations(proj_id):
            await self._transition_to_free_network(proj_id, public_project_id, seed_status)

    async def _handle_origin_relock(self, processor: Any, device_id: int, station_id: int, public_project_id: int, current_timestamp: int):
        await self._touch_online_heartbeat(device_id, station_id, current_timestamp)
        try:
            await self._touch_active_alert(station_id, "gnss_velocity", current_timestamp)
        except Exception as touch_error:
            logger.exception(f"❌ GNSS active-alert refresh during origin relock failed: {touch_error}")

        status_payload = {
            "status": "ORIGIN_RELOCK_COLLECTING",
            "fix_quality": getattr(processor, "min_fix_quality", 4),
            "message": "Collecting stable RTK FIXED samples to replace the monitoring origin",
            "data": {"integrity_state": "ORIGIN_RELOCK_COLLECTING", "position_quality_reliable": False},
        }
        try:
            await self._upsert_latest_sensor_cache(station_id, "gnss", current_timestamp, status_payload)
            await manager.broadcast({
                "type": "sensor_status", "project_id": public_project_id,
                "station_id": station_id, "sensor_type": "gnss",
                "timestamp": current_timestamp, "data": status_payload,
            })
        except Exception as ws_e:
            logger.exception(f"❌ GNSS origin relock status update failed: {ws_e}")

    async def _handle_gnss_quarantine(self, station_id: int, device_id: int, station_config: dict, status_payload: dict, raw_payload: str, current_timestamp: int):
        try:
            await self._touch_active_alert(station_id, "gnss_velocity", current_timestamp)
        except Exception as touch_error:
            logger.exception(f"❌ GNSS active-alert refresh failed: {touch_error}")
        if status_payload.get("status") != "ADJUSTMENT_IN_PROGRESS" and self._is_processing_storage_enabled(station_config):
            rec = {
                "station_id": station_id, "timestamp": current_timestamp, "sensor_type": "gnss_anomaly",
                "ingest_id": self._make_ingest_id(device_id, station_id, "gnss_anomaly", current_timestamp, status_payload, raw_payload),
                "data": status_payload, "value_1": None, "value_2": None, "value_3": None, "value_4": None, "value_5": None
            }
            async with self._buffer_lock:
                self._sensor_buffer.append(rec)

    async def _handle_gnss_status_message(self, res: dict, public_project_id: int, station_id: int, device_id: int, station_config: dict, raw_payload: str, current_timestamp: int):
        status_payload = {
            "status": res.get("status"), "sub_status": res.get("sub_status"),
            "fix_quality": res.get("fix_quality"), "fix_mode": res.get("fix_mode"),
            "message": res.get("message"), "raw_payload": res.get("raw_payload", ""),
            "data": res.get("data"),
        }
        quarantine_statuses = {
            "INITIALIZING", "VELOCITY_WARMUP", "INVALID_DATA", "UNVERIFIED_POSITION_SHIFT",
            "UNTRUSTED_GEOMETRY", "PERSISTENT_OFFSET_QUARANTINED", "REJECTED_MEASUREMENT",
            "UNSTABLE_FIX", "REFERENCE_CHANGE_PENDING", "REFERENCE_TRANSITION",
            "STALE_REFERENCE", "REACQUIRE_REFUSED", "CHECKSUM_FAILED", "NO_DATA", "ADJUSTMENT_IN_PROGRESS",
        }
        if res.get("status") in quarantine_statuses:
            await self._handle_gnss_quarantine(station_id, device_id, station_config, status_payload, raw_payload, current_timestamp)
        try:
            await self._upsert_latest_sensor_cache(station_id, "gnss", current_timestamp, status_payload)
        except Exception:
            pass
        try:
            await manager.broadcast({
                "type": "sensor_status", "project_id": public_project_id,
                "station_id": station_id, "sensor_type": "gnss",
                "timestamp": current_timestamp, "data": status_payload
            })
        except Exception as ws_e:
            logger.exception(f"❌ WS GNSS status error: {ws_e}")

    async def _handle_origin_status_message(self, res: dict, public_project_id: int, station_id: int, current_timestamp: int):
        status_payload = {
            "status": res.get("status"), "fix_quality": res.get("fix_quality"),
            "fix_mode": res.get("fix_mode"), "message": res.get("message")
        }
        try:
            await self._upsert_latest_sensor_cache(station_id, "gnss", current_timestamp, status_payload)
        except Exception:
            pass
        try:
            await manager.broadcast({
                "type": "sensor_status", "project_id": public_project_id,
                "station_id": station_id, "sensor_type": "gnss",
                "timestamp": current_timestamp, "data": status_payload
            })
        except Exception as ws_e:
            logger.exception(f"❌ WS GNSS origin status error: {ws_e}")

    async def _handle_gngga_result(self, res: dict | None, info: dict, public_project_id: int, station_id: int, station_name: str, processor: Any, station_config: dict, device_id: int, raw_payload: str, current_timestamp: int) -> dict | None:
        if res is None and getattr(processor, "_origin_relock_in_progress", False):
            await self._handle_origin_relock(processor, device_id, station_id, public_project_id, current_timestamp)
            return None
        if not res:
            return None
        r_type = res.get("type")
        if r_type == "gnss_processed":
            p_data = res.get("data")
            lat, lon = p_data.get("latitude"), p_data.get("longitude")
            if lat is not None and lon is not None:
                self.round_robin_manager.update_rover_llh(info.get("station_code"), lat, lon, p_data.get("altitude", 0.0))
            return p_data
        if r_type == "gnss_status":
            await self._handle_gnss_status_message(res, public_project_id, station_id, device_id, station_config, raw_payload, current_timestamp)
            return None
        if r_type == "origin_locked":
            logger.info(f"🎯 [{station_name}] GNSS Origin locked")
            try:
                await self._upsert_latest_sensor_cache(station_id, "gnss", current_timestamp, res.get("data", {}))
            except Exception:
                pass
            return None
        if r_type == "origin_status":
            await self._handle_origin_status_message(res, public_project_id, station_id, current_timestamp)
            return None
        return None

    async def _process_gnss_payload(
        self,
        info: dict,
        raw_payload: str,
        public_project_id: int,
        station_id: int,
        station_name: str,
        processor: Any,
        station_config: dict,
        device_id: int,
        adjustment_only: bool,
        current_timestamp: int,
    ) -> dict | None:
        sensor_type = info["type"]
        try:
            proj_id = int(info.get("project_id") or info.get("station_id") or 0)
            phase = self.adjustment_phase.get(proj_id)
            if proj_id not in self.round_robin_manager._sessions:
                phase = None

            has_agrica = "#AGRICA" in raw_payload or self.round_robin_manager.has_pending_agrica_fragment(proj_id, station_id)
            if has_agrica:
                await self._handle_agrica_stream(raw_payload, info, phase, proj_id, public_project_id, station_id)

            if adjustment_only:
                return None

            if re.search(r"\$G[NP]GGA,", raw_payload):
                if self._monitoring_paused_for_adjustment(public_project_id, station_id):
                    res = {
                        "type": "gnss_status", "status": "ADJUSTMENT_IN_PROGRESS",
                        "message": "GNSS monitoring paused while correction source changes for adjustment",
                        "data": {"integrity_state": "ADJUSTMENT_IN_PROGRESS", "position_quality_reliable": False},
                    }
                else:
                    res = processor.process_gngga(raw_payload, station_config)
                return await self._handle_gngga_result(
                    res, info, public_project_id, station_id, station_name,
                    processor, station_config, device_id, raw_payload, current_timestamp
                )
        except Exception as e:
            logger.exception(f"Processing error ({sensor_type}): {e}")
            return None
        return None
