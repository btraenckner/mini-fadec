"""Immutable typed scenario definitions and construction validation."""

from dataclasses import dataclass
from collections.abc import Iterable
from typing import TypeAlias

from simulation.plants.config import PlantSelectionConfig
from simulation.scenarios.actions import (
    ScenarioAction,
    validate_action_definition,
)
from simulation.scenarios.conditions import (
    ActionExecutedCondition,
    AllConditions,
    ElapsedAfterActionCondition,
    ScenarioCondition,
)
from simulation.scenarios.triggers import AtTimeTrigger, WhenConditionTrigger
from simulation.verification.requirements import Requirement


ScenarioConfigurationValue: TypeAlias = str | int | float | bool | None
ScenarioConfigurationOverrides: TypeAlias = tuple[
    tuple[str, ScenarioConfigurationValue], ...
]

SUPPORTED_CONFIGURATION_OVERRIDES = frozenset(
    {
        "artifact_base_directory",
        "telemetry_sampling_period_s",
        "sensor_random_seed",
        "scheduler_preset",
    }
)


@dataclass(frozen=True)
class RecordingConfiguration:
    """Scenario-owned recording behavior without recorder implementation detail."""

    enabled: bool = True
    run_name: str | None = None

    def __post_init__(self) -> None:
        if self.run_name is not None and not self.run_name.strip():
            raise ValueError("recording run_name cannot be empty")


@dataclass(frozen=True)
class Scenario:
    """Complete immutable definition of one deterministic scenario."""

    scenario_id: str
    name: str
    description: str
    max_duration_s: float
    actions: tuple[ScenarioAction, ...]
    requirements: tuple[Requirement, ...]
    tags: tuple[str, ...] = ()
    time_step_s: float | None = None
    recording: RecordingConfiguration = RecordingConfiguration()
    expected_terminal_condition: ScenarioCondition | None = None
    configuration_overrides: ScenarioConfigurationOverrides = ()
    random_seed: int | None = 0
    plant_config_override: PlantSelectionConfig | None = None

    def __post_init__(self) -> None:
        if not self.scenario_id.strip():
            raise ValueError("scenario_id cannot be empty")
        if not self.name.strip():
            raise ValueError("scenario name cannot be empty")
        if not self.description.strip():
            raise ValueError("scenario description cannot be empty")
        if self.max_duration_s <= 0.0:
            raise ValueError("max_duration_s must be greater than zero")
        if self.time_step_s is not None and self.time_step_s <= 0.0:
            raise ValueError("time_step_s must be greater than zero")

        for action in self.actions:
            validate_action_definition(action)
        _require_unique(
            (action.action_id for action in self.actions),
            "action ID",
        )
        _require_unique(
            (requirement.requirement_id for requirement in self.requirements),
            "requirement ID",
        )
        _require_unique(self.tags, "scenario tag")
        _require_unique((name for name, _ in self.configuration_overrides), "override")
        unsupported = {
            name
            for name, _ in self.configuration_overrides
            if name not in SUPPORTED_CONFIGURATION_OVERRIDES
        }
        if unsupported:
            names = ", ".join(sorted(unsupported))
            raise ValueError(f"unsupported configuration override(s): {names}")
        self._validate_action_references()

    def _validate_action_references(self) -> None:
        action_ids = {action.action_id for action in self.actions}
        for action in self.actions:
            trigger = action.trigger
            if not isinstance(trigger, (AtTimeTrigger, WhenConditionTrigger)):
                raise TypeError(
                    f"action {action.action_id!r} has unsupported trigger definition"
                )
            if isinstance(trigger, WhenConditionTrigger):
                for reference in _condition_action_references(trigger.condition):
                    if reference not in action_ids:
                        raise ValueError(
                            f"action {action.action_id!r} references unknown action "
                            f"{reference!r}"
                        )


def _condition_action_references(
    condition: ScenarioCondition,
) -> tuple[str, ...]:
    if isinstance(condition, (ActionExecutedCondition, ElapsedAfterActionCondition)):
        return (condition.action_id,)
    if isinstance(condition, AllConditions):
        return tuple(
            reference
            for child in condition.conditions
            for reference in _condition_action_references(child)
        )
    return ()


def _require_unique(values: Iterable[str], label: str) -> None:
    value_list = list(values)
    duplicates = sorted({value for value in value_list if value_list.count(value) > 1})
    if duplicates:
        raise ValueError(f"duplicate {label}(s): {', '.join(duplicates)}")
