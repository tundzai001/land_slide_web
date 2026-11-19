"""GNSSRuntimeMixin for the GNSS velocity processor."""

from __future__ import annotations

from .common import (
    A_WGS84,
    E2_WGS84,
    F_WGS84,
    GNSS_RUNTIME_STATE_SAVE_INTERVAL_S,
    GNSS_RUNTIME_STATE_VERSION,
    Any,
    Dict,
    Optional,
    asyncio,
    calendar,
    deque,
    logger,
    math,
    np,
    re,
    time,
    DatumParams,
    VN2000Converter,
    normalize_vn2000_l0_value,
    parse_vn2000_central_meridian,
)


class GNSSRuntimeMixin:
    def mark_reference_changed(self, timestamp: float = None, source: str = None):
        """Signal that CORS base / datum reference changed; allows tracking reacquire within time window."""
        self._reference_changed_at = timestamp or time.time()
        self._reference_change_source = source
        self._schedule_runtime_state_save(force=True)
        logger.info(f"[{self._log_prefix()}] Reference frame change marked (source: {source})")

    def is_reference_changed_recently(self, current_ts: float, window_s: float = 300.0) -> bool:
        """Check if a reference change occurred within window_s seconds."""
        changed_at = getattr(self, '_reference_changed_at', None)
        if changed_at is None:
            return False
        delta_s = current_ts - changed_at
        return 0.0 <= delta_s <= window_s

    @staticmethod
    def _normalize_epoch_timestamp(value) -> Optional[float]:
        try:
            timestamp = float(value)
            if not math.isfinite(timestamp):
                return None
            return timestamp / 1000.0 if timestamp > 1e11 else timestamp
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _validated_tracking_offset(value):
        offset = np.asarray(value, dtype=float)
        if (
            offset.shape != (3,)
            or not np.all(np.isfinite(offset))
            or np.linalg.norm(offset[:2]) > 2.0
            or abs(offset[2]) > 10.0
        ):
            raise ValueError(f"invalid persisted tracking offset: {offset}")
        return offset

    def _runtime_state_key(self) -> str:
        return f"gnss_runtime_state:{self.device_id}"

    def _runtime_origin_identity(self):
        origin = getattr(self, "origin", None)
        locked_at = self._normalize_epoch_timestamp(getattr(self, "_origin_locked_at", None))
        origin_record_id = getattr(self, "_origin_record_id", None)
        if not origin or locked_at is None or origin_record_id is None:
            return None
        try:
            identity = {
                "id": int(origin_record_id),
                "locked_at": int(locked_at),
                "lat": float(origin["lat"]),
                "lon": float(origin["lon"]),
                "h": float(origin["h"]),
            }
        except (KeyError, TypeError, ValueError):
            return None
        return identity if all(math.isfinite(identity[key]) for key in ("lat", "lon", "h")) else None

    @staticmethod
    def _validated_runtime_vector(value, name):
        vector = np.asarray(value, dtype=float)
        if vector.shape != (3,) or not np.all(np.isfinite(vector)) or np.max(np.abs(vector)) > 1_000_000.0:
            raise ValueError(f"invalid {name}: {vector}")
        return vector

    def _snapshot_reacquire_candidates(self):
        candidates = []
        for candidate in list(getattr(self, "reacquire_candidates", ()))[:10]:
            try:
                candidate_ts = self._normalize_epoch_timestamp(candidate["ts"])
                candidate_position = self._validated_runtime_vector(candidate["pos_enu"], "quarantine ENU")
                if candidate_ts is None:
                    continue
                candidates.append({
                    "ts": candidate_ts,
                    "pos_enu": candidate_position.tolist(),
                    "fix_quality": int(candidate.get("fix_quality", self.min_fix_quality)),
                })
            except (KeyError, TypeError, ValueError):
                continue

        shift_started_at = self._normalize_epoch_timestamp(getattr(self, "_shift_started_at", None))
        quarantine = (
            {"started_at": shift_started_at, "candidates": candidates}
            if candidates and shift_started_at is not None else None
        )
        return candidates, quarantine

    def _runtime_state_snapshot(self):
        identity = self._runtime_origin_identity()
        history = getattr(self, "history", None)
        if identity is None or not history:
            return None
        last = history[-1]
        if not isinstance(last, dict) or "ts" not in last or "pos_enu" not in last:
            return None
        last_ts = self._normalize_epoch_timestamp(last["ts"])
        if last_ts is None:
            return None
        try:
            last_position = self._validated_runtime_vector(last["pos_enu"], "last trusted ENU")
            displacement = self._validated_runtime_vector(
                getattr(self, "disp_enu_state", np.zeros(3, dtype=float)),
                "displacement ENU",
            )
            tracking_offset = self._validated_tracking_offset(
                getattr(self, "tracking_offset_enu", np.zeros(3, dtype=float))
            )
        except (TypeError, ValueError):
            return None

        _candidates, quarantine = self._snapshot_reacquire_candidates()
        reference_changed_at = self._normalize_epoch_timestamp(getattr(self, "_reference_changed_at", None))
        last_handled_event = self._normalize_epoch_timestamp(
            getattr(self, "_last_handled_reference_event_ts", None)
        )
        peak_mm = float(getattr(self, "peak_displacement_mm", 0.0))
        if not math.isfinite(peak_mm):
            return None
        reference_source = getattr(self, "_reference_change_source", None)
        if reference_source is not None and not isinstance(reference_source, str):
            reference_source = str(reference_source)
        return {
            "version": GNSS_RUNTIME_STATE_VERSION,
            "origin": identity,
            "tracking_offset_enu": tracking_offset.tolist(),
            "last_trusted": {"gga_timestamp": last_ts, "pos_enu": last_position.tolist()},
            "displacement": {
                "enu": displacement.tolist(),
                "ready": bool(getattr(self, "disp_state_ready", False)),
                "peak_mm": max(0.0, peak_mm),
            },
            "last_reacquire_ts": self._normalize_epoch_timestamp(
                getattr(self, "_last_reacquire_ts", 0.0)
            ) or 0.0,
            "reference_event": {
                "changed_at": reference_changed_at,
                "source": reference_source,
                "last_handled_at": last_handled_event,
            },
            "quarantine": quarantine,
            "updated_at": int(time.time()),
        }

    def _validate_stored_origin_and_offset(self, value: dict) -> bool:
        expected_origin = self._runtime_origin_identity()
        stored_origin = value.get("origin")
        if expected_origin is None or not isinstance(stored_origin, dict):
            return False
        if int(stored_origin.get("locked_at")) != expected_origin["locked_at"]:
            return False
        if int(stored_origin.get("id")) != expected_origin["id"]:
            return False
        for key, tolerance in (("lat", 1e-10), ("lon", 1e-10), ("h", 1e-4)):
            if not math.isclose(
                float(stored_origin.get(key)), expected_origin[key], rel_tol=0.0, abs_tol=tolerance
            ):
                return False

        stored_offset = self._validated_tracking_offset(value.get("tracking_offset_enu"))
        current_offset = self._validated_tracking_offset(
            getattr(self, "tracking_offset_enu", np.zeros(3, dtype=float))
        )
        return bool(np.allclose(stored_offset, current_offset, rtol=0.0, atol=1e-7))

    def _validate_stored_quarantine(self, quarantine, trusted_ts: float):
        if quarantine is None:
            return [], None
        if not isinstance(quarantine, dict) or not isinstance(quarantine.get("candidates"), list):
            return None
        shift_started_at = self._normalize_epoch_timestamp(quarantine.get("started_at"))
        if shift_started_at is None or shift_started_at < trusted_ts:
            return None
        restored = []
        for candidate in quarantine["candidates"][-10:]:
            if not isinstance(candidate, dict):
                return None
            candidate_ts = self._normalize_epoch_timestamp(candidate.get("ts"))
            candidate_position = self._validated_runtime_vector(
                candidate.get("pos_enu"), "quarantine ENU"
            )
            fix_quality = int(candidate.get("fix_quality"))
            if candidate_ts is None or candidate_ts <= trusted_ts:
                return None
            restored.append({
                "ts": candidate_ts,
                "pos_enu": candidate_position,
                "fix_quality": fix_quality,
            })
        if not restored:
            return None
        return restored, shift_started_at

    def _parse_trusted_and_displacement(self, value: dict):
        trusted = value.get("last_trusted")
        displacement = value.get("displacement")
        if not isinstance(trusted, dict) or not isinstance(displacement, dict):
            return None
        trusted_ts = self._normalize_epoch_timestamp(trusted.get("gga_timestamp"))
        trusted_position = self._validated_runtime_vector(trusted.get("pos_enu"), "last trusted ENU")
        displacement_position = self._validated_runtime_vector(displacement.get("enu"), "displacement ENU")
        displacement_ready = displacement.get("ready")
        peak_mm = float(displacement.get("peak_mm"))
        if (
            trusted_ts is None or trusted_ts <= 0.0
            or not isinstance(displacement_ready, bool)
            or not math.isfinite(peak_mm) or peak_mm < 0.0
        ):
            return None
        return trusted_ts, trusted_position, displacement_position, displacement_ready, peak_mm

    def _parse_reference_event(self, value: dict):
        last_reacquire_ts = self._normalize_epoch_timestamp(value.get("last_reacquire_ts", 0.0))
        if last_reacquire_ts is None or last_reacquire_ts < 0.0:
            return None
        reference_event = value.get("reference_event") or {}
        if not isinstance(reference_event, dict):
            return None
        reference_changed_at = self._normalize_epoch_timestamp(reference_event.get("changed_at"))
        last_handled_event = self._normalize_epoch_timestamp(reference_event.get("last_handled_at"))
        reference_source = reference_event.get("source")
        if reference_source is not None and not isinstance(reference_source, str):
            return None
        return last_reacquire_ts, reference_changed_at, reference_source, last_handled_event

    def _restore_runtime_state(self, value) -> bool:
        """Restore only a checkpoint tied to this exact immutable origin and offset."""
        self._needs_boot_anchor = True
        try:
            if not isinstance(value, dict) or value.get("version") != GNSS_RUNTIME_STATE_VERSION:
                return False
            if not self._validate_stored_origin_and_offset(value):
                return False

            td_res = self._parse_trusted_and_displacement(value)
            if td_res is None:
                return False
            trusted_ts, trusted_position, displacement_position, displacement_ready, peak_mm = td_res

            ref_res = self._parse_reference_event(value)
            if ref_res is None:
                return False
            last_reacquire_ts, reference_changed_at, reference_source, last_handled_event = ref_res

            quarantine_res = self._validate_stored_quarantine(value.get("quarantine"), trusted_ts)
            if quarantine_res is None:
                return False
            restored_candidates, shift_started_at = quarantine_res

            self.history.clear()
            self.history.append({"ts": trusted_ts, "pos_enu": trusted_position})
            self.reacquire_candidates.clear()
            self.reacquire_candidates.extend(restored_candidates)
            self.disp_enu_state = displacement_position
            self.disp_state_ready = displacement_ready
            self.peak_displacement_mm = peak_mm
            self._last_reacquire_ts = last_reacquire_ts
            self._reference_changed_at = reference_changed_at
            self._reference_change_source = reference_source
            self._last_handled_reference_event_ts = last_handled_event
            self._shift_started_at = shift_started_at
            self._consecutive_rejects = len(restored_candidates)
            self._quarantine_checkpointed = bool(restored_candidates)
            self._needs_boot_anchor = False
            return True
        except (KeyError, TypeError, ValueError, OverflowError):
            return False

    async def _async_save_runtime_state(self, snapshot) -> bool:
        if snapshot is None:
            return False
        try:
            from app.models.config import GlobalConfig
            from sqlalchemy import select

            async with self.db_session_factory() as db:
                result = await db.execute(select(GlobalConfig).where(GlobalConfig.key == self._runtime_state_key()))
                existing = result.scalar_one_or_none()
                now = int(time.time())
                if existing:
                    existing.value = snapshot
                    existing.updated_at = now
                    existing.updated_by = "gnss_processor"
                else:
                    db.add(GlobalConfig(
                        key=self._runtime_state_key(),
                        value=snapshot,
                        updated_at=now,
                        updated_by="gnss_processor",
                    ))
                await db.commit()
            return True
        except Exception as exc:
            logger.exception(f"[{self._log_prefix()}] Failed to persist GNSS runtime state: {exc}")
            return False

    async def _runtime_state_save_loop(self):
        try:
            while getattr(self, "_runtime_state_dirty", False):
                self._runtime_state_dirty = False
                snapshot = self._runtime_state_pending_snapshot
                offset = self._runtime_state_pending_offset
                self._runtime_state_pending_snapshot = None
                self._runtime_state_pending_offset = None
                if offset is not None and not await self._async_save_tracking_offset(offset):
                    continue
                await self._async_save_runtime_state(snapshot)
        finally:
            self._runtime_state_save_task = None

    def _schedule_runtime_state_save(self, *, force=False, persist_tracking_offset=False):
        if not getattr(self, "db_session_factory", None):
            return
        now = time.monotonic()
        last = getattr(self, "_last_runtime_state_schedule_monotonic", 0.0)
        if not force and now - last < GNSS_RUNTIME_STATE_SAVE_INTERVAL_S:
            return
        snapshot = self._runtime_state_snapshot()
        if snapshot is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._last_runtime_state_schedule_monotonic = now
        self._runtime_state_pending_snapshot = snapshot
        if persist_tracking_offset:
            self._runtime_state_pending_offset = np.asarray(self.tracking_offset_enu, dtype=float).copy()
        self._runtime_state_dirty = True
        task = getattr(self, "_runtime_state_save_task", None)
        if task is None or task.done():
            self._runtime_state_save_task = loop.create_task(self._runtime_state_save_loop())
