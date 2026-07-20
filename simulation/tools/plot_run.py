"""Plot persisted telemetry without coupling plotting to simulation timing."""

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.axes import Axes


def plot_run(run_directory: Path, output_path: Path | None = None) -> None:
    """Create a seven-panel diagnostic plot from one telemetry CSV."""

    telemetry = _read_telemetry(run_directory / "telemetry.csv")
    if not telemetry:
        raise ValueError("telemetry.csv contains no samples")

    times_s = _numbers(telemetry, "simulation_time_s")
    figure, axes = plt.subplots(7, 1, figsize=(13, 18), sharex=True)
    _plot_speed(axes[0], times_s, telemetry)
    _plot_egt(axes[1], times_s, telemetry)
    _plot_fuel(axes[2], times_s, telemetry)
    _plot_limits(axes[3], times_s, telemetry)
    axes[4].plot(
        times_s,
        _optional_numbers(telemetry, "rotor_acceleration_rpm_per_s"),
    )
    axes[4].set_ylabel("Acceleration\n[rpm/s]")
    _plot_categories(
        axes[5],
        times_s,
        [row["aggregate_sensor_health"] for row in telemetry],
        "Sensor health",
    )
    _plot_categories(
        axes[6],
        times_s,
        [row["active_protection_limiter"] for row in telemetry],
        "Active limiter",
    )
    axes[6].set_xlabel("Simulation time [s]")
    for axis in axes:
        axis.grid(alpha=0.3)
    figure.suptitle(run_directory.name)
    figure.tight_layout()
    if output_path is None:
        plt.show()
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(output_path, dpi=150)
        plt.close(figure)


def _plot_speed(
    axis: Axes,
    times_s: list[float],
    telemetry: list[dict[str, str]],
) -> None:
    axis.plot(times_s, _numbers(telemetry, "rotor_speed_rpm"), label="True")
    axis.plot(
        times_s,
        _numbers(telemetry, "speed_setpoint_rpm"),
        label="Setpoint",
    )
    axis.set_ylabel("Speed [rpm]")
    axis.legend()


def _plot_egt(
    axis: Axes,
    times_s: list[float],
    telemetry: list[dict[str, str]],
) -> None:
    axis.plot(
        times_s,
        _numbers(telemetry, "exhaust_temperature_c"),
        label="True",
    )
    axis.plot(
        times_s,
        _optional_numbers(telemetry, "measured_exhaust_temperature_c"),
        label="Raw",
    )
    axis.plot(
        times_s,
        _optional_numbers(telemetry, "validated_exhaust_temperature_c"),
        label="Validated",
    )
    axis.set_ylabel("EGT [°C]")
    axis.legend()


def _plot_fuel(
    axis: Axes,
    times_s: list[float],
    telemetry: list[dict[str, str]],
) -> None:
    axis.plot(
        times_s,
        _numbers(telemetry, "requested_fuel_command"),
        label="Requested",
    )
    axis.plot(
        times_s,
        _numbers(telemetry, "allowed_fuel_command"),
        label="Final",
    )
    axis.set_ylabel("Fuel [normalized]")
    axis.legend()


def _plot_limits(
    axis: Axes,
    times_s: list[float],
    telemetry: list[dict[str, str]],
) -> None:
    fields = (
        "egt_fuel_limit",
        "acceleration_fuel_limit",
        "overspeed_fuel_limit",
        "state_maximum_fuel_command",
        "deceleration_minimum_fuel_command",
    )
    for field_name in fields:
        axis.plot(times_s, _numbers(telemetry, field_name), label=field_name)
    axis.set_ylabel("Fuel limits")
    axis.legend(ncol=2, fontsize="small")


def _plot_categories(
    axis: Axes,
    times_s: list[float],
    values: list[str],
    label: str,
) -> None:
    categories = tuple(dict.fromkeys(values))
    category_numbers = {
        category: index for index, category in enumerate(categories)
    }
    axis.step(
        times_s,
        [category_numbers[value] for value in values],
        where="post",
    )
    axis.set_yticks(range(len(categories)), categories)
    axis.set_ylabel(label)


def _read_telemetry(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as telemetry_file:
        return list(csv.DictReader(telemetry_file))


def _numbers(rows: list[dict[str, str]], field_name: str) -> list[float]:
    return [float(row[field_name]) for row in rows]


def _optional_numbers(
    rows: list[dict[str, str]],
    field_name: str,
) -> list[float]:
    return [
        float(row[field_name]) if row[field_name] else float("nan")
        for row in rows
    ]


def main(arguments: list[str] | None = None) -> None:
    """Parse command-line paths and plot one recorded run."""

    parser = argparse.ArgumentParser()
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("--output", type=Path)
    parsed_arguments = parser.parse_args(arguments)
    plot_run(parsed_arguments.run_directory, parsed_arguments.output)


if __name__ == "__main__":
    main()
