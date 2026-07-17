"""Unit tests for coordinated engine-simulation telemetry."""

import pytest

from simulation.application.engine_simulation import EngineSimulationCoordinator
from simulation.operation.engine_state import EngineOperatingState
from simulation.operation.state_machine import EngineOperationRequest


def test_initial_snapshot_contains_safe_dashboard_telemetry() -> None:
    snapshot = EngineSimulationCoordinator().snapshot

    assert snapshot.operating_state is EngineOperatingState.OFF
    assert snapshot.speed_setpoint_rpm == pytest.approx(0.0)
    assert snapshot.estimated_thrust_n == pytest.approx(0.0)
    assert snapshot.estimated_fuel_flow_ml_min == pytest.approx(0.0)


def test_running_snapshot_contains_setpoint_and_engine_outputs() -> None:
    coordinator = EngineSimulationCoordinator()
    time_step_s = 0.01
    startup_requested = True

    for _ in range(int(10.0 / time_step_s)):
        snapshot = coordinator.step(
            request=EngineOperationRequest(
                startup_requested=startup_requested,
            ),
            time_step_s=time_step_s,
        )
        startup_requested = False
        if snapshot.operating_state is EngineOperatingState.IDLE:
            break

    snapshot = coordinator.step(
        request=EngineOperationRequest(throttle_command=0.5),
        time_step_s=time_step_s,
    )

    assert snapshot.operating_state is EngineOperatingState.RUNNING
    assert snapshot.speed_setpoint_rpm == pytest.approx(83_500.0)
    assert snapshot.estimated_thrust_n > 0.0
    assert snapshot.estimated_fuel_flow_ml_min > 0.0
