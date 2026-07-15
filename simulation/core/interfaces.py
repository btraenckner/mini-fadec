"""Interfaces for interchangeable Mini-FADEC simulation components."""

from typing import Protocol

from simulation.core.types import (
    ActuatorCommand,
    AmbientConditions,
    ControlRequest,
    EngineOutputs,
    EngineState,
    SensorData,
)


class EngineModelInterface(Protocol):
    """Interface implemented by every compatible engine model."""

    @property
    def state(self) -> EngineState:
        """Return the current internal engine state."""
        ...

    def step(
        self,
        actuator_command: ActuatorCommand,
        ambient_conditions: AmbientConditions,
        time_step_s: float,
    ) -> EngineOutputs:
        """Advance the engine model by one simulation step."""
        ...


class SensorModelInterface(Protocol):
    """Interface implemented by simulated or real sensor adapters."""

    def measure(self, engine_state: EngineState) -> SensorData:
        """Convert the current engine state into controller measurements."""
        ...


class EngineControllerInterface(Protocol):
    """Interface implemented by every compatible engine controller."""

    def update(
        self,
        control_request: ControlRequest,
        sensor_data: SensorData,
        time_step_s: float,
    ) -> ActuatorCommand:
        """Calculate the actuator command for one control cycle."""
        ...