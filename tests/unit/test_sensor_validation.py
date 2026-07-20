"""Unit tests for time-based sensor signal validation."""

from dataclasses import replace

import pytest

from simulation.core.types import RawSensorData
from simulation.operation.engine_state import EngineOperatingState
from simulation.validation.sensor_validation import (
    ChannelDiagnosticReason,
    ChannelHealth,
    ExhaustTemperatureValidationConfiguration,
    RotorSpeedValidationConfiguration,
    SensorSignalValidator,
    SensorValidationConfiguration,
    SensorValidationContext,
)


VALID_RAW_DATA = RawSensorData(
    rotor_speed_rpm=50_000.0,
    exhaust_temperature_c=600.0,
)
OFF_CONTEXT = SensorValidationContext()


def test_valid_values_remain_valid() -> None:
    validator = SensorSignalValidator()

    result = validator.update(VALID_RAW_DATA, OFF_CONTEXT, time_step_s=0.01)

    assert result.rotor_speed.health is ChannelHealth.VALID
    assert result.exhaust_temperature.health is ChannelHealth.VALID
    assert result.sensor_data.rotor_speed_rpm == pytest.approx(50_000.0)
    assert result.sensor_data.exhaust_temperature_c == pytest.approx(600.0)


def test_unavailable_measurement_uses_configured_invalidation_persistence() -> None:
    validator = SensorSignalValidator(
        SensorValidationConfiguration(
            rotor_speed=RotorSpeedValidationConfiguration(
                unavailable_persistence_s=0.03
            )
        )
    )
    validator.update(VALID_RAW_DATA, OFF_CONTEXT, time_step_s=0.01)
    unavailable_data = replace(VALID_RAW_DATA, rotor_speed_rpm=None)

    first_result = validator.update(
        unavailable_data,
        OFF_CONTEXT,
        time_step_s=0.01,
    )
    validator.update(unavailable_data, OFF_CONTEXT, time_step_s=0.01)
    invalid_result = validator.update(
        unavailable_data,
        OFF_CONTEXT,
        time_step_s=0.01,
    )

    assert first_result.rotor_speed.health is ChannelHealth.SUSPECT
    assert invalid_result.rotor_speed.health is ChannelHealth.INVALID
    assert (
        invalid_result.rotor_speed.diagnostic_reason
        is ChannelDiagnosticReason.MEASUREMENT_UNAVAILABLE
    )


def test_out_of_range_rotor_speed_is_detected() -> None:
    validator = SensorSignalValidator()
    validator.update(VALID_RAW_DATA, OFF_CONTEXT, time_step_s=0.01)

    result = validator.update(
        replace(VALID_RAW_DATA, rotor_speed_rpm=150_000.0),
        OFF_CONTEXT,
        time_step_s=0.01,
    )

    assert result.rotor_speed.health is ChannelHealth.SUSPECT
    assert (
        result.rotor_speed.diagnostic_reason
        is ChannelDiagnosticReason.ABOVE_PHYSICAL_RANGE
    )


def test_out_of_range_egt_is_detected() -> None:
    validator = SensorSignalValidator()
    validator.update(VALID_RAW_DATA, OFF_CONTEXT, time_step_s=0.01)

    result = validator.update(
        replace(VALID_RAW_DATA, exhaust_temperature_c=1_000.0),
        OFF_CONTEXT,
        time_step_s=0.01,
    )

    assert result.exhaust_temperature.health is ChannelHealth.SUSPECT
    assert (
        result.exhaust_temperature.diagnostic_reason
        is ChannelDiagnosticReason.ABOVE_PHYSICAL_RANGE
    )


def test_excessive_rotor_speed_rate_is_detected() -> None:
    validator = SensorSignalValidator()
    validator.update(VALID_RAW_DATA, OFF_CONTEXT, time_step_s=0.01)

    result = validator.update(
        replace(VALID_RAW_DATA, rotor_speed_rpm=51_000.0),
        OFF_CONTEXT,
        time_step_s=0.01,
    )

    assert result.rotor_speed.health is ChannelHealth.SUSPECT
    assert (
        result.rotor_speed.diagnostic_reason
        is ChannelDiagnosticReason.RATE_THRESHOLD_VIOLATION
    )


def test_excessive_egt_rate_is_detected() -> None:
    validator = SensorSignalValidator()
    validator.update(VALID_RAW_DATA, OFF_CONTEXT, time_step_s=0.01)

    result = validator.update(
        replace(VALID_RAW_DATA, exhaust_temperature_c=620.0),
        OFF_CONTEXT,
        time_step_s=0.01,
    )

    assert result.exhaust_temperature.health is ChannelHealth.SUSPECT
    assert (
        result.exhaust_temperature.diagnostic_reason
        is ChannelDiagnosticReason.RATE_THRESHOLD_VIOLATION
    )


def test_single_transient_violation_is_suspect_not_immediately_invalid() -> None:
    validator = SensorSignalValidator()
    validator.update(VALID_RAW_DATA, OFF_CONTEXT, time_step_s=0.01)

    result = validator.update(
        replace(VALID_RAW_DATA, rotor_speed_rpm=150_000.0),
        OFF_CONTEXT,
        time_step_s=0.01,
    )

    assert result.rotor_speed.health is ChannelHealth.SUSPECT
    assert result.rotor_speed.value_is_held
    assert result.rotor_speed.value == pytest.approx(50_000.0)


def test_sustained_violation_becomes_invalid() -> None:
    validator = SensorSignalValidator()
    validator.update(VALID_RAW_DATA, OFF_CONTEXT, time_step_s=0.01)
    invalid_data = replace(VALID_RAW_DATA, rotor_speed_rpm=150_000.0)

    for _ in range(10):
        result = validator.update(invalid_data, OFF_CONTEXT, time_step_s=0.01)

    assert result.rotor_speed.health is ChannelHealth.INVALID


def test_sustained_valid_input_recovers_invalid_through_suspect() -> None:
    validator = SensorSignalValidator()
    validator.update(VALID_RAW_DATA, OFF_CONTEXT, time_step_s=0.01)
    unavailable_data = replace(VALID_RAW_DATA, rotor_speed_rpm=None)
    invalid_result = validator.update(
        unavailable_data,
        OFF_CONTEXT,
        time_step_s=0.01,
    )

    recovering_result = validator.update(
        VALID_RAW_DATA,
        OFF_CONTEXT,
        time_step_s=0.01,
    )
    for _ in range(19):
        recovered_result = validator.update(
            VALID_RAW_DATA,
            OFF_CONTEXT,
            time_step_s=0.01,
        )

    assert invalid_result.rotor_speed.health is ChannelHealth.INVALID
    assert recovering_result.rotor_speed.health is ChannelHealth.SUSPECT
    assert recovered_result.rotor_speed.health is ChannelHealth.VALID


def test_stuck_rotor_speed_is_detected_while_starter_is_commanded() -> None:
    validator = SensorSignalValidator()
    cranking_context = SensorValidationContext(
        operating_state=EngineOperatingState.CRANKING,
        starter_commanded=True,
    )

    for _ in range(40):
        result = validator.update(
            VALID_RAW_DATA,
            cranking_context,
            time_step_s=0.01,
        )

    assert result.rotor_speed.health is ChannelHealth.INVALID
    assert (
        result.rotor_speed.diagnostic_reason
        is ChannelDiagnosticReason.STUCK_SIGNAL
    )


def test_stopped_rotor_in_off_does_not_trigger_stuck_detection() -> None:
    validator = SensorSignalValidator()
    stopped_data = RawSensorData(
        rotor_speed_rpm=0.0,
        exhaust_temperature_c=15.0,
    )

    for _ in range(100):
        result = validator.update(
            stopped_data,
            OFF_CONTEXT,
            time_step_s=0.01,
        )

    assert result.rotor_speed.health is ChannelHealth.VALID


def test_stuck_egt_is_detected_during_ignition() -> None:
    validator = SensorSignalValidator()
    ignition_context = SensorValidationContext(
        operating_state=EngineOperatingState.IGNITION,
        ignition_commanded=True,
        fuel_enabled=True,
        fuel_command=0.25,
    )

    for index in range(40):
        result = validator.update(
            RawSensorData(
                rotor_speed_rpm=50_000.0 + index * 100.0,
                exhaust_temperature_c=600.0,
            ),
            ignition_context,
            time_step_s=0.01,
        )

    assert result.exhaust_temperature.health is ChannelHealth.INVALID
    assert (
        result.exhaust_temperature.diagnostic_reason
        is ChannelDiagnosticReason.STUCK_SIGNAL
    )


def test_stable_egt_at_steady_operating_point_is_not_stuck() -> None:
    validator = SensorSignalValidator()
    steady_context = SensorValidationContext(
        operating_state=EngineOperatingState.RUNNING,
        fuel_enabled=True,
        fuel_command=0.5,
        throttle_command=0.5,
    )

    for _ in range(100):
        result = validator.update(
            VALID_RAW_DATA,
            steady_context,
            time_step_s=0.01,
        )

    assert result.exhaust_temperature.health is ChannelHealth.VALID


def test_last_known_valid_value_is_held_during_short_invalid_period() -> None:
    validator = SensorSignalValidator()
    validator.update(VALID_RAW_DATA, OFF_CONTEXT, time_step_s=0.01)

    result = validator.update(
        replace(VALID_RAW_DATA, exhaust_temperature_c=None),
        OFF_CONTEXT,
        time_step_s=0.01,
    )

    assert result.exhaust_temperature.health is ChannelHealth.INVALID
    assert result.exhaust_temperature.value == pytest.approx(600.0)
    assert result.exhaust_temperature.value_is_held


def test_last_known_valid_hold_expires() -> None:
    validator = SensorSignalValidator(
        SensorValidationConfiguration(
            exhaust_temperature=ExhaustTemperatureValidationConfiguration(
                last_valid_hold_time_s=0.02
            )
        )
    )
    validator.update(VALID_RAW_DATA, OFF_CONTEXT, time_step_s=0.01)
    unavailable_data = replace(VALID_RAW_DATA, exhaust_temperature_c=None)

    validator.update(unavailable_data, OFF_CONTEXT, time_step_s=0.01)
    validator.update(unavailable_data, OFF_CONTEXT, time_step_s=0.01)
    result = validator.update(unavailable_data, OFF_CONTEXT, time_step_s=0.01)

    assert result.exhaust_temperature.health is ChannelHealth.INVALID
    assert result.exhaust_temperature.value is None
    assert result.exhaust_temperature.value_is_held is False


def test_reset_restores_initial_validator_behavior() -> None:
    validator = SensorSignalValidator()
    validator.update(VALID_RAW_DATA, OFF_CONTEXT, time_step_s=0.01)
    validator.update(
        replace(VALID_RAW_DATA, rotor_speed_rpm=None),
        OFF_CONTEXT,
        time_step_s=0.01,
    )

    validator.reset()
    result = validator.update(VALID_RAW_DATA, OFF_CONTEXT, time_step_s=0.01)

    assert result.rotor_speed.health is ChannelHealth.VALID
    assert result.rotor_speed.diagnostic_reason is ChannelDiagnosticReason.NONE


def test_rotor_speed_and_egt_health_states_are_independent() -> None:
    validator = SensorSignalValidator()
    validator.update(VALID_RAW_DATA, OFF_CONTEXT, time_step_s=0.01)

    result = validator.update(
        replace(VALID_RAW_DATA, rotor_speed_rpm=None),
        OFF_CONTEXT,
        time_step_s=0.01,
    )

    assert result.rotor_speed.health is ChannelHealth.INVALID
    assert result.exhaust_temperature.health is ChannelHealth.VALID


def test_aggregate_status_reports_most_severe_channel_health() -> None:
    validator = SensorSignalValidator()
    validator.update(VALID_RAW_DATA, OFF_CONTEXT, time_step_s=0.01)

    result = validator.update(
        RawSensorData(
            rotor_speed_rpm=None,
            exhaust_temperature_c=1_000.0,
        ),
        OFF_CONTEXT,
        time_step_s=0.01,
    )

    assert result.rotor_speed.health is ChannelHealth.INVALID
    assert result.exhaust_temperature.health is ChannelHealth.SUSPECT
    assert result.aggregate_health is ChannelHealth.INVALID


def test_invalid_time_step_is_rejected() -> None:
    validator = SensorSignalValidator()

    with pytest.raises(
        ValueError,
        match="time_step_s must be greater than zero",
    ):
        validator.update(VALID_RAW_DATA, OFF_CONTEXT, time_step_s=0.0)
