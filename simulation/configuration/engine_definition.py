"""Physical engine, plant, sensor, and actuator definition."""

from dataclasses import dataclass, field

from simulation.configuration._serialization import configuration_to_dict
from simulation.plants.config import PlantSelectionConfig
from simulation.sensors.sensor_model import SensorModelConfiguration


@dataclass(frozen=True)
class EngineSourceReference:
    """One public source used to construct an engine profile."""

    title: str
    url: str
    revision: str = ""
    data_scope: str = ""

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("source title cannot be empty")
        if not self.url.startswith(("https://", "http://")):
            raise ValueError("source URL must use HTTP or HTTPS")


@dataclass(frozen=True)
class EngineHardwareSpecification:
    """Publicly reported hardware data, separate from model parameters."""

    manufacturer: str = "Mini-FADEC project"
    model_name: str = "Reference single-spool engine"
    engine_type: str = "single-spool turbojet"
    part_number: str | None = None
    idle_speed_rpm: float | None = 39_000.0
    maximum_speed_rpm: float | None = 128_000.0
    idle_thrust_n: float | None = 6.0
    maximum_thrust_n: float | None = 140.0
    idle_fuel_flow_ml_min: float | None = 100.0
    maximum_fuel_flow_ml_min: float | None = 480.0
    minimum_exhaust_temperature_c: float | None = 450.0
    maximum_exhaust_temperature_c: float | None = 680.0
    mass_kg: float | None = None
    diameter_mm: float | None = None
    length_mm: float | None = None
    pressure_ratio: float | None = None
    mass_flow_kg_s: float | None = None
    exhaust_velocity_km_h: float | None = None
    exhaust_power_kw: float | None = None
    specific_fuel_consumption_kg_n_h: float | None = None
    minimum_supply_voltage_v: float | None = None
    maximum_supply_voltage_v: float | None = None
    maximum_starting_power_w: float | None = None
    generator_output_w: float | None = None
    dc_dc_converter_output_w: float | None = None
    dc_dc_converter_output_current_a: float | None = None
    fuel_types: tuple[str, ...] = ()
    communication_interfaces: tuple[str, ...] = ()
    integrated_features: tuple[str, ...] = ()
    operating_notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.manufacturer.strip():
            raise ValueError("manufacturer cannot be empty")
        if not self.model_name.strip():
            raise ValueError("model_name cannot be empty")
        if not self.engine_type.strip():
            raise ValueError("engine_type cannot be empty")
        nonnegative_values = (
            self.idle_thrust_n,
            self.maximum_thrust_n,
            self.idle_speed_rpm,
            self.maximum_speed_rpm,
            self.idle_fuel_flow_ml_min,
            self.maximum_fuel_flow_ml_min,
            self.mass_kg,
            self.diameter_mm,
            self.length_mm,
            self.pressure_ratio,
            self.mass_flow_kg_s,
            self.exhaust_velocity_km_h,
            self.exhaust_power_kw,
            self.specific_fuel_consumption_kg_n_h,
            self.minimum_supply_voltage_v,
            self.maximum_supply_voltage_v,
            self.maximum_starting_power_w,
            self.generator_output_w,
            self.dc_dc_converter_output_w,
            self.dc_dc_converter_output_current_a,
        )
        if any(value is not None and value < 0.0 for value in nonnegative_values):
            raise ValueError("reported hardware values cannot be negative")
        if (
            self.idle_speed_rpm is not None
            and self.maximum_speed_rpm is not None
            and self.maximum_speed_rpm < self.idle_speed_rpm
        ):
            raise ValueError("maximum speed cannot be below idle speed")
        if (
            self.idle_thrust_n is not None
            and self.maximum_thrust_n is not None
            and self.maximum_thrust_n < self.idle_thrust_n
        ):
            raise ValueError("maximum thrust cannot be below idle thrust")
        if (
            self.minimum_supply_voltage_v is not None
            and self.maximum_supply_voltage_v is not None
            and self.maximum_supply_voltage_v < self.minimum_supply_voltage_v
        ):
            raise ValueError(
                "maximum supply voltage cannot be below minimum voltage"
            )


@dataclass(frozen=True)
class EngineDataProvenance:
    """Evidence, assumptions, and limitations behind one engine profile."""

    data_quality: str = "educational reference assumptions"
    sources: tuple[EngineSourceReference, ...] = ()
    modelling_assumptions: tuple[str, ...] = ()
    known_limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.data_quality.strip():
            raise ValueError("data_quality cannot be empty")


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
    hardware: EngineHardwareSpecification = field(
        default_factory=EngineHardwareSpecification
    )
    provenance: EngineDataProvenance = field(
        default_factory=EngineDataProvenance
    )
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
