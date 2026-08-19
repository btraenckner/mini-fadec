"""Tests for versioned engine definitions and FADEC calibration."""

import json
from dataclasses import replace

import pytest

from simulation.application.factory import create_application
from simulation.configuration import (
    ConfigurationCompatibilityError,
    reference_engine_definition,
    reference_fadec_calibration,
    validate_engine_fadec_compatibility,
)
from simulation.controllers.speed_controller import (
    LinearThrottleToSpeedScheduler,
)
from simulation.plants.types import PlantModelKind
from simulation.sensors.sensor_model import (
    RotorSpeedSensorConfiguration,
)


def test_reference_engine_and_calibration_are_compatible_and_serializable() -> (
    None
):
    engine_definition = reference_engine_definition()
    fadec_calibration = reference_fadec_calibration()

    validate_engine_fadec_compatibility(
        engine_definition,
        fadec_calibration,
    )

    engine_snapshot = engine_definition.to_dict()
    calibration_snapshot = fadec_calibration.to_dict()
    json.dumps(engine_snapshot)
    json.dumps(calibration_snapshot)
    assert engine_snapshot["plant"]["model"] == "first_order"  # type: ignore[index]
    assert calibration_snapshot["target_engine_id"] == (
        engine_definition.engine_id
    )


def test_compatibility_rejects_calibration_for_a_different_engine() -> None:
    calibration = replace(
        reference_fadec_calibration(),
        target_engine_id="other-engine",
    )

    with pytest.raises(ConfigurationCompatibilityError) as error:
        validate_engine_fadec_compatibility(
            reference_engine_definition(),
            calibration,
        )

    assert {issue.code for issue in error.value.issues} == {"target_engine"}


def test_compatibility_rejects_schedule_above_engine_envelope() -> None:
    calibration = replace(
        reference_fadec_calibration(),
        speed_schedule=LinearThrottleToSpeedScheduler(
            idle_speed_rpm=39_000.0,
            maximum_speed_rpm=130_000.0,
        ),
    )

    with pytest.raises(ConfigurationCompatibilityError) as error:
        validate_engine_fadec_compatibility(
            reference_engine_definition(),
            calibration,
        )

    issue_codes = {issue.code for issue in error.value.issues}
    assert "maximum_speed" in issue_codes
    assert "overspeed_reference" in issue_codes


def test_compatibility_rejects_sensor_range_below_protection_threshold() -> None:
    engine_definition = reference_engine_definition()
    engine_definition = replace(
        engine_definition,
        sensors=replace(
            engine_definition.sensors,
            rotor_speed=RotorSpeedSensorConfiguration(
                maximum_value_rpm=130_000.0
            ),
        ),
    )

    with pytest.raises(ConfigurationCompatibilityError) as error:
        validate_engine_fadec_compatibility(
            engine_definition,
            reference_fadec_calibration(),
        )

    issue_codes = {issue.code for issue in error.value.issues}
    assert "rotor_speed_sensor_range" in issue_codes
    assert "rotor_speed_range_alignment" in issue_codes


def test_application_composes_runtime_from_explicit_profiles() -> None:
    engine_definition = replace(
        reference_engine_definition(),
        engine_id="test-engine",
        sensors=replace(
            reference_engine_definition().sensors,
            rotor_speed=RotorSpeedSensorConfiguration(
                noise_standard_deviation_rpm=0.0,
            ),
        ),
    )
    calibration = replace(
        reference_fadec_calibration(),
        target_engine_id="test-engine",
        calibration_id="test-calibration",
    )

    service = create_application(
        engine_definition=engine_definition,
        fadec_calibration=calibration,
        sensor_random_seed=42,
    )

    assert service.engine_definition is engine_definition
    assert service.fadec_calibration is calibration
    assert service.coordinator.speed_controller.scheduler == (
        calibration.speed_schedule
    )
    assert service.coordinator.protection_manager.parameters == (
        calibration.fuel_protection.manager
    )
    assert service.coordinator.sensor_model.configuration.random_seed == 42
    assert (
        service.coordinator.sensor_model.configuration.rotor_speed
        .noise_standard_deviation_rpm
        == 0.0
    )


def test_plant_switch_preserves_engine_identity_and_fadec_calibration() -> None:
    service = create_application()
    calibration = service.fadec_calibration

    service.select_plant_model(PlantModelKind.PATHSIM_GREYBOX_V1)

    assert service.engine_definition is not None
    assert service.engine_definition.plant.model is (
        PlantModelKind.PATHSIM_GREYBOX_V1
    )
    assert service.fadec_calibration is calibration
    assert service.coordinator.speed_controller.parameters == (
        calibration.speed_controller  # type: ignore[union-attr]
    )


def test_application_rejects_engine_definition_and_plant_override() -> None:
    with pytest.raises(ValueError, match="either engine_definition"):
        create_application(
            engine_definition=reference_engine_definition(),
            plant_config=reference_engine_definition().plant,
        )


def test_application_rejects_incompatible_profiles_before_startup() -> None:
    calibration = replace(
        reference_fadec_calibration(),
        target_engine_id="other-engine",
    )

    with pytest.raises(ConfigurationCompatibilityError, match="target_engine"):
        create_application(fadec_calibration=calibration)
