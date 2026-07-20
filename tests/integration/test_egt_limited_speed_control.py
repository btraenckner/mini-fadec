"""Integration tests for exhaust-temperature-limited speed control."""

from simulation.controllers.speed_controller import PIEngineSpeedController
from simulation.core.types import AmbientConditions, ControlRequest, SensorData
from simulation.models.engine_model import FirstOrderEngineModel
from simulation.operation.engine_state import EngineOperatingState
from simulation.protection.exhaust_temperature_limiter import (
    ExhaustTemperatureLimiter,
)
from simulation.sensors.fault_injection import SensorFaultInjector
from simulation.sensors.sensor_model import ConfigurableSensorModel
from simulation.validation.sensor_validation import (
    SensorSignalValidator,
    SensorValidationContext,
)


def test_egt_limiter_restricts_closed_loop_fuel_command() -> None:
    engine_model = FirstOrderEngineModel.running_at_idle()
    controller = PIEngineSpeedController()
    limiter = ExhaustTemperatureLimiter()
    sensor_model = ConfigurableSensorModel()
    fault_injector = SensorFaultInjector()
    sensor_validator = SensorSignalValidator()
    ambient_conditions = AmbientConditions()
    control_request = ControlRequest(throttle_command=1.0)

    requested_fuel_commands: list[float] = []
    protected_fuel_commands: list[float] = []
    rotor_speeds_rpm: list[float] = []
    exhaust_temperatures_c: list[float] = []
    time_step_s = 0.01
    number_of_steps = int(15.0 / time_step_s)
    previous_fuel_command = 0.0

    for _ in range(number_of_steps):
        nominal_sensor_data = sensor_model.measure(
            engine_state=engine_model.state,
            time_step_s=time_step_s,
        )
        raw_sensor_data = fault_injector.apply(
            nominal_sensor_data,
            time_step_s=time_step_s,
        )
        validated_data = sensor_validator.update(
            raw_sensor_data,
            context=SensorValidationContext(
                operating_state=EngineOperatingState.RUNNING,
                fuel_enabled=True,
                fuel_command=previous_fuel_command,
                throttle_command=control_request.throttle_command,
            ),
            time_step_s=time_step_s,
        ).sensor_data
        assert validated_data.rotor_speed_rpm is not None
        assert validated_data.exhaust_temperature_c is not None
        sensor_data = SensorData(
            rotor_speed_rpm=validated_data.rotor_speed_rpm,
            exhaust_temperature_c=validated_data.exhaust_temperature_c,
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

        engine_model.step(
            actuator_command=protected_command,
            ambient_conditions=ambient_conditions,
            time_step_s=time_step_s,
        )
        previous_fuel_command = protected_command.fuel_command

        requested_fuel_commands.append(requested_command.fuel_command)
        protected_fuel_commands.append(protected_command.fuel_command)
        rotor_speeds_rpm.append(engine_model.state.rotor_speed_rpm)
        exhaust_temperatures_c.append(
            engine_model.state.exhaust_temperature_c
        )

    limited_step_indices = [
        index
        for index, (requested_fuel, protected_fuel) in enumerate(
            zip(requested_fuel_commands, protected_fuel_commands)
        )
        if protected_fuel < requested_fuel
    ]

    assert limited_step_indices
    first_limited_step = limited_step_indices[0]
    minimum_protected_fuel = min(protected_fuel_commands)

    assert first_limited_step * time_step_s < 2.0
    assert rotor_speeds_rpm[-1] > rotor_speeds_rpm[first_limited_step]
    assert protected_fuel_commands[-1] > minimum_protected_fuel + 0.2
    assert rotor_speeds_rpm[-1] >= 0.98 * 128_000.0
    assert exhaust_temperatures_c[-1] <= (
        limiter.parameters.maximum_exhaust_temperature_c + 2.0
    )
