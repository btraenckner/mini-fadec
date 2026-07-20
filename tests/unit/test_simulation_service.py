"""Unit tests for the dashboard-ready application service."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from simulation.application.engine_simulation import EngineSimulationCoordinator
from simulation.application.simulation_service import SimulationService
from simulation.sensors.fault_injection import BiasSensorFault, SensorChannel
from simulation.telemetry.events import EventType
from simulation.telemetry.metadata import GitMetadata
from simulation.telemetry.recorder import RunRecorder, RunRecorderParameters


def _service(tmp_path: Path | None = None) -> SimulationService:
    recorder = None
    if tmp_path is not None:
        recorder = RunRecorder(
            RunRecorderParameters(base_directory=tmp_path),
            wall_clock=lambda: datetime(
                2026,
                7,
                20,
                tzinfo=timezone.utc,
            ),
            git_metadata_provider=lambda _: GitMetadata(),
        )
    return SimulationService(recorder=recorder)


def test_service_queues_commands_and_exposes_one_canonical_snapshot() -> None:
    service = _service()
    initial = service.get_latest_snapshot()
    service.request_start()
    assert service.set_throttle(1.5) == pytest.approx(1.0)

    first = service.step()
    second = service.step()

    assert first.snapshot_sequence_number == initial.snapshot_sequence_number + 1
    assert first.startup_requested
    assert first.throttle_demand == pytest.approx(1.0)
    assert second.startup_requested is False
    assert service.get_latest_snapshot() is second
    assert {event.event_type for event in service.get_recent_events()} >= {
        EventType.STARTUP_REQUESTED,
        EventType.THROTTLE_CHANGED,
    }


def test_service_controls_faults_without_exposing_low_level_mutation() -> None:
    service = _service()

    service.inject_sensor_fault(
        SensorChannel.ROTOR_SPEED,
        BiasSensorFault(offset=250.0),
    )
    assert "bias +250 rpm" in service.describe_sensor_fault(
        SensorChannel.ROTOR_SPEED
    )
    service.clear_sensor_fault(SensorChannel.ROTOR_SPEED)

    assert service.describe_sensor_fault(SensorChannel.ROTOR_SPEED) == "none"


def test_service_recording_lifecycle_and_marker_are_public(tmp_path: Path) -> None:
    service = _service(tmp_path)

    run_directory = service.start_recording("service run")
    marker = service.add_marker("stable condition")
    service.step()
    summary = service.stop_recording()

    assert run_directory.parent == tmp_path
    assert marker.event_type is EventType.USER_MARKER
    assert summary is not None
    assert summary.event_count >= 3
    assert service.recorder.is_recording is False
    assert service.list_recent_runs() == (run_directory,)


def test_service_cleanup_marks_active_recording_incomplete(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.start_recording()

    service.close()

    status = service.get_recording_status()
    assert status is not None
    assert status.completion_status == "incomplete"


def test_service_rejects_invalid_time_step() -> None:
    with pytest.raises(ValueError, match="time_step_s"):
        SimulationService(
            coordinator=EngineSimulationCoordinator(),
            time_step_s=0.0,
        )
