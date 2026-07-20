"""Independent validated-speed soft and hard overspeed protection."""

from dataclasses import dataclass

from simulation.operation.engine_state import EngineOperatingState
from simulation.protection.types import OverspeedLimitResult


@dataclass(frozen=True)
class OverspeedLimiterParameters:
    """Grey-box assumptions derived from maximum normal operating speed."""

    maximum_normal_speed_rpm: float = 128_000.0
    soft_overspeed_ratio: float = 1.03
    hard_overspeed_ratio: float = 1.08
    minimum_fuel_limit: float = 0.0

    def __post_init__(self) -> None:
        if self.maximum_normal_speed_rpm <= 0.0:
            raise ValueError("maximum normal speed must be greater than zero")
        if self.soft_overspeed_ratio < 1.0:
            raise ValueError("soft overspeed ratio must be at least one")
        if self.hard_overspeed_ratio <= self.soft_overspeed_ratio:
            raise ValueError("hard overspeed ratio must exceed soft ratio")
        if not 0.0 <= self.minimum_fuel_limit <= 1.0:
            raise ValueError("minimum overspeed fuel limit must be in range")

    @property
    def soft_overspeed_speed_rpm(self) -> float:
        return self.maximum_normal_speed_rpm * self.soft_overspeed_ratio

    @property
    def hard_overspeed_speed_rpm(self) -> float:
        return self.maximum_normal_speed_rpm * self.hard_overspeed_ratio


class OverspeedLimiter:
    """Reduce fuel above soft overspeed and cut it at hard overspeed."""

    _ENABLED_STATES = frozenset(
        {
            EngineOperatingState.CRANKING,
            EngineOperatingState.IGNITION,
            EngineOperatingState.IDLE,
            EngineOperatingState.RUNNING,
        }
    )

    def __init__(
        self,
        parameters: OverspeedLimiterParameters | None = None,
    ) -> None:
        self.parameters = parameters or OverspeedLimiterParameters()

    def evaluate(
        self,
        requested_fuel_command: float,
        rotor_speed_rpm: float | None,
        operating_state: EngineOperatingState,
        time_step_s: float,
    ) -> OverspeedLimitResult:
        """Return the soft limit or deterministic hard-cutoff request."""

        if time_step_s <= 0.0:
            raise ValueError("time_step_s must be greater than zero")

        requested_fuel = self._clamp(requested_fuel_command, 0.0, 1.0)
        speed_ratio = (
            None
            if rotor_speed_rpm is None
            else rotor_speed_rpm / self.parameters.maximum_normal_speed_rpm
        )
        if (
            rotor_speed_rpm is None
            or operating_state not in self._ENABLED_STATES
            or rotor_speed_rpm < self.parameters.soft_overspeed_speed_rpm
        ):
            return OverspeedLimitResult(
                fuel_limit=requested_fuel,
                speed_ratio=speed_ratio,
                soft_active=False,
                hard_active=False,
                critical_fault_request=False,
            )

        if rotor_speed_rpm >= self.parameters.hard_overspeed_speed_rpm:
            return OverspeedLimitResult(
                fuel_limit=0.0,
                speed_ratio=speed_ratio,
                soft_active=True,
                hard_active=True,
                critical_fault_request=True,
            )

        intervention_fraction = (
            rotor_speed_rpm - self.parameters.soft_overspeed_speed_rpm
        ) / (
            self.parameters.hard_overspeed_speed_rpm
            - self.parameters.soft_overspeed_speed_rpm
        )
        fuel_limit = requested_fuel - intervention_fraction * (
            requested_fuel - self.parameters.minimum_fuel_limit
        )
        return OverspeedLimitResult(
            fuel_limit=self._clamp(fuel_limit, 0.0, requested_fuel),
            speed_ratio=speed_ratio,
            soft_active=True,
            hard_active=False,
            critical_fault_request=False,
        )

    def reset(self) -> None:
        """Reset nonpersistent overspeed state (currently stateless)."""

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(value, maximum))
