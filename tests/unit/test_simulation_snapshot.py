"""Unit tests for the canonical runtime snapshot and serializer."""

from dataclasses import fields, is_dataclass
import json

from simulation.application.engine_simulation import EngineSimulationCoordinator
from simulation.telemetry.serialization import (
    TELEMETRY_FIELDS,
    snapshot_to_telemetry_row,
)
from simulation.telemetry.snapshot import (
    TELEMETRY_SCHEMA_VERSION,
    SimulationSnapshot,
)


def test_snapshot_contains_all_mandatory_observable_groups() -> None:
    snapshot = EngineSimulationCoordinator().snapshot

    mandatory_fields = {
        "simulation_time_s",
        "step_index",
        "startup_requested",
        "operating_state",
        "speed_setpoint_rpm",
        "rotor_speed_rpm",
        "measured_rotor_speed_rpm",
        "validated_rotor_speed_rpm",
        "rotor_speed_health",
        "rotor_speed_fault_type",
        "egt_fuel_limit",
        "active_protection_limiter",
        "allowed_fuel_command",
    }

    assert mandatory_fields <= {field.name for field in fields(snapshot)}
    assert isinstance(snapshot, SimulationSnapshot)
    assert is_dataclass(snapshot)


def test_snapshot_serialization_is_stable_and_preserves_unavailable_values() -> None:
    snapshot = EngineSimulationCoordinator().snapshot

    first_row = snapshot_to_telemetry_row(snapshot)
    second_row = snapshot_to_telemetry_row(snapshot)

    assert tuple(first_row) == TELEMETRY_FIELDS
    assert tuple(first_row) == tuple(field.name for field in fields(snapshot))
    assert first_row == second_row
    assert first_row["telemetry_schema_version"] == TELEMETRY_SCHEMA_VERSION
    assert first_row["operating_state"] == "OFF"
    assert first_row["active_protection_limiter"] == "HARD_CUTOFF"
    assert first_row["speed_error_rpm"] is None
    assert first_row["rotor_acceleration_rpm_per_s"] is None


def test_snapshot_serialization_contains_only_flat_serializable_values() -> None:
    row = snapshot_to_telemetry_row(EngineSimulationCoordinator().snapshot)

    serialized = json.dumps(row, sort_keys=False)

    assert "EngineSimulationCoordinator" not in serialized
    assert "FirstOrderEngineModel" not in serialized
    assert all(
        value is None or isinstance(value, (str, int, float, bool))
        for value in row.values()
    )
