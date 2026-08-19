"""Provisional family-proxy profile for the AeroDesignWorks B350STG."""

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


AERODESIGNWORKS_B350_STG_PROFILE_ID = "aerodesignworks-b350-stg"
AERODESIGNWORKS_B350_STG_ENGINE_ID = "adw-b350-stg-provisional-greybox"


def aerodesignworks_b350_stg_profile() -> EngineConfigurationProfile:
    """Return a provisional B350STG profile using B300-family proxy data."""

    engine_definition = EngineDefinition(
        engine_id=AERODESIGNWORKS_B350_STG_ENGINE_ID,
        display_name="AeroDesignWorks B350STG",
        definition_version="0.1.0",
        hardware=EngineHardwareSpecification(
            manufacturer="AeroDesignWorks GmbH",
            model_name="B350STG",
            engine_type="single-spool turbojet",
            idle_speed_rpm=None,
            maximum_speed_rpm=None,
            idle_thrust_n=None,
            maximum_thrust_n=None,
            idle_fuel_flow_ml_min=None,
            maximum_fuel_flow_ml_min=None,
            minimum_exhaust_temperature_c=None,
            maximum_exhaust_temperature_c=None,
            integrated_features=("integrated starter-generator",),
            operating_notes=(
                "AeroDesignWorks identifies the B350STG publicly but does not "
                "publish a detailed B350STG datasheet.",
                "The current manufacturer site describes it as part of the "
                "series-produced B300 engine family.",
            ),
        ),
        provenance=EngineDataProvenance(
            data_quality="provisional B300-family proxy; not B350 test data",
            sources=(
                EngineSourceReference(
                    title="AeroDesignWorks turbojet product overview",
                    url="https://www.aerodesignworks.com/en/",
                    revision="accessed 2026-08-19",
                    data_scope=(
                        "B350STG identity, integrated starter-generator and "
                        "B300-family context"
                    ),
                ),
                EngineSourceReference(
                    title="AeroDesignWorks B300F operating manual",
                    url=(
                        "https://www.aerodesignworks.com/wp-content/uploads/"
                        "OperatingManual_B300F.pdf"
                    ),
                    revision="2020-04-24",
                    data_scope=(
                        "family proxy for RPM, thrust, fuel, EGT, dimensions "
                        "and acceleration"
                    ),
                ),
                EngineSourceReference(
                    title="AeroDesignWorks HORNET-III ECU manual",
                    url=(
                        "https://www.aerodesignworks.com/wp-content/uploads/"
                        "2022-04-27_hornet_manual_v3.0_en.pdf"
                    ),
                    revision="3.0, 2022-04-27",
                    data_scope="control behavior and cubic thrust/RPM relation",
                ),
            ),
            modelling_assumptions=(
                "350 N maximum thrust is inferred from the B350 designation.",
                "35,000/104,000 rpm and 680-760 °C use published B300F values.",
                "Maximum fuel flow scales B300F 980 ml/min by 350/300.",
                "Idle thrust and fuel flow use the same 350/300 scaling.",
                "The 1.53 s spool time constant approximates the B300F 4.6 s "
                "idle-to-maximum acceleration as a 95% first-order response.",
                "Start thresholds, sensor behavior and protection rates are assumed.",
                "PathSim coefficients are scaled educational grey-box values.",
            ),
            known_limitations=(
                "No public B350STG RPM, EGT, fuel, mass or transient dataset found.",
                "No compressor map, generator map or manufacturer calibration used.",
                "This profile must be replaced when B350STG test data are available.",
            ),
        ),
        plant=_plant_configuration(),
        sensors=_sensor_configuration(),
        operating_envelope=EngineOperatingEnvelope(
            idle_speed_rpm=35_000.0,
            maximum_continuous_speed_rpm=104_000.0,
            maximum_transient_speed_rpm=112_320.0,
            maximum_continuous_exhaust_temperature_c=740.0,
            maximum_transient_exhaust_temperature_c=760.0,
        ),
    )
    calibration = _fadec_calibration()
    return EngineConfigurationProfile(
        profile_id=AERODESIGNWORKS_B350_STG_PROFILE_ID,
        display_name="ADW B350STG (provisional)",
        fidelity=EngineProfileFidelity.PROVISIONAL_FAMILY_PROXY,
        engine_definition=engine_definition,
        fadec_calibration=calibration,
    )


def _plant_configuration() -> PlantSelectionConfig:
    scaled_maximum_fuel_flow_ml_min = 980.0 * 350.0 / 300.0
    return PlantSelectionConfig(
        first_order=FirstOrderPlantConfig(
            parameters=EngineModelParameters(
                stopped_exhaust_temperature_c=15.0,
                ignition_enable_speed_rpm=12_000.0,
                starter_disengagement_speed_rpm=30_000.0,
                minimum_light_off_fuel_command=0.10,
                starter_time_constant_s=0.9,
                spool_down_time_constant_s=2.0,
                idle_speed_rpm=35_000.0,
                maximum_speed_rpm=104_000.0,
                speed_time_constant_s=4.6 / 3.0,
                idle_exhaust_temperature_c=680.0,
                fuel_egt_heating_gain_c=80.0,
                speed_egt_cooling_gain_c=40.0,
                acceleration_egt_gain_c=20.0,
                exhaust_temperature_time_constant_s=0.6,
                idle_thrust_n=15.0 * 350.0 / 300.0,
                maximum_thrust_n=350.0,
                thrust_speed_exponent=3.0,
                idle_fuel_flow_ml_min=(
                    scaled_maximum_fuel_flow_ml_min * 0.20
                ),
                maximum_fuel_flow_ml_min=scaled_maximum_fuel_flow_ml_min,
            )
        ),
        pathsim=PathSimGreyBoxConfig(
            normalized_inertia=1.5,
            starter_torque_gain_per_s=0.14,
            minimum_lightoff_speed_ratio=0.10,
            full_combustion_speed_ratio=0.30,
            combustion_base_temperature_rise_c=600.0,
            linear_fuel_temperature_gain_c=1_050.0,
            quadratic_fuel_temperature_gain_c=250.0,
            maximum_combustion_temperature_rise_c=785.0,
            speed_temperature_cooling_gain_c=100.0,
            thermal_time_constant_s=0.6,
            maximum_speed_rpm=104_000.0,
            maximum_normalized_speed=1.10,
            maximum_thrust_n=350.0,
            thrust_speed_exponent=3.0,
            maximum_fuel_flow_ml_min=scaled_maximum_fuel_flow_ml_min,
        ),
    )


def _sensor_configuration() -> SensorModelConfiguration:
    return SensorModelConfiguration(
        rotor_speed=RotorSpeedSensorConfiguration(
            noise_standard_deviation_rpm=50.0,
            quantization_step_rpm=10.0,
            maximum_value_rpm=120_000.0,
        ),
        exhaust_temperature=ExhaustTemperatureSensorConfiguration(
            noise_standard_deviation_c=1.5,
            quantization_step_c=0.5,
            maximum_value_c=850.0,
        ),
    )


def _fadec_calibration() -> FadecCalibration:
    return FadecCalibration(
        calibration_id="adw-b350-stg-provisional-calibration",
        display_name="ADW B350STG provisional B300-family calibration",
        calibration_version="0.1.0",
        target_engine_id=AERODESIGNWORKS_B350_STG_ENGINE_ID,
        speed_schedule=LinearThrottleToSpeedScheduler(
            idle_speed_rpm=35_000.0,
            maximum_speed_rpm=104_000.0,
        ),
        speed_controller=SpeedControllerParameters(
            proportional_gain=4.39e-5,
            integral_gain=5.80e-5,
        ),
        state_machine=EngineStateMachineParameters(
            ignition_enable_speed_rpm=12_000.0,
            self_sustaining_speed_rpm=30_000.0,
            stopped_speed_threshold_rpm=500.0,
            light_off_temperature_c=500.0,
            start_fuel_command=0.25,
        ),
        sensor_validation=SensorValidationConfiguration(
            rotor_speed=RotorSpeedValidationConfiguration(
                maximum_value_rpm=115_000.0,
                maximum_absolute_rate_rpm_s=100_000.0,
            ),
            exhaust_temperature=ExhaustTemperatureValidationConfiguration(
                maximum_value_c=820.0,
            ),
        ),
        fuel_protection=FuelProtectionCalibration(
            exhaust_temperature=ExhaustTemperatureLimiterParameters(
                intervention_exhaust_temperature_c=740.0,
                maximum_exhaust_temperature_c=760.0,
            ),
            acceleration_estimator=RotorAccelerationEstimatorParameters(
                filter_time_constant_s=0.08
            ),
            acceleration=AccelerationLimiterParameters(
                soft_acceleration_limit_rpm_per_s=50_000.0,
                hard_acceleration_limit_rpm_per_s=75_000.0,
            ),
            deceleration=DecelerationLimiterParameters(
                maximum_fuel_decrease_rate_per_s=0.4
            ),
            overspeed=OverspeedLimiterParameters(
                maximum_normal_speed_rpm=104_000.0,
            ),
        ),
    )
