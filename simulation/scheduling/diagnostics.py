"""Immutable diagnostics produced by the deterministic scheduler."""

from dataclasses import dataclass


SCHEDULER_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class TaskDiagnostics:
    """Runtime release and execution state for one periodic task."""

    task_name: str
    enabled: bool
    release_count: int
    execution_count: int
    last_release_tick: int | None
    last_execution_tick: int | None
    next_release_tick: int
    last_execution_simulation_time_s: float | None
    effective_period_s: float
    missed_release_count: int
    skipped_execution_count: int


@dataclass(frozen=True)
class SchedulerDiagnostics:
    """Defensive complete scheduler state for application clients."""

    scheduler_schema_version: str
    preset_name: str
    base_tick_s: float
    current_tick: int
    current_simulation_time_s: float
    last_tick_execution_order: tuple[str, ...]
    total_missed_release_count: int
    tasks: tuple[TaskDiagnostics, ...]

