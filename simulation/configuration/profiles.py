"""Registry of compatible reference and public-data engine profiles."""

from collections.abc import Callable

from simulation.configuration.aerodesignworks_b350_stg import (
    AERODESIGNWORKS_B350_STG_PROFILE_ID,
    aerodesignworks_b350_stg_profile,
)
from simulation.configuration.engine_definition import EngineDefinition
from simulation.configuration.fadec_calibration import FadecCalibration
from simulation.configuration.jetcat_p1000_pro import (
    JETCAT_P1000_PRO_PROFILE_ID,
    jetcat_p1000_pro_profile,
)
from simulation.configuration.profile_types import (
    EngineConfigurationProfile,
    EngineProfileFidelity,
)
from simulation.plants.config import PlantSelectionConfig


REFERENCE_ENGINE_PROFILE_ID = "mini-fadec-reference"


def reference_engine_definition(
    plant: PlantSelectionConfig | None = None,
) -> EngineDefinition:
    """Return a fresh reference engine definition."""

    return EngineDefinition(plant=plant or PlantSelectionConfig())


def reference_fadec_calibration() -> FadecCalibration:
    """Return a fresh calibration matching the reference engine."""

    return FadecCalibration()


def reference_engine_profile() -> EngineConfigurationProfile:
    """Return the original educational reference as a selectable profile."""

    return EngineConfigurationProfile(
        profile_id=REFERENCE_ENGINE_PROFILE_ID,
        display_name="Mini-FADEC reference",
        fidelity=EngineProfileFidelity.EDUCATIONAL_REFERENCE,
        engine_definition=reference_engine_definition(),
        fadec_calibration=reference_fadec_calibration(),
    )


_PROFILE_FACTORIES: tuple[
    Callable[[], EngineConfigurationProfile], ...
] = (
    reference_engine_profile,
    jetcat_p1000_pro_profile,
    aerodesignworks_b350_stg_profile,
)


def list_engine_profiles() -> tuple[EngineConfigurationProfile, ...]:
    """Return fresh profiles in stable dashboard display order."""

    return tuple(factory() for factory in _PROFILE_FACTORIES)


def get_engine_profile(profile_id: str) -> EngineConfigurationProfile:
    """Return one fresh profile by stable identifier."""

    normalized_id = profile_id.strip().lower()
    for profile in list_engine_profiles():
        if profile.profile_id == normalized_id:
            return profile
    available = ", ".join(
        profile.profile_id for profile in list_engine_profiles()
    )
    raise KeyError(
        f"unknown engine profile {profile_id!r}; available: {available}"
    )


__all__ = (
    "AERODESIGNWORKS_B350_STG_PROFILE_ID",
    "JETCAT_P1000_PRO_PROFILE_ID",
    "REFERENCE_ENGINE_PROFILE_ID",
    "aerodesignworks_b350_stg_profile",
    "get_engine_profile",
    "jetcat_p1000_pro_profile",
    "list_engine_profiles",
    "reference_engine_definition",
    "reference_engine_profile",
    "reference_fadec_calibration",
)
