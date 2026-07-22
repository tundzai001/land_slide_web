"""Round-robin observation and receiver-command state models."""
import asyncio
import re
from dataclasses import dataclass
from typing import Any, Optional

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

