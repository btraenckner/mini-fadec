"""Composition of engine operation, control, protection, and dynamics."""

from dataclasses import dataclass

from simulation.application.event_log import InMemoryEventLog
from simulation.application.sensor_fault_response import (
    SensorFaultResponse,
    SensorFaultResponsePolicy,
    SensorFaultResponseReason,
)
from simulation.controllers.speed_controller import PIEngineSpeedController
from simulation.core.interfaces import SensorModelInterface
from simulation.core.types import (
    ActuatorCommand,
    AmbientConditions,
    ControlRequest,
    SensorData,
    ValidatedSensorData,
)
from simulation.models.engine_model import FirstOrderEngineModel
from simulation.operation.engine_state import EngineOperatingState
from simulation.operation.state_machine import (
    EngineOperatingCommand,
    EngineOperationRequest,
    EngineStateMachine,
)
from simulation.protection.exhaust_temperature_limiter import (
    ExhaustTemperatureLimiter,
)
from simulation.protection.overspeed_limiter import (
    OverspeedLimiter,
    OverspeedLimiterParameters,
)
from simulation.protection.protection_manager import ProtectionManager
from simulation.protection.types import (
    ProtectionContext,
    ProtectionDiagnosticReason,
    ProtectionLimiter,
    ProtectionResult,
)
from simulation.sensors.sensor_model import (
    ConfigurableSensorModel,
    SensorModelConfiguration,
)
from simulation.sensors.fault_injection import (
    SensorChannel,
    SensorFaultDefinition,
    SensorFaultInjector,
)
from simulation.validation.sensor_validation import (
    ChannelDiagnosticReason,
    ChannelHealth,
    SensorSignalValidator,
    SensorValidationContext,
    SensorValidationResult,
)


@dataclass(frozen=True)
class EngineSimulationSnapshot:
    """Observable state of one coordinated simulation step."""

    simulation_time_s: float
    previous_operating_state: EngineOperatingState
    operating_state: EngineOperatingState
    throttle_command: float
    speed_setpoint_rpm: float
    rotor_speed_rpm: float
    measured_rotor_speed_rpm: float | None
    validated_rotor_speed_rpm: float | None
    rotor_speed_measurement_error_rpm: float | None
    rotor_speed_health: ChannelHealth
    rotor_speed_diagnostic_reason: ChannelDiagnosticReason
    rotor_speed_value_is_held: bool
    rotor_speed_fault: str
    exhaust_temperature_c: float
    measured_exhaust_temperature_c: float | None
    validated_exhaust_temperature_c: float | None
    exhaust_temperature_measurement_error_c: float | None
    exhaust_temperature_health: ChannelHealth
    exhaust_temperature_diagnostic_reason: ChannelDiagnosticReason
    exhaust_temperature_value_is_held: bool
    exhaust_temperature_fault: str
    aggregate_sensor_health: ChannelHealth
    rotor_speed_sensor_sample_period_s: float
    exhaust_temperature_sensor_sample_period_s: float
    requested_fuel_command: float
    allowed_fuel_command: float
    egt_fuel_limit: float
    acceleration_fuel_limit: float
    overspeed_fuel_limit: float
    deceleration_minimum_fuel_command: float
    state_maximum_fuel_command: float
    active_protection_limiter: ProtectionLimiter
    constraining_protection_limiters: tuple[ProtectionLimiter, ...]
    protection_diagnostic_reasons: tuple[ProtectionDiagnosticReason, ...]
    rotor_acceleration_rpm_per_s: float | None
    rotor_deceleration_rpm_per_s: float | None
    speed_ratio: float | None
    soft_overspeed_active: bool
    hard_overspeed_active: bool
    protection_hard_cutoff_active: bool
    critical_protection_fault_request: bool
    protection_arbitration_conflict: bool
    estimated_thrust_n: float
    estimated_fuel_flow_ml_min: float
    starter_commanded: bool
    ignition_commanded: bool
    speed_control_enabled: bool
    fuel_enabled: bool
    shutdown_fuel_cutoff_active: bool
    egt_limiter_active: bool
    automatic_sensor_fault_request_active: bool
    sensor_fault_response_reason: SensorFaultResponseReason
    fuel_cutoff_due_to_sensor_invalidity: bool


class EngineSimulationCoordinator:
    """Compose the operating state machine with control and engine dynamics."""

    def __init__(
        self,
        engine_model: FirstOrderEngineModel | None = None,
        state_machine: EngineStateMachine | None = None,
        speed_controller: PIEngineSpeedController | None = None,
        egt_limiter: ExhaustTemperatureLimiter | None = None,
        protection_manager: ProtectionManager | None = None,
        sensor_model: SensorModelInterface | None = None,
        sensor_fault_injector: SensorFaultInjector | None = None,
        sensor_validator: SensorSignalValidator | None = None,
        sensor_fault_response_policy: SensorFaultResponsePolicy | None = None,
        event_log: InMemoryEventLog | None = None,
        ambient_conditions: AmbientConditions | None = None,
    ) -> None:
        self.engine_model = engine_model or FirstOrderEngineModel()
        self.state_machine = state_machine or EngineStateMachine()
        self.speed_controller = speed_controller or PIEngineSpeedController()
        if protection_manager is not None and egt_limiter is not None:
            raise ValueError(
                "provide either protection_manager or egt_limiter, not both"
            )
        self.protection_manager = protection_manager or ProtectionManager(
            egt_limiter=egt_limiter or ExhaustTemperatureLimiter(),
            overspeed_limiter=OverspeedLimiter(
                parameters=OverspeedLimiterParameters(
                    maximum_normal_speed_rpm=(
                        self.speed_controller.scheduler.maximum_speed_rpm
                    )
                )
            ),
        )
        # Compatibility alias for callers that inspect EGT thresholds.
        self.egt_limiter = self.protection_manager.egt_limiter
        # Set random_seed=None for non-reproducible demonstration noise.
        self.sensor_model = sensor_model or ConfigurableSensorModel(
            configuration=SensorModelConfiguration(random_seed=0)
        )
        self.sensor_fault_injector = (
            sensor_fault_injector or SensorFaultInjector(random_seed=0)
        )
        self.sensor_validator = sensor_validator or SensorSignalValidator()
        self.sensor_fault_response_policy = (
            sensor_fault_response_policy or SensorFaultResponsePolicy()
        )
        self.event_log = event_log or InMemoryEventLog()
        self.ambient_conditions = ambient_conditions or AmbientConditions()

        self._simulation_time_s = 0.0
        self._speed_control_was_enabled = False
        self._automatic_fault_was_active = False
        self._last_nominal_sensor_data: SensorData | None = None
        self._snapshot = self._initial_snapshot()
        self._reported_active_protection_limiter = (
            self._snapshot.active_protection_limiter
        )
        self._pending_active_protection_limiter = (
            self._snapshot.active_protection_limiter
        )
        self._pending_active_limiter_since_s = 0.0
        self._reported_limiter_activity = {
            ProtectionLimiter.ACCELERATION: False,
            ProtectionLimiter.DECELERATION: False,
        }
        self._pending_limiter_activity = dict(
            self._reported_limiter_activity
        )
        self._pending_limiter_activity_since_s = {
            limiter: 0.0 for limiter in self._reported_limiter_activity
        }
        self._arbitration_conflict_was_reported = False
        self._arbitration_conflict_clear_since_s: float | None = None

    @property
    def snapshot(self) -> EngineSimulationSnapshot:
        """Return the latest coordinated simulation snapshot."""

        return self._snapshot

    def inject_sensor_fault(
        self,
        channel: SensorChannel,
        fault: SensorFaultDefinition,
    ) -> None:
        """Activate or replace a simulation-only fault on one sensor channel."""

        current_measurement = None
        if self._last_nominal_sensor_data is not None:
            current_measurement = (
                self._last_nominal_sensor_data.rotor_speed_rpm
                if channel is SensorChannel.ROTOR_SPEED
                else self._last_nominal_sensor_data.exhaust_temperature_c
            )
        self.sensor_fault_injector.activate(
            channel=channel,
            fault=fault,
            current_measurement=current_measurement,
        )
        self.event_log.record(
            self._simulation_time_s,
            f"Injected {channel.value} sensor fault: "
            f"{self.sensor_fault_injector.describe(channel)}",
        )

    def clear_sensor_fault(self, channel: SensorChannel) -> None:
        """Clear one injected fault without resetting validator recovery."""

        if not self.sensor_fault_injector.is_active(channel):
            return
        self.sensor_fault_injector.clear(channel)
        self.event_log.record(
            self._simulation_time_s,
            f"Cleared {channel.value} sensor fault",
        )

    def clear_sensor_faults(self) -> None:
        """Clear all injected faults without bypassing validation recovery."""

        for channel in SensorChannel:
            self.clear_sensor_fault(channel)

    def _validation_context(
        self,
        request: EngineOperationRequest,
    ) -> SensorValidationContext:
        """Create narrowly scoped context from the previous coordinated step."""

        return SensorValidationContext(
            operating_state=self.state_machine.state,
            starter_commanded=self._snapshot.starter_commanded,
            ignition_commanded=self._snapshot.ignition_commanded,
            fuel_enabled=self._snapshot.fuel_enabled,
            fuel_command=self._snapshot.allowed_fuel_command,
            throttle_command=request.throttle_command,
        )

    @staticmethod
    def _effective_operation_request(
        request: EngineOperationRequest,
        validation_result: SensorValidationResult,
        sensor_fault_response: SensorFaultResponse,
    ) -> EngineOperationRequest:
        """Combine manual requests with automatic sensor fault response."""

        sensors_recovered = (
            validation_result.rotor_speed.health is ChannelHealth.VALID
            and validation_result.exhaust_temperature.health
            is ChannelHealth.VALID
        )
        return EngineOperationRequest(
            throttle_command=request.throttle_command,
            startup_requested=request.startup_requested,
            shutdown_requested=request.shutdown_requested,
            fault_requested=(
                request.fault_requested
                or sensor_fault_response.automatic_fault_requested
            ),
            reset_requested=request.reset_requested and sensors_recovered,
        )

    def step(
        self,
        request: EngineOperationRequest,
        time_step_s: float,
    ) -> EngineSimulationSnapshot:
        """Advance all composed simulation components by one time step."""

        nominal_sensor_data = self.sensor_model.measure(
            engine_state=self.engine_model.state,
            time_step_s=time_step_s,
        )
        self._last_nominal_sensor_data = nominal_sensor_data
        raw_sensor_data = self.sensor_fault_injector.apply(
            sensor_data=nominal_sensor_data,
            time_step_s=time_step_s,
        )
        validation_result = self.sensor_validator.update(
            raw_sensor_data=raw_sensor_data,
            context=self._validation_context(request),
            time_step_s=time_step_s,
        )
        previous_operating_state = self.state_machine.state
        sensor_fault_response = self.sensor_fault_response_policy.evaluate(
            operating_state=previous_operating_state,
            validation_result=validation_result,
        )
        effective_request = self._effective_operation_request(
            request,
            validation_result,
            sensor_fault_response,
        )
        operating_command = self.state_machine.update(
            request=effective_request,
            sensor_data=validation_result.sensor_data,
            time_step_s=time_step_s,
        )

        if self._speed_control_was_enabled and not (
            operating_command.speed_control_enabled
        ):
            self.speed_controller.reset()

        requested_command = self._requested_actuator_command(
            operating_command=operating_command,
            sensor_data=validation_result.sensor_data,
            time_step_s=time_step_s,
        )
        allowed_command, protection_result = self._protected_actuator_command(
            requested_command=requested_command,
            operating_command=operating_command,
            sensor_data=validation_result.sensor_data,
            sensor_critical_condition=(
                sensor_fault_response.fuel_cutoff_required
            ),
            time_step_s=time_step_s,
        )
        if (
            protection_result.critical_protection_fault_request
            and operating_command.state is not EngineOperatingState.FAULT
        ):
            operating_command = self.state_machine.update(
                request=EngineOperationRequest(
                    throttle_command=request.throttle_command,
                    fault_requested=True,
                ),
                sensor_data=validation_result.sensor_data,
                time_step_s=time_step_s,
            )
            self.speed_controller.reset()
            allowed_command = ActuatorCommand(
                fuel_command=protection_result.final_fuel_command,
                starter_commanded=operating_command.starter_commanded,
                ignition_commanded=operating_command.ignition_commanded,
                fuel_enabled=operating_command.fuel_enabled,
            )

        engine_outputs = self.engine_model.step(
            actuator_command=allowed_command,
            ambient_conditions=self.ambient_conditions,
            time_step_s=time_step_s,
        )
        self._simulation_time_s += time_step_s
        self._speed_control_was_enabled = operating_command.speed_control_enabled
        self._record_sensor_events(
            validation_result=validation_result,
            sensor_fault_response=sensor_fault_response,
            protection_result=protection_result,
        )

        egt_limiter_active = (
            ProtectionDiagnosticReason.EGT_LIMITING
            in protection_result.diagnostic_reasons
        )
        self._snapshot = EngineSimulationSnapshot(
            simulation_time_s=self._simulation_time_s,
            previous_operating_state=previous_operating_state,
            operating_state=operating_command.state,
            throttle_command=operating_command.effective_throttle_command,
            speed_setpoint_rpm=self._speed_setpoint_rpm(operating_command),
            rotor_speed_rpm=self.engine_model.state.rotor_speed_rpm,
            measured_rotor_speed_rpm=raw_sensor_data.rotor_speed_rpm,
            validated_rotor_speed_rpm=(
                validation_result.sensor_data.rotor_speed_rpm
            ),
            rotor_speed_measurement_error_rpm=self._measurement_error(
                raw_sensor_data.rotor_speed_rpm,
                self.engine_model.state.rotor_speed_rpm,
            ),
            rotor_speed_health=validation_result.rotor_speed.health,
            rotor_speed_diagnostic_reason=(
                validation_result.rotor_speed.diagnostic_reason
            ),
            rotor_speed_value_is_held=(
                validation_result.rotor_speed.value_is_held
            ),
            rotor_speed_fault=self.sensor_fault_injector.describe(
                SensorChannel.ROTOR_SPEED
            ),
            exhaust_temperature_c=(
                self.engine_model.state.exhaust_temperature_c
            ),
            measured_exhaust_temperature_c=(
                raw_sensor_data.exhaust_temperature_c
            ),
            validated_exhaust_temperature_c=(
                validation_result.sensor_data.exhaust_temperature_c
            ),
            exhaust_temperature_measurement_error_c=self._measurement_error(
                raw_sensor_data.exhaust_temperature_c,
                self.engine_model.state.exhaust_temperature_c,
            ),
            exhaust_temperature_health=(
                validation_result.exhaust_temperature.health
            ),
            exhaust_temperature_diagnostic_reason=(
                validation_result.exhaust_temperature.diagnostic_reason
            ),
            exhaust_temperature_value_is_held=(
                validation_result.exhaust_temperature.value_is_held
            ),
            exhaust_temperature_fault=self.sensor_fault_injector.describe(
                SensorChannel.EXHAUST_TEMPERATURE
            ),
            aggregate_sensor_health=validation_result.aggregate_health,
            rotor_speed_sensor_sample_period_s=(
                self.sensor_model.rotor_speed_sample_period_s
            ),
            exhaust_temperature_sensor_sample_period_s=(
                self.sensor_model.exhaust_temperature_sample_period_s
            ),
            requested_fuel_command=requested_command.fuel_command,
            allowed_fuel_command=allowed_command.fuel_command,
            egt_fuel_limit=protection_result.egt_fuel_limit,
            acceleration_fuel_limit=(
                protection_result.acceleration_fuel_limit
            ),
            overspeed_fuel_limit=protection_result.overspeed_fuel_limit,
            deceleration_minimum_fuel_command=(
                protection_result.deceleration_minimum_fuel_command
            ),
            state_maximum_fuel_command=(
                protection_result.state_maximum_fuel_command
            ),
            active_protection_limiter=protection_result.active_limiter,
            constraining_protection_limiters=(
                protection_result.constraining_limiters
            ),
            protection_diagnostic_reasons=(
                protection_result.diagnostic_reasons
            ),
            rotor_acceleration_rpm_per_s=(
                protection_result.rotor_acceleration_rpm_per_s
            ),
            rotor_deceleration_rpm_per_s=(
                protection_result.rotor_deceleration_rpm_per_s
            ),
            speed_ratio=protection_result.speed_ratio,
            soft_overspeed_active=(
                protection_result.soft_overspeed_active
            ),
            hard_overspeed_active=(
                protection_result.hard_overspeed_active
            ),
            protection_hard_cutoff_active=(
                protection_result.hard_cutoff_active
            ),
            critical_protection_fault_request=(
                protection_result.critical_protection_fault_request
            ),
            protection_arbitration_conflict=(
                protection_result.arbitration_conflict
            ),
            estimated_thrust_n=engine_outputs.estimated_thrust_n,
            estimated_fuel_flow_ml_min=(
                engine_outputs.estimated_fuel_flow_ml_min
            ),
            starter_commanded=allowed_command.starter_commanded,
            ignition_commanded=allowed_command.ignition_commanded,
            speed_control_enabled=operating_command.speed_control_enabled,
            fuel_enabled=allowed_command.fuel_enabled,
            shutdown_fuel_cutoff_active=(
                operating_command.shutdown_fuel_cutoff_active
            ),
            egt_limiter_active=egt_limiter_active,
            automatic_sensor_fault_request_active=(
                sensor_fault_response.automatic_fault_requested
            ),
            sensor_fault_response_reason=sensor_fault_response.reason,
            fuel_cutoff_due_to_sensor_invalidity=(
                sensor_fault_response.fuel_cutoff_required
            ),
        )
        return self._snapshot

    def _requested_actuator_command(
        self,
        operating_command: EngineOperatingCommand,
        sensor_data: ValidatedSensorData,
        time_step_s: float,
    ) -> ActuatorCommand:
        """Calculate the requested command for the current operating mode."""

        if operating_command.speed_control_enabled:
            complete_sensor_data = self._required_sensor_data(sensor_data)
            controller_command = self.speed_controller.update(
                control_request=ControlRequest(
                    throttle_command=(
                        operating_command.effective_throttle_command
                    )
                ),
                sensor_data=complete_sensor_data,
                time_step_s=time_step_s,
            )
            fuel_command = controller_command.fuel_command
        else:
            fuel_command = operating_command.open_loop_fuel_command

        return ActuatorCommand(
            fuel_command=fuel_command,
            starter_commanded=operating_command.starter_commanded,
            ignition_commanded=operating_command.ignition_commanded,
            fuel_enabled=operating_command.fuel_enabled,
        )

    def _protected_actuator_command(
        self,
        requested_command: ActuatorCommand,
        operating_command: EngineOperatingCommand,
        sensor_data: ValidatedSensorData,
        sensor_critical_condition: bool,
        time_step_s: float,
    ) -> tuple[ActuatorCommand, ProtectionResult]:
        """Apply the centralized protection manager to requested fuel."""

        protection_result = self.protection_manager.apply(
            requested_fuel_command=requested_command.fuel_command,
            sensor_data=sensor_data,
            context=ProtectionContext(
                operating_state=operating_command.state,
                fuel_enabled=operating_command.fuel_enabled,
                sensor_critical_condition=sensor_critical_condition,
            ),
            time_step_s=time_step_s,
        )
        return (
            ActuatorCommand(
                fuel_command=protection_result.final_fuel_command,
                starter_commanded=requested_command.starter_commanded,
                ignition_commanded=requested_command.ignition_commanded,
                fuel_enabled=requested_command.fuel_enabled,
            ),
            protection_result,
        )

    @staticmethod
    def _required_sensor_data(
        sensor_data: ValidatedSensorData,
    ) -> SensorData:
        """Return complete validated data or reject unsafe controller use."""

        if (
            sensor_data.rotor_speed_rpm is None
            or sensor_data.exhaust_temperature_c is None
        ):
            raise RuntimeError(
                "complete validated sensor data is required for closed-loop control"
            )
        return SensorData(
            rotor_speed_rpm=sensor_data.rotor_speed_rpm,
            exhaust_temperature_c=sensor_data.exhaust_temperature_c,
        )

    def _record_sensor_events(
        self,
        validation_result: SensorValidationResult,
        sensor_fault_response: SensorFaultResponse,
        protection_result: ProtectionResult,
    ) -> None:
        """Record sensor and protection transitions without repeated events."""

        channel_results = (
            (
                "Rotor-speed",
                self._snapshot.rotor_speed_health,
                validation_result.rotor_speed.health,
            ),
            (
                "EGT",
                self._snapshot.exhaust_temperature_health,
                validation_result.exhaust_temperature.health,
            ),
        )
        for channel_name, previous_health, current_health in channel_results:
            if previous_health is not current_health:
                self.event_log.record(
                    self._simulation_time_s,
                    f"{channel_name} channel {previous_health.value} -> "
                    f"{current_health.value}",
                )

        automatic_fault_active = (
            sensor_fault_response.automatic_fault_requested
        )
        if automatic_fault_active and not self._automatic_fault_was_active:
            self.event_log.record(
                self._simulation_time_s,
                "Automatic FAULT request: "
                f"{sensor_fault_response.reason.value}",
            )
            self.event_log.record(
                self._simulation_time_s,
                "Fuel cut off due to sensor invalidity",
            )
        self._automatic_fault_was_active = automatic_fault_active
        self._record_protection_events(protection_result)

    def _record_protection_events(
        self,
        protection_result: ProtectionResult,
    ) -> None:
        """Record protection activation, release, conflict, and critical edges."""

        self._record_debounced_active_limiter(protection_result.active_limiter)
        limiter_activity = {
            ProtectionLimiter.ACCELERATION: (
                ProtectionDiagnosticReason.ACCELERATION_LIMITING
                in protection_result.diagnostic_reasons
            ),
            ProtectionLimiter.DECELERATION: (
                ProtectionDiagnosticReason.DECELERATION_LIMITING
                in protection_result.diagnostic_reasons
            ),
        }
        for limiter, active in limiter_activity.items():
            self._record_debounced_limiter_activity(limiter, active)

        if (
            protection_result.soft_overspeed_active
            and not self._snapshot.soft_overspeed_active
        ):
            self.event_log.record(
                self._simulation_time_s,
                "Soft overspeed intervention activated",
            )
        if (
            protection_result.hard_overspeed_active
            and not self._snapshot.hard_overspeed_active
        ):
            self.event_log.record(
                self._simulation_time_s,
                "Hard overspeed fuel cutoff",
            )
        self._record_arbitration_conflict(protection_result)
        if (
            protection_result.critical_protection_fault_request
            and not self._snapshot.critical_protection_fault_request
        ):
            self.event_log.record(
                self._simulation_time_s,
                "Critical protection FAULT request",
            )

    def _record_debounced_active_limiter(
        self,
        current_limiter: ProtectionLimiter,
    ) -> None:
        """Report primary-authority changes only after a stable short dwell."""

        if current_limiter is not self._pending_active_protection_limiter:
            self._pending_active_protection_limiter = current_limiter
            self._pending_active_limiter_since_s = self._simulation_time_s
            return
        if (
            current_limiter is self._reported_active_protection_limiter
            or self._simulation_time_s
            - self._pending_active_limiter_since_s
            < 0.05
        ):
            return

        previous_limiter = self._reported_active_protection_limiter
        self.event_log.record(
            self._simulation_time_s,
            f"Active fuel limiter {previous_limiter.value} -> "
            f"{current_limiter.value}",
        )
        self._reported_active_protection_limiter = current_limiter

    def _record_debounced_limiter_activity(
        self,
        limiter: ProtectionLimiter,
        active: bool,
    ) -> None:
        """Report sustained acceleration and deceleration limiter edges."""

        if active is not self._pending_limiter_activity[limiter]:
            self._pending_limiter_activity[limiter] = active
            self._pending_limiter_activity_since_s[limiter] = (
                self._simulation_time_s
            )
            return
        if (
            active is self._reported_limiter_activity[limiter]
            or self._simulation_time_s
            - self._pending_limiter_activity_since_s[limiter]
            < 0.05
        ):
            return

        label = (
            "Acceleration limiter"
            if limiter is ProtectionLimiter.ACCELERATION
            else "Deceleration limiter"
        )
        self.event_log.record(
            self._simulation_time_s,
            f"{label} {'activated' if active else 'released'}",
        )
        self._reported_limiter_activity[limiter] = active

    def _record_arbitration_conflict(
        self,
        protection_result: ProtectionResult,
    ) -> None:
        """Report a conflict once until normal arbitration is stable again."""

        if protection_result.arbitration_conflict:
            self._arbitration_conflict_clear_since_s = None
            if not self._arbitration_conflict_was_reported:
                self.event_log.record(
                    self._simulation_time_s,
                    "Fuel arbitration conflict; safety upper limit selected",
                )
                self._arbitration_conflict_was_reported = True
            return

        if not self._arbitration_conflict_was_reported:
            return
        if self._arbitration_conflict_clear_since_s is None:
            self._arbitration_conflict_clear_since_s = self._simulation_time_s
        elif (
            self._simulation_time_s
            - self._arbitration_conflict_clear_since_s
            >= 1.0
        ):
            self._arbitration_conflict_was_reported = False
            self._arbitration_conflict_clear_since_s = None

    @staticmethod
    def _measurement_error(
        measured_value: float | None,
        true_value: float,
    ) -> float | None:
        """Return a simulation-only truth comparison when measurement exists."""

        if measured_value is None:
            return None
        return measured_value - true_value

    def _speed_setpoint_rpm(
        self,
        operating_command: EngineOperatingCommand,
    ) -> float:
        """Return the scheduled setpoint when speed control is enabled."""

        if not operating_command.speed_control_enabled:
            return 0.0

        return self.speed_controller.scheduler.get_speed_setpoint_rpm(
            operating_command.effective_throttle_command
        )

    def _initial_snapshot(self) -> EngineSimulationSnapshot:
        """Create the safe initial OFF-state snapshot."""

        protection_result = self.protection_manager.last_result
        return EngineSimulationSnapshot(
            simulation_time_s=0.0,
            previous_operating_state=EngineOperatingState.OFF,
            operating_state=EngineOperatingState.OFF,
            throttle_command=0.0,
            speed_setpoint_rpm=0.0,
            rotor_speed_rpm=self.engine_model.state.rotor_speed_rpm,
            measured_rotor_speed_rpm=self.engine_model.state.rotor_speed_rpm,
            validated_rotor_speed_rpm=self.engine_model.state.rotor_speed_rpm,
            rotor_speed_measurement_error_rpm=0.0,
            rotor_speed_health=ChannelHealth.VALID,
            rotor_speed_diagnostic_reason=ChannelDiagnosticReason.NONE,
            rotor_speed_value_is_held=False,
            rotor_speed_fault="none",
            exhaust_temperature_c=self.engine_model.state.exhaust_temperature_c,
            measured_exhaust_temperature_c=(
                self.engine_model.state.exhaust_temperature_c
            ),
            validated_exhaust_temperature_c=(
                self.engine_model.state.exhaust_temperature_c
            ),
            exhaust_temperature_measurement_error_c=0.0,
            exhaust_temperature_health=ChannelHealth.VALID,
            exhaust_temperature_diagnostic_reason=(
                ChannelDiagnosticReason.NONE
            ),
            exhaust_temperature_value_is_held=False,
            exhaust_temperature_fault="none",
            aggregate_sensor_health=ChannelHealth.VALID,
            rotor_speed_sensor_sample_period_s=(
                self.sensor_model.rotor_speed_sample_period_s
            ),
            exhaust_temperature_sensor_sample_period_s=(
                self.sensor_model.exhaust_temperature_sample_period_s
            ),
            requested_fuel_command=0.0,
            allowed_fuel_command=0.0,
            egt_fuel_limit=protection_result.egt_fuel_limit,
            acceleration_fuel_limit=(
                protection_result.acceleration_fuel_limit
            ),
            overspeed_fuel_limit=protection_result.overspeed_fuel_limit,
            deceleration_minimum_fuel_command=(
                protection_result.deceleration_minimum_fuel_command
            ),
            state_maximum_fuel_command=(
                protection_result.state_maximum_fuel_command
            ),
            active_protection_limiter=protection_result.active_limiter,
            constraining_protection_limiters=(
                protection_result.constraining_limiters
            ),
            protection_diagnostic_reasons=(
                protection_result.diagnostic_reasons
            ),
            rotor_acceleration_rpm_per_s=(
                protection_result.rotor_acceleration_rpm_per_s
            ),
            rotor_deceleration_rpm_per_s=(
                protection_result.rotor_deceleration_rpm_per_s
            ),
            speed_ratio=protection_result.speed_ratio,
            soft_overspeed_active=(
                protection_result.soft_overspeed_active
            ),
            hard_overspeed_active=(
                protection_result.hard_overspeed_active
            ),
            protection_hard_cutoff_active=(
                protection_result.hard_cutoff_active
            ),
            critical_protection_fault_request=(
                protection_result.critical_protection_fault_request
            ),
            protection_arbitration_conflict=(
                protection_result.arbitration_conflict
            ),
            estimated_thrust_n=0.0,
            estimated_fuel_flow_ml_min=0.0,
            starter_commanded=False,
            ignition_commanded=False,
            speed_control_enabled=False,
            fuel_enabled=False,
            shutdown_fuel_cutoff_active=False,
            egt_limiter_active=False,
            automatic_sensor_fault_request_active=False,
            sensor_fault_response_reason=SensorFaultResponseReason.NONE,
            fuel_cutoff_due_to_sensor_invalidity=False,
        )
