"""Run the production Round-Robin adjustment locally against live Dam 1 MQTT data."""

from __future__ import annotations

import asyncio
import argparse
import json
import logging
import shutil
import sys
import time
from pathlib import Path

from backend.app.config import settings
from backend.app.modules.ntrip_pusher import ntrip_manager
from backend.processors.gnss_adjustment_runtime import parse_agrica
from backend.processors.round_robin_manager import RoundRobinAdjustmentManager
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


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stations",
        nargs="+",
        choices=sorted(STATIONS),
        default=list(STATIONS),
    )
    parser.add_argument("--base", default="SinQuyen2")
    parser.add_argument("--cluster-name", default="Sin Quyen live local probe")
    parser.add_argument("--preflight-seconds", type=float, default=30.0)
    parser.add_argument("--seed-timeout-seconds", type=float, default=180.0)
    parser.add_argument("--restore-only", action="store_true")
    parser.add_argument(
        "--output",
        default="live_full_adjustment_result.json",
        help="Write the complete successful adjustment result as JSON.",
    )
    parser.add_argument(
        "--xlsx-output",
        default="",
        help="Also write the production adjustment workbook to this path.",
    )
    args = parser.parse_args()
    selected_stations = {
        station: STATIONS[station]
        for station in dict.fromkeys(args.stations)
    }
    selected_topics = {
        topic: station
        for topic, station in TOPICS.items()
        if station in selected_stations
    }
    results: list[dict] = []
    errors: list[str] = []

    async def progress_callback(_project_id: int, message: str) -> None:
        print(f"[{ts()}] PHASE: {message}", flush=True)

    async def result_callback(_project_id: int, result: dict) -> None:
        results.append(result)
        quality = result.get("quality") or {}
        print(
            f"[{ts()}] RESULT: rover_count={result.get('rover_count')} "
            f"baselines={len(result.get('baselines') or [])} "
            f"loops={len(result.get('loops') or [])} "
            f"cross_observations={quality.get('observation_baseline_count')} "
            f"variance_factor={quality.get('variance_factor')}",
            flush=True,
        )

    async def error_callback(_project_id: int, message: str) -> None:
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
        try:
            await ntrip_manager.wait_for_rtcm(station, timeout=25.0)
        except Exception:
            diagnostic = ntrip_manager.get_diagnostics(station)
            print(f"[{ts()}] ROUTE DIAGNOSTIC {station}: {diagnostic}", flush=True)
            await ntrip_manager.stop_pusher(station)
            raise
        print(
            f"[{ts()}] ROUTE VERIFIED {station}: "
            f"{ntrip_manager.get_diagnostics(station)}",
            flush=True,
        )
        return True

    async def route_stop(station: str) -> None:
        await ntrip_manager.stop_pusher(station)
        print(f"[{ts()}] ROUTE STOP: {station}", flush=True)

    hosts = [
        host.strip()
        for host in settings.NTRIP_CONTROL_HOSTS.split(",")
        if host.strip()
    ]
    manager = RoundRobinAdjustmentManager(
        _UnusedPublisher(),
        caster_host=hosts[0],
        caster_hosts=hosts,
        caster_port=settings.NTRIP_CONTROL_PORT,
        source_host=settings.NTRIP_SOURCE_HOST,
        source_port=settings.NTRIP_SOURCE_PORT,
        control_password=settings.NTRIP_CONTROL_PASSWORD,
        source_password=settings.NTRIP_SOURCE_PASSWORD,
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
                    "station_id": selected_stations[station],
                    "station_code": station,
                },
            )

        loop.call_soon_threadsafe(ingest)

    feed = LiveFeed(
        manager,
        payload_callback=process_payload,
        topics=selected_topics,
    )
    feed.start()
    try:
        if args.restore_only:
            if len(selected_stations) != 1:
                raise RuntimeError("--restore-only requires exactly one station")
            station = next(iter(selected_stations))
            await asyncio.sleep(3)
            client_info = await manager._find_client_info(station)
            if not client_info:
                raise RuntimeError(
                    f"No active AICaster session is available to restore {station}"
                )
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
            raise RuntimeError(
                f"{station} acknowledged ROVER restore but emitted no fresh AGRICA"
            )

        print(f"[{ts()}] MQTT connected; sampling live fixed-base identity ...", flush=True)
        deadline = time.monotonic() + max(5.0, args.preflight_seconds)
        observations = {}
        while time.monotonic() < deadline:
            for station, station_id in selected_stations.items():
                with feed.lock:
                    latest = feed.latest_agrica.get(station)
                if not latest:
                    continue
                parsed = parse_agrica(
                    latest[1],
                    project_id=PROJECT_ID,
                    station_id=station_id,
                    rover_name=station,
                )
                if parsed and parsed[-1].rover_llh and parsed[-1].base_llh:
                    observations[station] = parsed[-1]
            if len(observations) == len(selected_stations):
                break
            await asyncio.sleep(0.25)
        if len(observations) != len(selected_stations):
            missing = sorted(set(selected_stations) - set(observations))
            raise RuntimeError(f"Missing complete live AGRICA from: {', '.join(missing)}")

        for station, obs in observations.items():
            print(
                f"[{ts()}] SEED LIVE {station}: pos_type={obs.position_type}, "
                f"rover_llh={obs.rover_llh}, base_llh={obs.base_llh}, "
                f"baseline={obs.baseline_neu}, std={obs.std_neu}",
                flush=True,
            )

        cors_stations = await asyncio.to_thread(
            manager._cors_api_request_sync,
            "GET",
            "/api/public/map-stations",
        )
        if isinstance(cors_stations, dict):
            cors_stations = cors_stations.get("value") or cors_stations.get("items") or []
        base_station = next(
            (
                station
                for station in cors_stations
                if str(station.get("name") or station.get("code") or "").strip().casefold()
                == str(args.base).strip().casefold()
            ),
            None,
        )
        if base_station is None:
            raise RuntimeError(f"CORS base {args.base!r} was not found")
        base_config = base_station.get("service_config") or {}
        base_server_id = next(
            (
                server_id
                for server_id in (1, 2)
                if str(base_config.get(f"mountpoint{server_id}") or "").strip().casefold()
                == str(args.base).strip().casefold()
            ),
            None,
        )
        if base_server_id is None:
            raise RuntimeError(f"CORS base {args.base!r} has no matching S1/S2 mountpoint")
        base_llh = (
            float(base_station["lat"]),
            float(base_station["lon"]),
            float(base_station.get("alt") or 0.0),
        )
        print(
            f"[{ts()}] CORS SELECTED: {args.base} status={base_station.get('status')} "
            f"serial={base_station.get('serial')} S{base_server_id} LLH={base_llh}",
            flush=True,
        )

        manager.configure_project(
            PROJECT_ID,
            [{
                "name": str(args.cluster_name),
                "stations": list(selected_stations.values()),
                "rovers": list(selected_stations),
                "base_station": str(args.base),
                "base_lat": base_llh[0],
                "base_lon": base_llh[1],
                "base_alt": base_llh[2],
                "base_stream_host": str(base_config.get(f"serverhost{base_server_id}") or ""),
                "base_stream_port": int(base_config.get(f"port{base_server_id}") or 2101),
                "base_stream_mp": str(base_config.get(f"mountpoint{base_server_id}") or ""),
                "base_service_config": base_config,
                "base_serial": str(base_station.get("serial") or ""),
                "base_server_id": base_server_id,
                "round_robin_route_host": str(base_config.get(f"serverhost{base_server_id}") or ""),
                "round_robin_route_port": int(base_config.get(f"port{base_server_id}") or 2101),
                "round_robin_route_mountpoint": str(base_config.get(f"mountpoint{base_server_id}") or ""),
                "round_robin_route_password": settings.NTRIP_SOURCE_PASSWORD,
                "skip_offline_rovers": True,
            }],
        )

        topology = await manager.prepare_common_fixed_base_seed(PROJECT_ID)
        print(f"[{ts()}] COMMON BASE TOPOLOGY: {topology}", flush=True)

        print(f"[{ts()}] Collecting source/length-verified live seed ...", flush=True)
        seed_deadline = time.monotonic() + max(30.0, args.seed_timeout_seconds)
        while time.monotonic() < seed_deadline:
            status = manager.get_seed_collection_status(PROJECT_ID)
            if status.get("complete"):
                break
            await asyncio.sleep(0.5)
        else:
            status = manager.get_seed_collection_status(PROJECT_ID)
            cluster = manager._sessions[PROJECT_ID]["clusters"][0]
            rejected_ids = {
                int(station_id)
                for station_id in (
                    list(status.get("missing_station_ids") or ())
                    + list(status.get("silent_station_ids") or ())
                    + list(status.get("invalid_fix_station_ids") or ())
                )
            }
            retained_pairs = [
                (int(station_id), str(rover))
                for station_id, rover in zip(
                    cluster.get("stations") or (),
                    cluster.get("rovers") or (),
                )
                if int(station_id) not in rejected_ids
            ]
            if (
                cluster.get("skip_offline_rovers")
                and status.get("fallback_ready")
                and len(retained_pairs) >= 2
            ):
                cluster["stations"] = [item[0] for item in retained_pairs]
                cluster["rovers"] = [item[1] for item in retained_pairs]
                print(
                    f"[{ts()}] SEED SKIP OFFLINE/INVALID: station_ids="
                    f"{sorted(rejected_ids)}; continuing with "
                    f"{', '.join(cluster['rovers'])}",
                    flush=True,
                )
            else:
                raise RuntimeError(
                    f"Seed collection did not become ready: {status}"
                )
        cluster = manager._sessions[PROJECT_ID]["clusters"][0]
        print(
            f"[{ts()}] SEED READY: {manager.get_seed_collection_status(PROJECT_ID)}, "
            f"stored_observations={len(cluster['observations'])}",
            flush=True,
        )

        print(f"[{ts()}] STARTING FULL LOCAL ROUND-ROBIN + SOLVER", flush=True)
        await manager._run_cycle(PROJECT_ID)

        if errors:
            print(f"[{ts()}] FINAL ERROR: {errors[-1]}", flush=True)
            return 1
        if not results:
            print(f"[{ts()}] FINAL ERROR: cycle returned without result", flush=True)
            return 1

        result = results[-1]
        output_path = Path(args.output).resolve()
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        xlsx_output_path = None
        if args.xlsx_output:
            backend_directory = Path(__file__).resolve().parent / "backend"
            if str(backend_directory) not in sys.path:
                sys.path.insert(0, str(backend_directory))
            from mqtt_bridge import MQTTBridge

            report_bridge = MQTTBridge.__new__(MQTTBridge)
            generated_xlsx = report_bridge._append_adjustment_to_excel(
                PROJECT_ID,
                int(time.time()),
                result,
                "",
            )
            xlsx_output_path = Path(args.xlsx_output).resolve()
            xlsx_output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(generated_xlsx, xlsx_output_path)
        print(f"[{ts()}] FINAL SUCCESS", flush=True)
        print(f"[{ts()}] RESULT JSON: {output_path}", flush=True)
        if xlsx_output_path:
            print(f"[{ts()}] RESULT XLSX: {xlsx_output_path}", flush=True)
        for point_name, point in sorted((result.get("points") or {}).items()):
            print(
                f"  POINT {point_name}: adjusted={point.get('adjusted')} "
                f"std={point.get('standard_deviation')}",
                flush=True,
            )
        for loop_item in result.get("loops") or []:
            print(
                f"  LOOP {loop_item.get('loop')}: points={loop_item.get('points')} "
                f"observed_closure={loop_item.get('observed_closure')}",
                flush=True,
            )
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
