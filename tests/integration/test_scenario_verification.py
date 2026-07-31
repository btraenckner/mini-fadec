"""End-to-end regression tests for deterministic scenario verification."""

import csv
from dataclasses import replace
import json
from pathlib import Path

import pytest

from simulation.application.interactive_simulation import run_scripted_smoke_test
from simulation.scenarios.definitions import Scenario
from simulation.scenarios.library import get_scenario, list_scenarios
from simulation.scenarios.runner import ScenarioRunner
from simulation.scenarios.serialization import normalize_deterministic_result
from simulation.telemetry.events import EventType
from simulation.verification.results import ScenarioOverallStatus


def _isolated_scenario(scenario: Scenario, base_directory: Path) -> Scenario:
    return replace(
        scenario,
        configuration_overrides=(
            ("artifact_base_directory", str(base_directory)),
        ),
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as csv_file:
        return list(csv.DictReader(csv_file))


@pytest.fixture(scope="module")
def scenario_results(tmp_path_factory: pytest.TempPathFactory):
    base_directory = tmp_path_factory.mktemp("scenario-suite")
    results = {}
    for scenario in list_scenarios():
        isolated = _isolated_scenario(
            scenario,
            base_directory / scenario.name,
        )
        results[scenario.name] = ScenarioRunner().run_scenario(isolated)
    return results


def test_complete_regression_scenario_library_passes(scenario_results: dict) -> None:
    assert set(scenario_results) == {
        "normal_start_run_shutdown",
        "large_throttle_step",
        "rapid_throttle_reduction",
        "rpm_sensor_dropout",
        "egt_sensor_dropout",
        "soft_overspeed",
        "hard_overspeed",
    }
    assert all(
        result.overall_status is ScenarioOverallStatus.PASS
        for result in scenario_results.values()
    )


def test_normal_lifecycle_records_expected_state_sequence(
    scenario_results: dict,
) -> None:
    result = scenario_results["normal_start_run_shutdown"]
    events = _read_csv(result.event_path)
    states = [
        json.loads(row["new_value"])
        for row in events
        if row["event_type"] == EventType.ENGINE_STATE_CHANGED.value
    ]

    assert states == [
        "CRANKING",
        "IGNITION",
        "IDLE",
        "RUNNING",
        "IDLE",
        "SHUTDOWN",
        "OFF",
    ]


def test_transient_scenarios_activate_expected_limiters_and_shutdown(
    scenario_results: dict,
) -> None:
    acceleration = scenario_results["large_throttle_step"]
    reduction = scenario_results["rapid_throttle_reduction"]
    acceleration_events = {
        row["message"] for row in _read_csv(acceleration.event_path)
    }
    reduction_events = {
        row["message"] for row in _read_csv(reduction.event_path)
    }

    assert "Acceleration limiter activated" in acceleration_events
    assert {
        "REQ-TRANSIENT-OVERSHOOT",
        "REQ-TRANSIENT-SETTLING",
    } <= {
        item.requirement_id
        for item in acceleration.requirement_results
        if item.status.value == "PASS"
    }
    assert "Deceleration limiter activated" in reduction_events
    assert reduction.final_engine_state.value == "OFF"


def test_sensor_dropout_scenarios_produce_safe_typed_response(
    scenario_results: dict,
) -> None:
    for name in ("rpm_sensor_dropout", "egt_sensor_dropout"):
        result = scenario_results[name]
        event_types = {
            row["event_type"] for row in _read_csv(result.event_path)
        }
        assert result.final_engine_state.value == "FAULT"
        assert EventType.SENSOR_FAULT_INJECTED.value in event_types
        assert EventType.SENSOR_HEALTH_CHANGED.value in event_types
        assert EventType.AUTOMATIC_FAULT_REQUESTED.value in event_types
        assert EventType.SAFETY_FUEL_CUTOFF.value in event_types
        assert any(
            item.requirement_id.endswith("FAULT-FUEL")
            and item.status.value == "PASS"
            for item in result.requirement_results
        )


def test_soft_and_hard_overspeed_use_validated_fault_path(
    scenario_results: dict,
) -> None:
    soft = scenario_results["soft_overspeed"]
    hard = scenario_results["hard_overspeed"]
    soft_events = {
        row["event_type"] for row in _read_csv(soft.event_path)
    }
    hard_events = {
        row["event_type"] for row in _read_csv(hard.event_path)
    }
    soft_telemetry = _read_csv(soft.telemetry_path)
    hard_telemetry = _read_csv(hard.telemetry_path)

    assert EventType.SOFT_OVERSPEED_ACTIVATED.value in soft_events
    assert EventType.HARD_OVERSPEED_ACTIVATED.value not in soft_events
    assert any(
        row["active_protection_limiter"] == "OVERSPEED"
        and float(row["allowed_fuel_command"])
        < float(row["requested_fuel_command"])
        for row in soft_telemetry
    )
    assert EventType.HARD_OVERSPEED_ACTIVATED.value in hard_events
    assert EventType.CRITICAL_PROTECTION_REQUESTED.value in hard_events
    assert EventType.SAFETY_FUEL_CUTOFF.value in hard_events
    assert float(hard_telemetry[-1]["allowed_fuel_command"]) == pytest.approx(0.0)
    assert hard.final_engine_state.value == "FAULT"


def test_run_artifacts_match_in_memory_verification_results(
    scenario_results: dict,
) -> None:
    for result in scenario_results.values():
        assert result.run_directory is not None
        assert {
            "telemetry.csv",
            "events.csv",
            "metadata.json",
            "requirements.json",
            "report.md",
            "scenario.json",
        } <= {path.name for path in result.run_directory.iterdir()}
        requirements = json.loads(
            result.requirements_path.read_text(encoding="utf-8")
        )
        report = result.report_path.read_text(encoding="utf-8")

        assert requirements["overall_result"] == result.overall_status.value
        assert [
            item["status"] for item in requirements["requirement_results"]
        ] == [item.status.value for item in result.requirement_results]
        assert f"Scenario result:** {result.overall_status.value}" in report


def test_repeated_scenario_runs_have_equivalent_normalized_results_and_csv(
    tmp_path: Path,
) -> None:
    scenario = get_scenario("normal_start_run_shutdown")
    first = ScenarioRunner().run_scenario(
        _isolated_scenario(scenario, tmp_path / "first")
    )
    second = ScenarioRunner().run_scenario(
        _isolated_scenario(scenario, tmp_path / "second")
    )

    assert normalize_deterministic_result(first) == normalize_deterministic_result(
        second
    )
    assert first.telemetry_path.read_text(encoding="utf-8") == second.telemetry_path.read_text(encoding="utf-8")
    assert first.event_path.read_text(encoding="utf-8") == second.event_path.read_text(encoding="utf-8")


def test_all_scenario_final_fuel_commands_remain_bounded(
    scenario_results: dict,
) -> None:
    for result in scenario_results.values():
        assert all(
            0.0 <= float(row["allowed_fuel_command"]) <= 1.0
            for row in _read_csv(result.telemetry_path)
        )


def test_scenario_core_has_no_dashboard_or_terminal_dependency() -> None:
    source_files = (
        Path("simulation/scenarios/runner.py"),
        Path("simulation/scenarios/actions.py"),
        Path("simulation/scenarios/conditions.py"),
        Path("simulation/verification/evaluators.py"),
    )
    source = "\n".join(path.read_text(encoding="utf-8") for path in source_files)

    assert "live_dashboard" not in source
    assert "interactive_simulation" not in source
    assert "input(" not in source
    assert "print(" not in source
    assert ".engine_model" not in source


def test_existing_interactive_scripted_smoke_test_remains_operational() -> None:
    run_scripted_smoke_test()
