"""Print a concise summary of one recorded Mini-FADEC run."""

import argparse
import csv
import json
from collections import Counter
from pathlib import Path


def inspect_run(run_directory: Path) -> str:
    """Return a human-readable summary from persisted run artifacts."""

    metadata = _read_metadata(run_directory / "metadata.json")
    telemetry = _read_csv(run_directory / "telemetry.csv")
    events = _read_csv(run_directory / "events.csv")
    if not telemetry:
        raise ValueError("telemetry.csv contains no samples")

    first_time_s = _number(telemetry[0], "simulation_time_s")
    last_time_s = _number(telemetry[-1], "simulation_time_s")
    limiter_counts = Counter(
        row["active_protection_limiter"] for row in telemetry
    )
    critical_fault_occurred = any(
        _boolean(row.get("critical_protection_fault_request", ""))
        for row in telemetry
    ) or any(
        row.get("event_type")
        in {
            "HARD_OVERSPEED_ACTIVATED",
            "CRITICAL_PROTECTION_REQUESTED",
            "AUTOMATIC_FAULT_REQUESTED",
        }
        for row in events
    )
    final_fuel = [
        _number(row, "allowed_fuel_command") for row in telemetry
    ]
    acceleration = [
        value
        for row in telemetry
        if (
            value := _optional_number(
                row,
                "rotor_acceleration_rpm_per_s",
            )
        )
        is not None
    ]

    lines = (
        f"Run name: {metadata.get('run_name', 'unavailable')}",
        f"Duration: {last_time_s - first_time_s:.3f} s",
        f"Samples: {len(telemetry)}",
        f"Events: {len(events)}",
        f"Git commit: {metadata.get('git_commit') or 'unavailable'}",
        "Maximum true/validated RPM: "
        f"{_maximum(telemetry, 'rotor_speed_rpm'):.1f} / "
        f"{_maximum_optional(telemetry, 'validated_rotor_speed_rpm')}",
        "Maximum true/validated EGT: "
        f"{_maximum(telemetry, 'exhaust_temperature_c'):.1f} / "
        f"{_maximum_optional(telemetry, 'validated_exhaust_temperature_c')}",
        "Maximum estimated acceleration: "
        f"{max(acceleration) if acceleration else 'unavailable'}",
        f"Final fuel range: {min(final_fuel):.3f} .. {max(final_fuel):.3f}",
        "Active limiter samples: "
        + ", ".join(
            f"{limiter}={count}"
            for limiter, count in sorted(limiter_counts.items())
        ),
        f"Final engine state: {telemetry[-1]['operating_state']}",
        f"Critical fault occurred: {critical_fault_occurred}",
        f"Completion status: {metadata.get('completion_status', 'unavailable')}",
    )
    return "\n".join(lines)


def _read_metadata(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as metadata_file:
        value = json.load(metadata_file)
    if not isinstance(value, dict):
        raise ValueError("metadata.json must contain one object")
    return value


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as csv_file:
        return list(csv.DictReader(csv_file))


def _number(row: dict[str, str], field_name: str) -> float:
    return float(row[field_name])


def _optional_number(
    row: dict[str, str],
    field_name: str,
) -> float | None:
    value = row.get(field_name, "")
    return None if value == "" else float(value)


def _maximum(rows: list[dict[str, str]], field_name: str) -> float:
    return max(_number(row, field_name) for row in rows)


def _maximum_optional(
    rows: list[dict[str, str]],
    field_name: str,
) -> str:
    values = [
        value
        for row in rows
        if (value := _optional_number(row, field_name)) is not None
    ]
    return f"{max(values):.1f}" if values else "unavailable"


def _boolean(value: str) -> bool:
    return value.lower() == "true"


def main(arguments: list[str] | None = None) -> None:
    """Parse a run directory and print its offline summary."""

    parser = argparse.ArgumentParser()
    parser.add_argument("run_directory", type=Path)
    parsed_arguments = parser.parse_args(arguments)
    print(inspect_run(parsed_arguments.run_directory))


if __name__ == "__main__":
    main()
