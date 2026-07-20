"""Composition of engine operation, control, protection, and dynamics."""

from collections.abc import Iterable

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
    sensor_fault_parameters,
    sensor_fault_type,
)
from simulation.telemetry.snapshot import (
    TELEMETRY_SCHEMA_VERSION,
    SimulationSnapshot,
)
from simulation.telemetry.interfaces import SnapshotSink
from simulation.telemetry.events import (
    EventCategory,
    EventSeverity,
    EventType,
    SimulationEventMonitor,
)
from simulation.validation.sensor_validation import (
    ChannelDiagnosticReason,
    ChannelHealth,
    SensorSignalValidator,
    SensorValidationContext,
    SensorValidationResult,
)


EngineSimulationSnapshot = SimulationSnapshot
"""Compatibility alias for the canonical telemetry-owned snapshot type."""


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
        snapshot_sinks: Iterable[SnapshotSink] = (),
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
        self._snapshot_sinks = list(snapshot_sinks)
        self.ambient_conditions = ambient_conditions or AmbientConditions()

        self._simulation_time_s = 0.0
        self._step_index = 0
        self._snapshot_sequence_number = 0
        self._state_duration_s = 0.0
        self._previous_throttle_demand = 0.0
        self._speed_control_was_enabled = False
        self._last_nominal_sensor_data: SensorData | None = None
        self._snapshot = self._initial_snapshot()
        self.event_monitor = SimulationEventMonitor(
            self.event_log,
            initial_snapshot=self._snapshot,
        )

    @property
    def snapshot(self) -> EngineSimulationSnapshot:
        """Return the latest coordinated simulation snapshot."""

        return self._snapshot

    def add_snapshot_sink(self, sink: SnapshotSink) -> None:
        """Register one synchronous read-only snapshot consumer."""

        if all(existing is not sink for existing in self._snapshot_sinks):
            self._snapshot_sinks.append(sink)

    def remove_snapshot_sink(self, sink: SnapshotSink) -> None:
        """Remove one previously registered snapshot consumer."""

        self._snapshot_sinks = [
            existing for existing in self._snapshot_sinks if existing is not sink
        ]

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
        description = self.sensor_fault_injector.describe(channel)
        self.event_log.emit(
            self._simulation_time_s,
            EventCategory.SENSOR_FAULT,
            EventType.SENSOR_FAULT_INJECTED,
            EventSeverity.WARNING,
            "sensor_fault_injector",
            f"Injected {channel.value} sensor fault: {description}",
            new_value=description,
            diagnostic_code=sensor_fault_type(fault),
        )

    def clear_sensor_fault(self, channel: SensorChannel) -> None:
        """Clear one injected fault without resetting validator recovery."""

        if not self.sensor_fault_injector.is_active(channel):
            return
        previous_description = self.sensor_fault_injector.describe(channel)
        self.sensor_fault_injector.clear(channel)
        self.event_log.emit(
            self._simulation_time_s,
            EventCategory.SENSOR_FAULT,
            EventType.SENSOR_FAULT_CLEARED,
            EventSeverity.INFO,
            "sensor_fault_injector",
            f"Cleared {channel.value} sensor fault",
            old_value=previous_description,
            new_value="none",
        )

    def clear_sensor_faults(self) -> None:
        """Clear all injected faults without bypassing validation recovery."""

        for channel in SensorChannel:
            self.clear_sensor_fault(channel)

    def describe_sensor_fault(self, channel: SensorChannel) -> str:
        """Return the stable public description of one injected fault."""

        return self.sensor_fault_injector.describe(channel)

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
        self._step_index += 1
        self._snapshot_sequence_number += 1
        if operating_command.state is previous_operating_state:
            self._state_duration_s += time_step_s
        else:
            self._state_duration_s = 0.0
        self._speed_control_was_enabled = operating_command.speed_control_enabled
        egt_limiter_active = (
            ProtectionDiagnosticReason.EGT_LIMITING
            in protection_result.diagnostic_reasons
        )
        speed_setpoint_rpm = self._speed_setpoint_rpm(operating_command)
        validated_speed_rpm = validation_result.sensor_data.rotor_speed_rpm
        throttle_demand = self._clamp(request.throttle_command, 0.0, 1.0)
        latest_operator_command = self._latest_operator_command(
            request,
            throttle_demand,
        )
        self._snapshot = SimulationSnapshot(
            telemetry_schema_version=TELEMETRY_SCHEMA_VERSION,
            simulation_time_s=self._simulation_time_s,
            step_index=self._step_index,
            time_step_s=time_step_s,
            snapshot_sequence_number=self._snapshot_sequence_number,
            startup_requested=request.startup_requested,
            shutdown_requested=request.shutdown_requested,
            reset_requested=request.reset_requested,
            fault_requested=request.fault_requested,
            throttle_demand=throttle_demand,
            latest_operator_command=latest_operator_command,
            previous_operating_state=previous_operating_state,
            operating_state=operating_command.state,
            state_duration_s=self._state_duration_s,
            starter_commanded=allowed_command.starter_commanded,
            ignition_commanded=allowed_command.ignition_commanded,
            speed_control_enabled=operating_command.speed_control_enabled,
            fuel_enabled=allowed_command.fuel_enabled,
            throttle_command=operating_command.effective_throttle_command,
            speed_setpoint_rpm=speed_setpoint_rpm,
            speed_error_rpm=(
                speed_setpoint_rpm - validated_speed_rpm
                if operating_command.speed_control_enabled
                and validated_speed_rpm is not None
                else None
            ),
            requested_fuel_command=requested_command.fuel_command,
            rotor_speed_rpm=self.engine_model.state.rotor_speed_rpm,
            exhaust_temperature_c=(
                self.engine_model.state.exhaust_temperature_c
            ),
            estimated_thrust_n=engine_outputs.estimated_thrust_n,
            estimated_fuel_flow_ml_min=(
                engine_outputs.estimated_fuel_flow_ml_min
            ),
            measured_rotor_speed_rpm=raw_sensor_data.rotor_speed_rpm,
            validated_rotor_speed_rpm=validated_speed_rpm,
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
            rotor_speed_fault_type=sensor_fault_type(
                self.sensor_fault_injector.active_fault(
                    SensorChannel.ROTOR_SPEED
                )
            ),
            rotor_speed_fault_parameters=sensor_fault_parameters(
                self.sensor_fault_injector.active_fault(
                    SensorChannel.ROTOR_SPEED
                )
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
            exhaust_temperature_fault_type=sensor_fault_type(
                self.sensor_fault_injector.active_fault(
                    SensorChannel.EXHAUST_TEMPERATURE
                )
            ),
            exhaust_temperature_fault_parameters=sensor_fault_parameters(
                self.sensor_fault_injector.active_fault(
                    SensorChannel.EXHAUST_TEMPERATURE
                )
            ),
            aggregate_sensor_health=validation_result.aggregate_health,
            rotor_speed_sensor_sample_period_s=(
                self.sensor_model.rotor_speed_sample_period_s
            ),
            exhaust_temperature_sensor_sample_period_s=(
                self.sensor_model.exhaust_temperature_sample_period_s
            ),
            allowed_fuel_command=allowed_command.fuel_command,
            egt_fuel_limit=protection_result.egt_fuel_limit,
            egt_intervention_temperature_c=(
                self.egt_limiter.parameters.intervention_exhaust_temperature_c
            ),
            egt_maximum_temperature_c=(
                self.egt_limiter.parameters.maximum_exhaust_temperature_c
            ),
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
            shutdown_fuel_cutoff_active=(
                operating_command.shutdown_fuel_cutoff_active
            ),
            egt_limiter_active=egt_limiter_active,
            automatic_sensor_fault_request_active=(
                sensor_fault_response.automatic_fault_requested
            ),
            sensor_fault_response_reason=sensor_fault_response.reason.value,
            fuel_cutoff_due_to_sensor_invalidity=(
                sensor_fault_response.fuel_cutoff_required
            ),
        )
        self._previous_throttle_demand = throttle_demand
        self.event_monitor.observe(self._snapshot)
        for sink in tuple(self._snapshot_sinks):
            sink.publish(self._snapshot)
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

    def _latest_operator_command(
        self,
        request: EngineOperationRequest,
        throttle_demand: float,
    ) -> str:
        """Return a stable description of meaningful input on this step."""

        commands: list[str] = []
        if request.startup_requested:
            commands.append("start")
        if request.shutdown_requested:
            commands.append("shutdown")
        if request.fault_requested:
            commands.append("fault")
        if request.reset_requested:
            commands.append("reset")
        if abs(throttle_demand - self._previous_throttle_demand) > 1.0e-12:
            commands.append("throttle")
        return ",".join(commands) or "none"

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(value, maximum))

    def _initial_snapshot(self) -> EngineSimulationSnapshot:
        """Create the safe initial OFF-state snapshot."""

        protection_result = self.protection_manager.last_result
        return SimulationSnapshot(
            telemetry_schema_version=TELEMETRY_SCHEMA_VERSION,
            simulation_time_s=0.0,
            step_index=0,
            time_step_s=0.0,
            snapshot_sequence_number=0,
            startup_requested=False,
            shutdown_requested=False,
            reset_requested=False,
            fault_requested=False,
            throttle_demand=0.0,
            latest_operator_command="none",
            previous_operating_state=EngineOperatingState.OFF,
            operating_state=EngineOperatingState.OFF,
            state_duration_s=0.0,
            starter_commanded=False,
            ignition_commanded=False,
            speed_control_enabled=False,
            fuel_enabled=False,
            throttle_command=0.0,
            speed_setpoint_rpm=0.0,
            speed_error_rpm=None,
            requested_fuel_command=0.0,
            rotor_speed_rpm=self.engine_model.state.rotor_speed_rpm,
            exhaust_temperature_c=self.engine_model.state.exhaust_temperature_c,
            estimated_thrust_n=0.0,
            estimated_fuel_flow_ml_min=0.0,
            measured_rotor_speed_rpm=self.engine_model.state.rotor_speed_rpm,
            validated_rotor_speed_rpm=self.engine_model.state.rotor_speed_rpm,
            rotor_speed_measurement_error_rpm=0.0,
            rotor_speed_health=ChannelHealth.VALID,
            rotor_speed_diagnostic_reason=ChannelDiagnosticReason.NONE,
            rotor_speed_value_is_held=False,
            rotor_speed_fault="none",
            rotor_speed_fault_type="none",
            rotor_speed_fault_parameters=(),
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
            exhaust_temperature_fault_type="none",
            exhaust_temperature_fault_parameters=(),
            aggregate_sensor_health=ChannelHealth.VALID,
            rotor_speed_sensor_sample_period_s=(
                self.sensor_model.rotor_speed_sample_period_s
            ),
            exhaust_temperature_sensor_sample_period_s=(
                self.sensor_model.exhaust_temperature_sample_period_s
            ),
            allowed_fuel_command=0.0,
            egt_fuel_limit=protection_result.egt_fuel_limit,
            egt_intervention_temperature_c=(
                self.egt_limiter.parameters.intervention_exhaust_temperature_c
            ),
            egt_maximum_temperature_c=(
                self.egt_limiter.parameters.maximum_exhaust_temperature_c
            ),
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
            shutdown_fuel_cutoff_active=False,
            egt_limiter_active=False,
            automatic_sensor_fault_request_active=False,
            sensor_fault_response_reason=SensorFaultResponseReason.NONE.value,
            fuel_cutoff_due_to_sensor_invalidity=False,
        )
