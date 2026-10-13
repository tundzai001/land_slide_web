"""Adjustment result, progress, and failure callbacks for MQTT."""

import logging
import time
from collections import defaultdict

from app.features.gnss_adjustment.store import (
    add_report_links,
    compact_adjustment_payload,
    persist_evidence,
    write_adjustment_failure_report,
)
from app.websocket import manager

logger = logging.getLogger(__name__)


class MQTTAdjustmentMixin:
    def _handle_gnss_reference_change(self, cluster: dict, timestamp: float, source: str):
        """Forward confirmed CORS operations to the affected monitoring devices."""
        station_ids = set()
        station_codes = set()
        for value in cluster.get("stations", []):
            try:
                station_ids.add(int(value))
            except (TypeError, ValueError):
                station_codes.add(str(value).strip())
        project_id = cluster.get("project_id")
        notified = set()
        for info in self.topic_map.values():
            if (
                info.get("type") != "gnss"
                or (
                    int(info.get("station_id") or 0) not in station_ids
                    and str(info.get("station_code") or "").strip() not in station_codes
                )
                or (project_id is not None and int(info.get("project_id") or 0) != int(project_id))
            ):
                continue
            processor = info.get("processor")
            if processor is not None and id(processor) not in notified:
                processor.mark_reference_changed(timestamp=timestamp, source=source)
                notified.add(id(processor))

    def _adjustment_run_context(self, run_id: int) -> dict:
        if not hasattr(self, "adjustment_run_contexts"):
            self.adjustment_run_contexts = {}
        if not hasattr(self, "adjustment_cluster_results"):
            self.adjustment_cluster_results = defaultdict(dict)
        context = dict(self.adjustment_run_contexts.get(int(run_id)) or {})
        context.setdefault("run_id", int(run_id))
        context.setdefault("project_id", int(run_id))
        context.setdefault("project_code", "")
        context.setdefault("cluster_name", "Cụm")
        self.adjustment_run_contexts.setdefault(int(run_id), context)
        self.adjustment_cluster_results.setdefault(int(context["project_id"]), {})
        return context

    def _refresh_project_adjustment_state(self, project_id: int) -> tuple[str, dict]:
        contexts = [
            context
            for context in self.adjustment_run_contexts.values()
            if int(context.get("project_id") or 0) == int(project_id)
        ]
        active = [
            context for context in contexts
            if context.get("status") in {"STARTING", "COLLECTING_BASELINE", "FREE_NETWORK", "PAUSED"}
        ]
        if active:
            statuses = {context.get("status") for context in active}
            phase = "PAUSED" if statuses == {"PAUSED"} else (
                "FREE_NETWORK" if "FREE_NETWORK" in statuses else "COLLECTING_BASELINE"
            )
        else:
            terminal = {str(context.get("status") or "") for context in contexts}
            failed = terminal.intersection({"ERROR", "FAILED_QUALITY_GATE"})
            completed = "COMPLETED" in terminal
            phase = "PARTIAL_FAILED" if failed and completed else (
                "FAILED_QUALITY_GATE" if terminal == {"FAILED_QUALITY_GATE"} else (
                    "ERROR" if failed else "COMPLETED"
                )
            )
        self.adjustment_phase[int(project_id)] = phase
        results = self.adjustment_cluster_results.get(int(project_id), {})
        ordered_results = sorted(
            results.values(),
            key=lambda item: (
                item.get("cluster_index") is None,
                int(item.get("cluster_index") or 0),
                str(item.get("cluster_name") or ""),
            ),
        )
        latest = ordered_results[-1] if ordered_results else {}
        summary = {
            **latest,
            "project_id": int(project_id),
            "phase": phase,
            "cluster_results": ordered_results,
        }
        if ordered_results:
            self.adjustment_results[int(project_id)] = summary
        return phase, summary

    async def _handle_round_robin_adjustment_result(self, project_id: int, adjustment: dict):
        """Always persist audit reports; publish coordinates only after quality PASS."""
        run_id = int(project_id)
        run_context = self._adjustment_run_context(run_id)
        public_project_id = int(run_context["project_id"])
        cluster_name = str(
            adjustment.get("cluster_name")
            or run_context.get("cluster_name")
            or "Cụm"
        )
        adjustment["project_id"] = public_project_id
        adjustment["project_code"] = (
            adjustment.get("project_code") or run_context.get("project_code")
        )
        adjustment["cluster_name"] = cluster_name
        if run_context.get("cluster_index") is not None:
            adjustment["cluster_index"] = int(run_context["cluster_index"])
        adjustment["run_id"] = run_id
        current_timestamp = int(time.time())
        adjustment, evidence = compact_adjustment_payload(adjustment)
        cluster_index = int(adjustment.get("cluster_index", -1))
        # Scheduler run IDs are reused for every cycle. Keep a stable token
        # within this session while giving the next cycle a distinct key.
        run_token = run_context.setdefault("started_at_ns", time.time_ns())
        self.adjustment_run_contexts[run_id]["started_at_ns"] = run_token
        adjustment_key = f"run:{public_project_id}:{cluster_index}:{run_id}:{run_token}"
        adjustment["adjustment_key"] = adjustment_key
        adjustment = add_report_links(
            adjustment,
            project_id=public_project_id,
            timestamp=current_timestamp,
        )
        try:
            await persist_evidence(
                evidence,
                adjustment_key=adjustment_key,
                project_id=public_project_id,
                cluster_index=cluster_index,
                timestamp=current_timestamp,
            )
        except Exception as exc:
            message = f"Bình sai đã tính xong nhưng không thể lưu bằng chứng GNSS: {exc}"
            logger.error("Project %s run %s: %s", public_project_id, run_id, message, exc_info=True)
            await self._handle_round_robin_adjustment_error(run_id, message)
            return
        quality_gate = adjustment.get("quality_gate") or {}
        if not bool(quality_gate.get("passed")):
            reasons = "; ".join(quality_gate.get("reasons") or [])
            message = (
                "Bình sai đã tạo hồ sơ audit nhưng không đạt quality gate; "
                "không lưu/publish tọa độ chính thức. "
                f"{reasons or 'quality gate failed'}"
            )
            self.adjustment_phase[run_id] = "FAILED_QUALITY_GATE"
            self.adjustment_message[run_id] = message
            self.adjustment_run_contexts[run_id]["status"] = "FAILED_QUALITY_GATE"
            self.adjustment_cluster_results[public_project_id][run_id] = adjustment
            station_id = next(
                (
                    int(point.get("station_id"))
                    for point in (adjustment.get("points") or {}).values()
                    if point.get("station_id")
                ),
                0,
            )
            async with self._buffer_lock:
                self._sensor_buffer.append({
                    "station_id": station_id,
                    "timestamp": current_timestamp,
                    "sensor_type": "gnss_adjustment_failed",
                    "ingest_id": self._make_ingest_id(
                        0,
                        station_id,
                        "gnss_adjustment_failed",
                        current_timestamp,
                        adjustment,
                    ),
                    "adjustment_key": adjustment_key,
                    "adjustment_project_id": public_project_id,
                    "adjustment_cluster_index": cluster_index,
                    "data": adjustment,
                    "value_1": None,
                    "value_2": None,
                    "value_3": None,
                    "value_4": None,
                    "value_5": None,
                })
            phase, summary = self._refresh_project_adjustment_state(public_project_id)
            await manager.broadcast({
                "type": "gnss_adjustment_progress",
                "project_id": public_project_id,
                "run_id": run_id,
                "cluster_name": cluster_name,
                "phase": phase,
                "message": f"{cluster_name}: {message}",
                "timestamp": current_timestamp,
                "data": summary,
            })
            return
        interpretation_status = str(
            quality_gate.get("interpretation_status") or "PASS"
        )
        completed_message = (
            "Connected GNSS network adjustment completed with diagnostic warnings."
            if interpretation_status == "PASS_WITH_WARNINGS" else
            "Connected GNSS network adjustment completed."
        )
        self.adjustment_phase[run_id] = "COMPLETED"
        self.adjustment_message[run_id] = completed_message
        self.adjustment_run_contexts[run_id]["status"] = "COMPLETED"
        self.adjustment_cluster_results[public_project_id][run_id] = adjustment
        phase, summary = self._refresh_project_adjustment_state(public_project_id)
        self.adjustment_message[public_project_id] = f"{cluster_name}: {completed_message}"

        representative_pending = True
        for point in adjustment.get("points", {}).values():
            station_id = point.get("station_id")
            if not station_id:
                continue
            adjustment_project_id = None
            adjustment_cluster_index = None
            if representative_pending:
                row_adjustment_key = adjustment_key
                adjustment_project_id = public_project_id
                adjustment_cluster_index = cluster_index
                representative_pending = False
                stored_data = adjustment
            else:
                # Keep one complete network result; station history only needs
                # the point belonging to that station.
                stored_data = {
                    "type": "gnss_adjusted_station",
                    "adjustment_key": adjustment_key,
                    "project_id": public_project_id,
                    "cluster_index": cluster_index,
                    "point": point,
                }
                row_adjustment_key = None
            payload = {
                "station_id": station_id,
                "timestamp": current_timestamp,
                "sensor_type": "gnss_adjusted",
                "ingest_id": self._make_ingest_id(
                    0, station_id, "gnss_adjusted", current_timestamp, adjustment
                ),
                "adjustment_key": row_adjustment_key,
                "adjustment_project_id": adjustment_project_id,
                "adjustment_cluster_index": adjustment_cluster_index,
                "data": stored_data,
                "value_1": None,
                "value_2": None,
                "value_3": None,
                "value_4": None,
                "value_5": None,
            }
            async with self._buffer_lock:
                self._sensor_buffer.append(payload)
            try:
                await self._upsert_latest_sensor_cache(
                    station_id,
                    "gnss_adjusted",
                    current_timestamp,
                    stored_data,
                )
                await manager.broadcast({
                    "type": "sensor_status",
                    "station_id": station_id,
                    "sensor_type": "gnss_adjusted",
                    "timestamp": current_timestamp,
                    "data": adjustment,
                })
            except Exception as exc:
                logger.error("Could not publish GNSS adjustment for station %s: %s", station_id, exc)

        await manager.broadcast({
            "type": "gnss_adjustment_progress",
            "project_id": public_project_id,
            "run_id": run_id,
            "cluster_name": cluster_name,
            "phase": phase,
            "message": f"{cluster_name}: {completed_message}",
            "timestamp": current_timestamp,
            # The UI may not currently be viewing one of the adjusted stations,
            # so publish the downloadable result on the project-level event too.
            "data": summary,
        })

    async def _handle_round_robin_adjustment_error(self, project_id: int, message: str):
        run_id = int(project_id)
        run_context = self._adjustment_run_context(run_id)
        public_project_id = int(run_context["project_id"])
        cluster_name = str(run_context.get("cluster_name") or "Cụm")
        diagnostics = self.round_robin_manager.get_adjustment_diagnostics(run_id)
        try:
            await self.round_robin_manager.restore_common_fixed_base_topology(run_id)
        except Exception as restore_exc:
            logger.error(
                "Could not restore fixed-base topology for run %s: %s",
                run_id,
                restore_exc,
                exc_info=True,
            )
            message = f"{message}; topology restore failed: {restore_exc}"
        self.adjustment_phase[run_id] = "ERROR"
        self.adjustment_message[run_id] = message
        if run_id in self.adjustment_run_contexts:
            self.adjustment_run_contexts[run_id]["status"] = "ERROR"
        failure_result = await write_adjustment_failure_report(
            public_project_id,
            message,
            source="round_robin_runtime",
            project_code=str(run_context.get("project_code") or "") or None,
            cluster_name=cluster_name,
            context={
                "phase": "FREE_NETWORK",
                "run_id": run_id,
                "cluster_index": run_context.get("cluster_index"),
                "diagnostics": diagnostics,
            },
        )
        if failure_result:
            failure_result["run_id"] = run_id
            self.adjustment_cluster_results[public_project_id][run_id] = failure_result
        else:
            self.adjustment_cluster_results[public_project_id].pop(run_id, None)
        phase, summary = self._refresh_project_adjustment_state(public_project_id)
        self.adjustment_message[public_project_id] = f"{cluster_name}: {message}"
        await manager.broadcast({
            "type": "gnss_adjustment_progress",
            "project_id": public_project_id,
            "run_id": run_id,
            "cluster_name": cluster_name,
            "phase": phase,
            "message": f"{cluster_name}: {message}",
            "data": summary,
        })

    async def _handle_round_robin_progress(self, project_id: int, message: str):
        run_id = int(project_id)
        run_context = self._adjustment_run_context(run_id)
        public_project_id = int(run_context["project_id"])
        cluster_name = str(run_context.get("cluster_name") or "Cụm")
        prefixed_message = f"{cluster_name}: {message}"
        self.adjustment_message[run_id] = message
        self.adjustment_message[public_project_id] = prefixed_message
        phase = str(self.adjustment_phase.get(run_id) or "").upper()
        if phase not in {"COLLECTING_BASELINE", "FREE_NETWORK", "PAUSED"}:
            # Receiver health preflight runs inside the start request, before the
            # persistent phase is installed. Do not mislabel those messages as
            # FREE_NETWORK/solver work.
            phase = "COLLECTING_BASELINE"
        await manager.broadcast({
            "type": "gnss_adjustment_progress",
            "project_id": public_project_id,
            "run_id": run_id,
            "cluster_name": cluster_name,
            "phase": phase,
            "message": prefixed_message,
        })
