"""Deterministic simulation-only fault injection for measured sensor data."""

import random
from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

from simulation.core.types import RawSensorData, SensorData


class SensorChannel(Enum):
    """Sensor channels that support injected simulation faults."""

    ROTOR_SPEED = "rpm"
    EXHAUST_TEMPERATURE = "egt"


@dataclass(frozen=True)
class BiasSensorFault:
    """Add a constant offset to a measured channel."""

    offset: float


@dataclass(frozen=True)
class StuckSensorFault:
    """Freeze a channel at activation or at an explicit configured value."""

    value: float | None = None


@dataclass(frozen=True)
class DropoutSensorFault:
    """Make a measured channel explicitly unavailable."""


@dataclass(frozen=True)
class ForcedValueSensorFault:
    """Replace a channel with a configured value."""

    value: float


@dataclass(frozen=True)
class ExcessiveNoiseSensorFault:
    """Add temporary Gaussian noise to a measured channel."""

    standard_deviation: float

    def __post_init__(self) -> None:
        if self.standard_deviation < 0.0:
            raise ValueError("fault noise standard deviation cannot be negative")


@dataclass(frozen=True)
class DriftSensorFault:
    """Add an offset that increases linearly with active fault time."""

    rate_per_second: float


SensorFaultDefinition: TypeAlias = (
    BiasSensorFault
    | StuckSensorFault
    | DropoutSensorFault
    | ForcedValueSensorFault
    | ExcessiveNoiseSensorFault
    | DriftSensorFault
)


@dataclass
class _ActiveSensorFault:
    """Runtime state associated with one active channel fault."""

    definition: SensorFaultDefinition
    elapsed_time_s: float = 0.0
    retained_stuck_value: float | None = None


class SensorFaultInjector:
    """Apply at most one replaceable fault independently to each channel."""

    def __init__(
        self,
        random_seed: int | None = 0,
        random_generator: random.Random | None = None,
    ) -> None:
        self.random_seed = random_seed
        self._random = random_generator or random.Random(random_seed)
        self._initial_random_state = self._random.getstate()
        self._rotor_speed_fault: _ActiveSensorFault | None = None
        self._egt_fault: _ActiveSensorFault | None = None

    def activate(
        self,
        channel: SensorChannel,
        fault: SensorFaultDefinition,
        current_measurement: float | None = None,
    ) -> None:
        """Activate a fault, explicitly replacing one on the same channel."""

        active_fault = _ActiveSensorFault(definition=fault)
        if isinstance(fault, StuckSensorFault):
            active_fault.retained_stuck_value = (
                fault.value if fault.value is not None else current_measurement
            )
        self._set_active_fault(channel, active_fault)

    def clear(self, channel: SensorChannel) -> None:
        """Clear the active fault and its channel-specific runtime state."""

        self._set_active_fault(channel, None)

    def clear_all(self) -> None:
        """Clear active faults on all channels."""

        self._rotor_speed_fault = None
        self._egt_fault = None

    def is_active(self, channel: SensorChannel) -> bool:
        """Return whether a channel currently has an injected fault."""

        return self._active_fault(channel) is not None

    def active_fault(
        self,
        channel: SensorChannel,
    ) -> SensorFaultDefinition | None:
        """Return the active typed fault definition for a channel."""

        active_fault = self._active_fault(channel)
        return active_fault.definition if active_fault is not None else None

    def describe(self, channel: SensorChannel) -> str:
        """Return a concise diagnostic description of a channel fault."""

        fault = self.active_fault(channel)
        unit = "rpm" if channel is SensorChannel.ROTOR_SPEED else "°C"
        if fault is None:
            return "none"
        if isinstance(fault, BiasSensorFault):
            return f"bias {fault.offset:+g} {unit}"
        if isinstance(fault, StuckSensorFault):
            value = fault.value
            return "stuck current" if value is None else f"stuck {value:g} {unit}"
        if isinstance(fault, DropoutSensorFault):
            return "dropout"
        if isinstance(fault, ForcedValueSensorFault):
            return f"forced value {fault.value:g} {unit}"
        if isinstance(fault, ExcessiveNoiseSensorFault):
            return f"noise σ={fault.standard_deviation:g} {unit}"
        return f"drift {fault.rate_per_second:+g} {unit}/s"

    def apply(
        self,
        sensor_data: SensorData,
        time_step_s: float,
    ) -> RawSensorData:
        """Apply active faults after the normal sensor measurement effects."""

        if time_step_s <= 0.0:
            raise ValueError("time_step_s must be greater than zero")

        return RawSensorData(
            rotor_speed_rpm=self._apply_channel_fault(
                value=sensor_data.rotor_speed_rpm,
                active_fault=self._rotor_speed_fault,
                time_step_s=time_step_s,
            ),
            exhaust_temperature_c=self._apply_channel_fault(
                value=sensor_data.exhaust_temperature_c,
                active_fault=self._egt_fault,
                time_step_s=time_step_s,
            ),
        )

    def reset(self) -> None:
        """Clear faults and restore the initial deterministic random state."""

        self.clear_all()
        self._random.setstate(self._initial_random_state)

    def _apply_channel_fault(
        self,
        value: float,
        active_fault: _ActiveSensorFault | None,
        time_step_s: float,
    ) -> float | None:
        """Apply one channel fault and advance its simulation-time state."""

        if active_fault is None:
            return value

        fault = active_fault.definition
        if isinstance(fault, BiasSensorFault):
            faulted_value: float | None = value + fault.offset
        elif isinstance(fault, StuckSensorFault):
            if active_fault.retained_stuck_value is None:
                active_fault.retained_stuck_value = value
            faulted_value = active_fault.retained_stuck_value
        elif isinstance(fault, DropoutSensorFault):
            faulted_value = None
        elif isinstance(fault, ForcedValueSensorFault):
            faulted_value = fault.value
        elif isinstance(fault, ExcessiveNoiseSensorFault):
            faulted_value = value
            if fault.standard_deviation > 0.0:
                faulted_value += self._random.gauss(
                    mu=0.0,
                    sigma=fault.standard_deviation,
                )
        else:
            faulted_value = (
                value + fault.rate_per_second * active_fault.elapsed_time_s
            )

        active_fault.elapsed_time_s += time_step_s
        return faulted_value

    def _active_fault(
        self,
        channel: SensorChannel,
    ) -> _ActiveSensorFault | None:
        """Return the runtime fault state for a channel."""

        if channel is SensorChannel.ROTOR_SPEED:
            return self._rotor_speed_fault
        return self._egt_fault

    def _set_active_fault(
        self,
        channel: SensorChannel,
        active_fault: _ActiveSensorFault | None,
    ) -> None:
        """Set the runtime fault state for a channel."""

        if channel is SensorChannel.ROTOR_SPEED:
            self._rotor_speed_fault = active_fault
        else:
            self._egt_fault = active_fault
