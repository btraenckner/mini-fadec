"""Unit tests for project-owned PathSim grey-box equation functions."""

import math

import pytest

from simulation.plants.pathsim_greybox.config import PathSimGreyBoxConfig
from simulation.plants.pathsim_greybox.equations import (
    GreyBoxInputs,
    GreyBoxStateVector,
    calculate_algebraic_terms,
    calculate_combustion_effectiveness,
    calculate_state_derivative,
    calculate_thrust_n,
)


PARAMETERS = PathSimGreyBoxConfig()


def _inputs(
    *,
    fuel: float = 0.0,
    starter: bool = False,
    ignition: bool = False,
    fuel_enabled: bool = True,
) -> GreyBoxInputs:
    return GreyBoxInputs(
        fuel_command=fuel,
        starter_commanded=starter,
        ignition_commanded=ignition,
        fuel_enabled=fuel_enabled,
        ambient_temperature_c=15.0,
        ambient_pressure_pa=101_325.0,
    )


def test_zero_fuel_and_starter_create_no_positive_drive_torque() -> None:
    terms = calculate_algebraic_terms(
        GreyBoxStateVector(0.0, 0.2, 15.0),
        _inputs(fuel_enabled=False),
        PARAMETERS,
    )

    assert terms.starter_torque == 0.0
    assert terms.turbine_torque == 0.0


def test_starter_command_creates_positive_starter_torque() -> None:
    terms = calculate_algebraic_terms(
        GreyBoxStateVector(0.0, 0.0, 15.0),
        _inputs(starter=True, fuel_enabled=False),
        PARAMETERS,
    )

    assert terms.starter_torque > 0.0


def test_fuel_command_drives_fuel_lag_toward_bounded_command() -> None:
    increasing = calculate_state_derivative(
        GreyBoxStateVector(0.2, 0.2, 300.0),
        _inputs(fuel=0.8, ignition=True),
        PARAMETERS,
    )
    cutoff = calculate_state_derivative(
        GreyBoxStateVector(0.2, 0.2, 300.0),
        _inputs(fuel=0.8, fuel_enabled=False),
        PARAMETERS,
    )

    assert increasing.effective_fuel > 0.0
    assert cutoff.effective_fuel < 0.0


def test_turbine_torque_increases_with_effective_fuel() -> None:
    low = calculate_algebraic_terms(
        GreyBoxStateVector(0.1, 0.3, 300.0),
        _inputs(fuel=0.5),
        PARAMETERS,
    )
    high = calculate_algebraic_terms(
        GreyBoxStateVector(0.5, 0.3, 300.0),
        _inputs(fuel=0.5),
        PARAMETERS,
    )

    assert high.turbine_torque > low.turbine_torque


def test_compressor_and_friction_loads_are_nonnegative_and_speed_dependent() -> None:
    low = calculate_algebraic_terms(
        GreyBoxStateVector(0.0, 0.1, 15.0),
        _inputs(fuel_enabled=False),
        PARAMETERS,
    )
    high = calculate_algebraic_terms(
        GreyBoxStateVector(0.0, 0.5, 15.0),
        _inputs(fuel_enabled=False),
        PARAMETERS,
    )

    assert low.friction_load >= 0.0
    assert high.compressor_load > low.compressor_load
    assert high.friction_load > low.friction_load


def test_combustion_effectiveness_is_bounded_with_ignition_and_speed_support() -> None:
    state = GreyBoxStateVector(0.2, 0.0, 15.0)
    no_support = calculate_combustion_effectiveness(
        state,
        _inputs(fuel=0.2),
        PARAMETERS,
    )
    ignition_support = calculate_combustion_effectiveness(
        state,
        _inputs(fuel=0.2, ignition=True),
        PARAMETERS,
    )
    speed_support = calculate_combustion_effectiveness(
        GreyBoxStateVector(0.2, 0.3, 300.0),
        _inputs(fuel=0.2),
        PARAMETERS,
    )

    assert no_support == 0.0
    assert 0.0 < ignition_support <= 1.0
    assert speed_support == pytest.approx(1.0)


def test_equilibrium_temperature_increases_with_fuel() -> None:
    low = calculate_algebraic_terms(
        GreyBoxStateVector(0.1, 0.3, 300.0),
        _inputs(fuel=0.5),
        PARAMETERS,
    )
    high = calculate_algebraic_terms(
        GreyBoxStateVector(0.5, 0.3, 300.0),
        _inputs(fuel=0.5),
        PARAMETERS,
    )

    assert high.equilibrium_temperature_c > low.equilibrium_temperature_c


def test_thrust_is_nonnegative_and_increases_with_speed() -> None:
    stopped = calculate_thrust_n(
        GreyBoxStateVector(0.0, 0.0, 15.0),
        _inputs(),
        PARAMETERS,
    )
    running = calculate_thrust_n(
        GreyBoxStateVector(0.0, 0.7, 15.0),
        _inputs(),
        PARAMETERS,
    )

    assert stopped == 0.0
    assert running > stopped


def test_derivatives_are_finite_and_boundary_guard_prevents_negative_speed() -> None:
    derivative = calculate_state_derivative(
        GreyBoxStateVector(0.0, 0.0, 15.0),
        _inputs(fuel_enabled=False),
        PARAMETERS,
    )

    assert all(math.isfinite(value) for value in derivative.__dict__.values())
    assert derivative.normalized_speed == 0.0
