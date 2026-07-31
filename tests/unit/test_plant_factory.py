"""Tests for the stable engine-plant boundary and explicit factory."""

import json

import pytest

from simulation.core.types import ActuatorCommand, AmbientConditions
from simulation.plants.config import PlantSelectionConfig
from simulation.plants.factory import (
    create_engine_plant,
    list_plant_models,
)
from simulation.plants.interfaces import EnginePlant
from simulation.plants.types import PlantModelKind


def test_first_order_backend_satisfies_engine_plant_protocol() -> None:
    plant = create_engine_plant(PlantModelKind.FIRST_ORDER)

    assert isinstance(plant, EnginePlant)
    assert plant.model_id == PlantModelKind.FIRST_ORDER.value
    assert plant.display_name == "First-order reference"


def test_factory_rejects_unknown_model_identifier() -> None:
    with pytest.raises(ValueError, match="unknown plant model"):
        create_engine_plant("not-a-plant")


def test_factory_model_list_has_stable_ids_and_display_order() -> None:
    assert tuple(model.model for model in list_plant_models()) == (
        PlantModelKind.FIRST_ORDER,
        PlantModelKind.PATHSIM_GREYBOX_V1,
    )


def test_each_factory_creation_owns_independent_state() -> None:
    first = create_engine_plant()
    second = create_engine_plant()

    first.step(
        ActuatorCommand(fuel_command=0.0, starter_commanded=True),
        AmbientConditions(),
        0.01,
    )

    assert first.state.rotor_speed_rpm > 0.0
    assert second.state.rotor_speed_rpm == 0.0
    assert first.state is not second.state


def test_first_order_metadata_and_selection_configuration_are_serializable() -> None:
    selection = PlantSelectionConfig()
    plant = create_engine_plant(selection)

    json.dumps(selection.to_dict())
    json.dumps(plant.get_metadata())
    assert plant.get_metadata()["plant_model_id"] == "first_order"


def test_first_order_backend_rejects_invalid_time_step() -> None:
    plant = create_engine_plant()

    with pytest.raises(ValueError, match="greater than zero"):
        plant.step(
            ActuatorCommand(fuel_command=0.0),
            AmbientConditions(),
            0.0,
        )


def test_first_order_diagnostics_do_not_fabricate_pathsim_values() -> None:
    diagnostics = create_engine_plant().get_diagnostics()

    assert diagnostics.model_time_s == 0.0
    assert diagnostics.step_count == 0
    assert diagnostics.pathsim is None


def test_first_order_reset_restores_original_initial_condition() -> None:
    plant = create_engine_plant()
    plant.step(
        ActuatorCommand(fuel_command=0.0, starter_commanded=True),
        AmbientConditions(),
        0.01,
    )

    plant.reset(ambient=AmbientConditions(temperature_c=30.0))

    assert plant.state.rotor_speed_rpm == 0.0
    assert plant.state.exhaust_temperature_c == 15.0
    assert plant.get_diagnostics().model_time_s == 0.0
    assert plant.get_diagnostics().step_count == 0
