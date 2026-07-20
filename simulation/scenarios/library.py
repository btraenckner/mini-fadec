"""Explicit deterministic regression-scenario library."""

from simulation.operation.engine_state import EngineOperatingState
from simulation.protection.types import ProtectionLimiter
from simulation.scenarios.actions import (
    AddMarkerAction,
    ClearSensorFaultAction,
    InjectSensorFaultAction,
    RequestShutdownAction,
    SetThrottleAction,
    StartEngineAction,
)
from simulation.scenarios.conditions import (
    AllConditions,
    ElapsedAfterActionCondition,
    EngineStateEqualsCondition,
    EventTypeObservedCondition,
)
from simulation.scenarios.definitions import RecordingConfiguration, Scenario
from simulation.scenarios.triggers import AtTimeTrigger, WhenConditionTrigger
from simulation.sensors.fault_injection import (
    DriftSensorFault,
    DropoutSensorFault,
    SensorChannel,
)
from simulation.telemetry.events import EventType
from simulation.validation.sensor_validation import ChannelHealth
from simulation.verification.evaluators import (
    AccelerationLimitRequirementEvaluator,
    ActuatorInvariant,
    ActuatorInvariantRequirementEvaluator,
    EventNotObservedRequirementEvaluator,
    EventObservedRequirementEvaluator,
    FaultResponseTimeRequirementEvaluator,
    FuelCutoffResponseRequirementEvaluator,
    NoTruthFallbackRequirementEvaluator,
    NumericSignal,
    OvershootRequirementEvaluator,
    ProtectionLimiterObservedRequirementEvaluator,
    SensorHealthReachedRequirementEvaluator,
    SettlingTimeRequirementEvaluator,
    StateReachedWithinRequirementEvaluator,
    StateSequenceRequirementEvaluator,
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


def _common_fuel_requirements(prefix: str) -> tuple[Requirement, ...]:
    return (
        _requirement(
            f"{prefix}-FUEL-BOUNDS",
            "Final fuel command shall remain within [0.0, 1.0].",
            RequirementCategory.ACTUATOR_SAFETY,
            ActuatorInvariantRequirementEvaluator(
                ActuatorInvariant.FUEL_BOUNDED
            ),
            RequirementCriticality.CRITICAL,
        ),
    )


def normal_lifecycle_scenario() -> Scenario:
    actions = (
        StartEngineAction(
            action_id="start",
            description="Request engine startup",
            trigger=AtTimeTrigger(0.10),
        ),
        SetThrottleAction(
            action_id="set_moderate_throttle",
            description="Set moderate running demand after idle",
            trigger=WhenConditionTrigger(
                EngineStateEqualsCondition(EngineOperatingState.IDLE),
                timeout_s=12.0,
            ),
            throttle_demand=0.55,
        ),
        SetThrottleAction(
            action_id="return_to_idle",
            description="Return throttle demand to idle",
            trigger=WhenConditionTrigger(
                ElapsedAfterActionCondition("set_moderate_throttle", 5.0),
                timeout_s=20.0,
            ),
            throttle_demand=0.0,
        ),
        RequestShutdownAction(
            action_id="shutdown",
            description="Request shutdown after returning to idle",
            trigger=WhenConditionTrigger(
                AllConditions(
                    (
                        ElapsedAfterActionCondition("return_to_idle", 0.0),
                        EngineStateEqualsCondition(EngineOperatingState.IDLE),
                    )
                ),
                timeout_s=22.0,
            ),
        ),
    )
    requirements = (
        _requirement(
            "REQ-NORMAL-STATE-SEQUENCE",
            "The normal lifecycle shall follow the expected state sequence.",
            RequirementCategory.STATE_SEQUENCE,
            StateSequenceRequirementEvaluator(
                (
                    EngineOperatingState.OFF,
                    EngineOperatingState.CRANKING,
                    EngineOperatingState.IGNITION,
                    EngineOperatingState.IDLE,
                    EngineOperatingState.RUNNING,
                    EngineOperatingState.IDLE,
                    EngineOperatingState.SHUTDOWN,
                    EngineOperatingState.OFF,
                )
            ),
            RequirementCriticality.CRITICAL,
        ),
        _requirement(
            "REQ-NORMAL-IDLE-TIME",
            "IDLE shall be reached within 10 seconds after startup request.",
            RequirementCategory.STATE_TIMING,
            StateReachedWithinRequirementEvaluator(
                EngineOperatingState.IDLE,
                "start",
                maximum_elapsed_s=10.0,
            ),
        ),
        _requirement(
            "REQ-NORMAL-SHUTDOWN-TIME",
            "OFF shall be reached within 8 seconds after shutdown request.",
            RequirementCategory.STATE_TIMING,
            StateReachedWithinRequirementEvaluator(
                EngineOperatingState.OFF,
                "shutdown",
                maximum_elapsed_s=8.0,
            ),
        ),
        _requirement(
            "REQ-NORMAL-NO-FAULT",
            "No automatic FAULT request shall occur during normal operation.",
            RequirementCategory.LOGICAL_INVARIANT,
            EventNotObservedRequirementEvaluator(
                EventType.AUTOMATIC_FAULT_REQUESTED
            ),
            RequirementCriticality.CRITICAL,
        ),
        _requirement(
            "REQ-NORMAL-NO-HARD-OVERSPEED",
            "No hard overspeed event shall occur during normal operation.",
            RequirementCategory.PROTECTION,
            EventNotObservedRequirementEvaluator(
                EventType.HARD_OVERSPEED_ACTIVATED
            ),
            RequirementCriticality.CRITICAL,
        ),
        _requirement(
            "REQ-NORMAL-OFF-FUEL",
            "Fuel shall be zero while the engine is OFF.",
            RequirementCategory.ACTUATOR_SAFETY,
            ActuatorInvariantRequirementEvaluator(
                ActuatorInvariant.FUEL_ZERO_IN_OFF
            ),
            RequirementCriticality.CRITICAL,
        ),
        _requirement(
            "REQ-NORMAL-RUNNING-STARTER",
            "Starter shall be inactive while the engine is RUNNING.",
            RequirementCategory.ACTUATOR_SAFETY,
            ActuatorInvariantRequirementEvaluator(
                ActuatorInvariant.STARTER_INACTIVE_IN_RUNNING
            ),
        ),
        *_common_fuel_requirements("REQ-NORMAL"),
    )
    return Scenario(
        scenario_id="SCN-NORMAL-001",
        name="normal_start_run_shutdown",
        description="Normal startup, moderate operation, return to idle, and shutdown.",
        max_duration_s=25.0,
        time_step_s=0.01,
        recording=RecordingConfiguration(run_name="scenario_normal_lifecycle"),
        actions=actions,
        requirements=requirements,
        tags=("normal", "lifecycle", "regression"),
        expected_terminal_condition=EngineStateEqualsCondition(
            EngineOperatingState.OFF
        ),
    )


def large_throttle_step_scenario() -> Scenario:
    actions = (
        StartEngineAction(
            action_id="start",
            description="Request startup",
            trigger=AtTimeTrigger(0.10),
        ),
        SetThrottleAction(
            action_id="large_throttle_step",
            description="Apply a large throttle increase from idle",
            trigger=WhenConditionTrigger(
                EngineStateEqualsCondition(EngineOperatingState.IDLE),
                timeout_s=12.0,
            ),
            throttle_demand=0.70,
        ),
        AddMarkerAction(
            action_id="settling_window_complete",
            description="End the transient evidence window",
            trigger=WhenConditionTrigger(
                ElapsedAfterActionCondition("large_throttle_step", 10.0),
                timeout_s=24.0,
            ),
            marker_text="large throttle settling window complete",
        ),
    )
    requirements = (
        _requirement(
            "REQ-TRANSIENT-ACCEL-LIMITER",
            "Acceleration limiting shall constrain a large throttle step.",
            RequirementCategory.PROTECTION,
            ProtectionLimiterObservedRequirementEvaluator(
                ProtectionLimiter.ACCELERATION,
                reference_action_id="large_throttle_step",
            ),
        ),
        _requirement(
            "REQ-TRANSIENT-ACCEL-EVENT",
            "Acceleration limiter activation shall be recorded.",
            RequirementCategory.PROTECTION,
            EventObservedRequirementEvaluator(EventType.LIMITER_ACTIVATED),
        ),
        _requirement(
            "REQ-TRANSIENT-ACCEL-LIMIT",
            "Estimated rotor acceleration shall remain below 22,500 rpm/s.",
            RequirementCategory.TRANSIENT,
            AccelerationLimitRequirementEvaluator(
                maximum_acceleration_rpm_per_s=20_000.0,
                tolerance_rpm_per_s=2_500.0,
                reference_action_id="large_throttle_step",
            ),
        ),
        _requirement(
            "REQ-TRANSIENT-OVERSHOOT",
            "Rotor-speed overshoot shall remain below 3 percent.",
            RequirementCategory.TRANSIENT,
            OvershootRequirementEvaluator(
                reference_action_id="large_throttle_step",
                signal=NumericSignal.VALIDATED_ROTOR_SPEED_RPM,
                maximum_overshoot_percent=3.0,
                evaluation_duration_s=8.0,
            ),
        ),
        _requirement(
            "REQ-TRANSIENT-SETTLING",
            "Rotor speed shall settle within 2 percent for 0.5 seconds within 10 seconds.",
            RequirementCategory.STEADY_STATE,
            SettlingTimeRequirementEvaluator(
                reference_action_id="large_throttle_step",
                signal=NumericSignal.VALIDATED_ROTOR_SPEED_RPM,
                tolerance_percent=2.0,
                dwell_time_s=0.5,
                maximum_settling_time_s=10.0,
            ),
        ),
        _requirement(
            "REQ-TRANSIENT-NO-CRITICAL",
            "No critical protection request shall occur.",
            RequirementCategory.PROTECTION,
            EventNotObservedRequirementEvaluator(
                EventType.CRITICAL_PROTECTION_REQUESTED
            ),
            RequirementCriticality.CRITICAL,
        ),
        *_common_fuel_requirements("REQ-TRANSIENT"),
    )
    return Scenario(
        scenario_id="SCN-TRANSIENT-001",
        name="large_throttle_step",
        description="Large acceleration demand held through a settling window.",
        max_duration_s=24.0,
        actions=actions,
        requirements=requirements,
        tags=("transient", "acceleration", "regression"),
        expected_terminal_condition=EngineStateEqualsCondition(
            EngineOperatingState.RUNNING
        ),
        recording=RecordingConfiguration(run_name="scenario_large_throttle_step"),
    )


def rapid_throttle_reduction_scenario() -> Scenario:
    actions = (
        StartEngineAction(
            action_id="start",
            description="Request startup",
            trigger=AtTimeTrigger(0.10),
        ),
        SetThrottleAction(
            action_id="set_high_throttle",
            description="Establish a high running condition",
            trigger=WhenConditionTrigger(
                EngineStateEqualsCondition(EngineOperatingState.IDLE),
                timeout_s=12.0,
            ),
            throttle_demand=0.70,
        ),
        SetThrottleAction(
            action_id="rapid_reduction",
            description="Apply a rapid throttle reduction",
            trigger=WhenConditionTrigger(
                ElapsedAfterActionCondition("set_high_throttle", 6.0),
                timeout_s=22.0,
            ),
            throttle_demand=0.30,
        ),
        RequestShutdownAction(
            action_id="shutdown",
            description="Request shutdown after lower-speed settling",
            trigger=WhenConditionTrigger(
                ElapsedAfterActionCondition("rapid_reduction", 5.0),
                timeout_s=28.0,
            ),
        ),
    )
    requirements = (
        _requirement(
            "REQ-DECEL-LIMITER",
            "Deceleration limiting shall constrain the rapid fuel reduction.",
            RequirementCategory.PROTECTION,
            ProtectionLimiterObservedRequirementEvaluator(
                ProtectionLimiter.DECELERATION,
                require_fuel_reduction=False,
                reference_action_id="rapid_reduction",
            ),
        ),
        _requirement(
            "REQ-DECEL-EVENT",
            "Deceleration limiter activation shall be recorded.",
            RequirementCategory.PROTECTION,
            EventObservedRequirementEvaluator(EventType.LIMITER_ACTIVATED),
        ),
        _requirement(
            "REQ-DECEL-SHUTDOWN",
            "Shutdown shall reach OFF despite deceleration limiting.",
            RequirementCategory.STATE_TIMING,
            StateReachedWithinRequirementEvaluator(
                EngineOperatingState.OFF,
                "shutdown",
                maximum_elapsed_s=8.0,
            ),
            RequirementCriticality.CRITICAL,
        ),
        *_common_fuel_requirements("REQ-DECEL"),
    )
    return Scenario(
        scenario_id="SCN-TRANSIENT-002",
        name="rapid_throttle_reduction",
        description="High running condition followed by rapid reduction and shutdown.",
        max_duration_s=32.0,
        actions=actions,
        requirements=requirements,
        tags=("transient", "deceleration", "shutdown", "regression"),
        expected_terminal_condition=EngineStateEqualsCondition(
            EngineOperatingState.OFF
        ),
        recording=RecordingConfiguration(run_name="scenario_rapid_reduction"),
    )


def _dropout_scenario(channel: SensorChannel) -> Scenario:
    channel_name = "rpm" if channel is SensorChannel.ROTOR_SPEED else "egt"
    scenario_id = "SCN-FAULT-001" if channel is SensorChannel.ROTOR_SPEED else "SCN-FAULT-002"
    actions = (
        StartEngineAction(
            action_id="start",
            description="Request startup",
            trigger=AtTimeTrigger(0.10),
        ),
        SetThrottleAction(
            action_id="set_running_throttle",
            description="Establish stable running operation",
            trigger=WhenConditionTrigger(
                EngineStateEqualsCondition(EngineOperatingState.IDLE),
                timeout_s=12.0,
            ),
            throttle_demand=0.60,
        ),
        InjectSensorFaultAction(
            action_id="inject_dropout",
            description=f"Inject {channel_name.upper()} sensor dropout",
            trigger=WhenConditionTrigger(
                ElapsedAfterActionCondition("set_running_throttle", 4.0),
                timeout_s=22.0,
            ),
            channel=channel,
            fault=DropoutSensorFault(),
        ),
    )
    requirements = (
        _requirement(
            f"REQ-{channel_name.upper()}-FAULT-INJECTION",
            "The sensor fault-injection event shall be recorded.",
            RequirementCategory.SENSOR_FAULT_RESPONSE,
            EventObservedRequirementEvaluator(EventType.SENSOR_FAULT_INJECTED),
        ),
        _requirement(
            f"REQ-{channel_name.upper()}-HEALTH",
            "The faulted sensor channel shall become INVALID.",
            RequirementCategory.SENSOR_FAULT_RESPONSE,
            SensorHealthReachedRequirementEvaluator(
                channel,
                ChannelHealth.INVALID,
                reference_action_id="inject_dropout",
            ),
            RequirementCriticality.CRITICAL,
        ),
        _requirement(
            f"REQ-{channel_name.upper()}-FAULT-RESPONSE",
            "Sensor dropout shall produce FAULT within 0.5 seconds.",
            RequirementCategory.SENSOR_FAULT_RESPONSE,
            FaultResponseTimeRequirementEvaluator(
                "inject_dropout",
                maximum_response_time_s=0.5,
                required_health=ChannelHealth.INVALID,
                health_signal=(
                    "rotor_speed"
                    if channel is SensorChannel.ROTOR_SPEED
                    else "egt"
                ),
            ),
            RequirementCriticality.CRITICAL,
        ),
        _requirement(
            f"REQ-{channel_name.upper()}-FUEL-CUTOFF",
            "Sensor dropout shall produce zero fuel within one simulation step.",
            RequirementCategory.ACTUATOR_SAFETY,
            FuelCutoffResponseRequirementEvaluator(
                reference_action_id="inject_dropout",
                maximum_response_time_s=0.01,
            ),
            RequirementCriticality.CRITICAL,
        ),
        _requirement(
            f"REQ-{channel_name.upper()}-NO-TRUTH-FALLBACK",
            "Unavailable sensor data shall not be replaced by engine truth.",
            RequirementCategory.LOGICAL_INVARIANT,
            NoTruthFallbackRequirementEvaluator(channel, "inject_dropout"),
            RequirementCriticality.CRITICAL,
        ),
        _requirement(
            f"REQ-{channel_name.upper()}-CRITICAL-EVENT",
            "The automatic critical response event shall be recorded.",
            RequirementCategory.SENSOR_FAULT_RESPONSE,
            EventObservedRequirementEvaluator(
                EventType.AUTOMATIC_FAULT_REQUESTED
            ),
            RequirementCriticality.CRITICAL,
        ),
        _requirement(
            f"REQ-{channel_name.upper()}-FAULT-FUEL",
            "Fuel shall remain zero in FAULT.",
            RequirementCategory.ACTUATOR_SAFETY,
            ActuatorInvariantRequirementEvaluator(
                ActuatorInvariant.FUEL_ZERO_IN_FAULT
            ),
            RequirementCriticality.CRITICAL,
        ),
        *_common_fuel_requirements(f"REQ-{channel_name.upper()}"),
    )
    return Scenario(
        scenario_id=scenario_id,
        name=f"{channel_name}_sensor_dropout",
        description=f"Stable operation followed by {channel_name.upper()} sensor dropout.",
        max_duration_s=24.0,
        actions=actions,
        requirements=requirements,
        tags=("fault", "sensor", channel_name, "regression"),
        expected_terminal_condition=EngineStateEqualsCondition(
            EngineOperatingState.FAULT
        ),
        recording=RecordingConfiguration(run_name=f"scenario_{channel_name}_dropout"),
    )


def rpm_sensor_dropout_scenario() -> Scenario:
    return _dropout_scenario(SensorChannel.ROTOR_SPEED)


def egt_sensor_dropout_scenario() -> Scenario:
    return _dropout_scenario(SensorChannel.EXHAUST_TEMPERATURE)


def soft_overspeed_scenario() -> Scenario:
    actions = (
        StartEngineAction(
            action_id="start",
            description="Request startup",
            trigger=AtTimeTrigger(0.10),
        ),
        SetThrottleAction(
            action_id="set_running_throttle",
            description="Establish stable running operation",
            trigger=WhenConditionTrigger(
                EngineStateEqualsCondition(EngineOperatingState.IDLE),
                timeout_s=12.0,
            ),
            throttle_demand=1.00,
        ),
        InjectSensorFaultAction(
            action_id="inject_speed_drift",
            description="Inject gradual validated speed drift",
            trigger=WhenConditionTrigger(
                ElapsedAfterActionCondition("set_running_throttle", 5.0),
                timeout_s=22.0,
            ),
            channel=SensorChannel.ROTOR_SPEED,
            fault=DriftSensorFault(rate_per_second=8_000.0),
        ),
        AddMarkerAction(
            action_id="soft_intervention_detected",
            description="Mark the first soft overspeed intervention",
            trigger=WhenConditionTrigger(
                EventTypeObservedCondition(EventType.SOFT_OVERSPEED_ACTIVATED),
                timeout_s=32.0,
            ),
            marker_text="soft overspeed intervention detected",
        ),
        ClearSensorFaultAction(
            action_id="clear_speed_drift",
            description="Clear drift after soft overspeed intervention",
            trigger=WhenConditionTrigger(
                ElapsedAfterActionCondition("soft_intervention_detected", 0.25),
                timeout_s=32.0,
            ),
            channel=SensorChannel.ROTOR_SPEED,
        ),
        RequestShutdownAction(
            action_id="shutdown_after_intervention",
            description="Request shutdown after soft overspeed intervention",
            trigger=WhenConditionTrigger(
                ElapsedAfterActionCondition("clear_speed_drift", 0.0),
                timeout_s=32.0,
            ),
        ),
        AddMarkerAction(
            action_id="soft_overspeed_complete",
            description="Complete recovery evidence window",
            trigger=WhenConditionTrigger(
                ElapsedAfterActionCondition("clear_speed_drift", 1.0),
                timeout_s=35.0,
            ),
            marker_text="soft overspeed recovery complete",
        ),
    )
    requirements = (
        _requirement(
            "REQ-SOFT-OVERSPEED-EVENT",
            "Soft overspeed intervention shall occur.",
            RequirementCategory.PROTECTION,
            EventObservedRequirementEvaluator(
                EventType.SOFT_OVERSPEED_ACTIVATED
            ),
        ),
        _requirement(
            "REQ-SOFT-OVERSPEED-FUEL",
            "Overspeed protection shall constrain fuel.",
            RequirementCategory.PROTECTION,
            ProtectionLimiterObservedRequirementEvaluator(
                ProtectionLimiter.OVERSPEED,
                reference_action_id="inject_speed_drift",
            ),
            RequirementCriticality.CRITICAL,
        ),
        _requirement(
            "REQ-SOFT-NO-HARD-CUTOFF",
            "Soft overspeed shall not produce a hard-cutoff event.",
            RequirementCategory.PROTECTION,
            EventNotObservedRequirementEvaluator(
                EventType.HARD_OVERSPEED_ACTIVATED
            ),
            RequirementCriticality.CRITICAL,
        ),
        _requirement(
            "REQ-SOFT-NO-FAULT",
            "Soft overspeed shall not immediately transition to FAULT.",
            RequirementCategory.PROTECTION,
            EventNotObservedRequirementEvaluator(
                EventType.AUTOMATIC_FAULT_REQUESTED
            ),
            RequirementCriticality.CRITICAL,
        ),
        *_common_fuel_requirements("REQ-SOFT"),
    )
    return Scenario(
        scenario_id="SCN-PROT-001",
        name="soft_overspeed",
        description="Validated gradual speed drift into soft overspeed intervention.",
        max_duration_s=36.0,
        actions=actions,
        requirements=requirements,
        tags=("protection", "overspeed", "soft", "regression"),
        expected_terminal_condition=EngineStateEqualsCondition(
            EngineOperatingState.OFF
        ),
        recording=RecordingConfiguration(run_name="scenario_soft_overspeed"),
    )


def hard_overspeed_scenario() -> Scenario:
    actions = (
        StartEngineAction(
            action_id="start",
            description="Request startup",
            trigger=AtTimeTrigger(0.10),
        ),
        SetThrottleAction(
            action_id="set_running_throttle",
            description="Establish stable running operation",
            trigger=WhenConditionTrigger(
                EngineStateEqualsCondition(EngineOperatingState.IDLE),
                timeout_s=12.0,
            ),
            throttle_demand=0.60,
        ),
        InjectSensorFaultAction(
            action_id="inject_speed_drift",
            description="Inject gradual validated speed drift through hard overspeed",
            trigger=WhenConditionTrigger(
                ElapsedAfterActionCondition("set_running_throttle", 5.0),
                timeout_s=22.0,
            ),
            channel=SensorChannel.ROTOR_SPEED,
            fault=DriftSensorFault(rate_per_second=8_000.0),
        ),
    )
    requirements = (
        _requirement(
            "REQ-HARD-OVERSPEED-EVENT",
            "Hard overspeed activation shall be recorded.",
            RequirementCategory.PROTECTION,
            EventObservedRequirementEvaluator(
                EventType.HARD_OVERSPEED_ACTIVATED
            ),
            RequirementCriticality.CRITICAL,
        ),
        _requirement(
            "REQ-HARD-CRITICAL-REQUEST",
            "Hard overspeed shall request critical protection.",
            RequirementCategory.PROTECTION,
            EventObservedRequirementEvaluator(
                EventType.CRITICAL_PROTECTION_REQUESTED
            ),
            RequirementCriticality.CRITICAL,
        ),
        _requirement(
            "REQ-HARD-FUEL-CUTOFF",
            "Hard overspeed shall produce zero fuel within one simulation step.",
            RequirementCategory.ACTUATOR_SAFETY,
            FuelCutoffResponseRequirementEvaluator(
                reference_event_type=EventType.HARD_OVERSPEED_ACTIVATED,
                maximum_response_time_s=0.01,
            ),
            RequirementCriticality.CRITICAL,
        ),
        _requirement(
            "REQ-HARD-FAULT",
            "Hard overspeed shall transition to FAULT after the injected drift.",
            RequirementCategory.PROTECTION,
            FaultResponseTimeRequirementEvaluator(
                "inject_speed_drift",
                maximum_response_time_s=20.0,
            ),
            RequirementCriticality.CRITICAL,
        ),
        _requirement(
            "REQ-HARD-FAULT-FUEL",
            "Fuel shall remain zero in FAULT.",
            RequirementCategory.ACTUATOR_SAFETY,
            ActuatorInvariantRequirementEvaluator(
                ActuatorInvariant.FUEL_ZERO_IN_FAULT
            ),
            RequirementCriticality.CRITICAL,
        ),
        *_common_fuel_requirements("REQ-HARD"),
    )
    return Scenario(
        scenario_id="SCN-PROT-002",
        name="hard_overspeed",
        description="Validated gradual speed drift through the hard overspeed threshold.",
        max_duration_s=38.0,
        actions=actions,
        requirements=requirements,
        tags=("protection", "overspeed", "hard", "regression"),
        expected_terminal_condition=EngineStateEqualsCondition(
            EngineOperatingState.FAULT
        ),
        recording=RecordingConfiguration(run_name="scenario_hard_overspeed"),
    )


REGRESSION_SCENARIOS = (
    normal_lifecycle_scenario(),
    large_throttle_step_scenario(),
    rapid_throttle_reduction_scenario(),
    rpm_sensor_dropout_scenario(),
    egt_sensor_dropout_scenario(),
    soft_overspeed_scenario(),
    hard_overspeed_scenario(),
)


def list_scenarios() -> tuple[Scenario, ...]:
    """Return the explicit registry in deterministic execution order."""

    return REGRESSION_SCENARIOS


def get_scenario(identifier: str) -> Scenario:
    """Look up one scenario by stable ID or human-readable name."""

    normalized = identifier.strip().lower()
    for scenario in REGRESSION_SCENARIOS:
        if normalized in {scenario.scenario_id.lower(), scenario.name.lower()}:
            return scenario
    raise KeyError(f"unknown scenario: {identifier}")
