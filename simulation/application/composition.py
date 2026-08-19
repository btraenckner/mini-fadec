"""Construct one runtime from an engine definition and FADEC calibration."""

from dataclasses import replace

from simulation.application.engine_simulation import EngineSimulationCoordinator
from simulation.configuration.compatibility import (
    validate_engine_fadec_compatibility,
)
from simulation.configuration.engine_definition import EngineDefinition
from simulation.configuration.fadec_calibration import FadecCalibration
from simulation.controllers.speed_controller import PIEngineSpeedController
from simulation.core.types import AmbientConditions
from simulation.operation.state_machine import EngineStateMachine
from simulation.protection.acceleration_limiter import (
    AccelerationLimiter,
    RotorAccelerationEstimator,
)
from simulation.protection.deceleration_limiter import DecelerationLimiter
from simulation.protection.exhaust_temperature_limiter import (
    ExhaustTemperatureLimiter,
)
from simulation.protection.overspeed_limiter import OverspeedLimiter
from simulation.protection.protection_manager import ProtectionManager
from simulation.scheduling.config import SchedulerConfig
from simulation.sensors.fault_injection import SensorFaultInjector
from simulation.sensors.sensor_model import ConfigurableSensorModel
from simulation.validation.sensor_validation import SensorSignalValidator


def create_configured_coordinator(
    engine_definition: EngineDefinition,
    fadec_calibration: FadecCalibration,
    *,
    scheduler_config: SchedulerConfig | None = None,
    sensor_random_seed: int | None = 0,
    ambient_conditions: AmbientConditions | None = None,
) -> EngineSimulationCoordinator:
    """Validate and compose a fresh isolated simulation coordinator."""

    validate_engine_fadec_compatibility(
        engine_definition,
        fadec_calibration,
    )
    protection = fadec_calibration.fuel_protection
    sensor_configuration = replace(
        engine_definition.sensors,
        random_seed=sensor_random_seed,
    )
    return EngineSimulationCoordinator(
        plant_config=engine_definition.plant,
        state_machine=EngineStateMachine(fadec_calibration.state_machine),
        speed_controller=PIEngineSpeedController(
            scheduler=fadec_calibration.speed_schedule,
            parameters=fadec_calibration.speed_controller,
        ),
        protection_manager=ProtectionManager(
            egt_limiter=ExhaustTemperatureLimiter(
                protection.exhaust_temperature
            ),
            acceleration_estimator=RotorAccelerationEstimator(
                protection.acceleration_estimator
            ),
            acceleration_limiter=AccelerationLimiter(
                protection.acceleration
            ),
            deceleration_limiter=DecelerationLimiter(
                protection.deceleration
            ),
            overspeed_limiter=OverspeedLimiter(protection.overspeed),
            parameters=protection.manager,
        ),
        sensor_model=ConfigurableSensorModel(sensor_configuration),
        sensor_fault_injector=SensorFaultInjector(
            random_seed=sensor_random_seed
        ),
        sensor_validator=SensorSignalValidator(
            fadec_calibration.sensor_validation
        ),
        scheduler_config=scheduler_config,
        ambient_conditions=ambient_conditions,
    )
