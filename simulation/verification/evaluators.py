"""Focused requirement evaluators over snapshots, events, and action results."""

import math
from dataclasses import dataclass
from enum import Enum

from simulation.operation.engine_state import EngineOperatingState
from simulation.protection.types import ProtectionLimiter
from simulation.scheduling.presets import TASK_PRIORITIES
from simulation.sensors.fault_injection import SensorChannel
from simulation.telemetry.events import EventType
from simulation.telemetry.snapshot import SimulationSnapshot
from simulation.validation.sensor_validation import ChannelHealth
from simulation.verification.evidence import RequirementEvidence
from simulation.verification.requirements import (
    EvaluationContext,
    EvaluationOutcome,
    RequirementStatus,
)


class NumericSignal(Enum):
    VALIDATED_ROTOR_SPEED_RPM = "validated_rotor_speed_rpm"
    VALIDATED_EGT_C = "validated_exhaust_temperature_c"
    REQUESTED_FUEL_COMMAND = "requested_fuel_command"
    ALLOWED_FUEL_COMMAND = "allowed_fuel_command"
    ROTOR_ACCELERATION_RPM_PER_S = "rotor_acceleration_rpm_per_s"
    SPEED_SETPOINT_RPM = "speed_setpoint_rpm"
    SPEED_ERROR_RPM = "speed_error_rpm"
    THROTTLE_DEMAND = "throttle_demand"


class ActuatorInvariant(Enum):
    FUEL_BOUNDED = "FUEL_BOUNDED"
    FUEL_ZERO_IN_OFF = "FUEL_ZERO_IN_OFF"
    FUEL_ZERO_IN_FAULT = "FUEL_ZERO_IN_FAULT"
    STARTER_INACTIVE_IN_RUNNING = "STARTER_INACTIVE_IN_RUNNING"


@dataclass(frozen=True)
class StateReachedRequirementEvaluator:
    target_state: EngineOperatingState
    after_action_id: str | None = None

    def evaluate(self, context: EvaluationContext) -> EvaluationOutcome:
        start_time = _action_time(context, self.after_action_id)
        if self.after_action_id is not None and start_time is None:
            return _not_evaluated("reference action was not executed")
        match = next(
            (
                snapshot
                for snapshot in context.snapshots
                if (start_time is None or snapshot.simulation_time_s >= start_time)
                and snapshot.operating_state is self.target_state
            ),
            None,
        )
        if match is None:
            return EvaluationOutcome(
                RequirementStatus.FAIL,
                RequirementEvidence(
                    expected_value=self.target_state.value,
                    start_time_s=start_time,
                    relevant_action_id=self.after_action_id,
                ),
                f"State {self.target_state.value} was not reached",
                "STATE_NOT_REACHED",
            )
        return EvaluationOutcome(
            RequirementStatus.PASS,
            RequirementEvidence(
                measured_value=match.operating_state.value,
                expected_value=self.target_state.value,
                evaluation_time_s=match.simulation_time_s,
                start_time_s=start_time,
                engine_state=match.operating_state.value,
                relevant_action_id=self.after_action_id,
            ),
            f"State {self.target_state.value} reached at {match.simulation_time_s:.3f} s",
        )


@dataclass(frozen=True)
class StateReachedWithinRequirementEvaluator:
    target_state: EngineOperatingState
    reference_action_id: str
    maximum_elapsed_s: float
    tolerance_s: float = 1.0e-9

    def __post_init__(self) -> None:
        if self.maximum_elapsed_s < 0.0 or self.tolerance_s < 0.0:
            raise ValueError("state timing limits cannot be negative")

    def evaluate(self, context: EvaluationContext) -> EvaluationOutcome:
        start_time = _action_time(context, self.reference_action_id)
        if start_time is None:
            return _not_evaluated("reference action was not executed")
        match = next(
            (
                snapshot
                for snapshot in context.snapshots
                if snapshot.simulation_time_s + self.tolerance_s >= start_time
                and snapshot.operating_state is self.target_state
            ),
            None,
        )
        if match is None:
            return EvaluationOutcome(
                RequirementStatus.FAIL,
                RequirementEvidence(
                    expected_value=self.target_state.value,
                    upper_limit=self.maximum_elapsed_s,
                    tolerance=self.tolerance_s,
                    start_time_s=start_time,
                    relevant_action_id=self.reference_action_id,
                ),
                f"State {self.target_state.value} was not reached",
                "STATE_NOT_REACHED",
            )
        elapsed = match.simulation_time_s - start_time
        margin = self.maximum_elapsed_s - elapsed
        passed = elapsed <= self.maximum_elapsed_s + self.tolerance_s
        return EvaluationOutcome(
            RequirementStatus.PASS if passed else RequirementStatus.FAIL,
            RequirementEvidence(
                measured_value=elapsed,
                expected_value=self.target_state.value,
                upper_limit=self.maximum_elapsed_s,
                tolerance=self.tolerance_s,
                margin=margin,
                evaluation_time_s=match.simulation_time_s,
                start_time_s=start_time,
                elapsed_time_s=elapsed,
                engine_state=match.operating_state.value,
                relevant_action_id=self.reference_action_id,
            ),
            (
                f"State reached in {elapsed:.3f} s"
                if passed
                else f"State reached too late in {elapsed:.3f} s"
            ),
            None if passed else "STATE_REACHED_TOO_LATE",
        )


@dataclass(frozen=True)
class StateSequenceRequirementEvaluator:
    expected_states: tuple[EngineOperatingState, ...]

    def __post_init__(self) -> None:
        if not self.expected_states:
            raise ValueError("expected state sequence cannot be empty")

    def evaluate(self, context: EvaluationContext) -> EvaluationOutcome:
        observed = _state_transitions(context.snapshots)
        expected = tuple(state.value for state in self.expected_states)
        mismatch_index = next(
            (
                index
                for index, (actual, wanted) in enumerate(zip(observed, expected))
                if actual != wanted
            ),
            min(len(observed), len(expected))
            if len(observed) != len(expected)
            else None,
        )
        passed = mismatch_index is None
        diagnostic = None
        if mismatch_index is not None:
            actual = observed[mismatch_index] if mismatch_index < len(observed) else "missing"
            wanted = expected[mismatch_index] if mismatch_index < len(expected) else "end"
            diagnostic = f"sequence mismatch at index {mismatch_index}: expected {wanted}, observed {actual}"
        return EvaluationOutcome(
            RequirementStatus.PASS if passed else RequirementStatus.FAIL,
            RequirementEvidence(
                measured_value=" -> ".join(observed),
                expected_value=" -> ".join(expected),
                diagnostic_message=diagnostic,
            ),
            "State transition sequence matched" if passed else diagnostic or "State sequence mismatch",
            None if passed else "STATE_SEQUENCE_MISMATCH",
        )


@dataclass(frozen=True)
class SignalMaximumRequirementEvaluator:
    signal: NumericSignal
    maximum: float
    tolerance: float = 0.0
    start_time_s: float | None = None
    end_time_s: float | None = None
    reference_action_id: str | None = None

    def evaluate(self, context: EvaluationContext) -> EvaluationOutcome:
        samples = _numeric_samples(
            context,
            self.signal,
            self.start_time_s,
            self.end_time_s,
            self.reference_action_id,
        )
        if samples is None:
            return _not_evaluated("reference action was not executed")
        if not samples:
            return _not_evaluated(f"signal {self.signal.value} was unavailable")
        maximum_time, measured = max(samples, key=lambda item: item[1])
        first_violation = next(
            (time_s for time_s, value in samples if value > self.maximum + self.tolerance),
            None,
        )
        passed = first_violation is None
        return _limit_outcome(
            passed=passed,
            measured=measured,
            limit=self.maximum,
            tolerance=self.tolerance,
            evaluation_time_s=maximum_time,
            first_violation_time_s=first_violation,
            maximum=True,
            signal=self.signal,
        )


@dataclass(frozen=True)
class SignalMinimumRequirementEvaluator:
    signal: NumericSignal
    minimum: float
    tolerance: float = 0.0
    start_time_s: float | None = None
    end_time_s: float | None = None
    reference_action_id: str | None = None

    def evaluate(self, context: EvaluationContext) -> EvaluationOutcome:
        samples = _numeric_samples(
            context,
            self.signal,
            self.start_time_s,
            self.end_time_s,
            self.reference_action_id,
        )
        if samples is None:
            return _not_evaluated("reference action was not executed")
        if not samples:
            return _not_evaluated(f"signal {self.signal.value} was unavailable")
        minimum_time, measured = min(samples, key=lambda item: item[1])
        first_violation = next(
            (time_s for time_s, value in samples if value < self.minimum - self.tolerance),
            None,
        )
        passed = first_violation is None
        return _limit_outcome(
            passed=passed,
            measured=measured,
            limit=self.minimum,
            tolerance=self.tolerance,
            evaluation_time_s=minimum_time,
            first_violation_time_s=first_violation,
            maximum=False,
            signal=self.signal,
        )


@dataclass(frozen=True)
class SignalBandRequirementEvaluator:
    signal: NumericSignal
    target: float | None = None
    target_signal: NumericSignal | None = None
    tolerance: float = 0.0
    tolerance_percent: float | None = None
    reference_action_id: str | None = None
    start_offset_s: float = 0.0
    end_offset_s: float | None = None

    def __post_init__(self) -> None:
        if (self.target is None) == (self.target_signal is None):
            raise ValueError("provide exactly one band target")
        if self.tolerance < 0.0 or (
            self.tolerance_percent is not None and self.tolerance_percent < 0.0
        ):
            raise ValueError("band tolerances cannot be negative")

    def evaluate(self, context: EvaluationContext) -> EvaluationOutcome:
        snapshots = _window_snapshots(
            context,
            self.reference_action_id,
            self.start_offset_s,
            self.end_offset_s,
        )
        if snapshots is None:
            return _not_evaluated("reference action was not executed")
        evaluated: list[tuple[float, float, float, float]] = []
        for snapshot in snapshots:
            value = _snapshot_numeric(snapshot, self.signal)
            target = self.target
            if self.target_signal is not None:
                target = _snapshot_numeric(snapshot, self.target_signal)
            if value is None or target is None:
                continue
            allowed = self.tolerance + abs(target) * (
                (self.tolerance_percent or 0.0) / 100.0
            )
            evaluated.append((snapshot.simulation_time_s, value, target, allowed))
        if not evaluated:
            return _not_evaluated("band signals were unavailable")
        violations = [
            sample for sample in evaluated if abs(sample[1] - sample[2]) > sample[3]
        ]
        worst = max(evaluated, key=lambda sample: abs(sample[1] - sample[2]) - sample[3])
        passed = not violations
        return EvaluationOutcome(
            RequirementStatus.PASS if passed else RequirementStatus.FAIL,
            RequirementEvidence(
                measured_value=worst[1],
                expected_value=worst[2],
                lower_limit=worst[2] - worst[3],
                upper_limit=worst[2] + worst[3],
                tolerance=worst[3],
                margin=worst[3] - abs(worst[1] - worst[2]),
                evaluation_time_s=worst[0],
                first_violation_time_s=violations[0][0] if violations else None,
                maximum_violation=(
                    max(abs(value - target) - allowed for _, value, target, allowed in violations)
                    if violations
                    else 0.0
                ),
                relevant_action_id=self.reference_action_id,
            ),
            "Signal remained in band" if passed else "Signal left the required band",
            None if passed else "SIGNAL_OUTSIDE_BAND",
        )


@dataclass(frozen=True)
class SettlingTimeRequirementEvaluator:
    reference_action_id: str
    signal: NumericSignal
    target: float | None = None
    target_signal: NumericSignal | None = NumericSignal.SPEED_SETPOINT_RPM
    tolerance: float = 0.0
    tolerance_percent: float = 2.0
    dwell_time_s: float = 0.5
    maximum_settling_time_s: float = 8.0

    def __post_init__(self) -> None:
        if self.target is not None and self.target_signal is not None:
            raise ValueError("provide only one settling target")
        if self.target is None and self.target_signal is None:
            raise ValueError("a settling target is required")
        if min(
            self.tolerance,
            self.tolerance_percent,
            self.dwell_time_s,
            self.maximum_settling_time_s,
        ) < 0.0:
            raise ValueError("settling parameters cannot be negative")

    def evaluate(self, context: EvaluationContext) -> EvaluationOutcome:
        reference_time = _action_time(context, self.reference_action_id)
        if reference_time is None:
            return _not_evaluated("reference action was not executed")
        deadline = reference_time + self.maximum_settling_time_s
        samples: list[tuple[float, float, float, float]] = []
        for snapshot in context.snapshots:
            if not reference_time <= snapshot.simulation_time_s <= deadline + context.time_step_s:
                continue
            value = _snapshot_numeric(snapshot, self.signal)
            target = self.target
            if self.target_signal is not None:
                target = _snapshot_numeric(snapshot, self.target_signal)
            if value is None or target is None:
                continue
            allowed = self.tolerance + abs(target) * self.tolerance_percent / 100.0
            samples.append((snapshot.simulation_time_s, value, target, allowed))
        if not samples:
            return _not_evaluated("settling signals were unavailable")
        band_start: float | None = None
        settling_time: float | None = None
        settling_sample: tuple[float, float, float, float] | None = None
        for sample in samples:
            in_band = abs(sample[1] - sample[2]) <= sample[3]
            if not in_band:
                band_start = None
                continue
            if band_start is None:
                band_start = sample[0]
            if sample[0] - band_start + context.time_step_s >= self.dwell_time_s:
                settling_time = band_start - reference_time
                settling_sample = sample
                break
        if settling_time is None or settling_sample is None:
            last = samples[-1]
            return EvaluationOutcome(
                RequirementStatus.FAIL,
                RequirementEvidence(
                    measured_value=last[1],
                    expected_value=last[2],
                    tolerance=last[3],
                    upper_limit=self.maximum_settling_time_s,
                    start_time_s=reference_time,
                    end_time_s=deadline,
                    relevant_action_id=self.reference_action_id,
                ),
                "Signal did not settle for the required dwell time",
                "SETTLING_TIME_EXCEEDED",
            )
        margin = self.maximum_settling_time_s - settling_time
        return EvaluationOutcome(
            RequirementStatus.PASS,
            RequirementEvidence(
                measured_value=settling_time,
                expected_value=settling_sample[2],
                tolerance=settling_sample[3],
                upper_limit=self.maximum_settling_time_s,
                margin=margin,
                evaluation_time_s=settling_sample[0],
                start_time_s=reference_time,
                elapsed_time_s=settling_time,
                relevant_action_id=self.reference_action_id,
            ),
            f"Signal settled in {settling_time:.3f} s",
        )


@dataclass(frozen=True)
class OvershootRequirementEvaluator:
    reference_action_id: str
    signal: NumericSignal
    maximum_overshoot_percent: float
    target: float | None = None
    target_signal: NumericSignal | None = NumericSignal.SPEED_SETPOINT_RPM
    evaluation_duration_s: float | None = None
    tolerance_percent: float = 0.0

    def evaluate(self, context: EvaluationContext) -> EvaluationOutcome:
        reference_time = _action_time(context, self.reference_action_id)
        if reference_time is None:
            return _not_evaluated("reference action was not executed")
        samples = []
        for snapshot in context.snapshots:
            if snapshot.simulation_time_s < reference_time:
                continue
            if (
                self.evaluation_duration_s is not None
                and snapshot.simulation_time_s > reference_time + self.evaluation_duration_s
            ):
                continue
            value = _snapshot_numeric(snapshot, self.signal)
            target = self.target
            if self.target_signal is not None:
                target = _snapshot_numeric(snapshot, self.target_signal)
            if value is not None and target is not None and target > 0.0:
                samples.append((snapshot.simulation_time_s, value, target))
        if not samples:
            return _not_evaluated("overshoot target or signal was unavailable")
        peak = max(samples, key=lambda item: item[1])
        overshoot = max(0.0, (peak[1] - peak[2]) / peak[2] * 100.0)
        allowed = self.maximum_overshoot_percent + self.tolerance_percent
        passed = overshoot <= allowed
        return EvaluationOutcome(
            RequirementStatus.PASS if passed else RequirementStatus.FAIL,
            RequirementEvidence(
                measured_value=overshoot,
                expected_value=peak[2],
                upper_limit=self.maximum_overshoot_percent,
                tolerance=self.tolerance_percent,
                margin=self.maximum_overshoot_percent - overshoot,
                evaluation_time_s=peak[0],
                start_time_s=reference_time,
                relevant_action_id=self.reference_action_id,
                maximum_violation=max(0.0, overshoot - allowed),
            ),
            f"Peak overshoot was {overshoot:.3f}%",
            None if passed else "OVERSHOOT_EXCEEDED",
        )


@dataclass(frozen=True)
class AccelerationLimitRequirementEvaluator:
    maximum_acceleration_rpm_per_s: float
    tolerance_rpm_per_s: float = 0.0
    reference_action_id: str | None = None

    def evaluate(self, context: EvaluationContext) -> EvaluationOutcome:
        return SignalMaximumRequirementEvaluator(
            signal=NumericSignal.ROTOR_ACCELERATION_RPM_PER_S,
            maximum=self.maximum_acceleration_rpm_per_s,
            tolerance=self.tolerance_rpm_per_s,
            reference_action_id=self.reference_action_id,
        ).evaluate(context)


@dataclass(frozen=True)
class ActuatorInvariantRequirementEvaluator:
    invariant: ActuatorInvariant
    tolerance: float = 1.0e-9

    def evaluate(self, context: EvaluationContext) -> EvaluationOutcome:
        if not context.snapshots:
            return _not_evaluated("no snapshots were captured")
        applicable: list[tuple[SimulationSnapshot, bool, str]] = []
        for snapshot in context.snapshots:
            if self.invariant is ActuatorInvariant.FUEL_BOUNDED:
                valid = -self.tolerance <= snapshot.allowed_fuel_command <= 1.0 + self.tolerance
                applicable.append((snapshot, valid, f"fuel={snapshot.allowed_fuel_command:.6g}"))
            elif self.invariant is ActuatorInvariant.FUEL_ZERO_IN_OFF and snapshot.operating_state is EngineOperatingState.OFF:
                valid = abs(snapshot.allowed_fuel_command) <= self.tolerance
                applicable.append((snapshot, valid, f"fuel={snapshot.allowed_fuel_command:.6g}"))
            elif self.invariant is ActuatorInvariant.FUEL_ZERO_IN_FAULT and snapshot.operating_state is EngineOperatingState.FAULT:
                valid = abs(snapshot.allowed_fuel_command) <= self.tolerance
                applicable.append((snapshot, valid, f"fuel={snapshot.allowed_fuel_command:.6g}"))
            elif self.invariant is ActuatorInvariant.STARTER_INACTIVE_IN_RUNNING and snapshot.operating_state is EngineOperatingState.RUNNING:
                valid = not snapshot.starter_commanded
                applicable.append((snapshot, valid, f"starter={snapshot.starter_commanded}"))
        if not applicable:
            return EvaluationOutcome(
                RequirementStatus.NOT_APPLICABLE,
                RequirementEvidence(diagnostic_message="no applicable snapshots"),
                "No snapshots matched the invariant's applicable state",
            )
        violation = next((sample for sample in applicable if not sample[1]), None)
        passed = violation is None
        selected = violation or applicable[-1]
        return EvaluationOutcome(
            RequirementStatus.PASS if passed else RequirementStatus.FAIL,
            RequirementEvidence(
                measured_value=selected[2],
                expected_value=self.invariant.value,
                tolerance=self.tolerance,
                evaluation_time_s=selected[0].simulation_time_s,
                first_violation_time_s=(selected[0].simulation_time_s if violation else None),
                engine_state=selected[0].operating_state.value,
            ),
            "Actuator invariant held" if passed else f"Actuator invariant violated: {selected[2]}",
            None if passed else "ACTUATOR_INVARIANT_VIOLATION",
        )


@dataclass(frozen=True)
class EventObservedRequirementEvaluator:
    event_type: EventType
    source: str | None = None
    diagnostic_code: str | None = None
    start_time_s: float | None = None
    end_time_s: float | None = None

    def evaluate(self, context: EvaluationContext) -> EvaluationOutcome:
        event = next((event for event in context.events if self._matches(event)), None)
        if event is None:
            return EvaluationOutcome(
                RequirementStatus.FAIL,
                RequirementEvidence(
                    expected_value=self.event_type.value,
                    start_time_s=self.start_time_s,
                    end_time_s=self.end_time_s,
                    relevant_event_type=self.event_type.value,
                ),
                f"Event {self.event_type.value} was not observed",
                "EVENT_NOT_OBSERVED",
            )
        return EvaluationOutcome(
            RequirementStatus.PASS,
            RequirementEvidence(
                measured_value=event.event_type.value,
                expected_value=self.event_type.value,
                evaluation_time_s=event.simulation_time_s,
                relevant_event_type=event.event_type.value,
                diagnostic_message=event.message,
            ),
            f"Event observed at {event.simulation_time_s:.3f} s",
        )

    def _matches(self, event: object) -> bool:
        return (
            getattr(event, "event_type", None) is self.event_type
            and (self.source is None or getattr(event, "source", None) == self.source)
            and (
                self.diagnostic_code is None
                or getattr(event, "diagnostic_code", None) == self.diagnostic_code
            )
            and (
                self.start_time_s is None
                or getattr(event, "simulation_time_s") >= self.start_time_s
            )
            and (
                self.end_time_s is None
                or getattr(event, "simulation_time_s") <= self.end_time_s
            )
        )


@dataclass(frozen=True)
class EventNotObservedRequirementEvaluator:
    event_type: EventType
    source: str | None = None
    diagnostic_code: str | None = None

    def evaluate(self, context: EvaluationContext) -> EvaluationOutcome:
        observed = EventObservedRequirementEvaluator(
            event_type=self.event_type,
            source=self.source,
            diagnostic_code=self.diagnostic_code,
        ).evaluate(context)
        if observed.status is RequirementStatus.FAIL:
            return EvaluationOutcome(
                RequirementStatus.PASS,
                RequirementEvidence(expected_value=f"no {self.event_type.value}"),
                f"Event {self.event_type.value} was not observed",
            )
        return EvaluationOutcome(
            RequirementStatus.FAIL,
            observed.evidence,
            f"Unexpected event {self.event_type.value} was observed",
            "UNEXPECTED_EVENT_OBSERVED",
        )


@dataclass(frozen=True)
class FaultResponseTimeRequirementEvaluator:
    reference_action_id: str
    maximum_response_time_s: float
    target_state: EngineOperatingState = EngineOperatingState.FAULT
    required_health: ChannelHealth | None = None
    health_signal: str | None = None
    tolerance_s: float = 1.0e-9

    def evaluate(self, context: EvaluationContext) -> EvaluationOutcome:
        reference_time = _action_time(context, self.reference_action_id)
        if reference_time is None:
            return _not_evaluated("fault action was not executed")
        match = next(
            (
                snapshot
                for snapshot in context.snapshots
                if snapshot.simulation_time_s >= reference_time
                and snapshot.operating_state is self.target_state
                and self._health_matches(snapshot)
            ),
            None,
        )
        if match is None:
            return EvaluationOutcome(
                RequirementStatus.FAIL,
                RequirementEvidence(
                    expected_value=self.target_state.value,
                    upper_limit=self.maximum_response_time_s,
                    start_time_s=reference_time,
                    relevant_action_id=self.reference_action_id,
                ),
                "Required fault response was not observed",
                "FAULT_RESPONSE_NOT_OBSERVED",
            )
        elapsed = match.simulation_time_s - reference_time
        passed = elapsed <= self.maximum_response_time_s + self.tolerance_s
        return EvaluationOutcome(
            RequirementStatus.PASS if passed else RequirementStatus.FAIL,
            RequirementEvidence(
                measured_value=elapsed,
                expected_value=self.target_state.value,
                upper_limit=self.maximum_response_time_s,
                tolerance=self.tolerance_s,
                margin=self.maximum_response_time_s - elapsed,
                evaluation_time_s=match.simulation_time_s,
                start_time_s=reference_time,
                elapsed_time_s=elapsed,
                engine_state=match.operating_state.value,
                relevant_action_id=self.reference_action_id,
            ),
            f"Fault response completed in {elapsed:.3f} s",
            None if passed else "FAULT_RESPONSE_TOO_SLOW",
        )

    def _health_matches(self, snapshot: SimulationSnapshot) -> bool:
        if self.required_health is None:
            return True
        if self.health_signal == "rotor_speed":
            return snapshot.rotor_speed_health is self.required_health
        if self.health_signal == "egt":
            return snapshot.exhaust_temperature_health is self.required_health
        return snapshot.aggregate_sensor_health is self.required_health


@dataclass(frozen=True)
class FuelCutoffResponseRequirementEvaluator:
    reference_action_id: str | None = None
    reference_event_type: EventType | None = None
    maximum_response_time_s: float = 0.01
    tolerance_s: float = 1.0e-9

    def evaluate(self, context: EvaluationContext) -> EvaluationOutcome:
        reference_time = _action_time(context, self.reference_action_id)
        if self.reference_event_type is not None:
            event = next(
                (event for event in context.events if event.event_type is self.reference_event_type),
                None,
            )
            reference_time = event.simulation_time_s if event is not None else None
        if reference_time is None:
            return _not_evaluated("fuel-cutoff reference was not observed")
        zero_snapshot = next(
            (
                snapshot
                for snapshot in context.snapshots
                if snapshot.simulation_time_s + self.tolerance_s >= reference_time
                and abs(snapshot.allowed_fuel_command) <= self.tolerance_s
            ),
            None,
        )
        if zero_snapshot is None:
            return EvaluationOutcome(
                RequirementStatus.FAIL,
                RequirementEvidence(
                    expected_value=0.0,
                    upper_limit=self.maximum_response_time_s,
                    start_time_s=reference_time,
                ),
                "Zero fuel command was not observed",
                "FUEL_CUTOFF_NOT_OBSERVED",
            )
        elapsed = max(0.0, zero_snapshot.simulation_time_s - reference_time)
        passed = elapsed <= self.maximum_response_time_s + self.tolerance_s
        return EvaluationOutcome(
            RequirementStatus.PASS if passed else RequirementStatus.FAIL,
            RequirementEvidence(
                measured_value=zero_snapshot.allowed_fuel_command,
                expected_value=0.0,
                upper_limit=self.maximum_response_time_s,
                tolerance=self.tolerance_s,
                margin=self.maximum_response_time_s - elapsed,
                evaluation_time_s=zero_snapshot.simulation_time_s,
                start_time_s=reference_time,
                elapsed_time_s=elapsed,
            ),
            f"Fuel cutoff completed in {elapsed:.3f} s",
            None if passed else "FUEL_CUTOFF_TOO_SLOW",
        )


@dataclass(frozen=True)
class ProtectionLimiterObservedRequirementEvaluator:
    """Verify one limiter constrained fuel, optionally requiring reduction."""

    limiter: ProtectionLimiter
    require_fuel_reduction: bool = True
    reference_action_id: str | None = None

    def evaluate(self, context: EvaluationContext) -> EvaluationOutcome:
        reference_time = _action_time(context, self.reference_action_id)
        if self.reference_action_id is not None and reference_time is None:
            return _not_evaluated("reference action was not executed")
        match = next(
            (
                snapshot
                for snapshot in context.snapshots
                if (reference_time is None or snapshot.simulation_time_s >= reference_time)
                and self.limiter in snapshot.constraining_protection_limiters
                and (
                    not self.require_fuel_reduction
                    or snapshot.allowed_fuel_command
                    < snapshot.requested_fuel_command - 1.0e-9
                )
            ),
            None,
        )
        if match is None:
            return EvaluationOutcome(
                RequirementStatus.FAIL,
                RequirementEvidence(
                    expected_value=self.limiter.value,
                    start_time_s=reference_time,
                    relevant_action_id=self.reference_action_id,
                ),
                f"Limiter {self.limiter.value} did not constrain fuel",
                "LIMITER_NOT_OBSERVED",
            )
        return EvaluationOutcome(
            RequirementStatus.PASS,
            RequirementEvidence(
                measured_value=match.allowed_fuel_command,
                expected_value=match.requested_fuel_command,
                evaluation_time_s=match.simulation_time_s,
                engine_state=match.operating_state.value,
                relevant_action_id=self.reference_action_id,
            ),
            f"Limiter {self.limiter.value} constrained fuel at {match.simulation_time_s:.3f} s",
        )


@dataclass(frozen=True)
class SensorHealthReachedRequirementEvaluator:
    """Verify one validator channel reaches a typed health state."""

    channel: SensorChannel
    target_health: ChannelHealth
    reference_action_id: str | None = None

    def evaluate(self, context: EvaluationContext) -> EvaluationOutcome:
        reference_time = _action_time(context, self.reference_action_id)
        if self.reference_action_id is not None and reference_time is None:
            return _not_evaluated("reference action was not executed")
        match = next(
            (
                snapshot
                for snapshot in context.snapshots
                if (reference_time is None or snapshot.simulation_time_s >= reference_time)
                and self._health(snapshot) is self.target_health
            ),
            None,
        )
        if match is None:
            return EvaluationOutcome(
                RequirementStatus.FAIL,
                RequirementEvidence(
                    expected_value=self.target_health.value,
                    start_time_s=reference_time,
                    relevant_action_id=self.reference_action_id,
                ),
                f"{self.channel.value} health did not reach {self.target_health.value}",
                "SENSOR_HEALTH_NOT_REACHED",
            )
        return EvaluationOutcome(
            RequirementStatus.PASS,
            RequirementEvidence(
                measured_value=self.target_health.value,
                expected_value=self.target_health.value,
                evaluation_time_s=match.simulation_time_s,
                engine_state=match.operating_state.value,
                relevant_action_id=self.reference_action_id,
            ),
            f"{self.channel.value} health reached {self.target_health.value}",
        )

    def _health(self, snapshot: SimulationSnapshot) -> ChannelHealth:
        return (
            snapshot.rotor_speed_health
            if self.channel is SensorChannel.ROTOR_SPEED
            else snapshot.exhaust_temperature_health
        )


@dataclass(frozen=True)
class NoTruthFallbackRequirementEvaluator:
    """Verify unavailable raw data is absent or explicitly held, never truth-filled."""

    channel: SensorChannel
    reference_action_id: str

    def evaluate(self, context: EvaluationContext) -> EvaluationOutcome:
        reference_time = _action_time(context, self.reference_action_id)
        if reference_time is None:
            return _not_evaluated("fault action was not executed")
        unavailable_seen = False
        for snapshot in context.snapshots:
            if snapshot.simulation_time_s < reference_time:
                continue
            if self.channel is SensorChannel.ROTOR_SPEED:
                raw = snapshot.measured_rotor_speed_rpm
                validated = snapshot.validated_rotor_speed_rpm
                held = snapshot.rotor_speed_value_is_held
            else:
                raw = snapshot.measured_exhaust_temperature_c
                validated = snapshot.validated_exhaust_temperature_c
                held = snapshot.exhaust_temperature_value_is_held
            if raw is not None:
                continue
            unavailable_seen = True
            if validated is not None and not held:
                return EvaluationOutcome(
                    RequirementStatus.FAIL,
                    RequirementEvidence(
                        measured_value=validated,
                        expected_value="None or explicitly held value",
                        evaluation_time_s=snapshot.simulation_time_s,
                        engine_state=snapshot.operating_state.value,
                        relevant_action_id=self.reference_action_id,
                    ),
                    "Unavailable raw signal was replaced without held-value indication",
                    "UNDECLARED_SIGNAL_FALLBACK",
                )
        if not unavailable_seen:
            return _not_evaluated("no unavailable raw sample was captured")
        return EvaluationOutcome(
            RequirementStatus.PASS,
            RequirementEvidence(
                expected_value="None or explicitly held value",
                start_time_s=reference_time,
                relevant_action_id=self.reference_action_id,
            ),
            "No engine-truth fallback was observed",
        )


@dataclass(frozen=True)
class NoMissedSchedulerReleaseRequirementEvaluator:
    """Verify that every captured logical release was processed."""

    def evaluate(self, context: EvaluationContext) -> EvaluationOutcome:
        if not context.snapshots:
            return _not_evaluated("no snapshots were captured")
        maximum_missed = max(
            snapshot.scheduler_missed_release_count
            for snapshot in context.snapshots
        )
        passed = maximum_missed == 0
        return EvaluationOutcome(
            RequirementStatus.PASS if passed else RequirementStatus.FAIL,
            RequirementEvidence(
                measured_value=maximum_missed,
                expected_value=0,
            ),
            (
                "No logical task releases were missed"
                if passed
                else f"{maximum_missed} logical task releases were missed"
            ),
            None if passed else "SCHEDULER_RELEASE_MISSED",
        )


@dataclass(frozen=True)
class SchedulerPresetRequirementEvaluator:
    """Verify that all captured snapshots use the intended timing preset."""

    expected_preset: str

    def evaluate(self, context: EvaluationContext) -> EvaluationOutcome:
        observed = tuple(
            dict.fromkeys(
                snapshot.scheduler_preset for snapshot in context.snapshots
            )
        )
        passed = observed == (self.expected_preset,)
        return EvaluationOutcome(
            RequirementStatus.PASS if passed else RequirementStatus.FAIL,
            RequirementEvidence(
                measured_value=", ".join(observed),
                expected_value=self.expected_preset,
            ),
            (
                f"Scheduler preset matched {self.expected_preset}"
                if passed
                else "Unexpected scheduler preset was observed"
            ),
            None if passed else "SCHEDULER_PRESET_MISMATCH",
        )


_TASK_EXECUTION_COUNT_FIELDS = {
    "sensor": "sensor_execution_count",
    "validation": "validation_execution_count",
    "controller": "controller_execution_count",
    "protection": "protection_execution_count",
    "state_machine": "state_machine_execution_count",
}


@dataclass(frozen=True)
class TaskExecutionCountRequirementEvaluator:
    """Check an exact tick-derived task execution count at the final snapshot."""

    task_name: str
    period_ticks: int
    phase_offset_ticks: int = 0

    def __post_init__(self) -> None:
        if self.task_name not in _TASK_EXECUTION_COUNT_FIELDS:
            raise ValueError(f"unsupported task count: {self.task_name}")
        if self.period_ticks <= 0:
            raise ValueError("period_ticks must be greater than zero")

    def evaluate(self, context: EvaluationContext) -> EvaluationOutcome:
        if not context.snapshots:
            return _not_evaluated("no snapshots were captured")
        snapshot = context.snapshots[-1]
        measured = int(
            getattr(
                snapshot,
                _TASK_EXECUTION_COUNT_FIELDS[self.task_name],
            )
        )
        expected = _expected_release_count(
            snapshot.scheduler_tick,
            self.period_ticks,
            self.phase_offset_ticks,
        )
        passed = measured == expected
        return EvaluationOutcome(
            RequirementStatus.PASS if passed else RequirementStatus.FAIL,
            RequirementEvidence(
                measured_value=measured,
                expected_value=expected,
                evaluation_time_s=snapshot.simulation_time_s,
                diagnostic_message=(
                    f"task={self.task_name}, tick={snapshot.scheduler_tick}, "
                    f"period_ticks={self.period_ticks}, "
                    f"phase_ticks={self.phase_offset_ticks}"
                ),
            ),
            (
                f"{self.task_name} executed exactly {measured} times"
                if passed
                else (
                    f"{self.task_name} executed {measured} times; "
                    f"expected {expected}"
                )
            ),
            None if passed else "TASK_EXECUTION_COUNT_MISMATCH",
        )


@dataclass(frozen=True)
class TaskExecutionRatioRequirementEvaluator:
    """Verify two task counts match their exact integer release contracts."""

    numerator_task: str
    numerator_period_ticks: int
    denominator_task: str
    denominator_period_ticks: int

    def evaluate(self, context: EvaluationContext) -> EvaluationOutcome:
        if not context.snapshots:
            return _not_evaluated("no snapshots were captured")
        snapshot = context.snapshots[-1]
        numerator = _task_execution_count(snapshot, self.numerator_task)
        denominator = _task_execution_count(snapshot, self.denominator_task)
        expected_numerator = _expected_release_count(
            snapshot.scheduler_tick,
            self.numerator_period_ticks,
            0,
        )
        expected_denominator = _expected_release_count(
            snapshot.scheduler_tick,
            self.denominator_period_ticks,
            0,
        )
        passed = (
            numerator == expected_numerator
            and denominator == expected_denominator
        )
        measured = f"{numerator}:{denominator}"
        expected = f"{expected_numerator}:{expected_denominator}"
        return EvaluationOutcome(
            RequirementStatus.PASS if passed else RequirementStatus.FAIL,
            RequirementEvidence(
                measured_value=measured,
                expected_value=expected,
                evaluation_time_s=snapshot.simulation_time_s,
                diagnostic_message=(
                    f"{self.numerator_task}:{self.denominator_task}"
                ),
            ),
            (
                f"Task execution ratio matched exact counts {expected}"
                if passed
                else f"Task execution ratio {measured}; expected {expected}"
            ),
            None if passed else "TASK_EXECUTION_RATIO_MISMATCH",
        )


@dataclass(frozen=True)
class DeterministicTaskOrderRequirementEvaluator:
    """Verify every published same-tick task list follows explicit priority."""

    def evaluate(self, context: EvaluationContext) -> EvaluationOutcome:
        violation = next(
            (
                snapshot
                for snapshot in context.snapshots
                if snapshot.scheduler_tasks_executed_current_tick
                != tuple(
                    sorted(
                        snapshot.scheduler_tasks_executed_current_tick,
                        key=lambda task_name: (
                            TASK_PRIORITIES[task_name],
                            task_name,
                        ),
                    )
                )
            ),
            None,
        )
        passed = violation is None
        return EvaluationOutcome(
            RequirementStatus.PASS if passed else RequirementStatus.FAIL,
            RequirementEvidence(
                measured_value=(
                    "priority ordered"
                    if passed
                    else ", ".join(
                        violation.scheduler_tasks_executed_current_tick
                    )
                ),
                expected_value="ascending explicit task priority",
                evaluation_time_s=(
                    None
                    if violation is None
                    else violation.simulation_time_s
                ),
            ),
            (
                "Every same-tick task list followed explicit priority"
                if passed
                else "A same-tick task list violated explicit priority"
            ),
            None if passed else "TASK_EXECUTION_ORDER_MISMATCH",
        )


@dataclass(frozen=True)
class PlantModelRequirementEvaluator:
    """Verify that all captured snapshots identify one selected plant."""

    expected_model_id: str

    def evaluate(self, context: EvaluationContext) -> EvaluationOutcome:
        observed = {snapshot.plant_model_id for snapshot in context.snapshots}
        passed = observed == {self.expected_model_id}
        return EvaluationOutcome(
            RequirementStatus.PASS if passed else RequirementStatus.FAIL,
            RequirementEvidence(
                measured_value=",".join(sorted(observed)),
                expected_value=self.expected_model_id,
            ),
            (
                f"Plant model {self.expected_model_id} was used"
                if passed
                else f"Unexpected plant model set: {sorted(observed)}"
            ),
            None if passed else "PLANT_MODEL_MISMATCH",
        )


@dataclass(frozen=True)
class FinitePlantSignalsRequirementEvaluator:
    """Verify finite, bounded basic physical outputs for a development plant."""

    def evaluate(self, context: EvaluationContext) -> EvaluationOutcome:
        violation = next(
            (
                snapshot
                for snapshot in context.snapshots
                if not all(
                    math.isfinite(value)
                    for value in (
                        snapshot.rotor_speed_rpm,
                        snapshot.exhaust_temperature_c,
                        snapshot.estimated_thrust_n,
                    )
                )
                or snapshot.rotor_speed_rpm < 0.0
                or snapshot.estimated_thrust_n < 0.0
            ),
            None,
        )
        passed = violation is None
        return EvaluationOutcome(
            RequirementStatus.PASS if passed else RequirementStatus.FAIL,
            RequirementEvidence(
                measured_value=passed,
                expected_value=True,
                first_violation_time_s=(
                    violation.simulation_time_s
                    if violation is not None
                    else None
                ),
            ),
            (
                "All plant signals were finite and non-negative where required"
                if passed
                else "A non-finite or negative physical output was observed"
            ),
            None if passed else "INVALID_PLANT_SIGNAL",
        )


@dataclass(frozen=True)
class PlantTimeSynchronizationRequirementEvaluator:
    """Verify scheduler snapshot time and plant integration time agree."""

    tolerance_s: float = 1.0e-10

    def evaluate(self, context: EvaluationContext) -> EvaluationOutcome:
        errors = tuple(
            abs(snapshot.plant_time_s - snapshot.simulation_time_s)
            for snapshot in context.snapshots
        )
        maximum_error_s = max(errors, default=0.0)
        passed = maximum_error_s <= self.tolerance_s
        return EvaluationOutcome(
            RequirementStatus.PASS if passed else RequirementStatus.FAIL,
            RequirementEvidence(
                measured_value=maximum_error_s,
                upper_limit=self.tolerance_s,
            ),
            (
                f"Maximum plant time error was {maximum_error_s:.3e} s"
            ),
            None if passed else "PLANT_TIME_MISMATCH",
        )


@dataclass(frozen=True)
class PathSimFuelLagRequirementEvaluator:
    """Verify at least one commanded-fuel transient leads effective fuel."""

    minimum_lag: float = 1.0e-4

    def evaluate(self, context: EvaluationContext) -> EvaluationOutcome:
        match = next(
            (
                snapshot
                for snapshot in context.snapshots
                if snapshot.plant_diagnostics is not None
                and snapshot.allowed_fuel_command
                - snapshot.plant_diagnostics.effective_fuel
                >= self.minimum_lag
            ),
            None,
        )
        passed = match is not None
        measured_lag = (
            match.allowed_fuel_command
            - match.plant_diagnostics.effective_fuel
            if match is not None and match.plant_diagnostics is not None
            else None
        )
        return EvaluationOutcome(
            RequirementStatus.PASS if passed else RequirementStatus.FAIL,
            RequirementEvidence(
                measured_value=measured_lag,
                lower_limit=self.minimum_lag,
                evaluation_time_s=(
                    match.simulation_time_s if match is not None else None
                ),
            ),
            (
                "Effective fuel lagged the applied command"
                if passed
                else "No effective-fuel lag was observed"
            ),
            None if passed else "PATHSIM_FUEL_LAG_NOT_OBSERVED",
        )


def _expected_release_count(
    current_tick: int,
    period_ticks: int,
    phase_offset_ticks: int,
) -> int:
    if current_tick < phase_offset_ticks:
        return 0
    return ((current_tick - phase_offset_ticks) // period_ticks) + 1


def _task_execution_count(
    snapshot: SimulationSnapshot,
    task_name: str,
) -> int:
    try:
        field_name = _TASK_EXECUTION_COUNT_FIELDS[task_name]
    except KeyError as error:
        raise ValueError(f"unsupported task count: {task_name}") from error
    return int(getattr(snapshot, field_name))


def _action_time(context: EvaluationContext, action_id: str | None) -> float | None:
    if action_id is None:
        return None
    result = context.action_results.get(action_id)
    return None if result is None else result.execution_time_s


def _state_transitions(snapshots: tuple[SimulationSnapshot, ...]) -> tuple[str, ...]:
    states: list[str] = []
    for snapshot in snapshots:
        value = snapshot.operating_state.value
        if not states or states[-1] != value:
            states.append(value)
    return tuple(states)


def _snapshot_numeric(
    snapshot: SimulationSnapshot,
    signal: NumericSignal,
) -> float | None:
    value = getattr(snapshot, signal.value)
    if value is None or isinstance(value, bool):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _numeric_samples(
    context: EvaluationContext,
    signal: NumericSignal,
    start_time_s: float | None,
    end_time_s: float | None,
    reference_action_id: str | None,
) -> list[tuple[float, float]] | None:
    reference_time = _action_time(context, reference_action_id)
    if reference_action_id is not None and reference_time is None:
        return None
    effective_start = max(
        value for value in (start_time_s, reference_time, 0.0) if value is not None
    )
    samples = []
    for snapshot in context.snapshots:
        if snapshot.simulation_time_s < effective_start:
            continue
        if end_time_s is not None and snapshot.simulation_time_s > end_time_s:
            continue
        value = _snapshot_numeric(snapshot, signal)
        if value is not None:
            samples.append((snapshot.simulation_time_s, value))
    return samples


def _window_snapshots(
    context: EvaluationContext,
    reference_action_id: str | None,
    start_offset_s: float,
    end_offset_s: float | None,
) -> tuple[SimulationSnapshot, ...] | None:
    reference_time = _action_time(context, reference_action_id)
    if reference_action_id is not None and reference_time is None:
        return None
    start = (reference_time or 0.0) + start_offset_s
    end = None if end_offset_s is None else (reference_time or 0.0) + end_offset_s
    return tuple(
        snapshot
        for snapshot in context.snapshots
        if snapshot.simulation_time_s >= start
        and (end is None or snapshot.simulation_time_s <= end)
    )


def _not_evaluated(message: str) -> EvaluationOutcome:
    return EvaluationOutcome(
        RequirementStatus.NOT_EVALUATED,
        RequirementEvidence(diagnostic_message=message),
        message,
        "EVIDENCE_UNAVAILABLE",
    )


def _limit_outcome(
    *,
    passed: bool,
    measured: float,
    limit: float,
    tolerance: float,
    evaluation_time_s: float,
    first_violation_time_s: float | None,
    maximum: bool,
    signal: NumericSignal,
) -> EvaluationOutcome:
    margin = limit - measured if maximum else measured - limit
    violation = max(0.0, -margin - tolerance)
    qualifier = "maximum" if maximum else "minimum"
    return EvaluationOutcome(
        RequirementStatus.PASS if passed else RequirementStatus.FAIL,
        RequirementEvidence(
            measured_value=measured,
            upper_limit=limit if maximum else None,
            lower_limit=None if maximum else limit,
            tolerance=tolerance,
            margin=margin,
            evaluation_time_s=evaluation_time_s,
            first_violation_time_s=first_violation_time_s,
            maximum_violation=violation,
        ),
        f"Observed {qualifier} {signal.value} was {measured:.6g}",
        None if passed else f"SIGNAL_{qualifier.upper()}_VIOLATION",
    )
