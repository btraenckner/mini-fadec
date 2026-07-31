"""Tests for scheduler-aware scenario requirement evaluators."""

from dataclasses import replace

from simulation.application.engine_simulation import EngineSimulationCoordinator
from simulation.verification.evaluators import (
    DeterministicTaskOrderRequirementEvaluator,
    NoMissedSchedulerReleaseRequirementEvaluator,
    SchedulerPresetRequirementEvaluator,
    TaskExecutionCountRequirementEvaluator,
    TaskExecutionRatioRequirementEvaluator,
)
from simulation.verification.requirements import (
    EvaluationContext,
    RequirementStatus,
)


def _context() -> EvaluationContext:
    coordinator = EngineSimulationCoordinator()
    snapshots = [coordinator.snapshot]
    previous_sequence = coordinator.snapshot.snapshot_sequence_number
    for _ in range(21):
        snapshot = coordinator.step_one_tick()
        if snapshot.snapshot_sequence_number != previous_sequence:
            snapshots.append(snapshot)
            previous_sequence = snapshot.snapshot_sequence_number
    return EvaluationContext(
        snapshots=tuple(snapshots),
        events=(),
        action_results={},
        time_step_s=coordinator.scheduler_config.base_tick_s,
    )


def test_scheduler_evaluators_accept_exact_nominal_timing_evidence() -> None:
    context = _context()
    evaluators = (
        NoMissedSchedulerReleaseRequirementEvaluator(),
        SchedulerPresetRequirementEvaluator("nominal-multirate"),
        TaskExecutionCountRequirementEvaluator("sensor", period_ticks=5),
        TaskExecutionRatioRequirementEvaluator(
            "controller",
            10,
            "sensor",
            5,
        ),
        DeterministicTaskOrderRequirementEvaluator(),
    )

    outcomes = tuple(evaluator.evaluate(context) for evaluator in evaluators)

    assert all(
        outcome.status is RequirementStatus.PASS for outcome in outcomes
    )


def test_scheduler_evaluators_report_mismatched_evidence() -> None:
    context = _context()
    final = context.snapshots[-1]

    missed_context = replace(
        context,
        snapshots=(
            *context.snapshots[:-1],
            replace(final, scheduler_missed_release_count=1),
        ),
    )
    count_context = replace(
        context,
        snapshots=(
            *context.snapshots[:-1],
            replace(
                final,
                sensor_execution_count=final.sensor_execution_count + 1,
            ),
        ),
    )
    order_context = replace(
        context,
        snapshots=(
            *context.snapshots[:-1],
            replace(
                final,
                scheduler_tasks_executed_current_tick=(
                    "plant",
                    "command",
                ),
            ),
        ),
    )

    assert NoMissedSchedulerReleaseRequirementEvaluator().evaluate(
        missed_context
    ).status is RequirementStatus.FAIL
    assert SchedulerPresetRequirementEvaluator("single-rate").evaluate(
        context
    ).status is RequirementStatus.FAIL
    assert TaskExecutionCountRequirementEvaluator("sensor", 5).evaluate(
        count_context
    ).status is RequirementStatus.FAIL
    assert TaskExecutionRatioRequirementEvaluator(
        "controller",
        10,
        "sensor",
        5,
    ).evaluate(count_context).status is RequirementStatus.FAIL
    assert DeterministicTaskOrderRequirementEvaluator().evaluate(
        order_context
    ).status is RequirementStatus.FAIL
