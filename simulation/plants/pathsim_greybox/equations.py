"""Inspectable equations for the educational nonlinear grey-box plant."""

import math
from dataclasses import dataclass

from simulation.core.types import EngineOutputs
from simulation.plants.pathsim_greybox.config import PathSimGreyBoxConfig


@dataclass(frozen=True)
class GreyBoxStateVector:
    """Continuous PathSim state vector in project-owned types."""

    effective_fuel: float
    normalized_speed: float
    gas_temperature_c: float


@dataclass(frozen=True)
class GreyBoxInputs:
    """Held actuator and ambient inputs for one plant interval."""

    fuel_command: float
    starter_commanded: bool
    ignition_commanded: bool
    fuel_enabled: bool
    ambient_temperature_c: float
    ambient_pressure_pa: float


@dataclass(frozen=True)
class GreyBoxAlgebraicTerms:
    """Named nonlinear terms used by dynamics, diagnostics, and learning."""

    commanded_fuel: float
    combustion_effectiveness: float
    starter_torque: float
    turbine_torque: float
    compressor_load: float
    friction_load: float
    equilibrium_temperature_c: float
    thrust_n: float


def calculate_state_derivative(
    state: GreyBoxStateVector,
    inputs: GreyBoxInputs,
    parameters: PathSimGreyBoxConfig,
) -> GreyBoxStateVector:
    """Return the fuel, normalized-spool, and thermal state derivatives."""

    validate_state_and_inputs(state, inputs)
    terms = calculate_algebraic_terms(state, inputs, parameters)
    fuel_derivative = (
        terms.commanded_fuel - state.effective_fuel
    ) / parameters.fuel_time_constant_s
    net_drive = (
        terms.starter_torque
        + terms.turbine_torque
        - terms.compressor_load
        - terms.friction_load
    )
    speed_derivative = net_drive / parameters.normalized_inertia
    temperature_derivative = (
        terms.equilibrium_temperature_c - state.gas_temperature_c
    ) / parameters.thermal_time_constant_s

    if state.effective_fuel <= 0.0 and fuel_derivative < 0.0:
        fuel_derivative = 0.0
    if state.effective_fuel >= 1.0 and fuel_derivative > 0.0:
        fuel_derivative = 0.0
    if state.normalized_speed <= 0.0 and speed_derivative < 0.0:
        speed_derivative = 0.0
    if (
        state.normalized_speed >= parameters.maximum_normalized_speed
        and speed_derivative > 0.0
    ):
        speed_derivative = 0.0
    if (
        state.gas_temperature_c <= parameters.minimum_gas_temperature_c
        and temperature_derivative < 0.0
    ):
        temperature_derivative = 0.0

    derivative = GreyBoxStateVector(
        effective_fuel=fuel_derivative,
        normalized_speed=speed_derivative,
        gas_temperature_c=temperature_derivative,
    )
    _require_finite_values("state derivative", derivative)
    return derivative


def calculate_algebraic_terms(
    state: GreyBoxStateVector,
    inputs: GreyBoxInputs,
    parameters: PathSimGreyBoxConfig,
) -> GreyBoxAlgebraicTerms:
    """Calculate the documented torque, combustion, temperature, and thrust terms."""

    commanded_fuel = (
        clamp(inputs.fuel_command, 0.0, 1.0)
        if inputs.fuel_enabled
        else 0.0
    )
    combustion_effectiveness = calculate_combustion_effectiveness(
        state,
        inputs,
        parameters,
    )
    starter_torque = parameters.starter_torque_gain_per_s * float(
        inputs.starter_commanded
    )
    turbine_torque = (
        parameters.turbine_torque_gain_per_s
        * clamp(state.effective_fuel, 0.0, 1.0)
        * combustion_effectiveness
    )
    nonnegative_speed = max(state.normalized_speed, 0.0)
    compressor_load = (
        parameters.compressor_load_gain_per_s * nonnegative_speed**2
    )
    friction_load = parameters.friction_load_gain_per_s * nonnegative_speed
    combustion_temperature_rise_c = combustion_effectiveness * (
        parameters.combustion_base_temperature_rise_c
        + parameters.linear_fuel_temperature_gain_c * state.effective_fuel
        + parameters.quadratic_fuel_temperature_gain_c
        * state.effective_fuel**2
    )
    equilibrium_temperature_c = max(
        parameters.minimum_gas_temperature_c,
        inputs.ambient_temperature_c
        + combustion_temperature_rise_c
        - parameters.speed_temperature_cooling_gain_c * nonnegative_speed,
    )
    thrust_n = calculate_thrust_n(state, inputs, parameters)
    terms = GreyBoxAlgebraicTerms(
        commanded_fuel=commanded_fuel,
        combustion_effectiveness=combustion_effectiveness,
        starter_torque=starter_torque,
        turbine_torque=turbine_torque,
        compressor_load=compressor_load,
        friction_load=friction_load,
        equilibrium_temperature_c=equilibrium_temperature_c,
        thrust_n=thrust_n,
    )
    _require_finite_values("algebraic terms", terms)
    return terms


def calculate_combustion_effectiveness(
    state: GreyBoxStateVector,
    inputs: GreyBoxInputs,
    parameters: PathSimGreyBoxConfig,
) -> float:
    """Return bounded physical combustion support without FADEC-state knowledge."""

    if not inputs.fuel_enabled or state.effective_fuel <= 0.0:
        return 0.0
    speed_sustain = smooth_transition(
        state.normalized_speed,
        start=parameters.minimum_lightoff_speed_ratio,
        end=parameters.full_combustion_speed_ratio,
    )
    ignition_support = (
        parameters.ignition_effectiveness
        if inputs.ignition_commanded
        else 0.0
    )
    return clamp(max(speed_sustain, ignition_support), 0.0, 1.0)


def calculate_outputs(
    state: GreyBoxStateVector,
    inputs: GreyBoxInputs,
    parameters: PathSimGreyBoxConfig,
) -> EngineOutputs:
    """Calculate common algebraic plant outputs from the current state."""

    terms = calculate_algebraic_terms(state, inputs, parameters)
    return EngineOutputs(
        estimated_thrust_n=terms.thrust_n,
        estimated_fuel_flow_ml_min=(
            parameters.maximum_fuel_flow_ml_min
            * clamp(state.effective_fuel, 0.0, 1.0)
        ),
    )


def calculate_thrust_n(
    state: GreyBoxStateVector,
    inputs: GreyBoxInputs,
    parameters: PathSimGreyBoxConfig,
) -> float:
    """Estimate non-negative thrust with one documented pressure correction."""

    normalized_speed = clamp(
        state.normalized_speed,
        0.0,
        parameters.maximum_normalized_speed,
    )
    ambient_correction = clamp(
        inputs.ambient_pressure_pa / 101_325.0,
        0.5,
        1.2,
    )
    return max(
        0.0,
        parameters.maximum_thrust_n
        * normalized_speed**parameters.thrust_speed_exponent
        * ambient_correction,
    )


def constrain_state(
    state: GreyBoxStateVector,
    parameters: PathSimGreyBoxConfig,
) -> GreyBoxStateVector:
    """Apply documented state-domain guards after each exact solver substep."""

    _require_finite_values("integrated state", state)
    return GreyBoxStateVector(
        effective_fuel=clamp(state.effective_fuel, 0.0, 1.0),
        normalized_speed=clamp(
            state.normalized_speed,
            0.0,
            parameters.maximum_normalized_speed,
        ),
        gas_temperature_c=max(
            state.gas_temperature_c,
            parameters.minimum_gas_temperature_c,
        ),
    )


def validate_state_and_inputs(
    state: GreyBoxStateVector,
    inputs: GreyBoxInputs,
) -> None:
    """Reject non-finite state and input data before numerical integration."""

    _require_finite_values("state", state)
    for name, value in (
        ("fuel_command", inputs.fuel_command),
        ("ambient_temperature_c", inputs.ambient_temperature_c),
        ("ambient_pressure_pa", inputs.ambient_pressure_pa),
    ):
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
    if inputs.ambient_pressure_pa <= 0.0:
        raise ValueError("ambient_pressure_pa must be greater than zero")


def smooth_transition(value: float, *, start: float, end: float) -> float:
    """Return a cubic smoothstep between ordered lower and upper bounds."""

    if end <= start:
        raise ValueError("smooth transition end must be greater than start")
    fraction = clamp((value - start) / (end - start), 0.0, 1.0)
    return fraction * fraction * (3.0 - 2.0 * fraction)


def clamp(value: float, minimum: float, maximum: float) -> float:
    """Limit a finite value to one closed interval."""

    return max(minimum, min(value, maximum))


def _require_finite_values(label: str, value: object) -> None:
    for field_value in value.__dict__.values():
        if isinstance(field_value, (int, float)) and not math.isfinite(
            field_value
        ):
            raise ValueError(f"{label} contains a non-finite value")
