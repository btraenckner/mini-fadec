"""Unit tests for live dashboard controls and telemetry history."""

import pytest

from simulation.application.dashboard_model import (
    DashboardControls,
    DashboardHistory,
    DashboardSimulation,
)
from simulation.application.engine_simulation import EngineSimulationCoordinator


@pytest.mark.parametrize(
    ("requested_throttle", "expected_throttle"),
    [(-0.5, 0.0), (0.7, 0.7), (1.5, 1.0)],
)
def test_dashboard_throttle_is_clamped_and_persistent(
    requested_throttle: float,
    expected_throttle: float,
) -> None:
    controls = DashboardControls()

    controls.set_throttle(requested_throttle)

    assert controls.consume_request().throttle_command == pytest.approx(
        expected_throttle
    )
    assert controls.consume_request().throttle_command == pytest.approx(
        expected_throttle
    )


def test_dashboard_operator_requests_are_one_shot() -> None:
    controls = DashboardControls()
    controls.request_startup()
    controls.request_shutdown()
    controls.request_fault()
    controls.request_reset()

    first_request = controls.consume_request()
    second_request = controls.consume_request()

    assert first_request.startup_requested
    assert first_request.shutdown_requested
    assert first_request.fault_requested
    assert first_request.reset_requested
    assert second_request.startup_requested is False
    assert second_request.shutdown_requested is False
    assert second_request.fault_requested is False
    assert second_request.reset_requested is False


def test_dashboard_history_is_bounded() -> None:
    coordinator = EngineSimulationCoordinator()
    history = DashboardHistory(maximum_samples=2)

    history.append(coordinator.snapshot)
    history.append(coordinator.snapshot)
    history.append(coordinator.snapshot)

    assert len(history.times_s) == 2
    assert len(history.operating_states) == 2
    assert len(history.estimated_thrusts_n) == 2


def test_dashboard_simulation_advances_fixed_steps_and_records_history() -> None:
    dashboard_simulation = DashboardSimulation(time_step_s=0.01)
    dashboard_simulation.controls.request_startup()

    snapshot = dashboard_simulation.advance(elapsed_wall_time_s=0.025)

    assert snapshot.simulation_time_s == pytest.approx(0.02)
    assert len(dashboard_simulation.history.times_s) == 2
    assert snapshot.starter_commanded


def test_dashboard_simulation_rejects_negative_elapsed_time() -> None:
    dashboard_simulation = DashboardSimulation()

    with pytest.raises(
        ValueError,
        match="elapsed_wall_time_s must not be negative",
    ):
        dashboard_simulation.advance(elapsed_wall_time_s=-0.01)
