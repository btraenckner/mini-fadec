"""Unit tests for typed scenario definitions, actions, conditions, and triggers."""

from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from simulation.application.engine_simulation import EngineSimulationCoordinator
from simulation.operation.engine_state import EngineOperatingState
from simulation.protection.types import (
    ProtectionDiagnosticReason,
    ProtectionLimiter,
)
from simulation.scenarios.actions import (
    ActionExecutionStatus,
    ActionResult,
    AddMarkerAction,
    ClearSensorFaultAction,
    InjectSensorFaultAction,
    RequestManualFaultAction,
    RequestResetAction,
    RequestShutdownAction,
    SetFuelDeliveryFaultAction,
    SetThrottleAction,
    StartEngineAction,
    StartRecordingAction,
    StopRecordingAction,
)
from simulation.scenarios.conditions import (
    ActionExecutedCondition,
    ConditionContext,
    ConstrainingLimiterCondition,
    ElapsedAfterActionCondition,
    EngineStateEqualsCondition,
    EventTypeObservedCondition,
    ProtectionReasonActiveCondition,
    ValidatedEgtAboveCondition,
    ValidatedEgtAtMaximumCondition,
    ValidatedRotorSpeedAboveCondition,
)
from simulation.scenarios.definitions import Scenario
from simulation.scenarios.serialization import scenario_to_dict
from simulation.scenarios.triggers import AtTimeTrigger, WhenConditionTrigger
from simulation.sensors.fault_injection import (
    DropoutSensorFault,
    SensorChannel,
)
from simulation.telemetry.events import (
    EventCategory,
    EventSeverity,
    EventType,
    SimulationEvent,
)
from simulation.telemetry.recorder import RunRecordingSummary
from simulation.verification.evidence import RequirementEvidence
from simulation.verification.requirements import (
    EvaluationOutcome,
    Requirement,
    RequirementCategory,
    RequirementCriticality,
    RequirementStatus,
)


@dataclass(frozen=True)
class PassingEvaluator:
    def evaluate(self, context: object) -> EvaluationOutcome:
        return EvaluationOutcome(
            RequirementStatus.PASS,
            RequirementEvidence(),
            "passed",
        )


class FakeService:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.calls: list[object] = []
        self.recording = False

    def request_start(self) -> None:
        self.calls.append("start")

    def set_throttle(self, throttle_demand: float) -> float:
        self.calls.append(("throttle", throttle_demand))
        return max(0.0, min(throttle_demand, 1.0))

    def request_shutdown(self) -> None:
        self.calls.append("shutdown")

    def request_fault(self) -> None:
        self.calls.append("fault")

    def request_reset(self) -> None:
        self.calls.append("reset")

    def inject_sensor_fault(self, channel: object, fault: object) -> None:
        self.calls.append(("inject", channel, fault))

    def clear_sensor_fault(self, channel: object) -> None:
        self.calls.append(("clear", channel))

    def set_fuel_delivery_fault(self, active: bool) -> None:
        self.calls.append(("fuel_delivery_fault", active))

    def add_marker(self, text: str) -> SimulationEvent:
        self.calls.append(("marker", text))
        return _event(EventType.USER_MARKER)

    def start_recording(self, run_name: str | None = None) -> Path:
        self.recording = True
        self.calls.append(("record_start", run_name))
        return self.tmp_path

    def stop_recording(
        self,
        *,
        completed: bool = True,
    ) -> RunRecordingSummary | None:
        self.calls.append(("record_stop", completed))
        if not self.recording:
            return None
        self.recording = False
        return RunRecordingSummary(
            run_name="test",
            run_directory=self.tmp_path,
            telemetry_sample_count=1,
            event_count=1,
            telemetry_sampling_period_s=0.05,
            completion_status="complete",
        )


def _requirement(requirement_id: str = "REQ-1") -> Requirement:
    return Requirement(
        requirement_id=requirement_id,
        description="A test requirement",
        category=RequirementCategory.LOGICAL_INVARIANT,
        criticality=RequirementCriticality.MAJOR,
        evaluator=PassingEvaluator(),
    )


def _action(action_id: str = "start") -> StartEngineAction:
    return StartEngineAction(
        action_id=action_id,
        description="Start",
        trigger=AtTimeTrigger(0.0),
    )


def _scenario(**changes: object) -> Scenario:
    values: dict[str, object] = {
        "scenario_id": "SCN-TEST-001",
        "name": "test_scenario",
        "description": "Test scenario",
        "max_duration_s": 1.0,
        "actions": (_action(),),
        "requirements": (_requirement(),),
    }
    values.update(changes)
    return Scenario(**values)  # type: ignore[arg-type]


def _event(event_type: EventType) -> SimulationEvent:
    return SimulationEvent(
        simulation_time_s=0.5,
        event_sequence=1,
        category=EventCategory.SYSTEM,
        event_type=event_type,
        severity=EventSeverity.INFO,
        source="test",
        message="event",
    )


def _context(
    *,
    time_s: float = 0.0,
    state: EngineOperatingState = EngineOperatingState.OFF,
    events: tuple[SimulationEvent, ...] = (),
    action_results: dict[str, ActionResult] | None = None,
) -> ConditionContext:
    initial = EngineSimulationCoordinator().snapshot
    snapshot = replace(
        initial,
        simulation_time_s=time_s,
        operating_state=state,
    )
    return ConditionContext(
        latest_snapshot=snapshot,
        snapshots=(initial, snapshot),
        recent_events=events,
        action_results=action_results or {},
    )


def test_valid_scenario_can_be_constructed_with_immutable_defaults() -> None:
    first = _scenario()
    second = _scenario(scenario_id="SCN-TEST-002")

    assert first.actions[0].action_id == "start"
    assert first.tags == second.tags == ()
    assert first.configuration_overrides == second.configuration_overrides == ()


def test_duplicate_action_and_requirement_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate action ID"):
        _scenario(actions=(_action("same"), _action("same")))
    with pytest.raises(ValueError, match="duplicate requirement ID"):
        _scenario(requirements=(_requirement("same"), _requirement("same")))


@pytest.mark.parametrize("duration", [0.0, -1.0])
def test_nonpositive_duration_is_rejected(duration: float) -> None:
    with pytest.raises(ValueError, match="max_duration_s"):
        _scenario(max_duration_s=duration)


def test_invalid_trigger_and_unknown_dependency_are_rejected() -> None:
    invalid = replace(_action(), trigger=object())
    with pytest.raises(TypeError, match="unsupported trigger"):
        _scenario(actions=(invalid,))

    dependent = SetThrottleAction(
        action_id="dependent",
        description="Dependent",
        trigger=WhenConditionTrigger(ActionExecutedCondition("missing")),
        throttle_demand=0.5,
    )
    with pytest.raises(ValueError, match="unknown action"):
        _scenario(actions=(_action(), dependent))


def test_scenario_serialization_is_deterministic_and_typed() -> None:
    scenario = _scenario(tags=("test",))

    first = scenario_to_dict(scenario)
    second = scenario_to_dict(scenario)

    assert first == second
    assert first["actions"][0]["type"] == "StartEngineAction"  # type: ignore[index]
    assert first["requirements"][0]["evaluator"]["type"] == "PassingEvaluator"  # type: ignore[index]


def test_unsupported_configuration_override_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported configuration"):
        _scenario(configuration_overrides=(("engine_object", "forbidden"),))


def test_time_trigger_boundary_crossing_and_condition_timeout_are_deterministic() -> None:
    trigger = AtTimeTrigger(1.0)

    assert not trigger.is_due(_context(time_s=0.99))
    assert trigger.is_due(_context(time_s=1.0))
    assert trigger.is_due(_context(time_s=1.01))

    conditional = WhenConditionTrigger(
        EngineStateEqualsCondition(EngineOperatingState.IDLE),
        timeout_s=2.0,
    )
    assert conditional.is_due(_context(state=EngineOperatingState.IDLE))
    assert not conditional.has_timed_out(2.0)
    assert conditional.has_timed_out(2.01)


def test_state_signal_event_and_dependency_conditions_use_observable_data() -> None:
    completed = ActionResult(
        action_id="first",
        description="first",
        action_type="TestAction",
        status=ActionExecutionStatus.EXECUTED,
        required_success=True,
        execution_time_s=0.5,
    )
    context = _context(
        time_s=1.0,
        state=EngineOperatingState.IDLE,
        events=(_event(EventType.USER_MARKER),),
        action_results={"first": completed},
    )
    context = replace(
        context,
        latest_snapshot=replace(
            context.latest_snapshot,
            validated_rotor_speed_rpm=40_000.0,
            validated_exhaust_temperature_c=500.0,
        ),
    )

    assert EngineStateEqualsCondition(EngineOperatingState.IDLE).evaluate(context)
    assert ValidatedRotorSpeedAboveCondition(39_000.0).evaluate(context)
    assert ValidatedEgtAboveCondition(499.0).evaluate(context)
    assert ValidatedEgtAtMaximumCondition().evaluate(
        replace(
            context,
            latest_snapshot=replace(
                context.latest_snapshot,
                validated_exhaust_temperature_c=680.0,
                egt_maximum_temperature_c=680.0,
            ),
        )
    )
    assert ConstrainingLimiterCondition(ProtectionLimiter.EGT).evaluate(
        replace(
            context,
            latest_snapshot=replace(
                context.latest_snapshot,
                constraining_protection_limiters=(ProtectionLimiter.EGT,),
            ),
        )
    )
    assert ProtectionReasonActiveCondition(
        ProtectionDiagnosticReason.EGT_LIMITING
    ).evaluate(
        replace(
            context,
            latest_snapshot=replace(
                context.latest_snapshot,
                protection_diagnostic_reasons=(
                    ProtectionDiagnosticReason.EGT_LIMITING,
                ),
            ),
        )
    )
    assert EventTypeObservedCondition(EventType.USER_MARKER).evaluate(context)
    assert ActionExecutedCondition("first").evaluate(context)
    assert ElapsedAfterActionCondition("first", 0.5).evaluate(context)


def test_unavailable_signal_conditions_do_not_convert_none_to_zero() -> None:
    context = _context()
    context = replace(
        context,
        latest_snapshot=replace(
            context.latest_snapshot,
            validated_rotor_speed_rpm=None,
            validated_exhaust_temperature_c=None,
        ),
    )

    assert not ValidatedRotorSpeedAboveCondition(0.0).evaluate(context)
    assert not ValidatedEgtAboveCondition(0.0).evaluate(context)


def test_typed_actions_route_every_command_through_service(tmp_path: Path) -> None:
    service = FakeService(tmp_path)
    trigger = AtTimeTrigger(0.0)
    actions = (
        _action(),
        SetThrottleAction(
            action_id="throttle",
            description="Throttle",
            trigger=trigger,
            throttle_demand=0.5,
        ),
        RequestShutdownAction(
            action_id="shutdown",
            description="Shutdown",
            trigger=trigger,
        ),
        RequestResetAction(
            action_id="reset",
            description="Reset",
            trigger=trigger,
        ),
        RequestManualFaultAction(
            action_id="fault",
            description="Fault",
            trigger=trigger,
        ),
        InjectSensorFaultAction(
            action_id="inject",
            description="Inject",
            trigger=trigger,
            channel=SensorChannel.ROTOR_SPEED,
            fault=DropoutSensorFault(),
        ),
        ClearSensorFaultAction(
            action_id="clear",
            description="Clear",
            trigger=trigger,
            channel=SensorChannel.ROTOR_SPEED,
        ),
        SetFuelDeliveryFaultAction(
            action_id="fuel_fault",
            description="Fuel delivery fault",
            trigger=trigger,
            active=True,
        ),
        AddMarkerAction(
            action_id="marker",
            description="Marker",
            trigger=trigger,
            marker_text="test marker",
        ),
        StartRecordingAction(
            action_id="record",
            description="Record",
            trigger=trigger,
            run_name="scenario",
        ),
        StopRecordingAction(
            action_id="stop_record",
            description="Stop record",
            trigger=trigger,
        ),
    )

    for action in actions:
        action.execute(service)

    assert service.calls == [
        "start",
        ("throttle", 0.5),
        "shutdown",
        "reset",
        "fault",
        ("inject", SensorChannel.ROTOR_SPEED, DropoutSensorFault()),
        ("clear", SensorChannel.ROTOR_SPEED),
        ("fuel_delivery_fault", True),
        ("marker", "test marker"),
        ("record_start", "scenario"),
        ("record_stop", True),
    ]


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_throttle_action_rejects_invalid_input(value: float) -> None:
    with pytest.raises(ValueError, match="throttle"):
        SetThrottleAction(
            action_id="throttle",
            description="Throttle",
            trigger=AtTimeTrigger(0.0),
            throttle_demand=value,
        )


@pytest.mark.parametrize(
    ("requested", "accepted"),
    [(-0.1, 0.0), (1.1, 1.0)],
)
def test_throttle_action_allows_service_boundary_clamping(
    tmp_path: Path,
    requested: float,
    accepted: float,
) -> None:
    service = FakeService(tmp_path)

    message = SetThrottleAction(
        action_id="throttle",
        description="Throttle",
        trigger=AtTimeTrigger(0.0),
        throttle_demand=requested,
    ).execute(service)

    assert service.calls == [("throttle", requested)]
    assert message == f"throttle set to {accepted:.3f}"
