"""Project-owned reference engine and FADEC calibration profiles."""

from simulation.configuration.engine_definition import EngineDefinition
from simulation.configuration.fadec_calibration import FadecCalibration
from simulation.plants.config import PlantSelectionConfig


def reference_engine_definition(
    plant: PlantSelectionConfig | None = None,
) -> EngineDefinition:
    """Return a fresh reference engine definition."""

    return EngineDefinition(plant=plant or PlantSelectionConfig())


def reference_fadec_calibration() -> FadecCalibration:
    """Return a fresh calibration matching the reference engine."""

    return FadecCalibration()
