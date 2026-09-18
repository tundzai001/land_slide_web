"""Round-Robin aicaster responsibilities."""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Any, Callable, Dict, Iterable, List, Optional
from .geometry import (
    _aggregate_parallel_baselines,
    _build_fundamental_loops,
    _canonical_baseline,
    _ecef_to_llh,
    _graph_components,
    _is_usable_llh,
    _llh_horizontal_distance_m,
    _neu_to_ecef_delta,
    _vector_length,
)

logger = logging.getLogger(__name__)

class RoundRobinAicasterMixin:
    async def _find_client_info(
        self,
        station_code: str,
        *,
        project_id: Optional[int] = None,
        log_missing: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """Find a rover across every configured AICaster client table."""

        candidates, successful_hosts, query_errors = await self._fetch_active_client_candidates()
        binding = self._configured_aicaster_user(project_id, station_code)
        configured_username = str(binding.get("username") or "").strip()
        configured_host = str(binding.get("caster_host") or "").strip()
        eligible_candidates = candidates
        if configured_host:
            eligible_candidates = [
                item
                for item in candidates
                if str(item.get("CasterHost") or "").casefold()
                == configured_host.casefold()
            ]

        lookup_name = configured_username or station_code
        selected = self._select_client_candidate(eligible_candidates, lookup_name)
        if selected:
            logger.info(
                "Matched station %s%s to AICaster %s:%s (username=%s receiverID=%s mountpoint=%s)",
                station_code,
                f" via configured username {configured_username}" if configured_username else "",
                selected["CasterHost"],
                selected["CasterPort"],
                selected["Username"],
                selected["receiverID"],
                selected["Mountpoint"],
            )
            return selected

        if not successful_hosts:
            raise RuntimeError(
                "Could not query any configured AICaster client table: "
                + "; ".join(query_errors)
            )
        if log_missing:
            logger.error(
                "No AICaster client session matched station %s (configured username=%s host=%s). "
                "Queried=%s errors=%s available=%s",
                station_code,
                configured_username or "<station-code fallback>",
                configured_host or "<any>",
                successful_hosts,
                query_errors,
                [
                    {
                        "host": item["CasterHost"],
                        "username": item["Username"],
                        "receiver_id": item["receiverID"],
                        "mountpoint": item["Mountpoint"],
                    }
                    for item in candidates
                ],
            )
        return None


    def _configured_aicaster_user(
        self,
        project_id: Optional[int],
        station_code: str,
    ) -> Dict[str, Any]:
        if project_id is None:
            return {}
        session = self._sessions.get(int(project_id)) or {}
        target = str(station_code or "").strip().casefold()
        for cluster in session.get("clusters", []):
            bindings = cluster.get("aicaster_users") or {}
            for code, binding in bindings.items():
                if str(code).strip().casefold() == target and isinstance(binding, dict):
                    return binding
        return {}


    async def _fetch_active_client_candidates(
        self,
    ) -> tuple[List[Dict[str, Any]], List[str], List[str]]:
        results = await asyncio.gather(
            *(self._query_client_table(host) for host in self.caster_hosts),
            return_exceptions=True,
        )
        candidates: List[Dict[str, Any]] = []
        query_errors: List[str] = []
        successful_hosts: List[str] = []
        for host, result in zip(self.caster_hosts, results):
            if isinstance(result, BaseException):
                detail = str(result).strip() or result.__class__.__name__
                query_errors.append(f"{host}:{self.caster_port} ({detail})")
                continue
            successful_hosts.append(host)
            candidates.extend(
                self._parse_client_table(
                    result,
                    caster_host=host,
                    caster_port=self.caster_port,
                )
            )
        return candidates, successful_hosts, query_errors


    async def list_aicaster_users(self) -> List[Dict[str, Any]]:
        """Return configured AICaster users without exposing their passwords."""

        results = await asyncio.gather(
            *(self._query_user_table(host) for host in self.caster_hosts),
            return_exceptions=True,
        )
        users: List[Dict[str, Any]] = []
        successful_hosts: List[str] = []
        query_errors: List[str] = []
        for host, result in zip(self.caster_hosts, results):
            if isinstance(result, BaseException):
                detail = str(result).strip() or result.__class__.__name__
                query_errors.append(f"{host}:{self.caster_port} ({detail})")
                continue
            successful_hosts.append(host)
            users.extend(
                self._parse_user_table(
                    result,
                    caster_host=host,
                    caster_port=self.caster_port,
                )
            )
        if not successful_hosts:
            raise RuntimeError(
                "Could not query any configured AICaster user table: "
                + "; ".join(query_errors)
            )
        unique: Dict[tuple[str, str], Dict[str, Any]] = {}
        for item in users:
            key = (
                str(item.get("CasterHost") or "").casefold(),
                str(item.get("Username") or "").casefold(),
            )
            unique[key] = item
        return sorted(
            unique.values(),
            key=lambda item: (
                str(item.get("CasterHost") or "").casefold(),
                str(item.get("Username") or "").casefold(),
            ),
        )


    def _observation_matches_active_base(
        self,
        cluster: dict,
        active_base: str,
        observation: Any,
    ) -> tuple[bool, str]:
        """Verify AGRICA's reported base coordinate before assigning an edge."""

        reported = observation.base_llh
        if active_base == "BASE":
            selected_candidate = cluster.get("selected_fixed_base_candidate")
            if not isinstance(selected_candidate, dict):
                selected_candidate, selection_diagnostic = (
                    self._identify_fixed_base_candidate(cluster, observation)
                )
                if selected_candidate is None:
                    return False, selection_diagnostic
                self._lock_fixed_base_candidate(
                    cluster,
                    selected_candidate,
                    selection_diagnostic,
                )
                logger.info(
                    "Fixed-base failover selection cluster=%s: %s",
                    cluster.get("name"),
                    selection_diagnostic,
                )
            try:
                expected = self._cluster_base_llh(cluster)
            except ValueError as exc:
                return False, f"cannot verify fixed BASE: {exc}"
        else:
            cached = (
                cluster.get("temporary_base_llh_by_rover", {}).get(active_base)
                or self.rover_llh_cache.get(active_base)
            )
            if not cached:
                return False, f"cannot verify temporary base {active_base}: LLH cache is unavailable"
            expected = (
                float(cached["lat"]),
                float(cached["lon"]),
                float(cached["alt"]),
            )

        if not _is_usable_llh(reported):
            if active_base == "BASE":
                # Several UM980 rover profiles emit zeroes for BASE_lat/lon/h.
                # Never treat that as proof that the correction source is the
                # configured fixed base: after a temporary-base route closes,
                # the receiver can retain a Fixed solution from that old RTCM
                # stream for tens of seconds. Verify the baseline length against
                # the configured fixed-base-to-rover geometry instead.
                rover_llh = getattr(observation, "rover_llh", None)
                baseline_neu = getattr(observation, "baseline_neu", None)
                if not rover_llh or not baseline_neu:
                    return False, (
                        f"rejected {observation.rover_name}: AGRICA has no usable base_llh, "
                        "and missing rover_llh or baseline_neu to verify configured fixed BASE"
                    )
                rover_to_fixed_dist = _llh_horizontal_distance_m(rover_llh, expected)
                baseline_horiz_len = math.hypot(baseline_neu[0], baseline_neu[1])
                fixed_error = abs(rover_to_fixed_dist - baseline_horiz_len)
                if fixed_error > self.BASE_IDENTITY_TOLERANCE_M:
                    return False, (
                        f"rejected {observation.rover_name}: AGRICA has no usable base_llh, "
                        f"and baseline length ({baseline_horiz_len:.1f} m) does not match "
                        f"distance to configured fixed BASE ({rover_to_fixed_dist:.1f} m; "
                        f"error {fixed_error:.2f} m). The receiver may still hold the "
                        "previous temporary-base Fixed solution"
                    )
                return True, (
                    "AGRICA has no usable base_llh; baseline geometry matches configured "
                    f"fixed BASE (error {fixed_error:.2f} m)"
                )
            rover_llh = getattr(observation, "rover_llh", None)
            baseline_neu = getattr(observation, "baseline_neu", None)
            if not rover_llh or not baseline_neu:
                return False, (
                    f"rejected {observation.rover_name}: AGRICA has no usable base_llh, "
                    f"and missing rover_llh or baseline_neu to verify expected base"
                )
            
            rover_to_expected_dist = _llh_horizontal_distance_m(rover_llh, expected)
            baseline_horiz_len = math.hypot(baseline_neu[0], baseline_neu[1])
            fixed_base = self._cluster_base_llh(cluster)
            rover_to_fixed_dist = _llh_horizontal_distance_m(rover_llh, fixed_base)
            expected_error = abs(rover_to_expected_dist - baseline_horiz_len)
            fixed_error = abs(rover_to_fixed_dist - baseline_horiz_len)

            if fixed_error + 1.0 < expected_error:
                return False, (
                    f"rejected {observation.rover_name}: baseline vector still matches fixed BASE; "
                    f"fixed-BASE error={fixed_error:.2f} m, temporary-base error={expected_error:.2f} m"
                )
            
            if expected_error > self.BASE_IDENTITY_TOLERANCE_M:
                return False, (
                    f"rejected {observation.rover_name}: missing base_llh, and baseline length "
                    f"({baseline_horiz_len:.1f} m) does not match distance to expected base {active_base} "
                    f"({rover_to_expected_dist:.1f} m)"
                )

            return True, (
                f"baseline vector matches temporary base {active_base} "
                f"(error {expected_error:.2f} m; fixed-BASE error={fixed_error:.2f} m)"
            )

        separation = _llh_horizontal_distance_m(reported, expected)
        height_delta = abs(float(reported[2]) - float(expected[2]))
        if active_base != "BASE":
            try:
                fixed_base = self._cluster_base_llh(cluster)
            except ValueError:
                fixed_base = None
            if fixed_base is not None:
                fixed_base_separation = _llh_horizontal_distance_m(reported, fixed_base)
                if fixed_base_separation + 1.0 < separation:
                    return False, (
                        f"rejected {observation.rover_name}: AGRICA base_llh matches fixed BASE "
                        f"({fixed_base_separation:.2f} m) more closely than temporary base "
                        f"{active_base} ({separation:.2f} m); correction source has not switched yet"
                    )
        if separation > self.BASE_IDENTITY_TOLERANCE_M:
            return False, (
                f"rejected {observation.rover_name}: AGRICA base_llh is {separation:.2f} m horizontally "
                f"from expected {active_base} (limit {self.BASE_IDENTITY_TOLERANCE_M:.1f} m); "
                "correction source has not switched yet or this is a transition fragment"
            )

        # A matching BASE_lat/lon alone is not enough during a caster handover:
        # a receiver can briefly combine a new/stale metadata sentence with a
        # baseline vector from the previous correction stream. Independently
        # estimate the horizontal base-to-rover distance and require the AGRICA
        # N/E vector length to agree before admitting this epoch to the seed.
        geometry_diagnostic = ""
        if active_base == "BASE" and cluster.get("require_fixed_base_length_check"):
            rover_llh = getattr(observation, "rover_llh", None)
            baseline_neu = getattr(observation, "baseline_neu", None)
            if not _is_usable_llh(rover_llh) or not baseline_neu:
                return False, (
                    f"rejected {observation.rover_name}: fixed-base identity matched, "
                    "but rover_llh or baseline_neu is unavailable for the mandatory "
                    "baseline-length handover check"
                )
            estimated_length = _llh_horizontal_distance_m(expected, rover_llh)
            measured_length = math.hypot(
                float(baseline_neu[0]),
                float(baseline_neu[1]),
            )
            length_error = abs(estimated_length - measured_length)
            if length_error > self.FIXED_BASE_LENGTH_TOLERANCE_M:
                return False, (
                    f"rejected {observation.rover_name}: base coordinate matches {active_base}, "
                    f"but baseline horizontal length is {measured_length:.1f} m while "
                    f"selected-base geometry estimates {estimated_length:.1f} m "
                    f"(error {length_error:.2f} m, limit "
                    f"{self.FIXED_BASE_LENGTH_TOLERANCE_M:.1f} m); rover is probably still "
                    "using the previous RTCM source"
                )
            geometry_diagnostic = (
                f", baseline length {measured_length:.1f}/{estimated_length:.1f} m "
                f"(error {length_error:.2f} m)"
            )
        return True, (
            f"verified base {active_base} (horizontal delta {separation:.2f} m, "
            f"height delta {height_delta:.2f} m{geometry_diagnostic})"
        )


    def _clear_cluster_fragment_buffers(self, project_id: int, cluster: dict) -> None:
        for station_id in cluster.get("stations", []):
            self._agrica_fragment_buffers.pop((int(project_id), int(station_id)), None)


    async def _query_client_table(self, caster_host: str) -> str:
        writer = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(caster_host, self.caster_port),
                timeout=10.0,
            )
            writer.write(b"GET /clienttable HTTP/1.0\r\n\r\n")
            await writer.drain()
            data = await asyncio.wait_for(reader.read(), timeout=10.0)
            return data.decode(errors="ignore")
        finally:
            if writer:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass


    async def _query_user_table(self, caster_host: str) -> str:
        writer = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(caster_host, self.caster_port),
                timeout=10.0,
            )
            writer.write(b"GET /usertable HTTP/1.0\r\n\r\n")
            await writer.drain()
            data = await asyncio.wait_for(reader.read(), timeout=10.0)
            return data.decode(errors="ignore")
        finally:
            if writer:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass


    @staticmethod
    def _parse_user_table(
        user_table: str,
        caster_host: Optional[str] = None,
        caster_port: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        users = []
        for line in user_table.strip().splitlines():
            parts = [part.strip() for part in line.split(";")]
            if len(parts) <= 3 or parts[0] != "STR" or not parts[1]:
                continue
            # parts[2] is the password. It is intentionally discarded here and
            # must never leave the backend API.
            users.append({
                "Username": parts[1],
                "Mountpoints": [
                    mountpoint.strip()
                    for mountpoint in parts[3].split(",")
                    if mountpoint.strip()
                ],
                "Status": parts[5] if len(parts) > 5 else "",
                "Identifier": parts[6] if len(parts) > 6 else "",
                "ActiveClientCount": parts[7] if len(parts) > 7 else "",
                "CasterHost": caster_host,
                "CasterPort": caster_port,
            })
        return users


    @staticmethod
    def _parse_client_table(
        client_table: str,
        caster_host: Optional[str] = None,
        caster_port: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        candidates = []
        for line in client_table.strip().splitlines():
            parts = [part.strip() for part in line.split(";")]
            if len(parts) <= 4 or parts[0] != "STR":
                continue
            candidates.append({
                "Username": parts[1],
                "receiverID": parts[2],
                "Mountpoint": parts[3],
                "CasterHost": caster_host,
                "CasterPort": caster_port,
            })
        return candidates


    @staticmethod
    def _select_client_candidate(
        candidates: List[Dict[str, Any]],
        station_code: str,
    ) -> Optional[Dict[str, Any]]:
        target = station_code.strip().lower()
        exact_matches = []
        fuzzy_matches = []
        for candidate in candidates:
            username = candidate["Username"]
            receiver_id = candidate["receiverID"]
            mountpoint = candidate["Mountpoint"]
            # Depending on the AICaster build, the station code can be exposed
            # as Username, receiverID, or Mountpoint.
            fields = {username.lower(), receiver_id.lower(), mountpoint.lower()}
            if target in fields:
                exact_matches.append(candidate)
            elif any(target in field for field in fields):
                fuzzy_matches.append(candidate)

        if exact_matches:
            return exact_matches[0]
        if len(fuzzy_matches) == 1:
            return fuzzy_matches[0]
        if len(fuzzy_matches) > 1:
            logger.error(
                "Ambiguous AICaster client sessions for %s: %s",
                station_code,
                [item["Mountpoint"] for item in fuzzy_matches],
            )
        return None


    @classmethod
    def _select_client_info(cls, client_table: str, station_code: str) -> Optional[Dict[str, Any]]:
        """Compatibility helper used by focused parser tests."""

        return cls._select_client_candidate(cls._parse_client_table(client_table), station_code)
