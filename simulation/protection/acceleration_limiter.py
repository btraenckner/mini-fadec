"""Validated-speed acceleration estimation and fuel limiting."""

from dataclasses import dataclass, field

from simulation.operation.engine_state import EngineOperatingState
from simulation.protection.types import (
    AccelerationEstimate,
    AccelerationLimitResult,
)


@dataclass(frozen=True)
class RotorAccelerationEstimatorParameters:
    """Configuration for the deterministic acceleration estimate."""

    # Initial grey-box assumption; this is not a validated sensor filter.
    filter_time_constant_s: float = 0.05

    def __post_init__(self) -> None:
        if self.filter_time_constant_s < 0.0:
            raise ValueError("filter_time_constant_s cannot be negative")


class RotorAccelerationEstimator:
    """Estimate filtered acceleration from validated rotor-speed samples."""

    def __init__(
        self,
        parameters: RotorAccelerationEstimatorParameters | None = None,
    ) -> None:
        self.parameters = parameters or RotorAccelerationEstimatorParameters()
        self._previous_speed_rpm: float | None = None
        self._elapsed_since_valid_sample_s = 0.0
        self._filtered_acceleration_rpm_per_s = 0.0

    def update(
        self,
        rotor_speed_rpm: float | None,
        time_step_s: float,
    ) -> AccelerationEstimate:
        """Update the estimate without creating a first-sample spike."""

        if time_step_s <= 0.0:
            raise ValueError("time_step_s must be greater than zero")

        self._elapsed_since_valid_sample_s += time_step_s
        if rotor_speed_rpm is None:
            return AccelerationEstimate(
                acceleration_rpm_per_s=None,
                initialized_from_previous_sample=False,
            )

        if self._previous_speed_rpm is None:
            self._previous_speed_rpm = rotor_speed_rpm
            self._elapsed_since_valid_sample_s = 0.0
            self._filtered_acceleration_rpm_per_s = 0.0
            return AccelerationEstimate(
                acceleration_rpm_per_s=0.0,
                initialized_from_previous_sample=False,
            )

        sample_interval_s = max(
            self._elapsed_since_valid_sample_s,
            time_step_s,
        )
        raw_acceleration_rpm_per_s = (
            rotor_speed_rpm - self._previous_speed_rpm
        ) / sample_interval_s
        time_constant_s = self.parameters.filter_time_constant_s
        filter_fraction = (
            1.0
            if time_constant_s == 0.0
            else sample_interval_s / (time_constant_s + sample_interval_s)
        )
        self._filtered_acceleration_rpm_per_s += filter_fraction * (
            raw_acceleration_rpm_per_s
            - self._filtered_acceleration_rpm_per_s
        )
        self._previous_speed_rpm = rotor_speed_rpm
        self._elapsed_since_valid_sample_s = 0.0
        return AccelerationEstimate(
            acceleration_rpm_per_s=self._filtered_acceleration_rpm_per_s,
            initialized_from_previous_sample=True,
        )

    def reset(self) -> None:
        """Clear retained speed, timing, and filtered acceleration."""

        self._previous_speed_rpm = None
        self._elapsed_since_valid_sample_s = 0.0
        self._filtered_acceleration_rpm_per_s = 0.0


@dataclass(frozen=True)
class AccelerationLimiterParameters:
    """Grey-box assumptions for rotor-acceleration fuel protection."""

    soft_acceleration_limit_rpm_per_s: float = 12_000.0
    hard_acceleration_limit_rpm_per_s: float = 20_000.0
    minimum_acceleration_fuel_limit: float = 0.0
    # Release is deliberately slower than intervention to avoid limit cycling.
    maximum_fuel_limit_increase_rate_per_s: float = 1.0
    enabled_operating_states: frozenset[EngineOperatingState] = field(
        default_factory=lambda: frozenset(
            {
                EngineOperatingState.IDLE,
                EngineOperatingState.RUNNING,
            }
        )
    )

    def __post_init__(self) -> None:
        if self.soft_acceleration_limit_rpm_per_s < 0.0:
            raise ValueError("soft acceleration limit cannot be negative")
        if (
            self.hard_acceleration_limit_rpm_per_s
            <= self.soft_acceleration_limit_rpm_per_s
        ):
            raise ValueError("hard acceleration limit must exceed soft limit")
        if not 0.0 <= self.minimum_acceleration_fuel_limit <= 1.0:
            raise ValueError("minimum acceleration fuel limit must be in range")
        if self.maximum_fuel_limit_increase_rate_per_s <= 0.0:
            raise ValueError("fuel limit increase rate must be greater than zero")


class AccelerationLimiter:
    """Progressively restrict fuel during excessive validated acceleration."""

    def __init__(
        self,
        parameters: AccelerationLimiterParameters | None = None,
    ) -> None:
        self.parameters = parameters or AccelerationLimiterParameters()
        self._retained_fuel_limit: float | None = None

    def evaluate(
        self,
        requested_fuel_command: float,
        acceleration_estimate: AccelerationEstimate,
        operating_state: EngineOperatingState,
        time_step_s: float,
    ) -> AccelerationLimitResult:
        """Return a monotonic upper fuel limit for the current acceleration."""

        if time_step_s <= 0.0:
            raise ValueError("time_step_s must be greater than zero")

        requested_fuel = self._clamp(requested_fuel_command, 0.0, 1.0)
        acceleration = acceleration_estimate.acceleration_rpm_per_s
        if (
            operating_state not in self.parameters.enabled_operating_states
            or acceleration is None
            or not acceleration_estimate.initialized_from_previous_sample
        ):
            self.reset()
            return AccelerationLimitResult(
                fuel_limit=requested_fuel,
                active=False,
                intervention_fraction=0.0,
            )

        intervention_fraction = self._clamp(
            (
                acceleration
                - self.parameters.soft_acceleration_limit_rpm_per_s
            )
            / (
                self.parameters.hard_acceleration_limit_rpm_per_s
                - self.parameters.soft_acceleration_limit_rpm_per_s
            ),
            0.0,
            1.0,
        )
        target_fuel_limit = requested_fuel - intervention_fraction * (
            requested_fuel
            - self.parameters.minimum_acceleration_fuel_limit
        )
        target_fuel_limit = self._clamp(
            target_fuel_limit,
            0.0,
            requested_fuel,
        )
        if (
            intervention_fraction == 0.0
            and (
                self._retained_fuel_limit is None
                or self._retained_fuel_limit >= requested_fuel - 1.0e-12
            )
        ):
            self._retained_fuel_limit = None
            return AccelerationLimitResult(
                fuel_limit=requested_fuel,
                active=False,
                intervention_fraction=0.0,
            )

        if self._retained_fuel_limit is None:
            fuel_limit = target_fuel_limit
        elif target_fuel_limit <= self._retained_fuel_limit:
            fuel_limit = target_fuel_limit
        else:
            fuel_limit = min(
                target_fuel_limit,
                self._retained_fuel_limit
                + self.parameters.maximum_fuel_limit_increase_rate_per_s
                * time_step_s,
        )
        fuel_limit = self._clamp(fuel_limit, 0.0, requested_fuel)
        active = fuel_limit < requested_fuel - 1.0e-12
        self._retained_fuel_limit = fuel_limit if active else None
        return AccelerationLimitResult(
            fuel_limit=fuel_limit,
            active=active,
            intervention_fraction=intervention_fraction,
        )

    def reset(self) -> None:
        """Clear the retained limit used for deterministic gradual release."""

        self._retained_fuel_limit = None

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(value, maximum))
