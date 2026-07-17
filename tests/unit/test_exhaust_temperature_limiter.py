"""Unit tests for exhaust-temperature protection."""

import pytest

from simulation.core.types import ActuatorCommand, SensorData
from simulation.protection.exhaust_temperature_limiter import (
    ExhaustTemperatureLimiter,
)


def test_limiter_passes_fuel_through_below_intervention_temperature() -> None:
    limiter = ExhaustTemperatureLimiter()
    requested_command = ActuatorCommand(fuel_command=0.8)

    protected_command = limiter.apply(
        requested_command=requested_command,
        sensor_data=SensorData(
            rotor_speed_rpm=100_000.0,
            exhaust_temperature_c=640.0,
        ),
        time_step_s=0.01,
    )

    assert protected_command.fuel_command == pytest.approx(0.8)


def test_limiter_progressively_reduces_fuel_in_intervention_region() -> None:
    limiter = ExhaustTemperatureLimiter()

    protected_command = limiter.apply(
        requested_command=ActuatorCommand(fuel_command=0.8),
        sensor_data=SensorData(
            rotor_speed_rpm=100_000.0,
            exhaust_temperature_c=665.0,
        ),
        time_step_s=0.01,
    )

    assert protected_command.fuel_command == pytest.approx(0.5)


def test_limiter_reduces_fuel_more_strongly_at_maximum_temperature() -> None:
    limiter = ExhaustTemperatureLimiter()
    requested_command = ActuatorCommand(fuel_command=1.0)

    intervention_command = limiter.apply(
        requested_command=requested_command,
        sensor_data=SensorData(
            rotor_speed_rpm=100_000.0,
            exhaust_temperature_c=665.0,
        ),
        time_step_s=0.01,
    )
    maximum_temperature_command = limiter.apply(
        requested_command=requested_command,
        sensor_data=SensorData(
            rotor_speed_rpm=100_000.0,
            exhaust_temperature_c=680.0,
        ),
        time_step_s=0.01,
    )

    assert (
        maximum_temperature_command.fuel_command
        < intervention_command.fuel_command
    )
    assert maximum_temperature_command.fuel_command == pytest.approx(0.4)


def test_limiter_adds_stronger_reduction_above_maximum_temperature() -> None:
    limiter = ExhaustTemperatureLimiter()

    protected_command = limiter.apply(
        requested_command=ActuatorCommand(fuel_command=1.0),
        sensor_data=SensorData(
            rotor_speed_rpm=100_000.0,
            exhaust_temperature_c=685.0,
        ),
        time_step_s=0.01,
    )

    assert protected_command.fuel_command == pytest.approx(0.2)


@pytest.mark.parametrize("requested_fuel_command", [0.0, 0.4, 1.0])
def test_limiter_never_increases_requested_fuel(
    requested_fuel_command: float,
) -> None:
    limiter = ExhaustTemperatureLimiter()

    protected_command = limiter.apply(
        requested_command=ActuatorCommand(
            fuel_command=requested_fuel_command,
        ),
        sensor_data=SensorData(
            rotor_speed_rpm=100_000.0,
            exhaust_temperature_c=700.0,
        ),
        time_step_s=0.01,
    )

    assert 0.0 <= protected_command.fuel_command <= 1.0
    assert protected_command.fuel_command <= requested_fuel_command


def test_limiter_rejects_invalid_time_step() -> None:
    limiter = ExhaustTemperatureLimiter()

    with pytest.raises(
        ValueError,
        match="time_step_s must be greater than zero",
    ):
        limiter.apply(
            requested_command=ActuatorCommand(fuel_command=0.8),
            sensor_data=SensorData(
                rotor_speed_rpm=100_000.0,
                exhaust_temperature_c=660.0,
            ),
            time_step_s=0.0,
        )
