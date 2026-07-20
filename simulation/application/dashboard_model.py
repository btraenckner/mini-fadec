"""Testable control and history model for the live engine dashboard."""

from dataclasses import dataclass, field

from simulation.application.engine_simulation import (
    EngineSimulationCoordinator,
    EngineSimulationSnapshot,
)
from simulation.operation.engine_state import EngineOperatingState
from simulation.operation.state_machine import EngineOperationRequest


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
        controls: DashboardControls | None = None,
        history: DashboardHistory | None = None,
        *,
        time_step_s: float = 0.01,
        maximum_catch_up_s: float = 0.25,
    ) -> None:
        self.coordinator = coordinator or EngineSimulationCoordinator()
        self.controls = controls or DashboardControls()
        self.history = history or DashboardHistory()
        self.time_step_s = time_step_s
        self.maximum_catch_up_s = maximum_catch_up_s
        self._accumulated_time_s = 0.0

    def advance(self, elapsed_wall_time_s: float) -> EngineSimulationSnapshot:
        """Advance fixed simulation steps represented by elapsed wall time."""

        if elapsed_wall_time_s < 0.0:
            raise ValueError("elapsed_wall_time_s must not be negative")

        self._accumulated_time_s += min(
            elapsed_wall_time_s,
            self.maximum_catch_up_s,
        )
        while self._accumulated_time_s >= self.time_step_s:
            snapshot = self.coordinator.step(
                request=self.controls.consume_request(),
                time_step_s=self.time_step_s,
            )
            self.history.append(snapshot)
            self._accumulated_time_s -= self.time_step_s

        return self.coordinator.snapshot
