"""Structured runtime observability for the Mini-FADEC simulation."""

from simulation.telemetry.events import SimulationEvent
from simulation.telemetry.interfaces import SnapshotSink
from simulation.telemetry.snapshot import SimulationSnapshot


__all__ = ["SimulationEvent", "SimulationSnapshot", "SnapshotSink"]
