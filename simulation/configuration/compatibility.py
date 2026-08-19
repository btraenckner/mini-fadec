"""Cross-check physical engine definitions against FADEC calibration."""

import math
from dataclasses import dataclass

from simulation.configuration.engine_definition import EngineDefinition
from simulation.configuration.fadec_calibration import FadecCalibration
from simulation.plants.types import PlantModelKind


@dataclass(frozen=True)
class CompatibilityIssue:
    """One deterministic engine/calibration compatibility finding."""

    code: str
    message: str


class ConfigurationCompatibilityError(ValueError):
    """Raised when a FADEC calibration cannot safely target an engine."""

    def __init__(self, issues: tuple[CompatibilityIssue, ...]) -> None:
        self.issues = issues
        details = "; ".join(
            f"{issue.code}: {issue.message}" for issue in issues
        )
        super().__init__(f"engine/FADEC configuration is incompatible: {details}")


def validate_engine_fadec_compatibility(
    engine_definition: EngineDefinition,
    fadec_calibration: FadecCalibration,
) -> None:
    """Reject inconsistent physical and software configuration before startup."""

    issues: list[CompatibilityIssue] = []
    envelope = engine_definition.operating_envelope
    actuator = engine_definition.actuators
    sensors = engine_definition.sensors
    schedule = fadec_calibration.speed_schedule
    controller = fadec_calibration.speed_controller
    state_machine = fadec_calibration.state_machine
    validation = fadec_calibration.sensor_validation
    protection = fadec_calibration.fuel_protection

    def add(code: str, message: str) -> None:
        issues.append(CompatibilityIssue(code=code, message=message))

    if fadec_calibration.target_engine_id != engine_definition.engine_id:
        add(
            "target_engine",
            f"calibration targets {fadec_calibration.target_engine_id!r}, not "
            f"{engine_definition.engine_id!r}",
        )

    if schedule.maximum_speed_rpm <= schedule.idle_speed_rpm:
        add("speed_schedule", "maximum speed must exceed idle speed")
    if not _equal(schedule.idle_speed_rpm, envelope.idle_speed_rpm):
        add(
            "idle_speed",
            "scheduled idle speed must match the engine idle speed",
        )
    if schedule.maximum_speed_rpm > envelope.maximum_continuous_speed_rpm:
        add(
            "maximum_speed",
            "scheduled maximum exceeds the continuous engine-speed limit",
        )

    plant = engine_definition.plant
    if plant.model is PlantModelKind.FIRST_ORDER:
        plant_parameters = plant.first_order.parameters
        plant_idle_speed_rpm = plant_parameters.idle_speed_rpm
        if not _equal(plant_idle_speed_rpm, envelope.idle_speed_rpm):
            add(
                "plant_idle_speed",
                "first-order plant idle speed does not match the engine "
                "operating envelope",
            )
        plant_maximum_speed_rpm = plant_parameters.maximum_speed_rpm
        if (
            state_machine.ignition_enable_speed_rpm
            < plant_parameters.ignition_enable_speed_rpm
        ):
            add(
                "plant_ignition_speed",
                "FADEC enables ignition below the plant light-off speed",
            )
        if (
            state_machine.start_fuel_command
            < plant_parameters.minimum_light_off_fuel_command
        ):
            add(
                "plant_light_off_fuel",
                "FADEC start fuel is below the plant light-off requirement",
            )
    else:
        plant_maximum_speed_rpm = plant.pathsim.maximum_speed_rpm
        minimum_lightoff_speed_rpm = (
            plant.pathsim.minimum_lightoff_speed_ratio
            * plant.pathsim.maximum_speed_rpm
        )
        if state_machine.ignition_enable_speed_rpm < minimum_lightoff_speed_rpm:
            add(
                "plant_ignition_speed",
                "FADEC enables ignition below the plant light-off speed",
            )
    if not _equal(
        plant_maximum_speed_rpm,
        envelope.maximum_continuous_speed_rpm,
    ):
        add(
            "plant_maximum_speed",
            "plant maximum speed does not match the engine operating envelope",
        )

    hard_overspeed_rpm = protection.overspeed.hard_overspeed_speed_rpm
    if not _equal(
        protection.overspeed.maximum_normal_speed_rpm,
        schedule.maximum_speed_rpm,
    ):
        add(
            "overspeed_reference",
            "overspeed reference must match the scheduled maximum speed",
        )
    if hard_overspeed_rpm > envelope.maximum_transient_speed_rpm:
        add(
            "hard_overspeed",
            "hard overspeed threshold exceeds the transient engine-speed limit",
        )
    if sensors.rotor_speed.maximum_value_rpm < hard_overspeed_rpm:
        add(
            "rotor_speed_sensor_range",
            "rotor-speed sensor cannot measure the hard overspeed threshold",
        )
    if validation.rotor_speed.maximum_value_rpm < hard_overspeed_rpm:
        add(
            "rotor_speed_validation_range",
            "rotor-speed validation rejects the hard overspeed threshold",
        )
    if (
        validation.rotor_speed.minimum_value_rpm
        < sensors.rotor_speed.minimum_value_rpm
        or validation.rotor_speed.maximum_value_rpm
        > sensors.rotor_speed.maximum_value_rpm
    ):
        add(
            "rotor_speed_range_alignment",
            "rotor-speed validation range exceeds the sensor range",
        )

    egt = protection.exhaust_temperature
    if (
        egt.intervention_exhaust_temperature_c
        >= egt.maximum_exhaust_temperature_c
    ):
        add(
            "egt_intervention",
            "EGT intervention temperature must be below its maximum",
        )
    if (
        egt.intervention_exhaust_temperature_c
        > envelope.maximum_continuous_exhaust_temperature_c
    ):
        add(
            "continuous_egt",
            "EGT intervention begins above the continuous engine limit",
        )
    if (
        egt.maximum_exhaust_temperature_c
        > envelope.maximum_transient_exhaust_temperature_c
    ):
        add(
            "maximum_egt",
            "EGT protection maximum exceeds the transient engine limit",
        )
    if (
        sensors.exhaust_temperature.maximum_value_c
        < envelope.maximum_transient_exhaust_temperature_c
    ):
        add(
            "egt_sensor_range",
            "EGT sensor cannot measure the transient temperature limit",
        )
    if (
        validation.exhaust_temperature.maximum_value_c
        < envelope.maximum_transient_exhaust_temperature_c
    ):
        add(
            "egt_validation_range",
            "EGT validation rejects the transient temperature limit",
        )
    if (
        validation.exhaust_temperature.minimum_value_c
        < sensors.exhaust_temperature.minimum_value_c
        or validation.exhaust_temperature.maximum_value_c
        > sensors.exhaust_temperature.maximum_value_c
    ):
        add(
            "egt_range_alignment",
            "EGT validation range exceeds the sensor range",
        )

    if not (
        state_machine.stopped_speed_threshold_rpm
        < state_machine.ignition_enable_speed_rpm
        < state_machine.self_sustaining_speed_rpm
        < envelope.idle_speed_rpm
    ):
        add(
            "start_sequence",
            "start thresholds must be ordered below engine idle speed",
        )
    if not engine_definition.actuators.starter_command_available:
        add("starter_interface", "engine start requires a starter command")
    if not engine_definition.actuators.ignition_command_available:
        add("ignition_interface", "engine start requires an ignition command")

    fuel_ranges = (
        (
            "speed_controller_fuel_range",
            controller.minimum_fuel_command,
            controller.maximum_fuel_command,
        ),
        (
            "protection_manager_fuel_range",
            protection.manager.minimum_fuel_command,
            protection.manager.maximum_fuel_command,
        ),
        (
            "egt_fuel_range",
            egt.minimum_fuel_command,
            egt.maximum_fuel_command,
        ),
        (
            "deceleration_fuel_range",
            protection.deceleration.minimum_fuel_command,
            protection.deceleration.maximum_fuel_command,
        ),
    )
    for code, minimum, maximum in fuel_ranges:
        if minimum >= maximum:
            add(code, "minimum fuel must be below maximum fuel")
        elif (
            minimum < actuator.minimum_fuel_command
            or maximum > actuator.maximum_fuel_command
        ):
            add(code, "calibrated fuel range exceeds the actuator interface")

    fuel_values = (
        ("start_fuel", state_machine.start_fuel_command),
        (
            "minimum_acceleration_fuel",
            protection.acceleration.minimum_acceleration_fuel_limit,
        ),
        ("minimum_overspeed_fuel", protection.overspeed.minimum_fuel_limit),
    )
    for code, value in fuel_values:
        if not (
            actuator.minimum_fuel_command
            <= value
            <= actuator.maximum_fuel_command
        ):
            add(code, "calibrated fuel value exceeds the actuator interface")

    if controller.proportional_gain < 0.0 or controller.integral_gain < 0.0:
        add("controller_gain", "PI controller gains cannot be negative")

    if issues:
        raise ConfigurationCompatibilityError(tuple(issues))


def _equal(first: float, second: float) -> bool:
    return math.isclose(first, second, rel_tol=0.0, abs_tol=1.0e-9)
