"""Run the production Round-Robin adjustment locally against live Dam 1 MQTT data."""

from __future__ import annotations

import asyncio
import argparse
import json
import logging
import sys
import time
from io import BytesIO
from pathlib import Path

from backend.app.config import settings
from backend.app.mqtt.ntrip_pusher import ntrip_manager
from backend.processors.gnss_adjustment.runtime import parse_agrica
from backend.processors.gnss_adjustment.round_robin import RoundRobinAdjustmentManager
from live_base_output_probe import LiveFeed, _UnusedPublisher
from live_gnss_probe import TOPICS


PROJECT_ID = 9003
STATIONS = {
    "Dap2_1": 8,
    "Dap2_2": 9,
    "Dap1_1": 5,
    "Dap1_2": 7,
    "Dap1_3": 6,
    "Dap1_4": 4,
}


def ts() -> str:
    return time.strftime("%H:%M:%S")


async def _handle_rover_restore(manager: RoundRobinAdjustmentManager, station: str, feed: LiveFeed) -> int:
    await asyncio.sleep(3)
    client_info = await manager._find_client_info(station)
    if not client_info:
        raise RuntimeError(f"No active AICaster session is available to restore {station}")
    print(
        f"[{ts()}] RESTORE ONLY: {station} via "
        f"{client_info.get('CasterHost')}:{client_info.get('CasterPort')}/"
        f"{client_info.get('Mountpoint')}",
        flush=True,
    )
    await manager._restore_rover_output_sequence(
        rover_code=station,
        mountpoint=str(client_info.get("Mountpoint") or ""),
        client_info=client_info,
        commands=manager._build_unicore_rover_config(),
        project_id=None,
    )
    restore_started = time.monotonic()
    deadline = restore_started + 20
    while time.monotonic() < deadline:
        if feed.latest_agrica_time(station) >= restore_started:
            print(f"[{ts()}] RESTORE VERIFIED: fresh AGRICA from {station}", flush=True)
            return 0
        await asyncio.sleep(0.25)
    raise RuntimeError(f"{station} acknowledged ROVER restore but emitted no fresh AGRICA")


async def _sample_live_agrica_observations(feed: LiveFeed, selected_stations: dict, preflight_seconds: float) -> dict:
    deadline = time.monotonic() + max(5.0, preflight_seconds)
    observations = {}
    while time.monotonic() < deadline:
        for station, station_id in selected_stations.items():
            with feed.lock:
                latest = feed.latest_agrica.get(station)
            if not latest:
                continue
            parsed = parse_agrica(latest[1], project_id=PROJECT_ID, station_id=station_id, rover_name=station)
            if parsed and parsed[-1].rover_llh and parsed[-1].base_llh:
                observations[station] = parsed[-1]
        if len(observations) == len(selected_stations):
            break
        await asyncio.sleep(0.25)
    if len(observations) != len(selected_stations):
        missing = sorted(set(selected_stations) - set(observations))
        raise RuntimeError(f"Missing complete live AGRICA from: {', '.join(missing)}")
    return observations


def _resolve_cors_base_config(manager: RoundRobinAdjustmentManager, base_name: str) -> tuple[dict, int, tuple[float, float, float]]:
    cors_stations = manager._cors_api_request_sync("GET", "/api/public/map-stations")
    if isinstance(cors_stations, dict):
        cors_stations = cors_stations.get("value") or cors_stations.get("items") or []
    base_station = next(
        (
            s for s in cors_stations
            if str(s.get("name") or s.get("code") or "").strip().casefold() == str(base_name).strip().casefold()
        ),
        None,
    )
    if base_station is None:
        raise RuntimeError(f"CORS base {base_name!r} was not found")
    base_config = base_station.get("service_config") or {}
    base_server_id = next(
        (
            sid for sid in (1, 2)
            if str(base_config.get(f"mountpoint{sid}") or "").strip().casefold() == str(base_name).strip().casefold()
        ),
        None,
    )
    if base_server_id is None:
        raise RuntimeError(f"CORS base {base_name!r} has no matching S1/S2 mountpoint")
    base_llh = (float(base_station["lat"]), float(base_station["lon"]), float(base_station.get("alt") or 0.0))
    print(
        f"[{ts()}] CORS SELECTED: {base_name} status={base_station.get('status')} "
        f"serial={base_station.get('serial')} S{base_server_id} LLH={base_llh}",
        flush=True,
    )
    return base_station, base_server_id, base_llh


async def _wait_for_seed_collection(manager: RoundRobinAdjustmentManager, project_id: int, seed_timeout_seconds: float) -> None:
    seed_deadline = time.monotonic() + max(30.0, seed_timeout_seconds)
    while time.monotonic() < seed_deadline:
        status = manager.get_seed_collection_status(project_id)
        if status.get("complete"):
            return
        await asyncio.sleep(0.5)

    status = manager.get_seed_collection_status(project_id)
    if status.get("fallback_ready"):
        status = manager.skip_missing_seed_stations(project_id)
        print(f"[{ts()}] SEED SKIP OFFLINE/DEGRADED: station_ids={status.get('skipped_station_ids') or []}", flush=True)
    if not status.get("complete"):
        raise RuntimeError(f"Seed collection did not become ready: {status}")


def _write_probe_outputs(result: dict, output_file: str, xlsx_output: str) -> None:
    output_path = Path(output_file).resolve()
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    xlsx_path = None
    if xlsx_output:
        backend_dir = Path(__file__).resolve().parent / "backend"
        if str(backend_dir) not in sys.path:
            sys.path.insert(0, str(backend_dir))
        from mqtt_bridge import MQTTBridge
        report_bridge = MQTTBridge.__new__(MQTTBridge)
        report_stream = BytesIO()
        report_bridge._append_adjustment_to_excel(PROJECT_ID, int(time.time()), result, "", output_stream=report_stream)
        xlsx_path = Path(xlsx_output).resolve()
        xlsx_path.parent.mkdir(parents=True, exist_ok=True)
        xlsx_path.write_bytes(report_stream.getvalue())

    print(f"[{ts()}] FINAL SUCCESS\n[{ts()}] RESULT JSON: {output_path}", flush=True)
    if xlsx_path:
        print(f"[{ts()}] RESULT XLSX: {xlsx_path}", flush=True)


async def _route_start(station: str, host: str, port: int, mountpoint: str, password: str) -> bool:
    print(f"[{ts()}] ROUTE START: {station} -> {host}:{port}/{mountpoint}", flush=True)
    await ntrip_manager.start_pusher(station, host, port, mountpoint, password)
    return True


async def _route_wait(station: str, timeout_sec: float = 25.0) -> None:
    try:
        await ntrip_manager.wait_for_rtcm(station, timeout=timeout_sec)
    except Exception:
        print(f"[{ts()}] ROUTE DIAGNOSTIC {station}: {ntrip_manager.get_diagnostics(station)}", flush=True)
        await ntrip_manager.stop_pusher(station)
        raise
    print(f"[{ts()}] ROUTE VERIFIED {station}: {ntrip_manager.get_diagnostics(station)}", flush=True)


async def _route_stop(station: str) -> None:
    await ntrip_manager.stop_pusher(station)
    print(f"[{ts()}] ROUTE STOP: {station}", flush=True)


def _create_round_robin_manager(results: list, errors: list) -> RoundRobinAdjustmentManager:
    async def progress_callback(_project_id: int, message: str) -> None:
        await asyncio.sleep(0)
        print(f"[{ts()}] PHASE: {message}", flush=True)

    async def result_callback(_project_id: int, result: dict) -> None:
        await asyncio.sleep(0)
        results.append(result)
        quality = result.get("quality") or {}
        print(
            f"[{ts()}] RESULT: rover_count={result.get('rover_count')} "
            f"baselines={len(result.get('baselines') or [])} loops={len(result.get('loops') or [])} "
            f"variance_factor={quality.get('variance_factor')}",
            flush=True,
        )

    async def error_callback(_project_id: int, message: str) -> None:
        await asyncio.sleep(0)
        errors.append(message)
        print(f"[{ts()}] ERROR: {message}", flush=True)

    hosts = [h.strip() for h in settings.NTRIP_HOSTS.split(",") if h.strip()]
    if not hosts:
        raise RuntimeError("NTRIP_HOSTS must contain at least one caster host")

    return RoundRobinAdjustmentManager(
        _UnusedPublisher(),
        caster_host=hosts[0], caster_hosts=hosts, caster_port=settings.NTRIP_PORT,
        source_host=hosts[0], source_port=settings.NTRIP_PORT,
        control_password=settings.NTRIP_PASSWORD, source_password=settings.NTRIP_PASSWORD,
        web_cors_api_base_url=settings.WEB_CORS_API_BASE_URL,
        web_cors_api_token=settings.WEB_CORS_API_TOKEN,
        web_cors_api_username=settings.WEB_CORS_API_USERNAME,
        web_cors_api_password=settings.WEB_CORS_API_PASSWORD,
        route_start_callback=_route_start, route_wait_callback=_route_wait, route_stop_callback=_route_stop,
        result_callback=result_callback, error_callback=error_callback, progress_callback=progress_callback,
    )


def _configure_probe_manager(manager, args, selected_stations, base_station, base_server_id, base_llh):
    base_config = base_station.get("service_config") or {}
    manager.configure_project(PROJECT_ID, [{
        "name": str(args.cluster_name), "stations": list(selected_stations.values()),
        "rovers": list(selected_stations), "base_station": str(args.base),
        "base_lat": base_llh[0], "base_lon": base_llh[1], "base_alt": base_llh[2],
        "base_stream_host": str(base_config.get(f"serverhost{base_server_id}") or ""),
        "base_stream_port": int(base_config.get(f"port{base_server_id}") or 2101),
        "base_stream_mp": str(base_config.get(f"mountpoint{base_server_id}") or ""),
        "base_service_config": base_config, "base_serial": str(base_station.get("serial") or ""),
        "base_server_id": base_server_id,
        "round_robin_route_host": str(base_config.get(f"serverhost{base_server_id}") or ""),
        "round_robin_route_port": int(base_config.get(f"port{base_server_id}") or 2101),
        "round_robin_route_mountpoint": str(base_config.get(f"mountpoint{base_server_id}") or ""),
        "round_robin_route_password": settings.NTRIP_PASSWORD, "skip_offline_rovers": True,
    }])


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stations", nargs="+", choices=sorted(STATIONS), default=list(STATIONS))
    parser.add_argument("--base", default="SinQuyen2")
    parser.add_argument("--cluster-name", default="Sin Quyen live local probe")
    parser.add_argument("--preflight-seconds", type=float, default=30.0)
    parser.add_argument("--seed-timeout-seconds", type=float, default=180.0)
    parser.add_argument("--restore-only", action="store_true")
    parser.add_argument("--output", default="live_full_adjustment_result.json")
    parser.add_argument("--xlsx-output", default="")
    args = parser.parse_args()

    selected_stations = {station: STATIONS[station] for station in dict.fromkeys(args.stations)}
    selected_topics = {topic: station for topic, station in TOPICS.items() if station in selected_stations}
    results: list[dict] = []
    errors: list[str] = []

    manager = _create_round_robin_manager(results, errors)

    loop = asyncio.get_running_loop()
    def process_payload(station: str, _topic: str, payload: bytes) -> None:
        ntrip_manager.feed_data(station, payload)
        loop.call_soon_threadsafe(
            lambda: manager.add_agrica_payload(
                payload.decode("utf-8", errors="ignore"),
                {"project_id": PROJECT_ID, "station_id": selected_stations[station], "station_code": station},
            )
        )

    feed = LiveFeed(manager, payload_callback=process_payload, topics=selected_topics)
    feed.start()
    try:
        if args.restore_only:
            if len(selected_stations) != 1:
                raise RuntimeError("--restore-only requires exactly one station")
            return await _handle_rover_restore(manager, next(iter(selected_stations)), feed)

        print(f"[{ts()}] MQTT connected; sampling live fixed-base identity ...", flush=True)
        observations = await _sample_live_agrica_observations(feed, selected_stations, args.preflight_seconds)
        for station, obs in observations.items():
            print(f"[{ts()}] SEED LIVE {station}: pos_type={obs.position_type}, baseline={obs.baseline_neu}", flush=True)

        base_station, base_server_id, base_llh = await asyncio.to_thread(_resolve_cors_base_config, manager, args.base)
        _configure_probe_manager(manager, args, selected_stations, base_station, base_server_id, base_llh)

        topology = await manager.prepare_common_fixed_base_seed(PROJECT_ID)
        print(f"[{ts()}] COMMON BASE TOPOLOGY: {topology}", flush=True)
        print(f"[{ts()}] Collecting source/length-verified live seed ...", flush=True)
        await _wait_for_seed_collection(manager, PROJECT_ID, args.seed_timeout_seconds)

        print(f"[{ts()}] STARTING FULL LOCAL ROUND-ROBIN + SOLVER", flush=True)
        await manager._run_cycle(PROJECT_ID)

        if errors:
            print(f"[{ts()}] FINAL ERROR: {errors[-1]}", flush=True)
            return 1
        if not results:
            print(f"[{ts()}] FINAL ERROR: cycle returned without result", flush=True)
            return 1

        _write_probe_outputs(results[-1], args.output, args.xlsx_output)
        return 0
    finally:
        try:
            await manager.restore_common_fixed_base_topology(PROJECT_ID)
        except Exception:
            logging.exception("Failed to restore common SinQuyen topology")
        for station in selected_stations:
            try:
                await ntrip_manager.stop_pusher(station)
            except Exception:
                logging.exception("Failed to stop local NTRIP pusher for %s", station)
        feed.stop()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    raise SystemExit(asyncio.run(main()))
