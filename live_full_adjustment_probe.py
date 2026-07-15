"""Run the production Round-Robin adjustment locally against live Dam 1 MQTT data."""

from __future__ import annotations

import asyncio
import logging
import statistics
import time

from backend.app.config import settings
from backend.app.modules.ntrip_pusher import ntrip_manager
from backend.processors.gnss_adjustment_runtime import parse_agrica
from backend.processors.round_robin_manager import RoundRobinAdjustmentManager
from live_base_output_probe import LiveFeed, _UnusedPublisher


PROJECT_ID = 9003
STATIONS = {
    "Dap1_1": 5,
    "Dap1_2": 7,
    "Dap1_3": 6,
    "Dap1_4": 4,
}


def ts() -> str:
    return time.strftime("%H:%M:%S")


async def main() -> int:
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
                    "station_id": STATIONS[station],
                    "station_code": station,
                },
            )

        loop.call_soon_threadsafe(ingest)

    feed = LiveFeed(manager, payload_callback=process_payload)
    feed.start()
    try:
        print(f"[{ts()}] MQTT connected; sampling live fixed-base identity ...", flush=True)
        deadline = time.monotonic() + 20
        observations = {}
        while time.monotonic() < deadline:
            for station, station_id in STATIONS.items():
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
            if len(observations) == len(STATIONS):
                break
            await asyncio.sleep(0.25)
        if len(observations) != len(STATIONS):
            missing = sorted(set(STATIONS) - set(observations))
            raise RuntimeError(f"Missing complete live AGRICA from: {', '.join(missing)}")

        base_llh = tuple(
            statistics.median(obs.base_llh[axis] for obs in observations.values())
            for axis in range(3)
        )
        print(f"[{ts()}] Fixed BASE LLH from live AGRICA: {base_llh}", flush=True)
        for station, obs in observations.items():
            print(
                f"[{ts()}] SEED LIVE {station}: pos_type={obs.position_type}, "
                f"rover_llh={obs.rover_llh}, base_llh={obs.base_llh}, "
                f"baseline={obs.baseline_neu}, std={obs.std_neu}",
                flush=True,
            )

        manager.configure_project(
            PROJECT_ID,
            [{
                "name": "Dam 1 live local probe",
                "stations": list(STATIONS.values()),
                "rovers": list(STATIONS),
                "base_station": "SinQuyen1",
                "base_lat": base_llh[0],
                "base_lon": base_llh[1],
                "base_alt": base_llh[2],
                "base_stream_host": "aitogy.com.vn",
                "base_stream_port": 2101,
                "base_stream_mp": "SinQuyen1",
                "round_robin_route_host": "aitogy.com.vn",
                "round_robin_route_port": 2101,
                "round_robin_route_mountpoint": "SinQuyen1",
                "round_robin_route_password": settings.NTRIP_SOURCE_PASSWORD,
            }],
        )

        print(f"[{ts()}] Collecting 10 live fixed-base seed epochs ...", flush=True)
        seed_deadline = time.monotonic() + 30
        while time.monotonic() < seed_deadline:
            status = manager.get_seed_collection_status(PROJECT_ID)
            if (
                status.get("complete")
                and int(status.get("step_count") or 0)
                >= int(status.get("max_steps") or 10)
            ):
                break
            await asyncio.sleep(0.5)
        else:
            raise RuntimeError(
                f"Seed collection did not become ready: "
                f"{manager.get_seed_collection_status(PROJECT_ID)}"
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
        print(f"[{ts()}] FINAL SUCCESS", flush=True)
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
        for station in STATIONS:
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
