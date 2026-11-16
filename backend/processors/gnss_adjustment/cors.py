"""Round-Robin cors responsibilities."""

from __future__ import annotations

import asyncio
import copy
import inspect
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

PUBLIC_MAP_STATIONS_ENDPOINT = "/api/public/map-stations"

class RoundRobinCorsMixin:
    def _cors_api_request_sync(
        self,
        method: str,
        path: str,
        payload: Optional[dict] = None,
        *,
        access_token: Optional[str] = None,
        _auth_retried: bool = False,
    ) -> Any:
        if path == PUBLIC_MAP_STATIONS_ENDPOINT:
            access_token = access_token or self._cors_token_sync()
            path = (
                "/api/integrations/stations"
                if access_token.startswith("cors_") else "/api/map/stations"
            )
        elif path.startswith("/api/devices/") and path.endswith("/configure-service") and access_token and access_token.startswith("cors_"):
            path = path.replace("/api/devices/", "/api/integrations/stations/", 1)
        url = f"{self.web_cors_api_base_url}{path}"
        headers = {"Accept": "application/json"}
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        request = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method=method.upper(),
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = response.read().decode("utf-8", errors="replace")
                if response.status < 200 or response.status >= 300:
                    raise RuntimeError(f"CORS API HTTP {response.status} for {path}")
        except urllib.error.HTTPError as exc:
            if (path == "/api/map/stations" and exc.code == 401
                    and not _auth_retried and self.web_cors_api_username):
                self._web_cors_access_token = ""
                return self._cors_api_request_sync(
                    method, path, payload,
                    access_token=self._cors_token_sync(force_login=True),
                    _auth_retried=True,
                )
            # Bound proxy responses before decoding; retain API validation details.
            with exc:
                detail = exc.read(2048).decode("utf-8", errors="replace").strip()
            if not detail or detail.startswith("<"):
                detail = str(exc.reason or "HTTP request failed")
            detail = " ".join(detail.split())[:500]
            raise RuntimeError(
                f"CORS API HTTP {exc.code} for {path}: {detail or exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"CORS API unavailable for {path}: {exc.reason}") from exc
        if not body.strip():
            return {}
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"CORS API returned non-JSON data for {path}") from exc


    def _cors_token_sync(self, *, force_login: bool = False) -> str:
        if self._web_cors_access_token and not force_login:
            return self._web_cors_access_token
        if not self.web_cors_api_username or not self.web_cors_api_password:
            raise RuntimeError(
                "WEB CORS API credentials are not configured; set WEB_CORS_API_TOKEN or "
                "WEB_CORS_API_USERNAME/WEB_CORS_API_PASSWORD"
            )
        login_result = self._cors_api_request_sync(
            "POST",
            "/api/auth/login",
            {
                "username": self.web_cors_api_username,
                "password": self.web_cors_api_password,
            },
        )
        token = str((login_result or {}).get("access_token") or "").strip()
        if not token:
            raise RuntimeError("CORS login succeeded without an access_token")
        self._web_cors_access_token = token
        return token


    def _cors_configure_service_sync(self, serial: str, service_config: dict) -> dict:
        path = f"/api/devices/{urllib.parse.quote(str(serial), safe='')}/configure-service"
        token = self._cors_token_sync()
        try:
            result = self._cors_api_request_sync(
                "POST",
                path,
                service_config,
                access_token=token,
            )
        except RuntimeError as exc:
            if "HTTP 401" not in str(exc) or not self.web_cors_api_username:
                raise
            self._web_cors_access_token = ""
            result = self._cors_api_request_sync(
                "POST",
                path,
                service_config,
                access_token=self._cors_token_sync(force_login=True),
            )
        if (result or {}).get("status") != "service_config_sent_and_saved":
            raise RuntimeError(
                f"CORS configure-service did not confirm device {serial}: "
                f"status={(result or {}).get('status') or 'missing'}"
            )
        return result


    @staticmethod
    def _cors_service_config_with_server_enabled(
        service_config: dict,
        server_id: Optional[int],
        *,
        enabled: bool,
    ) -> dict:
        """Hard-enable or hard-disable CORS outputs without stream sleep modes."""

        cfg = copy.deepcopy(service_config or {})
        target_sids = [1, 2] if server_id is None else [server_id]
        for sid in target_sids:
            cfg[f"server{sid}_enabled"] = bool(enabled)
        return cfg


    @staticmethod
    def _normalize_stream_host(value: Any) -> str:
        raw = str(value or "").strip().lower()
        if not raw:
            return ""
        parsed = urllib.parse.urlsplit(
            raw if "://" in raw else f"//{raw}",
            allow_fragments=False,
        )
        return str(parsed.hostname or raw).strip().lower().rstrip(".")


    def _find_cors_station_sync(
        self,
        mountpoint: str,
        selected_host: str,
        selected_serial: str = "",
        selected_server_id: Optional[int] = None,
    ) -> tuple[str, int, dict]:
        stations = self._cors_api_request_sync("GET", PUBLIC_MAP_STATIONS_ENDPOINT)
        if isinstance(stations, dict):
            stations = stations.get("value") or stations.get("items") or []
        target = str(mountpoint or "").strip().casefold()
        target_host = self._normalize_stream_host(selected_host)
        target_serial = str(selected_serial or "").strip().casefold()
        try:
            target_server_id = (
                int(selected_server_id) if selected_server_id not in (None, "") else None
            )
        except (TypeError, ValueError):
            target_server_id = None
        matches = []
        for station in stations or []:
            if not isinstance(station, dict):
                continue
            cfg = station.get("service_config")
            if not isinstance(cfg, dict):
                continue
            station_serial = str(station.get("serial") or "").strip()
            if target_serial and station_serial.casefold() != target_serial:
                continue
            for sid in (1, 2):
                if target_server_id is not None and sid != target_server_id:
                    continue
                candidate = str(cfg.get(f"mountpoint{sid}") or "").strip().casefold()
                candidate_host = self._normalize_stream_host(
                    cfg.get(f"serverhost{sid}") or cfg.get(f"server{sid}_host")
                )
                if (
                    candidate
                    and candidate == target
                    and (not target_host or candidate_host == target_host)
                ):
                    matches.append((station_serial, sid, cfg))
        if len(matches) != 1 or not matches[0][0]:
            raise RuntimeError(
                f"WEB CORS host={selected_host!r} mountpoint={mountpoint!r} "
                f"serial={selected_serial!r} S{selected_server_id or '*'} matched "
                f"{len(matches)} streams; expected exactly one"
            )
        return matches[0]


    def _disable_conflict_base_sync(self, serial: str) -> Optional[dict]:
        stations = self._cors_api_request_sync("GET", PUBLIC_MAP_STATIONS_ENDPOINT)
        if isinstance(stations, dict):
            stations = stations.get("value") or stations.get("items") or []
        for station in stations or []:
            if not isinstance(station, dict):
                continue
            station_serial = str(station.get("serial") or "").strip()
            if station_serial.casefold() == serial.casefold():
                cfg = station.get("service_config")
                if not isinstance(cfg, dict):
                    return None
                original = copy.deepcopy(cfg)
                new_cfg = self._cors_service_config_with_server_enabled(
                    cfg,
                    None,
                    enabled=False,
                )
                self._cors_configure_service_sync(station_serial, new_cfg)
                return original
        logger.warning(f"Could not find conflict base with serial {serial} to disable")
        return None


    async def _set_cors_fixed_base_enabled(
        self,
        mountpoint: str,
        enabled: bool,
        selected_host: str = "",
        selected_serial: str = "",
        selected_server_id: Optional[int] = None,
        all_streams: bool = False,
    ) -> None:
        # configure-service replaces the whole device config. Serialize its
        # read/modify/write with other clusters and the failover daemon.
        async with self._cors_topology_lock:
            await self._set_cors_fixed_base_enabled_unlocked(
                mountpoint, enabled, selected_host, selected_serial,
                selected_server_id, all_streams,
            )

    async def _set_cors_fixed_base_enabled_unlocked(
        self, mountpoint, enabled, selected_host, selected_serial,
        selected_server_id, all_streams,
    ) -> None:
        if not mountpoint:
            return
        snapshot_key = (
            self._normalize_stream_host(selected_host),
            str(mountpoint).strip().casefold(),
            str(selected_serial or "").strip().casefold(),
            int(selected_server_id) if selected_server_id not in (None, "") else 0,
        )
        if not enabled:
            snapshot = self._cors_fixed_base_snapshots.get(snapshot_key)
            if snapshot and snapshot["confirmed_disabled"]:
                return
            if snapshot:
                serial = snapshot["serial"]
                server_id = snapshot["server_id"]
                original = copy.deepcopy(snapshot["service_config"])
                disabled_server_ids = snapshot["disabled_server_ids"]
            else:
                serial, server_id, original = await asyncio.to_thread(
                    self._find_cors_station_sync,
                    mountpoint,
                    selected_host,
                    selected_serial,
                    selected_server_id,
                )
                # A peer may already have disabled S1 when this job snapshots S2.
                # Retain the original flags so the final release restores both.
                peers = [peer for peer in self._cors_fixed_base_snapshots.values()
                         if peer["serial"].casefold() == serial.casefold()]
                for peer in peers:
                    for sid in peer["disabled_server_ids"]:
                        flag = f"server{sid}_enabled"
                        if flag in peer["service_config"]:
                            original[flag] = peer["service_config"][flag]
                        else:
                            original.pop(flag, None)
                disabled_server_ids = (1, 2) if all_streams else (server_id,)
                snapshot = {
                    "serial": serial,
                    "server_id": server_id,
                    "service_config": copy.deepcopy(original),
                    "disabled_server_ids": disabled_server_ids,
                    "confirmed_disabled": False,
                }
                self._cors_fixed_base_snapshots[snapshot_key] = snapshot
            peers = [peer for key, peer in self._cors_fixed_base_snapshots.items()
                     if key != snapshot_key and peer["serial"].casefold() == serial.casefold()]
            disabled_config = self._cors_service_config_with_server_enabled(
                original,
                None if all_streams else server_id,
                enabled=False,
            )
            for peer in peers:
                for sid in peer["disabled_server_ids"]:
                    disabled_config[f"server{sid}_enabled"] = False
            await asyncio.to_thread(
                self._cors_configure_service_sync,
                serial,
                disabled_config,
            )
            # The API confirms dispatch, not device application. SOURCE startup
            # must still prove the selected caster has released the mountpoint.
            snapshot["confirmed_disabled"] = True
            logger.info(
                "WEB CORS configure-service sent fixed-base disable request %s host=%s serial=%s S%s; awaiting SOURCE mountpoint release",
                mountpoint,
                selected_host,
                serial,
                server_id,
            )
            return

        snapshot = self._cors_fixed_base_snapshots.get(snapshot_key)
        if snapshot is None:
            logger.warning(
                "No WEB CORS hard-disable snapshot exists for host=%s fixed base=%s",
                selected_host,
                mountpoint,
            )
            return
        restored_config = copy.deepcopy(snapshot["service_config"])
        for peer_key, peer in self._cors_fixed_base_snapshots.items():
            if peer_key != snapshot_key and peer["serial"].casefold() == snapshot["serial"].casefold():
                for sid in peer["disabled_server_ids"]:
                    restored_config[f"server{sid}_enabled"] = False
        await asyncio.to_thread(
            self._cors_configure_service_sync,
            snapshot["serial"],
            restored_config,
        )
        self._cors_fixed_base_snapshots.pop(snapshot_key, None)
        logger.info(
            "WEB CORS configure-service restored fixed base %s host=%s serial=%s S%s",
            mountpoint,
            selected_host,
            snapshot["serial"],
            snapshot["server_id"],
        )


    @staticmethod
    def _cors_station_is_online(station: dict) -> bool:
        """Interpret physical receiver availability from WEB CORS map data."""

        for key in ("is_online", "online", "device_online"):
            if isinstance(station.get(key), bool):
                return bool(station[key])
        status = str(station.get("status") or "").strip().casefold()
        if status:
            return status in {"online", "active", "connected", "streaming"}
        return bool(station.get("ntrip_connected"))


    def _cors_stream_is_managed_by_adjustment(
        self,
        serial: str,
        _server_id: int,
    ) -> bool:
        target_serial = str(serial or "").strip().casefold()
        # Even a single-stream hold owns a full configure-service document.
        # Failover must not overwrite it via the other stream of this receiver.
        fixed_stream_is_managed = any(
            str(snapshot["serial"]).strip().casefold() == target_serial
            for snapshot in self._cors_fixed_base_snapshots.values()
        )
        if fixed_stream_is_managed:
            return True
        return any(
            target_serial in session.get("seed_topology_managed_serials", set())
            for session in self._sessions.values()
        )


    @staticmethod
    def _cors_server_enabled(service_config: dict, server_id: int) -> bool:
        return bool(service_config.get(f"server{server_id}_enabled", False))


    @staticmethod
    def _cors_effective_service_config(
        station: dict,
        fallback: Optional[dict] = None,
    ) -> dict:
        """Combine saved config with the live per-stream map representation.

        Newer CORS map payloads expose part of S1/S2 in ``streams`` while older
        payloads put everything in ``service_config``.  The adjustment used to
        inspect only the latter, which could reject a healthy dual-output base.
        Live stream metadata takes precedence over the project snapshot, while
        explicit service-config fields remain authoritative.
        """

        cfg = copy.deepcopy(fallback or {})
        for position, stream in enumerate(
            station.get("streams") if isinstance(station.get("streams"), list) else [],
            start=1,
        ):
            if not isinstance(stream, dict):
                continue
            raw_server_id = stream.get("server_id")
            if raw_server_id in (None, ""):
                digits = "".join(
                    char for char in str(stream.get("stream_id") or "") if char.isdigit()
                )
                raw_server_id = digits or position
            try:
                server_id = int(raw_server_id)
            except (TypeError, ValueError):
                continue
            if server_id not in (1, 2):
                continue

            mountpoint = str(stream.get("mountpoint") or "").strip()
            host = str(stream.get("host") or stream.get("server_host") or "").strip()
            if mountpoint:
                cfg[f"mountpoint{server_id}"] = mountpoint
            if host:
                cfg[f"serverhost{server_id}"] = host
            if stream.get("port") not in (None, ""):
                cfg[f"serverport{server_id}"] = stream["port"]
            if isinstance(stream.get("enabled"), bool):
                cfg[f"server{server_id}_enabled"] = stream["enabled"]

        live_config = station.get("service_config")
        if isinstance(live_config, dict):
            cfg.update(copy.deepcopy(live_config))
        return cfg


    def _cors_failover_stream(
        self,
        stations: list[dict],
        *,
        station_name: str,
        serial: str,
        server_id: Any,
        host: str,
        mountpoint: str,
    ) -> Optional[tuple[dict, int]]:
        target_name = str(station_name or "").strip().casefold()
        target_serial = str(serial or "").strip().casefold()
        target_host = self._normalize_stream_host(host)
        target_mountpoint = str(mountpoint or "").strip().casefold()
        try:
            target_server_id = int(server_id)
        except (TypeError, ValueError):
            target_server_id = 0
        matches: list[tuple[dict, int]] = []
        for station in stations:
            if not isinstance(station, dict):
                continue
            candidate_serial = str(station.get("serial") or "").strip().casefold()
            candidate_name = str(
                station.get("name") or station.get("code") or ""
            ).strip().casefold()
            if target_serial:
                if candidate_serial != target_serial:
                    continue
            elif target_name and candidate_name != target_name:
                continue
            config = self._cors_effective_service_config(station)
            if not config:
                continue
            for candidate_server_id in (1, 2):
                if target_server_id and candidate_server_id != target_server_id:
                    continue
                candidate_host = self._normalize_stream_host(
                    config.get(f"serverhost{candidate_server_id}")
                    or config.get(f"server{candidate_server_id}_host")
                )
                candidate_mountpoint = str(
                    config.get(f"mountpoint{candidate_server_id}") or ""
                ).strip().casefold()
                if target_host and candidate_host != target_host:
                    continue
                if target_mountpoint and candidate_mountpoint != target_mountpoint:
                    continue
                matches.append((station, candidate_server_id))
        return matches[0] if len(matches) == 1 else None


    async def reconcile_cors_failover_pairs(
        self,
        clusters: list[dict],
        *,
        stations: Optional[list[dict]] = None,
    ) -> list[dict]:
        async with self._cors_topology_lock:
            return await self._reconcile_cors_failover_pairs_unlocked(
                clusters,
                stations=stations,
            )


    async def _reconcile_cors_failover_pairs_unlocked(
        self,
        clusters: list[dict],
        *,
        stations: Optional[list[dict]] = None,
    ) -> list[dict]:
        """Keep each primary S1 / cross-station backup S2 pair mutually exclusive.

        Example: SinQuyen1/S1 normally owns mountpoint SinQuyen1.  If its
        receiver is offline, SinQuyen2/S2 is hard-enabled and feeds that same
        mountpoint. Once SinQuyen1 is online again,
        the backup is stopped before S1 is restored.
        """

        if stations is None:
            stations = await asyncio.to_thread(
                self._cors_api_request_sync,
                "GET",
                PUBLIC_MAP_STATIONS_ENDPOINT,
            )
        if isinstance(stations, dict):
            stations = stations.get("value") or stations.get("items") or []
        stations = [item for item in (stations or []) if isinstance(item, dict)]
        outcomes: list[dict] = []
        for cluster in clusters or []:
            if not isinstance(cluster, dict) or not cluster.get("backup_base_station"):
                continue
            primary = self._cors_failover_stream(
                stations,
                station_name=cluster.get("base_station"),
                serial=cluster.get("base_serial"),
                server_id=cluster.get("base_server_id"),
                host=cluster.get("base_stream_host"),
                mountpoint=cluster.get("base_stream_mp"),
            )
            backup = self._cors_failover_stream(
                stations,
                station_name=cluster.get("backup_base_station"),
                serial=cluster.get("backup_base_serial"),
                server_id=cluster.get("backup_base_server_id"),
                host=cluster.get("backup_base_stream_host"),
                mountpoint=cluster.get("backup_base_stream_mp"),
            )
            name = str(cluster.get("name") or "GNSS cluster")
            if primary is None or backup is None:
                outcomes.append({"cluster": name, "state": "INVALID_STREAM_IDENTITY"})
                continue
            primary_station, primary_server_id = primary
            backup_station, backup_server_id = backup
            primary_serial = str(primary_station.get("serial") or "").strip()
            backup_serial = str(backup_station.get("serial") or "").strip()
            primary_mp = str(cluster.get("base_stream_mp") or "").strip()
            backup_mp = str(cluster.get("backup_base_stream_mp") or "").strip()
            if not primary_mp or primary_mp.casefold() != backup_mp.casefold():
                outcomes.append({"cluster": name, "state": "MOUNTPOINT_MISMATCH"})
                continue
            if (
                self._cors_stream_is_managed_by_adjustment(primary_serial, primary_server_id)
                or self._cors_stream_is_managed_by_adjustment(backup_serial, backup_server_id)
            ):
                outcomes.append({"cluster": name, "state": "PAUSED_FOR_ADJUSTMENT"})
                continue

            primary_online = self._cors_station_is_online(primary_station)
            backup_online = self._cors_station_is_online(backup_station)
            pair_key = (
                primary_serial.casefold(),
                primary_server_id,
                backup_serial.casefold(),
                backup_server_id,
                primary_mp.casefold(),
            )
            previous_state = self._cors_failover_last_state.get(pair_key)
            change_started_at = time.time()
            configuration_changed = False

            if not primary_online and not backup_online:
                desired_state = "NO_SOURCE_BOTH_OFFLINE"
                self._cors_failover_last_state[pair_key] = desired_state
                outcomes.append({"cluster": name, "state": desired_state})
                continue

            if not primary_online:
                desired_state = "BACKUP_ACTIVE"
                backup_config = self._cors_effective_service_config(backup_station)
                if not self._cors_server_enabled(backup_config, backup_server_id):
                    enabled_config = self._cors_service_config_with_server_enabled(
                        backup_config,
                        backup_server_id,
                        enabled=True,
                    )
                    await asyncio.to_thread(
                        self._cors_configure_service_sync,
                        backup_serial,
                        enabled_config,
                    )
                    backup_station["service_config"] = enabled_config
                    configuration_changed = True
                    logger.warning(
                        "CORS automatic failover: %s offline; enabled %s/S%s -> %s",
                        cluster.get("base_station"),
                        cluster.get("backup_base_station"),
                        backup_server_id,
                        primary_mp,
                    )
            else:
                desired_state = "PRIMARY_ACTIVE"
                # Break-before-make on failback: never leave S1 and backup S2
                # publishing the same mountpoint concurrently.
                backup_config = self._cors_effective_service_config(backup_station)
                if self._cors_server_enabled(backup_config, backup_server_id):
                    disabled_config = self._cors_service_config_with_server_enabled(
                        backup_config,
                        backup_server_id,
                        enabled=False,
                    )
                    await asyncio.to_thread(
                        self._cors_configure_service_sync,
                        backup_serial,
                        disabled_config,
                    )
                    backup_station["service_config"] = disabled_config
                    configuration_changed = True
                primary_config = self._cors_effective_service_config(primary_station)
                if not self._cors_server_enabled(primary_config, primary_server_id):
                    enabled_config = self._cors_service_config_with_server_enabled(
                        primary_config,
                        primary_server_id,
                        enabled=True,
                    )
                    await asyncio.to_thread(
                        self._cors_configure_service_sync,
                        primary_serial,
                        enabled_config,
                    )
                    primary_station["service_config"] = enabled_config
                    configuration_changed = True
                    logger.info(
                        "CORS automatic failback: restored %s/S%s -> %s and stopped %s/S%s",
                        cluster.get("base_station"),
                        primary_server_id,
                        primary_mp,
                        cluster.get("backup_base_station"),
                        backup_server_id,
                    )

            self._cors_failover_last_state[pair_key] = desired_state
            if (self.reference_change_callback and configuration_changed
                    and previous_state != desired_state):
                # Publish only after every required control operation succeeded.
                # Repeated writes from a stale CORS map are not new handovers.
                result = self.reference_change_callback(
                    cluster, change_started_at, f"cors_failover:{desired_state}",
                )
                if inspect.isawaitable(result):
                    await result
            outcomes.append({
                "cluster": name,
                "state": desired_state,
                "primary_online": primary_online,
                "backup_online": backup_online,
                "mountpoint": primary_mp,
                "primary_station": str(cluster.get("base_station") or ""),
                "primary_serial": primary_serial,
                "primary_server_id": primary_server_id,
                "backup_station": str(cluster.get("backup_base_station") or ""),
                "backup_serial": backup_serial,
                "backup_server_id": backup_server_id,
            })
        return outcomes
