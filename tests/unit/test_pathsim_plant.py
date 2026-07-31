"""Integration-level unit tests for the PathSim plant adapter and model."""

import json
import math

import pytest

from simulation.core.types import ActuatorCommand, AmbientConditions
from simulation.plants.config import PlantSelectionConfig
from simulation.plants.factory import create_engine_plant
from simulation.plants.interfaces import EnginePlant
from simulation.plants.pathsim_greybox.config import (
    PathSimGreyBoxConfig,
    PathSimSolverConfig,
)
from simulation.plants.pathsim_greybox.model import PathSimGreyBoxEngineModel
from simulation.plants.types import PlantModelKind, PlantSimulationError


AMBIENT = AmbientConditions()


def _starter_command() -> ActuatorCommand:
    return ActuatorCommand(
        fuel_command=0.0,
        starter_commanded=True,
        fuel_enabled=False,
    )


def _combustion_command(fuel: float) -> ActuatorCommand:
    return ActuatorCommand(
        fuel_command=fuel,
        starter_commanded=True,
        ignition_commanded=True,
        fuel_enabled=True,
    )


def test_pathsim_backend_satisfies_public_plant_protocol_and_metadata() -> None:
    plant = create_engine_plant(PlantModelKind.PATHSIM_GREYBOX_V1)

    assert isinstance(plant, EnginePlant)
    assert plant.model_id == "pathsim_greybox_v1"
    assert plant.state.rotor_speed_rpm == 0.0
    assert plant.state.exhaust_temperature_c == 15.0
    json.dumps(plant.get_metadata())
    assert plant.get_metadata()["pathsim_package_version"] == "0.24.0"
    assert plant.get_metadata()["solver_api"] == (
        "Simulation.timestep(dt, adaptive=False)"
    )


def test_one_call_advances_exactly_one_requested_interval() -> None:
    plant = PathSimGreyBoxEngineModel(
        PathSimGreyBoxConfig(
            solver=PathSimSolverConfig(internal_substep_count=4)
        )
    )

    plant.step(_starter_command(), AMBIENT, 0.01)
    diagnostics = plant.get_diagnostics()

    assert diagnostics.model_time_s == pytest.approx(0.01)
    assert diagnostics.step_count == 1
    assert diagnostics.pathsim is not None
    assert diagnostics.pathsim.solver_step_count == 4
    assert diagnostics.pathsim.internal_substep_count == 4


def test_explicit_internal_step_must_exactly_match_requested_interval() -> None:
    plant = PathSimGreyBoxEngineModel(
        PathSimGreyBoxConfig(
            solver=PathSimSolverConfig(
                internal_step_s=0.003,
                internal_substep_count=3,
            )
        )
    )

    with pytest.raises(PlantSimulationError, match="divide"):
        plant.step(_starter_command(), AMBIENT, 0.01)


def test_repeated_steps_are_deterministic_and_keep_time_synchronized() -> None:
    first = PathSimGreyBoxEngineModel()
    second = PathSimGreyBoxEngineModel()

    for _ in range(100):
        first_outputs = first.step(_starter_command(), AMBIENT, 0.001)
        second_outputs = second.step(_starter_command(), AMBIENT, 0.001)

    assert first.state.rotor_speed_rpm == pytest.approx(
        second.state.rotor_speed_rpm,
        rel=0.0,
        abs=1.0e-12,
    )
    assert first_outputs == second_outputs
    assert first.get_diagnostics().model_time_s == pytest.approx(0.1)


def test_reset_restores_time_states_counters_and_repeatability() -> None:
    plant = PathSimGreyBoxEngineModel()
    commands = [_starter_command()] * 50 + [_combustion_command(0.3)] * 50

    for command in commands:
        first_outputs = plant.step(command, AMBIENT, 0.001)
    first_state = (
        plant.state.rotor_speed_rpm,
        plant.state.exhaust_temperature_c,
    )

    plant.reset(ambient=AMBIENT)
    assert plant.get_diagnostics().model_time_s == 0.0
    assert plant.get_diagnostics().step_count == 0
    for command in commands:
        second_outputs = plant.step(command, AMBIENT, 0.001)

    assert plant.state.rotor_speed_rpm == pytest.approx(first_state[0])
    assert plant.state.exhaust_temperature_c == pytest.approx(first_state[1])
    assert second_outputs == first_outputs


def test_fuel_step_lags_and_ignition_creates_thermal_response() -> None:
    plant = PathSimGreyBoxEngineModel()
    initial_temperature_c = plant.state.exhaust_temperature_c

    plant.step(_combustion_command(0.8), AMBIENT, 0.01)
    first_diagnostics = plant.get_diagnostics().pathsim
    assert first_diagnostics is not None
    assert 0.0 < first_diagnostics.effective_fuel < 0.8

    for _ in range(99):
        plant.step(_combustion_command(0.8), AMBIENT, 0.01)

    assert plant.state.exhaust_temperature_c > initial_temperature_c
    assert plant.get_diagnostics().pathsim is not None
    assert plant.get_diagnostics().pathsim.effective_fuel < 0.8


def test_fuel_cutoff_decays_effective_fuel_and_wind_down_remains_finite() -> None:
    plant = PathSimGreyBoxEngineModel()
    for _ in range(100):
        plant.step(_combustion_command(0.5), AMBIENT, 0.005)
    before_cutoff = plant.get_diagnostics().pathsim
    assert before_cutoff is not None

    for _ in range(100):
        outputs = plant.step(
            ActuatorCommand(fuel_command=1.0, fuel_enabled=False),
            AMBIENT,
            0.005,
        )
    after_cutoff = plant.get_diagnostics().pathsim
    assert after_cutoff is not None

    assert after_cutoff.effective_fuel < before_cutoff.effective_fuel
    assert plant.state.rotor_speed_rpm >= 0.0
    assert outputs.estimated_thrust_n >= 0.0
    assert all(
        math.isfinite(value)
        for value in (
            plant.state.rotor_speed_rpm,
            plant.state.exhaust_temperature_c,
            outputs.estimated_thrust_n,
        )
    )


def test_injected_solver_failure_raises_project_owned_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plant = PathSimGreyBoxEngineModel()

    monkeypatch.setattr(
        plant._adapter._simulation,  # noqa: SLF001 - failure injection boundary
        "timestep",
        lambda *_args, **_kwargs: (False, 1.0, 1.0, 1, 0),
    )

    with pytest.raises(PlantSimulationError, match="unsuccessful fixed step"):
        plant.step(_starter_command(), AMBIENT, 0.001)
    assert not plant.get_diagnostics().pathsim.latest_integration_success  # type: ignore[union-attr]


def test_factory_creations_do_not_share_pathsim_state_or_configuration() -> None:
    selection = PlantSelectionConfig(
        model=PlantModelKind.PATHSIM_GREYBOX_V1
    )
    first = create_engine_plant(selection)
    second = create_engine_plant(selection)

    first.step(_starter_command(), AMBIENT, 0.01)

    assert first.state.rotor_speed_rpm > 0.0
    assert second.state.rotor_speed_rpm == 0.0
    assert first.get_diagnostics() is not second.get_diagnostics()
