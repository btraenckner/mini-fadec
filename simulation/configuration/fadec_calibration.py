"""Versioned FADEC scheduling, control, validation, and protection calibration."""

from dataclasses import dataclass, field

from simulation.configuration._serialization import configuration_to_dict
from simulation.controllers.speed_controller import (
    LinearThrottleToSpeedScheduler,
    SpeedControllerParameters,
)
from simulation.operation.state_machine import EngineStateMachineParameters
from simulation.protection.acceleration_limiter import (
    AccelerationLimiterParameters,
    RotorAccelerationEstimatorParameters,
)
from simulation.protection.deceleration_limiter import (
    DecelerationLimiterParameters,
)
from simulation.protection.exhaust_temperature_limiter import (
    ExhaustTemperatureLimiterParameters,
)
from simulation.protection.overspeed_limiter import (
    OverspeedLimiterParameters,
)
from simulation.protection.protection_manager import (
    ProtectionManagerParameters,
)
from simulation.validation.sensor_validation import (
    SensorValidationConfiguration,
)


@dataclass(frozen=True)
class FuelProtectionCalibration:
    """All calibrated inputs to centralized fuel protection."""

    manager: ProtectionManagerParameters = field(
        default_factory=ProtectionManagerParameters
    )
    exhaust_temperature: ExhaustTemperatureLimiterParameters = field(
        default_factory=ExhaustTemperatureLimiterParameters
    )
    acceleration_estimator: RotorAccelerationEstimatorParameters = field(
        default_factory=RotorAccelerationEstimatorParameters
    )
    acceleration: AccelerationLimiterParameters = field(
        default_factory=AccelerationLimiterParameters
    )
    deceleration: DecelerationLimiterParameters = field(
        default_factory=DecelerationLimiterParameters
    )
    overspeed: OverspeedLimiterParameters = field(
        default_factory=OverspeedLimiterParameters
    )


@dataclass(frozen=True)
class FadecCalibration:
    """Versioned control-software values targeted to one engine definition."""

    calibration_id: str = "mini-fadec-reference-calibration"
    display_name: str = "Mini-FADEC reference calibration"
    calibration_version: str = "1.0.0"
    target_engine_id: str = "mini-fadec-reference-engine"
    speed_schedule: LinearThrottleToSpeedScheduler = field(
        default_factory=LinearThrottleToSpeedScheduler
    )
    speed_controller: SpeedControllerParameters = field(
        default_factory=SpeedControllerParameters
    )
    state_machine: EngineStateMachineParameters = field(
        default_factory=EngineStateMachineParameters
    )
    sensor_validation: SensorValidationConfiguration = field(
        default_factory=SensorValidationConfiguration
    )
    fuel_protection: FuelProtectionCalibration = field(
        default_factory=FuelProtectionCalibration
    )

    def __post_init__(self) -> None:
        for field_name, value in (
            ("calibration_id", self.calibration_id),
            ("display_name", self.display_name),
            ("calibration_version", self.calibration_version),
            ("target_engine_id", self.target_engine_id),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} cannot be empty")

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-compatible calibration snapshot."""

        return configuration_to_dict(self)
