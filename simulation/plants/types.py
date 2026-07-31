"""Stable identifiers, diagnostics, and errors for engine plants."""

from dataclasses import dataclass
from enum import Enum


class PlantModelKind(Enum):
    """Stable engine-plant identifiers used by configuration and artifacts."""

    FIRST_ORDER = "first_order"
    PATHSIM_GREYBOX_V1 = "pathsim_greybox_v1"


@dataclass(frozen=True)
class PlantModelDescriptor:
    """One selectable plant model exposed to application clients."""

    model: PlantModelKind
    display_name: str


@dataclass(frozen=True)
class PathSimPlantDiagnostics:
    """Optional PathSim-specific dynamic state without PathSim object leakage."""

    pathsim_version: str
    solver_id: str
    solver_mode: str
    fixed_step_s: float
    internal_substep_count: int
    effective_fuel: float
    normalized_speed: float
    gas_temperature_c: float
    combustion_effectiveness: float
    starter_torque: float
    turbine_torque: float
    compressor_load: float
    friction_load: float
    equilibrium_temperature_c: float
    latest_integration_success: bool
    latest_solver_error_indicator: float | None
    solver_step_count: int
    total_solver_evaluations: int | None
    total_solver_iterations: int | None


@dataclass(frozen=True)
class PlantDiagnostics:
    """Immutable common plant diagnostics with optional backend detail."""

    model_id: str
    display_name: str
    model_version: str
    model_time_s: float
    step_count: int
    latest_rotor_speed_rpm: float
    latest_exhaust_temperature_c: float
    latest_thrust_n: float
    pathsim: PathSimPlantDiagnostics | None = None


class PlantSimulationError(RuntimeError):
    """Raised when a plant backend cannot complete a requested interval."""
