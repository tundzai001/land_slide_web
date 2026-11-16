"""Database export job implementation."""

from __future__ import annotations
import asyncio
import csv
import io
import json
import logging
import os
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from sqlalchemy import func, select, text
from ....database import ConfigSessionLocal, DataSessionLocal
from ....models import config as model_config
from ....models import data as model_data
from ..reports.adjustment.render import render_adjustment_xlsx
from ..reports.simulation import (
    build_json as build_simulation_json,
    build_pdf as build_simulation_pdf,
    build_xlsx as build_simulation_xlsx,
)
from ..schemas import ExportExcelRequest
from ..sensors import export_sensor_record
from ..filenames import station_export_path, zip_component

logger = logging.getLogger(__name__)
EXPORT_DIR = str(Path(__file__).resolve().parents[4] / "temp_exports")
os.makedirs(EXPORT_DIR, exist_ok=True)

EXPORT_TASKS: Dict[str, dict] = {}
EXPORT_LOCK = asyncio.Lock()

async def _export_excel_task(task_id: str, request: ExportExcelRequest, selected: List[str]):
    filepath = None
    lock_acquired = False
    try:
        EXPORT_TASKS[task_id]["message"] = "Đang chờ lượt xuất dữ liệu..."
        await EXPORT_LOCK.acquire()
        lock_acquired = True
        EXPORT_TASKS[task_id]["status"] = "running"
        EXPORT_TASKS[task_id]["message"] = "Đang phân tích phạm vi dữ liệu..."

        timestamp_suffix = int(time.time())
        filename = f"landslide_backup_{timestamp_suffix}.zip"
        filepath = os.path.join(EXPORT_DIR, f"{task_id}_{filename}")

        # Level 1 is dramatically lighter on the event loop while still shrinking
        # repetitive CSV well. Only one export runs at once (EXPORT_LOCK).
        with zipfile.ZipFile(
            filepath, "w", zipfile.ZIP_DEFLATED, compresslevel=1
        ) as archive:

            def add_csv(filename_in_zip: str, headers: List[str], rows: List[List[Any]]):
                if not rows:
                    return 0
                with archive.open(filename_in_zip, "w") as bin_f:
                    with io.TextIOWrapper(bin_f, encoding="utf-8-sig", newline='') as text_f:
                        writer = csv.writer(text_f)
                        writer.writerow(headers)
                        for r in rows:
                            writer.writerow(r)
                return len(rows)

            async with ConfigSessionLocal() as config_db:
                async with DataSessionLocal() as data_db:
                    exported_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    total_records = 0
                    records_processed = 0
                    summary_rows = []

                    # 1. Fetch config boundaries
                    projects_result = await config_db.execute(select(model_config.Project))
                    all_project_rows = projects_result.scalars().all()
                    project_filter = set(request.project_ids or [])
                    project_rows = [p for p in all_project_rows if not project_filter or p.id in project_filter]
                    project_codes = {project.id: project.project_code for project in all_project_rows}

                    stations_result = await config_db.execute(select(model_config.Station))
                    all_station_rows = stations_result.scalars().all()
                    station_filter = set(request.station_ids or [])
                    station_rows = [
                        s for s in all_station_rows
                        if (not project_filter or s.project_id in project_filter)
                        and (not station_filter or s.id in station_filter)
                    ]
                    scope_station_ids = {station.id for station in station_rows}
                    station_mapping = {
                        station.id: {
                            "project_code": project_codes.get(station.project_id, "UNKNOWN_PROJECT"),
                            "station_code": station.station_code,
                        }
                        for station in station_rows
                    }
                    all_station_mapping = {
                        station.id: {
                            "project_code": project_codes.get(station.project_id, "UNKNOWN_PROJECT"),
                            "station_code": station.station_code,
                        }
                        for station in all_station_rows
                    }
                    requested_sensor_types = set(request.sensor_types or [])

                    # 2. Count data
                    EXPORT_TASKS[task_id]["message"] = "Đang tính toán dung lượng dữ liệu..."
                    total_expected_data = 0

                    sensor_query = select(model_data.SensorData)
                    if scope_station_ids:
                        sensor_query = sensor_query.where(model_data.SensorData.station_id.in_(scope_station_ids))
                    else:
                        sensor_query = sensor_query.where(text("1=0"))

                    # Historical builds stored every successful 1 Hz GNSS forward
                    # as audit data. The filter that previously excluded routine noise
                    # has been removed as per user request to export everything.
                    pass


                    sensor_type_filter = set(requested_sensor_types)
                    if sensor_type_filter:
                        db_sensor_types = set(sensor_type_filter)
                        if 'gnss' in db_sensor_types:
                            db_sensor_types.add('gnss_audit')
                        sensor_query = sensor_query.where(model_data.SensorData.sensor_type.in_(db_sensor_types))
                    # Network-adjustment payloads have their own project-level export.
                    sensor_query = sensor_query.where(
                        model_data.SensorData.sensor_type != 'gnss_adjusted'
                    )

                    if request.start_date:
                        try:
                            start_ts = int(datetime.strptime(request.start_date, '%Y-%m-%d').timestamp())
                            sensor_query = sensor_query.where(model_data.SensorData.timestamp >= start_ts)
                        except ValueError:
                            pass
                    if request.end_date:
                        try:
                            end_ts = int(datetime.strptime(f"{request.end_date} 23:59:59", '%Y-%m-%d %H:%M:%S').timestamp())
                            sensor_query = sensor_query.where(model_data.SensorData.timestamp <= end_ts)
                        except ValueError:
                            pass

                    if 'sensor_data' in selected:
                        count_q = select(func.count()).select_from(sensor_query.subquery())
                        total_expected_data += await data_db.scalar(count_q) or 0

                    adjustment_query = select(model_data.SensorData).where(
                        model_data.SensorData.sensor_type.in_(
                            ('gnss_adjusted', 'gnss_adjustment_failed')
                        ),
                        model_data.SensorData.adjustment_key.is_not(None),
                    )
                    if scope_station_ids:
                        adjustment_query = adjustment_query.where(
                            model_data.SensorData.station_id.in_(scope_station_ids)
                        )
                    else:
                        adjustment_query = adjustment_query.where(text("1=0"))
                    if request.start_date:
                        try:
                            start_ts = int(datetime.strptime(request.start_date, '%Y-%m-%d').timestamp())
                            adjustment_query = adjustment_query.where(
                                model_data.SensorData.timestamp >= start_ts
                            )
                        except ValueError:
                            pass
                    if request.end_date:
                        try:
                            end_ts = int(datetime.strptime(
                                f"{request.end_date} 23:59:59", '%Y-%m-%d %H:%M:%S'
                            ).timestamp())
                            adjustment_query = adjustment_query.where(
                                model_data.SensorData.timestamp <= end_ts
                            )
                        except ValueError:
                            pass
                    if 'gnss_adjustments' in selected:
                        count_q = select(func.count()).select_from(adjustment_query.subquery())
                        total_expected_data += await data_db.scalar(count_q) or 0

                    alert_query = select(model_data.Alert)
                    if scope_station_ids:
                        alert_query = alert_query.where(model_data.Alert.station_id.in_(scope_station_ids))
                    else:
                        alert_query = alert_query.where(text("1=0"))

                    if request.start_date:
                        try:
                            start_ts = int(datetime.strptime(request.start_date, '%Y-%m-%d').timestamp())
                            alert_query = alert_query.where(model_data.Alert.timestamp >= start_ts)
                        except ValueError:
                            pass
                    if request.end_date:
                        try:
                            end_ts = int(datetime.strptime(f"{request.end_date} 23:59:59", '%Y-%m-%d %H:%M:%S').timestamp())
                            alert_query = alert_query.where(model_data.Alert.timestamp <= end_ts)
                        except ValueError:
                            pass

                    if 'alerts' in selected:
                        count_q = select(func.count()).select_from(alert_query.subquery())
                        total_expected_data += await data_db.scalar(count_q) or 0

                    simulation_query = select(model_data.SimulationRun)
                    if project_filter:
                        simulation_query = simulation_query.where(model_data.SimulationRun.project_id.in_(project_filter))
                    if station_filter:
                        simulation_query = simulation_query.where(model_data.SimulationRun.station_id.in_(station_filter))
                    if request.start_date:
                        try:
                            simulation_query = simulation_query.where(model_data.SimulationRun.created_at >= int(datetime.strptime(request.start_date, '%Y-%m-%d').timestamp()))
                        except ValueError:
                            pass
                    if request.end_date:
                        try:
                            simulation_query = simulation_query.where(model_data.SimulationRun.created_at <= int(datetime.strptime(f"{request.end_date} 23:59:59", '%Y-%m-%d %H:%M:%S').timestamp()))
                        except ValueError:
                            pass
                    if 'simulations' in selected:
                        total_expected_data += await data_db.scalar(select(func.count()).select_from(simulation_query.subquery())) or 0

                    if total_expected_data == 0 and not any(t in selected for t in ['projects', 'stations', 'devices']):
                        EXPORT_TASKS[task_id]["status"] = "error"
                        EXPORT_TASKS[task_id]["error"] = "No data available for export"
                        return

                    EXPORT_TASKS[task_id]["message"] = "Đang trích xuất cấu hình (Projects, Stations, Devices)..."

                    if 'projects' in selected:
                        count = add_csv(
                            "PROJECTS.csv", ["id", "code", "name", "description", "active"],
                            [[p.id, p.project_code, p.name, p.description, p.is_active] for p in project_rows]
                        )
                        summary_rows.append(["PROJECTS", count, exported_at, "FULL"])
                        total_records += count

                    if 'stations' in selected:
                        count = add_csv(
                            "STATIONS.csv",
                            ["id", "project_code", "code", "name", "status", "last_update", "location"],
                            [[
                                s.id, project_codes.get(s.project_id, "UNKNOWN_PROJECT"), s.station_code,
                                s.name, s.status,
                                datetime.fromtimestamp(s.last_update).strftime('%Y-%m-%d %H:%M:%S') if s.last_update else None,
                                str(s.location) if s.location is not None else None,
                            ] for s in station_rows]
                        )
                        summary_rows.append(["STATIONS", count, exported_at, "FULL"])
                        total_records += count

                    if 'devices' in selected:
                        devices_result = await config_db.execute(select(model_config.Device))
                        devices = [
                            d for d in devices_result.scalars().all()
                            if d.station_id in scope_station_ids
                            and (not requested_sensor_types or d.device_type in requested_sensor_types)
                        ]
                        count = add_csv(
                            "DEVICES.csv",
                            ["id", "project_code", "station_code", "station_id", "code", "type", "topic"],
                            [[
                                d.id,
                                station_mapping.get(d.station_id, {}).get("project_code", "UNKNOWN_PROJECT"),
                                station_mapping.get(d.station_id, {}).get("station_code", f"station_{d.station_id}"),
                                d.station_id, d.device_code, d.device_type, d.mqtt_topic,
                            ] for d in devices]
                        )
                        summary_rows.append(["DEVICES", count, exported_at, "FULL"])
                        total_records += count

                    if 'gnss_adjustments' in selected:
                        EXPORT_TASKS[task_id]["message"] = "Đang đóng gói kết quả bình sai GNSS theo dự án/cụm..."
                        # Do not materialize every ORM row at once. Adjustment
                        # payloads can be large and the old SELECT + scalars().all()
                        # routinely exceeded asyncpg's command timeout.
                        adjustment_result = await data_db.stream(
                            adjustment_query.with_only_columns(
                                model_data.SensorData.id,
                                model_data.SensorData.timestamp,
                                model_data.SensorData.data,
                                model_data.SensorData.adjustment_key,
                            ).order_by(
                                model_data.SensorData.timestamp,
                                model_data.SensorData.id,
                            ).execution_options(
                                stream_results=True,
                                yield_per=500,
                            )
                        )
                        unique_adjustments: Dict[tuple, dict] = {}
                        cluster_filter = set(request.cluster_indices or [])
                        async for record in adjustment_result:
                            record_id, record_timestamp, record_data, adjustment_key = record
                            records_processed += 1
                            if records_processed % 100 == 0:
                                EXPORT_TASKS[task_id]["percent"] = min(
                                    99,
                                    int((records_processed / total_expected_data) * 99),
                                ) if total_expected_data else 50
                                EXPORT_TASKS[task_id]["message"] = (
                                    f"Đang đọc {records_processed}/{total_expected_data} kết quả bình sai..."
                                )
                                await asyncio.sleep(0)
                            payload = record_data if isinstance(record_data, dict) else {}
                            if cluster_filter and payload.get("cluster_index") not in cluster_filter:
                                continue
                            payload_project_id = int(payload.get("project_id") or 0)
                            adjustment_identity = str(
                                adjustment_key or payload.get("adjustment_key") or ""
                            ).strip()
                            key = (
                                ("adjustment", adjustment_identity)
                                if adjustment_identity
                                else (
                                    "legacy",
                                    payload_project_id,
                                    payload.get("cluster_index"),
                                    int(payload.get("computed_at") or record.timestamp or 0),
                                )
                            )
                            item = unique_adjustments.setdefault(key, {
                                "payload": payload,
                                "timestamp": int(record_timestamp or 0),
                                "record_ids": [],
                                "adjustment_key": adjustment_key,
                            })
                            item["record_ids"].append(int(record_id))
                        await adjustment_result.close()

                        adjustment_rows_by_project: Dict[str, List[List[Any]]] = {}
                        adjustment_headers = [
                            "database_record_ids", "time", "computed_at", "project_id",
                            "project_code", "cluster_index", "cluster_name", "source",
                            "status", "error_type", "error_message",
                            "station_ids", "station_codes", "rover_count", "base_name",
                            "base_lat", "base_lon", "base_h", "observation_baselines",
                            "averaged_baselines", "independent_loops", "degrees_of_freedom",
                            "variance_factor", "reference_std_m0", "weighted_residual_sum",
                            "max_normalized_residual", "global_variance_test_passed",
                            "excel_report_url", "audit_json_url",
                            "payload_json",
                        ]
                        for key, item in unique_adjustments.items():
                            payload = item["payload"]
                            project_id = int(payload.get("project_id") or key[0] or 0)
                            project_code = project_codes.get(project_id, f"PROJECT_{project_id or 'UNKNOWN'}")
                            points = payload.get("points") if isinstance(payload.get("points"), dict) else {}
                            station_ids = sorted({
                                int(point.get("station_id"))
                                for point in points.values()
                                if isinstance(point, dict) and point.get("station_id") is not None
                            }.union({
                                int(value)
                                for value in (payload.get("context") or {}).get("stations", [])
                                if str(value).isdigit()
                            }))
                            station_codes = [
                                all_station_mapping.get(station_id, {}).get(
                                    "station_code", f"station_{station_id}"
                                )
                                for station_id in station_ids
                            ]
                            quality = payload.get("quality") if isinstance(payload.get("quality"), dict) else {}
                            global_test = quality.get("global_test") if isinstance(quality.get("global_test"), dict) else {}
                            base = payload.get("base") if isinstance(payload.get("base"), dict) else {}
                            computed_at = int(payload.get("computed_at") or item["timestamp"] or 0)
                            safe_project = zip_component(project_code, f"project_{project_id}")
                            cluster_label = zip_component(
                                payload.get("cluster_name") or f"cluster_{payload.get('cluster_index', 0)}",
                                "cluster",
                            )
                            readable_time = (
                                datetime.fromtimestamp(computed_at).strftime("%Y-%m-%d_%H-%M-%S")
                                if computed_at else "unknown-time"
                            )
                            run_stem = f"{readable_time}_{cluster_label}"
                            # The JSON in the archive is the compact DB payload.
                            # Build its XLSX sibling in memory for this export only.
                            run_folder = f"gnss_adjustments/{safe_project}/{cluster_label}/{run_stem}"
                            archive.writestr(
                                f"{run_folder}/{run_stem}.json",
                                json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                            )
                            excel_url = payload.get("excel_report_url")
                            evidence = []
                            adjustment_key = str(
                                item.get("adjustment_key")
                                or payload.get("adjustment_key")
                                or ""
                            )
                            if adjustment_key:
                                evidence_result = await data_db.execute(
                                    select(model_data.GnssAdjustmentEvidence)
                                    .where(
                                        model_data.GnssAdjustmentEvidence.adjustment_key
                                        == adjustment_key
                                    )
                                    .order_by(
                                        model_data.GnssAdjustmentEvidence.source_index.asc()
                                    )
                                )
                                evidence = evidence_result.scalars().all()
                            xlsx_bytes = render_adjustment_xlsx(
                                payload,
                                evidence,
                                project_id=project_id,
                            )
                            archive.writestr(
                                f"{run_folder}/{run_stem}.xlsx",
                                xlsx_bytes,
                            )

                            adjustment_rows_by_project.setdefault(safe_project, []).append([
                                ";".join(map(str, sorted(item["record_ids"]))),
                                datetime.fromtimestamp(computed_at).strftime('%Y-%m-%d %H:%M:%S') if computed_at else None,
                                computed_at, project_id, project_code,
                                payload.get("cluster_index"), payload.get("cluster_name"), payload.get("source"),
                                payload.get("status") or payload.get("phase"),
                                (payload.get("error") or {}).get("type"),
                                (payload.get("error") or {}).get("message"),
                                ";".join(map(str, station_ids)), ";".join(station_codes),
                                payload.get("rover_count"), base.get("name"), base.get("lat"),
                                base.get("lon"), base.get("h"),
                                quality.get("observation_baseline_count")
                                or quality.get("raw_observation_count")
                                or len(payload.get("baseline_observations") or []),
                                quality.get("averaged_baseline_count", len(payload.get("baselines") or [])),
                                len(payload.get("loops") or []), quality.get("degrees_of_freedom"),
                                quality.get("variance_factor"), quality.get("reference_standard_deviation"),
                                quality.get("weighted_residual_sum"), quality.get("max_standardized_residual"),
                                global_test.get("passed"), excel_url,
                                payload.get("audit_json_url"),
                                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                            ])

                        adjustment_count = 0
                        for project_code, rows in sorted(adjustment_rows_by_project.items()):
                            count = add_csv(
                                f"gnss_adjustments/{project_code}/ADJUSTMENTS.csv",
                                adjustment_headers,
                                rows,
                            )
                            adjustment_count += count
                            summary_rows.append([
                                f"{project_code}/gnss_adjustments", count, exported_at, "PROJECT/CLUSTER/STATIONS"
                            ])
                        if not adjustment_rows_by_project:
                            summary_rows.append(["GNSS_ADJUSTMENTS", 0, exported_at, "FILTERED"])
                        total_records += adjustment_count

                    if 'sensor_data' in selected:
                        sensor_stream = await data_db.stream(
                            sensor_query.order_by(
                                model_data.SensorData.station_id,
                                model_data.SensorData.sensor_type,
                                model_data.SensorData.timestamp,
                                model_data.SensorData.id,
                            ).execution_options(yield_per=500)
                        )

                        current_key = None
                        bin_f = None
                        text_f = None
                        writer = None
                        sensor_counts = {}

                        async for d in sensor_stream.scalars():
                            mapping = station_mapping.get(d.station_id, {
                                "project_code": "UNKNOWN_PROJECT",
                                "station_code": f"station_{d.station_id}",
                            })
                            p_code, s_code = mapping["project_code"], mapping["station_code"]
                            sensor_export = export_sensor_record(d, mapping)
                            if sensor_export is None:
                                continue

                            dataset = sensor_export["dataset"]
                            key = (p_code, s_code, dataset)
                            if current_key != key:
                                if text_f:
                                    text_f.close()
                                    bin_f.close()
                                export_name = sensor_export["filename"]
                                base_sheet_title = station_export_path(
                                    p_code, s_code, d.station_id, export_name
                                )
                                bin_f = archive.open(base_sheet_title, "w")
                                text_f = io.TextIOWrapper(bin_f, encoding="utf-8-sig", newline='')
                                writer = csv.writer(text_f)
                                writer.writerow(sensor_export["headers"])
                                current_key = key

                            writer.writerow(sensor_export["row"])

                            count_key = f"{p_code}/{s_code}/{dataset}"
                            sensor_counts[count_key] = sensor_counts.get(count_key, 0) + 1
                            total_records += 1
                            records_processed += 1

                            if records_processed % 250 == 0:
                                EXPORT_TASKS[task_id]["percent"] = min(99, int((records_processed / total_expected_data) * 99)) if total_expected_data else 50
                                EXPORT_TASKS[task_id]["message"] = f"Đang xuất {records_processed}/{total_expected_data} dòng dữ liệu..."
                                await asyncio.sleep(0) # yield control to avoid blocking event loop

                        if text_f:
                            text_f.close()
                            bin_f.close()

                        if sensor_counts:
                            for dataset, count in sorted(sensor_counts.items()):
                                summary_rows.append([dataset, count, exported_at, "FULL"])
                        else:
                            summary_rows.append(["SENSOR_DATA", 0, exported_at, "FULL"])

                    if 'alerts' in selected:
                        alert_headers = [
                            "id", "time", "timestamp", "project_code", "station_code", "station_id",
                            "level", "category", "message", "resolved",
                        ]
                        alert_counts = {}
                        current_alert_key = None
                        bin_f = None
                        text_f = None
                        writer = None
                        alert_stream = await data_db.stream(
                            alert_query.order_by(
                                model_data.Alert.station_id,
                                model_data.Alert.timestamp,
                                model_data.Alert.id,
                            ).execution_options(yield_per=500)
                        )
                        async for alert in alert_stream.scalars():
                            mapping = station_mapping.get(alert.station_id, {
                                "project_code": "UNKNOWN_PROJECT",
                                "station_code": f"station_{alert.station_id}",
                            })
                            alert_key = (
                                mapping["project_code"], mapping["station_code"], alert.station_id
                            )
                            if current_alert_key != alert_key:
                                if text_f:
                                    text_f.close()
                                bin_f = archive.open(
                                    station_export_path(
                                        mapping["project_code"],
                                        mapping["station_code"],
                                        alert.station_id,
                                        "ALERTS.csv",
                                    ),
                                    "w",
                                )
                                text_f = io.TextIOWrapper(
                                    bin_f, encoding="utf-8-sig", newline=''
                                )
                                writer = csv.writer(text_f)
                                writer.writerow(alert_headers)
                                current_alert_key = alert_key

                            writer.writerow([
                                alert.id, datetime.fromtimestamp(alert.timestamp).strftime('%Y-%m-%d %H:%M:%S'),
                                alert.timestamp, mapping["project_code"], mapping["station_code"], alert.station_id,
                                alert.level, alert.category, alert.message, alert.is_resolved,
                            ])
                            alert_dataset = (
                                f"{mapping['project_code']}/{mapping['station_code']}/alerts"
                            )
                            alert_counts[alert_dataset] = alert_counts.get(alert_dataset, 0) + 1
                            total_records += 1
                            records_processed += 1

                            if records_processed % 250 == 0:
                                EXPORT_TASKS[task_id]["percent"] = min(99, int((records_processed / total_expected_data) * 99)) if total_expected_data else 50
                                EXPORT_TASKS[task_id]["message"] = f"Đang xuất {records_processed}/{total_expected_data} dòng dữ liệu..."
                                await asyncio.sleep(0)

                        if text_f:
                            text_f.close()
                        if alert_counts:
                            for dataset, count in sorted(alert_counts.items()):
                                summary_rows.append([dataset, count, exported_at, "FULL"])
                        else:
                            summary_rows.append(["ALERTS", 0, exported_at, "FULL"])

                    if 'simulations' in selected:
                        EXPORT_TASKS[task_id]["message"] = "Đang dựng báo cáo mô phỏng từ database..."
                        runs = (await data_db.execute(simulation_query.order_by(model_data.SimulationRun.created_at, model_data.SimulationRun.id))).scalars().all()
                        for run in runs:
                            project_component = zip_component(run.project_code, "MANUAL")
                            station_component = zip_component(run.station_code, "manual")
                            created_label = datetime.fromtimestamp(run.created_at).strftime("%Y-%m-%d_%H-%M-%S")
                            folder = f"simulations/{project_component}/{station_component}/{created_label}_{zip_component(run.display_name, f'run_{run.id}')}"
                            pdf_data, xlsx_data, json_data = await asyncio.gather(
                                asyncio.to_thread(build_simulation_pdf, run),
                                asyncio.to_thread(build_simulation_xlsx, run),
                                asyncio.to_thread(build_simulation_json, run),
                            )
                            archive.writestr(f"{folder}/report.pdf", pdf_data)
                            archive.writestr(f"{folder}/results.xlsx", xlsx_data)
                            archive.writestr(f"{folder}/data.json", json_data)
                            total_records += 1
                            records_processed += 1
                        summary_rows.append(["SIMULATIONS", len(runs), exported_at, "FILTERED"])

                    summary_rows.append(["TOTAL", total_records, exported_at, "FULL"])
                    add_csv("EXPORT_SUMMARY.csv", ["dataset", "record_count", "exported_at", "scope"], summary_rows)

        # ZipFile is closed automatically by the context manager, finishing the compression.

        if request.format == 'both':
            from .formats import add_excel_files
            EXPORT_TASKS[task_id]["message"] = "Đang tạo Excel từ các dataset CSV..."
            await asyncio.to_thread(add_excel_files, filepath)
        EXPORT_TASKS[task_id]["status"] = "completed"
        EXPORT_TASKS[task_id]["percent"] = 100
        EXPORT_TASKS[task_id]["message"] = "Hoàn thành!"
        EXPORT_TASKS[task_id]["file_path"] = filepath
        EXPORT_TASKS[task_id]["filename"] = filename

    except Exception as e:
        logger.exception(f"Excel full export background task failed: {e}")
        EXPORT_TASKS[task_id]["status"] = "error"
        EXPORT_TASKS[task_id]["error"] = str(e)
        EXPORT_TASKS[task_id]["message"] = "Xuất dữ liệu thất bại"
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError:
                logger.warning("Could not remove partial export file %s", filepath)
    finally:
        if lock_acquired:
            EXPORT_LOCK.release()
