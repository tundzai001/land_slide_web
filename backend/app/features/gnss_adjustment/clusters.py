"""Cluster normalization and online-rover selection for GNSS adjustment."""

import copy
import math
from typing import Any, Optional

from ...runtime import mqtt_service
from ...shared.station_policy import get_offline_threshold


def _resolve_station_ids(tokens: Any, stations_by_id: dict, stations_by_code: dict) -> list[int]:
    resolved = []
    for token in tokens if isinstance(tokens, list) else []:
        station = None
        try:
            station = stations_by_id.get(int(token))
        except (TypeError, ValueError):
            station = stations_by_code.get(str(token).strip())
        if station and station.id not in resolved:
            resolved.append(int(station.id))
    return resolved


def _normalize_candidate(source: dict, role: str, index: int) -> dict:
    prefix = "" if role == "primary" else "backup_"
    try:
        latitude = float(source.get(f"{prefix}base_lat"))
        longitude = float(source.get(f"{prefix}base_lon"))
        altitude = float(source.get(f"{prefix}base_alt") or 0.0)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"GNSS cluster #{index + 1} {role} base is missing a valid coordinate"
        ) from exc
    if (
        not all(math.isfinite(value) for value in (latitude, longitude, altitude))
        or not -90.0 <= latitude <= 90.0
        or not -180.0 <= longitude <= 180.0
        or (
            abs(latitude) < 1e-12
            and abs(longitude) < 1e-12
            and abs(altitude) < 1e-12
        )
    ):
        raise ValueError(
            f"GNSS cluster #{index + 1} has an invalid {role} fixed-base coordinate"
        )
    return {
        "role": role,
        "base_station": str(source.get(f"{prefix}base_station") or "").strip(),
        "base_lat": latitude,
        "base_lon": longitude,
        "base_alt": altitude,
        "base_stream": str(source.get(f"{prefix}base_stream") or "").strip(),
        "base_stream_host": str(
            source.get(f"{prefix}base_stream_host") or ""
        ).strip(),
        "base_stream_port": source.get(f"{prefix}base_stream_port"),
        "base_stream_mp": str(
            source.get(f"{prefix}base_stream_mp") or ""
        ).strip(),
        "base_service_config": copy.deepcopy(
            source.get(f"{prefix}base_service_config") or {}
        ),
        "base_serial": str(
            source.get(f"{prefix}base_serial") or ""
        ).strip(),
        "base_server_id": source.get(f"{prefix}base_server_id"),
    }


def _validate_backup_candidate(primary: dict, backup: dict, index: int) -> None:
    if backup["base_station"].casefold() == primary["base_station"].casefold():
        raise ValueError(f"GNSS cluster #{index + 1} backup base must differ from its primary base")
    if not backup["base_stream_host"] or not backup["base_stream_mp"]:
        raise ValueError(
            f"GNSS cluster #{index + 1} backup base requires an explicit CORS stream host and mountpoint"
        )
    if backup["base_stream_mp"].casefold() != primary["base_stream_mp"].casefold():
        raise ValueError(f"GNSS cluster #{index + 1} backup S2 must publish the same mountpoint as primary S1")


def _extract_aicaster_users(station_ids: list[int], stations_by_id: dict) -> dict:
    aicaster_users = {}
    for station_id in station_ids:
        station = stations_by_id[station_id]
        station_config = station.config if isinstance(station.config, dict) else {}
        binding = (
            station_config.get("gnss_aicaster_user")
            or station_config.get("gnss_aicaster_client")
            or {}
        )
        username = str(binding.get("username") or "").strip()
        if username:
            aicaster_users[station.station_code] = {
                "username": username,
                "caster_host": str(binding.get("caster_host") or "").strip(),
            }
    return aicaster_users


def _build_cluster_entry(raw_cluster: Any, index: int, stations_by_id: dict, stations_by_code: dict) -> Optional[dict]:
    cluster = dict(raw_cluster) if isinstance(raw_cluster, dict) else {"stations": raw_cluster}
    station_ids = _resolve_station_ids(cluster.get("stations", []), stations_by_id, stations_by_code)
    if len(station_ids) < 2:
        return None

    primary = _normalize_candidate(cluster, "primary", index)
    candidates = [primary]
    if str(cluster.get("backup_base_station") or "").strip():
        backup = _normalize_candidate(cluster, "backup", index)
        _validate_backup_candidate(primary, backup, index)
        candidates.append(backup)

    cluster["stations"] = station_ids
    cluster["rovers"] = [stations_by_id[station_id].station_code for station_id in station_ids]
    cluster["aicaster_users"] = _extract_aicaster_users(station_ids, stations_by_id)
    cluster["fixed_base_candidates"] = candidates
    cluster["selected_fixed_base_candidate"] = copy.deepcopy(primary) if len(candidates) == 1 else None
    cluster.update({key: copy.deepcopy(value) for key, value in primary.items() if key != "role"})
    return cluster


def normalize_active_clusters(
    raw_clusters: Any,
    stations: list[Any],
    selected_clusters: Optional[list[list[int | str]]],
) -> list[dict]:
    """Resolve persisted station codes to IDs without losing base metadata."""

    stations_by_id = {int(station.id): station for station in stations}
    stations_by_code = {
        str(station.station_code).strip(): station
        for station in stations
        if getattr(station, "station_code", None)
    }

    configured = []
    for index, raw_cluster in enumerate(raw_clusters or []):
        cluster_entry = _build_cluster_entry(raw_cluster, index, stations_by_id, stations_by_code)
        if cluster_entry:
            configured.append(cluster_entry)

    if not configured:
        raise ValueError("project has no valid GNSS cluster with two rovers and a fixed base")
    if selected_clusters is None:
        return configured

    selected = [_resolve_station_ids(cluster, stations_by_id, stations_by_code) for cluster in selected_clusters]
    if not selected or any(len(cluster) < 2 for cluster in selected):
        raise ValueError("the selected GNSS cluster must contain at least two project stations")

    active = []
    for selected_station_ids in selected:
        target = set(selected_station_ids)
        match = next((cluster for cluster in configured if set(cluster["stations"]) == target), None)
        if match is None:
            raise ValueError(
                "the selected stations do not match a configured GNSS cluster; select the cluster connection on the map"
            )
        active.append(match)
    return active


def restrict_clusters_to_online_stations(
    clusters: list[dict],
    online_station_ids: set[int],
) -> tuple[list[dict], list[int]]:
    """Remove offline rovers while preserving station/code ordering per cluster."""

    active_clusters = []
    excluded_station_ids = []
    diagnostics = []
    for source in clusters:
        station_rover_pairs = list(zip(source["stations"], source["rovers"], strict=True))
        included = [
            (station_id, rover)
            for station_id, rover in station_rover_pairs
            if int(station_id) in online_station_ids
        ]
        excluded_station_ids.extend(
            int(station_id)
            for station_id, _ in station_rover_pairs
            if int(station_id) not in online_station_ids
        )
        diagnostics.append(
            f"{source.get('name') or 'cluster'}: "
            f"online={[str(rover) for _, rover in included]}, "
            f"offline={[str(rover) for station_id, rover in station_rover_pairs if int(station_id) not in online_station_ids]}"
        )
        if len(included) < 2:
            continue
        cluster = dict(source)
        cluster["stations"] = [int(station_id) for station_id, _ in included]
        cluster["rovers"] = [str(rover) for _, rover in included]
        active_clusters.append(cluster)

    if not active_clusters:
        raise ValueError(
            "fewer than two online GNSS rovers are available in the selected cluster; "
            + "; ".join(diagnostics)
        )
    return active_clusters, sorted(set(excluded_station_ids))


def streaming_gnss_station_ids(
    clusters: list[dict],
    stations_by_id: dict[int, Any],
) -> set[int]:
    """Return stations with a recent MQTT payload, independent of DB flush timing."""

    online = set()
    for cluster in clusters:
        for station_id, rover_code in zip(
            cluster.get("stations", []),
            cluster.get("rovers", []),
            strict=True,
        ):
            station_id = int(station_id)
            station = stations_by_id.get(station_id)
            if station is None:
                continue
            threshold = get_offline_threshold(station.config, "gnss")
            health = mqtt_service.round_robin_manager.get_gnss_stream_health(
                str(rover_code),
                freshness_seconds=float(threshold),
            )
            if health.get("payload_recent"):
                online.add(station_id)
    return online

