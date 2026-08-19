"""Tests for selectable public-data engine configuration profiles."""

import json
from pathlib import Path

import pytest

from simulation.application.factory import create_application
from simulation.configuration import (
    AERODESIGNWORKS_B350_STG_PROFILE_ID,
    JETCAT_P1000_PRO_PROFILE_ID,
    REFERENCE_ENGINE_PROFILE_ID,
    EngineProfileFidelity,
    get_engine_profile,
    list_engine_profiles,
    validate_engine_fadec_compatibility,
)
from simulation.operation.engine_state import EngineOperatingState
from simulation.plants.types import PlantModelKind
from simulation.telemetry.events import EventType
from simulation.telemetry.recorder import RunRecorder, RunRecorderParameters


def test_profile_registry_is_stable_compatible_and_serializable() -> None:
    profiles = list_engine_profiles()

    assert tuple(profile.profile_id for profile in profiles) == (
        REFERENCE_ENGINE_PROFILE_ID,
        JETCAT_P1000_PRO_PROFILE_ID,
        AERODESIGNWORKS_B350_STG_PROFILE_ID,
    )
    for profile in profiles:
        validate_engine_fadec_compatibility(
            profile.engine_definition,
            profile.fadec_calibration,
        )
        json.dumps(profile.engine_definition.to_dict())
        json.dumps(profile.fadec_calibration.to_dict())
        assert profile.engine_definition.provenance.data_quality


def test_jetcat_profile_contains_published_hardware_data() -> None:
    profile = get_engine_profile(JETCAT_P1000_PRO_PROFILE_ID)
    hardware = profile.engine_definition.hardware

    assert profile.fidelity is EngineProfileFidelity.PUBLIC_DATA_GREY_BOX
    assert hardware.part_number == "71157-0000"
    assert hardware.idle_speed_rpm == pytest.approx(19_000.0)
    assert hardware.maximum_speed_rpm == pytest.approx(61_500.0)
    assert hardware.idle_thrust_n == pytest.approx(45.0)
    assert hardware.maximum_thrust_n == pytest.approx(1_100.0)
    assert hardware.maximum_fuel_flow_ml_min == pytest.approx(2_900.0)
    assert hardware.maximum_exhaust_temperature_c == pytest.approx(720.0)
    assert hardware.mass_kg == pytest.approx(11.0)
    assert hardware.generator_output_w == pytest.approx(500.0)
    assert hardware.dc_dc_converter_output_w == pytest.approx(180.0)
    assert "CAN bus" in hardware.communication_interfaces
    assert len(profile.engine_definition.provenance.sources) == 2


def test_b350_profile_keeps_proxy_values_out_of_hardware_facts() -> None:
    profile = get_engine_profile(AERODESIGNWORKS_B350_STG_PROFILE_ID)
    hardware = profile.engine_definition.hardware
    parameters = profile.engine_definition.plant.first_order.parameters

    assert profile.fidelity is EngineProfileFidelity.PROVISIONAL_FAMILY_PROXY
    assert hardware.maximum_thrust_n is None
    assert hardware.maximum_speed_rpm is None
    assert hardware.maximum_fuel_flow_ml_min is None
    assert parameters.maximum_thrust_n == pytest.approx(350.0)
    assert parameters.maximum_speed_rpm == pytest.approx(104_000.0)
    assert parameters.maximum_fuel_flow_ml_min == pytest.approx(
        980.0 * 350.0 / 300.0
    )
    assert "not B350 test data" in (
        profile.engine_definition.provenance.data_quality
    )
    assert len(profile.engine_definition.provenance.sources) == 3


def test_application_selects_profile_and_preserves_requested_backend() -> None:
    service = create_application()
    service.select_plant_model(PlantModelKind.PATHSIM_GREYBOX_V1)

    selected = service.select_engine_profile(JETCAT_P1000_PRO_PROFILE_ID)

    assert selected.profile_id == JETCAT_P1000_PRO_PROFILE_ID
    assert service.engine_definition is not None
    assert service.engine_definition.engine_id == (
        "jetcat-p1000-pro-public-greybox"
    )
    assert service.fadec_calibration is not None
    assert service.fadec_calibration.target_engine_id == (
        service.engine_definition.engine_id
    )
    assert service.coordinator.plant_config.model is (
        PlantModelKind.PATHSIM_GREYBOX_V1
    )
    assert service.get_latest_snapshot().simulation_time_s == 0.0
    assert any(
        event.event_type is EventType.ENGINE_PROFILE_SELECTED
        for event in service.get_recent_events()
    )


def test_profile_change_is_rejected_while_engine_is_not_off() -> None:
    service = create_application()
    service.request_start()
    service.step_one_tick()

    with pytest.raises(RuntimeError, match="only while the engine is OFF"):
        service.select_engine_profile(JETCAT_P1000_PRO_PROFILE_ID)

    assert any(
        event.event_type
        is EventType.ENGINE_PROFILE_CONFIGURATION_REJECTED
        for event in service.get_recent_events()
    )


def test_recording_captures_profile_identity_sources_and_assumptions(
    tmp_path: Path,
) -> None:
    recorder = RunRecorder(RunRecorderParameters(base_directory=tmp_path))
    service = create_application(
        engine_profile=JETCAT_P1000_PRO_PROFILE_ID,
        recorder=recorder,
    )

    run_directory = service.start_recording("jetcat-profile")
    service.step_one_tick()
    service.stop_recording()
    metadata = json.loads(
        (run_directory / "metadata.json").read_text(encoding="utf-8")
    )

    assert metadata["configuration_summary"]["engine_profile_id"] == (
        JETCAT_P1000_PRO_PROFILE_ID
    )
    assert metadata["engine_definition"]["hardware"]["maximum_thrust_n"] == (
        1_100.0
    )
    assert metadata["engine_definition"]["provenance"]["sources"]
    assert metadata["engine_definition"]["provenance"][
        "modelling_assumptions"
    ]


@pytest.mark.parametrize(
    "profile_id",
    [JETCAT_P1000_PRO_PROFILE_ID, AERODESIGNWORKS_B350_STG_PROFILE_ID],
)
@pytest.mark.parametrize(
    ("plant_model", "idle_duration_s", "run_duration_s"),
    [
        (PlantModelKind.FIRST_ORDER, 5.0, 10.0),
        (PlantModelKind.PATHSIM_GREYBOX_V1, 8.0, 12.0),
    ],
)
def test_profile_reaches_published_or_proxy_full_power_without_exceeding_limits(
    profile_id: str,
    plant_model: PlantModelKind,
    idle_duration_s: float,
    run_duration_s: float,
) -> None:
    profile = get_engine_profile(profile_id)
    service = create_application(engine_profile=profile_id, sensor_random_seed=0)
    if plant_model is not PlantModelKind.FIRST_ORDER:
        service.select_plant_model(plant_model)
    service.set_throttle(0.0)
    service.request_start()

    maximum_egt_c = service.get_latest_snapshot().exhaust_temperature_c
    maximum_speed_rpm = service.get_latest_snapshot().rotor_speed_rpm
    for _ in range(round(idle_duration_s / service.base_tick_s)):
        snapshot = service.step_one_tick()
        maximum_egt_c = max(maximum_egt_c, snapshot.exhaust_temperature_c)
        maximum_speed_rpm = max(maximum_speed_rpm, snapshot.rotor_speed_rpm)
    service.set_throttle(1.0)
    for _ in range(round(run_duration_s / service.base_tick_s)):
        snapshot = service.step_one_tick()
        maximum_egt_c = max(maximum_egt_c, snapshot.exhaust_temperature_c)
        maximum_speed_rpm = max(maximum_speed_rpm, snapshot.rotor_speed_rpm)
        assert 0.0 <= snapshot.allowed_fuel_command <= 1.0

    envelope = profile.engine_definition.operating_envelope
    assert snapshot.operating_state is EngineOperatingState.RUNNING
    assert snapshot.rotor_speed_rpm == pytest.approx(
        envelope.maximum_continuous_speed_rpm,
        rel=0.02,
    )
    assert snapshot.estimated_thrust_n == pytest.approx(
        profile.engine_definition.plant.first_order.parameters.maximum_thrust_n,
        rel=0.03,
    )
    assert maximum_egt_c <= (
        envelope.maximum_transient_exhaust_temperature_c + 1.0
    )
    assert maximum_speed_rpm <= envelope.maximum_transient_speed_rpm
