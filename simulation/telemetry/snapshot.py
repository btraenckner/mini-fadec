"""Canonical typed observable state of the Mini-FADEC runtime."""

from dataclasses import dataclass
from typing import TypeAlias

from simulation.operation.engine_state import EngineOperatingState
from simulation.protection.types import (
    ProtectionDiagnosticReason,
    ProtectionLimiter,
)
from simulation.validation.sensor_validation import (
    ChannelDiagnosticReason,
    ChannelHealth,
)


TELEMETRY_SCHEMA_VERSION = "1.0"

FaultParameterValue: TypeAlias = float | str | bool | None
FaultParameters: TypeAlias = tuple[tuple[str, FaultParameterValue], ...]


@dataclass(frozen=True)
class SimulationSnapshot:
    """Complete immutable observable state of one simulation sampling instant."""

    telemetry_schema_version: str
    simulation_time_s: float
    step_index: int
    time_step_s: float
    snapshot_sequence_number: int

    startup_requested: bool
    shutdown_requested: bool
    reset_requested: bool
    fault_requested: bool
    throttle_demand: float
    latest_operator_command: str

    previous_operating_state: EngineOperatingState
    operating_state: EngineOperatingState
    state_duration_s: float
    starter_commanded: bool
    ignition_commanded: bool
    speed_control_enabled: bool
    fuel_enabled: bool

    throttle_command: float
    speed_setpoint_rpm: float
    validated_rotor_speed_rpm: float | None
    speed_error_rpm: float | None
    requested_fuel_command: float

    rotor_speed_rpm: float
    exhaust_temperature_c: float
    estimated_thrust_n: float
    estimated_fuel_flow_ml_min: float

    measured_rotor_speed_rpm: float | None
    measured_exhaust_temperature_c: float | None
    rotor_speed_measurement_error_rpm: float | None
    exhaust_temperature_measurement_error_c: float | None

    validated_exhaust_temperature_c: float | None
    rotor_speed_health: ChannelHealth
    exhaust_temperature_health: ChannelHealth
    aggregate_sensor_health: ChannelHealth
    rotor_speed_diagnostic_reason: ChannelDiagnosticReason
    exhaust_temperature_diagnostic_reason: ChannelDiagnosticReason
    rotor_speed_value_is_held: bool
    exhaust_temperature_value_is_held: bool

    rotor_speed_fault: str
    rotor_speed_fault_type: str
    rotor_speed_fault_parameters: FaultParameters
    exhaust_temperature_fault: str
    exhaust_temperature_fault_type: str
    exhaust_temperature_fault_parameters: FaultParameters

    egt_fuel_limit: float
    egt_intervention_temperature_c: float
    egt_maximum_temperature_c: float
    acceleration_fuel_limit: float
    overspeed_fuel_limit: float
    state_maximum_fuel_command: float
    deceleration_minimum_fuel_command: float
    allowed_fuel_command: float
    rotor_acceleration_rpm_per_s: float | None
    rotor_deceleration_rpm_per_s: float | None
    speed_ratio: float | None
    active_protection_limiter: ProtectionLimiter
    constraining_protection_limiters: tuple[ProtectionLimiter, ...]
    soft_overspeed_active: bool
    hard_overspeed_active: bool
    protection_hard_cutoff_active: bool
    critical_protection_fault_request: bool
    protection_arbitration_conflict: bool
    protection_diagnostic_reasons: tuple[ProtectionDiagnosticReason, ...]

    shutdown_fuel_cutoff_active: bool
    egt_limiter_active: bool
    automatic_sensor_fault_request_active: bool
    sensor_fault_response_reason: str
    fuel_cutoff_due_to_sensor_invalidity: bool

    rotor_speed_sensor_sample_period_s: float
    exhaust_temperature_sensor_sample_period_s: float
