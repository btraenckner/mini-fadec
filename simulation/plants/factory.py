"""Explicit construction and discovery of supported engine plants."""

from dataclasses import replace

from simulation.core.types import AmbientConditions
from simulation.models.engine_model import FirstOrderEngineModel
from simulation.plants.config import PlantSelectionConfig
from simulation.plants.interfaces import EnginePlant
from simulation.plants.types import (
    PlantModelDescriptor,
    PlantModelKind,
)


_PLANT_MODELS = (
    PlantModelDescriptor(
        model=PlantModelKind.FIRST_ORDER,
        display_name="First-order reference",
    ),
    PlantModelDescriptor(
        model=PlantModelKind.PATHSIM_GREYBOX_V1,
        display_name="PathSim nonlinear grey-box v1",
    ),
)


def list_plant_models() -> tuple[PlantModelDescriptor, ...]:
    """Return supported plants in stable display order."""

    return _PLANT_MODELS


def plant_selection_for(
    model: PlantModelKind | str,
    *,
    base: PlantSelectionConfig | None = None,
) -> PlantSelectionConfig:
    """Return an independent selection for one stable model identifier."""

    model_kind = _normalize_model(model)
    return replace(base or PlantSelectionConfig(), model=model_kind)


def create_engine_plant(
    selection_config: PlantSelectionConfig | PlantModelKind | str | None = None,
    *,
    initial_ambient: AmbientConditions | None = None,
) -> EnginePlant:
    """Create exactly the requested backend without fallback behavior."""

    if selection_config is None:
        config = PlantSelectionConfig()
    elif isinstance(selection_config, PlantSelectionConfig):
        config = selection_config
    else:
        config = plant_selection_for(selection_config)

    if config.model is PlantModelKind.FIRST_ORDER:
        plant: EnginePlant = FirstOrderEngineModel(
            parameters=config.first_order.parameters,
            initially_running=config.first_order.initially_running,
        )
    elif config.model is PlantModelKind.PATHSIM_GREYBOX_V1:
        from simulation.plants.pathsim_greybox.model import (
            PathSimGreyBoxEngineModel,
        )

        plant = PathSimGreyBoxEngineModel(
            configuration=config.pathsim,
            initial_ambient=initial_ambient,
        )
    else:  # pragma: no cover - enum exhaustiveness guard
        raise ValueError(f"unsupported plant model: {config.model!r}")
    return plant


def _normalize_model(model: PlantModelKind | str) -> PlantModelKind:
    if isinstance(model, PlantModelKind):
        return model
    try:
        return PlantModelKind(model.strip().lower())
    except (AttributeError, ValueError) as error:
        raise ValueError(f"unknown plant model: {model}") from error
