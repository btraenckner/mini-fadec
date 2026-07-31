"""Testable control and history model for the live engine dashboard."""

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from simulation.application.engine_simulation import (
    EngineSimulationCoordinator,
    EngineSimulationSnapshot,
)
from simulation.application.simulation_service import SimulationService
from simulation.operation.engine_state import EngineOperatingState
from simulation.operation.state_machine import EngineOperationRequest
from simulation.scenarios.definitions import Scenario
from simulation.scenarios.library import list_scenarios
from simulation.scenarios.runner import (
    ScenarioExecutionState,
    ScenarioProgress,
    ScenarioRunner,
)
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
from simulation.telemetry.events import SimulationEvent
from simulation.verification.results import ScenarioResult


class DashboardOperatingMode(Enum):
    """Operator-selectable live dashboard execution modes."""

    MANUAL = "MANUAL"
    SCENARIO = "RUNNER"


class DashboardFaultType(Enum):
    """Fault types selectable from the live dashboard."""

    BIAS = "Bias"
    STUCK = "Stuck"
    DROPOUT = "Dropout"
    FORCED_VALUE = "Forced value"
    EXCESSIVE_NOISE = "Noise"
    DRIFT = "Drift"


class SensorFaultControlInterface(Protocol):
    """Narrow fault-control API shared by dashboard and terminal clients."""

    def inject_sensor_fault(
        self,
        channel: SensorChannel,
        fault: SensorFaultDefinition,
    ) -> None: ...

    def clear_sensor_fault(self, channel: SensorChannel) -> None: ...

    def clear_sensor_faults(self) -> None: ...

    def describe_sensor_fault(self, channel: SensorChannel) -> str: ...


@dataclass
class DashboardSensorFaultControls:
    """Testable sensor-fault selection and coordinator actions."""

    selected_channel: SensorChannel = SensorChannel.ROTOR_SPEED
    selected_fault_type: DashboardFaultType = DashboardFaultType.BIAS
    value_text: str = "5000"
    last_action_message: str = "No sensor fault action requested"

    def select_channel(self, channel: SensorChannel) -> None:
        """Select the channel targeted by the next dashboard action."""

        self.selected_channel = channel
        self.value_text = self.suggested_value_text()

    def select_fault_type(self, fault_type: DashboardFaultType) -> None:
        """Select the fault type targeted by the next dashboard action."""

        self.selected_fault_type = fault_type
        self.value_text = self.suggested_value_text()

    def set_value_text(self, value_text: str) -> None:
        """Store the optional numeric value entered by the operator."""

        self.value_text = value_text.strip()

    def inject(self, service: SensorFaultControlInterface) -> str:
        """Build and activate the selected typed fault definition."""

        fault = self._fault_definition()
        service.inject_sensor_fault(self.selected_channel, fault)
        self.last_action_message = (
            f"Injected {self._channel_name()}: "
            f"{service.describe_sensor_fault(self.selected_channel)}"
        )
        return self.last_action_message

    def clear_selected(self, service: SensorFaultControlInterface) -> str:
        """Clear the selected channel and begin validator recovery."""

        service.clear_sensor_fault(self.selected_channel)
        self.last_action_message = (
            f"Cleared {self._channel_name()}; validation recovery in progress"
        )
        return self.last_action_message

    def clear_all(self, service: SensorFaultControlInterface) -> str:
        """Clear both channels and begin validator recovery."""

        service.clear_sensor_faults()
        self.last_action_message = (
            "Cleared all sensor faults; validation recovery in progress"
        )
        return self.last_action_message

    def suggested_value_text(self) -> str:
        """Return a channel-specific initial value for the selected fault."""

        suggested_values = {
            (SensorChannel.ROTOR_SPEED, DashboardFaultType.BIAS): "5000",
            (SensorChannel.EXHAUST_TEMPERATURE, DashboardFaultType.BIAS): "40",
            (SensorChannel.ROTOR_SPEED, DashboardFaultType.STUCK): "",
            (SensorChannel.EXHAUST_TEMPERATURE, DashboardFaultType.STUCK): "",
            (SensorChannel.ROTOR_SPEED, DashboardFaultType.DROPOUT): "",
            (SensorChannel.EXHAUST_TEMPERATURE, DashboardFaultType.DROPOUT): "",
            (
                SensorChannel.ROTOR_SPEED,
                DashboardFaultType.FORCED_VALUE,
            ): "160000",
            (
                SensorChannel.EXHAUST_TEMPERATURE,
                DashboardFaultType.FORCED_VALUE,
            ): "1000",
            (
                SensorChannel.ROTOR_SPEED,
                DashboardFaultType.EXCESSIVE_NOISE,
            ): "1000",
            (
                SensorChannel.EXHAUST_TEMPERATURE,
                DashboardFaultType.EXCESSIVE_NOISE,
            ): "20",
            (SensorChannel.ROTOR_SPEED, DashboardFaultType.DRIFT): "500",
            (
                SensorChannel.EXHAUST_TEMPERATURE,
                DashboardFaultType.DRIFT,
            ): "20",
        }
        return suggested_values[
            (self.selected_channel, self.selected_fault_type)
        ]

    def value_hint(self) -> str:
        """Return concise input guidance for the selected fault."""

        unit = (
            "rpm" if self.selected_channel is SensorChannel.ROTOR_SPEED else "°C"
        )
        if self.selected_fault_type is DashboardFaultType.STUCK:
            return f"Value [{unit}] optional; blank freezes current measurement"
        if self.selected_fault_type is DashboardFaultType.DROPOUT:
            return "Value ignored; raw measurement becomes unavailable"
        if self.selected_fault_type is DashboardFaultType.EXCESSIVE_NOISE:
            return f"Additional Gaussian standard deviation [{unit}]"
        if self.selected_fault_type is DashboardFaultType.DRIFT:
            return f"Linear drift rate [{unit}/s]"
        return f"Fault value [{unit}]"

    def _fault_definition(self) -> SensorFaultDefinition:
        """Convert the current selection into one typed fault definition."""

        if self.selected_fault_type is DashboardFaultType.DROPOUT:
            return DropoutSensorFault()
        if self.selected_fault_type is DashboardFaultType.STUCK:
            return StuckSensorFault(value=self._optional_value())

        value = self._required_value()
        if self.selected_fault_type is DashboardFaultType.BIAS:
            return BiasSensorFault(offset=value)
        if self.selected_fault_type is DashboardFaultType.FORCED_VALUE:
            return ForcedValueSensorFault(value=value)
        if self.selected_fault_type is DashboardFaultType.EXCESSIVE_NOISE:
            return ExcessiveNoiseSensorFault(standard_deviation=value)
        return DriftSensorFault(rate_per_second=value)

    def _required_value(self) -> float:
        """Parse a required finite numeric fault value."""

        if not self.value_text:
            raise ValueError("the selected sensor fault requires a value")
        return self._parse_value(self.value_text)

    def _optional_value(self) -> float | None:
        """Parse an optional explicit stuck value."""

        if not self.value_text:
            return None
        return self._parse_value(self.value_text)

    @staticmethod
    def _parse_value(value_text: str) -> float:
        """Parse one numeric dashboard field with a clear error."""

        try:
            value = float(value_text)
        except ValueError as error:
            raise ValueError("sensor fault value must be numeric") from error
        if not math.isfinite(value):
            raise ValueError("sensor fault value must be finite")
        return value

    def _channel_name(self) -> str:
        """Return the selected channel's user-facing name."""

        if self.selected_channel is SensorChannel.ROTOR_SPEED:
            return "rotor-speed sensor"
        return "EGT sensor"


@dataclass
class DashboardControls:
    """Persistent throttle and one-shot dashboard operator requests."""

    throttle_command: float = 0.0
    _startup_requested: bool = False
    _shutdown_requested: bool = False
    _fault_requested: bool = False
    _reset_requested: bool = False

    def set_throttle(self, throttle_command: float) -> None:
        """Set and clamp the persistent operator throttle demand."""

        self.throttle_command = self._clamp(throttle_command, 0.0, 1.0)

    def request_startup(self) -> None:
        """Queue a one-shot startup request."""

        self._startup_requested = True

    def request_shutdown(self) -> None:
        """Queue a one-shot shutdown request."""

        self._shutdown_requested = True

    def request_fault(self) -> None:
        """Queue a one-shot manual fault request."""

        self._fault_requested = True

    def request_reset(self) -> None:
        """Queue a one-shot fault-reset request."""

        self._reset_requested = True

    def consume_request(self) -> EngineOperationRequest:
        """Return pending requests and clear one-shot request flags."""

        request = EngineOperationRequest(
            throttle_command=self.throttle_command,
            startup_requested=self._startup_requested,
            shutdown_requested=self._shutdown_requested,
            fault_requested=self._fault_requested,
            reset_requested=self._reset_requested,
        )
        self._startup_requested = False
        self._shutdown_requested = False
        self._fault_requested = False
        self._reset_requested = False
        return request

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        """Limit a value to a closed interval."""

        return max(minimum, min(value, maximum))


@dataclass
class DashboardHistory:
    """Bounded time history of live dashboard telemetry."""

    maximum_samples: int = 12_000
    times_s: list[float] = field(default_factory=list)
    operating_states: list[EngineOperatingState] = field(default_factory=list)
    throttle_commands: list[float] = field(default_factory=list)
    speed_setpoints_rpm: list[float] = field(default_factory=list)
    rotor_speeds_rpm: list[float] = field(default_factory=list)
    measured_rotor_speeds_rpm: list[float | None] = field(default_factory=list)
    validated_rotor_speeds_rpm: list[float | None] = field(
        default_factory=list
    )
    exhaust_temperatures_c: list[float] = field(default_factory=list)
    measured_exhaust_temperatures_c: list[float | None] = field(
        default_factory=list
    )
    validated_exhaust_temperatures_c: list[float | None] = field(
        default_factory=list
    )
    requested_fuel_commands: list[float] = field(default_factory=list)
    allowed_fuel_commands: list[float] = field(default_factory=list)
    estimated_thrusts_n: list[float] = field(default_factory=list)
    egt_limiter_activity: list[bool] = field(default_factory=list)

    def append(self, snapshot: EngineSimulationSnapshot) -> None:
        """Append one telemetry snapshot and enforce the history bound."""

        self.times_s.append(snapshot.simulation_time_s)
        self.operating_states.append(snapshot.operating_state)
        self.throttle_commands.append(snapshot.throttle_command)
        self.speed_setpoints_rpm.append(snapshot.speed_setpoint_rpm)
        self.rotor_speeds_rpm.append(snapshot.rotor_speed_rpm)
        self.measured_rotor_speeds_rpm.append(
            snapshot.measured_rotor_speed_rpm
        )
        self.validated_rotor_speeds_rpm.append(
            snapshot.validated_rotor_speed_rpm
        )
        self.exhaust_temperatures_c.append(snapshot.exhaust_temperature_c)
        self.measured_exhaust_temperatures_c.append(
            snapshot.measured_exhaust_temperature_c
        )
        self.validated_exhaust_temperatures_c.append(
            snapshot.validated_exhaust_temperature_c
        )
        self.requested_fuel_commands.append(snapshot.requested_fuel_command)
        self.allowed_fuel_commands.append(snapshot.allowed_fuel_command)
        self.estimated_thrusts_n.append(snapshot.estimated_thrust_n)
        self.egt_limiter_activity.append(snapshot.egt_limiter_active)
        self._trim_to_maximum_samples()

    def clear(self) -> None:
        """Clear every signal so a new dashboard session starts at zero."""

        histories: tuple[list[object], ...] = (
            self.times_s,
            self.operating_states,
            self.throttle_commands,
            self.speed_setpoints_rpm,
            self.rotor_speeds_rpm,
            self.measured_rotor_speeds_rpm,
            self.validated_rotor_speeds_rpm,
            self.exhaust_temperatures_c,
            self.measured_exhaust_temperatures_c,
            self.validated_exhaust_temperatures_c,
            self.requested_fuel_commands,
            self.allowed_fuel_commands,
            self.estimated_thrusts_n,
            self.egt_limiter_activity,
        )
        for history in histories:
            history.clear()

    def _trim_to_maximum_samples(self) -> None:
        """Discard the oldest samples when the configured bound is exceeded."""

        number_of_excess_samples = len(self.times_s) - self.maximum_samples
        if number_of_excess_samples <= 0:
            return

        histories: tuple[list[object], ...] = (
            self.times_s,
            self.operating_states,
            self.throttle_commands,
            self.speed_setpoints_rpm,
            self.rotor_speeds_rpm,
            self.measured_rotor_speeds_rpm,
            self.validated_rotor_speeds_rpm,
            self.exhaust_temperatures_c,
            self.measured_exhaust_temperatures_c,
            self.validated_exhaust_temperatures_c,
            self.requested_fuel_commands,
            self.allowed_fuel_commands,
            self.estimated_thrusts_n,
            self.egt_limiter_activity,
        )
        for history in histories:
            del history[:number_of_excess_samples]


class DashboardSimulation:
    """Advance the coordinator from elapsed wall time for a live dashboard."""

    def __init__(
        self,
        coordinator: EngineSimulationCoordinator | None = None,
        service: SimulationService | None = None,
        controls: DashboardControls | None = None,
        sensor_fault_controls: DashboardSensorFaultControls | None = None,
        history: DashboardHistory | None = None,
        scenarios: tuple[Scenario, ...] | None = None,
        scenario_runner_factory: Callable[[], ScenarioRunner] | None = None,
        *,
        time_step_s: float = 0.01,
        maximum_catch_up_s: float = 0.25,
    ) -> None:
        if coordinator is not None and service is not None:
            raise ValueError("provide either coordinator or service, not both")
        self.service = service or SimulationService(
            coordinator=coordinator,
            time_step_s=time_step_s,
        )
        # Compatibility view for integrations that only read the coordinator.
        self.coordinator = self.service.coordinator
        self.controls = controls or DashboardControls()
        self.sensor_fault_controls = (
            sensor_fault_controls or DashboardSensorFaultControls()
        )
        self.history = history or DashboardHistory()
        self.time_step_s = time_step_s
        self.maximum_catch_up_s = maximum_catch_up_s
        self._accumulated_time_s = 0.0
        self.scenarios = scenarios if scenarios is not None else list_scenarios()
        if not self.scenarios:
            raise ValueError("the dashboard requires at least one scenario")
        self._scenario_runner_factory = (
            scenario_runner_factory or ScenarioRunner
        )
        self.operating_mode = DashboardOperatingMode.MANUAL
        self._selected_scenario_index = 0
        self._scenario_runner: ScenarioRunner | None = None
        self._scenario_progress: ScenarioProgress | None = None
        self._scenario_result: ScenarioResult | None = None

    def advance(self, elapsed_wall_time_s: float) -> EngineSimulationSnapshot:
        """Advance fixed simulation steps represented by elapsed wall time."""

        if elapsed_wall_time_s < 0.0:
            raise ValueError("elapsed_wall_time_s must not be negative")

        if (
            self.operating_mode is DashboardOperatingMode.SCENARIO
            and self._scenario_progress is not None
        ):
            return self._advance_scenario(elapsed_wall_time_s)
        if self.operating_mode is DashboardOperatingMode.SCENARIO:
            return self.service.get_latest_snapshot()

        self._accumulated_time_s += min(
            elapsed_wall_time_s,
            self.maximum_catch_up_s,
        )
        while self._accumulated_time_s >= self.time_step_s:
            self.service.apply_request(self.controls.consume_request())
            snapshot = self.service.step()
            self.history.append(snapshot)
            self._accumulated_time_s -= self.time_step_s

        return self.service.get_latest_snapshot()

    @property
    def selected_scenario(self) -> Scenario:
        """Return the scenario currently selected by the operator."""

        return self.scenarios[self._selected_scenario_index]

    @property
    def scenario_progress(self) -> ScenarioProgress | None:
        """Return the most recent immutable scenario progress view."""

        return self._scenario_progress

    @property
    def scenario_result(self) -> ScenarioResult | None:
        """Return the final scenario result when execution has terminated."""

        return self._scenario_result

    @property
    def scenario_mode_active(self) -> bool:
        """Return whether the dashboard is displaying a scenario session."""

        return self.operating_mode is DashboardOperatingMode.SCENARIO

    @property
    def scenario_is_running(self) -> bool:
        """Return whether the selected scenario is actively advancing."""

        return (
            self._scenario_progress is not None
            and self._scenario_progress.execution_state
            is ScenarioExecutionState.RUNNING
        )

    def select_adjacent_scenario(self, offset: int) -> Scenario:
        """Cycle through the deterministic scenario library."""

        return self.select_scenario(
            (self._selected_scenario_index + offset) % len(self.scenarios)
        )

    def select_scenario(self, scenario_index: int) -> Scenario:
        """Select one registered scenario while the runner is stopped."""

        if self.scenario_is_running:
            raise RuntimeError(
                "cancel or finish the scenario before changing selection"
            )
        if not 0 <= scenario_index < len(self.scenarios):
            raise IndexError("scenario index is out of range")
        self._selected_scenario_index = scenario_index
        self._scenario_runner = None
        self._scenario_progress = None
        self._scenario_result = None
        return self.selected_scenario

    def enter_runner_mode(self) -> EngineSimulationSnapshot:
        """Switch from direct manual control to scenario-runner control."""

        if self.service.recorder.is_recording:
            raise RuntimeError(
                "stop the manual recording before entering runner mode"
            )
        self.operating_mode = DashboardOperatingMode.SCENARIO
        self._accumulated_time_s = 0.0
        return self.get_latest_snapshot()

    def start_selected_scenario(self) -> ScenarioProgress:
        """Prepare the selected scenario and enter isolated scenario mode."""

        if self.scenario_is_running:
            raise RuntimeError("a dashboard scenario is already running")
        if self.service.recorder.is_recording:
            raise RuntimeError(
                "stop the manual recording before starting a scenario"
            )

        self._scenario_runner = self._scenario_runner_factory()
        self._scenario_progress = self._scenario_runner.prepare_scenario(
            self.selected_scenario
        )
        self._scenario_result = self._scenario_runner.result
        self.operating_mode = DashboardOperatingMode.SCENARIO
        self._accumulated_time_s = 0.0
        self.history.clear()
        self.history.append(self._scenario_progress.latest_snapshot)
        return self._scenario_progress

    def cancel_scenario(self) -> ScenarioResult:
        """Cancel an active scenario and retain its final evidence for review."""

        if self._scenario_runner is None or self._scenario_progress is None:
            raise RuntimeError("no dashboard scenario has been started")
        self._scenario_result = self._scenario_runner.cancel_scenario()
        self._scenario_progress = (
            self._scenario_runner.get_scenario_progress()
        )
        self._append_scenario_snapshot()
        return self._scenario_result

    def return_to_manual_mode(self) -> EngineSimulationSnapshot:
        """Leave a completed scenario and restore the manual simulation."""

        if self.scenario_is_running:
            raise RuntimeError(
                "cancel or finish the scenario before returning to manual mode"
            )
        self.operating_mode = DashboardOperatingMode.MANUAL
        self._accumulated_time_s = 0.0
        snapshot = self.service.get_latest_snapshot()
        self.history.clear()
        self.history.append(snapshot)
        return snapshot

    def get_latest_snapshot(self) -> EngineSimulationSnapshot:
        """Return the snapshot belonging to the displayed execution mode."""

        if self.scenario_mode_active and self._scenario_progress is not None:
            return self._scenario_progress.latest_snapshot
        return self.service.get_latest_snapshot()

    def get_recent_events(self) -> tuple[SimulationEvent, ...]:
        """Return events belonging to the displayed execution mode."""

        if self.scenario_mode_active and self._scenario_progress is not None:
            return self._scenario_progress.recent_events
        return tuple(self.service.get_recent_events())

    def close(self) -> None:
        """Finalize active dashboard-owned execution and recording resources."""

        if self.scenario_is_running:
            self.cancel_scenario()
        self.service.close(completed=True)

    def _advance_scenario(
        self,
        elapsed_wall_time_s: float,
    ) -> EngineSimulationSnapshot:
        """Advance the active scenario at its configured fixed time step."""

        if self._scenario_runner is None or self._scenario_progress is None:
            raise RuntimeError("scenario mode has no prepared scenario")

        scenario_time_step_s = (
            self.selected_scenario.time_step_s or self.time_step_s
        )
        self._accumulated_time_s += min(
            elapsed_wall_time_s,
            self.maximum_catch_up_s,
        )
        while (
            self._accumulated_time_s >= scenario_time_step_s
            and self.scenario_is_running
        ):
            self._scenario_progress = (
                self._scenario_runner.step_scenario()
            )
            self._scenario_result = self._scenario_runner.result
            self._append_scenario_snapshot()
            self._accumulated_time_s -= scenario_time_step_s

        return self._scenario_progress.latest_snapshot

    def _append_scenario_snapshot(self) -> None:
        """Append a scenario snapshot once while preserving bounded history."""

        assert self._scenario_progress is not None
        snapshot = self._scenario_progress.latest_snapshot
        if (
            self.history.times_s
            and self.history.times_s[-1] == snapshot.simulation_time_s
        ):
            return
        self.history.append(snapshot)
