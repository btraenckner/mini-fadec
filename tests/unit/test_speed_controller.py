"""Unit tests for rotor-speed scheduling and control."""

import pytest

from simulation.controllers.speed_controller import (
    LinearThrottleToSpeedScheduler,
    PIEngineSpeedController,
)
from simulation.core.types import ControlRequest, SensorData


@pytest.mark.parametrize(
    ("throttle_command", "expected_speed_setpoint_rpm"),
    [
        (0.0, 39_000.0),
        (1.0, 128_000.0),
        (-0.5, 39_000.0),
        (1.5, 128_000.0),
    ],
)
def test_scheduler_maps_clamped_throttle_to_speed(
    throttle_command: float,
    expected_speed_setpoint_rpm: float,
) -> None:
    scheduler = LinearThrottleToSpeedScheduler()

    speed_setpoint_rpm = scheduler.get_speed_setpoint_rpm(throttle_command)

    assert speed_setpoint_rpm == pytest.approx(expected_speed_setpoint_rpm)


@pytest.mark.parametrize("rotor_speed_rpm", [0.0, 39_000.0, 128_000.0, 200_000.0])
def test_controller_output_remains_normalized(rotor_speed_rpm: float) -> None:
    controller = PIEngineSpeedController()

    actuator_command = controller.update(
        control_request=ControlRequest(throttle_command=0.7),
        sensor_data=SensorData(
            rotor_speed_rpm=rotor_speed_rpm,
            exhaust_temperature_c=450.0,
        ),
        time_step_s=0.01,
    )

    assert 0.0 <= actuator_command.fuel_command <= 1.0


def test_controller_rejects_invalid_time_step() -> None:
    controller = PIEngineSpeedController()

    with pytest.raises(
        ValueError,
        match="time_step_s must be greater than zero",
    ):
        controller.update(
            control_request=ControlRequest(throttle_command=0.7),
            sensor_data=SensorData(
                rotor_speed_rpm=39_000.0,
                exhaust_temperature_c=450.0,
            ),
            time_step_s=0.0,
        )
