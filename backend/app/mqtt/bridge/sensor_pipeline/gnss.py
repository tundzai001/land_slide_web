"""GNSS payload parsing and adjustment ingestion."""

from __future__ import annotations

import logging
from typing import Any

from app.websocket import manager

logger = logging.getLogger(__name__)


class GnssPayloadMixin:
    def _monitoring_paused_for_adjustment(self, project_id: int, station_id: int) -> bool:
        contexts = getattr(self, "adjustment_run_contexts", {})
        for run_id, session in self.round_robin_manager._sessions.items():
            # Seed handover changes correction sources before the public phase
            # exists. A failed restore keeps its snapshot and remains paused.
            if (self.adjustment_phase.get(run_id) not in {"STARTING", "COLLECTING_BASELINE", "FREE_NETWORK", "PAUSED"}
                    and not session.get("seed_topology_snapshots")):
                continue
            context = contexts.get(run_id) or {}
            if int(context.get("project_id") or session.get("monitoring_project_id") or run_id) != int(project_id):
                continue
            if any(
                int(station_id) in cluster.get("stations", ())
                for cluster in session.get("clusters", ())
            ):
                return True
        return False

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
        processed_data = None
        try:
            proj_id = int(info.get("project_id") or info.get("station_id") or 0)

            phase = self.adjustment_phase.get(proj_id)

            if proj_id not in self.round_robin_manager._sessions:
                phase = None

            has_pending_agrica = self.round_robin_manager.has_pending_agrica_fragment(
                proj_id,
                station_id,
            )

            if "#AGRICA" in raw_payload or has_pending_agrica:
                # AGRICA is collected only while an operator has started an
                # adjustment session.  A single BASE->Rover observation is
                # not a completed network adjustment.
                valid_obs = []
                if phase in {"COLLECTING_BASELINE", "FREE_NETWORK"}:
                    valid_obs = self.round_robin_manager.add_agrica_payload(raw_payload, info)
                    seed_status = None
                    if phase == "COLLECTING_BASELINE":
                        seed_status = self.round_robin_manager.get_seed_collection_status(proj_id)
                        if seed_status["fallback_ready"]:
                            seed_status = self.round_robin_manager.skip_missing_seed_stations(proj_id)
                        seed_progress_parts = []
                        for cluster_status in seed_status.get("clusters") or ():
                            rolling_by_station = (
                                cluster_status.get("rolling_stability_by_station") or {}
                            )
                            open_by_station = (
                                cluster_status.get("solver_window_open_by_station") or {}
                            )
                            count_by_station = (
                                cluster_status.get("solver_sample_counts_by_station") or {}
                            )
                            duration_by_station = (
                                cluster_status.get("solver_durations_by_station_seconds") or {}
                            )
                            warmup_count_by_station = (
                                cluster_status.get("sample_counts_by_station") or {}
                            )
                            warmup_duration_by_station = (
                                cluster_status.get("durations_by_station_seconds") or {}
                            )
                            reset_by_station = (
                                cluster_status.get("solver_window_reset_counts_by_station") or {}
                            )
                            drift_by_station = (
                                cluster_status.get("solver_drift_failure_counts_by_station") or {}
                            )
                            for waiting_station_id in (
                                cluster_status.get("warming_station_ids") or ()
                            ):
                                rolling = (
                                    rolling_by_station.get(waiting_station_id)
                                    or rolling_by_station.get(str(waiting_station_id))
                                    or {}
                                )
                                delta = rolling.get("delta_neu_m")
                                if delta and len(delta) == 3:
                                    delta_text = (
                                        "dN/E/U="
                                        f"{float(delta[0]) * 1000:.1f}/"
                                        f"{float(delta[1]) * 1000:.1f}/"
                                        f"{float(delta[2]) * 1000:.1f}mm"
                                    )
                                else:
                                    delta_text = (
                                        f"waiting for two {seed_status.get('stability_window_seconds', 10)}s windows"
                                    )
                                is_open = bool(
                                    open_by_station.get(waiting_station_id)
                                    or open_by_station.get(str(waiting_station_id))
                                )
                                if is_open:
                                    state_text = (
                                        "solver="
                                        f"{int(count_by_station.get(waiting_station_id, count_by_station.get(str(waiting_station_id), 0)) or 0)}/"
                                        f"{int(seed_status.get('solver_min_distinct_epochs') or 0)} epochs, "
                                        f"{int(duration_by_station.get(waiting_station_id, duration_by_station.get(str(waiting_station_id), 0)) or 0)}/"
                                        f"{int(seed_status.get('solver_min_duration_seconds') or 0)}s"
                                    )
                                else:
                                    state_text = (
                                        "fixed-base warm-up="
                                        f"{int(warmup_count_by_station.get(waiting_station_id, warmup_count_by_station.get(str(waiting_station_id), 0)) or 0)}/"
                                        f"{int(seed_status.get('seed_warmup_min_distinct_epochs') or 0)} epochs, "
                                        f"{int(warmup_duration_by_station.get(waiting_station_id, warmup_duration_by_station.get(str(waiting_station_id), 0)) or 0)}/"
                                        f"{int(seed_status.get('seed_warmup_min_duration_seconds') or 0)}s"
                                    )
                                reset_count = int(
                                    reset_by_station.get(
                                        waiting_station_id,
                                        reset_by_station.get(str(waiting_station_id), 0),
                                    ) or 0
                                )
                                drift_count = int(
                                    drift_by_station.get(
                                        waiting_station_id,
                                        drift_by_station.get(str(waiting_station_id), 0),
                                    ) or 0
                                )
                                seed_progress_parts.append(
                                    f"ID {waiting_station_id}: {state_text}, {delta_text}, "
                                    f"resets={reset_count}, rolling-advisory-strikes={drift_count}"
                                )
                        if seed_status.get("stability_timeout"):
                            phase = "ERROR"
                            await self._handle_round_robin_adjustment_error(
                                proj_id,
                                (
                                    "Fixed-base baselines did not produce a complete "
                                    "time-based stable solver window within "
                                    f"{seed_status['stability_timeout_seconds']}s. "
                                    "No network solution was published. Last station state: "
                                    f"{' | '.join(seed_progress_parts) or 'no rolling diagnostics'}"
                                ),
                            )
                    diagnostic = self.round_robin_manager.get_last_ingest_diagnostic(proj_id)
                    if diagnostic:
                        if seed_status:
                            diagnostic = {**diagnostic, "seed_status": seed_status}
                        if seed_status and (
                            seed_status["missing_station_ids"]
                            or seed_status.get("warming_station_ids")
                        ):
                            waiting_parts = []
                            if seed_status["missing_station_ids"]:
                                silent_ids = seed_status.get("silent_station_ids") or []
                                invalid_fix_ids = seed_status.get("invalid_fix_station_ids") or []
                                if silent_ids:
                                    waiting_parts.append(
                                        "no AGRICA station IDs "
                                        f"{silent_ids}"
                                    )
                                if invalid_fix_ids:
                                    position_type_parts = []
                                    for item in seed_status.get("clusters") or ():
                                        position_types = (
                                            item.get("latest_position_type_by_station") or {}
                                        )
                                        for invalid_station_id in invalid_fix_ids:
                                            value = position_types.get(
                                                invalid_station_id,
                                                position_types.get(str(invalid_station_id)),
                                            )
                                            if value is not None:
                                                position_type_parts.append(
                                                    f"ID {invalid_station_id}=type {value}"
                                                )
                                    waiting_parts.append(
                                        "AGRICA not RTK Fixed: "
                                        + (", ".join(dict.fromkeys(position_type_parts))
                                           or str(invalid_fix_ids))
                                    )
                            if seed_status.get("warming_station_ids"):
                                waiting_parts.append(
                                    " | ".join(seed_progress_parts)
                                    or "stations still building a stable seed window "
                                    f"{seed_status['warming_station_ids']}"
                                )
                            diagnostic = {
                                **diagnostic,
                                "message": (
                                    f"{diagnostic['message']} "
                                    f"Offline discovery {seed_status['step_count']}/{seed_status['max_steps']}; "
                                    f"waiting for {'; '.join(waiting_parts)}."
                                ),
                            }
                        diagnostic_message = str(diagnostic.get("message") or "")
                        is_fragment_update = diagnostic_message.startswith("Buffered AGRICA fragment")
                        should_broadcast_diagnostic = (
                            not is_fragment_update
                            or self._diag_should_log(
                                f"gnss_adjustment_fragment:{proj_id}:{station_id}",
                                2,
                            )
                        )
                        if should_broadcast_diagnostic:
                            await manager.broadcast({
                                "type": "gnss_adjustment_debug",
                                "project_id": public_project_id,
                                "run_id": proj_id,
                                "cluster_name": (self.adjustment_run_contexts.get(proj_id) or {}).get("cluster_name"),
                                **diagnostic,
                            })
                    for obs in valid_obs:
                        try:
                            baseline_from = self.round_robin_manager.get_active_base_for_station(
                                proj_id,
                                station_id,
                            )
                            await manager.broadcast({
                                "type": "gnss_baseline_collected",
                                "project_id": public_project_id,
                                "run_id": proj_id,
                                "cluster_name": (self.adjustment_run_contexts.get(proj_id) or {}).get("cluster_name"),
                                "station_id": station_id,
                                "from": baseline_from,
                                "rover_name": obs.rover_name,
                                "baseline_neu": obs.baseline_neu,
                                "std_neu": obs.std_neu,
                                "rover_llh": obs.rover_llh,
                                "base_llh": obs.base_llh,
                                "full_data": obs.full_data,
                            })
                        except Exception as exc:
                            logger.exception("Could not broadcast GNSS baseline: %s", exc)

                    if (
                        phase == "COLLECTING_BASELINE"
                        and self.round_robin_manager.has_complete_seed_observations(proj_id)
                    ):
                        skipped_station_ids = (seed_status or {}).get("skipped_station_ids", [])
                        active_session = (
                            self.round_robin_manager._sessions.get(proj_id) or {}
                        )
                        expected_station_ids = sorted({
                            int(station_id)
                            for cluster in active_session.get("clusters") or ()
                            for station_id in cluster.get("stations") or ()
                        })
                        roster = getattr(self, "adjustment_run_rosters", {}).get(proj_id) or {}
                        roster["participating_station_ids"] = expected_station_ids
                        roster["skipped_seed_station_ids"] = sorted({
                            *roster.get("skipped_seed_station_ids", []),
                            *skipped_station_ids,
                        })
                        if hasattr(self, "adjustment_run_rosters"):
                            self.adjustment_run_rosters[proj_id] = roster
                        self.adjustment_phase[proj_id] = "FREE_NETWORK"
                        if proj_id in self.adjustment_run_contexts:
                            self.adjustment_run_contexts[proj_id]["status"] = "FREE_NETWORK"
                        await manager.broadcast({
                            "type": "gnss_adjustment_progress",
                            "project_id": public_project_id,
                            "run_id": proj_id,
                            "cluster_name": (self.adjustment_run_contexts.get(proj_id) or {}).get("cluster_name"),
                            "phase": "FREE_NETWORK",
                            "expected_station_ids": expected_station_ids,
                            "roster": roster,
                            "message": (
                                "Skipped offline/degraded station IDs "
                                f"{skipped_station_ids} after {self.round_robin_manager.SEED_COLLECTION_MAX_STEPS} seed steps. "
                                "Starting Round-Robin with the remaining rovers."
                                if skipped_station_ids
                                else (
                                    "All selected rovers completed the fixed-base seed window "
                                    f"({self.round_robin_manager.SEED_SOLVER_MIN_DURATION_SECONDS}s "
                                    "stationary solver data each). Starting Round-Robin."
                                )
                            ),
                        })
                        # The Round-Robin manager has already identified and locked
                        # the actual primary/backup fixed-base service from AGRICA.
                        # Never stop the persisted primary mountpoint here: it may be
                        # offline while a backup station is feeding that mountpoint.
                        # The manager snapshots, sleeps and restores the selected
                        # CORS service atomically inside start_cycle().
                        await self.round_robin_manager.start_cycle(proj_id)

            if adjustment_only:
                return

            import re

            if re.search(r'\$G[NP]GGA,', raw_payload):
                if self._monitoring_paused_for_adjustment(public_project_id, station_id):
                    res = {
                        "type": "gnss_status",
                        "status": "ADJUSTMENT_IN_PROGRESS",
                        "message": "GNSS monitoring paused while correction source changes for adjustment",
                        "data": {
                            "integrity_state": "ADJUSTMENT_IN_PROGRESS",
                            "position_quality_reliable": False,
                        },
                    }
                else:
                    res = processor.process_gngga(raw_payload, station_config)
                if res is None and getattr(processor, "_origin_relock_in_progress", False):
                    await self._touch_online_heartbeat(device_id, station_id, current_timestamp)
                    try:
                        await self._touch_active_alert(
                            station_id,
                            'gnss_velocity',
                            current_timestamp,
                        )
                    except Exception as touch_error:
                        logger.exception(f"❌ GNSS active-alert refresh during origin relock failed: {touch_error}")

                    status_payload = {
                        "status": "ORIGIN_RELOCK_COLLECTING",
                        "fix_quality": getattr(processor, "min_fix_quality", 4),
                        "message": "Collecting stable RTK FIXED samples to replace the monitoring origin",
                        "data": {
                            "integrity_state": "ORIGIN_RELOCK_COLLECTING",
                            "position_quality_reliable": False,
                        },
                    }
                    try:
                        await self._upsert_latest_sensor_cache(
                            station_id, 'gnss', current_timestamp, status_payload
                        )
                        await manager.broadcast({
                            "type": "sensor_status",
                            "project_id": public_project_id,
                            "station_id": station_id,
                            "sensor_type": "gnss",
                            "timestamp": current_timestamp,
                            "data": status_payload,
                        })
                    except Exception as ws_e:
                        logger.exception(f"❌ GNSS origin relock status update failed: {ws_e}")
                    return
                if res and res.get('type') == 'gnss_processed':
                    processed_data = res.get('data')

                    # Cập nhật LLH cache cho RoundRobin
                    station_code = info.get("station_code")
                    lat = processed_data.get('latitude')
                    lon = processed_data.get('longitude')
                    alt = processed_data.get('altitude', 0.0)
                    if lat is not None and lon is not None:
                        self.round_robin_manager.update_rover_llh(station_code, lat, lon, alt)
                elif res and res.get('type') == 'gnss_status':
                    status_payload = {
                        "status": res.get('status'),
                        "sub_status": res.get('sub_status'),
                        "fix_quality": res.get('fix_quality'),
                        "fix_mode": res.get('fix_mode'),
                        "message": res.get('message'),
                        "raw_payload": res.get('raw_payload', ''),
                        "data": res.get('data'),
                    }

                    if res.get('status') in {
                        'INITIALIZING', 'VELOCITY_WARMUP', 'INVALID_DATA',
                        'UNVERIFIED_POSITION_SHIFT', 'UNTRUSTED_GEOMETRY',
                        'PERSISTENT_OFFSET_QUARANTINED', 'REJECTED_MEASUREMENT',
                        'UNSTABLE_FIX', 'REFERENCE_CHANGE_PENDING', 'REFERENCE_TRANSITION',
                        'STALE_REFERENCE', 'REACQUIRE_REFUSED',
                        'CHECKSUM_FAILED', 'NO_DATA', 'ADJUSTMENT_IN_PROGRESS',
                    }:
                        # Keep an existing unresolved GNSS alert alive
                        # while the processor is quarantined/warming up;
                        # this is not a safe reading and must not expire
                        # merely because the service restarted.
                        try:
                            await self._touch_active_alert(
                                station_id,
                                'gnss_velocity',
                                current_timestamp,
                            )
                        except Exception as touch_error:
                            logger.exception(f"❌ GNSS active-alert refresh failed: {touch_error}")
                        # Immediate buffering for anomalies can be disabled
                        # per station without stopping processing or alerts.
                        if (res.get('status') != 'ADJUSTMENT_IN_PROGRESS'
                                and self._is_processing_storage_enabled(station_config)):
                            anomaly_record = {
                                "station_id": station_id,
                                "timestamp": current_timestamp,
                                "sensor_type": "gnss_anomaly",
                                "ingest_id": self._make_ingest_id(
                                    device_id,
                                    station_id,
                                    "gnss_anomaly",
                                    current_timestamp,
                                    status_payload,
                                    raw_payload,
                                ),
                                "data": status_payload,
                                "value_1": None, "value_2": None, "value_3": None, "value_4": None, "value_5": None
                            }
                            async with self._buffer_lock:
                                self._sensor_buffer.append(anomaly_record)

                    try:
                        await self._upsert_latest_sensor_cache(station_id, 'gnss', current_timestamp, status_payload)
                    except Exception: pass
                    try:
                        await manager.broadcast({
                            "type": "sensor_status",
                            "project_id": public_project_id,
                            "station_id": station_id,
                            "sensor_type": "gnss",
                            "timestamp": current_timestamp,
                            "data": status_payload
                        })
                    except Exception as ws_e:
                        logger.exception(f"❌ WS GNSS status error: {ws_e}")
                    return
                elif res and res.get('type') == 'origin_locked':
                    logger.info(f"🎯 [{station_name}] GNSS Origin locked")
                    try:
                        await self._upsert_latest_sensor_cache(station_id, 'gnss', current_timestamp, res.get('data', {}))
                    except Exception: pass
                    return
                elif res and res.get('type') == 'origin_status':
                    status_payload = {
                        "status": res.get('status'),
                        "fix_quality": res.get('fix_quality'),
                        "fix_mode": res.get('fix_mode'),
                        "message": res.get('message')
                    }
                    try:
                        await self._upsert_latest_sensor_cache(station_id, 'gnss', current_timestamp, status_payload)
                    except Exception: pass
                    try:
                        await manager.broadcast({
                            "type": "sensor_status",
                            "project_id": public_project_id,
                            "station_id": station_id,
                            "sensor_type": "gnss",
                            "timestamp": current_timestamp,
                            "data": status_payload
                        })
                    except Exception as ws_e:
                        logger.exception(f"❌ WS GNSS origin status error: {ws_e}")
                    return
        except Exception as e:
            logger.exception(f"Processing error ({sensor_type}): {e}")
            return None
        return processed_data
