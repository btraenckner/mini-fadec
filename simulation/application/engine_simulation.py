"""Composition of engine operation, control, protection, and dynamics."""

from dataclasses import dataclass

from simulation.controllers.speed_controller import PIEngineSpeedController
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


@dataclass(frozen=True)
class EngineSimulationSnapshot:
    """Observable state of one coordinated simulation step."""

    simulation_time_s: float
    previous_operating_state: EngineOperatingState
    operating_state: EngineOperatingState
    throttle_command: float
    rotor_speed_rpm: float
    exhaust_temperature_c: float
    requested_fuel_command: float
    allowed_fuel_command: float
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
        ambient_conditions: AmbientConditions | None = None,
    ) -> None:
        self.engine_model = engine_model or FirstOrderEngineModel()
        self.state_machine = state_machine or EngineStateMachine()
        self.speed_controller = speed_controller or PIEngineSpeedController()
        self.egt_limiter = egt_limiter or ExhaustTemperatureLimiter()
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

        sensor_data = self._sensor_data()
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

        self.engine_model.step(
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
            rotor_speed_rpm=self.engine_model.state.rotor_speed_rpm,
            exhaust_temperature_c=(
                self.engine_model.state.exhaust_temperature_c
            ),
            requested_fuel_command=requested_command.fuel_command,
            allowed_fuel_command=allowed_command.fuel_command,
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

    def _sensor_data(self) -> SensorData:
        """Create ideal sensor data from the current engine state."""

        return SensorData(
            rotor_speed_rpm=self.engine_model.state.rotor_speed_rpm,
            exhaust_temperature_c=self.engine_model.state.exhaust_temperature_c,
        )

    def _initial_snapshot(self) -> EngineSimulationSnapshot:
        """Create the safe initial OFF-state snapshot."""

        return EngineSimulationSnapshot(
            simulation_time_s=0.0,
            previous_operating_state=EngineOperatingState.OFF,
            operating_state=EngineOperatingState.OFF,
            throttle_command=0.0,
            rotor_speed_rpm=self.engine_model.state.rotor_speed_rpm,
            exhaust_temperature_c=self.engine_model.state.exhaust_temperature_c,
            requested_fuel_command=0.0,
            allowed_fuel_command=0.0,
            starter_commanded=False,
            ignition_commanded=False,
            speed_control_enabled=False,
            fuel_enabled=False,
            shutdown_fuel_cutoff_active=False,
            egt_limiter_active=False,
        )
