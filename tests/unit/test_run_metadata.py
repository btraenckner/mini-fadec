"""Unit tests for stable, graceful run metadata."""

from datetime import datetime, timezone
import json
from pathlib import Path

from simulation.application.engine_simulation import EngineSimulationCoordinator
from simulation.telemetry.metadata import (
    GitMetadata,
    RunMetadataContext,
    build_run_metadata,
    collect_git_metadata,
)
from simulation.telemetry.recorder import RunRecorder, RunRecorderParameters


def _context() -> RunMetadataContext:
    return RunMetadataContext(
        simulation_time_step_s=0.01,
        sensor_random_seed=7,
        engine_model_identifier="engine",
        controller_identifier="controller",
        protection_manager_identifier="protection",
        configuration_summary=(("gain", 1.5), ("enabled", True)),
    )


def test_metadata_builder_has_stable_required_environment_fields() -> None:
    metadata = build_run_metadata(
        run_identifier="run-1",
        run_name="test",
        recording_start_wall_clock="2026-07-20T12:00:00+00:00",
        recording_stop_wall_clock=None,
        simulation_start_time_s=1.0,
        simulation_stop_time_s=2.0,
        telemetry_sampling_period_s=0.05,
        sample_count=3,
        event_count=4,
        completion_status="incomplete",
        context=_context(),
        git_metadata=GitMetadata(),
    )

    assert tuple(metadata)[:3] == (
        "metadata_schema_version",
        "telemetry_schema_version",
        "event_schema_version",
    )
    assert metadata["configuration_summary"] == {
        "gain": 1.5,
        "enabled": True,
    }
    assert metadata["python_version"]
    assert metadata["platform"]
    assert metadata["git_commit"] is None


def test_git_metadata_failure_does_not_fail_recording_and_counts_finalize(
    tmp_path: Path,
) -> None:
    unavailable_repository = tmp_path / "missing-repository"
    assert collect_git_metadata(unavailable_repository) == GitMetadata()

    recorder = RunRecorder(
        RunRecorderParameters(base_directory=tmp_path),
        wall_clock=lambda: datetime(2026, 7, 20, tzinfo=timezone.utc),
        git_metadata_provider=lambda _: collect_git_metadata(
            unavailable_repository
        ),
    )
    snapshot = EngineSimulationCoordinator().snapshot
    run_directory = recorder.start_recording(snapshot, _context())
    recorder.stop_recording(completed=True)

    with (run_directory / "metadata.json").open(encoding="utf-8") as file:
        metadata = json.load(file)
    assert metadata["completion_status"] == "complete"
    assert metadata["telemetry_sample_count"] == 1
    assert metadata["event_count"] == 0
    assert metadata["git_commit"] is None
    assert metadata["recording_stop_wall_clock"] is not None
