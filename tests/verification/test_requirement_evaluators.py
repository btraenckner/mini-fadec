"""Unit tests for snapshot- and event-based requirement evaluators."""

from dataclasses import replace

import pytest

from simulation.application.engine_simulation import EngineSimulationCoordinator
from simulation.operation.engine_state import EngineOperatingState
from simulation.protection.types import ProtectionDiagnosticReason
from simulation.scenarios.actions import (
    ActionExecutionStatus,
    ActionResult,
)
from simulation.sensors.fault_injection import SensorChannel
from simulation.telemetry.events import (
    EventCategory,
    EventSeverity,
    EventType,
    SimulationEvent,
)
from simulation.validation.sensor_validation import ChannelHealth
from simulation.verification.evaluators import (
    ActuatorInvariant,
    ActuatorInvariantRequirementEvaluator,
    AmbientConditionRequirementEvaluator,
    EventNotObservedRequirementEvaluator,
    EventObservedRequirementEvaluator,
    FaultResponseTimeRequirementEvaluator,
    FuelCutoffResponseRequirementEvaluator,
    NoTruthFallbackRequirementEvaluator,
    NumericSignal,
    OvershootRequirementEvaluator,
    ProtectionArbitrationRequirementEvaluator,
    SensorHealthReachedRequirementEvaluator,
    SettlingTimeRequirementEvaluator,
    SignalBandRequirementEvaluator,
    SignalMaximumRequirementEvaluator,
    SignalMinimumRequirementEvaluator,
    StateReachedRequirementEvaluator,
    StateReachedWithinRequirementEvaluator,
    StateSequenceRequirementEvaluator,
    ThrottleScheduleRequirementEvaluator,
    TrueEgtWithinConfiguredLimitRequirementEvaluator,
)
from simulation.verification.requirements import (
    EvaluationContext,
    RequirementStatus,
)


def _snapshot(
    time_s: float,
    state: EngineOperatingState = EngineOperatingState.OFF,
    **changes: object,
):
    snapshot = EngineSimulationCoordinator().snapshot
    return replace(
        snapshot,
        simulation_time_s=time_s,
        operating_state=state,
        **changes,
    )


def _action(action_id: str, time_s: float) -> ActionResult:
    return ActionResult(
        action_id=action_id,
        description=action_id,
        action_type="TestAction",
        status=ActionExecutionStatus.EXECUTED,
        required_success=True,
        execution_time_s=time_s,
    )


def _event(event_type: EventType, time_s: float = 1.0) -> SimulationEvent:
    return SimulationEvent(
        simulation_time_s=time_s,
        event_sequence=1,
        category=EventCategory.SYSTEM,
        event_type=event_type,
        severity=EventSeverity.INFO,
        source="test",
        message="test event",
    )


def _context(
    snapshots: tuple = (),
    events: tuple[SimulationEvent, ...] = (),
    actions: dict[str, ActionResult] | None = None,
) -> EvaluationContext:
    return EvaluationContext(
        snapshots=snapshots,
        events=events,
        action_results=actions or {},
        time_step_s=0.1,
    )


def test_state_reached_pass_and_fail() -> None:
    context = _context(
        (_snapshot(0.0), _snapshot(1.0, EngineOperatingState.IDLE))
    )

    passed = StateReachedRequirementEvaluator(
        EngineOperatingState.IDLE
    ).evaluate(context)
    failed = StateReachedRequirementEvaluator(
        EngineOperatingState.FAULT
    ).evaluate(context)

    assert passed.status is RequirementStatus.PASS
    assert passed.evidence.evaluation_time_s == pytest.approx(1.0)
    assert failed.status is RequirementStatus.FAIL
    assert failed.diagnostic_code == "STATE_NOT_REACHED"


def test_state_reached_within_time_pass_and_too_late_fail() -> None:
    context = _context(
        (
            _snapshot(0.0),
            _snapshot(2.0, EngineOperatingState.IDLE),
        ),
        actions={"start": _action("start", 0.5)},
    )

    passed = StateReachedWithinRequirementEvaluator(
        EngineOperatingState.IDLE,
        "start",
        maximum_elapsed_s=2.0,
    ).evaluate(context)
    failed = StateReachedWithinRequirementEvaluator(
        EngineOperatingState.IDLE,
        "start",
        maximum_elapsed_s=1.0,
    ).evaluate(context)

    assert passed.status is RequirementStatus.PASS
    assert passed.evidence.elapsed_time_s == pytest.approx(1.5)
    assert failed.status is RequirementStatus.FAIL
    assert failed.evidence.margin == pytest.approx(-0.5)


def test_state_sequence_ignores_repeated_snapshots_and_reports_mismatch() -> None:
    context = _context(
        (
            _snapshot(0.0),
            _snapshot(0.1),
            _snapshot(0.2, EngineOperatingState.CRANKING),
            _snapshot(0.3, EngineOperatingState.IDLE),
        )
    )
    expected = StateSequenceRequirementEvaluator(
        (
            EngineOperatingState.OFF,
            EngineOperatingState.CRANKING,
            EngineOperatingState.IDLE,
        )
    ).evaluate(context)
    mismatch = StateSequenceRequirementEvaluator(
        (EngineOperatingState.OFF, EngineOperatingState.IGNITION)
    ).evaluate(context)

    assert expected.status is RequirementStatus.PASS
    assert mismatch.status is RequirementStatus.FAIL
    assert "index 1" in str(mismatch.evidence.diagnostic_message)


def test_signal_maximum_pass_and_fail_capture_first_violation() -> None:
    context = _context(
        (
            _snapshot(0.0, allowed_fuel_command=0.2),
            _snapshot(0.1, allowed_fuel_command=0.8),
            _snapshot(0.2, allowed_fuel_command=1.1),
        )
    )

    passed = SignalMaximumRequirementEvaluator(
        NumericSignal.ALLOWED_FUEL_COMMAND,
        maximum=1.1,
    ).evaluate(context)
    failed = SignalMaximumRequirementEvaluator(
        NumericSignal.ALLOWED_FUEL_COMMAND,
        maximum=1.0,
    ).evaluate(context)

    assert passed.status is RequirementStatus.PASS
    assert failed.status is RequirementStatus.FAIL
    assert failed.evidence.first_violation_time_s == pytest.approx(0.2)
    assert failed.evidence.maximum_violation == pytest.approx(0.1)


def test_signal_minimum_pass_fail_and_tolerance_are_explicit() -> None:
    context = _context(
        (
            _snapshot(0.0, allowed_fuel_command=-0.001),
            _snapshot(0.1, allowed_fuel_command=0.5),
        )
    )

    passed = SignalMinimumRequirementEvaluator(
        NumericSignal.ALLOWED_FUEL_COMMAND,
        minimum=0.0,
        tolerance=0.002,
    ).evaluate(context)
    failed = SignalMinimumRequirementEvaluator(
        NumericSignal.ALLOWED_FUEL_COMMAND,
        minimum=0.0,
        tolerance=0.0,
    ).evaluate(context)

    assert passed.status is RequirementStatus.PASS
    assert failed.status is RequirementStatus.FAIL


def test_signal_band_pass_and_fail() -> None:
    passing_context = _context(
        (
            _snapshot(0.0, validated_rotor_speed_rpm=99.0),
            _snapshot(0.1, validated_rotor_speed_rpm=101.0),
        )
    )
    failing_context = _context(
        (_snapshot(0.0, validated_rotor_speed_rpm=103.0),)
    )
    evaluator = SignalBandRequirementEvaluator(
        NumericSignal.VALIDATED_ROTOR_SPEED_RPM,
        target=100.0,
        target_signal=None,
        tolerance_percent=2.0,
    )

    assert evaluator.evaluate(passing_context).status is RequirementStatus.PASS
    failure = evaluator.evaluate(failing_context)
    assert failure.status is RequirementStatus.FAIL
    assert failure.evidence.maximum_violation == pytest.approx(1.0)


def test_settling_time_requires_continuous_dwell_and_reports_failure() -> None:
    actions = {"step": _action("step", 0.0)}
    passing = _context(
        (
            _snapshot(0.0, validated_rotor_speed_rpm=80.0, speed_setpoint_rpm=100.0),
            _snapshot(0.1, validated_rotor_speed_rpm=99.0, speed_setpoint_rpm=100.0),
            _snapshot(0.2, validated_rotor_speed_rpm=100.0, speed_setpoint_rpm=100.0),
            _snapshot(0.3, validated_rotor_speed_rpm=100.0, speed_setpoint_rpm=100.0),
        ),
        actions=actions,
    )
    failing = _context(
        (
            _snapshot(0.0, validated_rotor_speed_rpm=80.0, speed_setpoint_rpm=100.0),
            _snapshot(0.1, validated_rotor_speed_rpm=99.0, speed_setpoint_rpm=100.0),
            _snapshot(0.2, validated_rotor_speed_rpm=80.0, speed_setpoint_rpm=100.0),
            _snapshot(0.3, validated_rotor_speed_rpm=99.0, speed_setpoint_rpm=100.0),
        ),
        actions=actions,
    )
    evaluator = SettlingTimeRequirementEvaluator(
        reference_action_id="step",
        signal=NumericSignal.VALIDATED_ROTOR_SPEED_RPM,
        tolerance_percent=2.0,
        dwell_time_s=0.2,
        maximum_settling_time_s=0.3,
    )

    assert evaluator.evaluate(passing).status is RequirementStatus.PASS
    assert evaluator.evaluate(failing).status is RequirementStatus.FAIL


def test_overshoot_pass_and_fail_handle_percentage_target() -> None:
    actions = {"step": _action("step", 0.0)}
    context = _context(
        (
            _snapshot(0.0, validated_rotor_speed_rpm=100.0, speed_setpoint_rpm=100.0),
            _snapshot(0.1, validated_rotor_speed_rpm=104.0, speed_setpoint_rpm=100.0),
        ),
        actions=actions,
    )

    passed = OvershootRequirementEvaluator(
        "step",
        NumericSignal.VALIDATED_ROTOR_SPEED_RPM,
        maximum_overshoot_percent=4.0,
    ).evaluate(context)
    failed = OvershootRequirementEvaluator(
        "step",
        NumericSignal.VALIDATED_ROTOR_SPEED_RPM,
        maximum_overshoot_percent=3.0,
    ).evaluate(context)

    assert passed.status is RequirementStatus.PASS
    assert failed.status is RequirementStatus.FAIL
    assert failed.evidence.measured_value == pytest.approx(4.0)


def test_actuator_invariant_pass_and_fail() -> None:
    passed = ActuatorInvariantRequirementEvaluator(
        ActuatorInvariant.FUEL_ZERO_IN_OFF
    ).evaluate(_context((_snapshot(0.0, allowed_fuel_command=0.0),)))
    failed = ActuatorInvariantRequirementEvaluator(
        ActuatorInvariant.FUEL_ZERO_IN_OFF
    ).evaluate(_context((_snapshot(0.0, allowed_fuel_command=0.1),)))

    assert passed.status is RequirementStatus.PASS
    assert failed.status is RequirementStatus.FAIL
    assert failed.evidence.first_violation_time_s == pytest.approx(0.0)


def test_event_observed_and_not_observed_pass_and_fail() -> None:
    context = _context(events=(_event(EventType.HARD_OVERSPEED_ACTIVATED),))

    observed = EventObservedRequirementEvaluator(
        EventType.HARD_OVERSPEED_ACTIVATED
    ).evaluate(context)
    missing = EventObservedRequirementEvaluator(
        EventType.LIMITER_RELEASED
    ).evaluate(context)
    absent = EventNotObservedRequirementEvaluator(
        EventType.LIMITER_RELEASED
    ).evaluate(context)
    unexpected = EventNotObservedRequirementEvaluator(
        EventType.HARD_OVERSPEED_ACTIVATED
    ).evaluate(context)

    assert observed.status is RequirementStatus.PASS
    assert missing.status is RequirementStatus.FAIL
    assert absent.status is RequirementStatus.PASS
    assert unexpected.status is RequirementStatus.FAIL


def test_fault_response_time_pass_and_fail() -> None:
    actions = {"fault": _action("fault", 1.0)}
    context = _context(
        (
            _snapshot(1.0, EngineOperatingState.RUNNING),
            _snapshot(
                1.2,
                EngineOperatingState.FAULT,
                rotor_speed_health=ChannelHealth.INVALID,
            ),
        ),
        actions=actions,
    )
    passed = FaultResponseTimeRequirementEvaluator(
        "fault",
        maximum_response_time_s=0.5,
        required_health=ChannelHealth.INVALID,
        health_signal="rotor_speed",
    ).evaluate(context)
    failed = FaultResponseTimeRequirementEvaluator(
        "fault",
        maximum_response_time_s=0.1,
    ).evaluate(context)

    assert passed.status is RequirementStatus.PASS
    assert failed.status is RequirementStatus.FAIL


def test_fuel_cutoff_response_pass_and_fail() -> None:
    actions = {"fault": _action("fault", 1.0)}
    passing = _context(
        (
            _snapshot(1.0, allowed_fuel_command=0.5),
            _snapshot(1.1, allowed_fuel_command=0.0),
        ),
        actions=actions,
    )
    failing = _context(
        (
            _snapshot(1.0, allowed_fuel_command=0.5),
            _snapshot(1.3, allowed_fuel_command=0.0),
        ),
        actions=actions,
    )
    evaluator = FuelCutoffResponseRequirementEvaluator(
        reference_action_id="fault",
        maximum_response_time_s=0.1,
    )

    assert evaluator.evaluate(passing).status is RequirementStatus.PASS
    assert evaluator.evaluate(failing).status is RequirementStatus.FAIL


def test_missing_or_unavailable_evidence_is_not_evaluated_not_zero() -> None:
    missing_action = StateReachedWithinRequirementEvaluator(
        EngineOperatingState.IDLE,
        "missing",
        maximum_elapsed_s=1.0,
    ).evaluate(_context((_snapshot(0.0),)))
    unavailable_signal = SignalMaximumRequirementEvaluator(
        NumericSignal.VALIDATED_ROTOR_SPEED_RPM,
        maximum=1.0,
    ).evaluate(
        _context((_snapshot(0.0, validated_rotor_speed_rpm=None),))
    )

    assert missing_action.status is RequirementStatus.NOT_EVALUATED
    assert unavailable_signal.status is RequirementStatus.NOT_EVALUATED


def test_sensor_health_and_no_truth_fallback_are_evaluated_explicitly() -> None:
    actions = {"dropout": _action("dropout", 1.0)}
    context = _context(
        (
            _snapshot(1.0, EngineOperatingState.RUNNING),
            _snapshot(
                1.1,
                EngineOperatingState.FAULT,
                measured_rotor_speed_rpm=None,
                validated_rotor_speed_rpm=50_000.0,
                rotor_speed_value_is_held=True,
                rotor_speed_health=ChannelHealth.INVALID,
            ),
        ),
        actions=actions,
    )

    health = SensorHealthReachedRequirementEvaluator(
        SensorChannel.ROTOR_SPEED,
        ChannelHealth.INVALID,
        "dropout",
    ).evaluate(context)
    fallback = NoTruthFallbackRequirementEvaluator(
        SensorChannel.ROTOR_SPEED,
        "dropout",
    ).evaluate(context)

    assert health.status is RequirementStatus.PASS
    assert fallback.status is RequirementStatus.PASS


def test_true_egt_uses_the_configured_snapshot_limit() -> None:
    evaluator = TrueEgtWithinConfiguredLimitRequirementEvaluator()
    passing = _context(
        (_snapshot(0.0, exhaust_temperature_c=679.0, egt_maximum_temperature_c=680.0),)
    )
    failing = _context(
        (_snapshot(0.0, exhaust_temperature_c=681.0, egt_maximum_temperature_c=680.0),)
    )

    assert evaluator.evaluate(passing).status is RequirementStatus.PASS
    failure = evaluator.evaluate(failing)
    assert failure.status is RequirementStatus.FAIL
    assert failure.diagnostic_code == "TRUE_EGT_LIMIT_EXCEEDED"


def test_throttle_schedule_evaluator_checks_clamping_and_linearity() -> None:
    points = (
        ("below", -0.2),
        ("zero", 0.0),
        ("middle", 0.5),
        ("maximum", 1.0),
        ("above", 1.2),
    )
    actions = {
        action_id: _action(action_id, float(index))
        for index, (action_id, _) in enumerate(points)
    }
    snapshots = tuple(
        _snapshot(
            float(index) + 0.1,
            EngineOperatingState.RUNNING,
            speed_control_enabled=True,
            throttle_demand=min(max(requested, 0.0), 1.0),
            speed_setpoint_rpm=(
                39_000.0
                + min(max(requested, 0.0), 1.0) * 89_000.0
            ),
        )
        for index, (_, requested) in enumerate(points)
    )

    outcome = ThrottleScheduleRequirementEvaluator(points).evaluate(
        _context(snapshots, actions=actions)
    )

    assert outcome.status is RequirementStatus.PASS
    assert outcome.evidence.measured_value == pytest.approx(0.0)


def test_protection_arbitration_reconstructs_concurrent_and_cutoff_cases() -> None:
    concurrent = _snapshot(
        1.0,
        EngineOperatingState.RUNNING,
        requested_fuel_command=0.8,
        egt_fuel_limit=0.6,
        acceleration_fuel_limit=0.5,
        state_maximum_fuel_command=1.0,
        deceleration_minimum_fuel_command=0.0,
        allowed_fuel_command=0.5,
        protection_hard_cutoff_active=False,
        protection_diagnostic_reasons=(
            ProtectionDiagnosticReason.EGT_LIMITING,
            ProtectionDiagnosticReason.ACCELERATION_LIMITING,
        ),
    )
    cutoff = replace(
        concurrent,
        simulation_time_s=1.1,
        allowed_fuel_command=0.0,
        protection_hard_cutoff_active=True,
    )
    evaluator = ProtectionArbitrationRequirementEvaluator(
        require_concurrent_limits=True,
        require_hard_cutoff=True,
    )

    assert evaluator.evaluate(
        _context((concurrent, cutoff))
    ).status is RequirementStatus.PASS


def test_ambient_evaluator_rejects_uncontrolled_snapshot_inputs() -> None:
    evaluator = AmbientConditionRequirementEvaluator(-20.0, 80_000.0)
    passing = _context(
        (_snapshot(0.0, ambient_temperature_c=-20.0, ambient_pressure_pa=80_000.0),)
    )
    failing = _context(
        (_snapshot(0.0, ambient_temperature_c=15.0, ambient_pressure_pa=101_325.0),)
    )

    assert evaluator.evaluate(passing).status is RequirementStatus.PASS
    assert evaluator.evaluate(failing).status is RequirementStatus.FAIL
