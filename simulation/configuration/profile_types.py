"""Typed pairing of one engine definition with one FADEC calibration."""

from dataclasses import dataclass
from enum import Enum

from simulation.configuration.compatibility import (
    validate_engine_fadec_compatibility,
)
from simulation.configuration.engine_definition import EngineDefinition
from simulation.configuration.fadec_calibration import FadecCalibration


class EngineProfileFidelity(Enum):
    """Evidence level behind a selectable engine profile."""

    EDUCATIONAL_REFERENCE = "educational reference"
    PUBLIC_DATA_GREY_BOX = "public-data grey-box"
    PROVISIONAL_FAMILY_PROXY = "provisional family proxy"


@dataclass(frozen=True)
class EngineConfigurationProfile:
    """One compatible, selectable engine and calibration pair."""

    profile_id: str
    display_name: str
    fidelity: EngineProfileFidelity
    engine_definition: EngineDefinition
    fadec_calibration: FadecCalibration

    def __post_init__(self) -> None:
        if not self.profile_id.strip():
            raise ValueError("profile_id cannot be empty")
        if not self.display_name.strip():
            raise ValueError("display_name cannot be empty")
        validate_engine_fadec_compatibility(
            self.engine_definition,
            self.fadec_calibration,
        )
