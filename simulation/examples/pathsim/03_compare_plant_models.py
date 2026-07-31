"""Compare structural behavior of both plants under identical inputs."""

from pathlib import Path

import matplotlib.pyplot as plt

from simulation.core.types import AmbientConditions
from simulation.examples.pathsim._commands import actuator_schedule
from simulation.plants.factory import create_engine_plant
from simulation.plants.types import PlantModelKind


def main() -> None:
    """Run an open-loop sequence through both replaceable plant backends."""

    time_step_s = 0.01
    duration_s = 20.0
    ambient = AmbientConditions()
    plants = (
        create_engine_plant(PlantModelKind.FIRST_ORDER),
        create_engine_plant(PlantModelKind.PATHSIM_GREYBOX_V1),
    )
    labels = ("First-order reference", "PathSim grey-box")
    colors = ("tab:blue", "tab:orange")
    traces: list[dict[str, list[float]]] = []

    for plant in plants:
        trace = {
            "fuel": [],
            "effective_fuel": [],
            "speed": [],
            "egt": [],
            "thrust": [],
        }
        for index in range(int(duration_s / time_step_s)):
            time_s = index * time_step_s
            command = actuator_schedule(time_s)
            outputs = plant.step(command, ambient, time_step_s)
            diagnostics = plant.get_diagnostics()
            commanded_fuel = (
                command.fuel_command if command.fuel_enabled else 0.0
            )
            trace["fuel"].append(commanded_fuel)
            trace["effective_fuel"].append(
                diagnostics.pathsim.effective_fuel
                if diagnostics.pathsim is not None
                else commanded_fuel
            )
            trace["speed"].append(plant.state.rotor_speed_rpm)
            trace["egt"].append(plant.state.exhaust_temperature_c)
            trace["thrust"].append(outputs.estimated_thrust_n)
        traces.append(trace)

    times_s = [
        (index + 1) * time_step_s
        for index in range(int(duration_s / time_step_s))
    ]
    figure, axes = plt.subplots(5, 1, sharex=True, figsize=(11, 12))
    quantities = (
        ("fuel", "Fuel command [-]"),
        ("effective_fuel", "Effective fuel [-]"),
        ("speed", "Rotor speed [rpm]"),
        ("egt", "EGT [°C]"),
        ("thrust", "Thrust [N]"),
    )
    for axis, (quantity, ylabel) in zip(axes, quantities):
        for trace, label, color in zip(traces, labels, colors):
            axis.plot(times_s, trace[quantity], label=label, color=color)
        axis.set_ylabel(ylabel)
        axis.grid(True)
    axes[1].text(
        0.01,
        0.04,
        "First-order has no fuel-lag state; its command is shown as a proxy.",
        transform=axes[1].transAxes,
        fontsize=8,
    )
    axes[0].legend(ncols=2)
    axes[-1].set_xlabel("Time [s]")
    figure.suptitle(
        "Mini-FADEC plant-model structural comparison\n"
        "The models are not expected to match; this is not an equivalence test."
    )
    figure.tight_layout()

    result_path = Path("results/pathsim/03_compare_plant_models.png")
    result_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(result_path, dpi=150)
    print("The two models are not expected to match.")
    print(f"Saved {result_path}")
    plt.show()


if __name__ == "__main__":
    main()
