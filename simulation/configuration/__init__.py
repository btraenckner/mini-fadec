"""Typed engine definitions and FADEC calibration profiles."""

from simulation.configuration.compatibility import (
    CompatibilityIssue,
    ConfigurationCompatibilityError,
    validate_engine_fadec_compatibility,
)
from simulation.configuration.engine_definition import (
    ActuatorInterfaceDefinition,
    EngineDefinition,
    EngineOperatingEnvelope,
)
from simulation.configuration.fadec_calibration import (
    FadecCalibration,
    FuelProtectionCalibration,
)
from simulation.configuration.profiles import (
    reference_engine_definition,
    reference_fadec_calibration,
)

__all__ = (
    "ActuatorInterfaceDefinition",
    "CompatibilityIssue",
    "ConfigurationCompatibilityError",
    "EngineDefinition",
    "EngineOperatingEnvelope",
    "FadecCalibration",
    "FuelProtectionCalibration",
    "reference_engine_definition",
    "reference_fadec_calibration",
    "validate_engine_fadec_compatibility",
)
