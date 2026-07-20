"""Composition of engine operation, control, protection, and dynamics."""

from dataclasses import dataclass

from simulation.controllers.speed_controller import PIEngineSpeedController
from simulation.core.interfaces import SensorModelInterface
from simulation.core.types import (
    ActuatorCommand,
    AmbientConditions,
    ControlRequest,
    SensorData,
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


@dataclass(frozen=True)
class EngineSimulationSnapshot:
    """Observable state of one coordinated simulation step."""

    simulation_time_s: float
    previous_operating_state: EngineOperatingState
    operating_state: EngineOperatingState
    throttle_command: float
    speed_setpoint_rpm: float
    rotor_speed_rpm: float
    measured_rotor_speed_rpm: float
    rotor_speed_measurement_error_rpm: float
    exhaust_temperature_c: float
    measured_exhaust_temperature_c: float
    exhaust_temperature_measurement_error_c: float
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


class EngineSimulationCoordinator:
    """Compose the operating state machine with control and engine dynamics."""

    def __init__(
        self,
        engine_model: FirstOrderEngineModel | None = None,
        state_machine: EngineStateMachine | None = None,
        speed_controller: PIEngineSpeedController | None = None,
        egt_limiter: ExhaustTemperatureLimiter | None = None,
        sensor_model: SensorModelInterface | None = None,
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
        self.ambient_conditions = ambient_conditions or AmbientConditions()

        self._simulation_time_s = 0.0
        self._speed_control_was_enabled = False
        self._snapshot = self._initial_snapshot()

    @property
    def snapshot(self) -> EngineSimulationSnapshot:
        """Return the latest coordinated simulation snapshot."""

        return self._snapshot

    def step(
        self,
        request: EngineOperationRequest,
        time_step_s: float,
    ) -> EngineSimulationSnapshot:
        """Advance all composed simulation components by one time step."""

        sensor_data = self.sensor_model.measure(
            engine_state=self.engine_model.state,
            time_step_s=time_step_s,
        )
        previous_operating_state = self.state_machine.state
        operating_command = self.state_machine.update(
            request=request,
            sensor_data=sensor_data,
            time_step_s=time_step_s,
        )

        if self._speed_control_was_enabled and not (
            operating_command.speed_control_enabled
        ):
            self.speed_controller.reset()

        requested_command = self._requested_actuator_command(
            operating_command=operating_command,
            sensor_data=sensor_data,
            time_step_s=time_step_s,
        )
        allowed_command = self._protected_actuator_command(
            requested_command=requested_command,
            operating_command=operating_command,
            sensor_data=sensor_data,
            time_step_s=time_step_s,
        )

        engine_outputs = self.engine_model.step(
            actuator_command=allowed_command,
            ambient_conditions=self.ambient_conditions,
            time_step_s=time_step_s,
        )
        self._simulation_time_s += time_step_s
        self._speed_control_was_enabled = operating_command.speed_control_enabled

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
            measured_rotor_speed_rpm=sensor_data.rotor_speed_rpm,
            rotor_speed_measurement_error_rpm=(
                sensor_data.rotor_speed_rpm
                - self.engine_model.state.rotor_speed_rpm
            ),
            exhaust_temperature_c=(
                self.engine_model.state.exhaust_temperature_c
            ),
            measured_exhaust_temperature_c=(
                sensor_data.exhaust_temperature_c
            ),
            exhaust_temperature_measurement_error_c=(
                sensor_data.exhaust_temperature_c
                - self.engine_model.state.exhaust_temperature_c
            ),
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
        )
        return self._snapshot

    def _requested_actuator_command(
        self,
        operating_command: EngineOperatingCommand,
        sensor_data: SensorData,
        time_step_s: float,
    ) -> ActuatorCommand:
        """Calculate the requested command for the current operating mode."""

        if operating_command.speed_control_enabled:
            controller_command = self.speed_controller.update(
                control_request=ControlRequest(
                    throttle_command=(
                        operating_command.effective_throttle_command
                    )
                ),
                sensor_data=sensor_data,
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
        sensor_data: SensorData,
        time_step_s: float,
    ) -> ActuatorCommand:
        """Apply EGT protection only in closed-loop running modes."""

        if not operating_command.speed_control_enabled:
            return requested_command

        return self.egt_limiter.apply(
            requested_command=requested_command,
            sensor_data=sensor_data,
            time_step_s=time_step_s,
        )

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
            rotor_speed_measurement_error_rpm=0.0,
            exhaust_temperature_c=self.engine_model.state.exhaust_temperature_c,
            measured_exhaust_temperature_c=(
                self.engine_model.state.exhaust_temperature_c
            ),
            exhaust_temperature_measurement_error_c=0.0,
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
        )
