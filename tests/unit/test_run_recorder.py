"""Unit tests for deterministic run recording and lifecycle cleanup."""

import csv
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from simulation.application.engine_simulation import EngineSimulationCoordinator
from simulation.telemetry.events import (
    EventCategory,
    EventSeverity,
    EventType,
    SimulationEvent,
)
from simulation.telemetry.metadata import GitMetadata, RunMetadataContext
from simulation.telemetry.recorder import (
    RunRecorder,
    RunRecorderParameters,
)
from simulation.telemetry.serialization import TELEMETRY_FIELDS


def _context() -> RunMetadataContext:
    return RunMetadataContext(
        simulation_time_step_s=0.01,
        sensor_random_seed=0,
        engine_model_identifier="FirstOrderEngineModel",
        controller_identifier="PIEngineSpeedController",
        protection_manager_identifier="ProtectionManager",
        configuration_summary=(("test", True),),
    )


def _recorder(base_directory: Path) -> RunRecorder:
    return RunRecorder(
        RunRecorderParameters(
            base_directory=base_directory,
            telemetry_sampling_period_s=0.05,
            flush_every_rows=2,
        ),
        wall_clock=lambda: datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc),
        git_metadata_provider=lambda _: GitMetadata(),
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as csv_file:
        return list(csv.DictReader(csv_file))


def test_recording_creates_stable_files_and_samples_by_simulation_time(
    tmp_path: Path,
) -> None:
    recorder = _recorder(tmp_path)
    initial = EngineSimulationCoordinator().snapshot

    run_directory = recorder.start_recording(
        initial,
        _context(),
        "normal run",
    )
    recorder.publish(replace(initial, simulation_time_s=0.02, snapshot_sequence_number=1))
    recorder.publish(replace(initial, simulation_time_s=0.05, snapshot_sequence_number=2))
    recorder.publish(replace(initial, simulation_time_s=0.099, snapshot_sequence_number=3))
    recorder.publish(replace(initial, simulation_time_s=0.101, snapshot_sequence_number=4))
    summary = recorder.stop_recording()

    rows = _read_csv(run_directory / "telemetry.csv")
    assert run_directory.name.endswith("normal_run")
    assert (run_directory / "events.csv").exists()
    assert (run_directory / "metadata.json").exists()
    assert tuple(rows[0]) == TELEMETRY_FIELDS
    assert [float(row["simulation_time_s"]) for row in rows] == [0.0, 0.05, 0.101]
    assert summary is not None
    assert summary.telemetry_sample_count == 3
    assert recorder.is_recording is False


def test_restart_is_unique_active_start_is_rejected_and_inactive_stop_is_safe(
    tmp_path: Path,
) -> None:
    recorder = _recorder(tmp_path)
    snapshot = EngineSimulationCoordinator().snapshot
    first_directory = recorder.start_recording(snapshot, _context(), "../unsafe")

    with pytest.raises(RuntimeError, match="already active"):
        recorder.start_recording(snapshot, _context(), "other")

    recorder.stop_recording()
    assert recorder.stop_recording() is None
    second_directory = recorder.start_recording(snapshot, _context(), "../unsafe")
    recorder.stop_recording()

    assert first_directory.parent == tmp_path
    assert first_directory.name.endswith("unsafe")
    assert second_directory != first_directory
    assert second_directory.name.endswith("unsafe_002")


def test_event_recording_uses_stable_csv_serialization(tmp_path: Path) -> None:
    recorder = _recorder(tmp_path)
    snapshot = EngineSimulationCoordinator().snapshot
    run_directory = recorder.start_recording(snapshot, _context())
    recorder.record_event(
        SimulationEvent(
            simulation_time_s=0.0,
            event_sequence=1,
            category=EventCategory.RECORDING,
            event_type=EventType.RECORDING_STARTED,
            severity=EventSeverity.INFO,
            source="test",
            message="started",
            old_value=None,
            new_value="run",
        )
    )
    recorder.stop_recording()

    event_rows = _read_csv(run_directory / "events.csv")
    assert len(event_rows) == 1
    assert event_rows[0]["event_type"] == "RECORDING_STARTED"
    assert event_rows[0]["old_value"] == "null"
    assert json.loads(event_rows[0]["new_value"]) == "run"


def test_controlled_exception_closes_files_and_marks_run_incomplete(
    tmp_path: Path,
) -> None:
    recorder = _recorder(tmp_path)
    snapshot = EngineSimulationCoordinator().snapshot

    with pytest.raises(RuntimeError, match="controlled"):
        with recorder.recording_session(snapshot, _context()) as run_directory:
            raise RuntimeError("controlled")

    with (run_directory / "metadata.json").open(encoding="utf-8") as file:
        metadata = json.load(file)
    assert recorder.is_recording is False
    assert metadata["completion_status"] == "incomplete"


def test_irregular_sampling_deadlines_are_deterministic(tmp_path: Path) -> None:
    def record_trace(directory: Path) -> list[float]:
        recorder = _recorder(directory)
        initial = EngineSimulationCoordinator().snapshot
        run_directory = recorder.start_recording(initial, _context())
        for sequence, simulation_time_s in enumerate(
            (0.011, 0.0499999999999, 0.0500000000001, 0.17, 0.19, 0.201),
            start=1,
        ):
            recorder.publish(
                replace(
                    initial,
                    simulation_time_s=simulation_time_s,
                    snapshot_sequence_number=sequence,
                )
            )
        recorder.stop_recording()
        return [
            float(row["simulation_time_s"])
            for row in _read_csv(run_directory / "telemetry.csv")
        ]

    assert record_trace(tmp_path / "one") == record_trace(tmp_path / "two")
