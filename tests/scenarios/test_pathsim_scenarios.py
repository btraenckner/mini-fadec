"""Scenario-runner coverage for isolated PathSim development scenarios."""

from dataclasses import replace
from pathlib import Path

from simulation.plants.factory import plant_selection_for
from simulation.scenarios.definitions import Scenario
from simulation.scenarios.library import (
    list_pathsim_scenarios,
    list_scenarios,
    pathsim_smoke_scenario,
)
from simulation.scenarios.runner import ScenarioRunner
from simulation.scenarios.serialization import normalize_deterministic_result
from simulation.verification.results import ScenarioOverallStatus


def _with_artifacts(scenario: Scenario, directory: Path) -> Scenario:
    return replace(
        scenario,
        configuration_overrides=(
            ("artifact_base_directory", str(directory)),
        ),
    )


def test_pathsim_scenarios_are_separate_from_first_order_regression_group() -> None:
    assert tuple(scenario.scenario_id for scenario in list_pathsim_scenarios()) == (
        "SCN-PLANT-PS-001",
        "SCN-PLANT-PS-002",
        "SCN-PLANT-PS-003",
    )
    assert all(
        scenario.plant_config_override is None
        for scenario in list_scenarios()
    )
    assert all(
        "pathsim" in scenario.tags for scenario in list_pathsim_scenarios()
    )


def test_pathsim_smoke_scenario_records_effective_selection_and_passes(
    tmp_path: Path,
) -> None:
    scenario = _with_artifacts(pathsim_smoke_scenario(), tmp_path)

    result = ScenarioRunner(
        plant_config=plant_selection_for("first_order")
    ).run_scenario(scenario)

    assert result.overall_status is ScenarioOverallStatus.PASS
    assert result.plant_model_id == "pathsim_greybox_v1"
    assert result.plant_display_name == "PathSim nonlinear grey-box v1"
    assert result.metadata_path is not None
    assert result.report_path is not None
    assert "PathSim nonlinear grey-box v1" in result.report_path.read_text(
        encoding="utf-8"
    )


def test_repeated_pathsim_scenario_results_are_deterministic(
    tmp_path: Path,
) -> None:
    first_scenario = _with_artifacts(
        pathsim_smoke_scenario(),
        tmp_path / "first",
    )
    second_scenario = _with_artifacts(
        pathsim_smoke_scenario(),
        tmp_path / "second",
    )

    first = ScenarioRunner().run_scenario(first_scenario)
    second = ScenarioRunner().run_scenario(second_scenario)

    assert normalize_deterministic_result(first) == (
        normalize_deterministic_result(second)
    )
