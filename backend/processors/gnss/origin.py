"""GNSSOriginMixin for the GNSS velocity processor."""

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
    haversine_2d,
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


class GNSSOriginMixin:
    def _schedule_load_origin(self):
        try:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                self._initialization_task = loop.create_task(self._async_load_origin_task())
            except RuntimeError:
                logger.warning(f"⚠️ Device {self.device_id}: Init outside event loop, origin will be collected manually.")
                self._initialization_complete = True
        except Exception as e:
            logger.exception(f"❌ Device {self.device_id}: Error scheduling DB load: {e}")
            self._initialization_complete = True

    async def _async_load_origin_task(self):
        try:
            from app.models.config import GlobalConfig, GNSSOrigin
            from sqlalchemy import select

            runtime_state = None
            async with self.db_session_factory() as db:
                try:
                    result = await db.execute(
                        select(GNSSOrigin).where(GNSSOrigin.device_id == self.device_id)
                    )
                    origin_record = result.scalar_one_or_none()
                except Exception as col_err:
                    # Nếu DB chưa kịp migrate cột tracking_offset, query các cột cơ bản
                    logger.warning(f"⚠️ Device {self.device_id}: Direct model select failed ({col_err}), attempting basic column select")
                    result = await db.execute(
                        select(
                            GNSSOrigin.lat, GNSSOrigin.lon, GNSSOrigin.h,
                            GNSSOrigin.rotation_matrix, GNSSOrigin.ecef_origin,
                            GNSSOrigin.locked_at, GNSSOrigin.id,
                        ).where(GNSSOrigin.device_id == self.device_id)
                    )
                    row = result.first()
                    if row:
                        origin_record = type('SimpleOrigin', (), {
                            'lat': row[0], 'lon': row[1], 'h': row[2],
                            'rotation_matrix': row[3], 'ecef_origin': row[4],
                            'locked_at': row[5],
                            'id': row[6],
                            'tracking_offset': None
                        })()
                    else:
                        origin_record = None

                try:
                    runtime_result = await db.execute(
                        select(GlobalConfig).where(GlobalConfig.key == self._runtime_state_key())
                    )
                    runtime_record = runtime_result.scalar_one_or_none()
                    runtime_state = runtime_record.value if runtime_record else None
                except Exception as runtime_err:
                    logger.warning(
                        f"[{self._log_prefix()}] GNSS runtime checkpoint unavailable: {runtime_err}"
                    )
            
            if origin_record:
                # Validate dữ liệu trước khi dùng
                if origin_record.rotation_matrix and origin_record.ecef_origin:
                    self.origin = {
                        'lat': origin_record.lat,
                        'lon': origin_record.lon,
                        'h': origin_record.h,
                        'R': np.array(origin_record.rotation_matrix),
                        'ecef': np.array(origin_record.ecef_origin)
                    }
                    self._origin_locked_at = getattr(origin_record, 'locked_at', None)
                    self._origin_record_id = getattr(origin_record, 'id', None)
                    if getattr(origin_record, 'tracking_offset', None):
                        try:
                            self.tracking_offset_enu = self._validated_tracking_offset(origin_record.tracking_offset)
                            logger.info(f"✅ [ASYNC LOAD] Loaded tracking offset for device {self.device_id}: {self.tracking_offset_enu}")
                        except Exception as ex:
                            logger.warning(f"⚠️ Device {self.device_id}: Ignored unsafe tracking offset: {ex}")
                    self.state = "ORIGIN_LOCKED"
                    if self._restore_runtime_state(runtime_state):
                        logger.info(
                            f"✅ [ASYNC LOAD] Restored GNSS safety checkpoint for device {self.device_id}"
                        )
                    else:
                        self._needs_boot_anchor = True
                        logger.warning(
                            f"[{self._log_prefix()}] No matching GNSS safety checkpoint; "
                            "first FIXED sample will be checked against the locked zero-ENU baseline"
                        )
                    logger.info(f"✅ [ASYNC LOAD] Loaded origin for device {self.device_id}: ({origin_record.lat}, {origin_record.lon})")
                else:
                    logger.warning(f"⚠️ Device {self.device_id}: Found origin record but matrix data is missing.")
            
        except Exception as e:
            logger.error(f"❌ Device {self.device_id}: Failed to load origin from DB: {repr(e)}")
        finally:
            self._initialization_complete = True

    async def _save_origin_to_db(self):
        """✅ Lưu origin vào DB và đồng bộ vào Station Config"""
        try:
            from app.models.config import GNSSOrigin, Station
            from sqlalchemy import select, update
            from app.websocket import manager  # WebSocket manager
            
            async with self.db_session_factory() as db:
                # 1. Cập nhật bảng GNSSOrigin (dành cho Processor)
                result = await db.execute(
                    select(GNSSOrigin).where(GNSSOrigin.device_id == self.device_id)
                )
                existing = result.scalar_one_or_none()
                
                rot_matrix = self.origin['R'].tolist() if hasattr(self.origin['R'], 'tolist') else self.origin['R']
                ecef_origin = self.origin['ecef'].tolist() if hasattr(self.origin['ecef'], 'tolist') else self.origin['ecef']
                tracking_offset_list = self.tracking_offset_enu.tolist() if hasattr(self.tracking_offset_enu, 'tolist') else list(self.tracking_offset_enu)

                is_new_origin = False
                if existing:
                    # A monitoring origin is a permanent reference. Never overwrite it
                    # from a later collection/race/restart.
                    self.origin = {
                        'lat': existing.lat,
                        'lon': existing.lon,
                        'h': existing.h,
                        'R': np.array(existing.rotation_matrix),
                        'ecef': np.array(existing.ecef_origin),
                    }
                    self._origin_locked_at = existing.locked_at
                    self._origin_record_id = existing.id
                    if getattr(existing, 'tracking_offset', None) and np.all(self.tracking_offset_enu == 0.0):
                        try:
                            self.tracking_offset_enu = self._validated_tracking_offset(existing.tracking_offset)
                        except Exception as ex:
                            logger.warning(f"⚠️ Device {self.device_id}: Ignored unsafe tracking offset: {ex}")
                    self.state = "ORIGIN_LOCKED"
                    logger.warning(
                        f"[{self._log_prefix()}] Existing locked origin preserved; candidate origin discarded"
                    )
                else:
                    is_new_origin = True
                    locked_at = int(time.time())
                    self._origin_locked_at = locked_at
                    new_origin = GNSSOrigin(
                        device_id=self.device_id,
                        lat=self.origin['lat'],
                        lon=self.origin['lon'],
                        h=self.origin['h'],
                        locked_at=locked_at,
                        spread_meters=0.0,
                        num_points=len(self.origin_candidates),
                        rotation_matrix=rot_matrix,
                        ecef_origin=ecef_origin,
                        tracking_offset=tracking_offset_list
                    )
                    db.add(new_origin)
                    await db.flush()
                    self._origin_record_id = new_origin.id
                
                # 2. ✅ Đồng bộ ngược vào Station.config['gnss_origin'] (dành cho UI Admin)
                # Tìm station_id từ device_id
                from app.models.config import Device
                dev_res = await db.execute(select(Device.station_id).where(Device.id == self.device_id))
                station_id = dev_res.scalar_one_or_none()
                
                if station_id and is_new_origin:
                    st_res = await db.execute(select(Station).where(Station.id == station_id))
                    station = st_res.scalar_one_or_none()
                    if station:
                        import copy
                        from sqlalchemy.orm.attributes import flag_modified
                        new_config = copy.deepcopy(station.config) if station.config else {}
                        new_config['gnss_origin'] = {
                            'lat': self.origin['lat'],
                            'lon': self.origin['lon'],
                            'h': self.origin['h'],
                            'locked_at': int(time.time())
                        }
                        station.config = new_config
                        flag_modified(station, 'config')
                        logger.info(f"🔄 Synced origin to Station {station_id} config")

                await db.commit()
                if is_new_origin:
                    logger.info(f"💾 Saved NEW origin for device {self.device_id} to DB (first-time lock)")

                # 3. ✅ Phát tín hiệu WebSocket để UI tự động cập nhật số mới
                if station_id:
                    await manager.broadcast({
                        "type": "origin_locked_event",
                        "station_id": station_id,
                        "sensor_type": "gnss",
                        "data": {
                            'lat': self.origin['lat'],
                            'lon': self.origin['lon'],
                            'h': self.origin['h']
                        }
                    })
                
        except Exception as e:
            logger.exception(f"❌ Error saving origin to DB: {e}")

    async def relock_origin(
        self,
        *,
        station_id: Optional[int] = None,
        actor: str = "admin",
        minimum_samples: int = 61,
        minimum_duration_s: float = 60.0,
        timeout_s: float = 120.0,
        poll_interval_s: float = 0.25,
    ):
        """Replace a locked origin after collecting a stable RTK FIXED window."""
        if self.state != "ORIGIN_LOCKED" or self.origin is None:
            raise ValueError("GNSS origin is not locked")
        if getattr(self, "_origin_relock_in_progress", False):
            raise ValueError("GNSS origin relock is already in progress")
        if getattr(self, "_offset_calibration_in_progress", False):
            raise ValueError("GNSS offset calibration is already in progress")

        minimum_samples = max(2, int(minimum_samples))
        minimum_duration_s = max(0.0, float(minimum_duration_s))
        timeout_s = max(minimum_duration_s, float(timeout_s))
        poll_interval_s = max(0.01, float(poll_interval_s))
        samples = self._origin_relock_samples
        samples.clear()
        self._origin_relock_integrity_config = None
        self._origin_relock_in_progress = True

        async def broadcast_progress(phase, sample_count=0, duration_s=0.0, message=None):
            try:
                from app.websocket import manager

                await manager.broadcast({
                    "type": "gnss_origin_relock_progress",
                    "station_id": station_id,
                    "device_id": self.device_id,
                    "data": {
                        "phase": phase,
                        "sample_count": sample_count,
                        "minimum_samples": minimum_samples,
                        "duration_s": round(duration_s, 1),
                        "minimum_duration_s": minimum_duration_s,
                        "remaining_s": max(0.0, minimum_duration_s - duration_s),
                        "message": message,
                    },
                })
            except Exception as exc:
                logger.debug("GNSS origin relock progress broadcast failed: %s", exc)

        try:
            duration_s = 0.0
            pending_save = getattr(self, "_runtime_state_save_task", None)
            if pending_save is not None and pending_save is not asyncio.current_task():
                await asyncio.shield(pending_save)

            deadline = asyncio.get_running_loop().time() + timeout_s
            last_progress_second = -1
            while True:
                candidates = list(samples)
                duration_s = (
                    float(candidates[-1]["ts"] - candidates[0]["ts"])
                    if len(candidates) >= 2 else 0.0
                )
                progress_second = int(min(duration_s, minimum_duration_s))
                if progress_second != last_progress_second:
                    last_progress_second = progress_second
                    await broadcast_progress("collecting", len(candidates), duration_s)

                if len(candidates) >= minimum_samples and duration_s >= minimum_duration_s:
                    break
                if asyncio.get_running_loop().time() >= deadline:
                    raise ValueError(
                        "Timed out collecting fresh RTK FIXED samples "
                        f"({len(candidates)}/{minimum_samples} samples, "
                        f"{duration_s:.1f}/{minimum_duration_s:.1f}s)"
                    )
                await asyncio.sleep(poll_interval_s)

            positions = [sample["wgs"] for sample in candidates]
            center_lat = float(np.median([point["lat"] for point in positions]))
            center_lon = float(np.median([point["lon"] for point in positions]))
            center_h = float(np.median([point["h"] for point in positions]))
            spread_xy_m = max(
                haversine_2d(center_lat, center_lon, point["lat"], point["lon"])
                for point in positions
            )
            spread_u_m = max(abs(point["h"] - center_h) for point in positions)
            integrity_cfg = (
                getattr(self, "_origin_relock_integrity_config", None)
                or self._integrity_config({})
            )
            max_spread_xy_m = integrity_cfg["reacquire_max_spread_xy_m"]
            max_spread_u_m = integrity_cfg["reacquire_max_spread_u_m"]
            if spread_xy_m > max_spread_xy_m or spread_u_m > max_spread_u_m:
                raise ValueError(
                    "RTK FIXED samples are not stable enough "
                    f"(2D spread {spread_xy_m * 1000:.1f}mm, "
                    f"vertical spread {spread_u_m * 1000:.1f}mm)"
                )

            new_origin = {
                "lat": center_lat,
                "lon": center_lon,
                "h": center_h,
                "R": self._get_rotation_matrix(center_lat, center_lon),
                "ecef": self._gngga_to_ecef(center_lat, center_lon, center_h),
            }
            locked_at = max(int(time.time()), int(self._origin_locked_at or 0) + 1)
            history_key = f"gnss_origin_history:{self.device_id}"

            from app.models.config import Device, GNSSOrigin, GlobalConfig, Station
            from sqlalchemy import select
            from sqlalchemy.orm.attributes import flag_modified

            async with self.db_session_factory() as db:
                record_result = await db.execute(
                    select(GNSSOrigin)
                    .where(GNSSOrigin.device_id == self.device_id)
                    .with_for_update()
                )
                record = record_result.scalar_one_or_none()
                if record is None:
                    raise ValueError("No persisted GNSS origin exists for this device")

                device = await db.get(Device, self.device_id)
                if device is None or (station_id is not None and device.station_id != station_id):
                    raise ValueError("GNSS device does not belong to this station")
                station = await db.get(Station, device.station_id)
                if station is None:
                    raise ValueError("Station no longer exists")

                previous_origin = {
                    "lat": float(record.lat),
                    "lon": float(record.lon),
                    "h": float(record.h),
                    "locked_at": int(record.locked_at),
                    "tracking_offset": record.tracking_offset or [0.0, 0.0, 0.0],
                }
                history_result = await db.execute(
                    select(GlobalConfig).where(GlobalConfig.key == history_key)
                )
                history_record = history_result.scalar_one_or_none()
                history = (
                    [entry for entry in history_record.value if isinstance(entry, dict)]
                    if history_record and isinstance(history_record.value, list)
                    else []
                )
                history.append({
                    "action": "admin_relock",
                    "changed_at": locked_at,
                    "changed_by": actor,
                    "previous_origin": previous_origin,
                    "origin": {
                        "lat": center_lat,
                        "lon": center_lon,
                        "h": center_h,
                        "locked_at": locked_at,
                    },
                    "sample_count": len(candidates),
                    "duration_s": duration_s,
                    "spread_xy_m": spread_xy_m,
                    "spread_u_m": spread_u_m,
                })
                history = history[-100:]

                record.lat = center_lat
                record.lon = center_lon
                record.h = center_h
                record.locked_at = locked_at
                record.spread_meters = spread_xy_m
                record.num_points = len(candidates)
                record.rotation_matrix = new_origin["R"].tolist()
                record.ecef_origin = new_origin["ecef"].tolist()
                record.tracking_offset = [0.0, 0.0, 0.0]

                station_config = dict(station.config or {})
                station_config["gnss_origin"] = {
                    "lat": center_lat,
                    "lon": center_lon,
                    "h": center_h,
                    "locked_at": locked_at,
                    "spread_meters": spread_xy_m,
                }
                station.config = station_config
                flag_modified(station, "config")
                station.location = {
                    **(station.location or {}),
                    "lat": center_lat,
                    "lon": center_lon,
                    "h": center_h,
                    "source": "GNSS Origin",
                }
                flag_modified(station, "location")
                station.updated_at = locked_at

                if history_record:
                    history_record.value = history
                    history_record.updated_at = locked_at
                    history_record.updated_by = actor
                else:
                    db.add(GlobalConfig(
                        key=history_key,
                        value=history,
                        updated_at=locked_at,
                        updated_by=actor,
                    ))

                checkpoint_result = await db.execute(
                    select(GlobalConfig).where(
                        GlobalConfig.key == self._runtime_state_key()
                    )
                )
                checkpoint = checkpoint_result.scalar_one_or_none()
                if checkpoint:
                    await db.delete(checkpoint)
                record_id = record.id
                await db.commit()

            self.origin = new_origin
            self._origin_locked_at = locked_at
            self._origin_record_id = record_id
            self.tracking_offset_enu = np.zeros(3, dtype=float)
            self.history.clear()
            self.reacquire_candidates.clear()
            self.origin_candidates.clear()
            self._velocity_confirmation_history.clear()
            self.v_enu_state = np.zeros(3, dtype=float)
            self.v_state_ready = False
            self.disp_enu_state = np.zeros(3, dtype=float)
            self.disp_state_ready = False
            self.peak_displacement_mm = 0.0
            self._last_reacquire_ts = 0.0
            self._needs_boot_anchor = True
            self._quarantine_checkpointed = False
            self._reference_changed_at = None
            self._reference_change_source = None
            self._last_handled_reference_event_ts = None
            self._reference_transition = None
            self._shift_started_at = None
            self._consecutive_rejects = 0
            self._last_origin_candidate_ts = None
            self.last_process_time = 0
            samples.clear()

            from app.websocket import manager
            try:
                await manager.broadcast({
                    "type": "origin_locked_event",
                    "station_id": station_id,
                    "sensor_type": "gnss",
                    "data": {
                        "lat": center_lat,
                        "lon": center_lon,
                        "h": center_h,
                        "relocked": True,
                        "previous_origin": previous_origin,
                    },
                })
            except Exception as exc:
                logger.warning("GNSS origin relock broadcast failed: %s", exc)
            await broadcast_progress("complete", len(candidates), duration_s)
            logger.info(
                "[%s] GNSS origin relocked by %s: (%s, %s, %s), %s samples, spread %.3f/%.3f m",
                self._log_prefix(), actor, center_lat, center_lon, center_h,
                len(candidates), spread_xy_m, spread_u_m,
            )
            return {
                "device_id": self.device_id,
                "previous_origin": previous_origin,
                "origin": {"lat": center_lat, "lon": center_lon, "h": center_h},
                "sample_count": len(candidates),
                "duration_s": duration_s,
                "spread_xy_mm": spread_xy_m * 1000.0,
                "spread_u_mm": spread_u_m * 1000.0,
                "locked_at": locked_at,
            }
        except Exception as exc:
            duration_s = (
                float(samples[-1]["ts"] - samples[0]["ts"])
                if len(samples) >= 2 else 0.0
            )
            await broadcast_progress("failed", len(samples), duration_s, str(exc))
            raise
        finally:
            self._origin_relock_in_progress = False
            samples.clear()

    async def _async_save_tracking_offset(self, offset=None):
        """Persist current tracking_offset to DB without modifying origin coordinates."""
        try:
            from app.models.config import GNSSOrigin
            from sqlalchemy import select
            
            offset_value = np.asarray(
                self.tracking_offset_enu if offset is None else offset,
                dtype=float,
            )

            async with self.db_session_factory() as db:
                result = await db.execute(
                    select(GNSSOrigin).where(GNSSOrigin.device_id == self.device_id)
                )
                existing = result.scalar_one_or_none()
                if existing:
                    existing.tracking_offset = offset_value.tolist()
                    await db.commit()
                    logger.info(f"💾 Persisted updated tracking offset for device {self.device_id} to DB: {offset_value}")
                    return True
                return False
        except Exception as e:
            logger.exception(f"❌ Error persisting tracking offset for device {self.device_id}: {e}")
            return False

    async def recalibrate_tracking_offset(
        self,
        *,
        station_id: Optional[int] = None,
        minimum_samples: int = 61,
        minimum_duration_s: float = 60.0,
        timeout_s: float = 120.0,
        poll_interval_s: float = 0.25,
    ):
        """Collect a fresh stable FIXED window and re-zero displacement.

        During quarantine, samples are deliberately excluded from ``history``.
        A manual calibration therefore uses a short-lived capture buffer filled
        by ``_handle_processing`` while this method is waiting.
        """
        if self.state != "ORIGIN_LOCKED" or self.origin is None:
            raise ValueError("GNSS origin is not locked")
        if getattr(self, "_origin_relock_in_progress", False):
            raise ValueError("GNSS origin relock is already in progress")
        if getattr(self, "_offset_calibration_in_progress", False):
            raise ValueError("GNSS offset calibration is already in progress")

        minimum_samples = max(2, int(minimum_samples))
        minimum_duration_s = max(0.0, float(minimum_duration_s))
        timeout_s = max(minimum_duration_s, float(timeout_s))
        poll_interval_s = max(0.01, float(poll_interval_s))
        started_after_ts = float(self.history[-1]["ts"]) if self.history else -math.inf
        old_offset = self.tracking_offset_enu.copy()
        capture_buffer = getattr(self, "_offset_calibration_samples", None)
        if capture_buffer is None:
            capture_buffer = deque(maxlen=600)
            self._offset_calibration_samples = capture_buffer
        capture_buffer.clear()
        deadline = asyncio.get_running_loop().time() + timeout_s
        self._offset_calibration_in_progress = True
        last_progress_second = -1
        used_capture_samples = False
        try:
            while True:
                captured_samples = list(capture_buffer)
                used_capture_samples = bool(captured_samples)
                samples = captured_samples or [
                    sample for sample in self.history
                    if float(sample["ts"]) > started_after_ts
                ]
                duration_s = (
                    float(samples[-1]["ts"] - samples[0]["ts"])
                    if len(samples) >= 2
                    else 0.0
                )
                progress_second = int(min(duration_s, minimum_duration_s))
                if progress_second != last_progress_second:
                    last_progress_second = progress_second
                    progress = {
                        "type": "gnss_offset_calibration_progress",
                        "station_id": station_id,
                        "device_id": self.device_id,
                        "data": {
                            "phase": "collecting",
                            "sample_count": len(samples),
                            "minimum_samples": minimum_samples,
                            "duration_s": round(duration_s, 1),
                            "minimum_duration_s": minimum_duration_s,
                            "remaining_s": max(0.0, minimum_duration_s - duration_s),
                        },
                    }
                    logger.info(
                        "[GNSS CALIBRATION] device=%s station=%s samples=%s/%s duration=%.1fs/%.1fs",
                        self.device_id,
                        station_id,
                        len(samples),
                        minimum_samples,
                        duration_s,
                        minimum_duration_s,
                    )
                    try:
                        from app.websocket import manager
                        await manager.broadcast(progress)
                    except Exception as exc:
                        logger.debug("GNSS calibration progress broadcast failed: %s", exc)
                if (
                    len(samples) >= minimum_samples
                    and duration_s >= minimum_duration_s
                ):
                    break
                if asyncio.get_running_loop().time() >= deadline:
                    raise ValueError(
                        "Timed out collecting fresh RTK FIXED samples "
                        f"({len(samples)}/{minimum_samples} samples, "
                        f"{duration_s:.1f}/{minimum_duration_s:.1f}s)"
                    )
                await asyncio.sleep(poll_interval_s)
        finally:
            self._offset_calibration_in_progress = False
            capture_buffer.clear()

        if not np.allclose(self.tracking_offset_enu, old_offset):
            raise ValueError("GNSS tracking reference changed during calibration; retry")

        positions = np.asarray([sample["pos_enu"] for sample in samples], dtype=float)
        center = np.median(positions, axis=0)
        residuals = positions - center
        spread_2d_m = float(np.max(np.linalg.norm(residuals[:, :2], axis=1)))
        spread_u_m = float(np.max(np.abs(residuals[:, 2])))
        config = self._integrity_config({})
        if (
            spread_2d_m > float(config["reacquire_max_spread_xy_m"])
            or spread_u_m > float(config["reacquire_max_spread_u_m"])
        ):
            raise ValueError(
                "RTK FIXED samples are not stable enough "
                f"(2D spread {spread_2d_m * 1000:.1f}mm, "
                f"vertical spread {spread_u_m * 1000:.1f}mm)"
            )

        proposed_offset = self._validated_tracking_offset(old_offset + center)
        if not await self._async_save_tracking_offset(proposed_offset):
            raise RuntimeError("Could not persist GNSS tracking offset")

        self.tracking_offset_enu = proposed_offset
        if used_capture_samples:
            # Quarantined samples never entered trusted history. Replace the
            # stale pre-shift anchor with their re-zeroed window so the first
            # post-calibration FIXED sample is accepted instead of creating a
            # synthetic jump back from ``-center``.
            self.history.clear()
            self.history.extend({
                "ts": sample["ts"],
                "pos_enu": np.asarray(sample["pos_enu"], dtype=float) - center,
            } for sample in samples)
        else:
            for sample in self.history:
                sample["pos_enu"] = np.asarray(sample["pos_enu"], dtype=float) - center

        calibrated_positions = np.asarray(
            [sample["pos_enu"] for sample in samples],
            dtype=float,
        )
        try:
            from app.websocket import manager
            completion_message = {
                "type": "gnss_offset_calibration_progress",
                "station_id": station_id,
                "device_id": self.device_id,
                "data": {
                    "phase": "complete",
                    "sample_count": len(samples),
                    "duration_s": round(duration_s, 1),
                    "remaining_s": 0.0,
                },
            }
            # Do not hold the HTTP calibration response on a stale browser socket.
            asyncio.create_task(manager.broadcast(completion_message))
        except Exception as exc:
            logger.debug("GNSS calibration completion broadcast failed: %s", exc)
        # Keep the newest measured residual; never synthesize a zero payload.
        self.disp_enu_state = calibrated_positions[-1].copy()
        self.disp_state_ready = True
        self._velocity_confirmation_history = deque(maxlen=120)
        self.last_significant_motion_ts = 0.0
        self.peak_displacement_mm = float(np.linalg.norm(self.disp_enu_state[:2]) * 1000.0)
        self._reference_transition = None
        self._consecutive_rejects = 0
        self.reacquire_candidates.clear()
        self._quarantine_checkpointed = False
        self._schedule_runtime_state_save(force=True)
        runtime_save_task = getattr(self, "_runtime_state_save_task", None)
        if runtime_save_task is not None:
            await asyncio.shield(runtime_save_task)

        return {
            "device_id": self.device_id,
            "sample_count": len(samples),
            "duration_s": duration_s,
            "spread_2d_mm": spread_2d_m * 1000.0,
            "spread_u_mm": spread_u_m * 1000.0,
            "shift_e_m": float(center[0]),
            "shift_n_m": float(center[1]),
            "shift_u_m": float(center[2]),
            "old_tracking_offset": old_offset.tolist(),
            "new_tracking_offset": proposed_offset.tolist(),
            "new_tracking_offset_2d_mm": float(
                np.linalg.norm(proposed_offset[:2]) * 1000.0
            ),
            "origin_unchanged": True,
        }
