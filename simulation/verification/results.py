"""Typed requirement and aggregate scenario verification results."""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from simulation.operation.engine_state import EngineOperatingState
from simulation.scenarios.actions import ActionResult
from simulation.verification.evidence import RequirementEvidence
from simulation.verification.requirements import (
    Requirement,
    RequirementCategory,
    RequirementCriticality,
    RequirementStatus,
)


class ScenarioOverallStatus(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class RequirementResult:
    """Serializable identity, status, and evidence for one requirement."""

    requirement_id: str
    description: str
    category: RequirementCategory
    criticality: RequirementCriticality
    status: RequirementStatus
    evidence: RequirementEvidence
    message: str
    diagnostic_code: str | None = None


@dataclass(frozen=True)
class ScenarioResult:
    """Complete immutable result returned to CLI or future dashboards."""

    scenario_id: str
    scenario_name: str
    overall_status: ScenarioOverallStatus
    execution_status: str
    simulation_start_time_s: float
    simulation_end_time_s: float
    simulated_duration_s: float
    wall_clock_execution_duration_s: float
    real_time_factor: float | None
    final_engine_state: EngineOperatingState
    action_results: tuple[ActionResult, ...]
    requirement_results: tuple[RequirementResult, ...]
    passed_requirement_count: int
    failed_requirement_count: int
    not_evaluated_requirement_count: int
    critical_failure_count: int
    run_directory: Path | None
    metadata_path: Path | None
    telemetry_path: Path | None
    event_path: Path | None
    requirements_path: Path | None
    scenario_path: Path | None
    report_path: Path | None
    summary: str
    exception_details: str | None = None


def evaluate_requirements(
    requirements: tuple[Requirement, ...],
    context: object,
) -> tuple[RequirementResult, ...]:
    """Evaluate every requirement and preserve evaluator errors explicitly."""

    results: list[RequirementResult] = []
    for requirement in requirements:
        try:
            outcome = requirement.evaluator.evaluate(context)  # type: ignore[arg-type]
        except Exception as error:  # evaluator failures are verification evidence
            results.append(
                RequirementResult(
                    requirement_id=requirement.requirement_id,
                    description=requirement.description,
                    category=requirement.category,
                    criticality=requirement.criticality,
                    status=RequirementStatus.ERROR,
                    evidence=RequirementEvidence(
                        diagnostic_message=str(error),
                    ),
                    message=f"Evaluator error: {error}",
                    diagnostic_code="EVALUATOR_ERROR",
                )
            )
            continue
        results.append(
            RequirementResult(
                requirement_id=requirement.requirement_id,
                description=requirement.description,
                category=requirement.category,
                criticality=requirement.criticality,
                status=outcome.status,
                evidence=outcome.evidence,
                message=outcome.message,
                diagnostic_code=outcome.diagnostic_code,
            )
        )
    return tuple(results)


def requirement_failure_impacts_scenario(
    requirement: Requirement,
    result: RequirementResult,
) -> bool:
    """Apply the documented deterministic requirement-impact rule."""

    if result.status is RequirementStatus.ERROR:
        return True
    if result.status is not RequirementStatus.FAIL:
        return False
    return not (
        requirement.criticality is RequirementCriticality.INFO
        and requirement.info_failure_is_warning_only
    )
