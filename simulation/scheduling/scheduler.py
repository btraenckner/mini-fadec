"""Deterministic integer-tick periodic scheduler without wall-clock coupling."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from simulation.scheduling.config import SchedulerConfig, seconds_to_ticks
from simulation.scheduling.diagnostics import (
    SCHEDULER_SCHEMA_VERSION,
    SchedulerDiagnostics,
    TaskDiagnostics,
)
from simulation.scheduling.task import PeriodicTaskDefinition


@dataclass(frozen=True)
class TaskExecutionContext:
    """Immutable release information supplied to one runtime task binding."""

    task_name: str
    current_tick: int
    release_time_s: float
    execution_period_s: float


TaskBinding = Callable[[TaskExecutionContext], None]


@dataclass
class _TaskRuntimeState:
    definition: PeriodicTaskDefinition
    enabled: bool
    release_count: int = 0
    execution_count: int = 0
    last_release_tick: int | None = None
    last_execution_tick: int | None = None
    next_release_tick: int = 0
    missed_release_count: int = 0
    skipped_execution_count: int = 0


class DeterministicScheduler:
    """Release explicitly bound tasks using exact integer tick arithmetic."""

    def __init__(
        self,
        config: SchedulerConfig,
        bindings: Mapping[str, TaskBinding] | None = None,
    ) -> None:
        self.config = config
        self._bindings = dict(bindings or {})
        unknown_bindings = set(self._bindings).difference(
            task.name for task in config.tasks
        )
        if unknown_bindings:
            names = ", ".join(sorted(unknown_bindings))
            raise ValueError(f"bindings reference unknown task(s): {names}")
        self._ordered_definitions = tuple(
            sorted(config.tasks, key=lambda task: (task.priority, task.name))
        )
        self._runtime: dict[str, _TaskRuntimeState] = {}
        self._current_tick = 0
        self._last_tick_execution_order: tuple[str, ...] = ()
        self.reset()

    @property
    def current_tick(self) -> int:
        """Return the next base tick that will be processed."""

        return self._current_tick

    @property
    def current_time_s(self) -> float:
        """Derive authoritative logical time from the integer tick count."""

        return self._current_tick * self.config.base_tick_s

    @property
    def last_tick_execution_order(self) -> tuple[str, ...]:
        """Return task names executed on the most recently processed tick."""

        return self._last_tick_execution_order

    def bind(self, task_name: str, binding: TaskBinding) -> None:
        """Associate one configured definition with a runtime callable."""

        self.config.task(task_name)
        self._bindings[task_name] = binding

    def reset(self) -> None:
        """Restore tick, releases, counters, and retained diagnostics."""

        self._current_tick = 0
        self._last_tick_execution_order = ()
        self._runtime = {
            definition.name: _TaskRuntimeState(
                definition=definition,
                enabled=definition.enabled,
                next_release_tick=definition.phase_offset_ticks,
            )
            for definition in self._ordered_definitions
        }

    def step_one_tick(self) -> tuple[str, ...]:
        """Process every release on one base tick in explicit priority order."""

        executed_tasks: list[str] = []
        for definition in self._ordered_definitions:
            state = self._runtime[definition.name]
            self._account_for_missed_releases(state)
            if self._current_tick != state.next_release_tick:
                continue

            state.release_count += 1
            state.last_release_tick = self._current_tick
            state.next_release_tick += definition.period_ticks
            if not state.enabled:
                state.skipped_execution_count += 1
                continue

            binding = self._bindings.get(definition.name)
            if binding is not None:
                binding(
                    TaskExecutionContext(
                        task_name=definition.name,
                        current_tick=self._current_tick,
                        release_time_s=(
                            self._current_tick * self.config.base_tick_s
                        ),
                        execution_period_s=(
                            definition.period_ticks * self.config.base_tick_s
                        ),
                    )
                )
            state.execution_count += 1
            state.last_execution_tick = self._current_tick
            executed_tasks.append(definition.name)

        self._last_tick_execution_order = tuple(executed_tasks)
        self._current_tick += 1
        return self._last_tick_execution_order

    def run_until_tick(self, target_tick: int) -> None:
        """Process every intermediate release until target_tick is next."""

        if target_tick < self._current_tick:
            raise ValueError("target_tick cannot precede current_tick")
        while self._current_tick < target_tick:
            self.step_one_tick()

    def run_for_duration(self, duration_s: float) -> None:
        """Run an exact integer number of base ticks."""

        ticks = seconds_to_ticks(
            duration_s,
            self.config.base_tick_s,
            field_name="duration_s",
            allow_zero=True,
        )
        self.run_until_tick(self._current_tick + ticks)

    def advance_without_processing(self, number_of_ticks: int) -> None:
        """Inject skipped logical time for diagnostics and robustness tests."""

        if number_of_ticks < 0:
            raise ValueError("number_of_ticks cannot be negative")
        self._current_tick += number_of_ticks
        self._last_tick_execution_order = ()

    def set_task_enabled(self, task_name: str, enabled: bool) -> None:
        """Enable or disable a configured task without changing its releases."""

        self._runtime[task_name].enabled = enabled

    def task_diagnostics(self) -> tuple[TaskDiagnostics, ...]:
        """Return immutable task diagnostics in explicit priority order."""

        return tuple(
            self._task_diagnostics(self._runtime[definition.name])
            for definition in self._ordered_definitions
        )

    def diagnostics(self) -> SchedulerDiagnostics:
        """Return a complete defensive scheduler diagnostics snapshot."""

        tasks = self.task_diagnostics()
        return SchedulerDiagnostics(
            scheduler_schema_version=SCHEDULER_SCHEMA_VERSION,
            preset_name=self.config.preset_name,
            base_tick_s=self.config.base_tick_s,
            current_tick=self.current_tick,
            current_simulation_time_s=self.current_time_s,
            last_tick_execution_order=self.last_tick_execution_order,
            total_missed_release_count=sum(
                task.missed_release_count for task in tasks
            ),
            tasks=tasks,
        )

    def _account_for_missed_releases(
        self,
        state: _TaskRuntimeState,
    ) -> None:
        if self._current_tick <= state.next_release_tick:
            return
        missed_releases = (
            (self._current_tick - state.next_release_tick - 1)
            // state.definition.period_ticks
        ) + 1
        state.release_count += missed_releases
        state.missed_release_count += missed_releases
        state.last_release_tick = (
            state.next_release_tick
            + (missed_releases - 1) * state.definition.period_ticks
        )
        state.next_release_tick += (
            missed_releases * state.definition.period_ticks
        )

    def _task_diagnostics(
        self,
        state: _TaskRuntimeState,
    ) -> TaskDiagnostics:
        last_execution_time_s = (
            None
            if state.last_execution_tick is None
            else state.last_execution_tick * self.config.base_tick_s
        )
        return TaskDiagnostics(
            task_name=state.definition.name,
            enabled=state.enabled,
            period_ticks=state.definition.period_ticks,
            phase_offset_ticks=state.definition.phase_offset_ticks,
            priority=state.definition.priority,
            release_count=state.release_count,
            execution_count=state.execution_count,
            last_release_tick=state.last_release_tick,
            last_execution_tick=state.last_execution_tick,
            next_release_tick=state.next_release_tick,
            last_execution_simulation_time_s=last_execution_time_s,
            next_release_simulation_time_s=(
                state.next_release_tick * self.config.base_tick_s
            ),
            effective_period_s=(
                state.definition.period_ticks * self.config.base_tick_s
            ),
            missed_release_count=state.missed_release_count,
            skipped_execution_count=state.skipped_execution_count,
        )
