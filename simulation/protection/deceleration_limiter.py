"""Normal-operation fuel decrease rate protection."""

from dataclasses import dataclass, field

from simulation.operation.engine_state import EngineOperatingState
from simulation.protection.types import DecelerationLimitResult


@dataclass(frozen=True)
class DecelerationLimiterParameters:
    """Grey-box assumptions for simplified combustion-stability protection."""

    maximum_fuel_decrease_rate_per_s: float = 0.5
    minimum_fuel_command: float = 0.0
    maximum_fuel_command: float = 1.0
    enabled_operating_states: frozenset[EngineOperatingState] = field(
        default_factory=lambda: frozenset(
            {
                EngineOperatingState.IDLE,
                EngineOperatingState.RUNNING,
            }
        )
    )

    def __post_init__(self) -> None:
        if self.maximum_fuel_decrease_rate_per_s < 0.0:
            raise ValueError("maximum fuel decrease rate cannot be negative")
        if self.minimum_fuel_command > self.maximum_fuel_command:
            raise ValueError("minimum fuel command cannot exceed maximum")


class DecelerationLimiter:
    """Produce a lower fuel bound during normal commanded deceleration."""

    def __init__(
        self,
        parameters: DecelerationLimiterParameters | None = None,
    ) -> None:
        self.parameters = parameters or DecelerationLimiterParameters()
        self._previous_final_fuel_command: float | None = None

    @property
    def previous_final_fuel_command(self) -> float | None:
        """Return the retained final command for diagnostics and testing."""

        return self._previous_final_fuel_command

    def evaluate(
        self,
        requested_fuel_command: float,
        operating_state: EngineOperatingState,
        time_step_s: float,
        *,
        bypass: bool = False,
    ) -> DecelerationLimitResult:
        """Return the current lower bound without retaining an unsafe result."""

        if time_step_s <= 0.0:
            raise ValueError("time_step_s must be greater than zero")

        requested_fuel = self._clamp(requested_fuel_command)
        if (
            bypass
            or operating_state not in self.parameters.enabled_operating_states
            or self._previous_final_fuel_command is None
        ):
            return DecelerationLimitResult(
                minimum_fuel_command=self.parameters.minimum_fuel_command,
                active=False,
            )

        minimum_fuel_command = max(
            self.parameters.minimum_fuel_command,
            self._previous_final_fuel_command
            - self.parameters.maximum_fuel_decrease_rate_per_s * time_step_s,
        )
        return DecelerationLimitResult(
            minimum_fuel_command=self._clamp(minimum_fuel_command),
            active=requested_fuel < minimum_fuel_command - 1.0e-12,
        )

    def retain_final_fuel_command(self, final_fuel_command: float) -> None:
        """Retain the manager-approved command for the next normal update."""

        self._previous_final_fuel_command = self._clamp(final_fuel_command)

    def reset(self) -> None:
        """Clear the retained command so the next update cannot be stale."""

        self._previous_final_fuel_command = None

    def _clamp(self, value: float) -> float:
        return max(
            self.parameters.minimum_fuel_command,
            min(value, self.parameters.maximum_fuel_command),
        )
