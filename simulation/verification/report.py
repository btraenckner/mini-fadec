"""Machine-readable and concise Markdown scenario verification reports."""

from datetime import datetime, timezone
from pathlib import Path

from simulation.scenarios.definitions import Scenario
from simulation.scenarios.serialization import scenario_to_dict
from simulation.verification.requirements import RequirementStatus
from simulation.verification.results import ScenarioResult
from simulation.verification.serialization import (
    REQUIREMENTS_REPORT_SCHEMA_VERSION,
    update_json_object,
    write_json_exclusive,
)


def write_verification_artifacts(
    scenario: Scenario,
    result: ScenarioResult,
    run_directory: Path,
    *,
    generated_at: datetime | None = None,
    git_commit: str | None = None,
) -> tuple[Path, Path, Path]:
    """Write scenario JSON, requirements JSON, and Markdown exactly once."""

    generated = generated_at or datetime.now(timezone.utc)
    scenario_path = run_directory / "scenario.json"
    requirements_path = run_directory / "requirements.json"
    report_path = run_directory / "report.md"

    write_json_exclusive(scenario_path, scenario_to_dict(scenario))
    write_json_exclusive(
        requirements_path,
        {
            "report_schema_version": REQUIREMENTS_REPORT_SCHEMA_VERSION,
            "scenario_id": result.scenario_id,
            "scenario_name": result.scenario_name,
            "overall_result": result.overall_status.value,
            "execution_status": result.execution_status,
            "summary_counts": {
                "passed": result.passed_requirement_count,
                "failed": result.failed_requirement_count,
                "not_evaluated": result.not_evaluated_requirement_count,
                "critical_failures": result.critical_failure_count,
            },
            "requirement_results": result.requirement_results,
            "action_results": result.action_results,
            "generated_at": generated.isoformat(),
            "paths": {
                "run_directory": result.run_directory,
                "metadata": result.metadata_path,
                "telemetry": result.telemetry_path,
                "events": result.event_path,
                "scenario": scenario_path,
                "requirements": requirements_path,
                "report": report_path,
            },
        },
    )
    _write_markdown_report(
        path=report_path,
        scenario=scenario,
        result=result,
        git_commit=git_commit,
    )
    if result.metadata_path is not None and result.metadata_path.exists():
        update_json_object(
            result.metadata_path,
            {
                "scenario_id": scenario.scenario_id,
                "scenario_name": scenario.name,
                "scenario_tags": scenario.tags,
                "scenario_execution_status": result.execution_status,
                "overall_verification_result": result.overall_status.value,
                "requirement_counts": {
                    "passed": result.passed_requirement_count,
                    "failed": result.failed_requirement_count,
                    "not_evaluated": result.not_evaluated_requirement_count,
                    "critical_failures": result.critical_failure_count,
                },
                "action_counts": {
                    "total": len(result.action_results),
                    "executed": sum(
                        action.status.value == "EXECUTED"
                        for action in result.action_results
                    ),
                    "failed": sum(
                        action.status.value in {"FAILED", "TIMED_OUT"}
                        for action in result.action_results
                    ),
                },
            },
        )
    return scenario_path, requirements_path, report_path


def _write_markdown_report(
    *,
    path: Path,
    scenario: Scenario,
    result: ScenarioResult,
    git_commit: str | None,
) -> None:
    failed = tuple(
        requirement
        for requirement in result.requirement_results
        if requirement.status in {RequirementStatus.FAIL, RequirementStatus.ERROR}
    )
    lines = [
        f"# Verification Report: {scenario.scenario_id}",
        "",
        f"**Scenario:** {scenario.name}",
        "",
        scenario.description,
        "",
        f"**Scenario result:** {result.overall_status.value}",
        "",
        f"- Execution status: {result.execution_status}",
        f"- Simulated duration: {result.simulated_duration_s:.3f} s",
        f"- Wall-clock duration: {result.wall_clock_execution_duration_s:.6f} s",
        f"- Final engine state: {result.final_engine_state.value}",
        f"- Git commit: {git_commit or 'unavailable'}",
        f"- Run directory: {result.run_directory or 'unavailable'}",
        "",
        "## Summary",
        "",
        f"- Passed: {result.passed_requirement_count}",
        f"- Failed: {result.failed_requirement_count}",
        f"- Not evaluated: {result.not_evaluated_requirement_count}",
        f"- Critical failures: {result.critical_failure_count}",
        "",
        "## Actions",
        "",
        "| Action | Status | Time (s) | Message |",
        "|---|---:|---:|---|",
    ]
    lines.extend(
        f"| {action.action_id} | {action.status.value} | "
        f"{_format_optional(action.execution_time_s)} | "
        f"{_escape_table(action.message)} |"
        for action in result.action_results
    )
    lines.extend(
        [
            "",
            "## Requirements",
            "",
            "| Requirement | Criticality | Status | Evidence |",
            "|---|---:|---:|---|",
        ]
    )
    lines.extend(
        f"| {requirement.requirement_id} | {requirement.criticality.value} | "
        f"{requirement.status.value} | {_escape_table(requirement.message)} |"
        for requirement in result.requirement_results
    )
    if failed:
        lines.extend(["", "## Failed Requirement Details", ""])
        for requirement in failed:
            evidence = requirement.evidence
            lines.extend(
                [
                    f"### {requirement.requirement_id}",
                    "",
                    requirement.description,
                    "",
                    f"- Status: {requirement.status.value}",
                    f"- Message: {requirement.message}",
                    f"- Measured: {evidence.measured_value}",
                    f"- Expected: {evidence.expected_value}",
                    f"- Limit: {_format_limit(evidence.lower_limit, evidence.upper_limit)}",
                    f"- Tolerance: {evidence.tolerance}",
                    f"- Margin: {evidence.margin}",
                    f"- First violation: {evidence.first_violation_time_s}",
                    f"- Diagnostic: {evidence.diagnostic_message or requirement.diagnostic_code}",
                    "",
                ]
            )
    if result.exception_details:
        lines.extend(
            [
                "## Execution Error",
                "",
                result.exception_details,
                "",
            ]
        )
    lines.extend(
        [
            "",
            "## Run Artifacts",
            "",
            f"- [Telemetry]({Path('telemetry.csv')})",
            f"- [Events]({Path('events.csv')})",
            f"- [Metadata]({Path('metadata.json')})",
            f"- [Scenario definition]({Path('scenario.json')})",
            f"- [Requirement results]({Path('requirements.json')})",
            "",
            "This report is produced by a development simulation environment, "
            "not a certified aerospace verification tool.",
        ]
    )
    with path.open("x", encoding="utf-8") as report_file:
        report_file.write("\n".join(lines))
        report_file.write("\n")


def _format_optional(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"


def _format_limit(lower: float | None, upper: float | None) -> str:
    if lower is not None:
        return f">= {lower}"
    if upper is not None:
        return f"<= {upper}"
    return "-"


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
