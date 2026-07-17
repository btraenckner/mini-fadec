"""Integration tests for exhaust-temperature-limited speed control."""

from simulation.controllers.speed_controller import PIEngineSpeedController
from simulation.core.types import AmbientConditions, ControlRequest, SensorData
from simulation.models.engine_model import FirstOrderEngineModel
from simulation.protection.exhaust_temperature_limiter import (
    ExhaustTemperatureLimiter,
)


def test_egt_limiter_restricts_closed_loop_fuel_command() -> None:
    engine_model = FirstOrderEngineModel()
    controller = PIEngineSpeedController()
    limiter = ExhaustTemperatureLimiter()
    ambient_conditions = AmbientConditions()
    control_request = ControlRequest(throttle_command=1.0)

    limiter_activated = False
    time_step_s = 0.01
    number_of_steps = int(10.0 / time_step_s)

    for _ in range(number_of_steps):
        sensor_data = SensorData(
            rotor_speed_rpm=engine_model.state.rotor_speed_rpm,
            exhaust_temperature_c=engine_model.state.exhaust_temperature_c,
        )
        requested_command = controller.update(
            control_request=control_request,
            sensor_data=sensor_data,
            time_step_s=time_step_s,
        )
        protected_command = limiter.apply(
            requested_command=requested_command,
            sensor_data=sensor_data,
            time_step_s=time_step_s,
        )

        assert 0.0 <= protected_command.fuel_command <= 1.0

        limiter_activated = limiter_activated or (
            protected_command.fuel_command < requested_command.fuel_command
        )

        engine_model.step(
            actuator_command=protected_command,
            ambient_conditions=ambient_conditions,
            time_step_s=time_step_s,
        )

    assert limiter_activated
    assert engine_model.state.rotor_speed_rpm > 39_000.0
    assert engine_model.state.exhaust_temperature_c <= 665.0
