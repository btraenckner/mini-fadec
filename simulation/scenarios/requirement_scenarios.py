"""Focused deterministic scenarios for formal FADEC requirement evidence."""

from dataclasses import replace

from simulation.operation.engine_state import EngineOperatingState
from simulation.protection.types import (
    ProtectionDiagnosticReason,
    ProtectionLimiter,
)
from simulation.scenarios.actions import (
    AddMarkerAction,
    ClearSensorFaultAction,
    InjectSensorFaultAction,
    RequestManualFaultAction,
    RequestResetAction,
    SetFuelDeliveryFaultAction,
    SetThrottleAction,
    StartEngineAction,
)
from simulation.scenarios.conditions import (
    AllConditions,
    ElapsedAfterActionCondition,
    EngineStateEqualsCondition,
    EventTypeObservedCondition,
    ProtectionReasonActiveCondition,
    SensorHealthEqualsCondition,
    ValidatedEgtAtMaximumCondition,
    ValidatedRotorSpeedBelowCondition,
)
from simulation.scenarios.definitions import RecordingConfiguration, Scenario
from simulation.scenarios.triggers import AtTimeTrigger, WhenConditionTrigger
from simulation.sensors.fault_injection import (
    BiasSensorFault,
    DriftSensorFault,
    DropoutSensorFault,
    ExcessiveNoiseSensorFault,
    ForcedValueSensorFault,
    SensorChannel,
    SensorFaultDefinition,
    StuckSensorFault,
)
from simulation.telemetry.events import EventType
from simulation.validation.sensor_validation import ChannelHealth
from simulation.verification.evaluators import (
    ActuatorInvariant,
    ActuatorInvariantRequirementEvaluator,
    AmbientConditionRequirementEvaluator,
    EgtLimitFuelCutoffRequirementEvaluator,
    EgtLimiterCharacteristicRequirementEvaluator,
    EventObservedRequirementEvaluator,
    HungStartTimeoutRequirementEvaluator,
    ProtectionArbitrationRequirementEvaluator,
    ProtectionLimiterObservedRequirementEvaluator,
    ResetInterlockRequirementEvaluator,
    SensorFaultMatrixRequirementEvaluator,
    ThrottleScheduleRequirementEvaluator,
)
from simulation.verification.requirements import (
    Requirement,
    RequirementCategory,
    RequirementCriticality,
)


def _requirement(
    requirement_id: str,
    description: str,
    category: RequirementCategory,
    evaluator: object,
    criticality: RequirementCriticality = RequirementCriticality.MAJOR,
) -> Requirement:
    return Requirement(
        requirement_id=requirement_id,
        description=description,
        category=category,
        criticality=criticality,
        evaluator=evaluator,  # type: ignore[arg-type]
    )


def _fuel_bounds_requirement(prefix: str) -> Requirement:
    return _requirement(
        f"{prefix}-FUEL-BOUNDS",
        "Final fuel command shall remain within [0.0, 1.0].",
        RequirementCategory.ACTUATOR_SAFETY,
        ActuatorInvariantRequirementEvaluator(ActuatorInvariant.FUEL_BOUNDED),
        RequirementCriticality.CRITICAL,
    )


def fault_reset_interlock_scenario() -> Scenario:
    """Exercise reset rejection while turning and acceptance when stopped."""

    return Scenario(
        scenario_id="SCN-OPS-003",
        name="fault_reset_interlock",
        description=(
            "Enter FAULT from RUNNING, reject reset while turning, then accept "
            "reset after the validated rotor reaches the stopped threshold."
        ),
        max_duration_s=30.0,
        actions=(
            StartEngineAction(
                action_id="start",
                description="Request startup",
                trigger=AtTimeTrigger(0.10),
            ),
            SetThrottleAction(
                action_id="set_running_throttle",
                description="Establish a turning RUNNING condition",
                trigger=WhenConditionTrigger(
                    EngineStateEqualsCondition(EngineOperatingState.IDLE),
                    timeout_s=12.0,
                ),
                throttle_demand=0.55,
            ),
            RequestManualFaultAction(
                action_id="request_fault",
                description="Enter the latched FAULT state",
                trigger=WhenConditionTrigger(
                    ElapsedAfterActionCondition("set_running_throttle", 2.0),
                    timeout_s=18.0,
                ),
            ),
            RequestResetAction(
                action_id="reset_while_turning",
                description="Request reset while rotor speed exceeds stopped",
                trigger=WhenConditionTrigger(
                    AllConditions(
                        (
                            ElapsedAfterActionCondition("request_fault", 0.05),
                            EngineStateEqualsCondition(
                                EngineOperatingState.FAULT
                            ),
                        )
                    ),
                    timeout_s=19.0,
                ),
            ),
            RequestResetAction(
                action_id="reset_when_stopped",
                description="Request reset at or below the stopped threshold",
                trigger=WhenConditionTrigger(
                    AllConditions(
                        (
                            EngineStateEqualsCondition(
                                EngineOperatingState.FAULT
                            ),
                            ValidatedRotorSpeedBelowCondition(400.0),
                        )
                    ),
                    timeout_s=29.0,
                ),
            ),
        ),
        requirements=(
            _requirement(
                "REQ-OPS-RESET-INTERLOCK",
                "Turning reset shall be rejected and stopped reset accepted.",
                RequirementCategory.LOGICAL_INVARIANT,
                ResetInterlockRequirementEvaluator(
                    turning_reset_action_id="reset_while_turning",
                    stopped_reset_action_id="reset_when_stopped",
                ),
                RequirementCriticality.CRITICAL,
            ),
            _fuel_bounds_requirement("REQ-OPS-RESET"),
        ),
        tags=("operation", "fault", "reset", "regression"),
        recording=RecordingConfiguration(
            run_name="scenario_fault_reset_interlock"
        ),
        expected_terminal_condition=EngineStateEqualsCondition(
            EngineOperatingState.OFF
        ),
    )


def hot_start_protection_scenario() -> Scenario:
    """Hold the plant below self-sustaining speed and sweep validated EGT."""

    return Scenario(
        scenario_id="SCN-START-001",
        name="hot_start_protection",
        description=(
            "Prevent physical fuel delivery during IGNITION while a controlled "
            "valid EGT drift reaches the configured transient limit."
        ),
        max_duration_s=8.0,
        actions=(
            SetFuelDeliveryFaultAction(
                action_id="block_fuel_delivery",
                description="Prevent the plant from completing light-off",
                trigger=AtTimeTrigger(0.0),
                active=True,
            ),
            StartEngineAction(
                action_id="start",
                description="Request startup",
                trigger=AtTimeTrigger(0.10),
            ),
            InjectSensorFaultAction(
                action_id="inject_egt_drift",
                description="Sweep validated EGT to the transient limit",
                trigger=WhenConditionTrigger(
                    EngineStateEqualsCondition(EngineOperatingState.IGNITION),
                    timeout_s=4.0,
                ),
                channel=SensorChannel.EXHAUST_TEMPERATURE,
                fault=DriftSensorFault(rate_per_second=400.0),
            ),
            AddMarkerAction(
                action_id="egt_maximum_reached",
                description="Close the hot-start cutoff evidence window",
                trigger=WhenConditionTrigger(
                    ValidatedEgtAtMaximumCondition(),
                    timeout_s=7.0,
                ),
                marker_text="hot-start EGT maximum reached",
            ),
        ),
        requirements=(
            _requirement(
                "REQ-START-HOT-FUEL-CUTOFF",
                "Fuel shall reach zero at the start EGT maximum.",
                RequirementCategory.PROTECTION,
                EgtLimitFuelCutoffRequirementEvaluator("inject_egt_drift"),
                RequirementCriticality.CRITICAL,
            ),
            _requirement(
                "REQ-START-HOT-EGT-LIMITER",
                "EGT protection shall constrain the constant start fuel request.",
                RequirementCategory.PROTECTION,
                ProtectionLimiterObservedRequirementEvaluator(
                    ProtectionLimiter.EGT,
                    reference_action_id="inject_egt_drift",
                ),
                RequirementCriticality.CRITICAL,
            ),
            _fuel_bounds_requirement("REQ-START-HOT"),
        ),
        tags=("start", "hot-start", "protection", "regression"),
        recording=RecordingConfiguration(
            run_name="scenario_hot_start_protection"
        ),
        expected_terminal_condition=EngineStateEqualsCondition(
            EngineOperatingState.IGNITION
        ),
    )


def hung_start_timeout_scenario() -> Scenario:
    """Prevent light-off until deterministic start supervision expires."""

    return Scenario(
        scenario_id="SCN-START-002",
        name="hung_start_timeout",
        description=(
            "Inject complete physical fuel-delivery loss, request start, and "
            "retain the stimulus through the configured 10-second timeout."
        ),
        max_duration_s=12.0,
        actions=(
            SetFuelDeliveryFaultAction(
                action_id="block_fuel_delivery",
                description="Prevent combustion and IDLE entry",
                trigger=AtTimeTrigger(0.0),
                active=True,
            ),
            StartEngineAction(
                action_id="start",
                description="Request startup",
                trigger=AtTimeTrigger(0.10),
            ),
            AddMarkerAction(
                action_id="start_timeout_observed",
                description="Mark the supervised hung-start response",
                trigger=WhenConditionTrigger(
                    EventTypeObservedCondition(
                        EventType.START_TIMEOUT_ACTIVATED
                    ),
                    timeout_s=11.0,
                ),
                marker_text="hung-start timeout observed",
            ),
        ),
        requirements=(
            _requirement(
                "REQ-START-HUNG-TIMEOUT",
                "An unsuccessful start shall enter safe FAULT in 10 seconds.",
                RequirementCategory.STATE_TIMING,
                HungStartTimeoutRequirementEvaluator(
                    start_action_id="start",
                    maximum_start_duration_s=10.0,
                ),
                RequirementCriticality.CRITICAL,
            ),
            _requirement(
                "REQ-START-HUNG-EVENT",
                "The hung-start timeout shall be recorded.",
                RequirementCategory.STATE_TIMING,
                EventObservedRequirementEvaluator(
                    EventType.START_TIMEOUT_ACTIVATED
                ),
                RequirementCriticality.CRITICAL,
            ),
            _requirement(
                "REQ-START-HUNG-FAULT-FUEL",
                "Fuel shall remain zero after the hung-start FAULT.",
                RequirementCategory.ACTUATOR_SAFETY,
                ActuatorInvariantRequirementEvaluator(
                    ActuatorInvariant.FUEL_ZERO_IN_FAULT
                ),
                RequirementCriticality.CRITICAL,
            ),
            _fuel_bounds_requirement("REQ-START-HUNG"),
        ),
        tags=("start", "hung-start", "timeout", "regression"),
        recording=RecordingConfiguration(run_name="scenario_hung_start_timeout"),
        expected_terminal_condition=EngineStateEqualsCondition(
            EngineOperatingState.FAULT
        ),
    )


def throttle_schedule_scenario() -> Scenario:
    """Capture integrated throttle clamping and speed scheduling points."""

    points = (
        ("throttle_below_minimum", -0.25),
        ("throttle_at_minimum", 0.0),
        ("throttle_mid_range", 0.5),
        ("throttle_at_maximum", 1.0),
        ("throttle_above_maximum", 1.25),
    )
    actions = [
        StartEngineAction(
            action_id="start",
            description="Request startup",
            trigger=AtTimeTrigger(0.10),
        ),
        SetThrottleAction(
            action_id=points[0][0],
            description="Apply throttle below the normalized range",
            trigger=WhenConditionTrigger(
                EngineStateEqualsCondition(EngineOperatingState.IDLE),
                timeout_s=12.0,
            ),
            throttle_demand=points[0][1],
        ),
    ]
    for index, (action_id, throttle) in enumerate(points[1:], start=1):
        actions.append(
            SetThrottleAction(
                action_id=action_id,
                description=f"Apply schedule point {throttle:g}",
                trigger=WhenConditionTrigger(
                    ElapsedAfterActionCondition(points[index - 1][0], 0.25),
                    timeout_s=14.0,
                ),
                throttle_demand=throttle,
            )
        )
    actions.append(
        AddMarkerAction(
            action_id="schedule_complete",
            description="Close the throttle-schedule evidence window",
            trigger=WhenConditionTrigger(
                ElapsedAfterActionCondition(points[-1][0], 0.25),
                timeout_s=15.0,
            ),
            marker_text="throttle schedule sweep complete",
        )
    )
    return Scenario(
        scenario_id="SCN-SPD-001",
        name="throttle_speed_schedule",
        description=(
            "Apply below-range, endpoint, intermediate, and above-range "
            "throttle demands through the application boundary."
        ),
        max_duration_s=16.0,
        actions=tuple(actions),
        requirements=(
            _requirement(
                "REQ-SPD-THROTTLE-SCHEDULE",
                "Throttle shall clamp and map linearly to scheduled speed.",
                RequirementCategory.SIGNAL_LIMIT,
                ThrottleScheduleRequirementEvaluator(points),
                RequirementCriticality.MAJOR,
            ),
            _fuel_bounds_requirement("REQ-SPD-SCHEDULE"),
        ),
        tags=("speed-control", "schedule", "clamping", "regression"),
        recording=RecordingConfiguration(
            run_name="scenario_throttle_speed_schedule"
        ),
        expected_terminal_condition=EngineStateEqualsCondition(
            EngineOperatingState.RUNNING
        ),
    )


def egt_limiter_arbitration_scenario() -> Scenario:
    """Exercise integrated EGT limiting concurrently with acceleration limiting."""

    return Scenario(
        scenario_id="SCN-PROT-003",
        name="egt_limiter_arbitration",
        description=(
            "Apply a large throttle step and controlled valid EGT drift so EGT "
            "and acceleration limits overlap at the centralized arbiter."
        ),
        max_duration_s=16.0,
        actions=(
            StartEngineAction(
                action_id="start",
                description="Request startup",
                trigger=AtTimeTrigger(0.10),
            ),
            SetThrottleAction(
                action_id="large_throttle_step",
                description="Apply a large acceleration demand",
                trigger=WhenConditionTrigger(
                    EngineStateEqualsCondition(EngineOperatingState.IDLE),
                    timeout_s=12.0,
                ),
                throttle_demand=0.85,
            ),
            InjectSensorFaultAction(
                action_id="inject_egt_drift",
                description="Sweep EGT through its intervention region",
                trigger=WhenConditionTrigger(
                    ElapsedAfterActionCondition("large_throttle_step", 0.0),
                    timeout_s=12.5,
                ),
                channel=SensorChannel.EXHAUST_TEMPERATURE,
                fault=DriftSensorFault(rate_per_second=600.0),
            ),
            AddMarkerAction(
                action_id="concurrent_limits_observed",
                description="Mark concurrent EGT and acceleration constraints",
                trigger=WhenConditionTrigger(
                    AllConditions(
                        (
                            ProtectionReasonActiveCondition(
                                ProtectionDiagnosticReason.EGT_LIMITING
                            ),
                            ProtectionReasonActiveCondition(
                                ProtectionDiagnosticReason.ACCELERATION_LIMITING
                            ),
                        )
                    ),
                    timeout_s=14.0,
                ),
                marker_text="concurrent EGT and acceleration limits observed",
            ),
            AddMarkerAction(
                action_id="egt_maximum_reached",
                description="Mark the end of the EGT sweep",
                trigger=WhenConditionTrigger(
                    ValidatedEgtAtMaximumCondition(),
                    timeout_s=14.5,
                ),
                marker_text="EGT limiter sweep reached maximum",
            ),
        ),
        requirements=(
            _requirement(
                "REQ-EGT-LIMITER-CHARACTERISTIC",
                "EGT fuel restriction shall increase through intervention.",
                RequirementCategory.PROTECTION,
                EgtLimiterCharacteristicRequirementEvaluator(
                    reference_action_id="inject_egt_drift",
                    end_action_id="egt_maximum_reached",
                ),
                RequirementCriticality.CRITICAL,
            ),
            _requirement(
                "REQ-PROT-ARBITRATION-CONCURRENT",
                "Concurrent protection limits shall retain the safest fuel command.",
                RequirementCategory.LOGICAL_INVARIANT,
                ProtectionArbitrationRequirementEvaluator(
                    reference_action_id="large_throttle_step",
                    require_concurrent_limits=True,
                ),
                RequirementCriticality.CRITICAL,
            ),
            _fuel_bounds_requirement("REQ-EGT-ARBITRATION"),
        ),
        tags=("protection", "egt", "arbitration", "regression"),
        recording=RecordingConfiguration(
            run_name="scenario_egt_limiter_arbitration"
        ),
        expected_terminal_condition=EngineStateEqualsCondition(
            EngineOperatingState.RUNNING
        ),
    )


def _fault_matrix(
    channel: SensorChannel,
) -> tuple[tuple[str, SensorFaultDefinition, float], ...]:
    if channel is SensorChannel.ROTOR_SPEED:
        return (
            ("bias", BiasSensorFault(offset=100.0), 0.45),
            ("drift", DriftSensorFault(rate_per_second=500.0), 0.45),
            ("stuck", StuckSensorFault(), 0.45),
            ("forced_value", ForcedValueSensorFault(value=84_000.0), 0.20),
            ("excessive_noise", ExcessiveNoiseSensorFault(50.0), 0.45),
            ("dropout", DropoutSensorFault(), 0.05),
        )
    return (
        ("bias", BiasSensorFault(offset=2.0), 0.45),
        ("drift", DriftSensorFault(rate_per_second=5.0), 0.45),
        ("stuck", StuckSensorFault(), 0.45),
        ("forced_value", ForcedValueSensorFault(value=550.0), 0.20),
        ("excessive_noise", ExcessiveNoiseSensorFault(0.5), 0.45),
        ("dropout", DropoutSensorFault(), 0.05),
    )


def sensor_fault_matrix_scenario(channel: SensorChannel) -> Scenario:
    """Exercise every supported injected fault and recovery on one channel."""

    channel_name = channel.value
    actions = [
        StartEngineAction(
            action_id="start",
            description="Request startup",
            trigger=AtTimeTrigger(0.10),
        ),
        SetThrottleAction(
            action_id="set_running_throttle",
            description="Establish a stable test condition",
            trigger=WhenConditionTrigger(
                EngineStateEqualsCondition(EngineOperatingState.IDLE),
                timeout_s=12.0,
            ),
            throttle_demand=0.50,
        ),
    ]
    previous_action_id = "set_running_throttle"
    for index, (fault_name, fault, duration_s) in enumerate(
        _fault_matrix(channel)
    ):
        inject_id = f"inject_{fault_name}"
        clear_id = f"clear_{fault_name}"
        delay_s = 4.0 if index == 0 else 0.40
        actions.extend(
            (
                InjectSensorFaultAction(
                    action_id=inject_id,
                    description=f"Inject {channel_name} {fault_name} fault",
                    trigger=WhenConditionTrigger(
                        ElapsedAfterActionCondition(previous_action_id, delay_s),
                        timeout_s=22.0,
                    ),
                    channel=channel,
                    fault=fault,
                ),
                ClearSensorFaultAction(
                    action_id=clear_id,
                    description=f"Clear {channel_name} {fault_name} fault",
                    trigger=WhenConditionTrigger(
                        ElapsedAfterActionCondition(inject_id, duration_s),
                        timeout_s=23.0,
                    ),
                    channel=channel,
                ),
            )
        )
        previous_action_id = clear_id
    actions.append(
        AddMarkerAction(
            action_id="matrix_recovery_complete",
            description="Close the channel recovery evidence window",
            trigger=WhenConditionTrigger(
                AllConditions(
                    (
                        ElapsedAfterActionCondition(previous_action_id, 0.40),
                        SensorHealthEqualsCondition(channel, ChannelHealth.VALID),
                    )
                ),
                timeout_s=24.0,
            ),
            marker_text=f"{channel_name} fault matrix recovery complete",
        )
    )
    return Scenario(
        scenario_id=(
            "SCN-SENS-004" if channel is SensorChannel.ROTOR_SPEED else "SCN-SENS-005"
        ),
        name=f"{channel_name}_sensor_fault_matrix",
        description=(
            f"Apply bias, drift, stuck, forced-value, excessive-noise, and "
            f"dropout faults to the {channel_name} channel and clear each one."
        ),
        max_duration_s=25.0,
        actions=tuple(actions),
        requirements=(
            _requirement(
                f"REQ-{channel_name.upper()}-FAULT-MATRIX",
                "Every supported fault and its recovery shall be captured.",
                RequirementCategory.SENSOR_FAULT_RESPONSE,
                SensorFaultMatrixRequirementEvaluator(channel),
                RequirementCriticality.MAJOR,
            ),
            _fuel_bounds_requirement(f"REQ-{channel_name.upper()}-MATRIX"),
        ),
        tags=("sensor", "fault-matrix", channel_name, "regression"),
        recording=RecordingConfiguration(
            run_name=f"scenario_{channel_name}_sensor_fault_matrix"
        ),
        expected_terminal_condition=EngineStateEqualsCondition(
            EngineOperatingState.FAULT
        ),
    )


def ambient_challenge_scenario(
    source: Scenario,
    *,
    scenario_id: str,
    name: str,
    temperature_c: float,
    pressure_pa: float,
) -> Scenario:
    """Create a controlled SIL ambient point without claiming plant fidelity."""

    overrides = dict(source.configuration_overrides)
    overrides.update(
        ambient_temperature_c=temperature_c,
        ambient_pressure_pa=pressure_pa,
    )
    return replace(
        source,
        scenario_id=scenario_id,
        name=name,
        description=(
            f"Controlled SIL ambient challenge at {temperature_c:g} °C and "
            f"{pressure_pa:g} Pa using the normal lifecycle. The reference "
            "plant does not yet model physical ambient sensitivity."
        ),
        requirements=(
            *source.requirements,
            _requirement(
                f"REQ-{scenario_id.removeprefix('SCN-')}-AMBIENT",
                "Ambient inputs shall remain controlled with bounded finite behavior.",
                RequirementCategory.LOGICAL_INVARIANT,
                AmbientConditionRequirementEvaluator(
                    expected_temperature_c=temperature_c,
                    expected_pressure_pa=pressure_pa,
                ),
                RequirementCriticality.CRITICAL,
            ),
        ),
        tags=tuple(
            dict.fromkeys((*source.tags, "ambient", "sil-challenge"))
        ),
        recording=replace(source.recording, run_name=f"scenario_{name}"),
        configuration_overrides=tuple(overrides.items()),
    )
