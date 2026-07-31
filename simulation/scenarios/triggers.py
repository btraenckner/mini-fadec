"""Simulation-time trigger definitions for scenario actions."""

from dataclasses import dataclass

from simulation.scenarios.conditions import ConditionContext, ScenarioCondition


@dataclass(frozen=True)
class AtTimeTrigger:
    """Become due when simulation time reaches or crosses a boundary."""

    time_s: float

    def __post_init__(self) -> None:
        if self.time_s < 0.0:
            raise ValueError("trigger time_s cannot be negative")

    def is_due(self, context: ConditionContext) -> bool:
        current_time_s = context.simulation_time_s
        tolerance_s = 1.0e-12 * max(1.0, abs(current_time_s), self.time_s)
        return current_time_s + tolerance_s >= self.time_s


@dataclass(frozen=True)
class WhenConditionTrigger:
    """Become due when a typed condition matches before its timeout."""

    condition: ScenarioCondition
    timeout_s: float | None = None

    def __post_init__(self) -> None:
        if self.timeout_s is not None and self.timeout_s <= 0.0:
            raise ValueError("condition timeout_s must be greater than zero")
        if not callable(getattr(self.condition, "evaluate", None)):
            raise TypeError("condition must implement evaluate")

    def is_due(self, context: ConditionContext) -> bool:
        return self.condition.evaluate(context)

    def has_timed_out(self, simulation_time_s: float) -> bool:
        if self.timeout_s is None:
            return False
        tolerance_s = 1.0e-12 * max(1.0, simulation_time_s, self.timeout_s)
        return simulation_time_s > self.timeout_s + tolerance_s


ScenarioTrigger = AtTimeTrigger | WhenConditionTrigger
