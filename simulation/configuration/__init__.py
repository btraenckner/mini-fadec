"""Typed engine definitions and FADEC calibration profiles."""

from simulation.configuration.compatibility import (
    CompatibilityIssue,
    ConfigurationCompatibilityError,
    validate_engine_fadec_compatibility,
)
from simulation.configuration.engine_definition import (
    ActuatorInterfaceDefinition,
    EngineDataProvenance,
    EngineDefinition,
    EngineHardwareSpecification,
    EngineOperatingEnvelope,
    EngineSourceReference,
)
from simulation.configuration.fadec_calibration import (
    FadecCalibration,
    FuelProtectionCalibration,
)
from simulation.configuration.profile_types import (
    EngineConfigurationProfile,
    EngineProfileFidelity,
)
from simulation.configuration.profiles import (
    AERODESIGNWORKS_B350_STG_PROFILE_ID,
    JETCAT_P1000_PRO_PROFILE_ID,
    REFERENCE_ENGINE_PROFILE_ID,
    aerodesignworks_b350_stg_profile,
    get_engine_profile,
    jetcat_p1000_pro_profile,
    list_engine_profiles,
    reference_engine_definition,
    reference_engine_profile,
    reference_fadec_calibration,
)

__all__ = (
    "ActuatorInterfaceDefinition",
    "AERODESIGNWORKS_B350_STG_PROFILE_ID",
    "CompatibilityIssue",
    "ConfigurationCompatibilityError",
    "EngineDataProvenance",
    "EngineConfigurationProfile",
    "EngineDefinition",
    "EngineHardwareSpecification",
    "EngineOperatingEnvelope",
    "EngineSourceReference",
    "EngineProfileFidelity",
    "FadecCalibration",
    "FuelProtectionCalibration",
    "JETCAT_P1000_PRO_PROFILE_ID",
    "REFERENCE_ENGINE_PROFILE_ID",
    "aerodesignworks_b350_stg_profile",
    "get_engine_profile",
    "jetcat_p1000_pro_profile",
    "list_engine_profiles",
    "reference_engine_definition",
    "reference_engine_profile",
    "reference_fadec_calibration",
    "validate_engine_fadec_compatibility",
)
