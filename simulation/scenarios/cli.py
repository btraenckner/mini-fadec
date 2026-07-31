"""Non-interactive command-line adapter for deterministic scenarios."""

import argparse
import json
from collections.abc import Sequence

from simulation.scenarios.library import (
    get_scenario,
    list_all_scenarios,
    list_scenarios,
)
from simulation.scenarios.runner import ScenarioRunner
from simulation.scenarios.serialization import definition_to_dict
from simulation.scheduling.presets import list_scheduler_presets
from simulation.verification.results import ScenarioOverallStatus, ScenarioResult


def main(arguments: Sequence[str] | None = None) -> int:
    """Execute the scenario CLI and return a process exit status."""

    parser = argparse.ArgumentParser(
        description="Run deterministic Mini-FADEC verification scenarios."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list", help="list registered regression scenarios")
    subparsers.add_parser("presets", help="list scheduler timing presets")
    show_parser = subparsers.add_parser("show", help="show one scenario")
    show_parser.add_argument("scenario")
    run_parser = subparsers.add_parser("run", help="run one scenario")
    run_parser.add_argument("scenario")
    run_parser.add_argument(
        "--scheduler",
        choices=_scheduler_preset_names(),
    )
    run_all_parser = subparsers.add_parser(
        "run-all",
        help="run all registered scenarios",
    )
    run_all_parser.add_argument(
        "--scheduler",
        choices=_scheduler_preset_names(),
    )
    parsed = parser.parse_args(arguments)

    try:
        if parsed.command == "list":
            _print_scenario_list()
            return 0
        if parsed.command == "presets":
            _print_scheduler_presets()
            return 0
        if parsed.command == "show":
            _print_scenario(get_scenario(parsed.scenario))
            return 0
        if parsed.command == "run":
            result = ScenarioRunner(
                scheduler_preset=parsed.scheduler
            ).run_scenario(
                get_scenario(parsed.scenario)
            )
            _print_result(result)
            return 0 if result.overall_status is ScenarioOverallStatus.PASS else 1
    except KeyError as error:
        parser.error(str(error))

    results = tuple(
        ScenarioRunner(
            scheduler_preset=parsed.scheduler
        ).run_scenario(scenario)
        for scenario in list_scenarios()
    )
    _print_result_table(results)
    return (
        0
        if all(
            result.overall_status is ScenarioOverallStatus.PASS
            for result in results
        )
        else 1
    )


def _print_scenario_list() -> None:
    print("ID              NAME                         TAGS")
    for scenario in list_all_scenarios():
        print(
            f"{scenario.scenario_id:15s} "
            f"{scenario.name:28s} "
            f"{','.join(scenario.tags)}"
        )
        print(f"  {scenario.description}")


def _print_scheduler_presets() -> None:
    print("NAME                 CLASSIFICATION")
    for preset in list_scheduler_presets():
        classification = (
            "mandatory"
            if preset.mandatory_regression
            else "experimental"
        )
        print(f"{preset.preset_name:20s} {classification}")


def _scheduler_preset_names() -> tuple[str, ...]:
    return tuple(
        preset.preset_name for preset in list_scheduler_presets()
    )


def _print_scenario(scenario: object) -> None:
    payload = definition_to_dict(scenario)
    print(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False))


def _print_result(result: ScenarioResult) -> None:
    print(f"Scenario:        {result.scenario_name}")
    print(f"Execution:       {result.execution_status}")
    print(f"Simulated time:  {result.simulated_duration_s:.3f} s")
    print(f"Wall-clock time: {result.wall_clock_execution_duration_s:.6f} s")
    print(f"Result:          {result.overall_status.value}")
    print(
        "Requirements:    "
        f"{result.passed_requirement_count} passed, "
        f"{result.failed_requirement_count} failed, "
        f"{result.not_evaluated_requirement_count} not evaluated"
    )
    print(f"Run directory:   {result.run_directory or 'unavailable'}")


def _print_result_table(results: tuple[ScenarioResult, ...]) -> None:
    print("SCENARIO                     EXECUTION   RESULT  PASS FAIL N/E")
    for result in results:
        print(
            f"{result.scenario_name:28s} "
            f"{result.execution_status:11s} "
            f"{result.overall_status.value:6s} "
            f"{result.passed_requirement_count:4d} "
            f"{result.failed_requirement_count:4d} "
            f"{result.not_evaluated_requirement_count:3d}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
