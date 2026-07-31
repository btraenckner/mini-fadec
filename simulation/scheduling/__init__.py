"""Deterministic multi-rate scheduling for Mini-FADEC simulation tasks."""

from simulation.scheduling.config import (
    ExecutionConvention,
    SchedulerConfig,
    SchedulingMode,
    seconds_to_ticks,
    task_from_seconds,
)
from simulation.scheduling.diagnostics import (
    SCHEDULER_SCHEMA_VERSION,
    SchedulerDiagnostics,
    TaskDiagnostics,
)
from simulation.scheduling.presets import (
    get_scheduler_preset,
    list_scheduler_presets,
    nominal_multirate,
    single_rate_reference,
    slow_controller,
    slow_sensors,
    stress_timing,
)
from simulation.scheduling.scheduler import (
    DeterministicScheduler,
    TaskExecutionContext,
)
from simulation.scheduling.task import PeriodicTaskDefinition

__all__ = [
    "SCHEDULER_SCHEMA_VERSION",
    "DeterministicScheduler",
    "ExecutionConvention",
    "PeriodicTaskDefinition",
    "SchedulerConfig",
    "SchedulerDiagnostics",
    "SchedulingMode",
    "TaskDiagnostics",
    "TaskExecutionContext",
    "get_scheduler_preset",
    "list_scheduler_presets",
    "nominal_multirate",
    "seconds_to_ticks",
    "single_rate_reference",
    "slow_controller",
    "slow_sensors",
    "stress_timing",
    "task_from_seconds",
]
