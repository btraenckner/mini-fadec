"""Unit tests for the simplified engine model."""

import pytest

from simulation.core.types import ActuatorCommand, AmbientConditions
from simulation.models.engine_model import FirstOrderEngineModel


def test_engine_starts_at_idle_speed() -> None:
    engine_model = FirstOrderEngineModel()

    assert engine_model.state.rotor_speed_rpm == pytest.approx(39_000.0)


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
