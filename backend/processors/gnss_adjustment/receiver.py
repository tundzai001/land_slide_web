"""Round-Robin receiver responsibilities."""

from __future__ import annotations

import asyncio
import base64
import inspect
import json
import logging
import math
import time
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
from .session import (
    _COMMAND_RESPONSE_RE,
    _CollectedObservation,
    _CommandAckWaiter,
    _SafeRoverRotationSkip,
    _normalized_receiver_command,
    _receiver_response_result,
    requires_common_base_handover,
    RoundRobinSessionLifecycleMixin,
)
from .statistics import (
    _BASELINE_STD_REJECTION_THRESHOLD_M,
    _InformationAccumulator,
    _edge_effective_sample_size,
    _initial_positive_sequence_ess,
    _pooled_lag_one_autocorrelations,
    _rolling_drift_exceeds_abort_limits,
    _rolling_mean_stability,
    _spd_solve,
    _split_effective_sample_sessions,
)

logger = logging.getLogger(__name__)

class RoundRobinReceiverMixin:
    async def _set_rover_as_temporary_base(
        self,
        rover_code: str,
        project_id: Optional[int] = None,
        route_host: Optional[str] = None,
        route_port: Optional[int] = None,
        route_mountpoint: Optional[str] = None,
        route_password: Optional[str] = None,
        on_collection_started: Optional[Callable[[], None]] = None,
        on_stable_collection_started: Optional[Callable[[], None]] = None,
        on_stable_collection_invalid: Optional[Callable[[str], None]] = None,
        on_collection_stopped: Optional[Callable[[], None]] = None,
        collection_status_callback: Optional[Callable[[], dict]] = None,
        expected_cross_rovers: Optional[set[str]] = None,
        base_llh_override: Optional[dict] = None,
        before_route_start: Optional[Callable[[], Any]] = None,
        before_rover_restore: Optional[Callable[[], Any]] = None,
        after_rover_restore: Optional[Callable[[], Any]] = None,
    ) -> None:
        logger.info("[Round-Robin] Setting %s as temporary base", rover_code)
        await self._emit_progress(
            project_id,
            f"{rover_code}: querying {self.caster_hosts} for an active AICaster client session.",
        )
        restore_llh = self.rover_llh_cache.get(rover_code) or {}
        llh = base_llh_override or restore_llh
        if not llh:
            raise _SafeRoverRotationSkip(
                f"No LLH cache found for {rover_code}; receiver was not changed."
            )

        client_info = await self._find_client_info(
            rover_code,
            project_id=project_id,
        )
        if not client_info:
            raise _SafeRoverRotationSkip(
                f"Could not find an active AICaster client session for {rover_code}; receiver was not changed."
            )
        mountpoint = client_info.get("Mountpoint", "")
        if not mountpoint:
            raise _SafeRoverRotationSkip(
                f"AICaster client session for {rover_code} has no mountpoint; receiver was not changed."
            )
        await self._emit_progress(
            project_id,
            (
                f"{rover_code}: matched AICaster "
                f"{client_info.get('CasterHost')}:{client_info.get('CasterPort')} "
                f"username={client_info.get('Username')} "
                f"receiverID={client_info.get('receiverID')} mountpoint={mountpoint}."
            ),
        )

        commands = self._build_unicore_base_config(
            setup_method="FIXED",
            lat=llh["lat"],
            lon=llh["lon"],
            alt=llh["alt"],
            ecef_xyz=llh.get("ecef_xyz"),
        )
        rover_commands = self._build_unicore_rover_config(
            restore_undulation=restore_llh.get("undulation")
        )
        preflight_command = rover_commands[0]
        preflight_text = preflight_command.decode("ascii", errors="replace").strip()
        await self._emit_progress(
            project_id,
            (
                f"{rover_code}: preflight {preflight_text}; BASE mode is blocked until "
                "the same MQTT topic confirms the command and receiver response."
            ),
        )
        preflight_verified = False
        for preflight_attempt in range(1, self.PREFLIGHT_CONNECTION_ATTEMPTS + 1):
            preflight_verified = await self._send_set_command(
                mountpoint,
                client_info.get("Username", rover_code),
                client_info.get("receiverID", ""),
                [preflight_command],
                password=self.control_password,
                caster_host=client_info.get("CasterHost"),
                caster_port=client_info.get("CasterPort"),
                ack_station_code=rover_code,
            )
            if preflight_verified:
                break
            if preflight_attempt < self.PREFLIGHT_CONNECTION_ATTEMPTS:
                await self._emit_progress(
                    project_id,
                    (
                        f"{rover_code}: preflight connection failed; opening a fresh "
                        "SET connection and retrying before BASE mode."
                    ),
                )
                await asyncio.sleep(1)
        if not preflight_verified:
            detail = self._last_set_error or "no verified MQTT receiver response"
            raise _SafeRoverRotationSkip(
                f"Refusing to set {rover_code} as BASE because ROVER recovery "
                f"preflight was not verified: {detail}"
            )

        route_started = False
        collection_started = False
        restore_error: Optional[str] = None
        target_route_host = route_host or self.source_host
        target_route_port = int(route_port or self.source_port)
        target_route_mountpoint = route_mountpoint or f"{rover_code}_BASE"
        target_route_password = self.source_password if route_password is None else route_password
        operation_error: Optional[Exception] = None
        if before_route_start:
            try:
                before_route_result = before_route_start()
                if inspect.isawaitable(before_route_result):
                    await before_route_result
            except Exception as route_prepare_exc:
                if before_rover_restore:
                    recovery_result = before_rover_restore()
                    if inspect.isawaitable(recovery_result):
                        await recovery_result
                raise _SafeRoverRotationSkip(
                    f"{rover_code}: could not stop the fixed BASE immediately before "
                    f"temporary fanout; receiver remains ROVER: {route_prepare_exc}"
                ) from route_prepare_exc
        await self._emit_progress(
            project_id,
            (
                f"{rover_code}: priming MQTT-to-NTRIP fanout "
                f"{target_route_host}:{target_route_port}/{target_route_mountpoint} "
                "before BASE mode to minimize the correction-source handover gap."
            ),
        )
        try:
            for release_attempt in range(
                1, self.FIXED_BASE_MOUNTPOINT_RELEASE_ATTEMPTS + 1
            ):
                try:
                    await self._start_ntrip_route(
                        rover_code,
                        target_route_mountpoint,
                        host=target_route_host,
                        port=target_route_port,
                        password=target_route_password,
                    )
                    route_started = True
                    break
                except Exception as route_exc:
                    mountpoint_busy = "mountpoint already in using" in str(route_exc).casefold()
                    if (
                        not mountpoint_busy
                        or release_attempt >= self.FIXED_BASE_MOUNTPOINT_RELEASE_ATTEMPTS
                    ):
                        raise
                    # configure-service confirms that the command was persisted,
                    # not that AICaster has already closed the old SOURCE socket.
                    # Keep the fixed base asleep and retry the temporary SOURCE
                    # until that exact mountpoint is observably released.
                    await self._emit_progress(
                        project_id,
                        (
                            f"{rover_code}: CORS accepted the fixed-BASE disable request but AICaster still "
                            f"holds {target_route_mountpoint}; waiting for mountpoint release "
                            f"({release_attempt}/{self.FIXED_BASE_MOUNTPOINT_RELEASE_ATTEMPTS})."
                        ),
                    )
                    try:
                        await self._stop_ntrip_route(rover_code)
                    except Exception as stop_exc:
                        logger.warning(
                            "Could not clear pending route for %s while waiting for mountpoint release: %s",
                            rover_code,
                            stop_exc,
                        )
                    await asyncio.sleep(
                        self.FIXED_BASE_MOUNTPOINT_RELEASE_RETRY_SECONDS
                    )
        except Exception as route_exc:
            if before_rover_restore:
                recovery_result = before_rover_restore()
                if inspect.isawaitable(recovery_result):
                    await recovery_result
            raise _SafeRoverRotationSkip(
                f"{rover_code}: could not prime every temporary SOURCE target; "
                f"receiver remains ROVER: {route_exc}"
            ) from route_exc

        await self._emit_progress(
            project_id,
            (
                f"{rover_code}: sending SET BASE to {client_info.get('CasterHost')}:"
                f"{client_info.get('CasterPort')} (HTTP Basic auth "
                f"{'enabled' if self.control_password else 'disabled'})."
            ),
        )
        try:
            base_verified = await self._send_set_command(
                mountpoint,
                client_info.get("Username", rover_code),
                client_info.get("receiverID", ""),
                commands,
                password=self.control_password,
                caster_host=client_info.get("CasterHost"),
                caster_port=client_info.get("CasterPort"),
                ack_station_code=rover_code,
            )
        except Exception:
            await self._stop_ntrip_route(rover_code)
            route_started = False
            raise
        if not base_verified:
            detail = self._last_set_error or "AICaster returned no rejection detail"
            await self._emit_progress(
                project_id,
                (
                    f"{rover_code}: SET BASE was not fully verified; sending an "
                    "immediate ROVER recovery sequence before aborting."
                ),
            )
            try:
                await self._stop_ntrip_route(rover_code)
            finally:
                route_started = False
            try:
                await self._restore_rover_output_sequence(
                    rover_code=rover_code,
                    mountpoint=mountpoint,
                    client_info=client_info,
                    commands=rover_commands,
                    project_id=project_id,
                )
                recovered = True
            except Exception as recovery_exc:
                recovered = False
                recovery_detail = str(recovery_exc) or "no verified MQTT recovery ACK"
                logger.critical(
                    "Emergency ROVER recovery was not verified for %s: %s",
                    rover_code,
                    recovery_detail,
                )
                detail = f"{detail}; ROVER recovery also unverified: {recovery_detail}"
            error_message = f"AICaster rejected the SET command for {rover_code}: {detail}"
            if recovered:
                raise _SafeRoverRotationSkip(error_message)
            raise RuntimeError(error_message)
        warning_suffix = ""
        if self._last_set_warnings:
            warning_suffix = " Optional RTCM fallbacks: " + "; ".join(self._last_set_warnings)
        await self._emit_progress(
            project_id,
            (
                f"{rover_code}: SET BASE accepted; response="
                f"{self._last_set_response or '200 OK'}.{warning_suffix}"
            ),
        )

        try:
            await self._emit_progress(
                project_id,
                (
                    f"{rover_code}: BASE profile acknowledged; waiting for every primed "
                    "SOURCE target to forward its first verified RTCM3 frame."
                ),
            )
            await self._emit_progress(
                project_id,
                (
                    f"{rover_code}: verifying MQTT-to-NTRIP fanout "
                    f"{target_route_host}:{target_route_port}/{target_route_mountpoint}."
                ),
            )
            for route_attempt in range(1, self.RTCM_ROUTE_RECOVERY_ATTEMPTS + 1):
                try:
                    if not route_started:
                        await self._start_ntrip_route(
                            rover_code,
                            target_route_mountpoint,
                            host=target_route_host,
                            port=target_route_port,
                            password=target_route_password,
                        )
                        route_started = True
                    await self._wait_for_ntrip_route(rover_code, timeout=25.0)
                    break
                except Exception as route_exc:
                    is_missing_rtcm = "no valid rtcm3 frame" in str(route_exc).casefold()
                    if (
                        not is_missing_rtcm
                        or route_attempt >= self.RTCM_ROUTE_RECOVERY_ATTEMPTS
                    ):
                        raise
                    # A receiver may ACK output commands while retaining a stale
                    # rover log configuration on COM2. Reapply the clean, minimal
                    # base profile over a new SET connection and prove the output
                    # again before abandoning this rotation.
                    try:
                        await self._stop_ntrip_route(rover_code)
                        route_started = False
                    except Exception as stop_exc:
                        logger.warning(
                            "Could not stop failed RTCM route for %s before recovery: %s",
                            rover_code,
                            stop_exc,
                        )
                    await self._emit_progress(
                        project_id,
                        (
                            f"{rover_code}: receiver ACKed BASE commands but emitted no "
                            "RTCM3; clearing stale COM2 logs and reapplying the minimal "
                            "UM980 base profile on a fresh SET connection."
                        ),
                    )
                    reapplied = await self._send_set_command(
                        mountpoint,
                        client_info.get("Username", rover_code),
                        client_info.get("receiverID", ""),
                        commands,
                        password=self.control_password,
                        caster_host=client_info.get("CasterHost"),
                        caster_port=client_info.get("CasterPort"),
                        ack_station_code=rover_code,
                    )
                    if not reapplied:
                        raise RuntimeError(
                            f"{rover_code}: RTCM recovery profile was not verified: "
                            f"{self._last_set_error or 'no receiver ACK'}"
                        ) from route_exc
                    await self._emit_progress(
                        project_id,
                        (
                            f"{rover_code}: recovered BASE profile acknowledged; retrying "
                            "the route immediately."
                        ),
                    )
            await self._reset_cross_rovers_for_temporary_base(
                temporary_base_code=rover_code,
                target_rovers=expected_cross_rovers,
                project_id=project_id,
            )
            if on_collection_started:
                on_collection_started()
            collection_started = True
            if collection_status_callback is None:
                # Compatibility path for callers that cannot inspect incoming
                # AGRICA observations. Production injects a status callback and
                # uses the verified, adaptive handover path below.
                await self._emit_progress(
                    project_id,
                    (
                        f"{rover_code}: RTCM route is live; waiting "
                        f"{self.CROSS_BASE_SETTLE_SECONDS}s for rover correction sources "
                        "to report the temporary base_llh. Transition observations are rejected."
                    ),
                )
                await asyncio.sleep(self.CROSS_BASE_SETTLE_SECONDS)
                if on_stable_collection_started:
                    on_stable_collection_started()
                await self._emit_progress(
                    project_id,
                    (
                        f"{rover_code}: NTRIP SOURCE accepted and first RTCM frame "
                        f"forwarded; collecting cross-baselines for "
                        f"{self.CROSS_BASE_STABLE_COLLECTION_SECONDS}s."
                    ),
                )
                await asyncio.sleep(self.CROSS_BASE_STABLE_COLLECTION_SECONDS)
            else:
                expected = set(expected_cross_rovers or ())
                await self._emit_progress(
                    project_id,
                    (
                        f"{rover_code}: RTCM route is live; waiting up to "
                        f"{self.CROSS_BASE_SWITCH_TIMEOUT_SECONDS}s for AGRICA to "
                        "verify the temporary base and a solver-eligible baseline."
                    ),
                )
                loop = asyncio.get_running_loop()
                deadline = loop.time() + self.CROSS_BASE_SWITCH_TIMEOUT_SECONDS
                latest_status: dict = {}
                handover_verified = False
                verified_participants: set[str] = set()
                partial_handover_started_at: Optional[float] = None
                while True:
                    latest_status = dict(collection_status_callback() or {})
                    participants = set(latest_status.get("rover_names") or ())
                    sample_counts_by_rover = {
                        str(name): int(count)
                        for name, count in (
                            latest_status.get("sample_counts_by_rover") or {}
                        ).items()
                    }
                    # Compatibility callbacks may not expose per-rover counts.
                    # Production does, and requires several distinct GNSS epochs
                    # before declaring the RTCM handover stable.
                    stable_participants = (
                        {
                            name
                            for name, count in sample_counts_by_rover.items()
                            if count >= self.CROSS_BASE_HANDOVER_MIN_SAMPLES
                        }
                        if sample_counts_by_rover
                        else participants
                    )
                    sample_count = int(latest_status.get("sample_count") or 0)
                    verified_participants = (
                        stable_participants & expected
                        if expected else set(stable_participants)
                    )
                    # One stable rover is sufficient to prove that this
                    # temporary RTCM source is live. Requiring every configured
                    # rover made one silent receiver invalidate useful edges
                    # from all the other receivers. Overall solvability is
                    # enforced later by the connected cross-baseline graph. A
                    # short grace window still lets other healthy rovers join
                    # before the stability target set is frozen.
                    now = loop.time()
                    if sample_count > 0 and verified_participants:
                        if partial_handover_started_at is None:
                            partial_handover_started_at = now
                        all_expected_verified = (
                            not expected or expected.issubset(stable_participants)
                        )
                        handover_verified = all_expected_verified or (
                            now - partial_handover_started_at
                            >= self.CROSS_BASE_PARTIAL_HANDOVER_GRACE_SECONDS
                        )
                    if handover_verified or loop.time() >= deadline:
                        break
                    await asyncio.sleep(self.CROSS_BASE_STATUS_POLL_SECONDS)

                participants = set(latest_status.get("rover_names") or ())
                if handover_verified:
                    await self._emit_progress(
                        project_id,
                        (
                            f"{rover_code}: temporary-base handover verified from "
                            f"{', '.join(sorted(verified_participants))} after at least "
                            f"{self.CROSS_BASE_HANDOVER_MIN_SAMPLES} distinct epochs each; waiting "
                            f"{self.CROSS_BASE_POST_HANDOVER_SETTLE_SECONDS}s for the new FIXED "
                            "solution to settle before opening the solver window."
                        ),
                    )
                    unavailable_targets = sorted(expected - verified_participants)
                    if unavailable_targets:
                        await self._emit_progress(
                            project_id,
                            (
                                f"{rover_code}: continuing with partial live coverage; "
                                f"no verified handover from {', '.join(unavailable_targets)}. "
                                "These rovers will not invalidate the useful cross-baselines; "
                                "the final connected-graph check remains mandatory."
                            ),
                        )
                    await asyncio.sleep(self.CROSS_BASE_POST_HANDOVER_SETTLE_SECONDS)
                    await self._emit_progress(
                        project_id,
                        (
                            f"{rover_code}: monitoring baseline mean, scatter and slope in two "
                            f"{self.STABILITY_WINDOW_SECONDS}-second windows "
                            f"(at least {self.STABILITY_MIN_SAMPLES_PER_WINDOW} epochs each); require "
                            f"|dN|/|dE| <= {self.STABILITY_HORIZONTAL_COMPONENT_LIMIT_M * 1000:.1f} mm, "
                            f"|dU| <= {self.STABILITY_UP_COMPONENT_LIMIT_M * 1000:.1f} mm "
                            f"with STD <= {self.STABILITY_HORIZONTAL_STD_LIMIT_M * 1000:.0f}/"
                            f"{self.STABILITY_UP_STD_LIMIT_M * 1000:.0f} mm (horizontal/up); "
                            "fast/slow EWMA is an early transition detector only; "
                            f"continuously for {self.STABILITY_HOLD_SECONDS}s before opening "
                            "the solver window."
                        ),
                    )
                    stability_targets = set(verified_participants)
                    solver_window_open = False
                    reset_count = 0
                    drift_failure_counts = dict.fromkeys(stability_targets, 0)
                    drift_evaluation_epochs = dict.fromkeys(stability_targets, None)
                    stability_deadline = (
                        loop.time() + self.CROSS_BASE_STABILITY_TIMEOUT_SECONDS
                    )
                    while True:
                        latest_status = dict(collection_status_callback() or {})
                        rolling = {
                            str(name): dict(diagnostic or {})
                            for name, diagnostic in (
                                latest_status.get("rolling_stability_by_rover") or {}
                            ).items()
                        }
                        now = loop.time()
                        stable_held = bool(stability_targets) and all(
                            rolling.get(name, {}).get("stable") is True
                            and not rolling.get(name, {}).get(
                                "ewma_transition_detected", False
                            )
                            and int(
                                rolling.get(name, {}).get("stable_run_seconds") or 0
                            ) >= self.STABILITY_HOLD_SECONDS
                            for name in stability_targets
                        )

                        if solver_window_open:
                            aborting_now = set()
                            for name in stability_targets:
                                diagnostic = rolling.get(name, {})
                                latest_epoch = diagnostic.get("latest_epoch")
                                abort_exceeded = _rolling_drift_exceeds_abort_limits(
                                    diagnostic,
                                    horizontal_component_limit_m=(
                                        self.STABILITY_ABORT_HORIZONTAL_COMPONENT_LIMIT_M
                                    ),
                                    up_component_limit_m=(
                                        self.STABILITY_ABORT_UP_COMPONENT_LIMIT_M
                                    ),
                                )
                                if abort_exceeded:
                                    aborting_now.add(name)
                                if (
                                    latest_epoch is not None
                                    and latest_epoch
                                    != drift_evaluation_epochs.get(name)
                                ):
                                    drift_evaluation_epochs[name] = latest_epoch
                                    drift_failure_counts[name] = (
                                        int(drift_failure_counts.get(name) or 0) + 1
                                        if abort_exceeded else 0
                                    )
                            aborting_repeatedly = {
                                name
                                for name, count in drift_failure_counts.items()
                                if count >= self.STABILITY_ABORT_CONSECUTIVE_EPOCHS
                            }
                            if aborting_repeatedly:
                                reset_count += 1
                                drift_details = []
                                for name in sorted(aborting_repeatedly):
                                    delta = rolling.get(name, {}).get("delta_neu_m")
                                    if delta and len(delta) == 3:
                                        drift_details.append(
                                            f"{name} dN/E/U="
                                            f"{float(delta[0]) * 1000:.1f}/"
                                            f"{float(delta[1]) * 1000:.1f}/"
                                            f"{float(delta[2]) * 1000:.1f} mm"
                                        )
                                if on_stable_collection_invalid:
                                    on_stable_collection_invalid("drift")
                                solver_window_open = False
                                drift_failure_counts = dict.fromkeys(stability_targets, 0)
                                await self._emit_progress(
                                    project_id,
                                    (
                                        f"{rover_code}: rolling-window or EWMA transition diagnostic exceeded the "
                                        f"{self.STABILITY_ABORT_HORIZONTAL_COMPONENT_LIMIT_M * 1000:.0f}/"
                                        f"{self.STABILITY_ABORT_UP_COMPONENT_LIMIT_M * 1000:.0f} mm "
                                        f"abort envelope for {self.STABILITY_ABORT_CONSECUTIVE_EPOCHS} "
                                        "consecutive receiver epochs; "
                                        f"quarantined solver window #{reset_count} and reset "
                                        "the stability hold timer. "
                                        f"{'; '.join(drift_details) or 'rolling threshold exceeded'}."
                                    ),
                                )
                            else:
                                solver_counts = {
                                    str(name): int(count)
                                    for name, count in (
                                        latest_status.get(
                                            "solver_sample_counts_by_rover"
                                        ) or {}
                                    ).items()
                                }
                                solver_durations = {
                                    str(name): int(duration)
                                    for name, duration in (
                                        latest_status.get(
                                            "solver_durations_by_rover_seconds"
                                        ) or {}
                                    ).items()
                                }
                                solver_ready = {
                                    name
                                    for name in stability_targets
                                    if solver_counts.get(name, 0)
                                    >= self.CROSS_BASE_STABLE_MIN_DISTINCT_EPOCHS
                                    and solver_durations.get(name, 0)
                                    >= self.CROSS_BASE_STABLE_MIN_DURATION_SECONDS
                                }
                                if (
                                    not aborting_now
                                    and stability_targets.issubset(solver_ready)
                                ):
                                    await self._emit_progress(
                                        project_id,
                                        (
                                            f"{rover_code}: stationary solver window complete "
                                            f"for {', '.join(sorted(stability_targets))}; "
                                            f"at least {self.CROSS_BASE_STABLE_MIN_DISTINCT_EPOCHS} "
                                            f"epochs and {self.CROSS_BASE_STABLE_MIN_DURATION_SECONDS}s "
                                            "per rover."
                                        ),
                                    )
                                    break
                        elif stable_held:
                            if on_stable_collection_started:
                                on_stable_collection_started()
                            solver_window_open = True
                            # The stability timeout governs how long we wait to
                            # open a clean window.  Once it opens, always grant
                            # the full mandatory solver duration; otherwise a
                            # window opened near the deadline is quarantined
                            # before it can possibly accumulate enough epochs.
                            stability_deadline = max(
                                stability_deadline,
                                now
                                + self.CROSS_BASE_STABLE_MIN_DURATION_SECONDS
                                + self.CROSS_BASE_STATUS_POLL_SECONDS * 2,
                            )
                            drift_failure_counts = dict.fromkeys(stability_targets, 0)
                            drift_evaluation_epochs = {
                                name: rolling.get(name, {}).get("latest_epoch")
                                for name in stability_targets
                            }
                            await self._emit_progress(
                                project_id,
                                (
                                    f"{rover_code}: rolling mean/scatter/slope remained stationary for "
                                    f"{self.STABILITY_HOLD_SECONDS}s; solver window opened. "
                                    f"Collecting at least {self.CROSS_BASE_STABLE_MIN_DURATION_SECONDS}s."
                                ),
                            )

                        if now >= stability_deadline:
                            if on_stable_collection_invalid:
                                on_stable_collection_invalid(
                                    "duration" if solver_window_open else "stability"
                                )
                            raise RuntimeError(
                                f"{rover_code}: no complete stationary solver window within "
                                f"{self.CROSS_BASE_STABILITY_TIMEOUT_SECONDS}s; "
                                f"rolling threshold N/E={self.STABILITY_HORIZONTAL_COMPONENT_LIMIT_M * 1000:.1f} mm, "
                                f"U={self.STABILITY_UP_COMPONENT_LIMIT_M * 1000:.1f} mm; "
                                f"STD horizontal/up={self.STABILITY_HORIZONTAL_STD_LIMIT_M * 1000:.0f}/"
                                f"{self.STABILITY_UP_STD_LIMIT_M * 1000:.0f} mm"
                            )
                        await asyncio.sleep(self.CROSS_BASE_STATUS_POLL_SECONDS)
                else:
                    missing = sorted(expected - participants)
                    unstable = sorted(expected - stable_participants)
                    handover_counts = {
                        name: sample_counts_by_rover.get(name, 0)
                        for name in sorted(expected or participants)
                    }
                    await self._emit_progress(
                        project_id,
                        (
                            f"{rover_code}: temporary-base handover was not fully "
                            f"verified before timeout; seen rovers="
                            f"{', '.join(sorted(participants)) or 'none'}, missing="
                            f"{', '.join(missing) or 'none'}, below "
                            f"{self.CROSS_BASE_HANDOVER_MIN_SAMPLES}-epoch requirement="
                            f"{', '.join(unstable) or 'none'}, epoch counts="
                            f"{handover_counts}. The rotation will be "
                            "retried after safe ROVER restore."
                        ),
                    )
                    if on_stable_collection_invalid:
                        on_stable_collection_invalid("source")
                    raise RuntimeError(
                        f"{rover_code}: temporary-base handover was not verified"
                    )
        except Exception as exc:
            operation_error = exc
        finally:
            if collection_started and on_collection_stopped:
                on_collection_stopped()
            if collection_started:
                await self._emit_progress(
                    project_id,
                    f"{rover_code}: cross-baseline collection window closed.",
                )
            if route_started:
                try:
                    await self._stop_ntrip_route(rover_code)
                except Exception as exc:
                    logger.error("Could not stop temporary NTRIP route for %s: %s", rover_code, exc)

            if before_rover_restore:
                try:
                    refreshed_client = before_rover_restore()
                    if inspect.isawaitable(refreshed_client):
                        refreshed_client = await refreshed_client
                    if isinstance(refreshed_client, dict) and refreshed_client:
                        client_info = refreshed_client
                        refreshed_mountpoint = str(
                            refreshed_client.get("Mountpoint") or ""
                        ).strip()
                        if refreshed_mountpoint:
                            mountpoint = refreshed_mountpoint
                except Exception as wake_exc:
                    restore_error = (
                        f"Could not restore fixed BASE before returning {rover_code} "
                        f"to ROVER: {str(wake_exc) or wake_exc.__class__.__name__}"
                    )
                    logger.error(restore_error)

            # A temporary base must never be left in BASE mode. Restore the
            # receiver without FRESET so its persistent NTRIP setup and baud
            # rate remain intact.
            await self._emit_progress(
                project_id,
                f"{rover_code}: sending SET ROVER to restore normal AGRICA operation.",
            )
            if restore_error:
                restored = False
            else:
                try:
                    await self._restore_rover_output_sequence(
                        rover_code=rover_code,
                        mountpoint=mountpoint,
                        client_info=client_info,
                        commands=rover_commands,
                        project_id=project_id,
                    )
                    restored = True
                except Exception as restore_exc:
                    restored = False
                    restore_error = (
                        f"Could not restore {rover_code} to ROVER mode: "
                        f"{str(restore_exc) or restore_exc.__class__.__name__}"
                    )
                    logger.error(restore_error)
            if restored:
                await self._emit_progress(
                    project_id,
                    f"{rover_code}: SET ROVER accepted; receiver restored.",
                )
                if after_rover_restore:
                    try:
                        after_result = after_rover_restore()
                        if inspect.isawaitable(after_result):
                            await after_result
                    except Exception as sleep_exc:
                        restore_error = (
                            f"{rover_code} is back in ROVER mode, but fixed BASE could "
                            f"not return to Sleep: "
                            f"{str(sleep_exc) or sleep_exc.__class__.__name__}"
                        )
                        logger.error(restore_error)
            await asyncio.sleep(5)
        if restore_error:
            raise RuntimeError(restore_error) from operation_error
        if operation_error:
            raise _SafeRoverRotationSkip(
                f"{rover_code}: temporary-base operation failed after verified ROVER restore: {operation_error}"
            ) from operation_error


    async def _start_ntrip_route(
        self,
        station_code: str,
        mountpoint: str,
        host: Optional[str] = None,
        port: Optional[int] = None,
        password: Optional[str] = None,
    ) -> None:
        target_host = host or self.source_host
        target_port = int(port or self.source_port)
        target_password = self.source_password if password is None else password
        if self.route_start_callback:
            result = self.route_start_callback(
                station_code,
                target_host,
                target_port,
                mountpoint,
                target_password,
            )
            if inspect.isawaitable(result):
                result = await result
            if result is False:
                raise ConnectionError(f"NTRIP SOURCE route was rejected for {station_code}")
            return

        # Compatibility fallback for deployments where route control is handled
        # by a separate MQTT consumer.  In-process deployments inject an async
        # callback and wait for the SOURCE handshake before collecting.
        route_payload = {
            "station_code": station_code,
            "host": target_host,
            "port": target_port,
            "mountpoint": mountpoint,
            "password": target_password,
        }
        self.mqtt_client.publish("command/ntrip/route/start", json.dumps(route_payload))


    async def _wait_for_ntrip_route(
        self,
        station_code: str,
        timeout: float = 25.0,
    ) -> None:
        if not self.route_wait_callback:
            return
        result = self.route_wait_callback(station_code, timeout)
        if inspect.isawaitable(result):
            await result


    async def _stop_ntrip_route(self, station_code: str) -> None:
        if self.route_stop_callback:
            result = self.route_stop_callback(station_code)
            if inspect.isawaitable(result):
                await result
            return
        self.mqtt_client.publish(
            "command/ntrip/route/stop",
            json.dumps({"station_code": station_code}),
        )


    async def _send_set_command(
        self,
        mountpoint: str,
        username: str,
        receiver_id: str,
        commands: List[bytes],
        password: str = "12345",
        caster_host: Optional[str] = None,
        caster_port: Optional[int] = None,
        wait_for_command_response: bool = True,
        # Field MQTT command ACKs commonly arrive around 8.1--8.3 seconds.
        # Twelve seconds avoids an unnecessary duplicate idempotent command
        # while retaining bounded retries for a genuinely lost response.
        command_response_timeout: float = 12.0,
        ack_station_code: Optional[str] = None,
        optional_unacknowledged_commands: Optional[List[str]] = None,
    ) -> bool:
        """Send a Caster SET request and Unicore commands to the selected rover."""
        target_host = caster_host or self.caster_host
        target_port = int(caster_port or self.caster_port)
        self._last_set_error = None
        self._last_set_response = None
        self._last_set_warnings = []
        optional_commands = {
            _normalized_receiver_command(command)
            for command in (optional_unacknowledged_commands or [])
        }
        writer = None
        active_mqtt_waiter = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(target_host, target_port),
                timeout=10.0,
            )
            auth_str = base64.b64encode(f"{username}:{password}".encode()).decode()
            headers = (
                f"SET /{mountpoint} HTTP/1.1\r\n"
                f"Authorization: Basic {auth_str}\r\n"
                f"User-Agent: NTRIP Client/1.0/{receiver_id}\r\n"
                f"Host: {target_host}:{target_port}\r\n"
                f"\r\n"
            )
            logger.info(
                "SET request target=%s:%s/%s username=%s receiverID=%s command_count=%s",
                target_host,
                target_port,
                mountpoint,
                username,
                receiver_id,
                len(commands),
            )
            writer.write(headers.encode("ascii"))
            await writer.drain()
            response = (
                await asyncio.wait_for(reader.read(1024), timeout=10.0)
            ).decode("ascii", errors="ignore")
            self._last_set_response = " ".join(response.strip().split()) or "empty response"
            logger.info(
                "SET response target=%s:%s/%s response=%s",
                target_host,
                target_port,
                mountpoint,
                self._last_set_response[:500],
            )
            if "200 OK" not in response:
                self._last_set_error = (
                    f"{target_host}:{target_port} mountpoint={mountpoint} "
                    f"username={username} auth={'enabled' if password else 'disabled'} "
                    f"response={self._last_set_response[:500]}"
                )
                logger.error("SET request rejected by Caster: %s", self._last_set_error)
                return False
            for command in commands:
                command_str = command.decode("ascii", errors="replace").strip()
                max_retries = 3
                for attempt in range(1, max_retries + 1):
                    logger.info("SET Unicore command mountpoint=%s command=%s (Attempt %d/%d)", mountpoint, command_str, attempt, max_retries)
                    mqtt_waiter = None
                    if wait_for_command_response and ack_station_code:
                        mqtt_waiter = self._register_command_ack_waiter(
                            ack_station_code,
                            command_str,
                        )
                        active_mqtt_waiter = mqtt_waiter
                    normalized_command = _normalized_receiver_command(command_str)
                    is_optional_command = normalized_command in optional_commands
                    if normalized_command.startswith("mode "):
                        burst_count = self.MODE_COMMAND_BURST_COUNT
                    elif normalized_command == "unlogall":
                        # UNLOGALL is idempotent, and field links occasionally
                        # lose its first command/ACK. A bounded burst avoids an
                        # otherwise unnecessary full response-timeout delay.
                        burst_count = self.UNLOGALL_COMMAND_BURST_COUNT
                    elif normalized_command.startswith("gpgga "):
                        # A field rotation showed that the first GPGGA enable can
                        # be dropped immediately after UNLOGALL.  Use the same
                        # bounded, ACK-aware recovery pattern as AGRICA so rover
                        # telemetry is restored without waiting through several
                        # full command retries.
                        burst_count = self.GPGGA_COMMAND_BURST_COUNT
                    elif normalized_command.startswith("agrica "):
                        # Field UM980 units can ignore an isolated AGRICA enable
                        # immediately after UNLOGALL/mode changes. A short burst
                        # matches the reliable manual recovery procedure and is
                        # stopped as soon as the MQTT command ACK arrives.
                        burst_count = self.AGRICA_COMMAND_BURST_COUNT
                    elif normalized_command.startswith("rtcm"):
                        burst_count = self.RTCM_COMMAND_BURST_COUNT
                    else:
                        burst_count = 1
                    # Bursts are an MQTT-ACK recovery mechanism.  Legacy/socket
                    # response callers have no asynchronous ACK signal that can
                    # stop a burst, so preserve their one-command exchange.
                    if mqtt_waiter is None:
                        burst_count = 1

                    for burst_index in range(1, burst_count + 1):
                        logger.info(
                            "SET command burst mountpoint=%s command=%s shot=%d/%d",
                            mountpoint,
                            command_str,
                            burst_index,
                            burst_count,
                        )
                        writer.write(command)
                        await writer.drain()
                        if burst_index >= burst_count:
                            break
                        await asyncio.sleep(self.COMMAND_BURST_INTERVAL_SECONDS)
                        if mqtt_waiter is not None and mqtt_waiter.future.done():
                            break
                    if wait_for_command_response:
                        try:
                            if mqtt_waiter is not None:
                                mqtt_result = await asyncio.wait_for(
                                    mqtt_waiter.future,
                                    timeout=(
                                        min(command_response_timeout, 3.0)
                                        if is_optional_command
                                        else command_response_timeout
                                    ),
                                )
                                success = bool(mqtt_result["accepted"])
                                rejected = not success
                                compact_response = (
                                    f"MQTT topic={mqtt_result['topic']} "
                                    f"echo={mqtt_result['command']} "
                                    f"response={mqtt_result['response']} "
                                    f"raw={mqtt_result.get('raw_response', mqtt_result['response'])}"
                                )
                            else:
                                end_time = asyncio.get_event_loop().time() + command_response_timeout
                                accumulated = ""
                                success = False
                                rejected = False

                                while asyncio.get_event_loop().time() < end_time:
                                    timeout_left = max(0.1, end_time - asyncio.get_event_loop().time())
                                    try:
                                        chunk = await asyncio.wait_for(reader.read(1024), timeout=timeout_left)
                                        if not chunk:
                                            break
                                        accumulated += chunk.decode("ascii", errors="ignore")
                                    except asyncio.TimeoutError:
                                        break

                                    upper_acc = accumulated.upper()
                                    if any(marker in upper_acc for marker in ("ERROR", "FAILED", "INVALID", "NO FUNCTION")):
                                        rejected = True
                                        break
                                    if "OK" in upper_acc:
                                        success = True
                                        break

                                compact_response = " ".join(accumulated.split())
                            self._last_set_response = compact_response
                            
                            if success:
                                logger.info(
                                    "SET receiver response mountpoint=%s command=%s response=%s",
                                    mountpoint,
                                    command_str,
                                    compact_response[:500],
                                )
                                break  # Break retry loop and proceed to next command
                                
                            if rejected:
                                logger.warning(
                                    "Command rejected mountpoint=%s command=%s response=%s",
                                    mountpoint,
                                    command_str,
                                    compact_response[:500],
                                )
                            else:
                                logger.warning(
                                    "No OK response for mountpoint=%s command=%s (attempt %d). Got: %s",
                                    mountpoint,
                                    command_str,
                                    attempt,
                                    compact_response[:500] or "empty",
                                )
                                
                            if attempt == max_retries:
                                failure_detail = (
                                    f"receiver rejected or ignored command {command_str}: "
                                    f"{compact_response[:500]}"
                                )
                                if is_optional_command:
                                    self._last_set_warnings.append(failure_detail)
                                    logger.warning(
                                        "Optional RTCM command was not acknowledged; continuing with MSM4 fallback: %s",
                                        failure_detail,
                                    )
                                    break
                                self._last_set_error = failure_detail
                                return False
                            await asyncio.sleep(1.0)
                        except Exception as loop_err:
                            response_error = str(loop_err).strip() or loop_err.__class__.__name__
                            if is_optional_command:
                                logger.warning(
                                    "No MQTT ACK yet for optional RTCM command %s: %s",
                                    command_str,
                                    response_error,
                                )
                            else:
                                logger.log(
                                    logging.ERROR if attempt == max_retries else logging.WARNING,
                                    "Error reading command response station=%s caster=%s:%s mountpoint=%s command=%s attempt=%s/%s: %s",
                                    ack_station_code or "unknown",
                                    target_host,
                                    target_port,
                                    mountpoint,
                                    command_str,
                                    attempt,
                                    max_retries,
                                    response_error,
                                )
                            if attempt == max_retries:
                                failure_detail = (
                                    f"no verified MQTT ACK for command {command_str} "
                                    f"from station {ack_station_code}: {loop_err.__class__.__name__}"
                                    if ack_station_code
                                    else str(loop_err)
                                )
                                if is_optional_command:
                                    self._last_set_warnings.append(failure_detail)
                                    logger.warning(
                                        "Optional RTCM command timed out; continuing with MSM4 fallback: %s",
                                        failure_detail,
                                    )
                                    break
                                self._last_set_error = failure_detail
                                return False
                        finally:
                            if mqtt_waiter is not None:
                                self._remove_command_ack_waiter(mqtt_waiter)
                                active_mqtt_waiter = None
                    else:
                        await asyncio.sleep(0.1)
                        break  # No need to retry if we don't wait for response
            return True
        except Exception as exc:
            if active_mqtt_waiter is not None:
                self._remove_command_ack_waiter(active_mqtt_waiter)
                active_mqtt_waiter = None
            detail = str(exc).strip() or exc.__class__.__name__
            self._last_set_error = (
                f"{target_host}:{target_port} mountpoint={mountpoint} "
                f"username={username} auth={'enabled' if password else 'disabled'} "
                f"error={detail}"
            )
            logger.error(
                "Error sending SET command to %s via %s:%s: %s",
                mountpoint,
                target_host,
                target_port,
                detail,
            )
            return False
        finally:
            if writer:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass


    async def _reset_cross_rovers_for_temporary_base(
        self,
        *,
        temporary_base_code: str,
        target_rovers: Optional[Iterable[str]],
        project_id: Optional[int],
    ) -> None:
        """Reboot rover clients after the temporary RTCM source is live."""

        temporary_base_key = str(temporary_base_code).casefold()
        reset_targets = [
            str(name)
            for name in sorted(set(target_rovers or ()))
            if str(name).casefold() != temporary_base_key
        ]
        if not reset_targets:
            return

        await self._emit_progress(
            project_id,
            (
                f"{temporary_base_code}: temporary RTCM source is live; sending RESET "
                f"to rover clients {', '.join(reset_targets)} to reacquire FIXED faster."
            ),
        )
        for rover_code in reset_targets:
            try:
                client_info = await self._find_client_info(
                    rover_code,
                    project_id=project_id,
                    log_missing=False,
                )
                if not client_info:
                    await self._emit_progress(
                        project_id,
                        (
                            f"{temporary_base_code}: could not RESET {rover_code}; "
                            "no active AICaster client session was found."
                        ),
                    )
                    continue
                mountpoint = str(client_info.get("Mountpoint") or "").strip()
                if not mountpoint:
                    await self._emit_progress(
                        project_id,
                        (
                            f"{temporary_base_code}: could not RESET {rover_code}; "
                            "AICaster client session has no mountpoint."
                        ),
                    )
                    continue
                accepted = await self._send_set_command(
                    mountpoint,
                    client_info.get("Username", rover_code),
                    client_info.get("receiverID", ""),
                    [b"RESET\r\n"],
                    password=self.control_password,
                    caster_host=client_info.get("CasterHost"),
                    caster_port=client_info.get("CasterPort"),
                    wait_for_command_response=False,
                )
                if accepted:
                    await self._emit_progress(
                        project_id,
                        f"{temporary_base_code}: RESET sent to rover client {rover_code}.",
                    )
                else:
                    await self._emit_progress(
                        project_id,
                        (
                            f"{temporary_base_code}: RESET was not accepted for "
                            f"{rover_code}: {self._last_set_error or 'no Caster response'}."
                        ),
                    )
            except Exception as exc:
                logger.warning(
                    "Could not send temporary-base RESET to rover=%s via base=%s: %s",
                    rover_code,
                    temporary_base_code,
                    exc,
                )
                await self._emit_progress(
                    project_id,
                    (
                        f"{temporary_base_code}: RESET failed for {rover_code}: "
                        f"{str(exc) or exc.__class__.__name__}."
                    ),
                )


    async def _restore_rover_output_sequence(
        self,
        *,
        rover_code: str,
        mountpoint: str,
        client_info: Dict[str, Any],
        commands: List[bytes],
        project_id: Optional[int],
        max_attempts: int = 3,
    ) -> None:
        """Restore ROVER mode/output, requiring ACKs for every state-changing step.

        Some UM980 units apply ``saveconfig`` but emit no command response while
        writing flash.  Once all preceding ROVER/output commands were verified,
        a missing ACK for that final persistence-only command must not falsely
        report that the receiver is still in BASE mode.
        """

        safe_max_attempts = max(1, int(max_attempts))
        for command_index, command in enumerate(commands, start=1):
            command_text = command.decode("ascii", errors="replace").strip()
            attempt = 0
            attempt_limit = safe_max_attempts
            while attempt < attempt_limit:
                attempt += 1
                await self._emit_progress(
                    project_id,
                    (
                        f"{rover_code}: restore step {command_index}/{len(commands)} "
                        f"{command_text} (attempt {attempt}); waiting for receiver response."
                    ),
                )
                acknowledged = await self._send_set_command(
                    mountpoint,
                    client_info.get("Username", rover_code),
                    client_info.get("receiverID", ""),
                    [command],
                    password=self.control_password,
                    caster_host=client_info.get("CasterHost"),
                    caster_port=client_info.get("CasterPort"),
                    wait_for_command_response=True,
                    ack_station_code=rover_code,
                )
                if acknowledged:
                    await self._emit_progress(
                        project_id,
                        f"{rover_code}: ACK received for {command_text}.",
                    )
                    break
                detail = self._last_set_error or "no receiver response"
                set_transport_failure = (
                    "mountpoint=" in detail.casefold()
                    and any(
                        marker in detail.casefold()
                        for marker in ("response=", "error=")
                    )
                )
                if set_transport_failure:
                    attempt_limit = max(
                        safe_max_attempts,
                        int(self.ROVER_RESTORE_TRANSPORT_ATTEMPTS),
                    )
                else:
                    attempt_limit = safe_max_attempts
                logger.warning(
                    "Rover restore retry rover=%s command=%s attempt=%s/%s "
                    "transport_failure=%s detail=%s",
                    rover_code,
                    command_text,
                    attempt,
                    attempt_limit,
                    set_transport_failure,
                    detail,
                )
                await self._emit_progress(
                    project_id,
                    (
                        f"{rover_code}: AICaster SET session is not ready for "
                        f"{command_text}; retrying in "
                        f"{self.ROVER_RESTORE_RETRY_SECONDS:g}s ({detail})."
                        if set_transport_failure
                        else f"{rover_code}: no ACK for {command_text}; retrying in "
                        f"{self.ROVER_RESTORE_RETRY_SECONDS:g}s ({detail})."
                    ),
                )
                if attempt < attempt_limit:
                    await asyncio.sleep(self.ROVER_RESTORE_RETRY_SECONDS)
                    if set_transport_failure:
                        try:
                            refreshed_client = await self._find_client_info(
                                rover_code,
                                project_id=project_id,
                                log_missing=False,
                            )
                        except Exception as refresh_exc:
                            logger.warning(
                                "Could not refresh AICaster client session while restoring "
                                "%s: %s",
                                rover_code,
                                str(refresh_exc) or refresh_exc.__class__.__name__,
                            )
                        else:
                            if refreshed_client:
                                client_info = refreshed_client
                                refreshed_mountpoint = str(
                                    refreshed_client.get("Mountpoint") or ""
                                ).strip()
                                if refreshed_mountpoint:
                                    mountpoint = refreshed_mountpoint
                                await self._emit_progress(
                                    project_id,
                                    (
                                        f"{rover_code}: refreshed AICaster SET session "
                                        f"username={client_info.get('Username')} "
                                        f"receiverID={client_info.get('receiverID')} "
                                        f"mountpoint={mountpoint}; retrying {command_text}."
                                    ),
                                )
            else:
                is_optional_undulation = (
                    command_index > 1
                    and command_text.lower().startswith("config undulation ")
                )
                if is_optional_undulation:
                    detail = self._last_set_error or "no receiver response"
                    logger.warning(
                        "ROVER mode verified for %s, but optional undulation command "
                        "was not acknowledged; continuing to mandatory UNLOGALL and "
                        "AGRICA recovery. detail=%s",
                        rover_code,
                        detail,
                    )
                    await self._emit_progress(
                        project_id,
                        (
                            f"{rover_code}: optional {command_text} was not ACKed; "
                            "continuing with mandatory BASE-log shutdown and ROVER outputs."
                        ),
                    )
                    continue
                is_final_saveconfig = (
                    command_index == len(commands)
                    and command_index > 1
                    and command_text.lower() == "saveconfig"
                )
                if is_final_saveconfig:
                    detail = self._last_set_error or "no receiver response"
                    logger.warning(
                        "ROVER mode/output verified for %s, but saveconfig ACK was not "
                        "received after %s attempt(s); continuing because saveconfig "
                        "does not change receiver mode. detail=%s",
                        rover_code,
                        attempt,
                        detail,
                    )
                    await self._emit_progress(
                        project_id,
                        (
                            f"{rover_code}: ROVER mode and AGRICA output restored; "
                            "saveconfig was sent but its ACK was not observed. "
                            "Continuing with the verified ROVER state."
                        ),
                    )
                    return
                if set_transport_failure:
                    raise RuntimeError(
                        f"AICaster SET session for {rover_code} was not ready after "
                        f"{attempt} attempt(s); {command_text} was not sent: "
                        f"{self._last_set_error or 'no Caster response'}"
                    )
                raise RuntimeError(
                    f"{command_text} was not acknowledged after {attempt} attempt(s): "
                    f"{self._last_set_error or 'no receiver response'}"
                )


    def _build_unicore_base_config(
        self,
        setup_method: str,
        duration: int = 60,
        lat: float = 0,
        lon: float = 0,
        alt: float = 0,
        ecef_xyz: Optional[Iterable[float]] = None,
    ) -> list[bytes]:
        """Build a deterministic UM980 base profile for the COM2 MQTT bridge.

        Temporary bases start from a persisted rover profile which normally has
        GPGGA and AGRICA enabled.  Clear those rover logs *before* entering BASE
        mode, then keep the documented MODE BASE -> RTCM -> SAVECONFIG sequence
        contiguous.  Some field units continued to emit no-fix GGA only when
        UNLOGALL was inserted after MODE BASE, despite ACKing every RTCM command.
        MSM7 and ephemeris logs are intentionally omitted here: the four MSM4
        streams are sufficient for the short cross-baseline rotation and fit
        comfortably on every supported COM2 baud rate.
        """
        commands = [b"unlogall\r\n"]
        port = "com2"
        if setup_method.upper() == "SURVEY_IN":
            commands.append(f"mode base time {duration}\r\n".encode("ascii"))
        elif ecef_xyz is not None:
            xyz = tuple(float(value) for value in ecef_xyz)
            if (
                len(xyz) != 3
                or not all(math.isfinite(value) for value in xyz)
                or _vector_length(xyz) < 1_000_000.0
            ):
                raise ValueError("ecef_xyz must contain a usable Earth-centered XYZ coordinate")
            # N4 receivers distinguish ECEF from geodetic MODE BASE by param1:
            # an X coordinate outside latitude range [-90, 90] selects ECEF.
            # Four decimals preserve 0.1 mm while matching the official examples.
            commands.append(
                f"mode base {xyz[0]:.4f} {xyz[1]:.4f} {xyz[2]:.4f}\r\n".encode(
                    "ascii"
                )
            )
        else:
            # Unicore MODE BASE interprets its height as altitude unless the
            # undulation is explicitly zero. ``alt`` here is WGS84 ellipsoidal
            # height derived from AGRICA ECEF, so bind the datum before MODE BASE.
            commands.append(b"config undulation 0.0\r\n")
            commands.append(f"mode base {lat} {lon} {alt}\r\n".encode("ascii"))
        for message, interval in (
            ("1006", 10),
            ("1033", 10),
            ("1074", 1),
            ("1124", 1),
            ("1084", 1),
            ("1094", 1),
        ):
            commands.append(f"rtcm{message} {port} {interval}\r\n".encode("ascii"))
        commands.append(b"saveconfig\r\n")
        return commands


    @staticmethod
    def _build_unicore_rover_config(
        restore_undulation: Optional[float] = None,
    ) -> list[bytes]:
        """Restore UM980 rover output after one temporary-base collection."""

        undulation = "auto"
        if restore_undulation is not None:
            try:
                numeric_undulation = float(restore_undulation)
            except (TypeError, ValueError):
                numeric_undulation = math.nan
            if math.isfinite(numeric_undulation) and -1000.0 <= numeric_undulation <= 1000.0:
                # N4 command manual specifies four decimal places for a
                # user-supplied geoid separation.
                undulation = f"{numeric_undulation:.4f}"
        return [
            b"mode rover survey\r\n",
            f"config undulation {undulation}\r\n".encode("ascii"),
            b"unlogall\r\n",
            b"gpgga com2 1\r\n",
            b"AGRICA COM2 1\r\n",
            b"saveconfig\r\n",
        ]
