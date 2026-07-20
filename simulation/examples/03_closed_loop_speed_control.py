"""Run a closed-loop rotor-speed-control simulation."""

import matplotlib.pyplot as plt
import numpy as np

from simulation.controllers.speed_controller import (
    LinearThrottleToSpeedScheduler,
    PIEngineSpeedController,
)
from simulation.core.types import AmbientConditions, ControlRequest, SensorData
from simulation.models.engine_model import FirstOrderEngineModel
from simulation.operation.engine_state import EngineOperatingState
from simulation.sensors.fault_injection import SensorFaultInjector
from simulation.sensors.sensor_model import (
    ConfigurableSensorModel,
    SensorModelConfiguration,
)
from simulation.validation.sensor_validation import (
    SensorSignalValidator,
    SensorValidationContext,
)


def throttle_command_schedule(time_s: float) -> float:
    """Return the commanded normalized throttle input."""

    if time_s < 1.0:
        return 0.0
    if time_s < 6.0:
        return 0.7

    return 0.3


def main() -> None:
    time_step_s = 0.01
    simulation_duration_s = 10.0

    engine_model = FirstOrderEngineModel.running_at_idle()
    scheduler = LinearThrottleToSpeedScheduler()
    controller = PIEngineSpeedController(scheduler=scheduler)
    # Use random_seed=None to demonstrate non-reproducible measurement noise.
    sensor_model = ConfigurableSensorModel(
        configuration=SensorModelConfiguration(random_seed=0)
    )
    fault_injector = SensorFaultInjector(random_seed=0)
    sensor_validator = SensorSignalValidator()
    ambient_conditions = AmbientConditions()
    previous_fuel_command = 0.0

    times_s = np.arange(
        start=0.0,
        stop=simulation_duration_s + time_step_s,
        step=time_step_s,
    )

    throttle_commands: list[float] = []
    speed_setpoints_rpm: list[float] = []
    rotor_speeds_rpm: list[float] = []
    measured_rotor_speeds_rpm: list[float] = []
    fuel_commands: list[float] = []
    exhaust_temperatures_c: list[float] = []
    measured_exhaust_temperatures_c: list[float] = []
    estimated_thrusts_n: list[float] = []

    for time_s in times_s:
        throttle_command = throttle_command_schedule(time_s)
        control_request = ControlRequest(throttle_command=throttle_command)
        nominal_sensor_data = sensor_model.measure(
            engine_state=engine_model.state,
            time_step_s=time_step_s,
        )
        raw_sensor_data = fault_injector.apply(
            nominal_sensor_data,
            time_step_s=time_step_s,
        )
        validation_result = sensor_validator.update(
            raw_sensor_data,
            context=SensorValidationContext(
                operating_state=EngineOperatingState.RUNNING,
                fuel_enabled=True,
                fuel_command=previous_fuel_command,
                throttle_command=throttle_command,
            ),
            time_step_s=time_step_s,
        )
        validated_data = validation_result.sensor_data
        if (
            validated_data.rotor_speed_rpm is None
            or validated_data.exhaust_temperature_c is None
        ):
            raise RuntimeError("validated sensor data unavailable")
        sensor_data = SensorData(
            rotor_speed_rpm=validated_data.rotor_speed_rpm,
            exhaust_temperature_c=validated_data.exhaust_temperature_c,
        )

        actuator_command = controller.update(
            control_request=control_request,
            sensor_data=sensor_data,
            time_step_s=time_step_s,
        )
        outputs = engine_model.step(
            actuator_command=actuator_command,
            ambient_conditions=ambient_conditions,
            time_step_s=time_step_s,
        )
        previous_fuel_command = actuator_command.fuel_command

        throttle_commands.append(throttle_command)
        speed_setpoints_rpm.append(
            scheduler.get_speed_setpoint_rpm(throttle_command)
        )
        rotor_speeds_rpm.append(engine_model.state.rotor_speed_rpm)
        measured_rotor_speeds_rpm.append(sensor_data.rotor_speed_rpm)
        fuel_commands.append(actuator_command.fuel_command)
        exhaust_temperatures_c.append(
            engine_model.state.exhaust_temperature_c
        )
        measured_exhaust_temperatures_c.append(
            sensor_data.exhaust_temperature_c
        )
        estimated_thrusts_n.append(outputs.estimated_thrust_n)

    figure, axes = plt.subplots(5, 1, sharex=True)

    axes[0].plot(times_s, throttle_commands)
    axes[0].set_ylabel("Throttle [-]")
    axes[0].grid()

    axes[1].plot(times_s, speed_setpoints_rpm, label="Setpoint")
    axes[1].plot(times_s, rotor_speeds_rpm, label="True")
    axes[1].plot(times_s, measured_rotor_speeds_rpm, label="Measured")
    axes[1].set_ylabel("Rotor speed [rpm]")
    axes[1].legend()
    axes[1].grid()

    axes[2].plot(times_s, fuel_commands)
    axes[2].set_ylabel("Fuel command [-]")
    axes[2].grid()

    axes[3].plot(times_s, exhaust_temperatures_c, label="True")
    axes[3].plot(
        times_s,
        measured_exhaust_temperatures_c,
        label="Measured",
    )
    axes[3].set_ylabel("EGT [°C]")
    axes[3].legend()
    axes[3].grid()

    axes[4].plot(times_s, estimated_thrusts_n)
    axes[4].set_xlabel("Time [s]")
    axes[4].set_ylabel("Thrust [N]")
    axes[4].grid()

    figure.suptitle("Mini-FADEC closed-loop speed control")
    figure.tight_layout()

    figure.savefig(
        "results/03_closed_loop_speed_control.png",
        dpi=150,
    )

    plt.show()


if __name__ == "__main__":
    main()
