"""Shared explicit application composition for dashboard and scenarios."""

from simulation.application.simulation_service import SimulationService
from simulation.configuration.engine_definition import EngineDefinition
from simulation.configuration.fadec_calibration import FadecCalibration
from simulation.core.types import AmbientConditions
from simulation.plants.config import PlantSelectionConfig
from simulation.scheduling.config import SchedulerConfig, SchedulingMode
from simulation.telemetry.recorder import RunRecorder


def create_application(
    *,
    engine_definition: EngineDefinition | None = None,
    fadec_calibration: FadecCalibration | None = None,
    plant_config: PlantSelectionConfig | None = None,
    scheduler_config: SchedulerConfig | None = None,
    sensor_random_seed: int | None = 0,
    recorder: RunRecorder | None = None,
    ambient_conditions: AmbientConditions | None = None,
    scheduling_mode: SchedulingMode = SchedulingMode.UNPACED,
    time_step_s: float = 0.01,
) -> SimulationService:
    """Create one isolated runtime using the same path for every client."""

    return SimulationService(
        engine_definition=engine_definition,
        fadec_calibration=fadec_calibration,
        plant_config=plant_config,
        scheduler_config=scheduler_config,
        sensor_random_seed=sensor_random_seed,
        ambient_conditions=ambient_conditions,
        recorder=recorder,
        scheduling_mode=scheduling_mode,
        time_step_s=time_step_s,
    )
