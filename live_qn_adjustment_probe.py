"""Run the production GNSS adjustment pipeline locally for QN / Mong Duong.

The probe is intentionally fail-closed before the first receiver mutation:
all eight rover topics, RTK FIX AGRICA, AICaster sessions, and the fixed CORS
stream must be visible first.  RoundRobinAdjustmentManager owns every BASE /
ROVER transition and its normal finally blocks restore receiver/CORS state.
"""

from __future__ import annotations

import asyncio
import argparse
import json
import logging
from pathlib import Path
import sys
import time

ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from backend.app.config import settings
from backend.app.features.gnss_adjustment.store import (
    add_report_links,
    compact_adjustment_payload,
)
from backend.app.mqtt.ntrip_pusher import ntrip_manager
from backend.mqtt_bridge import MQTTBridge
from backend.processors.gnss_adjustment.runtime import parse_agrica
from backend.processors.gnss_adjustment.round_robin import RoundRobinAdjustmentManager
from live_base_output_probe import LiveFeed, _UnusedPublisher


PROJECT_ID = 9104
MQTT_BROKER = "aitogy.click"
MQTT_PORT = 1883
CASTER_HOST = "aitogy.click"
CASTER_PORT = 2101
MOUNTPOINT = "QN.CP"
FIXED_BASE_NAME = "QN.CamPha"
FIXED_BASE_LLH = (21.062199235, 107.330017286, -8.2944)

STATIONS = {
    "CP01": {"id": 101, "imei": "860549070039131"},
    "CP02": {"id": 102, "imei": "860549070366245"},
    "CP03": {"id": 103, "imei": "860549070374074"},
    "CP04": {"id": 104, "imei": "860549070085423"},
    "CP05": {"id": 105, "imei": "860549070085472"},
    "CP06": {"id": 106, "imei": "860549070084194"},
    "CP07": {"id": 107, "imei": "860549070084145"},
    "CP08": {"id": 108, "imei": "860549070084095"},
}
TOPICS = {
    f"device/{item['imei']}/upload": station
    for station, item in STATIONS.items()
}


def ts() -> str:
    return time.strftime("%H:%M:%S")


def station_value(mapping: dict, station_id: int, default=0):
    return mapping.get(station_id, mapping.get(str(station_id), default))


async def _print_diagnostic_sessions(manager: RoundRobinAdjustmentManager, selected_stations: dict) -> None:
    print(f"[{ts()}] Read-only AICaster session diagnostics:", flush=True)
    for station in selected_stations:
        try:
            client_info = await manager._find_client_info(station)
        except Exception as exc:
            print(f"  {station}: lookup error: {exc}", flush=True)
            continue
        if client_info:
            print(
                f"  {station}: {client_info.get('CasterHost')}:"
                f"{client_info.get('CasterPort')}/"
                f"{client_info.get('Mountpoint')}",
                flush=True,
            )
        else:
            print(f"  {station}: no active session", flush=True)
    print(
        f"[{ts()}] Diagnostic-only probe complete; no receiver/CORS mutation was attempted.",
        flush=True,
    )


async def _sample_qn_observations(feed: LiveFeed, selected_stations: dict, preflight_seconds: float, diagnostic_only: bool) -> dict:
    deadline = time.monotonic() + max(5.0, float(preflight_seconds))
    observations = {}
    while time.monotonic() < deadline:
        for station, item in selected_stations.items():
            with feed.lock:
                latest = feed.latest_agrica.get(station)
            if not latest:
                continue
            parsed = parse_agrica(
                latest[1],
                project_id=PROJECT_ID,
                station_id=item["id"],
                rover_name=station,
            )
            if parsed:
                observations[station] = parsed[-1]
        if len(observations) == len(selected_stations) and not diagnostic_only:
            break
        await asyncio.sleep(0.25)
    return observations


def _validate_qn_preflight(feed: LiveFeed, selected_stations: dict, observations: dict) -> None:
    missing = sorted(set(selected_stations) - set(observations))
    if missing:
        print(f"[{ts()}] MQTT topic diagnostics before safe abort:", flush=True)
        for station in selected_stations:
            stats = feed.snapshot(station)
            print(
                f"  {station}: messages={stats.messages}, bytes={stats.payload_bytes}, "
                f"AGRICA={stats.agrica_sentences}, GGA={stats.gga_sentences}, "
                f"command_responses={stats.command_responses}",
                flush=True,
            )
        raise RuntimeError(
            "Preflight aborted before receiver mutation; missing complete AGRICA: "
            + ", ".join(missing)
        )
    non_fixed = sorted(
        station
        for station, observation in observations.items()
        if int(observation.position_type or 0) != 4
    )
    if non_fixed:
        raise RuntimeError(
            "Preflight aborted before receiver mutation; rover not RTK FIX: "
            + ", ".join(non_fixed)
        )
    print(f"[{ts()}] MQTT/AGRICA PREFLIGHT PASS", flush=True)
    for station in selected_stations:
        obs = observations[station]
        print(
            f"  {station}: FIX={obs.position_type}, "
            f"baseline={tuple(round(v, 4) for v in obs.baseline_neu)}, "
            f"std={tuple(round(v, 4) for v in obs.std_neu)}, "
            f"base_llh={obs.base_llh}",
            flush=True,
        )


async def _verify_active_aicaster_sessions(manager: RoundRobinAdjustmentManager, selected_stations: dict) -> None:
    print(f"[{ts()}] Checking active AICaster SET sessions (read-only) ...", flush=True)
    client_sessions = {}
    for station in selected_stations:
        client_info = await manager._find_client_info(station)
        if client_info:
            client_sessions[station] = client_info
            print(
                f"  {station}: {client_info.get('CasterHost')}:"
                f"{client_info.get('CasterPort')}/"
                f"{client_info.get('Mountpoint')}",
                flush=True,
            )
        else:
            print(f"  {station}: no active SET session", flush=True)
    if not client_sessions:
        raise RuntimeError(
            "Preflight aborted before receiver mutation; no QN rover has an active AICaster SET session"
        )


def _format_qn_seed_lines(cluster: dict, selected_stations: dict) -> str:
    lines = []
    for station, item in selected_stations.items():
        station_id = item["id"]
        is_open = bool(station_value(cluster.get("solver_window_open_by_station") or {}, station_id))
        state_label = "solver" if is_open else "warm-up"
        counts = station_value(cluster.get("solver_sample_counts_by_station" if is_open else "sample_counts_by_station") or {}, station_id)
        durations = station_value(cluster.get("solver_durations_by_station_seconds" if is_open else "durations_by_station_seconds") or {}, station_id)
        lines.append(f"{station}:{state_label} {counts} {durations}s")
    return " | ".join(lines)


async def _wait_for_qn_seed(manager: RoundRobinAdjustmentManager, selected_stations: dict) -> None:
    print(f"[{ts()}] Collecting fixed-base warm-up + solver windows ...", flush=True)
    seed_deadline = time.monotonic() + 300.0
    last_progress_second = -1
    while time.monotonic() < seed_deadline:
        status = manager.get_seed_collection_status(PROJECT_ID)
        if status.get("complete"):
            return
        elapsed = int(status.get("stability_elapsed_seconds") or 0)
        if elapsed // 5 != last_progress_second // 5:
            last_progress_second = elapsed
            cluster = (status.get("clusters") or [{}])[0]
            print(f"[{ts()}] SEED: {_format_qn_seed_lines(cluster, selected_stations)}", flush=True)
        await asyncio.sleep(0.5)
    raise RuntimeError(
        "Fixed-base collection timeout: "
        + json.dumps(
            manager.get_seed_collection_status(PROJECT_ID),
            ensure_ascii=False,
            default=str,
        )
    )


def _print_qn_final_report(result: dict) -> None:
    report_timestamp = int(time.time())
    compact_result, evidence = compact_adjustment_payload(result)
    compact_result["project_id"] = PROJECT_ID
    compact_result["run_id"] = PROJECT_ID
    compact_result["adjustment_key"] = f"probe:{PROJECT_ID}:{report_timestamp}"
    report_urls = add_report_links(
        compact_result,
        project_id=PROJECT_ID,
        timestamp=report_timestamp,
    )
    quality = result.get("quality") or {}
    print(f"[{ts()}] FULL LOCAL QN ADJUSTMENT COMPLETE", flush=True)
    print(f"  quality_gate={quality.get('quality_gate_status')}", flush=True)
    print(
        f"  raw={quality.get('raw_observation_count')} "
        f"accepted={quality.get('accepted_raw_observation_count')} "
        f"edges={len(result.get('baselines') or [])} "
        f"loops={len(result.get('loops') or [])}",
        flush=True,
    )
    print(f"  Excel (on-demand)={report_urls['excel_report_url']}", flush=True)
    print(f"  JSON (on-demand)={report_urls['audit_json_url']}", flush=True)
    print(f"  Raw evidence rows in DB={len(evidence)}", flush=True)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mqtt-broker", default=MQTT_BROKER)
    parser.add_argument("--diagnostic-only", action="store_true")
    parser.add_argument("--preflight-seconds", type=float, default=60.0)
    parser.add_argument(
        "--stations",
        nargs="+",
        choices=sorted(STATIONS),
        default=list(STATIONS),
    )
    args = parser.parse_args()
    mqtt_broker = str(args.mqtt_broker).strip() or MQTT_BROKER
    selected_stations = {
        station: STATIONS[station]
        for station in dict.fromkeys(args.stations)
    }
    selected_topics = {
        f"device/{item['imei']}/upload": station
        for station, item in selected_stations.items()
    }

    results: list[dict] = []
    errors: list[str] = []

    async def progress_callback(_project_id: int, message: str) -> None:
        await asyncio.sleep(0)
        print(f"[{ts()}] PHASE: {message}", flush=True)

    async def result_callback(_project_id: int, result: dict) -> None:
        await asyncio.sleep(0)
        results.append(result)
        quality = result.get("quality") or {}
        print(
            f"[{ts()}] RESULT: rovers={result.get('rover_count')} "
            f"edges={len(result.get('baselines') or [])} "
            f"loops={len(result.get('loops') or [])} "
            f"gate={quality.get('quality_gate_status')} "
            f"vTPv={quality.get('weighted_residual_sum_squares')}",
            flush=True,
        )

    async def error_callback(_project_id: int, message: str) -> None:
        await asyncio.sleep(0)
        errors.append(message)
        print(f"[{ts()}] ERROR: {message}", flush=True)

    async def route_start(
        station: str,
        host: str,
        port: int,
        mountpoint: str,
        password: str,
    ) -> bool:
        print(
            f"[{ts()}] ROUTE START: {station} -> {host}:{port}/{mountpoint}",
            flush=True,
        )
        await ntrip_manager.start_pusher(station, host, port, mountpoint, password)
        await ntrip_manager.wait_for_rtcm(station, timeout=30.0)
        diagnostic = ntrip_manager.get_diagnostics(station)
        print(f"[{ts()}] ROUTE VERIFIED {station}: {diagnostic}", flush=True)
        return True

    async def route_stop(station: str) -> None:
        await ntrip_manager.stop_pusher(station)
        print(f"[{ts()}] ROUTE STOP: {station}", flush=True)

    hosts = [
        host.strip()
        for host in settings.NTRIP_HOSTS.split(",")
        if host.strip()
    ]
    if CASTER_HOST not in hosts:
        hosts.append(CASTER_HOST)
    manager = RoundRobinAdjustmentManager(
        _UnusedPublisher(),
        caster_host=CASTER_HOST,
        caster_hosts=hosts,
        caster_port=settings.NTRIP_PORT,
        source_host=CASTER_HOST,
        source_port=CASTER_PORT,
        control_password=settings.NTRIP_PASSWORD,
        source_password=settings.NTRIP_PASSWORD,
        web_cors_api_base_url=settings.WEB_CORS_API_BASE_URL,
        web_cors_api_token=settings.WEB_CORS_API_TOKEN,
        web_cors_api_username=settings.WEB_CORS_API_USERNAME,
        web_cors_api_password=settings.WEB_CORS_API_PASSWORD,
        route_start_callback=route_start,
        route_stop_callback=route_stop,
        result_callback=result_callback,
        error_callback=error_callback,
        progress_callback=progress_callback,
    )

    loop = asyncio.get_running_loop()

    def process_payload(station: str, _topic: str, payload: bytes) -> None:
        ntrip_manager.feed_data(station, payload)

        def ingest() -> None:
            manager.add_agrica_payload(
                payload.decode("utf-8", errors="ignore"),
                {
                    "project_id": PROJECT_ID,
                    "station_id": STATIONS[station]["id"],
                    "station_code": station,
                },
            )

        loop.call_soon_threadsafe(ingest)

    feed = LiveFeed(
        manager,
        payload_callback=process_payload,
        topics=selected_topics,
        mqtt_broker=mqtt_broker,
        mqtt_port=MQTT_PORT,
        mqtt_user=settings.MQTT_USER,
        mqtt_password=settings.MQTT_PASSWORD,
    )

    feed.start()
    cycle_started = False
    try:
        print(f"[{ts()}] MQTT connected to {mqtt_broker}:{MQTT_PORT}; waiting for fresh complete AGRICA ...", flush=True)
        observations = await _sample_qn_observations(feed, selected_stations, args.preflight_seconds, args.diagnostic_only)

        if args.diagnostic_only:
            await _print_diagnostic_sessions(manager, selected_stations)
            return 0

        _validate_qn_preflight(feed, selected_stations, observations)
        await _verify_active_aicaster_sessions(manager, selected_stations)

        _serial, server_id, _service_config = await asyncio.to_thread(manager._find_cors_station_sync, MOUNTPOINT, CASTER_HOST)
        print(f"[{ts()}] Fixed CORS stream preflight PASS: {CASTER_HOST}/{MOUNTPOINT} server-slot=S{server_id}", flush=True)

        manager.configure_project(PROJECT_ID, [{
            "name": "Mong Duong QN live local probe",
            "stations": [item["id"] for item in selected_stations.values()],
            "rovers": list(selected_stations),
            "base_station": FIXED_BASE_NAME,
            "base_lat": FIXED_BASE_LLH[0],
            "base_lon": FIXED_BASE_LLH[1],
            "base_alt": FIXED_BASE_LLH[2],
            "base_stream_host": CASTER_HOST,
            "base_stream_port": CASTER_PORT,
            "base_stream_mp": MOUNTPOINT,
            "round_robin_route_host": CASTER_HOST,
            "round_robin_route_port": CASTER_PORT,
            "round_robin_route_mountpoint": MOUNTPOINT,
            "round_robin_route_password": settings.NTRIP_PASSWORD,
        }])

        await _wait_for_qn_seed(manager, selected_stations)

        print(f"[{ts()}] FIXED-BASE SEED READY; starting full Round-Robin", flush=True)
        cycle_started = True
        await asyncio.wait_for(manager._run_cycle(PROJECT_ID), timeout=900.0)

        if errors:
            raise RuntimeError(errors[-1])
        if not results:
            raise RuntimeError("Round-Robin finished without an adjustment result")

        _print_qn_final_report(results[-1])
        return 0
    finally:
        for station in selected_stations:
            try:
                await ntrip_manager.stop_pusher(station)
            except Exception:
                logging.exception("Failed to stop NTRIP pusher for %s", station)
        feed.stop()
        if cycle_started:
            print(f"[{ts()}] Local probe cleanup complete", flush=True)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    raise SystemExit(asyncio.run(main()))
