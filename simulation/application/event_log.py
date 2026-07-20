"""Minimal in-memory event recording for simulation diagnostics."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SimulationEvent:
    """One timestamped simulation event."""

    simulation_time_s: float
    message: str


class InMemoryEventLog:
    """Retain ordered events for terminal output and later logging adapters."""

    def __init__(self) -> None:
        self._events: list[SimulationEvent] = []

    @property
    def events(self) -> tuple[SimulationEvent, ...]:
        """Return an immutable view of all recorded events."""

        return tuple(self._events)

    def record(self, simulation_time_s: float, message: str) -> None:
        """Append one event."""

        self._events.append(
            SimulationEvent(
                simulation_time_s=simulation_time_s,
                message=message,
            )
        )

    def reset(self) -> None:
        """Clear all retained events."""

        self._events.clear()
