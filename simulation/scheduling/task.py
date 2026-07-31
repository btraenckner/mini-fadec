"""Immutable periodic-task definitions for deterministic logical scheduling."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PeriodicTaskDefinition:
    """Serializable release contract for one periodic simulation task."""

    name: str
    period_ticks: int
    phase_offset_ticks: int
    priority: int
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("task name cannot be empty")
        if self.period_ticks <= 0:
            raise ValueError("task period_ticks must be greater than zero")
        if self.phase_offset_ticks < 0:
            raise ValueError("task phase_offset_ticks cannot be negative")
        if self.phase_offset_ticks >= self.period_ticks:
            raise ValueError(
                "task phase_offset_ticks must be smaller than period_ticks"
            )
        if self.priority < 0:
            raise ValueError("task priority cannot be negative")

