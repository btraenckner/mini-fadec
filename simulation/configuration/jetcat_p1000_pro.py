"""Public-data grey-box profile for the JetCat P1000-PRO."""

from simulation.configuration.engine_definition import (
    EngineDataProvenance,
    EngineDefinition,
    EngineHardwareSpecification,
    EngineOperatingEnvelope,
    EngineSourceReference,
)
from simulation.configuration.fadec_calibration import (
    FadecCalibration,
    FuelProtectionCalibration,
)
from simulation.configuration.profile_types import (
    EngineConfigurationProfile,
    EngineProfileFidelity,
)
from simulation.controllers.speed_controller import (
    LinearThrottleToSpeedScheduler,
    SpeedControllerParameters,
)
from simulation.models.engine_model import EngineModelParameters
from simulation.operation.state_machine import EngineStateMachineParameters
from simulation.plants.config import PlantSelectionConfig
from simulation.plants.first_order.config import FirstOrderPlantConfig
from simulation.plants.pathsim_greybox.config import PathSimGreyBoxConfig
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
from simulation.sensors.sensor_model import (
    ExhaustTemperatureSensorConfiguration,
    RotorSpeedSensorConfiguration,
    SensorModelConfiguration,
)
from simulation.validation.sensor_validation import (
    ExhaustTemperatureValidationConfiguration,
    RotorSpeedValidationConfiguration,
    SensorValidationConfiguration,
)


JETCAT_P1000_PRO_PROFILE_ID = "jetcat-p1000-pro"
JETCAT_P1000_PRO_ENGINE_ID = "jetcat-p1000-pro-public-greybox"


def jetcat_p1000_pro_profile() -> EngineConfigurationProfile:
    """Return a fresh P1000-PRO profile based on public manufacturer data."""

    engine_definition = EngineDefinition(
        engine_id=JETCAT_P1000_PRO_ENGINE_ID,
        display_name="JetCat P1000-PRO",
        definition_version="1.0.0",
        hardware=EngineHardwareSpecification(
            manufacturer="Ingenieurbüro CAT, M. Zipperer GmbH",
            model_name="JetCat P1000-PRO",
            engine_type="single-spool turbojet",
            part_number="71157-0000",
            idle_speed_rpm=19_000.0,
            maximum_speed_rpm=61_500.0,
            idle_thrust_n=45.0,
            maximum_thrust_n=1_100.0,
            idle_fuel_flow_ml_min=550.0,
            maximum_fuel_flow_ml_min=2_900.0,
            minimum_exhaust_temperature_c=480.0,
            maximum_exhaust_temperature_c=720.0,
            mass_kg=11.0,
            diameter_mm=234.0,
            length_mm=444.0,
            pressure_ratio=4.0,
            mass_flow_kg_s=1.8,
            exhaust_velocity_km_h=2_200.0,
            exhaust_power_kw=336.1,
            specific_fuel_consumption_kg_n_h=0.127,
            minimum_supply_voltage_v=10.0,
            maximum_supply_voltage_v=35.0,
            maximum_starting_power_w=300.0,
            generator_output_w=500.0,
            dc_dc_converter_output_w=180.0,
            dc_dc_converter_output_current_a=16.0,
            fuel_types=(
                "Jet A-1 with 3-5% approved turbine oil",
                "diesel with 3-5% approved turbine oil",
            ),
            communication_interfaces=(
                "PWM",
                "serial",
                "analog",
                "JetCat bus",
                "CAN bus",
            ),
            integrated_features=(
                "ECU",
                "brushless starter-generator",
                "two brushless fuel pumps",
                "three fuel/start valves and fuel filter",
                "dual direct-kerosene ignition",
                "barometric pressure sensor",
                "speed, EGT, fuel, current and voltage telemetry",
                "automatic cooldown and in-flight restart",
                "independent safety-shutdown input",
            ),
            operating_notes=(
                "Manufacturer performance data are specified at ISA conditions.",
                "Published 2021 start envelope: -40 to +50 °C, 0-6000 m, "
                "0-150 m/s.",
                "Published inspection interval: 50 operating hours.",
            ),
        ),
        provenance=EngineDataProvenance(
            data_quality="manufacturer data with explicit grey-box dynamics",
            sources=(
                EngineSourceReference(
                    title="JetCat P1000-PRO product specifications",
                    url=(
                        "https://www.jetcat.de/en/productdetails/produkte/"
                        "jetcat/produkte/Professionell/P1000"
                    ),
                    revision="accessed 2026-08-19",
                    data_scope=(
                        "current performance, dimensions, fuel, electrical "
                        "interfaces and integrated systems"
                    ),
                ),
                EngineSourceReference(
                    title="JetCat P1000-PRO basic technical information",
                    url=(
                        "https://www.jetcat.de/jetcat/produkte/pro/"
                        "JetCat-P1000-BasicTechnicalInformation-2021-16-02.pdf"
                    ),
                    revision="2021-02-16",
                    data_scope=(
                        "architecture, operating envelope and inspection interval"
                    ),
                ),
            ),
            modelling_assumptions=(
                "Spool, fuel and EGT time constants are not published.",
                "Start thresholds and acceleration limits are development values.",
                "Sensor noise, quantization and validation debounce are assumed.",
                "First-order thrust uses a quadratic above-idle speed relationship.",
                "PathSim thrust exponent is fitted to published idle and maximum "
                "thrust at the published speeds.",
                "PathSim coefficients are scaled educational grey-box values.",
            ),
            known_limitations=(
                "No manufacturer map, transient test data or ECU calibration used.",
                "Ambient corrections are absent from the first-order backend.",
                "Generator, pressure-ratio and mass-flow dynamics are metadata only.",
            ),
        ),
        plant=_plant_configuration(),
        sensors=_sensor_configuration(),
        operating_envelope=EngineOperatingEnvelope(
            idle_speed_rpm=19_000.0,
            maximum_continuous_speed_rpm=61_500.0,
            maximum_transient_speed_rpm=66_420.0,
            maximum_continuous_exhaust_temperature_c=700.0,
            maximum_transient_exhaust_temperature_c=720.0,
        ),
    )
    calibration = _fadec_calibration()
    return EngineConfigurationProfile(
        profile_id=JETCAT_P1000_PRO_PROFILE_ID,
        display_name="JetCat P1000-PRO",
        fidelity=EngineProfileFidelity.PUBLIC_DATA_GREY_BOX,
        engine_definition=engine_definition,
        fadec_calibration=calibration,
    )


def _plant_configuration() -> PlantSelectionConfig:
    return PlantSelectionConfig(
        first_order=FirstOrderPlantConfig(
            parameters=EngineModelParameters(
                stopped_exhaust_temperature_c=15.0,
                ignition_enable_speed_rpm=6_000.0,
                starter_disengagement_speed_rpm=16_000.0,
                minimum_light_off_fuel_command=0.10,
                starter_time_constant_s=0.8,
                spool_down_time_constant_s=2.5,
                idle_speed_rpm=19_000.0,
                maximum_speed_rpm=61_500.0,
                speed_time_constant_s=1.4,
                idle_exhaust_temperature_c=480.0,
                fuel_egt_heating_gain_c=250.0,
                speed_egt_cooling_gain_c=40.0,
                acceleration_egt_gain_c=20.0,
                exhaust_temperature_time_constant_s=0.7,
                idle_thrust_n=45.0,
                maximum_thrust_n=1_100.0,
                thrust_speed_exponent=2.0,
                idle_fuel_flow_ml_min=550.0,
                maximum_fuel_flow_ml_min=2_900.0,
            )
        ),
        pathsim=PathSimGreyBoxConfig(
            normalized_inertia=1.3,
            starter_torque_gain_per_s=0.14,
            minimum_lightoff_speed_ratio=0.075,
            full_combustion_speed_ratio=0.26,
            combustion_base_temperature_rise_c=430.0,
            linear_fuel_temperature_gain_c=1_000.0,
            quadratic_fuel_temperature_gain_c=250.0,
            maximum_combustion_temperature_rise_c=765.0,
            speed_temperature_cooling_gain_c=90.0,
            thermal_time_constant_s=0.7,
            maximum_speed_rpm=61_500.0,
            maximum_normalized_speed=1.10,
            maximum_thrust_n=1_100.0,
            thrust_speed_exponent=2.72,
            maximum_fuel_flow_ml_min=2_900.0,
        ),
    )


def _sensor_configuration() -> SensorModelConfiguration:
    return SensorModelConfiguration(
        rotor_speed=RotorSpeedSensorConfiguration(
            noise_standard_deviation_rpm=25.0,
            quantization_step_rpm=10.0,
            maximum_value_rpm=70_000.0,
        ),
        exhaust_temperature=ExhaustTemperatureSensorConfiguration(
            noise_standard_deviation_c=1.5,
            quantization_step_c=0.5,
            maximum_value_c=800.0,
        ),
    )


def _fadec_calibration() -> FadecCalibration:
    return FadecCalibration(
        calibration_id="jetcat-p1000-pro-initial-calibration",
        display_name="JetCat P1000-PRO initial public-data calibration",
        calibration_version="1.0.0",
        target_engine_id=JETCAT_P1000_PRO_ENGINE_ID,
        speed_schedule=LinearThrottleToSpeedScheduler(
            idle_speed_rpm=19_000.0,
            maximum_speed_rpm=61_500.0,
        ),
        speed_controller=SpeedControllerParameters(
            proportional_gain=7.12e-5,
            integral_gain=9.42e-5,
        ),
        state_machine=EngineStateMachineParameters(
            ignition_enable_speed_rpm=6_000.0,
            self_sustaining_speed_rpm=16_000.0,
            stopped_speed_threshold_rpm=500.0,
            light_off_temperature_c=400.0,
            start_fuel_command=0.25,
        ),
        sensor_validation=SensorValidationConfiguration(
            rotor_speed=RotorSpeedValidationConfiguration(
                maximum_value_rpm=68_000.0,
                maximum_absolute_rate_rpm_s=80_000.0,
            ),
            exhaust_temperature=ExhaustTemperatureValidationConfiguration(
                maximum_value_c=780.0,
            ),
        ),
        fuel_protection=FuelProtectionCalibration(
            exhaust_temperature=ExhaustTemperatureLimiterParameters(
                intervention_exhaust_temperature_c=700.0,
                maximum_exhaust_temperature_c=720.0,
            ),
            acceleration_estimator=RotorAccelerationEstimatorParameters(
                filter_time_constant_s=0.08
            ),
            acceleration=AccelerationLimiterParameters(
                soft_acceleration_limit_rpm_per_s=35_000.0,
                hard_acceleration_limit_rpm_per_s=55_000.0,
            ),
            deceleration=DecelerationLimiterParameters(
                maximum_fuel_decrease_rate_per_s=0.4
            ),
            overspeed=OverspeedLimiterParameters(
                maximum_normal_speed_rpm=61_500.0,
            ),
        ),
    )
