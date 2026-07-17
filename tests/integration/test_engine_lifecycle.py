"""Integration tests for the complete engine operating lifecycle."""

from simulation.application.engine_simulation import EngineSimulationCoordinator
from simulation.operation.engine_state import EngineOperatingState
from simulation.operation.state_machine import EngineOperationRequest


def test_complete_engine_lifecycle() -> None:
    coordinator = EngineSimulationCoordinator()
    time_step_s = 0.01
    throttle_command = 0.0
    startup_requested = True
    shutdown_requested = False

    visited_states = [EngineOperatingState.OFF]
    startup_completion_time_s: float | None = None
    idle_speed_rpm: float | None = None
    maximum_running_speed_rpm = 0.0
    egt_limiter_activated = False
    shutdown_fuel_commands: list[float] = []

    for _ in range(int(30.0 / time_step_s)):
        snapshot = coordinator.step(
            request=EngineOperationRequest(
                throttle_command=throttle_command,
                startup_requested=startup_requested,
                shutdown_requested=shutdown_requested,
            ),
            time_step_s=time_step_s,
        )
        startup_requested = False
        shutdown_requested = False

        if snapshot.operating_state is not visited_states[-1]:
            visited_states.append(snapshot.operating_state)

        if (
            snapshot.operating_state is EngineOperatingState.IDLE
            and startup_completion_time_s is None
        ):
            startup_completion_time_s = snapshot.simulation_time_s
            idle_speed_rpm = snapshot.rotor_speed_rpm
            throttle_command = 1.0

        if snapshot.operating_state is EngineOperatingState.RUNNING:
            maximum_running_speed_rpm = max(
                maximum_running_speed_rpm,
                snapshot.rotor_speed_rpm,
            )
            egt_limiter_activated = (
                egt_limiter_activated or snapshot.egt_limiter_active
            )
            if (
                idle_speed_rpm is not None
                and maximum_running_speed_rpm > idle_speed_rpm + 10_000.0
                and egt_limiter_activated
            ):
                shutdown_requested = True

        if snapshot.operating_state is EngineOperatingState.SHUTDOWN:
            shutdown_fuel_commands.append(snapshot.allowed_fuel_command)

        if (
            snapshot.operating_state is EngineOperatingState.OFF
            and len(visited_states) > 1
        ):
            break

    assert visited_states == [
        EngineOperatingState.OFF,
        EngineOperatingState.CRANKING,
        EngineOperatingState.IGNITION,
        EngineOperatingState.IDLE,
        EngineOperatingState.RUNNING,
        EngineOperatingState.SHUTDOWN,
        EngineOperatingState.OFF,
    ]
    assert startup_completion_time_s is not None
    assert startup_completion_time_s < 10.0
    assert idle_speed_rpm is not None
    assert maximum_running_speed_rpm > idle_speed_rpm + 10_000.0
    assert egt_limiter_activated
    assert shutdown_fuel_commands
    assert all(fuel_command == 0.0 for fuel_command in shutdown_fuel_commands)
    assert coordinator.snapshot.rotor_speed_rpm <= 500.0
