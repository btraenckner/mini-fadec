"""Validation tests for immutable PathSim plant configuration."""

import json
import math

import pytest

from simulation.plants.config import PlantSelectionConfig
from simulation.plants.pathsim_greybox.config import (
    PathSimGreyBoxConfig,
    PathSimInitialConditions,
    PathSimSolverConfig,
)
from simulation.plants.types import PlantModelKind


def test_valid_configuration_is_accepted_and_serializes_deterministically() -> None:
    configuration = PlantSelectionConfig(
        model=PlantModelKind.PATHSIM_GREYBOX_V1
    )

    first = json.dumps(configuration.to_dict(), sort_keys=True)
    second = json.dumps(configuration.to_dict(), sort_keys=True)

    assert first == second
    assert "pathsim_greybox_v1" in first


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    (
        ("fuel_time_constant_s", 0.0, "fuel_time_constant_s"),
        ("thermal_time_constant_s", -1.0, "thermal_time_constant_s"),
        ("normalized_inertia", 0.0, "normalized_inertia"),
        ("linear_fuel_temperature_gain_c", math.nan, "must be finite"),
        ("turbine_torque_gain_per_s", math.inf, "must be finite"),
    ),
)
def test_invalid_pathsim_parameter_is_rejected(
    field_name: str,
    value: float,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        PathSimGreyBoxConfig(**{field_name: value})


def test_invalid_combustion_speed_ratio_ordering_is_rejected() -> None:
    with pytest.raises(ValueError, match="strictly ordered"):
        PathSimGreyBoxConfig(
            minimum_lightoff_speed_ratio=0.3,
            full_combustion_speed_ratio=0.2,
        )


def test_invalid_internal_solver_step_is_rejected() -> None:
    with pytest.raises(ValueError, match="internal_step_s"):
        PathSimSolverConfig(internal_step_s=0.0)


@pytest.mark.parametrize("count", (0, -1, 1.5, True))
def test_invalid_internal_substep_count_is_rejected(count: object) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        PathSimSolverConfig(internal_substep_count=count)  # type: ignore[arg-type]


def test_default_configuration_objects_are_independent() -> None:
    first = PlantSelectionConfig()
    second = PlantSelectionConfig()

    assert first is not second
    assert first.pathsim is not second.pathsim
    assert first.pathsim.solver is not second.pathsim.solver
    assert (
        first.pathsim.initial_conditions
        is not second.pathsim.initial_conditions
    )


def test_initial_temperature_below_configured_bound_is_rejected() -> None:
    with pytest.raises(ValueError, match="below minimum"):
        PathSimGreyBoxConfig(
            initial_conditions=PathSimInitialConditions(
                gas_temperature_c=-90.0
            )
        )
