"""Consistency tests for formal FADEC test-case specifications."""

from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
import re

import pytest

from simulation.scenarios.library import list_all_scenarios
from simulation.verification import (
    TestCaseCatalogStatus as CatalogStatus,
    TestCaseImplementationStatus as ImplementationStatus,
    fadec_control_requirements_baseline,
    fadec_test_case_catalog,
)


def test_catalog_is_draft_complete_and_json_serializable() -> None:
    catalog = fadec_test_case_catalog()

    assert catalog.catalog_id == "MINI-FADEC-TEST-CASES"
    assert catalog.version == "0.1.0"
    assert catalog.status is CatalogStatus.DRAFT
    assert catalog.requirements_baseline_id == "MINI-FADEC-CONTROL-REQ"
    assert catalog.requirements_baseline_version == "0.1.0"
    assert len(catalog.test_cases) == 24
    assert len({case.test_case_id for case in catalog.test_cases}) == 24
    payload = catalog.to_dict()
    json.dumps(payload)
    assert payload["catalog_id"] == "MINI-FADEC-TEST-CASES"


def test_catalog_exactly_implements_baseline_planned_test_links() -> None:
    baseline = fadec_control_requirements_baseline()
    catalog = fadec_test_case_catalog()

    for requirement in baseline.requirements:
        actual_test_ids = tuple(
            case.test_case_id
            for case in catalog.for_requirement(requirement.requirement_id)
        )
        assert actual_test_ids == requirement.planned_test_case_ids


def test_implementation_summary_keeps_incomplete_evidence_visible() -> None:
    counts = Counter(
        case.implementation_status
        for case in fadec_test_case_catalog().test_cases
    )

    assert counts == {
        ImplementationStatus.EXECUTABLE_SCENARIO: 23,
        ImplementationStatus.PARTIAL_AUTOMATION: 1,
    }


def test_scenario_and_automated_test_references_resolve() -> None:
    scenarios = {
        scenario.scenario_id: scenario for scenario in list_all_scenarios()
    }
    catalog = fadec_test_case_catalog()

    for case in catalog.test_cases:
        for scenario_id in case.scenario_ids:
            assert scenario_id in scenarios
            assert case.maximum_duration_s >= scenarios[scenario_id].max_duration_s
        for reference in case.automated_test_references:
            path_text, function_name = reference.split("::", maxsplit=1)
            source = Path(path_text).read_text(encoding="utf-8")
            assert re.search(
                rf"^def {re.escape(function_name)}\(",
                source,
                re.MULTILINE,
            )


def test_executable_scenario_links_agree_with_baseline_trace() -> None:
    baseline = fadec_control_requirements_baseline()
    scenarios = {
        scenario.scenario_id: scenario for scenario in list_all_scenarios()
    }

    for case in fadec_test_case_catalog().test_cases:
        for scenario_id in case.scenario_ids:
            scenario_requirement_ids = {
                requirement.requirement_id
                for requirement in scenarios[scenario_id].requirements
            }
            for requirement_id in case.linked_requirement_ids:
                requirement = baseline.requirement(requirement_id)
                assert scenario_id in requirement.scenario_ids
                assert scenario_requirement_ids.intersection(
                    requirement.executable_requirement_ids
                )


def test_ambient_campaign_retains_explicit_physical_fidelity_gap() -> None:
    catalog = fadec_test_case_catalog()
    unresolved = tuple(
        case.test_case_id
        for case in catalog.test_cases
        if not all(environment.is_resolved for environment in case.environments)
    )

    assert unresolved == ()
    assert (
        catalog.test_case("TC-ENV-001").implementation_status
        is ImplementationStatus.PARTIAL_AUTOMATION
    )
    assert "do not establish physical" in " ".join(
        catalog.test_case("TC-ENV-001").acceptance_criteria
    )


def test_scenario_trace_lookup_preserves_baseline_order() -> None:
    catalog = fadec_test_case_catalog()

    assert tuple(
        case.test_case_id for case in catalog.for_scenario("SCN-NORMAL-001")
    ) == (
        "TC-OPS-001",
        "TC-OPS-002",
        "TC-ACT-001",
        "TC-ACT-002",
        "TC-ACT-003",
        "TC-EGT-002",
    )
    assert catalog.requirement_ids_for_scenario("SCN-NORMAL-001") == (
        "FADEC-OPS-001",
        "FADEC-OPS-002",
        "FADEC-OPS-003",
        "FADEC-ACT-001",
        "FADEC-ACT-002",
        "FADEC-ACT-003",
        "FADEC-EGT-002",
    )


def test_human_catalog_and_matrix_contain_controlled_test_cases() -> None:
    catalog_document = Path(
        "docs/verification/test_case_catalog.md"
    ).read_text(encoding="utf-8")
    matrix = Path(
        "docs/verification/requirements_traceability_matrix.md"
    ).read_text(encoding="utf-8")
    documented_ids = tuple(
        re.findall(r"^### (TC-[A-Z]+-\d{3}) —", catalog_document, re.MULTILINE)
    )
    catalog_ids = tuple(
        case.test_case_id for case in fadec_test_case_catalog().test_cases
    )

    assert documented_ids == catalog_ids
    baseline = fadec_control_requirements_baseline()
    catalog = fadec_test_case_catalog()
    for requirement in baseline.requirements:
        test_case = catalog.for_requirement(requirement.requirement_id)[0]
        expected_trace = (
            f"| `{requirement.requirement_id}` | `{test_case.test_case_id}` | "
            f"{test_case.implementation_status.value} |"
        )
        assert expected_trace in matrix
    assert "| `EXECUTABLE_SCENARIO` | 23 |" in catalog_document
    assert "| `PARTIAL_AUTOMATION` | 1 |" in catalog_document
    assert "| `PLANNED` | 0 |" in catalog_document


def test_unknown_lookup_and_duplicate_catalog_entries_are_rejected() -> None:
    catalog = fadec_test_case_catalog()

    with pytest.raises(KeyError, match="unknown test case"):
        catalog.test_case("TC-UNKNOWN-999")
    with pytest.raises(ValueError, match="test-case IDs must be unique"):
        replace(
            catalog,
            test_cases=(catalog.test_cases[0],) * 2,
        )
