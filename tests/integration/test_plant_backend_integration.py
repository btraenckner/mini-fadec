"""Application-level integration tests for selectable engine plants."""

import csv
import json
from pathlib import Path

import pytest

from simulation.application.dashboard_model import DashboardSimulation
from simulation.application.engine_simulation import EngineSimulationCoordinator
from simulation.application.factory import create_application
from simulation.operation.engine_state import EngineOperatingState
from simulation.operation.state_machine import EngineOperationRequest
from simulation.plants.config import PlantSelectionConfig
from simulation.plants.factory import plant_selection_for
from simulation.plants.types import PlantModelKind, PlantSimulationError
from simulation.telemetry.recorder import RunRecorder, RunRecorderParameters


def test_application_defaults_to_first_order_and_can_use_pathsim() -> None:
    first_order = create_application()
    pathsim = create_application(
        plant_config=plant_selection_for(
            PlantModelKind.PATHSIM_GREYBOX_V1
        )
    )

    assert first_order.get_latest_snapshot().plant_model_id == "first_order"
    assert pathsim.get_latest_snapshot().plant_model_id == (
        "pathsim_greybox_v1"
    )
    assert (
        first_order.coordinator.scheduler_config
        == pathsim.coordinator.scheduler_config
    )
    assert type(first_order.coordinator.sensor_model) is type(
        pathsim.coordinator.sensor_model
    )
    assert type(first_order.coordinator.speed_controller) is type(
        pathsim.coordinator.speed_controller
    )


def test_pathsim_truth_flows_through_sensors_and_fadec_chain() -> None:
    service = create_application(
        plant_config=plant_selection_for("pathsim_greybox_v1")
    )
    service.request_start()

    while (
        service.get_latest_snapshot().operating_state
        is not EngineOperatingState.IDLE
    ):
        snapshot = service.step()
        assert snapshot.simulation_time_s < 5.0

    assert snapshot.rotor_speed_rpm > 0.0
    assert snapshot.measured_rotor_speed_rpm is not None
    assert snapshot.validated_rotor_speed_rpm is not None
    assert snapshot.plant_time_s == pytest.approx(snapshot.simulation_time_s)
    assert snapshot.plant_diagnostics is not None


def test_pathsim_reaches_maximum_speed_without_sustained_egt_limiting() -> None:
    coordinator = EngineSimulationCoordinator(
        plant_config=PlantSelectionConfig(
            model=PlantModelKind.PATHSIM_GREYBOX_V1
        )
    )
    startup_requested = True
    throttle_command = 0.0
    idle_reached = False
    maximum_egt_c = coordinator.snapshot.exhaust_temperature_c

    for _ in range(int(15.0 / 0.01)):
        snapshot = coordinator.step(
            EngineOperationRequest(
                throttle_command=throttle_command,
                startup_requested=startup_requested,
            ),
            time_step_s=0.01,
        )
        startup_requested = False
        maximum_egt_c = max(
            maximum_egt_c,
            snapshot.exhaust_temperature_c,
        )
        if snapshot.operating_state is EngineOperatingState.IDLE:
            idle_reached = True
            throttle_command = 1.0

    assert idle_reached
    assert snapshot.operating_state is EngineOperatingState.RUNNING
    assert snapshot.rotor_speed_rpm == pytest.approx(128_000.0, rel=0.02)
    assert maximum_egt_c <= (
        coordinator.egt_limiter.parameters.maximum_exhaust_temperature_c
    )
    assert snapshot.exhaust_temperature_c < (
        coordinator.egt_limiter.parameters.intervention_exhaust_temperature_c
    )
    assert not snapshot.egt_limiter_active


def test_plant_switching_is_off_only_and_creates_clean_state() -> None:
    service = create_application()
    service.set_throttle(0.9)

    service.select_plant_model("pathsim_greybox_v1")
    selected = service.get_latest_snapshot()

    assert selected.plant_model_id == "pathsim_greybox_v1"
    assert selected.simulation_time_s == 0.0
    assert selected.allowed_fuel_command == 0.0
    assert selected.rotor_speed_rpm == 0.0
    assert service.get_plant_diagnostics().pathsim is not None
    assert service.get_plant_diagnostics().pathsim.effective_fuel == 0.0

    service.request_start()
    service.step()
    with pytest.raises(RuntimeError, match="only while the engine is OFF"):
        service.select_plant_model("first_order")


def test_switching_back_to_first_order_while_off_is_clean() -> None:
    service = create_application(
        plant_config=plant_selection_for("pathsim_greybox_v1")
    )

    service.select_plant_model("first_order")

    snapshot = service.get_latest_snapshot()
    assert snapshot.plant_model_id == "first_order"
    assert snapshot.plant_diagnostics is None
    assert snapshot.rotor_speed_rpm == 0.0


def test_dashboard_refresh_does_not_step_pathsim() -> None:
    service = create_application(
        plant_config=plant_selection_for("pathsim_greybox_v1")
    )
    dashboard = DashboardSimulation(service=service)
    before = service.get_plant_diagnostics()

    dashboard.advance(0.0)

    assert service.get_plant_diagnostics() == before


@pytest.mark.parametrize(
    "model_id",
    ("first_order", "pathsim_greybox_v1"),
)
def test_recording_contains_plant_snapshot_telemetry_and_metadata(
    model_id: str,
    tmp_path: Path,
) -> None:
    recorder = RunRecorder(
        RunRecorderParameters(base_directory=tmp_path)
    )
    service = create_application(
        plant_config=plant_selection_for(model_id),
        recorder=recorder,
    )
    run_directory = service.start_recording(f"record-{model_id}")
    service.step(0.051)
    service.stop_recording()

    metadata = json.loads(
        (run_directory / "metadata.json").read_text(encoding="utf-8")
    )
    with (run_directory / "telemetry.csv").open(
        newline="",
        encoding="utf-8",
    ) as telemetry_file:
        rows = list(csv.DictReader(telemetry_file))

    assert metadata["plant_model_id"] == model_id
    assert metadata["plant_configuration"]
    assert metadata["configuration_summary"]["engine_definition_id"] == (
        "mini-fadec-reference-engine"
    )
    assert metadata["configuration_summary"]["fadec_calibration_id"] == (
        "mini-fadec-reference-calibration"
    )
    assert metadata["engine_definition"]["plant"]["model"] == model_id
    assert metadata["fadec_calibration"]["target_engine_id"] == (
        "mini-fadec-reference-engine"
    )
    assert rows[-1]["plant_model_id"] == model_id
    assert float(rows[-1]["plant_time_s"]) == pytest.approx(0.051)
    if model_id == "first_order":
        assert rows[-1]["plant_effective_fuel"] == ""
    else:
        assert metadata["pathsim_package_version"] == "0.24.0"
        assert rows[-1]["plant_effective_fuel"] != ""


def test_pathsim_failure_finalizes_active_recording(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = RunRecorder(
        RunRecorderParameters(base_directory=tmp_path)
    )
    service = create_application(
        plant_config=plant_selection_for("pathsim_greybox_v1"),
        recorder=recorder,
    )
    service.start_recording("pathsim-failure")
    plant = service.coordinator.engine_model
    monkeypatch.setattr(
        plant._adapter._simulation,  # type: ignore[attr-defined]  # noqa: SLF001
        "timestep",
        lambda *_args, **_kwargs: (False, 1.0, 1.0, 1, 0),
    )

    with pytest.raises(PlantSimulationError):
        service.step_one_tick()

    assert not recorder.is_recording
    assert recorder.status is not None
    assert recorder.status.completion_status == "incomplete"
