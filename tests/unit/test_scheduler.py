"""Unit tests for deterministic integer-tick scheduling contracts."""

from dataclasses import FrozenInstanceError

import pytest

from simulation.scheduling.config import (
    SchedulerConfig,
    seconds_to_ticks,
    task_from_seconds,
)
from simulation.scheduling.presets import (
    get_scheduler_preset,
    list_scheduler_presets,
    nominal_multirate,
)
from simulation.scheduling.scheduler import (
    DeterministicScheduler,
    TaskExecutionContext,
)
from simulation.scheduling.task import PeriodicTaskDefinition


def _config(
    *tasks: PeriodicTaskDefinition,
    base_tick_s: float = 0.001,
) -> SchedulerConfig:
    return SchedulerConfig(
        preset_name="test",
        base_tick_s=base_tick_s,
        tasks=tasks
        or (
            PeriodicTaskDefinition(
                name="task",
                period_ticks=1,
                phase_offset_ticks=0,
                priority=10,
            ),
        ),
    )


def test_valid_configuration_and_stable_serialization() -> None:
    config = nominal_multirate()

    payload = config.to_dict()

    assert payload["preset_name"] == "nominal-multirate"
    assert payload["base_tick_s"] == pytest.approx(0.001)
    assert tuple(payload) == (
        "preset_name",
        "base_tick_s",
        "execution_convention",
        "development_assumption",
        "mandatory_regression",
        "tasks",
    )
    assert payload["tasks"][0]["name"] == "command"  # type: ignore[index]


@pytest.mark.parametrize("base_tick_s", [0.0, -0.001])
def test_configuration_rejects_non_positive_base_tick(
    base_tick_s: float,
) -> None:
    with pytest.raises(ValueError, match="base_tick_s"):
        _config(base_tick_s=base_tick_s)


@pytest.mark.parametrize("period_ticks", [0, -1])
def test_task_rejects_non_positive_period(period_ticks: int) -> None:
    with pytest.raises(ValueError, match="period_ticks"):
        PeriodicTaskDefinition(
            name="invalid",
            period_ticks=period_ticks,
            phase_offset_ticks=0,
            priority=1,
        )


def test_seconds_conversion_rejects_non_integral_period_and_phase() -> None:
    with pytest.raises(ValueError, match="integer multiple"):
        seconds_to_ticks(
            0.0015,
            0.001,
            field_name="period_s",
        )
    with pytest.raises(ValueError, match="integer multiple"):
        task_from_seconds(
            name="phase",
            base_tick_s=0.001,
            period_s=0.005,
            phase_offset_s=0.0015,
            priority=1,
        )


def test_task_rejects_phase_outside_period() -> None:
    with pytest.raises(ValueError, match="smaller"):
        PeriodicTaskDefinition(
            name="invalid",
            period_ticks=5,
            phase_offset_ticks=5,
            priority=1,
        )


def test_configuration_rejects_duplicate_names_and_priorities() -> None:
    task = PeriodicTaskDefinition("same", 1, 0, 1)
    with pytest.raises(ValueError, match="name"):
        _config(task, task)

    with pytest.raises(ValueError, match="priority"):
        _config(
            task,
            PeriodicTaskDefinition("different", 2, 0, 1),
        )


def test_presets_are_independent_immutable_configurations() -> None:
    first = get_scheduler_preset("nominal-multirate")
    second = get_scheduler_preset("nominal-multirate")

    assert first == second
    assert first is not second
    assert len(list_scheduler_presets()) == 5
    with pytest.raises(FrozenInstanceError):
        first.base_tick_s = 1.0  # type: ignore[misc]


def test_task_releases_at_tick_zero_and_exact_periodic_ticks() -> None:
    releases: list[int] = []
    scheduler = DeterministicScheduler(
        _config(PeriodicTaskDefinition("sample", 3, 0, 1)),
        {"sample": lambda context: releases.append(context.current_tick)},
    )

    scheduler.run_until_tick(10)

    assert releases == [0, 3, 6, 9]
    diagnostics = scheduler.task_diagnostics()[0]
    assert diagnostics.release_count == 4
    assert diagnostics.execution_count == 4
    assert diagnostics.next_release_tick == 12


def test_non_zero_phase_releases_at_exact_ticks_and_holds_between() -> None:
    releases: list[int] = []
    scheduler = DeterministicScheduler(
        _config(PeriodicTaskDefinition("sample", 4, 2, 1)),
        {"sample": lambda context: releases.append(context.current_tick)},
    )

    scheduler.run_until_tick(11)

    assert releases == [2, 6, 10]


def test_simultaneous_tasks_execute_by_explicit_priority() -> None:
    order: list[str] = []
    scheduler = DeterministicScheduler(
        _config(
            PeriodicTaskDefinition("last", 1, 0, 20),
            PeriodicTaskDefinition("first", 1, 0, 10),
        ),
        {
            "last": lambda context: order.append(context.task_name),
            "first": lambda context: order.append(context.task_name),
        },
    )

    execution_order = scheduler.step_one_tick()

    assert execution_order == ("first", "last")
    assert order == ["first", "last"]


def test_disabled_task_skips_execution_and_can_be_enabled() -> None:
    releases: list[int] = []
    scheduler = DeterministicScheduler(
        _config(
            PeriodicTaskDefinition(
                "task",
                2,
                0,
                1,
                enabled=False,
            )
        ),
        {"task": lambda context: releases.append(context.current_tick)},
    )

    scheduler.run_until_tick(3)
    scheduler.set_task_enabled("task", True)
    scheduler.run_until_tick(5)

    assert releases == [4]
    diagnostics = scheduler.task_diagnostics()[0]
    assert diagnostics.release_count == 3
    assert diagnostics.execution_count == 1
    assert diagnostics.skipped_execution_count == 2


def test_reset_restores_tick_zero_release_and_diagnostics() -> None:
    releases: list[int] = []
    scheduler = DeterministicScheduler(
        _config(PeriodicTaskDefinition("task", 2, 0, 1)),
        {"task": lambda context: releases.append(context.current_tick)},
    )
    scheduler.run_until_tick(5)

    scheduler.reset()
    diagnostics = scheduler.diagnostics()
    scheduler.step_one_tick()

    assert diagnostics.current_tick == 0
    assert diagnostics.tasks[0].execution_count == 0
    assert releases == [0, 2, 4, 0]


def test_long_integer_run_has_no_release_drift() -> None:
    scheduler = DeterministicScheduler(
        _config(PeriodicTaskDefinition("task", 7, 0, 1))
    )

    scheduler.run_until_tick(100_000)

    diagnostics = scheduler.task_diagnostics()[0]
    assert diagnostics.execution_count == 14_286
    assert diagnostics.last_execution_tick == 99_995
    assert diagnostics.next_release_tick == 100_002
    assert diagnostics.missed_release_count == 0
    assert scheduler.current_time_s == pytest.approx(100.0)


def test_deliberate_tick_skip_is_the_only_normal_missed_release_source() -> None:
    scheduler = DeterministicScheduler(
        _config(PeriodicTaskDefinition("task", 2, 0, 1))
    )
    scheduler.step_one_tick()

    scheduler.advance_without_processing(5)
    scheduler.step_one_tick()

    diagnostics = scheduler.task_diagnostics()[0]
    assert diagnostics.missed_release_count == 2
    assert diagnostics.execution_count == 2
    assert scheduler.diagnostics().total_missed_release_count == 2


def test_task_receives_its_effective_period_contract() -> None:
    contexts: list[TaskExecutionContext] = []
    scheduler = DeterministicScheduler(
        _config(PeriodicTaskDefinition("task", 5, 0, 1)),
        {"task": contexts.append},
    )

    scheduler.step_one_tick()

    assert contexts[0].release_time_s == pytest.approx(0.0)
    assert contexts[0].execution_period_s == pytest.approx(0.005)
    assert scheduler.task_diagnostics()[0].effective_period_s == pytest.approx(
        0.005
    )


def test_diagnostics_are_immutable_defensive_snapshots() -> None:
    scheduler = DeterministicScheduler(_config())
    diagnostics = scheduler.diagnostics()

    scheduler.step_one_tick()

    assert diagnostics.current_tick == 0
    assert diagnostics.tasks[0].execution_count == 0
    with pytest.raises(FrozenInstanceError):
        diagnostics.current_tick = 99  # type: ignore[misc]
