"""Stable flat serialization for snapshots and telemetry CSV rows."""

import json
from enum import Enum
from typing import TypeAlias

from simulation.telemetry.snapshot import SimulationSnapshot


SerializedValue: TypeAlias = str | int | float | bool | None

TELEMETRY_FIELDS = (
    "telemetry_schema_version",
    "simulation_time_s",
    "step_index",
    "time_step_s",
    "snapshot_sequence_number",
    "startup_requested",
    "shutdown_requested",
    "reset_requested",
    "fault_requested",
    "throttle_demand",
    "latest_operator_command",
    "previous_operating_state",
    "operating_state",
    "state_duration_s",
    "starter_commanded",
    "ignition_commanded",
    "speed_control_enabled",
    "fuel_enabled",
    "throttle_command",
    "speed_setpoint_rpm",
    "validated_rotor_speed_rpm",
    "speed_error_rpm",
    "requested_fuel_command",
    "rotor_speed_rpm",
    "exhaust_temperature_c",
    "estimated_thrust_n",
    "estimated_fuel_flow_ml_min",
    "measured_rotor_speed_rpm",
    "measured_exhaust_temperature_c",
    "rotor_speed_measurement_error_rpm",
    "exhaust_temperature_measurement_error_c",
    "validated_exhaust_temperature_c",
    "rotor_speed_health",
    "exhaust_temperature_health",
    "aggregate_sensor_health",
    "rotor_speed_diagnostic_reason",
    "exhaust_temperature_diagnostic_reason",
    "rotor_speed_value_is_held",
    "exhaust_temperature_value_is_held",
    "rotor_speed_fault",
    "rotor_speed_fault_type",
    "rotor_speed_fault_parameters",
    "exhaust_temperature_fault",
    "exhaust_temperature_fault_type",
    "exhaust_temperature_fault_parameters",
    "egt_fuel_limit",
    "egt_intervention_temperature_c",
    "egt_maximum_temperature_c",
    "acceleration_fuel_limit",
    "overspeed_fuel_limit",
    "state_maximum_fuel_command",
    "deceleration_minimum_fuel_command",
    "allowed_fuel_command",
    "rotor_acceleration_rpm_per_s",
    "rotor_deceleration_rpm_per_s",
    "speed_ratio",
    "active_protection_limiter",
    "constraining_protection_limiters",
    "soft_overspeed_active",
    "hard_overspeed_active",
    "protection_hard_cutoff_active",
    "critical_protection_fault_request",
    "protection_arbitration_conflict",
    "protection_diagnostic_reasons",
    "shutdown_fuel_cutoff_active",
    "egt_limiter_active",
    "automatic_sensor_fault_request_active",
    "sensor_fault_response_reason",
    "fuel_cutoff_due_to_sensor_invalidity",
    "rotor_speed_sensor_sample_period_s",
    "exhaust_temperature_sensor_sample_period_s",
)


def snapshot_to_telemetry_row(
    snapshot: SimulationSnapshot,
) -> dict[str, SerializedValue]:
    """Return one flat row in the documented deterministic schema order."""

    return {
        field_name: _serialize_value(getattr(snapshot, field_name))
        for field_name in TELEMETRY_FIELDS
    }


def _serialize_value(value: object) -> SerializedValue:
    """Serialize enums and immutable tuples without losing unavailable values."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, tuple):
        return json.dumps(
            _json_compatible(value),
            ensure_ascii=False,
            separators=(",", ":"),
        )
    raise TypeError(f"unsupported telemetry value: {type(value).__name__}")


def _json_compatible(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_json_compatible(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported nested telemetry value: {type(value).__name__}")
