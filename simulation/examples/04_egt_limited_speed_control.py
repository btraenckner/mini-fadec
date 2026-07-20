"""Run a closed-loop speed simulation with exhaust-temperature protection."""

import matplotlib.pyplot as plt
import numpy as np

from simulation.controllers.speed_controller import (
    LinearThrottleToSpeedScheduler,
    PIEngineSpeedController,
)
from simulation.core.types import (
    ActuatorCommand,
    AmbientConditions,
    ControlRequest,
    SensorData,
)
from simulation.models.engine_model import FirstOrderEngineModel
from simulation.operation.engine_state import EngineOperatingState
from simulation.protection.protection_manager import ProtectionManager
from simulation.protection.types import (
    ProtectionContext,
)
from simulation.sensors.sensor_model import (
    ConfigurableSensorModel,
    SensorModelConfiguration,
)
from simulation.sensors.fault_injection import SensorFaultInjector
from simulation.validation.sensor_validation import (
    SensorSignalValidator,
    SensorValidationContext,
)


def throttle_command_schedule(time_s: float) -> float:
    """Return the commanded normalized throttle input."""

    if time_s < 1.0:
        return 0.0
    if time_s < 12.0:
        return 1.0

    return 0.3


def main() -> None:
    time_step_s = 0.01
    simulation_duration_s = 15.0

    engine_model = FirstOrderEngineModel.running_at_idle()
    scheduler = LinearThrottleToSpeedScheduler()
    controller = PIEngineSpeedController(scheduler=scheduler)
    protection_manager = ProtectionManager()
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
    requested_fuel_commands: list[float] = []
    protected_fuel_commands: list[float] = []
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

        requested_command = controller.update(
            control_request=control_request,
            sensor_data=sensor_data,
            time_step_s=time_step_s,
        )
        protection_result = protection_manager.apply(
            requested_fuel_command=requested_command.fuel_command,
            sensor_data=validated_data,
            context=ProtectionContext(
                operating_state=EngineOperatingState.RUNNING,
                fuel_enabled=True,
            ),
            time_step_s=time_step_s,
        )
        protected_command = ActuatorCommand(
            fuel_command=protection_result.final_fuel_command
        )
        outputs = engine_model.step(
            actuator_command=protected_command,
            ambient_conditions=ambient_conditions,
            time_step_s=time_step_s,
        )
        previous_fuel_command = protected_command.fuel_command

        throttle_commands.append(throttle_command)
        speed_setpoints_rpm.append(
            scheduler.get_speed_setpoint_rpm(throttle_command)
        )
        rotor_speeds_rpm.append(engine_model.state.rotor_speed_rpm)
        measured_rotor_speeds_rpm.append(sensor_data.rotor_speed_rpm)
        requested_fuel_commands.append(requested_command.fuel_command)
        protected_fuel_commands.append(protected_command.fuel_command)
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

    axes[2].plot(times_s, requested_fuel_commands, label="Requested")
    axes[2].plot(times_s, protected_fuel_commands, label="Protected")
    axes[2].set_ylabel("Fuel command [-]")
    axes[2].legend()
    axes[2].grid()

    axes[3].plot(times_s, exhaust_temperatures_c, label="True EGT")
    axes[3].plot(
        times_s,
        measured_exhaust_temperatures_c,
        label="Measured EGT",
    )
    axes[3].axhline(
        protection_manager.egt_limiter.parameters.intervention_exhaust_temperature_c,
        color="tab:orange",
        linestyle="--",
        label="Intervention",
    )
    axes[3].axhline(
        protection_manager.egt_limiter.parameters.maximum_exhaust_temperature_c,
        color="tab:red",
        linestyle="--",
        label="Limit",
    )
    axes[3].set_ylabel("EGT [°C]")
    axes[3].legend()
    axes[3].grid()

    axes[4].plot(times_s, estimated_thrusts_n)
    axes[4].set_xlabel("Time [s]")
    axes[4].set_ylabel("Thrust [N]")
    axes[4].grid()

    figure.suptitle("Mini-FADEC EGT-limited speed control")
    figure.tight_layout()

    figure.savefig(
        "results/04_egt_limited_speed_control.png",
        dpi=150,
    )

    plt.show()


if __name__ == "__main__":
    main()
