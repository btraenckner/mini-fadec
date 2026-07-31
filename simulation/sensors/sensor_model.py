"""Configurable sensor model sampled by the central scheduler."""

import random
from dataclasses import dataclass, field

from simulation.core.types import EngineState, SensorData


@dataclass(frozen=True)
class RotorSpeedSensorConfiguration:
    """Configuration assumptions for the rotor-speed measurement channel."""

    bias_rpm: float = 0.0
    noise_standard_deviation_rpm: float = 50.0
    quantization_step_rpm: float = 10.0
    minimum_value_rpm: float = 0.0
    maximum_value_rpm: float = 150_000.0
    sample_period_s: float = 0.01

    def __post_init__(self) -> None:
        _validate_channel_configuration(
            noise_standard_deviation=self.noise_standard_deviation_rpm,
            quantization_step=self.quantization_step_rpm,
            minimum_value=self.minimum_value_rpm,
            maximum_value=self.maximum_value_rpm,
            sample_period_s=self.sample_period_s,
            channel_name="rotor-speed sensor",
        )


@dataclass(frozen=True)
class ExhaustTemperatureSensorConfiguration:
    """Configuration assumptions for the EGT measurement channel."""

    bias_c: float = 0.0
    noise_standard_deviation_c: float = 1.0
    quantization_step_c: float = 0.5
    minimum_value_c: float = -50.0
    maximum_value_c: float = 1_000.0
    sample_period_s: float = 0.02

    def __post_init__(self) -> None:
        _validate_channel_configuration(
            noise_standard_deviation=self.noise_standard_deviation_c,
            quantization_step=self.quantization_step_c,
            minimum_value=self.minimum_value_c,
            maximum_value=self.maximum_value_c,
            sample_period_s=self.sample_period_s,
            channel_name="EGT sensor",
        )


@dataclass(frozen=True)
class SensorModelConfiguration:
    """Configuration for all modeled engine measurement channels."""

    rotor_speed: RotorSpeedSensorConfiguration = field(
        default_factory=RotorSpeedSensorConfiguration
    )
    exhaust_temperature: ExhaustTemperatureSensorConfiguration = field(
        default_factory=ExhaustTemperatureSensorConfiguration
    )
    random_seed: int | None = 0


class ConfigurableSensorModel:
    """Convert engine truth into sampled, imperfect sensor measurements."""

    def __init__(
        self,
        configuration: SensorModelConfiguration | None = None,
        random_generator: random.Random | None = None,
    ) -> None:
        self.configuration = configuration or SensorModelConfiguration()
        self._random = random_generator or random.Random(
            self.configuration.random_seed
        )
        self._initial_random_state = self._random.getstate()

        self._retained_rotor_speed_rpm: float | None = None
        self._retained_exhaust_temperature_c: float | None = None

    @property
    def rotor_speed_sample_period_s(self) -> float:
        """Return the configured rotor-speed measurement sample period."""

        return self.configuration.rotor_speed.sample_period_s

    @property
    def exhaust_temperature_sample_period_s(self) -> float:
        """Return the configured EGT measurement sample period."""

        return self.configuration.exhaust_temperature.sample_period_s

    def measure(
        self,
        engine_state: EngineState,
        time_step_s: float,
    ) -> SensorData:
        """Sample both channels once and retain the newly released values."""

        if time_step_s <= 0.0:
            raise ValueError("time_step_s must be greater than zero")

        rotor_configuration = self.configuration.rotor_speed
        egt_configuration = self.configuration.exhaust_temperature
        self._retained_rotor_speed_rpm = self._measure_value(
            true_value=engine_state.rotor_speed_rpm,
            bias=rotor_configuration.bias_rpm,
            noise_standard_deviation=(
                rotor_configuration.noise_standard_deviation_rpm
            ),
            quantization_step=rotor_configuration.quantization_step_rpm,
            minimum_value=rotor_configuration.minimum_value_rpm,
            maximum_value=rotor_configuration.maximum_value_rpm,
        )
        self._retained_exhaust_temperature_c = self._measure_value(
            true_value=engine_state.exhaust_temperature_c,
            bias=egt_configuration.bias_c,
            noise_standard_deviation=(
                egt_configuration.noise_standard_deviation_c
            ),
            quantization_step=egt_configuration.quantization_step_c,
            minimum_value=egt_configuration.minimum_value_c,
            maximum_value=egt_configuration.maximum_value_c,
        )

        return SensorData(
            rotor_speed_rpm=self._retained_rotor_speed_rpm,
            exhaust_temperature_c=self._retained_exhaust_temperature_c,
        )

    def reset(self) -> None:
        """Reset retained values and deterministic random state."""

        self._retained_rotor_speed_rpm = None
        self._retained_exhaust_temperature_c = None
        self._random.setstate(self._initial_random_state)

    def _measure_value(
        self,
        true_value: float,
        bias: float,
        noise_standard_deviation: float,
        quantization_step: float,
        minimum_value: float,
        maximum_value: float,
    ) -> float:
        """Apply the documented measurement pipeline in explicit stages."""

        biased_value = true_value + bias
        noisy_value = biased_value
        if noise_standard_deviation > 0.0:
            noisy_value += self._random.gauss(
                mu=0.0,
                sigma=noise_standard_deviation,
            )

        quantized_value = noisy_value
        if quantization_step > 0.0:
            quantized_value = (
                round(noisy_value / quantization_step) * quantization_step
            )

        return max(minimum_value, min(quantized_value, maximum_value))



def _validate_channel_configuration(
    noise_standard_deviation: float,
    quantization_step: float,
    minimum_value: float,
    maximum_value: float,
    sample_period_s: float,
    channel_name: str,
) -> None:
    """Validate the common constraints of a measurement channel."""

    if noise_standard_deviation < 0.0:
        raise ValueError(
            f"{channel_name} noise standard deviation cannot be negative"
        )
    if quantization_step < 0.0:
        raise ValueError(f"{channel_name} quantization step cannot be negative")
    if minimum_value > maximum_value:
        raise ValueError(
            f"{channel_name} minimum value cannot exceed maximum value"
        )
    if sample_period_s <= 0.0:
        raise ValueError(
            f"{channel_name} sample_period_s must be greater than zero"
        )
