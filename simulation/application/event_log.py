"""Compatibility exports for the structured telemetry event log."""

from simulation.telemetry.events import SimulationEvent, SimulationEventLog

__all__ = ["InMemoryEventLog", "SimulationEvent"]


class InMemoryEventLog(SimulationEventLog):
    """Backward-compatible name for the bounded structured event log."""
