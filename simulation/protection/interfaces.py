"""Interfaces for interchangeable Mini-FADEC protection functions."""

from typing import Protocol

from simulation.core.types import ActuatorCommand, SensorData


class ActuatorProtectionInterface(Protocol):
    """Interface implemented by actuator-command protection functions."""

    def apply(
        self,
        requested_command: ActuatorCommand,
        sensor_data: SensorData,
        time_step_s: float,
    ) -> ActuatorCommand:
        """Apply protection limits to a requested actuator command."""
        ...
