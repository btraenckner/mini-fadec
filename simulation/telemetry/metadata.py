"""Stable run metadata and graceful environment identification."""

import platform
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

from simulation.telemetry.events import EVENT_SCHEMA_VERSION
from simulation.telemetry.snapshot import TELEMETRY_SCHEMA_VERSION


METADATA_SCHEMA_VERSION = "1.0"

ConfigurationValue: TypeAlias = str | int | float | bool | None


@dataclass(frozen=True)
class GitMetadata:
    """Gracefully collected source revision identity."""

    commit: str | None = None
    branch: str | None = None
    dirty: bool | None = None


@dataclass(frozen=True)
class RunMetadataContext:
    """Explicit static simulation identity captured once per recording."""

    simulation_time_step_s: float
    sensor_random_seed: int | None
    engine_model_identifier: str
    controller_identifier: str
    protection_manager_identifier: str
    configuration_identifier: str = "default"
    configuration_summary: tuple[tuple[str, ConfigurationValue], ...] = ()
    repository_root: Path | None = None


GitMetadataProvider: TypeAlias = Callable[[Path | None], GitMetadata]


def collect_git_metadata(repository_root: Path | None) -> GitMetadata:
    """Collect Git identity once, returning unavailable values on any failure."""

    if repository_root is None:
        return GitMetadata()
    try:
        commit = _run_git(repository_root, "rev-parse", "HEAD")
        branch = _run_git(repository_root, "branch", "--show-current") or None
        dirty = bool(_run_git(repository_root, "status", "--porcelain"))
    except (OSError, subprocess.SubprocessError):
        return GitMetadata()
    return GitMetadata(commit=commit or None, branch=branch, dirty=dirty)


def build_run_metadata(
    *,
    run_identifier: str,
    run_name: str,
    recording_start_wall_clock: str,
    recording_stop_wall_clock: str | None,
    simulation_start_time_s: float,
    simulation_stop_time_s: float | None,
    telemetry_sampling_period_s: float,
    sample_count: int,
    event_count: int,
    completion_status: str,
    context: RunMetadataContext,
    git_metadata: GitMetadata,
) -> dict[str, object]:
    """Build metadata in one explicit deterministic key order."""

    return {
        "metadata_schema_version": METADATA_SCHEMA_VERSION,
        "telemetry_schema_version": TELEMETRY_SCHEMA_VERSION,
        "event_schema_version": EVENT_SCHEMA_VERSION,
        "run_identifier": run_identifier,
        "run_name": run_name,
        "recording_start_wall_clock": recording_start_wall_clock,
        "recording_stop_wall_clock": recording_stop_wall_clock,
        "simulation_start_time_s": simulation_start_time_s,
        "simulation_stop_time_s": simulation_stop_time_s,
        "simulation_time_step_s": context.simulation_time_step_s,
        "telemetry_sampling_period_s": telemetry_sampling_period_s,
        "sensor_random_seed": context.sensor_random_seed,
        "engine_model_identifier": context.engine_model_identifier,
        "controller_identifier": context.controller_identifier,
        "protection_manager_identifier": (
            context.protection_manager_identifier
        ),
        "configuration_identifier": context.configuration_identifier,
        "configuration_summary": dict(context.configuration_summary),
        "git_commit": git_metadata.commit,
        "git_branch": git_metadata.branch,
        "git_dirty": git_metadata.dirty,
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "python_executable": Path(sys.executable).name,
        "platform": platform.platform(),
        "completion_status": completion_status,
        "telemetry_sample_count": sample_count,
        "event_count": event_count,
    }


def _run_git(repository_root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ("git", *arguments),
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
        timeout=2.0,
    )
    return result.stdout.strip()
