"""Unit tests for the configurable engine sensor model."""

from dataclasses import replace

import pytest

from simulation.core.types import EngineState
from simulation.sensors.sensor_model import (
    ConfigurableSensorModel,
    ExhaustTemperatureSensorConfiguration,
    RotorSpeedSensorConfiguration,
    SensorModelConfiguration,
)


NOISE_FREE_SPEED_CONFIGURATION = RotorSpeedSensorConfiguration(
    noise_standard_deviation_rpm=0.0,
    quantization_step_rpm=0.0,
)
NOISE_FREE_EGT_CONFIGURATION = ExhaustTemperatureSensorConfiguration(
    noise_standard_deviation_c=0.0,
    quantization_step_c=0.0,
)


def _sensor_model(
    rotor_speed: RotorSpeedSensorConfiguration = (
        NOISE_FREE_SPEED_CONFIGURATION
    ),
    exhaust_temperature: ExhaustTemperatureSensorConfiguration = (
        NOISE_FREE_EGT_CONFIGURATION
    ),
    random_seed: int | None = 0,
) -> ConfigurableSensorModel:
    """Create a sensor model with explicit test channel configurations."""

    return ConfigurableSensorModel(
        configuration=SensorModelConfiguration(
            rotor_speed=rotor_speed,
            exhaust_temperature=exhaust_temperature,
            random_seed=random_seed,
        )
    )


def test_zero_noise_and_bias_reproduce_truth_apart_from_quantization() -> None:
    sensor_model = _sensor_model(
        rotor_speed=replace(
            NOISE_FREE_SPEED_CONFIGURATION,
            quantization_step_rpm=10.0,
        ),
        exhaust_temperature=replace(
            NOISE_FREE_EGT_CONFIGURATION,
            quantization_step_c=0.5,
        ),
    )

    measurement = sensor_model.measure(
        EngineState(
            rotor_speed_rpm=12_344.0,
            exhaust_temperature_c=456.3,
        ),
        time_step_s=0.001,
    )

    assert measurement.rotor_speed_rpm == pytest.approx(12_340.0)
    assert measurement.exhaust_temperature_c == pytest.approx(456.5)


def test_configured_rotor_speed_bias_is_added() -> None:
    sensor_model = _sensor_model(
        rotor_speed=replace(
            NOISE_FREE_SPEED_CONFIGURATION,
            bias_rpm=125.0,
        )
    )

    measurement = sensor_model.measure(
        EngineState(rotor_speed_rpm=40_000.0, exhaust_temperature_c=450.0),
        time_step_s=0.01,
    )

    assert measurement.rotor_speed_rpm == pytest.approx(40_125.0)


def test_configured_egt_bias_is_added() -> None:
    sensor_model = _sensor_model(
        exhaust_temperature=replace(
            NOISE_FREE_EGT_CONFIGURATION,
            bias_c=-7.5,
        )
    )

    measurement = sensor_model.measure(
        EngineState(rotor_speed_rpm=39_000.0, exhaust_temperature_c=450.0),
        time_step_s=0.01,
    )

    assert measurement.exhaust_temperature_c == pytest.approx(442.5)


def test_zero_quantization_step_disables_quantization() -> None:
    sensor_model = _sensor_model()

    measurement = sensor_model.measure(
        EngineState(
            rotor_speed_rpm=12_345.67,
            exhaust_temperature_c=456.78,
        ),
        time_step_s=0.01,
    )

    assert measurement.rotor_speed_rpm == pytest.approx(12_345.67)
    assert measurement.exhaust_temperature_c == pytest.approx(456.78)


def test_positive_quantization_step_quantizes_around_zero() -> None:
    sensor_model = _sensor_model(
        rotor_speed=replace(
            NOISE_FREE_SPEED_CONFIGURATION,
            quantization_step_rpm=100.0,
        )
    )

    measurement = sensor_model.measure(
        EngineState(rotor_speed_rpm=12_349.0, exhaust_temperature_c=450.0),
        time_step_s=0.01,
    )

    assert measurement.rotor_speed_rpm == pytest.approx(12_300.0)


@pytest.mark.parametrize(
    "configuration_type",
    [RotorSpeedSensorConfiguration, ExhaustTemperatureSensorConfiguration],
)
def test_negative_quantization_step_is_rejected(
    configuration_type: type[
        RotorSpeedSensorConfiguration | ExhaustTemperatureSensorConfiguration
    ],
) -> None:
    keyword = (
        "quantization_step_rpm"
        if configuration_type is RotorSpeedSensorConfiguration
        else "quantization_step_c"
    )

    with pytest.raises(ValueError, match="quantization step cannot be negative"):
        configuration_type(**{keyword: -1.0})


def test_measurements_are_clamped_to_minimum_limits() -> None:
    sensor_model = _sensor_model()

    measurement = sensor_model.measure(
        EngineState(rotor_speed_rpm=-1_000.0, exhaust_temperature_c=-100.0),
        time_step_s=0.01,
    )

    assert measurement.rotor_speed_rpm == pytest.approx(0.0)
    assert measurement.exhaust_temperature_c == pytest.approx(-50.0)


def test_measurements_are_clamped_to_maximum_limits() -> None:
    sensor_model = _sensor_model()

    measurement = sensor_model.measure(
        EngineState(rotor_speed_rpm=200_000.0, exhaust_temperature_c=1_200.0),
        time_step_s=0.01,
    )

    assert measurement.rotor_speed_rpm == pytest.approx(150_000.0)
    assert measurement.exhaust_temperature_c == pytest.approx(1_000.0)


def test_identical_seeds_produce_identical_measurement_sequences() -> None:
    first_sensor_model = ConfigurableSensorModel()
    second_sensor_model = ConfigurableSensorModel()
    engine_state = EngineState(
        rotor_speed_rpm=75_000.0,
        exhaust_temperature_c=650.0,
    )

    first_sequence = [
        first_sensor_model.measure(engine_state, time_step_s=0.02)
        for _ in range(10)
    ]
    second_sequence = [
        second_sensor_model.measure(engine_state, time_step_s=0.02)
        for _ in range(10)
    ]

    assert first_sequence == second_sequence


def test_different_seeds_produce_different_noisy_measurement_sequences() -> None:
    first_sensor_model = _sensor_model(
        rotor_speed=replace(
            NOISE_FREE_SPEED_CONFIGURATION,
            noise_standard_deviation_rpm=50.0,
        ),
        random_seed=1,
    )
    second_sensor_model = _sensor_model(
        rotor_speed=replace(
            NOISE_FREE_SPEED_CONFIGURATION,
            noise_standard_deviation_rpm=50.0,
        ),
        random_seed=2,
    )
    engine_state = EngineState(
        rotor_speed_rpm=75_000.0,
        exhaust_temperature_c=650.0,
    )

    first_sequence = [
        first_sensor_model.measure(engine_state, time_step_s=0.01)
        for _ in range(5)
    ]
    second_sequence = [
        second_sensor_model.measure(engine_state, time_step_s=0.01)
        for _ in range(5)
    ]

    assert first_sequence != second_sequence


def test_zero_noise_is_deterministic_regardless_of_seed() -> None:
    engine_state = EngineState(
        rotor_speed_rpm=75_123.0,
        exhaust_temperature_c=651.25,
    )

    first_measurement = _sensor_model(random_seed=1).measure(
        engine_state,
        time_step_s=0.01,
    )
    second_measurement = _sensor_model(random_seed=2).measure(
        engine_state,
        time_step_s=0.01,
    )

    assert first_measurement == second_measurement


def test_rotor_speed_and_egt_can_use_different_sample_periods() -> None:
    sensor_model = _sensor_model(
        rotor_speed=replace(
            NOISE_FREE_SPEED_CONFIGURATION,
            sample_period_s=0.01,
        ),
        exhaust_temperature=replace(
            NOISE_FREE_EGT_CONFIGURATION,
            sample_period_s=0.02,
        ),
    )
    engine_state = EngineState(
        rotor_speed_rpm=10_000.0,
        exhaust_temperature_c=100.0,
    )
    sensor_model.measure(engine_state, time_step_s=0.005)
    engine_state.rotor_speed_rpm = 20_000.0
    engine_state.exhaust_temperature_c = 200.0

    sensor_model.measure(engine_state, time_step_s=0.005)
    measurement = sensor_model.measure(engine_state, time_step_s=0.005)

    assert measurement.rotor_speed_rpm == pytest.approx(20_000.0)
    assert measurement.exhaust_temperature_c == pytest.approx(100.0)


def test_channel_retains_previous_value_between_sample_instants() -> None:
    sensor_model = _sensor_model(
        rotor_speed=replace(
            NOISE_FREE_SPEED_CONFIGURATION,
            sample_period_s=0.02,
        )
    )
    engine_state = EngineState(
        rotor_speed_rpm=10_000.0,
        exhaust_temperature_c=450.0,
    )
    initial_measurement = sensor_model.measure(engine_state, time_step_s=0.005)
    engine_state.rotor_speed_rpm = 20_000.0

    retained_measurement = sensor_model.measure(
        engine_state,
        time_step_s=0.005,
    )

    assert retained_measurement.rotor_speed_rpm == pytest.approx(
        initial_measurement.rotor_speed_rpm
    )


def test_channels_update_independently() -> None:
    sensor_model = _sensor_model(
        rotor_speed=replace(
            NOISE_FREE_SPEED_CONFIGURATION,
            sample_period_s=0.01,
        ),
        exhaust_temperature=replace(
            NOISE_FREE_EGT_CONFIGURATION,
            sample_period_s=0.03,
        ),
    )
    engine_state = EngineState(
        rotor_speed_rpm=10_000.0,
        exhaust_temperature_c=100.0,
    )
    initial_measurement = sensor_model.measure(engine_state, time_step_s=0.01)
    engine_state.rotor_speed_rpm = 20_000.0
    engine_state.exhaust_temperature_c = 200.0

    updated_measurement = sensor_model.measure(engine_state, time_step_s=0.01)

    assert updated_measurement.rotor_speed_rpm == pytest.approx(20_000.0)
    assert updated_measurement.exhaust_temperature_c == pytest.approx(
        initial_measurement.exhaust_temperature_c
    )


def test_first_update_produces_valid_measurements_immediately() -> None:
    sensor_model = _sensor_model(
        rotor_speed=replace(
            NOISE_FREE_SPEED_CONFIGURATION,
            sample_period_s=1.0,
        ),
        exhaust_temperature=replace(
            NOISE_FREE_EGT_CONFIGURATION,
            sample_period_s=1.0,
        ),
    )

    measurement = sensor_model.measure(
        EngineState(rotor_speed_rpm=39_000.0, exhaust_temperature_c=450.0),
        time_step_s=0.001,
    )

    assert measurement.rotor_speed_rpm == pytest.approx(39_000.0)
    assert measurement.exhaust_temperature_c == pytest.approx(450.0)


@pytest.mark.parametrize("time_step_s", [0.0, -0.01])
def test_invalid_time_step_is_rejected(time_step_s: float) -> None:
    sensor_model = _sensor_model()

    with pytest.raises(
        ValueError,
        match="time_step_s must be greater than zero",
    ):
        sensor_model.measure(
            EngineState(rotor_speed_rpm=39_000.0, exhaust_temperature_c=450.0),
            time_step_s=time_step_s,
        )


def test_reset_restores_initial_sampling_behavior() -> None:
    sensor_model = _sensor_model(
        rotor_speed=replace(
            NOISE_FREE_SPEED_CONFIGURATION,
            sample_period_s=1.0,
        )
    )
    engine_state = EngineState(
        rotor_speed_rpm=10_000.0,
        exhaust_temperature_c=450.0,
    )
    sensor_model.measure(engine_state, time_step_s=0.01)
    engine_state.rotor_speed_rpm = 20_000.0
    retained_measurement = sensor_model.measure(engine_state, time_step_s=0.01)

    sensor_model.reset()
    reset_measurement = sensor_model.measure(engine_state, time_step_s=0.01)

    assert retained_measurement.rotor_speed_rpm == pytest.approx(10_000.0)
    assert reset_measurement.rotor_speed_rpm == pytest.approx(20_000.0)


def test_reset_restores_reproducible_seeded_behavior() -> None:
    sensor_model = ConfigurableSensorModel()
    engine_state = EngineState(
        rotor_speed_rpm=75_000.0,
        exhaust_temperature_c=650.0,
    )
    first_sequence = [
        sensor_model.measure(engine_state, time_step_s=0.02)
        for _ in range(5)
    ]

    sensor_model.reset()
    reset_sequence = [
        sensor_model.measure(engine_state, time_step_s=0.02)
        for _ in range(5)
    ]

    assert reset_sequence == first_sequence


def test_measurement_does_not_modify_engine_truth() -> None:
    sensor_model = ConfigurableSensorModel()
    engine_state = EngineState(
        rotor_speed_rpm=75_000.0,
        exhaust_temperature_c=650.0,
    )

    sensor_model.measure(engine_state, time_step_s=0.01)

    assert engine_state == EngineState(
        rotor_speed_rpm=75_000.0,
        exhaust_temperature_c=650.0,
    )
