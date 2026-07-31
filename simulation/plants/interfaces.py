"""Project-owned interface for replaceable physical engine plants."""

from typing import Protocol, runtime_checkable

from simulation.core.types import (
    ActuatorCommand,
    AmbientConditions,
    EngineOutputs,
    EngineState,
)
from simulation.plants.types import PlantDiagnostics


@runtime_checkable
class EnginePlant(Protocol):
    """Minimum physical-plant boundary used by the application scheduler."""

    @property
    def model_id(self) -> str:
        """Return the stable persistence identifier for this plant model."""
        ...

    @property
    def display_name(self) -> str:
        """Return the human-readable model name."""
        ...

    @property
    def model_version(self) -> str:
        """Return the project-owned model version."""
        ...

    @property
    def state(self) -> EngineState:
        """Return current engine truth consumed by the sensor model."""
        ...

    def reset(
        self,
        *,
        ambient: AmbientConditions | None = None,
    ) -> None:
        """Restore plant initial conditions and integration state."""
        ...

    def step(
        self,
        actuator_command: ActuatorCommand,
        ambient_conditions: AmbientConditions,
        time_step_s: float,
    ) -> EngineOutputs:
        """Advance exactly one scheduler-provided plant interval."""
        ...

    def get_diagnostics(self) -> PlantDiagnostics:
        """Return immutable current plant diagnostics."""
        ...

    def get_metadata(self) -> dict[str, object]:
        """Return a fresh JSON-serializable static metadata mapping."""
        ...
