"""Typed scheduler configuration and exact seconds-to-ticks conversion."""

import math
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from simulation.scheduling.task import PeriodicTaskDefinition


class ExecutionConvention(Enum):
    """Documented ordering convention for one logical simulation interval."""

    SAMPLE_CONTROL_THEN_INTEGRATE = "SAMPLE_CONTROL_THEN_INTEGRATE"


class SchedulingMode(Enum):
    """Logical execution pacing classification stored in run metadata."""

    UNPACED = "UNPACED"
    PACED = "PACED"


@dataclass(frozen=True)
class SchedulerConfig:
    """Immutable complete deterministic task-release configuration."""

    preset_name: str
    base_tick_s: float
    tasks: tuple[PeriodicTaskDefinition, ...]
    execution_convention: ExecutionConvention = (
        ExecutionConvention.SAMPLE_CONTROL_THEN_INTEGRATE
    )
    development_assumption: bool = True
    mandatory_regression: bool = True

    def __post_init__(self) -> None:
        if not self.preset_name.strip():
            raise ValueError("scheduler preset_name cannot be empty")
        if not math.isfinite(self.base_tick_s) or self.base_tick_s <= 0.0:
            raise ValueError("scheduler base_tick_s must be greater than zero")
        if not self.tasks:
            raise ValueError("scheduler must define at least one task")

        names = tuple(task.name for task in self.tasks)
        duplicate_names = sorted(
            {name for name in names if names.count(name) > 1}
        )
        if duplicate_names:
            raise ValueError(
                f"duplicate scheduler task name(s): {', '.join(duplicate_names)}"
            )
        priorities = tuple(task.priority for task in self.tasks)
        duplicate_priorities = sorted(
            {
                priority
                for priority in priorities
                if priorities.count(priority) > 1
            }
        )
        if duplicate_priorities:
            values = ", ".join(str(value) for value in duplicate_priorities)
            raise ValueError(f"duplicate scheduler task priority(s): {values}")

    def task(self, name: str) -> PeriodicTaskDefinition:
        """Return one task definition by stable name."""

        for task_definition in self.tasks:
            if task_definition.name == name:
                return task_definition
        raise KeyError(f"unknown scheduler task: {name}")

    def to_dict(self) -> dict[str, object]:
        """Serialize configuration in one stable documented key order."""

        return {
            "preset_name": self.preset_name,
            "base_tick_s": self.base_tick_s,
            "execution_convention": self.execution_convention.value,
            "development_assumption": self.development_assumption,
            "mandatory_regression": self.mandatory_regression,
            "tasks": [
                {
                    "name": task.name,
                    "period_ticks": task.period_ticks,
                    "period_s": task.period_ticks * self.base_tick_s,
                    "phase_offset_ticks": task.phase_offset_ticks,
                    "phase_offset_s": (
                        task.phase_offset_ticks * self.base_tick_s
                    ),
                    "priority": task.priority,
                    "enabled": task.enabled,
                }
                for task in self.tasks
            ],
        }


def seconds_to_ticks(
    duration_s: float,
    base_tick_s: float,
    *,
    field_name: str,
    allow_zero: bool = False,
) -> int:
    """Convert an exact base-tick multiple without floating-point modulo."""

    if not math.isfinite(base_tick_s) or base_tick_s <= 0.0:
        raise ValueError("scheduler base_tick_s must be greater than zero")
    minimum_duration_s = 0.0 if allow_zero else 0.0
    if (
        not math.isfinite(duration_s)
        or duration_s < minimum_duration_s
        or (not allow_zero and duration_s == 0.0)
    ):
        qualifier = "non-negative" if allow_zero else "greater than zero"
        raise ValueError(f"{field_name} must be {qualifier}")

    ratio = Decimal(str(duration_s)) / Decimal(str(base_tick_s))
    integral_ratio = ratio.to_integral_value()
    if ratio != integral_ratio:
        raise ValueError(
            f"{field_name} must be an exact integer multiple of base_tick_s"
        )
    return int(integral_ratio)


def task_from_seconds(
    *,
    name: str,
    base_tick_s: float,
    period_s: float,
    phase_offset_s: float = 0.0,
    priority: int,
    enabled: bool = True,
) -> PeriodicTaskDefinition:
    """Construct one validated task definition from timing in seconds."""

    return PeriodicTaskDefinition(
        name=name,
        period_ticks=seconds_to_ticks(
            period_s,
            base_tick_s,
            field_name=f"{name} period_s",
        ),
        phase_offset_ticks=seconds_to_ticks(
            phase_offset_s,
            base_tick_s,
            field_name=f"{name} phase_offset_s",
            allow_zero=True,
        ),
        priority=priority,
        enabled=enabled,
    )

