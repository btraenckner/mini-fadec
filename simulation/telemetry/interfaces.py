"""Narrow synchronous publication interfaces for runtime observability."""

from typing import Protocol

from simulation.telemetry.snapshot import SimulationSnapshot


class SnapshotSink(Protocol):
    """Read-only consumer of canonical simulation snapshots."""

    def publish(self, snapshot: SimulationSnapshot) -> None:
        """Consume one immutable snapshot synchronously."""
        ...

