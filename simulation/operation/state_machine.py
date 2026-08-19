"""Operating-state transition logic for the Mini-FADEC simulation."""

from dataclasses import dataclass

from simulation.core.types import SensorData, ValidatedSensorData
from simulation.operation.engine_state import EngineOperatingState


@dataclass(frozen=True)
class EngineStateMachineParameters:
    """Configuration parameters of the engine operating state machine."""

    # Initial grey-box assumptions; these values are not physically validated.
    ignition_enable_speed_rpm: float = 15_000.0
    self_sustaining_speed_rpm: float = 35_000.0
    stopped_speed_threshold_rpm: float = 500.0
    light_off_temperature_c: float = 500.0
    start_fuel_command: float = 0.25
    maximum_start_duration_s: float = 10.0
    idle_throttle_command: float = 0.0
    running_throttle_threshold: float = 0.02

    def __post_init__(self) -> None:
        if self.maximum_start_duration_s <= 0.0:
            raise ValueError("maximum start duration must be greater than zero")


@dataclass(frozen=True)
class EngineOperationRequest:
    """Explicit operator requests consumed by the state machine."""

    throttle_command: float = 0.0
    startup_requested: bool = False
    shutdown_requested: bool = False
    fault_requested: bool = False
    reset_requested: bool = False


@dataclass(frozen=True)
class EngineOperatingCommand:
    """Operating mode command produced by the state machine."""

    state: EngineOperatingState
    starter_commanded: bool
    ignition_commanded: bool
    speed_control_enabled: bool
    fuel_enabled: bool
    effective_throttle_command: float
    open_loop_fuel_command: float
    shutdown_fuel_cutoff_active: bool


class EngineStateMachine:
    """Manage explicit engine operating-state transitions."""

    def __init__(
        self,
        parameters: EngineStateMachineParameters | None = None,
    ) -> None:
        self.parameters = parameters or EngineStateMachineParameters()
        self._state = EngineOperatingState.OFF
        self._start_elapsed_s = 0.0
        self._start_timeout_triggered = False

    @property
    def state(self) -> EngineOperatingState:
        """Return the current engine operating state."""

        return self._state

    @property
    def start_elapsed_s(self) -> float:
        """Return elapsed CRANKING and IGNITION supervision time."""

        return self._start_elapsed_s

    @property
    def start_timeout_triggered(self) -> bool:
        """Return whether the current FAULT resulted from a hung start."""

        return self._start_timeout_triggered

    def update(
        self,
        request: EngineOperationRequest,
        sensor_data: SensorData | ValidatedSensorData,
        time_step_s: float,
    ) -> EngineOperatingCommand:
        """Evaluate transitions and return the resulting operating command."""

        if time_step_s <= 0.0:
            raise ValueError("time_step_s must be greater than zero")

        previous_state = self._state
        self._evaluate_transitions(request=request, sensor_data=sensor_data)
        self._update_start_supervision(previous_state, time_step_s)
        return self._command_for_state(request.throttle_command)

    def _update_start_supervision(
        self,
        previous_state: EngineOperatingState,
        time_step_s: float,
    ) -> None:
        start_states = {
            EngineOperatingState.CRANKING,
            EngineOperatingState.IGNITION,
        }
        if self._state in start_states:
            if previous_state not in start_states:
                self._start_elapsed_s = 0.0
                self._start_timeout_triggered = False
            self._start_elapsed_s += time_step_s
            if (
                self._start_elapsed_s
                >= self.parameters.maximum_start_duration_s
            ):
                self._state = EngineOperatingState.FAULT
                self._start_timeout_triggered = True
            return

        self._start_elapsed_s = 0.0
        if self._state is not EngineOperatingState.FAULT:
            self._start_timeout_triggered = False

    def _evaluate_transitions(
        self,
        request: EngineOperationRequest,
        sensor_data: SensorData | ValidatedSensorData,
    ) -> None:
        """Evaluate explicit transition conditions in priority order."""

        if request.fault_requested:
            self._state = EngineOperatingState.FAULT
            return

        if self._state is EngineOperatingState.FAULT:
            if (
                request.reset_requested
                and sensor_data.rotor_speed_rpm is not None
                and sensor_data.rotor_speed_rpm
                <= self.parameters.stopped_speed_threshold_rpm
            ):
                self._state = EngineOperatingState.OFF
            return

        if request.shutdown_requested and self._state in {
            EngineOperatingState.CRANKING,
            EngineOperatingState.IGNITION,
            EngineOperatingState.IDLE,
            EngineOperatingState.RUNNING,
        }:
            self._state = EngineOperatingState.SHUTDOWN
            return

        if self._state is EngineOperatingState.OFF:
            if request.startup_requested:
                self._state = EngineOperatingState.CRANKING
            return

        if self._state is EngineOperatingState.CRANKING:
            if (
                sensor_data.rotor_speed_rpm is not None
                and sensor_data.rotor_speed_rpm
                >= self.parameters.ignition_enable_speed_rpm
            ):
                self._state = EngineOperatingState.IGNITION
            return

        if self._state is EngineOperatingState.IGNITION:
            light_off_detected = (
                sensor_data.exhaust_temperature_c is not None
                and sensor_data.exhaust_temperature_c
                >= self.parameters.light_off_temperature_c
            )
            self_sustaining_speed_reached = (
                sensor_data.rotor_speed_rpm is not None
                and sensor_data.rotor_speed_rpm
                >= self.parameters.self_sustaining_speed_rpm
            )
            if light_off_detected and self_sustaining_speed_reached:
                self._state = EngineOperatingState.IDLE
            return

        if self._state is EngineOperatingState.IDLE:
            if request.throttle_command > self.parameters.running_throttle_threshold:
                self._state = EngineOperatingState.RUNNING
            return

        if self._state is EngineOperatingState.RUNNING:
            if request.throttle_command <= self.parameters.running_throttle_threshold:
                self._state = EngineOperatingState.IDLE
            return

        if self._state is EngineOperatingState.SHUTDOWN and (
            sensor_data.rotor_speed_rpm is not None
            and sensor_data.rotor_speed_rpm
            <= self.parameters.stopped_speed_threshold_rpm
        ):
            self._state = EngineOperatingState.OFF

    def _command_for_state(
        self,
        operator_throttle_command: float,
    ) -> EngineOperatingCommand:
        """Return actuator and control permissions for the current state."""

        if self._state is EngineOperatingState.CRANKING:
            return EngineOperatingCommand(
                state=self._state,
                starter_commanded=True,
                ignition_commanded=False,
                speed_control_enabled=False,
                fuel_enabled=False,
                effective_throttle_command=0.0,
                open_loop_fuel_command=0.0,
                shutdown_fuel_cutoff_active=False,
            )

        if self._state is EngineOperatingState.IGNITION:
            return EngineOperatingCommand(
                state=self._state,
                starter_commanded=True,
                ignition_commanded=True,
                speed_control_enabled=False,
                fuel_enabled=True,
                effective_throttle_command=0.0,
                open_loop_fuel_command=self.parameters.start_fuel_command,
                shutdown_fuel_cutoff_active=False,
            )

        if self._state in {
            EngineOperatingState.IDLE,
            EngineOperatingState.RUNNING,
        }:
            effective_throttle_command = (
                self.parameters.idle_throttle_command
                if self._state is EngineOperatingState.IDLE
                else self._clamp(operator_throttle_command, 0.0, 1.0)
            )
            return EngineOperatingCommand(
                state=self._state,
                starter_commanded=False,
                ignition_commanded=False,
                speed_control_enabled=True,
                fuel_enabled=True,
                effective_throttle_command=effective_throttle_command,
                open_loop_fuel_command=0.0,
                shutdown_fuel_cutoff_active=False,
            )

        fuel_cutoff_active = self._state in {
            EngineOperatingState.SHUTDOWN,
            EngineOperatingState.FAULT,
        }
        return EngineOperatingCommand(
            state=self._state,
            starter_commanded=False,
            ignition_commanded=False,
            speed_control_enabled=False,
            fuel_enabled=False,
            effective_throttle_command=0.0,
            open_loop_fuel_command=0.0,
            shutdown_fuel_cutoff_active=fuel_cutoff_active,
        )

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        """Limit a value to a closed interval."""

        return max(minimum, min(value, maximum))
