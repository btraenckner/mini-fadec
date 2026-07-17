"""Integration tests for closed-loop engine-speed control."""

import pytest

from simulation.controllers.speed_controller import (
    LinearThrottleToSpeedScheduler,
    PIEngineSpeedController,
)
from simulation.core.types import AmbientConditions, ControlRequest, SensorData
from simulation.models.engine_model import FirstOrderEngineModel


def test_controller_tracks_scheduled_rotor_speed() -> None:
    engine_model = FirstOrderEngineModel.running_at_idle()
    scheduler = LinearThrottleToSpeedScheduler()
    controller = PIEngineSpeedController(scheduler=scheduler)
    ambient_conditions = AmbientConditions()
    control_request = ControlRequest(throttle_command=0.7)

    initial_speed_rpm = engine_model.state.rotor_speed_rpm
    assert initial_speed_rpm == pytest.approx(39_000.0)

    time_step_s = 0.01
    number_of_steps = int(10.0 / time_step_s)

    for _ in range(number_of_steps):
        sensor_data = SensorData(
            rotor_speed_rpm=engine_model.state.rotor_speed_rpm,
            exhaust_temperature_c=engine_model.state.exhaust_temperature_c,
        )
        actuator_command = controller.update(
            control_request=control_request,
            sensor_data=sensor_data,
            time_step_s=time_step_s,
        )

        assert 0.0 <= actuator_command.fuel_command <= 1.0

        engine_model.step(
            actuator_command=actuator_command,
            ambient_conditions=ambient_conditions,
            time_step_s=time_step_s,
        )

    speed_setpoint_rpm = scheduler.get_speed_setpoint_rpm(
        control_request.throttle_command
    )

    assert engine_model.state.rotor_speed_rpm > initial_speed_rpm
    assert engine_model.state.rotor_speed_rpm == pytest.approx(
        speed_setpoint_rpm,
        rel=0.02,
    )
