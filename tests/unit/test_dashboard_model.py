"""Unit tests for live dashboard controls and telemetry history."""

import pytest

from simulation.application.dashboard_model import (
    DashboardControls,
    DashboardFaultType,
    DashboardHistory,
    DashboardSensorFaultControls,
    DashboardSimulation,
)
from simulation.application.engine_simulation import EngineSimulationCoordinator
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


@pytest.mark.parametrize("channel", list(SensorChannel))
@pytest.mark.parametrize(
    ("fault_type", "value_text", "expected_fault"),
    [
        (DashboardFaultType.BIAS, "12.5", BiasSensorFault(offset=12.5)),
        (DashboardFaultType.STUCK, "", StuckSensorFault()),
        (DashboardFaultType.DROPOUT, "", DropoutSensorFault()),
        (
            DashboardFaultType.FORCED_VALUE,
            "650",
            ForcedValueSensorFault(value=650.0),
        ),
        (
            DashboardFaultType.EXCESSIVE_NOISE,
            "7.5",
            ExcessiveNoiseSensorFault(standard_deviation=7.5),
        ),
        (
            DashboardFaultType.DRIFT,
            "-3",
            DriftSensorFault(rate_per_second=-3.0),
        ),
    ],
)
def test_dashboard_can_inject_every_sensor_fault_on_both_channels(
    channel: SensorChannel,
    fault_type: DashboardFaultType,
    value_text: str,
    expected_fault: SensorFaultDefinition,
) -> None:
    coordinator = EngineSimulationCoordinator()
    controls = DashboardSensorFaultControls()
    controls.select_channel(channel)
    controls.select_fault_type(fault_type)
    controls.set_value_text(value_text)

    message = controls.inject(coordinator)

    assert coordinator.sensor_fault_injector.active_fault(
        channel
    ) == expected_fault
    assert message.startswith("Injected")


def test_dashboard_stuck_fault_accepts_an_explicit_value() -> None:
    coordinator = EngineSimulationCoordinator()
    controls = DashboardSensorFaultControls(
        selected_fault_type=DashboardFaultType.STUCK,
        value_text="42",
    )

    controls.inject(coordinator)

    assert coordinator.sensor_fault_injector.active_fault(
        SensorChannel.ROTOR_SPEED
    ) == StuckSensorFault(value=42.0)


@pytest.mark.parametrize("value_text", ["", "not-a-number", "nan", "inf"])
def test_dashboard_rejects_invalid_required_fault_values(
    value_text: str,
) -> None:
    controls = DashboardSensorFaultControls(value_text=value_text)

    with pytest.raises(ValueError, match="value"):
        controls.inject(EngineSimulationCoordinator())


def test_dashboard_rejects_negative_noise_standard_deviation() -> None:
    controls = DashboardSensorFaultControls(
        selected_fault_type=DashboardFaultType.EXCESSIVE_NOISE,
        value_text="-1",
    )

    with pytest.raises(ValueError, match="cannot be negative"):
        controls.inject(EngineSimulationCoordinator())


def test_dashboard_clears_selected_fault_without_clearing_other_channel() -> None:
    coordinator = EngineSimulationCoordinator()
    controls = DashboardSensorFaultControls()
    controls.inject(coordinator)
    controls.select_channel(SensorChannel.EXHAUST_TEMPERATURE)
    controls.inject(coordinator)

    message = controls.clear_selected(coordinator)

    assert coordinator.sensor_fault_injector.is_active(
        SensorChannel.ROTOR_SPEED
    )
    assert not coordinator.sensor_fault_injector.is_active(
        SensorChannel.EXHAUST_TEMPERATURE
    )
    assert "recovery in progress" in message


def test_dashboard_clears_all_sensor_faults() -> None:
    coordinator = EngineSimulationCoordinator()
    controls = DashboardSensorFaultControls()
    controls.inject(coordinator)
    controls.select_channel(SensorChannel.EXHAUST_TEMPERATURE)
    controls.inject(coordinator)

    message = controls.clear_all(coordinator)

    assert all(
        not coordinator.sensor_fault_injector.is_active(channel)
        for channel in SensorChannel
    )
    assert "recovery in progress" in message


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
    assert len(history.measured_rotor_speeds_rpm) == 2
    assert len(history.validated_rotor_speeds_rpm) == 2
    assert len(history.measured_exhaust_temperatures_c) == 2
    assert len(history.validated_exhaust_temperatures_c) == 2
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
