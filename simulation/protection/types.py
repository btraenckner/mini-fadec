"""Typed inputs, outputs, and diagnostics for centralized fuel protection."""

from dataclasses import dataclass
from enum import Enum

from simulation.operation.engine_state import EngineOperatingState


class ProtectionLimiter(Enum):
    """Protection sources that can determine the final fuel command."""

    NONE = "NONE"
    EGT = "EGT"
    ACCELERATION = "ACCELERATION"
    DECELERATION = "DECELERATION"
    OVERSPEED = "OVERSPEED"
    STATE = "STATE"
    SENSOR_FAULT = "SENSOR_FAULT"
    HARD_CUTOFF = "HARD_CUTOFF"


class ProtectionDiagnosticReason(Enum):
    """Typed reasons emitted by protection evaluation and arbitration."""

    NONE = "none"
    EGT_LIMITING = "EGT fuel limiting"
    ACCELERATION_LIMITING = "rotor acceleration limiting"
    DECELERATION_LIMITING = "fuel decrease rate limiting"
    SOFT_OVERSPEED = "soft overspeed intervention"
    HARD_OVERSPEED = "hard overspeed fuel cutoff"
    STATE_FUEL_LIMIT = "operating-state fuel limit"
    STATE_HARD_CUTOFF = "operating-state hard cutoff"
    SENSOR_CRITICAL_CUTOFF = "critical sensor fault fuel cutoff"
    ARBITRATION_CONFLICT = "lower fuel bound exceeds safety upper limit"


@dataclass(frozen=True)
class ProtectionContext:
    """Narrow operating context needed for fuel-protection decisions."""

    operating_state: EngineOperatingState
    fuel_enabled: bool
    sensor_critical_condition: bool = False


@dataclass(frozen=True)
class AccelerationEstimate:
    """One deterministic estimate derived from validated rotor speed."""

    acceleration_rpm_per_s: float | None
    initialized_from_previous_sample: bool


@dataclass(frozen=True)
class AccelerationLimitResult:
    """Candidate upper fuel limit from rotor-acceleration protection."""

    fuel_limit: float
    active: bool
    intervention_fraction: float


@dataclass(frozen=True)
class DecelerationLimitResult:
    """Candidate lower fuel bound from normal fuel-decrease protection."""

    minimum_fuel_command: float
    active: bool


@dataclass(frozen=True)
class OverspeedLimitResult:
    """Candidate upper fuel limit and state from overspeed protection."""

    fuel_limit: float
    speed_ratio: float | None
    soft_active: bool
    hard_active: bool
    critical_fault_request: bool


@dataclass(frozen=True)
class FuelArbitrationResult:
    """Deterministic result of combining upper, lower, and cutoff limits."""

    final_fuel_command: float
    active_limiter: ProtectionLimiter
    constraining_limiters: tuple[ProtectionLimiter, ...]
    arbitration_conflict: bool


@dataclass(frozen=True)
class FuelLimitCandidates:
    """Typed candidate limits and activation states for fuel arbitration."""

    requested_fuel_command: float
    egt_fuel_limit: float
    egt_active: bool
    acceleration_fuel_limit: float
    acceleration_active: bool
    overspeed_fuel_limit: float
    overspeed_active: bool
    deceleration_minimum_fuel_command: float
    deceleration_active: bool
    state_maximum_fuel_command: float


@dataclass(frozen=True)
class ProtectionResult:
    """Complete explainable output of centralized fuel protection."""

    requested_fuel_command: float
    final_fuel_command: float
    egt_fuel_limit: float
    acceleration_fuel_limit: float
    overspeed_fuel_limit: float
    deceleration_minimum_fuel_command: float
    state_maximum_fuel_command: float
    active_limiter: ProtectionLimiter
    constraining_limiters: tuple[ProtectionLimiter, ...]
    rotor_acceleration_rpm_per_s: float | None
    rotor_deceleration_rpm_per_s: float | None
    speed_ratio: float | None
    soft_overspeed_active: bool
    hard_overspeed_active: bool
    hard_cutoff_active: bool
    critical_protection_fault_request: bool
    arbitration_conflict: bool
    diagnostic_reasons: tuple[ProtectionDiagnosticReason, ...]
