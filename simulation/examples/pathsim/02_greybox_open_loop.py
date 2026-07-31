"""Run the PathSim grey-box engine independently from the FADEC."""

from pathlib import Path

import matplotlib.pyplot as plt

from simulation.core.types import AmbientConditions
from simulation.examples.pathsim._commands import actuator_schedule
from simulation.plants.factory import create_engine_plant
from simulation.plants.types import PlantModelKind

def main() -> None:
    """Simulate twenty seconds and plot states, outputs, and torque terms."""

    time_step_s = 0.01
    number_of_steps = int(20.0 / time_step_s)
    plant = create_engine_plant(PlantModelKind.PATHSIM_GREYBOX_V1)
    ambient = AmbientConditions()

    times_s: list[float] = []
    fuel_commands: list[float] = []
    starter_commands: list[float] = []
    ignition_commands: list[float] = []
    effective_fuel: list[float] = []
    rotor_speeds_rpm: list[float] = []
    temperatures_c: list[float] = []
    thrusts_n: list[float] = []
    starter_torque: list[float] = []
    turbine_torque: list[float] = []
    compressor_load: list[float] = []
    friction_load: list[float] = []

    for index in range(number_of_steps):
        time_s = index * time_step_s
        command = actuator_schedule(time_s)
        outputs = plant.step(command, ambient, time_step_s)
        diagnostics = plant.get_diagnostics().pathsim
        assert diagnostics is not None

        times_s.append(time_s + time_step_s)
        fuel_commands.append(command.fuel_command if command.fuel_enabled else 0.0)
        starter_commands.append(float(command.starter_commanded))
        ignition_commands.append(float(command.ignition_commanded))
        effective_fuel.append(diagnostics.effective_fuel)
        rotor_speeds_rpm.append(plant.state.rotor_speed_rpm)
        temperatures_c.append(plant.state.exhaust_temperature_c)
        thrusts_n.append(outputs.estimated_thrust_n)
        starter_torque.append(diagnostics.starter_torque)
        turbine_torque.append(diagnostics.turbine_torque)
        compressor_load.append(diagnostics.compressor_load)
        friction_load.append(diagnostics.friction_load)

    figure, axes = plt.subplots(6, 1, sharex=True, figsize=(11, 13))
    axes[0].plot(times_s, fuel_commands, label="Fuel")
    axes[0].plot(times_s, starter_commands, label="Starter")
    axes[0].plot(times_s, ignition_commands, label="Ignition")
    axes[0].set_ylabel("Commands [-]")
    axes[0].legend(ncols=3)
    axes[1].plot(times_s, fuel_commands, label="Commanded")
    axes[1].plot(times_s, effective_fuel, label="Effective")
    axes[1].set_ylabel("Fuel [-]")
    axes[1].legend()
    axes[2].plot(times_s, rotor_speeds_rpm)
    axes[2].set_ylabel("Speed [rpm]")
    axes[3].plot(times_s, temperatures_c)
    axes[3].set_ylabel("EGT [°C]")
    axes[4].plot(times_s, thrusts_n)
    axes[4].set_ylabel("Thrust [N]")
    axes[5].plot(times_s, starter_torque, label="Starter")
    axes[5].plot(times_s, turbine_torque, label="Turbine")
    axes[5].plot(times_s, compressor_load, label="Compressor")
    axes[5].plot(times_s, friction_load, label="Friction")
    axes[5].set_ylabel("Effective\ntorque [1/s]")
    axes[5].set_xlabel("Time [s]")
    axes[5].legend(ncols=4)
    for axis in axes:
        axis.grid(True)
    figure.suptitle(
        "PathSim nonlinear grey-box open loop\n"
        "unvalidated development assumptions"
    )
    figure.tight_layout()

    result_path = Path("results/pathsim/02_greybox_open_loop.png")
    result_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(result_path, dpi=150)
    print(f"Saved {result_path}")
    plt.show()


if __name__ == "__main__":
    main()
