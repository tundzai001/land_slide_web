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

NO_RECEIVER_RESPONSE = "no receiver response"

class RoundRobinReceiverMixin:
    async def _resolve_temporary_base_target(
        self, rover_code: str, project_id: Optional[int], base_llh_override: Optional[dict]
    ) -> tuple[dict, str, dict, list[bytes], list[bytes]]:
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

        client_info = await self._find_client_info(rover_code, project_id=project_id)
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
            setup_method="FIXED", lat=llh["lat"], lon=llh["lon"], alt=llh["alt"],
            ecef_xyz=llh.get("ecef_xyz"),
        )
        rover_commands = self._build_unicore_rover_config(restore_undulation=restore_llh.get("undulation"))
        return client_info, mountpoint, llh, commands, rover_commands

    async def _run_temporary_base_preflight(
        self, rover_code: str, project_id: Optional[int], mountpoint: str,
        client_info: dict, rover_commands: list[bytes]
    ) -> None:
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
                mountpoint, client_info.get("Username", rover_code), client_info.get("receiverID", ""),
                [preflight_command], password=self.control_password, caster_host=client_info.get("CasterHost"),
                caster_port=client_info.get("CasterPort"), ack_station_code=rover_code,
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
                f"Refusing to set {rover_code} as BASE because ROVER recovery preflight was not verified: {detail}"
            )

    async def _before_route_handover(self, rover_code: str, before_route_start: Any, before_rover_restore: Any) -> None:
        if not before_route_start:
            return
        try:
            res = before_route_start()
            if inspect.isawaitable(res):
                await res
        except Exception as route_prepare_exc:
            if before_rover_restore:
                rec = before_rover_restore()
                if inspect.isawaitable(rec):
                    await rec
            raise _SafeRoverRotationSkip(
                f"{rover_code}: could not stop the fixed BASE immediately before temporary fanout: {route_prepare_exc}"
            ) from route_prepare_exc

    async def _wait_mountpoint_released(
        self, rover_code: str, project_id: Optional[int], target_route: dict,
        release_attempt: int, max_attempts: int, route_exc: Exception
    ) -> None:
        mountpoint_busy = "mountpoint already in using" in str(route_exc).casefold()
        if not mountpoint_busy or release_attempt >= max_attempts:
            raise route_exc
        await self._emit_progress(
            project_id,
            f"{rover_code}: CORS accepted the fixed-BASE disable request but AICaster still holds {target_route['mountpoint']}; waiting for mountpoint release ({release_attempt}/{max_attempts}).",
        )
        try:
            await self._stop_ntrip_route(rover_code)
        except Exception as stop_exc:
            logger.warning("Could not clear pending route for %s: %s", rover_code, stop_exc)
        await asyncio.sleep(self.FIXED_BASE_MOUNTPOINT_RELEASE_RETRY_SECONDS)

    async def _prime_temporary_route(
        self, rover_code: str, project_id: Optional[int], target_route: dict,
        before_route_start: Any, before_rover_restore: Any
    ) -> bool:
        await self._before_route_handover(rover_code, before_route_start, before_rover_restore)
        await self._emit_progress(
            project_id,
            f"{rover_code}: priming MQTT-to-NTRIP fanout {target_route['host']}:{target_route['port']}/{target_route['mountpoint']} before BASE mode.",
        )
        try:
            for release_attempt in range(1, self.FIXED_BASE_MOUNTPOINT_RELEASE_ATTEMPTS + 1):
                try:
                    await self._start_ntrip_route(
                        rover_code, target_route["mountpoint"], host=target_route["host"],
                        port=target_route["port"], password=target_route["password"],
                    )
                    return True
                except Exception as route_exc:
                    await self._wait_mountpoint_released(
                        rover_code, project_id, target_route, release_attempt,
                        self.FIXED_BASE_MOUNTPOINT_RELEASE_ATTEMPTS, route_exc
                    )
        except Exception as route_exc:
            if before_rover_restore:
                rec = before_rover_restore()
                if inspect.isawaitable(rec):
                    await rec
            raise _SafeRoverRotationSkip(
                f"{rover_code}: could not prime every temporary SOURCE target; receiver remains ROVER: {route_exc}"
            ) from route_exc
        return False

    async def _switch_mode_base_and_verify(
        self, rover_code: str, project_id: Optional[int], mountpoint: str,
        client_info: dict, commands: list[bytes], rover_commands: list[bytes]
    ) -> None:
        await self._emit_progress(
            project_id,
            f"{rover_code}: sending SET BASE to {client_info.get('CasterHost')}:{client_info.get('CasterPort')} (HTTP Basic auth {'enabled' if self.control_password else 'disabled'}).",
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
            raise
        if not base_verified:
            detail = self._last_set_error or "AICaster returned no rejection detail"
            await self._emit_progress(
                project_id,
                f"{rover_code}: SET BASE was not fully verified; sending an immediate ROVER recovery sequence before aborting.",
            )
            try:
                await self._stop_ntrip_route(rover_code)
            except Exception as stop_exc:
                logger.warning("Could not stop route on SET BASE failure for %s: %s", rover_code, stop_exc)
            recovered = False
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
                recovery_detail = str(recovery_exc) or "no verified MQTT recovery ACK"
                logger.critical("Emergency ROVER recovery was not verified for %s: %s", rover_code, recovery_detail)
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
            f"{rover_code}: SET BASE accepted; response={self._last_set_response or '200 OK'}.{warning_suffix}",
        )

    async def _reapply_base_profile_for_rtcm(
        self, rover_code: str, project_id: Optional[int], mountpoint: str,
        client_info: dict, commands: list[bytes], route_exc: Exception
    ) -> None:
        try:
            await self._stop_ntrip_route(rover_code)
        except Exception as stop_exc:
            logger.warning("Could not stop failed RTCM route for %s: %s", rover_code, stop_exc)
        await self._emit_progress(
            project_id,
            f"{rover_code}: receiver ACKed BASE commands but emitted no RTCM3; clearing stale COM2 logs and reapplying UM980 base profile.",
        )
        reapplied = await self._send_set_command(
            mountpoint, client_info.get("Username", rover_code), client_info.get("receiverID", ""),
            commands, password=self.control_password, caster_host=client_info.get("CasterHost"),
            caster_port=client_info.get("CasterPort"), ack_station_code=rover_code,
        )
        if not reapplied:
            raise RuntimeError(
                f"{rover_code}: RTCM recovery profile was not verified: {self._last_set_error or 'no receiver ACK'}"
            ) from route_exc
        await self._emit_progress(project_id, f"{rover_code}: recovered BASE profile acknowledged; retrying route.")

    async def _recover_and_wait_ntrip_route(
        self, rover_code: str, project_id: Optional[int], mountpoint: str,
        client_info: dict, commands: list[bytes], target_route: dict, route_started: bool
    ) -> bool:
        await self._emit_progress(
            project_id,
            f"{rover_code}: BASE profile acknowledged; waiting for primed SOURCE target to forward first verified RTCM3 frame.",
        )
        for route_attempt in range(1, self.RTCM_ROUTE_RECOVERY_ATTEMPTS + 1):
            try:
                if not route_started:
                    await self._start_ntrip_route(
                        rover_code, target_route["mountpoint"], host=target_route["host"],
                        port=target_route["port"], password=target_route["password"],
                    )
                    route_started = True
                await self._wait_for_ntrip_route(rover_code)
                break
            except Exception as route_exc:
                is_missing = "no valid rtcm3 frame" in str(route_exc).casefold()
                if not is_missing or route_attempt >= self.RTCM_ROUTE_RECOVERY_ATTEMPTS:
                    raise
                route_started = False
                await self._reapply_base_profile_for_rtcm(
                    rover_code, project_id, mountpoint, client_info, commands, route_exc
                )
        return route_started

    def _evaluate_handover_status(
        self, latest_status: dict, expected: set[str], partial_started_at: Optional[float], now: float
    ) -> tuple[set[str], set[str], bool, Optional[float]]:
        participants = set(latest_status.get("rover_names") or ())
        counts = {
            str(name): int(count)
            for name, count in (latest_status.get("sample_counts_by_rover") or {}).items()
        }
        stable_participants = (
            {name for name, count in counts.items() if count >= self.CROSS_BASE_HANDOVER_MIN_SAMPLES}
            if counts else participants
        )
        sample_count = int(latest_status.get("sample_count") or 0)
        verified = stable_participants & expected if expected else set(stable_participants)

        handover_verified = False
        new_partial = partial_started_at
        if sample_count > 0 and verified:
            if new_partial is None:
                new_partial = now
            all_expected = not expected or expected.issubset(stable_participants)
            handover_verified = all_expected or (
                now - new_partial >= self.CROSS_BASE_PARTIAL_HANDOVER_GRACE_SECONDS
            )
        return stable_participants, verified, handover_verified, new_partial

    async def _poll_rover_handover(
        self, collection_status_callback: Any, expected: set[str]
    ) -> tuple[bool, set[str], dict]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.CROSS_BASE_SWITCH_TIMEOUT_SECONDS
        handover_verified = False
        verified_participants: set[str] = set()
        stable_participants: set[str] = set()
        partial_started_at: Optional[float] = None
        latest_status: dict = {}

        while True:
            latest_status = dict(collection_status_callback() or {})
            now = loop.time()
            stable_participants, verified_participants, handover_verified, partial_started_at = (
                self._evaluate_handover_status(latest_status, expected, partial_started_at, now)
            )
            if handover_verified or now >= deadline:
                break
            await asyncio.sleep(self.CROSS_BASE_STATUS_POLL_SECONDS)

        counts = {
            str(name): int(count)
            for name, count in (latest_status.get("sample_counts_by_rover") or {}).items()
        }
        return handover_verified, verified_participants, counts

    def _check_solver_window_abort(
        self, rolling: dict, stability_targets: set[str],
        drift_evaluation_epochs: dict, drift_failure_counts: dict
    ) -> tuple[set[str], set[str]]:
        aborting_now = set()
        for name in stability_targets:
            diagnostic = rolling.get(name, {})
            latest_epoch = diagnostic.get("latest_epoch")
            abort_exceeded = _rolling_drift_exceeds_abort_limits(
                diagnostic,
                horizontal_component_limit_m=self.STABILITY_ABORT_HORIZONTAL_COMPONENT_LIMIT_M,
                up_component_limit_m=self.STABILITY_ABORT_UP_COMPONENT_LIMIT_M,
            )
            if abort_exceeded:
                aborting_now.add(name)
            if latest_epoch is not None and latest_epoch != drift_evaluation_epochs.get(name):
                drift_evaluation_epochs[name] = latest_epoch
                drift_failure_counts[name] = (
                    int(drift_failure_counts.get(name) or 0) + 1 if abort_exceeded else 0
                )
        aborting_repeatedly = {
            name for name, count in drift_failure_counts.items()
            if count >= self.STABILITY_ABORT_CONSECUTIVE_EPOCHS
        }
        return aborting_now, aborting_repeatedly

    async def _handle_solver_abort_reset(
        self, rover_code: str, project_id: Optional[int], aborting_repeatedly: set[str],
        rolling: dict, reset_count: int, on_stable_collection_invalid: Any
    ) -> None:
        drift_details = []
        for name in sorted(aborting_repeatedly):
            delta = rolling.get(name, {}).get("delta_neu_m")
            if delta and len(delta) == 3:
                drift_details.append(
                    f"{name} dN/E/U={float(delta[0]) * 1000:.1f}/{float(delta[1]) * 1000:.1f}/{float(delta[2]) * 1000:.1f} mm"
                )
        if on_stable_collection_invalid:
            on_stable_collection_invalid("drift")
        await self._emit_progress(
            project_id,
            f"{rover_code}: rolling-window or EWMA transition diagnostic exceeded abort envelope for {self.STABILITY_ABORT_CONSECUTIVE_EPOCHS} consecutive receiver epochs; quarantined solver window #{reset_count} and reset the stability hold timer. {'; '.join(drift_details) or 'rolling threshold exceeded'}.",
        )

    def _check_solver_window_ready(
        self, latest_status: dict, stability_targets: set[str], aborting_now: set[str]
    ) -> bool:
        solver_counts = {
            str(name): int(count)
            for name, count in (latest_status.get("solver_sample_counts_by_rover") or {}).items()
        }
        solver_durations = {
            str(name): int(duration)
            for name, duration in (latest_status.get("solver_durations_by_rover_seconds") or {}).items()
        }
        solver_ready = {
            name for name in stability_targets
            if solver_counts.get(name, 0) >= self.CROSS_BASE_STABLE_MIN_DISTINCT_EPOCHS
            and solver_durations.get(name, 0) >= self.CROSS_BASE_STABLE_MIN_DURATION_SECONDS
        }
        return not aborting_now and stability_targets.issubset(solver_ready)

    async def _process_stability_step(
        self, rover_code: str, project_id: Optional[int], rolling: dict,
        latest_status: dict, stability_targets: set[str], solver_window_open: bool,
        reset_count: int, on_stable_collection_invalid: Any,
        drift_evaluation_epochs: dict, drift_failure_counts: dict
    ) -> tuple[bool, bool, int]:
        aborting_now, aborting_repeatedly = self._check_solver_window_abort(
            rolling, stability_targets, drift_evaluation_epochs, drift_failure_counts
        )
        if aborting_repeatedly:
            reset_count += 1
            drift_failure_counts.clear()
            drift_failure_counts.update(dict.fromkeys(stability_targets, 0))
            await self._handle_solver_abort_reset(
                rover_code, project_id, aborting_repeatedly, rolling, reset_count, on_stable_collection_invalid
            )
            return False, False, reset_count
        if self._check_solver_window_ready(latest_status, stability_targets, aborting_now):
            await self._emit_progress(
                project_id,
                f"{rover_code}: stationary solver window complete for {', '.join(sorted(stability_targets))}.",
            )
            return True, True, reset_count
        return solver_window_open, False, reset_count

    def _is_stable_held(self, stability_targets: set[str], rolling: dict) -> bool:
        return bool(stability_targets) and all(
            rolling.get(name, {}).get("stable") is True
            and not rolling.get(name, {}).get("ewma_transition_detected", False)
            and int(rolling.get(name, {}).get("stable_run_seconds") or 0) >= self.STABILITY_HOLD_SECONDS
            for name in stability_targets
        )

    async def _open_solver_window_if_stable(
        self, rover_code: str, project_id: Optional[int], stability_targets: set[str],
        rolling: dict, now: float, stability_deadline: float, on_stable_collection_started: Any
    ) -> tuple[bool, float, dict, dict]:
        if on_stable_collection_started:
            on_stable_collection_started()
        new_deadline = max(
            stability_deadline,
            now + self.CROSS_BASE_STABLE_MIN_DURATION_SECONDS + self.CROSS_BASE_STATUS_POLL_SECONDS * 2,
        )
        counts = dict.fromkeys(stability_targets, 0)
        epochs = {name: rolling.get(name, {}).get("latest_epoch") for name in stability_targets}
        await self._emit_progress(project_id, f"{rover_code}: stationary solver window opened.")
        return True, new_deadline, counts, epochs

    async def _monitor_temporary_base_stability(
        self, rover_code: str, project_id: Optional[int], collection_status_callback: Any,
        on_stable_collection_started: Any, on_stable_collection_invalid: Any,
        verified_participants: set[str]
    ) -> None:
        stability_targets = set(verified_participants)
        solver_window_open = False
        reset_count = 0
        drift_failure_counts = dict.fromkeys(stability_targets, 0)
        drift_evaluation_epochs = dict.fromkeys(stability_targets, None)
        loop = asyncio.get_running_loop()
        stability_deadline = loop.time() + self.CROSS_BASE_STABILITY_TIMEOUT_SECONDS

        while True:
            latest_status = dict(collection_status_callback() or {})
            rolling = {
                str(name): dict(diag or {})
                for name, diag in (latest_status.get("rolling_stability_by_rover") or {}).items()
            }
            now = loop.time()

            if solver_window_open:
                solver_window_open, done, reset_count = await self._process_stability_step(
                    rover_code, project_id, rolling, latest_status, stability_targets,
                    solver_window_open, reset_count, on_stable_collection_invalid,
                    drift_evaluation_epochs, drift_failure_counts
                )
                if done:
                    break
            elif self._is_stable_held(stability_targets, rolling):
                solver_window_open, stability_deadline, drift_failure_counts, drift_evaluation_epochs = (
                    await self._open_solver_window_if_stable(
                        rover_code, project_id, stability_targets, rolling, now, stability_deadline, on_stable_collection_started
                    )
                )

            if now >= stability_deadline:
                if on_stable_collection_invalid:
                    on_stable_collection_invalid("duration" if solver_window_open else "stability")
                raise RuntimeError(
                    f"{rover_code}: no complete stationary solver window within {self.CROSS_BASE_STABILITY_TIMEOUT_SECONDS}s"
                )
            await asyncio.sleep(self.CROSS_BASE_STATUS_POLL_SECONDS)

    async def _run_adaptive_temporary_base_collection(
        self,
        rover_code: str,
        project_id: Optional[int],
        collection_status_callback: Callable[[], dict],
        on_stable_collection_started: Optional[Callable[[], None]],
        on_stable_collection_invalid: Optional[Callable[[str], None]],
        expected_cross_rovers: Any,
    ) -> None:
        expected = set(expected_cross_rovers or ())
        await self._emit_progress(
            project_id,
            f"{rover_code}: RTCM route is live; waiting up to {self.CROSS_BASE_SWITCH_TIMEOUT_SECONDS}s for AGRICA to verify the temporary base and a solver-eligible baseline.",
        )
        handover_verified, verified_participants, counts = (
            await self._poll_rover_handover(collection_status_callback, expected)
        )
        if not handover_verified:
            summary = (
                f"{rover_code}: no solver-eligible baseline verified within "
                f"{self.CROSS_BASE_SWITCH_TIMEOUT_SECONDS}s "
                f"(expected {', '.join(sorted(expected)) or 'any rover'}; observed "
                f"{', '.join(f'{k}:{v}' for k, v in sorted(counts.items())) or 'none'})."
            )
            await self._emit_progress(project_id, summary)
            raise _SafeRoverRotationSkip(summary)

        await self._emit_progress(
            project_id,
            f"{rover_code}: temporary-base handover verified from {', '.join(sorted(verified_participants))} after at least {self.CROSS_BASE_HANDOVER_MIN_SAMPLES} distinct epochs each; waiting {self.CROSS_BASE_POST_HANDOVER_SETTLE_SECONDS}s for the new FIXED solution to settle before opening the solver window.",
        )
        unavailable_targets = sorted(expected - verified_participants)
        if unavailable_targets:
            await self._emit_progress(
                project_id,
                f"{rover_code}: continuing with partial live coverage; no verified handover from {', '.join(unavailable_targets)}. These rovers will not invalidate the useful cross-baselines; the final connected-graph check remains mandatory.",
            )
        await asyncio.sleep(self.CROSS_BASE_POST_HANDOVER_SETTLE_SECONDS)
        await self._emit_progress(
            project_id,
            f"{rover_code}: monitoring baseline mean, scatter and slope before opening solver window.",
        )
        await self._monitor_temporary_base_stability(
            rover_code, project_id, collection_status_callback,
            on_stable_collection_started, on_stable_collection_invalid, verified_participants
        )

    async def _refresh_client_mountpoint_if_needed(self, before_rover_restore: Any, rover_code: str) -> tuple[Optional[dict], Optional[str], Optional[str]]:
        if not before_rover_restore:
            return None, None, None
        try:
            refreshed = before_rover_restore()
            if inspect.isawaitable(refreshed):
                refreshed = await refreshed
            if isinstance(refreshed, dict) and refreshed:
                mountpoint = str(refreshed.get("Mountpoint") or "").strip()
                return refreshed, mountpoint or None, None
            return None, None, None
        except Exception as wake_exc:
            err = f"Could not restore fixed BASE before returning {rover_code} to ROVER: {wake_exc}"
            logger.exception(err)
            return None, None, err

    async def _dispatch_rover_restore(
        self, rover_code: str, project_id: Optional[int], mountpoint: str,
        client_info: dict, rover_commands: list[bytes]
    ) -> tuple[bool, Optional[str]]:
        try:
            await self._restore_rover_output_sequence(
                rover_code=rover_code, mountpoint=mountpoint, client_info=client_info,
                commands=rover_commands, project_id=project_id,
            )
            return True, None
        except Exception as restore_exc:
            restore_error = f"Could not restore {rover_code} to ROVER mode: {restore_exc}"
            logger.exception(restore_error)
            return False, restore_error

    async def _handle_after_restore_hook(self, after_rover_restore: Any, rover_code: str) -> Optional[str]:
        if not after_rover_restore:
            return None
        try:
            res = after_rover_restore()
            if inspect.isawaitable(res):
                await res
            return None
        except Exception as sleep_exc:
            err = f"{rover_code} is back in ROVER mode, but fixed BASE failed to sleep: {sleep_exc}"
            logger.exception(err)
            return err

    async def _restore_rover_safe(
        self, rover_code: str, project_id: Optional[int], mountpoint: str,
        client_info: dict, rover_commands: list[bytes], before_rover_restore: Any,
        after_rover_restore: Any, route_started: bool, operation_error: Optional[Exception]
    ) -> None:
        if route_started:
            try:
                await self._stop_ntrip_route(rover_code)
            except Exception as exc:
                logger.exception("Could not stop temporary NTRIP route for %s: %s", rover_code, exc)

        refreshed_client, refreshed_mp, restore_error = await self._refresh_client_mountpoint_if_needed(
            before_rover_restore, rover_code
        )
        if refreshed_client:
            client_info = refreshed_client
        if refreshed_mp:
            mountpoint = refreshed_mp

        await self._emit_progress(project_id, f"{rover_code}: sending SET ROVER to restore normal AGRICA operation.")
        restored = False
        if not restore_error:
            restored, restore_error = await self._dispatch_rover_restore(
                rover_code, project_id, mountpoint, client_info, rover_commands
            )

        if restored:
            await self._emit_progress(project_id, f"{rover_code}: SET ROVER accepted; receiver restored.")
            hook_error = await self._handle_after_restore_hook(after_rover_restore, rover_code)
            if hook_error:
                restore_error = hook_error

        await asyncio.sleep(5)
        if restore_error:
            raise RuntimeError(restore_error) from operation_error
        if operation_error:
            raise _SafeRoverRotationSkip(
                f"{rover_code}: temporary-base operation failed after verified ROVER restore: {operation_error}"
            ) from operation_error

    async def _compat_wait_temporary_base(
        self, rover_code: str, project_id: Optional[int], on_stable_collection_started: Any
    ) -> None:
        await self._emit_progress(
            project_id,
            (
                f"{rover_code}: RTCM route is live; waiting {self.CROSS_BASE_SETTLE_SECONDS}s "
                "for rover correction sources to report the temporary base_llh."
            ),
        )
        await asyncio.sleep(self.CROSS_BASE_SETTLE_SECONDS)
        if on_stable_collection_started:
            on_stable_collection_started()
        await self._emit_progress(
            project_id,
            f"{rover_code}: NTRIP SOURCE accepted and first RTCM frame forwarded; collecting cross-baselines for {self.CROSS_BASE_STABLE_COLLECTION_SECONDS}s.",
        )
        await asyncio.sleep(self.CROSS_BASE_STABLE_COLLECTION_SECONDS)

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
        base_llh_override: Optional[dict] = None,
        **kwargs,
    ) -> None:
        expected_cross_rovers = kwargs.get("expected_cross_rovers")
        before_route_start = kwargs.get("before_route_start")
        before_rover_restore = kwargs.get("before_rover_restore")
        after_rover_restore = kwargs.get("after_rover_restore")

        client_info, mountpoint, _, commands, rover_commands = (
            await self._resolve_temporary_base_target(rover_code, project_id, base_llh_override)
        )
        await self._run_temporary_base_preflight(rover_code, project_id, mountpoint, client_info, rover_commands)

        target_route = {
            "host": route_host or self.source_host,
            "port": int(route_port or self.source_port),
            "mountpoint": route_mountpoint or f"{rover_code}_BASE",
            "password": self.source_password if route_password is None else route_password,
        }

        route_started = await self._prime_temporary_route(
            rover_code, project_id, target_route, before_route_start, before_rover_restore
        )
        collection_started = False
        operation_error = None
        try:
            await self._switch_mode_base_and_verify(
                rover_code, project_id, mountpoint, client_info, commands, rover_commands
            )
            route_started = await self._recover_and_wait_ntrip_route(
                rover_code, project_id, mountpoint, client_info, commands, target_route, route_started
            )
            await self._reset_cross_rovers_for_temporary_base(
                temporary_base_code=rover_code, target_rovers=expected_cross_rovers, project_id=project_id
            )
            if on_collection_started:
                on_collection_started()
            collection_started = True

            if collection_status_callback is None:
                await self._compat_wait_temporary_base(
                    rover_code, project_id, on_stable_collection_started
                )
            else:
                await self._run_adaptive_temporary_base_collection(
                    rover_code, project_id, collection_status_callback,
                    on_stable_collection_started, on_stable_collection_invalid, expected_cross_rovers
                )
        except Exception as exc:
            operation_error = exc
        finally:
            if collection_started and on_collection_stopped:
                on_collection_stopped()
            if collection_started:
                await self._emit_progress(project_id, f"{rover_code}: cross-baseline collection window closed.")
            await self._restore_rover_safe(
                rover_code, project_id, mountpoint, client_info, rover_commands,
                before_rover_restore, after_rover_restore, route_started, operation_error
            )


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
    ) -> None:
        if not self.route_wait_callback:
            return
        result = self.route_wait_callback(station_code, 25.0)
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


    async def _connect_and_authenticate_set(
        self, target_host: str, target_port: int, mountpoint: str,
        username: str, password: str, receiver_id: str, command_count: int
    ) -> tuple[Optional[asyncio.StreamReader], Optional[asyncio.StreamWriter]]:
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
            target_host, target_port, mountpoint, username, receiver_id, command_count,
        )
        writer.write(headers.encode("ascii"))
        await writer.drain()
        response = (
            await asyncio.wait_for(reader.read(1024), timeout=10.0)
        ).decode("ascii", errors="ignore")
        self._last_set_response = " ".join(response.strip().split()) or "empty response"
        logger.info(
            "SET response target=%s:%s/%s response=%s",
            target_host, target_port, mountpoint, self._last_set_response[:500],
        )
        if "200 OK" not in response:
            self._last_set_error = (
                f"{target_host}:{target_port} mountpoint={mountpoint} "
                f"username={username} auth={'enabled' if password else 'disabled'} "
                f"response={self._last_set_response[:500]}"
            )
            logger.error("SET request rejected by Caster: %s", self._last_set_error)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return None, None
        return reader, writer

    def _compute_burst_count(self, normalized_command: str, has_mqtt_waiter: bool) -> int:
        if not has_mqtt_waiter:
            return 1
        if normalized_command.startswith("mode "):
            return self.MODE_COMMAND_BURST_COUNT
        if normalized_command == "unlogall":
            return self.UNLOGALL_COMMAND_BURST_COUNT
        if normalized_command.startswith("gpgga "):
            return self.GPGGA_COMMAND_BURST_COUNT
        if normalized_command.startswith("agrica "):
            return self.AGRICA_COMMAND_BURST_COUNT
        if normalized_command.startswith("rtcm"):
            return self.RTCM_COMMAND_BURST_COUNT
        return 1

    async def _send_command_burst(
        self, writer: asyncio.StreamWriter, command: bytes, burst_count: int,
        mountpoint: str, command_str: str, mqtt_waiter: Any
    ) -> None:
        for burst_index in range(1, burst_count + 1):
            logger.info("SET command burst mountpoint=%s command=%s shot=%d/%d", mountpoint, command_str, burst_index, burst_count)
            writer.write(command)
            await writer.drain()
            if burst_index >= burst_count:
                break
            await asyncio.sleep(self.COMMAND_BURST_INTERVAL_SECONDS)
            if mqtt_waiter is not None and mqtt_waiter.future.done():
                break

    async def _read_command_socket_response(
        self, reader: asyncio.StreamReader, duration_seconds: float
    ) -> tuple[bool, bool, str]:
        end_time = asyncio.get_event_loop().time() + duration_seconds
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
        return success, rejected, " ".join(accumulated.split())

    async def _wait_single_command_response(
        self, reader: asyncio.StreamReader, mqtt_waiter: Any,
        is_optional: bool, wait_seconds: float
    ) -> tuple[bool, bool, str]:
        if mqtt_waiter is not None:
            actual_timeout = min(wait_seconds, 3.0) if is_optional else wait_seconds
            mqtt_result = await asyncio.wait_for(mqtt_waiter.future, timeout=actual_timeout)
            success = bool(mqtt_result["accepted"])
            rejected = not success
            compact = (
                f"MQTT topic={mqtt_result['topic']} "
                f"echo={mqtt_result['command']} "
                f"response={mqtt_result['response']} "
                f"raw={mqtt_result.get('raw_response', mqtt_result['response'])}"
            )
            return success, rejected, compact
        return await self._read_command_socket_response(reader, wait_seconds)

    def _handle_command_attempt_result(
        self, compact_response: str, success: bool, rejected: bool, attempt: int,
        max_retries: int, is_optional: bool, command_str: str, mountpoint: str
    ) -> Optional[bool]:
        self._last_set_response = compact_response
        if success:
            logger.info("SET receiver response mountpoint=%s command=%s response=%s", mountpoint, command_str, compact_response[:500])
            return True
        if rejected:
            logger.warning("Command rejected mountpoint=%s command=%s response=%s", mountpoint, command_str, compact_response[:500])
        else:
            logger.warning("No OK response for mountpoint=%s command=%s (attempt %d). Got: %s", mountpoint, command_str, attempt, compact_response[:500] or "empty")
        if attempt == max_retries:
            failure_detail = f"receiver rejected or ignored command {command_str}: {compact_response[:500]}"
            if is_optional:
                self._last_set_warnings.append(failure_detail)
                logger.warning("Optional RTCM command was not acknowledged; continuing with MSM4 fallback: %s", failure_detail)
                return True
            self._last_set_error = failure_detail
            return False
        return None

    def _handle_command_attempt_exception(
        self, loop_err: Exception, attempt: int, max_retries: int, is_optional: bool,
        command_str: str, ack_station: Optional[str], target_host: str, target_port: int, mountpoint: str
    ) -> Optional[bool]:
        response_error = str(loop_err).strip() or loop_err.__class__.__name__
        if is_optional:
            logger.warning("No MQTT ACK yet for optional RTCM command %s: %s", command_str, response_error)
        else:
            logger.log(
                logging.ERROR if attempt == max_retries else logging.WARNING,
                "Error reading command response station=%s caster=%s:%s mountpoint=%s command=%s attempt=%s/%s: %s",
                ack_station or "unknown", target_host, target_port, mountpoint, command_str, attempt, max_retries, response_error,
            )
        if attempt == max_retries:
            failure_detail = (
                f"no verified MQTT ACK for command {command_str} from station {ack_station}: {loop_err.__class__.__name__}"
                if ack_station else str(loop_err)
            )
            if is_optional:
                self._last_set_warnings.append(failure_detail)
                logger.warning("Optional RTCM command timed out; continuing with MSM4 fallback: %s", failure_detail)
                return True
            self._last_set_error = failure_detail
            return False
        return None

    async def _dispatch_single_set_command(
        self, writer: asyncio.StreamWriter, reader: asyncio.StreamReader,
        command: bytes, optional_commands: set, wait_for_response: bool,
        command_timeout: float, ack_station: Optional[str], mountpoint: str,
        target_host: str, target_port: int
    ) -> bool:
        command_str = command.decode("ascii", errors="replace").strip()
        normalized_command = _normalized_receiver_command(command_str)
        is_optional = normalized_command in optional_commands
        max_retries = 3

        for attempt in range(1, max_retries + 1):
            logger.info("SET Unicore command mountpoint=%s command=%s (Attempt %d/%d)", mountpoint, command_str, attempt, max_retries)
            mqtt_waiter = None
            if wait_for_response and ack_station:
                mqtt_waiter = self._register_command_ack_waiter(ack_station, command_str)
            burst_count = self._compute_burst_count(normalized_command, mqtt_waiter is not None)
            await self._send_command_burst(writer, command, burst_count, mountpoint, command_str, mqtt_waiter)

            if not wait_for_response:
                await asyncio.sleep(0.1)
                return True

            try:
                success, rejected, compact_response = await self._wait_single_command_response(
                    reader, mqtt_waiter, is_optional, command_timeout
                )
                res = self._handle_command_attempt_result(
                    compact_response, success, rejected, attempt, max_retries, is_optional, command_str, mountpoint
                )
                if res is not None:
                    return res
                await asyncio.sleep(1.0)
            except Exception as loop_err:
                res = self._handle_command_attempt_exception(
                    loop_err, attempt, max_retries, is_optional, command_str, ack_station, target_host, target_port, mountpoint
                )
                if res is not None:
                    return res
            finally:
                if mqtt_waiter is not None:
                    self._remove_command_ack_waiter(mqtt_waiter)
        return False

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
        try:
            reader, writer = await self._connect_and_authenticate_set(
                target_host, target_port, mountpoint, username, password, receiver_id, len(commands)
            )
            if reader is None or writer is None:
                return False
            for command in commands:
                ok = await self._dispatch_single_set_command(
                    writer, reader, command, optional_commands, wait_for_command_response,
                    command_response_timeout, ack_station_code, mountpoint, target_host, target_port
                )
                if not ok:
                    return False
            return True
        except Exception as exc:
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


    async def _handle_rover_restore_failure(
        self,
        *,
        rover_code: str,
        command_text: str,
        command_index: int,
        total_commands: int,
        project_id: Optional[int],
        attempt: int,
        set_transport_failure: bool,
    ) -> bool:
        """Handle unacknowledged restore command. Returns True if execution should continue."""
        is_optional_undulation = (
            command_index > 1
            and command_text.lower().startswith("config undulation ")
        )
        if is_optional_undulation:
            detail = self._last_set_error or NO_RECEIVER_RESPONSE
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
            return True
        is_final_saveconfig = (
            command_index == total_commands
            and command_index > 1
            and command_text.lower() == "saveconfig"
        )
        if is_final_saveconfig:
            detail = self._last_set_error or NO_RECEIVER_RESPONSE
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
            return False
        if set_transport_failure:
            raise RuntimeError(
                f"AICaster SET session for {rover_code} was not ready after "
                f"{attempt} attempt(s); {command_text} was not sent: "
                f"{self._last_set_error or 'no Caster response'}"
            )
        raise RuntimeError(
            f"{command_text} was not acknowledged after {attempt} attempt(s): "
            f"{self._last_set_error or NO_RECEIVER_RESPONSE}"
        )

    async def _refresh_rover_restore_session(
        self,
        rover_code: str,
        project_id: Optional[int],
        client_info: Dict[str, Any],
        mountpoint: str,
        command_text: str,
    ) -> tuple[Dict[str, Any], str]:
        """Attempt to refresh AICaster client session during transport retry."""
        try:
            refreshed_client = await self._find_client_info(
                rover_code,
                project_id=project_id,
                log_missing=False,
            )
        except Exception as refresh_exc:
            logger.warning(
                "Could not refresh AICaster client session while restoring %s: %s",
                rover_code,
                str(refresh_exc) or refresh_exc.__class__.__name__,
            )
            return client_info, mountpoint

        if not refreshed_client:
            return client_info, mountpoint

        client_info = refreshed_client
        refreshed_mountpoint = str(refreshed_client.get("Mountpoint") or "").strip()
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
        return client_info, mountpoint

    async def _attempt_rover_restore_command(
        self,
        *,
        rover_code: str,
        mountpoint: str,
        client_info: Dict[str, Any],
        command: bytes,
        command_index: int,
        total_commands: int,
        project_id: Optional[int],
        safe_max_attempts: int,
    ) -> tuple[bool, str, Dict[str, Any], int, bool]:
        command_text = command.decode("ascii", errors="replace").strip()
        attempt = 0
        attempt_limit = safe_max_attempts
        set_transport_failure = False
        while attempt < attempt_limit:
            attempt += 1
            await self._emit_progress(
                project_id,
                (
                    f"{rover_code}: restore step {command_index}/{total_commands} "
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
                return True, mountpoint, client_info, attempt, False
            detail = self._last_set_error or NO_RECEIVER_RESPONSE
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
                    client_info, mountpoint = await self._refresh_rover_restore_session(
                        rover_code,
                        project_id,
                        client_info,
                        mountpoint,
                        command_text,
                    )
        return False, mountpoint, client_info, attempt, set_transport_failure

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
        total_commands = len(commands)
        for command_index, command in enumerate(commands, start=1):
            command_text = command.decode("ascii", errors="replace").strip()
            ack, mountpoint, client_info, attempt, transport_fail = (
                await self._attempt_rover_restore_command(
                    rover_code=rover_code,
                    mountpoint=mountpoint,
                    client_info=client_info,
                    command=command,
                    command_index=command_index,
                    total_commands=total_commands,
                    project_id=project_id,
                    safe_max_attempts=safe_max_attempts,
                )
            )
            if not ack:
                should_continue = await self._handle_rover_restore_failure(
                    rover_code=rover_code,
                    command_text=command_text,
                    command_index=command_index,
                    total_commands=total_commands,
                    project_id=project_id,
                    attempt=attempt,
                    set_transport_failure=transport_fail,
                )
                if not should_continue:
                    return


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
