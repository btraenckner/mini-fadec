"""Unit tests for deterministic sensor fault injection."""

import pytest

from simulation.core.types import RawSensorData, SensorData
from simulation.sensors.fault_injection import (
    BiasSensorFault,
    DriftSensorFault,
    DropoutSensorFault,
    ExcessiveNoiseSensorFault,
    ForcedValueSensorFault,
    SensorChannel,
    SensorFaultInjector,
    StuckSensorFault,
)


NOMINAL_SENSOR_DATA = SensorData(
    rotor_speed_rpm=50_000.0,
    exhaust_temperature_c=600.0,
)


def test_bias_fault_adds_configured_offset() -> None:
    fault_injector = SensorFaultInjector()
    fault_injector.activate(
        SensorChannel.ROTOR_SPEED,
        BiasSensorFault(offset=5_000.0),
    )

    measurement = fault_injector.apply(NOMINAL_SENSOR_DATA, time_step_s=0.01)

    assert measurement.rotor_speed_rpm == pytest.approx(55_000.0)


def test_stuck_current_fault_freezes_activation_value() -> None:
    fault_injector = SensorFaultInjector()
    fault_injector.activate(
        SensorChannel.ROTOR_SPEED,
        StuckSensorFault(),
        current_measurement=50_000.0,
    )

    measurement = fault_injector.apply(
        SensorData(rotor_speed_rpm=60_000.0, exhaust_temperature_c=600.0),
        time_step_s=0.01,
    )

    assert measurement.rotor_speed_rpm == pytest.approx(50_000.0)


def test_stuck_explicit_value_fault_uses_configured_value() -> None:
    fault_injector = SensorFaultInjector()
    fault_injector.activate(
        SensorChannel.EXHAUST_TEMPERATURE,
        StuckSensorFault(value=700.0),
    )

    measurement = fault_injector.apply(NOMINAL_SENSOR_DATA, time_step_s=0.01)

    assert measurement.exhaust_temperature_c == pytest.approx(700.0)


def test_dropout_produces_explicit_unavailable_measurement() -> None:
    fault_injector = SensorFaultInjector()
    fault_injector.activate(
        SensorChannel.EXHAUST_TEMPERATURE,
        DropoutSensorFault(),
    )

    measurement = fault_injector.apply(NOMINAL_SENSOR_DATA, time_step_s=0.01)

    assert measurement.exhaust_temperature_c is None
    assert measurement.rotor_speed_rpm == pytest.approx(50_000.0)


def test_forced_value_fault_publishes_configured_value() -> None:
    fault_injector = SensorFaultInjector()
    fault_injector.activate(
        SensorChannel.ROTOR_SPEED,
        ForcedValueSensorFault(value=200_000.0),
    )

    measurement = fault_injector.apply(NOMINAL_SENSOR_DATA, time_step_s=0.01)

    assert measurement.rotor_speed_rpm == pytest.approx(200_000.0)


def test_excessive_noise_fault_is_deterministic_with_fixed_seed() -> None:
    first_injector = SensorFaultInjector(random_seed=42)
    second_injector = SensorFaultInjector(random_seed=42)
    for fault_injector in (first_injector, second_injector):
        fault_injector.activate(
            SensorChannel.ROTOR_SPEED,
            ExcessiveNoiseSensorFault(standard_deviation=1_000.0),
        )

    first_sequence = [
        first_injector.apply(NOMINAL_SENSOR_DATA, time_step_s=0.01)
        for _ in range(5)
    ]
    second_sequence = [
        second_injector.apply(NOMINAL_SENSOR_DATA, time_step_s=0.01)
        for _ in range(5)
    ]

    assert first_sequence == second_sequence


def test_drift_increases_with_elapsed_fault_time() -> None:
    fault_injector = SensorFaultInjector()
    fault_injector.activate(
        SensorChannel.EXHAUST_TEMPERATURE,
        DriftSensorFault(rate_per_second=20.0),
    )

    first_measurement = fault_injector.apply(
        NOMINAL_SENSOR_DATA,
        time_step_s=0.1,
    )
    second_measurement = fault_injector.apply(
        NOMINAL_SENSOR_DATA,
        time_step_s=0.1,
    )

    assert first_measurement.exhaust_temperature_c == pytest.approx(600.0)
    assert second_measurement.exhaust_temperature_c == pytest.approx(602.0)


def test_clearing_fault_restores_normal_sensor_model_output() -> None:
    fault_injector = SensorFaultInjector()
    fault_injector.activate(
        SensorChannel.ROTOR_SPEED,
        DropoutSensorFault(),
    )
    fault_injector.apply(NOMINAL_SENSOR_DATA, time_step_s=0.01)

    fault_injector.clear(SensorChannel.ROTOR_SPEED)
    measurement = fault_injector.apply(NOMINAL_SENSOR_DATA, time_step_s=0.01)

    assert measurement == RawSensorData(
        rotor_speed_rpm=50_000.0,
        exhaust_temperature_c=600.0,
    )


def test_new_fault_explicitly_replaces_existing_channel_fault() -> None:
    fault_injector = SensorFaultInjector()
    fault_injector.activate(
        SensorChannel.ROTOR_SPEED,
        BiasSensorFault(offset=5_000.0),
    )

    fault_injector.activate(
        SensorChannel.ROTOR_SPEED,
        ForcedValueSensorFault(value=100_000.0),
    )
    measurement = fault_injector.apply(NOMINAL_SENSOR_DATA, time_step_s=0.01)

    assert isinstance(
        fault_injector.active_fault(SensorChannel.ROTOR_SPEED),
        ForcedValueSensorFault,
    )
    assert measurement.rotor_speed_rpm == pytest.approx(100_000.0)


def test_rotor_speed_and_egt_faults_operate_independently() -> None:
    fault_injector = SensorFaultInjector()
    fault_injector.activate(
        SensorChannel.ROTOR_SPEED,
        BiasSensorFault(offset=1_000.0),
    )
    fault_injector.activate(
        SensorChannel.EXHAUST_TEMPERATURE,
        DropoutSensorFault(),
    )

    measurement = fault_injector.apply(NOMINAL_SENSOR_DATA, time_step_s=0.01)

    assert measurement.rotor_speed_rpm == pytest.approx(51_000.0)
    assert measurement.exhaust_temperature_c is None


def test_reset_clears_fault_timers_and_retained_values() -> None:
    fault_injector = SensorFaultInjector()
    fault_injector.activate(
        SensorChannel.EXHAUST_TEMPERATURE,
        DriftSensorFault(rate_per_second=20.0),
    )
    fault_injector.apply(NOMINAL_SENSOR_DATA, time_step_s=0.1)
    fault_injector.apply(NOMINAL_SENSOR_DATA, time_step_s=0.1)

    fault_injector.reset()
    fault_injector.activate(
        SensorChannel.EXHAUST_TEMPERATURE,
        DriftSensorFault(rate_per_second=20.0),
    )
    measurement = fault_injector.apply(NOMINAL_SENSOR_DATA, time_step_s=0.1)

    assert measurement.exhaust_temperature_c == pytest.approx(600.0)


def test_reset_restores_deterministic_noise_sequence() -> None:
    fault_injector = SensorFaultInjector(random_seed=42)
    fault = ExcessiveNoiseSensorFault(standard_deviation=1_000.0)
    fault_injector.activate(SensorChannel.ROTOR_SPEED, fault)
    first_sequence = [
        fault_injector.apply(NOMINAL_SENSOR_DATA, time_step_s=0.01)
        for _ in range(5)
    ]

    fault_injector.reset()
    fault_injector.activate(SensorChannel.ROTOR_SPEED, fault)
    reset_sequence = [
        fault_injector.apply(NOMINAL_SENSOR_DATA, time_step_s=0.01)
        for _ in range(5)
    ]

    assert reset_sequence == first_sequence


def test_invalid_time_step_is_rejected() -> None:
    fault_injector = SensorFaultInjector()

    with pytest.raises(
        ValueError,
        match="time_step_s must be greater than zero",
    ):
        fault_injector.apply(NOMINAL_SENSOR_DATA, time_step_s=0.0)


def test_negative_excessive_noise_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="fault noise standard deviation cannot be negative",
    ):
        ExcessiveNoiseSensorFault(standard_deviation=-1.0)
