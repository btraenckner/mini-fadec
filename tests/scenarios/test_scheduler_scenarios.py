"""Definition tests for mandatory and experimental scheduler scenarios."""

from simulation.scenarios.library import (
    get_scenario,
    list_all_scenarios,
    list_scenarios,
)


def test_required_scheduler_scenarios_are_registered() -> None:
    all_scenarios = list_all_scenarios()
    scheduler_scenarios = {
        scenario.scenario_id: scenario
        for scenario in all_scenarios
        if scenario.scenario_id.startswith("SCN-SCHED-")
    }

    assert set(scheduler_scenarios) == {
        "SCN-SCHED-001",
        "SCN-SCHED-002",
        "SCN-SCHED-003",
        "SCN-SCHED-004",
        "SCN-SCHED-005",
        "SCN-SCHED-006",
    }
    assert {
        scenario.scenario_id for scenario in list_scenarios()
    }.issuperset(
        {
            "SCN-SCHED-001",
            "SCN-SCHED-002",
            "SCN-SCHED-003",
            "SCN-SCHED-004",
        }
    )
    assert {
        scenario.scenario_id for scenario in list_scenarios()
    }.isdisjoint({"SCN-SCHED-005", "SCN-SCHED-006"})


def test_scheduler_scenarios_select_explicit_presets_and_classification() -> None:
    expected_presets = {
        "SCN-SCHED-001": "single-rate",
        "SCN-SCHED-002": "nominal-multirate",
        "SCN-SCHED-003": "nominal-multirate",
        "SCN-SCHED-004": "nominal-multirate",
        "SCN-SCHED-005": "slow-controller",
        "SCN-SCHED-006": "slow-sensors",
    }

    for scenario_id, expected_preset in expected_presets.items():
        scenario = get_scenario(scenario_id)
        assert dict(scenario.configuration_overrides)[
            "scheduler_preset"
        ] == expected_preset

    assert "experimental" in get_scenario("SCN-SCHED-005").tags
    assert "expected-failure" in get_scenario("SCN-SCHED-006").tags
