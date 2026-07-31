"""Validated immutable configuration for the PathSim grey-box plant."""

import math
from dataclasses import dataclass, field


def _require_finite(name: str, value: float) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")


def _require_positive(name: str, value: float) -> None:
    _require_finite(name, value)
    if value <= 0.0:
        raise ValueError(f"{name} must be greater than zero")


@dataclass(frozen=True)
class PathSimSolverConfig:
    """Deterministic fixed-step solver settings for PathSim 0.24."""

    solver_id: str = "rk4"
    fixed_step: bool = True
    internal_step_s: float | None = None
    internal_substep_count: int = 1
    absolute_tolerance: float | None = None
    relative_tolerance: float | None = None

    def __post_init__(self) -> None:
        if self.solver_id != "rk4":
            raise ValueError("Sprint 14 supports only the rk4 solver")
        if not self.fixed_step:
            raise ValueError("Sprint 14 requires fixed-step integration")
        if self.internal_step_s is not None:
            _require_positive("internal_step_s", self.internal_step_s)
        if (
            isinstance(self.internal_substep_count, bool)
            or not isinstance(self.internal_substep_count, int)
            or self.internal_substep_count <= 0
        ):
            raise ValueError("internal_substep_count must be a positive integer")
        for name, value in (
            ("absolute_tolerance", self.absolute_tolerance),
            ("relative_tolerance", self.relative_tolerance),
        ):
            if value is not None:
                _require_positive(name, value)


@dataclass(frozen=True)
class PathSimInitialConditions:
    """Initial continuous states for one plant instance."""

    effective_fuel: float = 0.0
    normalized_speed: float = 0.0
    gas_temperature_c: float | None = None

    def __post_init__(self) -> None:
        _require_finite("initial effective_fuel", self.effective_fuel)
        _require_finite("initial normalized_speed", self.normalized_speed)
        if not 0.0 <= self.effective_fuel <= 1.0:
            raise ValueError("initial effective_fuel must be between zero and one")
        if self.normalized_speed < 0.0:
            raise ValueError("initial normalized_speed must be non-negative")
        if self.gas_temperature_c is not None:
            _require_finite(
                "initial gas_temperature_c",
                self.gas_temperature_c,
            )


@dataclass(frozen=True)
class PathSimGreyBoxConfig:
    """Unvalidated development assumptions for the educational engine model."""

    fuel_time_constant_s: float = 0.15
    normalized_inertia: float = 1.0
    starter_torque_gain_per_s: float = 0.12
    turbine_torque_gain_per_s: float = 0.85
    compressor_load_gain_per_s: float = 0.55
    friction_load_gain_per_s: float = 0.04
    minimum_lightoff_speed_ratio: float = 0.08
    full_combustion_speed_ratio: float = 0.28
    ignition_effectiveness: float = 0.95
    combustion_base_temperature_rise_c: float = 350.0
    linear_fuel_temperature_gain_c: float = 1_000.0
    quadratic_fuel_temperature_gain_c: float = 300.0
    speed_temperature_cooling_gain_c: float = 100.0
    thermal_time_constant_s: float = 0.35
    maximum_speed_rpm: float = 128_000.0
    maximum_normalized_speed: float = 1.15
    maximum_thrust_n: float = 140.0
    thrust_speed_exponent: float = 2.0
    maximum_fuel_flow_ml_min: float = 480.0
    minimum_gas_temperature_c: float = -80.0
    initial_conditions: PathSimInitialConditions = field(
        default_factory=PathSimInitialConditions
    )
    solver: PathSimSolverConfig = field(default_factory=PathSimSolverConfig)

    def __post_init__(self) -> None:
        positive_values = (
            ("fuel_time_constant_s", self.fuel_time_constant_s),
            ("normalized_inertia", self.normalized_inertia),
            ("thermal_time_constant_s", self.thermal_time_constant_s),
            ("maximum_speed_rpm", self.maximum_speed_rpm),
            ("maximum_normalized_speed", self.maximum_normalized_speed),
            ("thrust_speed_exponent", self.thrust_speed_exponent),
        )
        for name, value in positive_values:
            _require_positive(name, value)
        finite_values = (
            ("starter_torque_gain_per_s", self.starter_torque_gain_per_s),
            ("turbine_torque_gain_per_s", self.turbine_torque_gain_per_s),
            ("compressor_load_gain_per_s", self.compressor_load_gain_per_s),
            ("friction_load_gain_per_s", self.friction_load_gain_per_s),
            ("ignition_effectiveness", self.ignition_effectiveness),
            (
                "combustion_base_temperature_rise_c",
                self.combustion_base_temperature_rise_c,
            ),
            (
                "linear_fuel_temperature_gain_c",
                self.linear_fuel_temperature_gain_c,
            ),
            (
                "quadratic_fuel_temperature_gain_c",
                self.quadratic_fuel_temperature_gain_c,
            ),
            (
                "speed_temperature_cooling_gain_c",
                self.speed_temperature_cooling_gain_c,
            ),
            ("maximum_thrust_n", self.maximum_thrust_n),
            ("maximum_fuel_flow_ml_min", self.maximum_fuel_flow_ml_min),
            ("minimum_gas_temperature_c", self.minimum_gas_temperature_c),
        )
        for name, value in finite_values:
            _require_finite(name, value)
        if any(value < 0.0 for _, value in finite_values[:-1]):
            raise ValueError("gain and maximum parameters must be non-negative")
        if not (
            0.0
            <= self.minimum_lightoff_speed_ratio
            < self.full_combustion_speed_ratio
            <= self.maximum_normalized_speed
        ):
            raise ValueError("combustion speed ratios must be strictly ordered")
        if not 0.0 <= self.ignition_effectiveness <= 1.0:
            raise ValueError("ignition_effectiveness must be between zero and one")
        if (
            self.initial_conditions.normalized_speed
            > self.maximum_normalized_speed
        ):
            raise ValueError(
                "initial normalized_speed exceeds maximum_normalized_speed"
            )
