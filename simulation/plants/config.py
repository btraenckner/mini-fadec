"""Typed selection configuration for engine-plant backends."""

from dataclasses import asdict, dataclass, field
from enum import Enum

from simulation.plants.first_order.config import FirstOrderPlantConfig
from simulation.plants.pathsim_greybox.config import PathSimGreyBoxConfig
from simulation.plants.types import PlantModelKind


@dataclass(frozen=True)
class PlantSelectionConfig:
    """Per-application immutable backend selection and grouped parameters."""

    model: PlantModelKind = PlantModelKind.FIRST_ORDER
    first_order: FirstOrderPlantConfig = field(
        default_factory=FirstOrderPlantConfig
    )
    pathsim: PathSimGreyBoxConfig = field(default_factory=PathSimGreyBoxConfig)

    def __post_init__(self) -> None:
        if not isinstance(self.model, PlantModelKind):
            raise TypeError("model must be a PlantModelKind")

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-compatible representation."""

        return _json_compatible(asdict(self))  # type: ignore[return-value]


def _json_compatible(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {
            str(key): _json_compatible(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_json_compatible(item) for item in value]
    return value
