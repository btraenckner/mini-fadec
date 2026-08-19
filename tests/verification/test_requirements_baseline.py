"""Consistency tests for the controlled FADEC requirements baseline."""

import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from simulation.scenarios.library import list_all_scenarios
from simulation.verification import (
    RequirementBaselineStatus,
    TraceabilityCoverage,
    fadec_control_requirements_baseline,
)


def test_baseline_is_draft_unique_and_json_serializable() -> None:
    baseline = fadec_control_requirements_baseline()

    assert baseline.baseline_id == "MINI-FADEC-CONTROL-REQ"
    assert baseline.version == "0.1.0"
    assert baseline.status is RequirementBaselineStatus.DRAFT
    assert len(baseline.requirements) == 26
    assert len(
        {requirement.requirement_id for requirement in baseline.requirements}
    ) == len(baseline.requirements)
    payload = baseline.to_dict()
    json.dumps(payload)
    assert payload["requirements"][0]["coverage"] in {  # type: ignore[index]
        coverage.value for coverage in TraceabilityCoverage
    }


def test_baseline_has_executable_trace_for_every_requirement() -> None:
    baseline = fadec_control_requirements_baseline()
    implemented = tuple(
        requirement
        for requirement in baseline.requirements
        if requirement.coverage is TraceabilityCoverage.IMPLEMENTED
    )
    planned = tuple(
        requirement
        for requirement in baseline.requirements
        if requirement.coverage is TraceabilityCoverage.PLANNED
    )

    assert len(implemented) == 26
    assert planned == ()


def test_every_executable_trace_resolves_to_existing_scenario_evidence() -> None:
    scenarios = {
        scenario.scenario_id: scenario for scenario in list_all_scenarios()
    }

    for requirement in fadec_control_requirements_baseline().requirements:
        linked_executable_ids: set[str] = set()
        for scenario_id in requirement.scenario_ids:
            assert scenario_id in scenarios
            linked_executable_ids.update(
                executable.requirement_id
                for executable in scenarios[scenario_id].requirements
            )
        assert set(requirement.executable_requirement_ids) <= (
            linked_executable_ids
        )


def test_human_requirements_document_contains_exact_baseline_ids() -> None:
    document = Path(
        "docs/requirements/fadec_control_requirements.md"
    ).read_text(encoding="utf-8")
    documented_ids = tuple(
        re.findall(r"^### (FADEC-[A-Z]+-\d{3}) —", document, re.MULTILINE)
    )
    baseline_ids = tuple(
        requirement.requirement_id
        for requirement in fadec_control_requirements_baseline().requirements
    )

    assert documented_ids == baseline_ids
    assert "Version | `0.1.0`" in document
    assert "Status | `DRAFT`" in document


def test_traceability_document_contains_every_requirement_and_summary() -> None:
    matrix = Path(
        "docs/verification/requirements_traceability_matrix.md"
    ).read_text(encoding="utf-8")

    for requirement in fadec_control_requirements_baseline().requirements:
        assert f"| `{requirement.requirement_id}` |" in matrix
    assert "| Implemented trace | 26 |" in matrix
    assert "| Planned gap | 0 |" in matrix


def test_unknown_requirement_lookup_and_duplicate_baseline_are_rejected() -> None:
    baseline = fadec_control_requirements_baseline()

    with pytest.raises(KeyError, match="unknown baseline requirement"):
        baseline.requirement("FADEC-UNKNOWN-999")
    with pytest.raises(ValueError, match="must be unique"):
        replace(
            baseline,
            requirements=(baseline.requirements[0],) * 2,
        )
