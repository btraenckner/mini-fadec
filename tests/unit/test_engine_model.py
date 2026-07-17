"""Unit tests for the simplified engine model."""

import pytest

from simulation.core.types import ActuatorCommand, AmbientConditions
from simulation.models.engine_model import EngineModelParameters, FirstOrderEngineModel


def test_engine_starts_at_idle_speed() -> None:
    engine_model = FirstOrderEngineModel()

    assert engine_model.state.rotor_speed_rpm == pytest.approx(39_000.0)


def test_engine_starts_at_idle_exhaust_temperature() -> None:
    engine_model = FirstOrderEngineModel()

    assert engine_model.state.exhaust_temperature_c == pytest.approx(450.0)


def test_full_fuel_command_accelerates_engine() -> None:
    engine_model = FirstOrderEngineModel()
    ambient_conditions = AmbientConditions()

    time_step_s = 0.01
    number_of_steps = int(3.0 / time_step_s)

    for _ in range(number_of_steps):
        engine_model.step(
            actuator_command=ActuatorCommand(
                fuel_command=1.0,
            ),
            ambient_conditions=ambient_conditions,
            time_step_s=time_step_s,
        )

    assert engine_model.state.rotor_speed_rpm > 123_000.0
    assert engine_model.state.rotor_speed_rpm < 128_000.0


def test_higher_fuel_command_increases_exhaust_temperature() -> None:
    lower_fuel_engine_model = FirstOrderEngineModel()
    higher_fuel_engine_model = FirstOrderEngineModel()

    lower_fuel_engine_model.step(
        actuator_command=ActuatorCommand(
            fuel_command=0.4,
        ),
        ambient_conditions=AmbientConditions(),
        time_step_s=0.01,
    )
    higher_fuel_engine_model.step(
        actuator_command=ActuatorCommand(
            fuel_command=0.8,
        ),
        ambient_conditions=AmbientConditions(),
        time_step_s=0.01,
    )

    assert (
        higher_fuel_engine_model.state.exhaust_temperature_c
        > lower_fuel_engine_model.state.exhaust_temperature_c
    )


def test_full_fuel_command_causes_transient_exhaust_temperature_peak() -> None:
    engine_model = FirstOrderEngineModel()
    ambient_conditions = AmbientConditions()

    time_step_s = 0.01
    number_of_steps = int(1.5 / time_step_s)

    for _ in range(number_of_steps):
        engine_model.step(
            actuator_command=ActuatorCommand(
                fuel_command=1.0,
            ),
            ambient_conditions=ambient_conditions,
            time_step_s=time_step_s,
        )

    assert engine_model.state.exhaust_temperature_c > 730.0


def test_increasing_rotor_speed_reduces_exhaust_temperature() -> None:
    low_speed_engine_model = FirstOrderEngineModel()
    high_speed_engine_model = FirstOrderEngineModel()
    low_speed_engine_model.state.exhaust_temperature_c = 600.0
    high_speed_engine_model.state.exhaust_temperature_c = 600.0
    high_speed_engine_model.state.rotor_speed_rpm = 128_000.0

    for engine_model in (low_speed_engine_model, high_speed_engine_model):
        engine_model.step(
            actuator_command=ActuatorCommand(fuel_command=0.8),
            ambient_conditions=AmbientConditions(),
            time_step_s=0.01,
        )

    assert (
        high_speed_engine_model.state.exhaust_temperature_c
        < low_speed_engine_model.state.exhaust_temperature_c
    )


def test_excess_fuel_adds_transient_exhaust_heating() -> None:
    engine_model = FirstOrderEngineModel()
    engine_model_without_transient_heating = FirstOrderEngineModel(
        parameters=EngineModelParameters(acceleration_egt_gain_c=0.0)
    )

    for model in (engine_model, engine_model_without_transient_heating):
        model.step(
            actuator_command=ActuatorCommand(fuel_command=1.0),
            ambient_conditions=AmbientConditions(),
            time_step_s=0.01,
        )

    assert (
        engine_model.state.exhaust_temperature_c
        > engine_model_without_transient_heating.state.exhaust_temperature_c
    )


@pytest.mark.parametrize(
    ("fuel_command", "expected_exhaust_temperature_c"),
    [
        (0.5, 550.0),
        (1.0, 650.0),
    ],
)
def test_exhaust_temperature_settles_with_speed_cooling(
    fuel_command: float,
    expected_exhaust_temperature_c: float,
) -> None:
    engine_model = FirstOrderEngineModel()
    time_step_s = 0.01

    for _ in range(int(10.0 / time_step_s)):
        engine_model.step(
            actuator_command=ActuatorCommand(fuel_command=fuel_command),
            ambient_conditions=AmbientConditions(),
            time_step_s=time_step_s,
        )

    assert engine_model.state.exhaust_temperature_c == pytest.approx(
        expected_exhaust_temperature_c,
        abs=1.0,
    )


def test_zero_fuel_keeps_exhaust_temperature_at_idle() -> None:
    engine_model = FirstOrderEngineModel()
    ambient_conditions = AmbientConditions()

    time_step_s = 0.01
    number_of_steps = int(1.5 / time_step_s)

    for _ in range(number_of_steps):
        engine_model.step(
            actuator_command=ActuatorCommand(
                fuel_command=0.0,
            ),
            ambient_conditions=ambient_conditions,
            time_step_s=time_step_s,
        )

    assert engine_model.state.exhaust_temperature_c == pytest.approx(450.0)


def test_invalid_time_step_is_rejected() -> None:
    engine_model = FirstOrderEngineModel()

    with pytest.raises(
        ValueError,
        match="time_step_s must be greater than zero",
    ):
        engine_model.step(
            actuator_command=ActuatorCommand(
                fuel_command=0.5,
            ),
            ambient_conditions=AmbientConditions(),
            time_step_s=0.0,
        )
