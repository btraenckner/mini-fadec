"""Run an open-loop fuel-command step on the engine model."""

import matplotlib.pyplot as plt
import numpy as np

from simulation.core.types import ActuatorCommand, AmbientConditions
from simulation.models.engine_model import FirstOrderEngineModel


def fuel_command_schedule(time_s: float) -> float:
    """Return the commanded normalized fuel input."""

    if time_s < 1.0:
        return 0.0

    return 1.0


def main() -> None:
    time_step_s = 0.01
    simulation_duration_s = 6.0

    engine_model = FirstOrderEngineModel()
    ambient_conditions = AmbientConditions()

    times_s = np.arange(
        start=0.0,
        stop=simulation_duration_s + time_step_s,
        step=time_step_s,
    )

    rotor_speeds_rpm: list[float] = []
    fuel_commands: list[float] = []
    estimated_thrusts_n: list[float] = []

    for time_s in times_s:
        fuel_command = fuel_command_schedule(time_s)

        outputs = engine_model.step(
            actuator_command=ActuatorCommand(
                fuel_command=fuel_command,
            ),
            ambient_conditions=ambient_conditions,
            time_step_s=time_step_s,
        )

        rotor_speeds_rpm.append(engine_model.state.rotor_speed_rpm)
        fuel_commands.append(fuel_command)
        estimated_thrusts_n.append(outputs.estimated_thrust_n)

    figure, axes = plt.subplots(3, 1, sharex=True)

    axes[0].plot(times_s, fuel_commands)
    axes[0].set_ylabel("Fuel command [-]")
    axes[0].grid()

    axes[1].plot(times_s, rotor_speeds_rpm)
    axes[1].set_ylabel("Rotor speed [rpm]")
    axes[1].grid()

    axes[2].plot(times_s, estimated_thrusts_n)
    axes[2].set_xlabel("Time [s]")
    axes[2].set_ylabel("Thrust [N]")
    axes[2].grid()

    figure.suptitle("Mini-FADEC open-loop engine response")
    figure.tight_layout()

    plt.show()


if __name__ == "__main__":
    main()
