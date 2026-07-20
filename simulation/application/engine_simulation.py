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
        self.egt_limiter = egt_limiter or ExhaustTemperatureLimiter()
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
        self._last_nominal_sensor_data = SensorData(
            rotor_speed_rpm=self.engine_model.state.rotor_speed_rpm,
            exhaust_temperature_c=self.engine_model.state.exhaust_temperature_c,
        )
        self._snapshot = self._initial_snapshot()

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
        allowed_command = self._protected_actuator_command(
            requested_command=requested_command,
            operating_command=operating_command,
            sensor_data=validation_result.sensor_data,
            time_step_s=time_step_s,
        )
        if sensor_fault_response.fuel_cutoff_required:
            allowed_command = ActuatorCommand(
                fuel_command=0.0,
                starter_commanded=False,
                ignition_commanded=False,
                fuel_enabled=False,
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
        )

        egt_limiter_active = (
            operating_command.speed_control_enabled
            and allowed_command.fuel_command < requested_command.fuel_command
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
        time_step_s: float,
    ) -> ActuatorCommand:
        """Apply EGT protection only in closed-loop running modes."""

        if not operating_command.speed_control_enabled:
            return requested_command

        complete_sensor_data = self._required_sensor_data(sensor_data)
        return self.egt_limiter.apply(
            requested_command=requested_command,
            sensor_data=complete_sensor_data,
            time_step_s=time_step_s,
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
    ) -> None:
        """Record health transitions and newly activated critical responses."""

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
