"""Signal validation and sensor-health reporting."""

from simulation.validation.sensor_validation import (
    ChannelDiagnosticReason,
    ChannelHealth,
    ExhaustTemperatureValidationConfiguration,
    RotorSpeedValidationConfiguration,
    SensorSignalValidator,
    SensorValidationConfiguration,
    SensorValidationContext,
    SensorValidationResult,
)

__all__ = [
    "ChannelDiagnosticReason",
    "ChannelHealth",
    "ExhaustTemperatureValidationConfiguration",
    "RotorSpeedValidationConfiguration",
    "SensorSignalValidator",
    "SensorValidationConfiguration",
    "SensorValidationContext",
    "SensorValidationResult",
]
