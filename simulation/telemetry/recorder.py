"""Deterministic CSV run recording driven only by simulation time."""

import csv
import json
import math
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

from simulation.telemetry.events import (
    EVENT_FIELDS,
    SimulationEvent,
    event_to_row,
)
from simulation.telemetry.metadata import (
    GitMetadata,
    GitMetadataProvider,
    RunMetadataContext,
    build_run_metadata,
    collect_git_metadata,
)
from simulation.telemetry.serialization import (
    TELEMETRY_FIELDS,
    snapshot_to_telemetry_row,
)
from simulation.telemetry.snapshot import SimulationSnapshot


@dataclass(frozen=True)
class RunRecorderParameters:
    """Filesystem and deterministic telemetry-sampling configuration."""

    base_directory: Path = field(default_factory=lambda: Path("artifacts/runs"))
    telemetry_sampling_period_s: float = 0.05
    flush_every_rows: int = 20

    def __post_init__(self) -> None:
        if self.telemetry_sampling_period_s <= 0.0:
            raise ValueError("telemetry sampling period must be greater than zero")
        if self.flush_every_rows <= 0:
            raise ValueError("flush_every_rows must be greater than zero")


@dataclass(frozen=True)
class RunRecordingSummary:
    """Final or current public recording status."""

    run_name: str
    run_directory: Path
    telemetry_sample_count: int
    event_count: int
    telemetry_sampling_period_s: float
    completion_status: str


class RunRecorder:
    """Write one safely isolated, reproducible run artifact directory."""

    def __init__(
        self,
        parameters: RunRecorderParameters | None = None,
        *,
        wall_clock: Callable[[], datetime] | None = None,
        git_metadata_provider: GitMetadataProvider = collect_git_metadata,
    ) -> None:
        self.parameters = parameters or RunRecorderParameters()
        self._wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        self._git_metadata_provider = git_metadata_provider
        self._reset_session_state()

    @property
    def is_recording(self) -> bool:
        return self._telemetry_file is not None

    @property
    def current_run_directory(self) -> Path | None:
        return self._run_directory

    @property
    def status(self) -> RunRecordingSummary | None:
        if self._run_directory is None or self._run_name is None:
            return None
        return RunRecordingSummary(
            run_name=self._run_name,
            run_directory=self._run_directory,
            telemetry_sample_count=self._sample_count,
            event_count=self._event_count,
            telemetry_sampling_period_s=(
                self.parameters.telemetry_sampling_period_s
            ),
            completion_status=(
                "recording" if self.is_recording else self._completion_status
            ),
        )

    def start_recording(
        self,
        initial_snapshot: SimulationSnapshot,
        metadata_context: RunMetadataContext,
        run_name: str | None = None,
    ) -> Path:
        """Create a unique run and record its first snapshot immediately."""

        if self.is_recording:
            raise RuntimeError("recording is already active")

        self._reset_session_state()
        sanitized_name = sanitize_run_name(run_name)
        start_wall_clock = self._wall_clock()
        run_directory = self._create_unique_run_directory(
            sanitized_name,
            start_wall_clock,
        )
        telemetry_file = (run_directory / "telemetry.csv").open(
            "w", newline="", encoding="utf-8"
        )
        events_file = (run_directory / "events.csv").open(
            "w", newline="", encoding="utf-8"
        )
        self._telemetry_file = telemetry_file
        self._events_file = events_file
        self._telemetry_writer = csv.DictWriter(
            telemetry_file,
            fieldnames=TELEMETRY_FIELDS,
        )
        self._event_writer = csv.DictWriter(
            events_file,
            fieldnames=EVENT_FIELDS,
        )
        self._telemetry_writer.writeheader()
        self._event_writer.writeheader()
        self._run_name = sanitized_name
        self._run_directory = run_directory
        self._metadata_context = metadata_context
        self._git_metadata = self._git_metadata_provider(
            metadata_context.repository_root
        )
        self._start_wall_clock = start_wall_clock
        self._simulation_start_time_s = initial_snapshot.simulation_time_s
        self._last_simulation_time_s = initial_snapshot.simulation_time_s
        self._next_sample_time_s = (
            initial_snapshot.simulation_time_s
            + self.parameters.telemetry_sampling_period_s
        )
        self._completion_status = "incomplete"
        self._write_snapshot(initial_snapshot)
        self._write_metadata(stop_wall_clock=None)
        return run_directory

    def publish(self, snapshot: SimulationSnapshot) -> None:
        """Record a snapshot only when its simulation-time deadline is due."""

        if not self.is_recording:
            return
        self._last_simulation_time_s = snapshot.simulation_time_s
        if snapshot.snapshot_sequence_number == self._last_snapshot_sequence:
            return
        assert self._next_sample_time_s is not None
        tolerance_s = 1.0e-12 * max(
            1.0,
            self.parameters.telemetry_sampling_period_s,
        )
        if snapshot.simulation_time_s + tolerance_s < self._next_sample_time_s:
            return

        self._write_snapshot(snapshot)
        periods_elapsed = math.floor(
            (
                snapshot.simulation_time_s
                - self._next_sample_time_s
                + tolerance_s
            )
            / self.parameters.telemetry_sampling_period_s
        ) + 1
        self._next_sample_time_s += (
            periods_elapsed * self.parameters.telemetry_sampling_period_s
        )

    def record_event(self, event: SimulationEvent) -> None:
        """Write one structured event while recording is active."""

        if not self.is_recording:
            return
        assert self._event_writer is not None
        self._event_writer.writerow(event_to_row(event))
        self._event_count += 1
        self._flush_if_due()

    def stop_recording(
        self,
        *,
        completed: bool = True,
    ) -> RunRecordingSummary | None:
        """Finalize metadata and close all files; inactive stop is safe."""

        if not self.is_recording:
            return None
        self._completion_status = "complete" if completed else "incomplete"
        stop_wall_clock = self._wall_clock()
        self._flush_files()
        assert self._telemetry_file is not None
        assert self._events_file is not None
        self._telemetry_file.close()
        self._events_file.close()
        self._telemetry_file = None
        self._events_file = None
        self._write_metadata(stop_wall_clock=stop_wall_clock)
        return self.status

    def close(self) -> None:
        """Close an interrupted active session while preserving partial metadata."""

        self.stop_recording(completed=False)

    @contextmanager
    def recording_session(
        self,
        initial_snapshot: SimulationSnapshot,
        metadata_context: RunMetadataContext,
        run_name: str | None = None,
    ) -> Iterator[Path]:
        """Record a complete context or finalize it as incomplete on failure."""

        run_directory = self.start_recording(
            initial_snapshot,
            metadata_context,
            run_name,
        )
        try:
            yield run_directory
        except BaseException:
            self.stop_recording(completed=False)
            raise
        else:
            self.stop_recording(completed=True)

    def _write_snapshot(self, snapshot: SimulationSnapshot) -> None:
        assert self._telemetry_writer is not None
        self._telemetry_writer.writerow(snapshot_to_telemetry_row(snapshot))
        self._sample_count += 1
        self._last_snapshot_sequence = snapshot.snapshot_sequence_number
        self._flush_if_due()

    def _flush_if_due(self) -> None:
        if (self._sample_count + self._event_count) % self.parameters.flush_every_rows == 0:
            self._flush_files()

    def _flush_files(self) -> None:
        if self._telemetry_file is not None:
            self._telemetry_file.flush()
        if self._events_file is not None:
            self._events_file.flush()

    def _create_unique_run_directory(
        self,
        run_name: str,
        start_wall_clock: datetime,
    ) -> Path:
        base_directory = self.parameters.base_directory
        base_directory.mkdir(parents=True, exist_ok=True)
        timestamp = start_wall_clock.astimezone(timezone.utc).strftime(
            "%Y-%m-%d_%H%M%S"
        )
        base_identifier = f"{timestamp}_{run_name}"
        run_directory = base_directory / base_identifier
        suffix = 2
        while run_directory.exists():
            run_directory = base_directory / f"{base_identifier}_{suffix:03d}"
            suffix += 1
        run_directory.mkdir()
        return run_directory

    def _write_metadata(self, stop_wall_clock: datetime | None) -> None:
        assert self._run_directory is not None
        assert self._run_name is not None
        assert self._metadata_context is not None
        assert self._git_metadata is not None
        assert self._start_wall_clock is not None
        metadata = build_run_metadata(
            run_identifier=self._run_directory.name,
            run_name=self._run_name,
            recording_start_wall_clock=self._start_wall_clock.isoformat(),
            recording_stop_wall_clock=(
                stop_wall_clock.isoformat() if stop_wall_clock else None
            ),
            simulation_start_time_s=self._simulation_start_time_s,
            simulation_stop_time_s=self._last_simulation_time_s,
            telemetry_sampling_period_s=(
                self.parameters.telemetry_sampling_period_s
            ),
            sample_count=self._sample_count,
            event_count=self._event_count,
            completion_status=self._completion_status,
            context=self._metadata_context,
            git_metadata=self._git_metadata,
        )
        with (self._run_directory / "metadata.json").open(
            "w", encoding="utf-8"
        ) as metadata_file:
            json.dump(metadata, metadata_file, indent=2, ensure_ascii=False)
            metadata_file.write("\n")

    def _reset_session_state(self) -> None:
        self._telemetry_file: TextIO | None = None
        self._events_file: TextIO | None = None
        self._telemetry_writer: csv.DictWriter[str] | None = None
        self._event_writer: csv.DictWriter[str] | None = None
        self._run_name: str | None = None
        self._run_directory: Path | None = None
        self._metadata_context: RunMetadataContext | None = None
        self._git_metadata: GitMetadata | None = None
        self._start_wall_clock: datetime | None = None
        self._simulation_start_time_s = 0.0
        self._last_simulation_time_s: float | None = None
        self._next_sample_time_s: float | None = None
        self._last_snapshot_sequence: int | None = None
        self._sample_count = 0
        self._event_count = 0
        self._completion_status = "not_started"


def sanitize_run_name(run_name: str | None) -> str:
    """Return a safe bounded path component without permitting traversal."""

    candidate = (run_name or "run").strip().replace(" ", "_")
    candidate = re.sub(r"[^A-Za-z0-9_-]+", "_", candidate)
    candidate = re.sub(r"_+", "_", candidate).strip("_-")
    return (candidate or "run")[:64]
