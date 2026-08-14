"""Round-robin observation and receiver-command state models."""
import asyncio
import copy
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


def requires_common_base_handover(cluster: dict) -> bool:
    """Return whether a cluster intentionally shares one physical seed base."""

    return str(cluster.get("cluster_type") or "normal").strip().lower() == "total"


class RoundRobinSessionLifecycleMixin:
    """Own session creation, cancellation, and station membership lookup."""

    def configure_project(self, project_id: int, clusters: list[dict]) -> None:
        prepared_clusters = []
        assigned_station_ids: set[int] = set()
        for raw_cluster in clusters or []:
            if not isinstance(raw_cluster, dict):
                continue
            station_ids = []
            for station_id in raw_cluster.get("stations", []):
                try:
                    station_ids.append(int(station_id))
                except (TypeError, ValueError):
                    continue
            station_ids = list(dict.fromkeys(station_ids))
            rover_codes = [
                str(code).strip()
                for code in raw_cluster.get("rovers", [])
                if str(code).strip()
            ]
            if len(station_ids) < 2:
                raise ValueError("each GNSS adjustment cluster needs at least two stations")
            if len(rover_codes) != len(station_ids):
                raise ValueError("cluster station IDs and rover codes are inconsistent")
            overlap = assigned_station_ids.intersection(station_ids)
            if overlap:
                raise ValueError(
                    f"a station cannot belong to more than one active cluster: {sorted(overlap)}"
                )
            assigned_station_ids.update(station_ids)
            cluster = dict(raw_cluster)
            cluster["stations"] = station_ids
            cluster["rovers"] = rover_codes
            cluster["observations"] = []
            prepared_clusters.append(cluster)

        if not prepared_clusters:
            raise ValueError("no valid GNSS adjustment clusters were supplied")
        self.clear_project(project_id)
        self._sessions[project_id] = {
            "clusters": prepared_clusters,
            "initial_clusters": copy.deepcopy(prepared_clusters),
            "active_bases": {},
            "seed_collection_steps": set(),
            "seed_window_states": {},
            "online_baseline_states": {},
            "seed_station_reports": {},
            "seed_started_monotonic": time.monotonic(),
            "control_state": "RUNNING",
            "resume_event": asyncio.Event(),
        }
        self._sessions[project_id]["resume_event"].set()

    def clear_project(self, project_id: int) -> None:
        task = self.running_tasks.pop(project_id, None)
        if task and not task.done():
            task.cancel()
        self._sessions.pop(project_id, None)
        self._last_ingest_diagnostics.pop(project_id, None)
        for key in [key for key in self._ingest_warning_last_logged if key[0] == project_id]:
            self._ingest_warning_last_logged.pop(key, None)
        for key in [key for key in self._agrica_fragment_buffers if key[0] == project_id]:
            self._agrica_fragment_buffers.pop(key, None)

    async def start_cycle(self, project_id: int) -> None:
        if project_id in self.running_tasks:
            logger.debug("RoundRobin cycle already running for project %s", project_id)
            return
        if project_id not in self._sessions:
            raise ValueError(f"project {project_id} has no configured adjustment session")
        self.running_tasks[project_id] = asyncio.create_task(self._run_cycle(project_id))

    def pause_project(self, project_id: int) -> bool:
        session = self._sessions.get(int(project_id))
        task = self.running_tasks.get(int(project_id))
        if session is None or (task is not None and task.done()):
            return False
        session["control_state"] = "PAUSED"
        session["resume_event"].clear()
        return True

    def resume_project(self, project_id: int) -> bool:
        session = self._sessions.get(int(project_id))
        task = self.running_tasks.get(int(project_id))
        if session is None or (task is not None and task.done()):
            return False
        session["control_state"] = "RUNNING"
        session["resume_event"].set()
        return True

    async def _wait_for_run_permission(self, project_id: Optional[int]) -> None:
        if project_id is None:
            return
        session = self._sessions.get(int(project_id))
        if session is None or session.get("control_state") != "PAUSED":
            return
        event = session.get("resume_event")
        if event is not None:
            await event.wait()

    @staticmethod
    def _cluster_index_for_station(session: dict, station_id: int) -> Optional[int]:
        for index, cluster in enumerate(session["clusters"]):
            if station_id in cluster["stations"]:
                return index
        return None

@dataclass
class _CollectedObservation:
    """An AGRICA observation tagged with the rover acting as its base."""

    base_name: str
    observation: Any
    solver_eligible: bool = True
    quality_flags: tuple[str, ...] = ()
    source_diagnostic: Optional[str] = None

    rotation_index: Optional[int] = None
    stable_window_index: Optional[int] = None
    vector_deviation_m: Optional[float] = None
    vector_filter_threshold_m: Optional[float] = None
    vector_filter_status: str = "SKIPPED_PRIOR_FILTER"

@dataclass
class _CommandAckWaiter:
    """One receiver command awaiting echo and ACK on its GNSS MQTT topic."""

    station_code: str
    command: str
    future: asyncio.Future
    topic: Optional[str] = None
    echo_seen: bool = False


class _SafeRoverRotationSkip(RuntimeError):
    """A rover rotation failed after the receiver was confirmed safe in ROVER mode."""


_COMMAND_RESPONSE_RE = re.compile(
    r"\$COMMAND\s*,\s*(?P<command>.*?)\s*,\s*RESPONSE\s*:\s*(?P<response>[^*\r\n]+)",
    re.IGNORECASE,
)


def _normalized_receiver_command(value: Any) -> str:
    """Normalize command text without losing parameter-level identity."""

    return " ".join(str(value or "").strip().split()).casefold()


def _receiver_response_result(response: str) -> Optional[bool]:
    """Return True for ACK, False for an explicit receiver rejection."""

    upper = " ".join(str(response or "").strip().upper().split())
    if upper == "OK" or upper.startswith("OK "):
        return True
    if any(
        upper == marker or upper.startswith(f"{marker} ")
        for marker in (
            "ERROR",
            "FAILED",
            "INVALID",
            "NO FUNCTION",
            "NO FUNC",
            "NOFUNC",
            "NO MATCHING FUNC",
            "NO MATCHING FUNCTION",
        )
    ):
        return False
    return None
