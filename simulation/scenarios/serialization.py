"""Explicit JSON-safe serialization for scenario definitions and results."""

import math
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping

from simulation.scenarios.definitions import Scenario


SCENARIO_SCHEMA_VERSION = "1.0"


def scenario_to_dict(scenario: Scenario) -> dict[str, object]:
    """Serialize one scenario without executable callbacks or mutable objects."""

    return {
        "scenario_schema_version": SCENARIO_SCHEMA_VERSION,
        "scenario_id": scenario.scenario_id,
        "name": scenario.name,
        "description": scenario.description,
        "max_duration_s": scenario.max_duration_s,
        "time_step_s": scenario.time_step_s,
        "recording": definition_to_dict(scenario.recording),
        "actions": [definition_to_dict(action) for action in scenario.actions],
        "requirements": [
            definition_to_dict(requirement) for requirement in scenario.requirements
        ],
        "tags": list(scenario.tags),
        "expected_terminal_condition": (
            definition_to_dict(scenario.expected_terminal_condition)
            if scenario.expected_terminal_condition is not None
            else None
        ),
        "configuration_overrides": dict(scenario.configuration_overrides),
        "random_seed": scenario.random_seed,
        "plant_config_override": (
            definition_to_dict(scenario.plant_config_override)
            if scenario.plant_config_override is not None
            else None
        ),
    }


def definition_to_dict(value: object) -> object:
    """Serialize typed immutable definitions with an explicit type discriminator."""

    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (tuple, list)):
        return [definition_to_dict(item) for item in value]
    if isinstance(value, Mapping):
        return {
            str(key): definition_to_dict(item)
            for key, item in value.items()
        }
    if is_dataclass(value):
        serialized: dict[str, object] = {"type": type(value).__name__}
        for field in fields(value):
            serialized[field.name] = definition_to_dict(
                getattr(value, field.name)
            )
        return serialized
    raise TypeError(f"unsupported serializable definition: {type(value).__name__}")


def normalize_deterministic_result(value: object) -> object:
    """Remove documented nondeterministic result fields before comparison."""

    serialized = definition_to_dict(value)
    if not isinstance(serialized, dict):
        return serialized
    ignored = {
        "wall_clock_execution_duration_s",
        "real_time_factor",
        "run_directory",
        "metadata_path",
        "telemetry_path",
        "event_path",
        "requirements_path",
        "scenario_path",
        "report_path",
    }
    return {key: item for key, item in serialized.items() if key not in ignored}
