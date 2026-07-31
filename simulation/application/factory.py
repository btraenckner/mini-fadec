"""Shared explicit application composition for dashboard and scenarios."""

from simulation.application.engine_simulation import EngineSimulationCoordinator
from simulation.application.simulation_service import SimulationService
from simulation.core.types import AmbientConditions
from simulation.plants.config import PlantSelectionConfig
from simulation.scheduling.config import SchedulerConfig, SchedulingMode
from simulation.sensors.fault_injection import SensorFaultInjector
from simulation.sensors.sensor_model import (
    ConfigurableSensorModel,
    SensorModelConfiguration,
)
from simulation.telemetry.recorder import RunRecorder


def create_application(
    *,
    plant_config: PlantSelectionConfig | None = None,
    scheduler_config: SchedulerConfig | None = None,
    sensor_random_seed: int | None = 0,
    recorder: RunRecorder | None = None,
    ambient_conditions: AmbientConditions | None = None,
    scheduling_mode: SchedulingMode = SchedulingMode.UNPACED,
    time_step_s: float = 0.01,
) -> SimulationService:
    """Create one isolated runtime using the same path for every client."""

    coordinator = EngineSimulationCoordinator(
        plant_config=plant_config,
        sensor_model=ConfigurableSensorModel(
            SensorModelConfiguration(random_seed=sensor_random_seed)
        ),
        sensor_fault_injector=SensorFaultInjector(
            random_seed=sensor_random_seed
        ),
        scheduler_config=scheduler_config,
        ambient_conditions=ambient_conditions,
    )
    return SimulationService(
        coordinator=coordinator,
        recorder=recorder,
        scheduling_mode=scheduling_mode,
        time_step_s=time_step_s,
    )
