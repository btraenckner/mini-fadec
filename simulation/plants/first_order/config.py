"""Typed configuration for the first-order reference plant."""

from dataclasses import dataclass, field

from simulation.models.engine_model import EngineModelParameters


@dataclass(frozen=True)
class FirstOrderPlantConfig:
    """Construction settings that preserve the existing plant defaults."""

    parameters: EngineModelParameters = field(
        default_factory=EngineModelParameters
    )
    initially_running: bool = False
