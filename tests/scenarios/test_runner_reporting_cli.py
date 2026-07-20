"""Unit tests for deterministic execution, progress, reporting, and CLI."""

from dataclasses import dataclass, replace
import json
from pathlib import Path

import pytest

from simulation.operation.engine_state import EngineOperatingState
from simulation.scenarios.actions import (
    ActionExecutionStatus,
    AddMarkerAction,
    StartEngineAction,
)
from simulation.scenarios.conditions import EngineStateEqualsCondition
from simulation.scenarios.definitions import RecordingConfiguration, Scenario
from simulation.scenarios.runner import (
    ScenarioExecutionState,
    ScenarioRunner,
)
from simulation.scenarios.serialization import normalize_deterministic_result
from simulation.scenarios.triggers import AtTimeTrigger, WhenConditionTrigger
from simulation.telemetry.events import EventType
from simulation.verification.evaluators import EventObservedRequirementEvaluator
from simulation.verification.evidence import RequirementEvidence
from simulation.verification.requirements import (
    EvaluationOutcome,
    Requirement,
    RequirementCategory,
    RequirementCriticality,
    RequirementStatus,
)
from simulation.verification.report import write_verification_artifacts
from simulation.verification.results import ScenarioOverallStatus


@dataclass(frozen=True, kw_only=True)
class FailingAction:
    action_id: str
    description: str
    trigger: AtTimeTrigger
    required_success: bool = True
    timeout_s: float | None = None

    def execute(self, service: object) -> str:
        raise RuntimeError("controlled action failure")


@dataclass(frozen=True)
class ConstantEvaluator:
    status: RequirementStatus
    measured_value: float | None = None

    def evaluate(self, context: object) -> EvaluationOutcome:
        return EvaluationOutcome(
            self.status,
            RequirementEvidence(measured_value=self.measured_value),
            self.status.value,
        )


@dataclass(frozen=True)
class ErrorEvaluator:
    def evaluate(self, context: object) -> EvaluationOutcome:
        raise RuntimeError("controlled evaluator failure")


def _requirement(
    evaluator: object | None = None,
    *,
    criticality: RequirementCriticality = RequirementCriticality.MAJOR,
) -> Requirement:
    return Requirement(
        requirement_id="REQ-TEST-001",
        description="Test requirement",
        category=RequirementCategory.LOGICAL_INVARIANT,
        criticality=criticality,
        evaluator=evaluator or ConstantEvaluator(RequirementStatus.PASS),  # type: ignore[arg-type]
    )


def _short_scenario(
    tmp_path: Path,
    *,
    actions: tuple | None = None,
    requirements: tuple[Requirement, ...] | None = None,
    max_duration_s: float = 0.10,
    recording: bool = True,
) -> Scenario:
    return Scenario(
        scenario_id="SCN-TEST-001",
        name="runner_test",
        description="Short deterministic runner test",
        max_duration_s=max_duration_s,
        time_step_s=0.01,
        recording=RecordingConfiguration(enabled=recording, run_name="runner_test"),
        actions=actions
        or (
            StartEngineAction(
                action_id="start",
                description="Start",
                trigger=AtTimeTrigger(0.01),
            ),
            AddMarkerAction(
                action_id="marker",
                description="Marker",
                trigger=AtTimeTrigger(0.03),
                marker_text="done",
            ),
        ),
        requirements=requirements
        or (
            _requirement(
                EventObservedRequirementEvaluator(EventType.USER_MARKER)
            ),
        ),
        configuration_overrides=(("artifact_base_directory", str(tmp_path)),),
    )


def test_runner_is_unpaced_and_actions_execute_once_in_definition_order(
    tmp_path: Path,
) -> None:
    scenario = _short_scenario(tmp_path)
    runner = ScenarioRunner(sleeper=lambda _: pytest.fail("unexpected sleep"))

    result = runner.run_scenario(scenario)

    assert result.overall_status is ScenarioOverallStatus.PASS
    assert [action.action_id for action in result.action_results] == [
        "start",
        "marker",
    ]
    assert [action.execution_time_s for action in result.action_results] == pytest.approx(
        [0.01, 0.03]
    )
    assert all(
        action.status is ActionExecutionStatus.EXECUTED
        for action in result.action_results
    )


def test_condition_timeout_and_maximum_duration_are_reported(tmp_path: Path) -> None:
    waiting = AddMarkerAction(
        action_id="never",
        description="Never due",
        trigger=WhenConditionTrigger(
            EngineStateEqualsCondition(target_state=EngineOperatingState.IDLE),
            timeout_s=0.04,
        ),
        marker_text="never",
    )
    scenario = _short_scenario(
        tmp_path,
        actions=(waiting,),
        max_duration_s=0.05,
    )

    result = ScenarioRunner().run_scenario(scenario)

    assert result.execution_status == ScenarioExecutionState.FAILED.value
    assert result.overall_status is ScenarioOverallStatus.FAIL
    assert result.action_results[0].status is ActionExecutionStatus.TIMED_OUT
    assert "latest state" in result.action_results[0].message


def test_scenario_duration_timeout_marks_pending_actions(tmp_path: Path) -> None:
    waiting = AddMarkerAction(
        action_id="never",
        description="Never due",
        trigger=WhenConditionTrigger(
            EngineStateEqualsCondition(EngineOperatingState.IDLE),
            timeout_s=None,
        ),
        marker_text="never",
    )
    result = ScenarioRunner().run_scenario(
        _short_scenario(
            tmp_path,
            actions=(waiting,),
            max_duration_s=0.03,
        )
    )

    assert result.execution_status == ScenarioExecutionState.TIMED_OUT.value
    assert result.action_results[0].status is ActionExecutionStatus.TIMED_OUT


def test_progress_is_programmatic_and_cancellation_finalizes_recording(
    tmp_path: Path,
) -> None:
    runner = ScenarioRunner()
    progress = runner.prepare_scenario(_short_scenario(tmp_path))

    assert progress.execution_state is ScenarioExecutionState.RUNNING
    assert progress.latest_snapshot.simulation_time_s == pytest.approx(0.0)
    assert progress.pending_action_count == 2
    assert progress.current_recording_directory is not None

    cancelled = runner.cancel_scenario()

    assert cancelled.overall_status is ScenarioOverallStatus.CANCELLED
    assert cancelled.execution_status == ScenarioExecutionState.CANCELLED.value
    assert cancelled.metadata_path is not None
    metadata = json.loads(cancelled.metadata_path.read_text(encoding="utf-8"))
    assert metadata["completion_status"] == "incomplete"


def test_disabled_automatic_recording_still_gets_diagnostic_artifacts(
    tmp_path: Path,
) -> None:
    result = ScenarioRunner().run_scenario(
        _short_scenario(tmp_path, recording=False)
    )

    assert result.overall_status is ScenarioOverallStatus.PASS
    assert result.run_directory is not None
    assert {
        "telemetry.csv",
        "events.csv",
        "metadata.json",
        "scenario.json",
        "requirements.json",
        "report.md",
    } <= {path.name for path in result.run_directory.iterdir()}


def test_required_and_optional_action_failures_follow_documented_policy(
    tmp_path: Path,
) -> None:
    required = FailingAction(
        action_id="required",
        description="Required failure",
        trigger=AtTimeTrigger(0.0),
    )
    optional = replace(
        required,
        action_id="optional",
        description="Optional failure",
        required_success=False,
    )

    required_result = ScenarioRunner().run_scenario(
        _short_scenario(
            tmp_path / "required",
            actions=(required,),  # type: ignore[arg-type]
            requirements=(_requirement(),),
        )
    )
    optional_result = ScenarioRunner().run_scenario(
        _short_scenario(
            tmp_path / "optional",
            actions=(optional,),  # type: ignore[arg-type]
            requirements=(_requirement(),),
        )
    )

    assert required_result.overall_status is ScenarioOverallStatus.FAIL
    assert required_result.action_results[0].status is ActionExecutionStatus.FAILED
    assert optional_result.overall_status is ScenarioOverallStatus.PASS
    assert optional_result.action_results[0].status is ActionExecutionStatus.FAILED


def test_evaluator_error_is_never_silently_converted_to_pass(tmp_path: Path) -> None:
    result = ScenarioRunner().run_scenario(
        _short_scenario(
            tmp_path,
            requirements=(_requirement(ErrorEvaluator()),),
        )
    )

    assert result.overall_status is ScenarioOverallStatus.FAIL
    assert result.requirement_results[0].status is RequirementStatus.ERROR
    assert result.requirement_results[0].diagnostic_code == "EVALUATOR_ERROR"


def test_info_failure_is_warning_only_but_major_failure_fails(tmp_path: Path) -> None:
    info = _requirement(
        ConstantEvaluator(RequirementStatus.FAIL),
        criticality=RequirementCriticality.INFO,
    )
    major = _requirement(ConstantEvaluator(RequirementStatus.FAIL))

    info_result = ScenarioRunner().run_scenario(
        _short_scenario(tmp_path / "info", requirements=(info,))
    )
    major_result = ScenarioRunner().run_scenario(
        _short_scenario(tmp_path / "major", requirements=(major,))
    )

    assert info_result.overall_status is ScenarioOverallStatus.PASS
    assert major_result.overall_status is ScenarioOverallStatus.FAIL


def test_reports_metadata_and_json_are_complete_and_standards_compliant(
    tmp_path: Path,
) -> None:
    result = ScenarioRunner().run_scenario(
        _short_scenario(
            tmp_path,
            requirements=(
                _requirement(
                    ConstantEvaluator(
                        RequirementStatus.PASS,
                        measured_value=float("nan"),
                    )
                ),
            ),
        )
    )

    assert result.requirements_path is not None
    assert result.report_path is not None
    assert result.scenario_path is not None
    requirements_text = result.requirements_path.read_text(encoding="utf-8")
    report_text = result.report_path.read_text(encoding="utf-8")
    requirements = json.loads(requirements_text)
    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))  # type: ignore[union-attr]

    assert requirements["report_schema_version"] == "1.0"
    assert requirements["action_results"]
    assert requirements["requirement_results"][0]["evidence"]["measured_value"] is None
    assert "NaN" not in requirements_text
    assert "Scenario result:** PASS" in report_text
    assert "REQ-TEST-001" in report_text
    assert metadata["scenario_id"] == "SCN-TEST-001"
    assert metadata["overall_verification_result"] == "PASS"

    with pytest.raises(FileExistsError):
        write_verification_artifacts(
            _short_scenario(tmp_path / "unused"),
            result,
            result.run_directory,  # type: ignore[arg-type]
        )


def test_repeated_runs_are_isolated_and_normalized_results_are_deterministic(
    tmp_path: Path,
) -> None:
    first = ScenarioRunner().run_scenario(_short_scenario(tmp_path / "first"))
    second = ScenarioRunner().run_scenario(_short_scenario(tmp_path / "second"))

    assert first.run_directory != second.run_directory
    assert normalize_deterministic_result(first) == normalize_deterministic_result(
        second
    )
