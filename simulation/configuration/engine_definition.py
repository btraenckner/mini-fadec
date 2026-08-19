"""Physical engine, plant, sensor, and actuator definition."""

from dataclasses import dataclass, field

from simulation.configuration._serialization import configuration_to_dict
from simulation.plants.config import PlantSelectionConfig
from simulation.sensors.sensor_model import SensorModelConfiguration


@dataclass(frozen=True)
class EngineOperatingEnvelope:
    """Approved operating limits supplied by the engine definition."""

    idle_speed_rpm: float = 39_000.0
    maximum_continuous_speed_rpm: float = 128_000.0
    maximum_transient_speed_rpm: float = 138_240.0
    maximum_continuous_exhaust_temperature_c: float = 650.0
    maximum_transient_exhaust_temperature_c: float = 680.0

    def __post_init__(self) -> None:
        if self.idle_speed_rpm <= 0.0:
            raise ValueError("idle speed must be greater than zero")
        if self.maximum_continuous_speed_rpm <= self.idle_speed_rpm:
            raise ValueError("maximum continuous speed must exceed idle speed")
        if (
            self.maximum_transient_speed_rpm
            < self.maximum_continuous_speed_rpm
        ):
            raise ValueError(
                "maximum transient speed cannot be below continuous speed"
            )
        if self.maximum_continuous_exhaust_temperature_c <= 0.0:
            raise ValueError(
                "maximum continuous exhaust temperature must be positive"
            )
        if (
            self.maximum_transient_exhaust_temperature_c
            < self.maximum_continuous_exhaust_temperature_c
        ):
            raise ValueError(
                "maximum transient exhaust temperature cannot be below "
                "continuous temperature"
            )


@dataclass(frozen=True)
class ActuatorInterfaceDefinition:
    """Commands accepted by the installed engine actuator interface."""

    minimum_fuel_command: float = 0.0
    maximum_fuel_command: float = 1.0
    starter_command_available: bool = True
    ignition_command_available: bool = True

    def __post_init__(self) -> None:
        if self.minimum_fuel_command >= self.maximum_fuel_command:
            raise ValueError("actuator maximum fuel must exceed minimum fuel")


@dataclass(frozen=True)
class EngineDefinition:
    """Versioned physical definition independent of control calibration."""

    engine_id: str = "mini-fadec-reference-engine"
    display_name: str = "Mini-FADEC reference single-spool engine"
    definition_version: str = "1.0.0"
    plant: PlantSelectionConfig = field(default_factory=PlantSelectionConfig)
    sensors: SensorModelConfiguration = field(
        default_factory=SensorModelConfiguration
    )
    actuators: ActuatorInterfaceDefinition = field(
        default_factory=ActuatorInterfaceDefinition
    )
    operating_envelope: EngineOperatingEnvelope = field(
        default_factory=EngineOperatingEnvelope
    )

    def __post_init__(self) -> None:
        for field_name, value in (
            ("engine_id", self.engine_id),
            ("display_name", self.display_name),
            ("definition_version", self.definition_version),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} cannot be empty")

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-compatible definition snapshot."""

        return configuration_to_dict(self)
