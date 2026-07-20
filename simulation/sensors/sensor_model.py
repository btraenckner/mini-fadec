"""Configurable sensor model for the Mini-FADEC simulation."""

import math
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

        self._rotor_speed_elapsed_s = 0.0
        self._egt_elapsed_s = 0.0
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
        """Publish sampled measurements derived from the current truth state."""

        if time_step_s <= 0.0:
            raise ValueError("time_step_s must be greater than zero")

        self._update_rotor_speed_measurement(engine_state, time_step_s)
        self._update_exhaust_temperature_measurement(
            engine_state,
            time_step_s,
        )

        if (
            self._retained_rotor_speed_rpm is None
            or self._retained_exhaust_temperature_c is None
        ):
            raise RuntimeError("sensor model did not produce valid measurements")

        return SensorData(
            rotor_speed_rpm=self._retained_rotor_speed_rpm,
            exhaust_temperature_c=self._retained_exhaust_temperature_c,
        )

    def reset(self) -> None:
        """Reset sample timing, retained values, and deterministic randomness."""

        self._rotor_speed_elapsed_s = 0.0
        self._egt_elapsed_s = 0.0
        self._retained_rotor_speed_rpm = None
        self._retained_exhaust_temperature_c = None
        self._random.setstate(self._initial_random_state)

    def _update_rotor_speed_measurement(
        self,
        engine_state: EngineState,
        time_step_s: float,
    ) -> None:
        """Update or retain the independently sampled rotor-speed signal."""

        configuration = self.configuration.rotor_speed
        should_sample, self._rotor_speed_elapsed_s = self._sampling_state(
            retained_value=self._retained_rotor_speed_rpm,
            elapsed_s=self._rotor_speed_elapsed_s,
            time_step_s=time_step_s,
            sample_period_s=configuration.sample_period_s,
        )
        if should_sample:
            self._retained_rotor_speed_rpm = self._measure_value(
                true_value=engine_state.rotor_speed_rpm,
                bias=configuration.bias_rpm,
                noise_standard_deviation=(
                    configuration.noise_standard_deviation_rpm
                ),
                quantization_step=configuration.quantization_step_rpm,
                minimum_value=configuration.minimum_value_rpm,
                maximum_value=configuration.maximum_value_rpm,
            )

    def _update_exhaust_temperature_measurement(
        self,
        engine_state: EngineState,
        time_step_s: float,
    ) -> None:
        """Update or retain the independently sampled EGT signal."""

        configuration = self.configuration.exhaust_temperature
        should_sample, self._egt_elapsed_s = self._sampling_state(
            retained_value=self._retained_exhaust_temperature_c,
            elapsed_s=self._egt_elapsed_s,
            time_step_s=time_step_s,
            sample_period_s=configuration.sample_period_s,
        )
        if should_sample:
            self._retained_exhaust_temperature_c = self._measure_value(
                true_value=engine_state.exhaust_temperature_c,
                bias=configuration.bias_c,
                noise_standard_deviation=(
                    configuration.noise_standard_deviation_c
                ),
                quantization_step=configuration.quantization_step_c,
                minimum_value=configuration.minimum_value_c,
                maximum_value=configuration.maximum_value_c,
            )

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

    @staticmethod
    def _sampling_state(
        retained_value: float | None,
        elapsed_s: float,
        time_step_s: float,
        sample_period_s: float,
    ) -> tuple[bool, float]:
        """Return whether to sample and the retained fractional elapsed time."""

        if retained_value is None:
            return True, 0.0

        updated_elapsed_s = elapsed_s + time_step_s
        tolerance_s = 1.0e-12 * max(1.0, sample_period_s)
        if updated_elapsed_s + tolerance_s < sample_period_s:
            return False, updated_elapsed_s

        return True, math.fmod(updated_elapsed_s, sample_period_s)


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
