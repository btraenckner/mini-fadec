"""Core data types used by the Mini-FADEC simulation."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AmbientConditions:
    """Environmental conditions affecting the engine."""

    temperature_c: float = 15.0
    pressure_pa: float = 101_325.0


@dataclass
class EngineState:
    """Internal physical state of the simulated engine."""

    rotor_speed_rpm: float
    exhaust_temperature_c: float


@dataclass(frozen=True)
class EngineOutputs:
    """Derived engine quantities that are not dynamic states."""

    estimated_thrust_n: float
    estimated_fuel_flow_ml_min: float


@dataclass(frozen=True)
class SensorData:
    """Measurements available to the engine controller."""

    rotor_speed_rpm: float
    exhaust_temperature_c: float


@dataclass(frozen=True)
class RawSensorData:
    """Possibly unavailable sensor values before signal validation."""

    rotor_speed_rpm: float | None
    exhaust_temperature_c: float | None


@dataclass(frozen=True)
class ControlRequest:
    """Requested engine operating point."""

    throttle_command: float


@dataclass(frozen=True)
class ActuatorCommand:
    """Commands sent by the controller to engine actuators."""

    fuel_command: float
    starter_commanded: bool = False
    ignition_commanded: bool = False
    fuel_enabled: bool = True
