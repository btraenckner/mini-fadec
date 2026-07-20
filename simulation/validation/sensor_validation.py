"""Stateful plausibility validation for raw Mini-FADEC sensor signals."""

from dataclasses import dataclass, field
from enum import Enum

from simulation.core.types import RawSensorData, ValidatedSensorData
from simulation.operation.engine_state import EngineOperatingState


class ChannelHealth(Enum):
    """Usability state of one validated sensor channel."""

    VALID = "VALID"
    SUSPECT = "SUSPECT"
    INVALID = "INVALID"


class ChannelDiagnosticReason(Enum):
    """Typed reason for a channel's current validation state."""

    NONE = "none"
    MEASUREMENT_UNAVAILABLE = "measurement unavailable"
    BELOW_PHYSICAL_RANGE = "below physical range"
    ABOVE_PHYSICAL_RANGE = "above physical range"
    RATE_THRESHOLD_VIOLATION = "rate threshold violation"
    STUCK_SIGNAL = "stuck signal"
    RECOVERING = "valid signal recovering"


@dataclass(frozen=True)
class RotorSpeedValidationConfiguration:
    """Plausibility and debounce assumptions for rotor-speed validation."""

    minimum_value_rpm: float = 0.0
    maximum_value_rpm: float = 145_000.0
    maximum_absolute_rate_rpm_s: float = 100_000.0
    minimum_stuck_change_rpm: float = 1.0
    stuck_persistence_s: float = 0.25
    violation_persistence_s: float = 0.10
    unavailable_persistence_s: float = 0.0
    recovery_time_s: float = 0.20
    last_valid_hold_time_s: float = 0.20

    def __post_init__(self) -> None:
        _validate_configuration(
            minimum_value=self.minimum_value_rpm,
            maximum_value=self.maximum_value_rpm,
            maximum_absolute_rate=self.maximum_absolute_rate_rpm_s,
            minimum_stuck_change=self.minimum_stuck_change_rpm,
            stuck_persistence_s=self.stuck_persistence_s,
            violation_persistence_s=self.violation_persistence_s,
            unavailable_persistence_s=self.unavailable_persistence_s,
            recovery_time_s=self.recovery_time_s,
            last_valid_hold_time_s=self.last_valid_hold_time_s,
            channel_name="rotor-speed validator",
        )


@dataclass(frozen=True)
class ExhaustTemperatureValidationConfiguration:
    """Plausibility and debounce assumptions for EGT validation."""

    minimum_value_c: float = -50.0
    maximum_value_c: float = 950.0
    maximum_absolute_rate_c_s: float = 1_500.0
    minimum_stuck_change_c: float = 0.01
    stuck_persistence_s: float = 0.25
    violation_persistence_s: float = 0.10
    unavailable_persistence_s: float = 0.0
    recovery_time_s: float = 0.20
    last_valid_hold_time_s: float = 0.20

    def __post_init__(self) -> None:
        _validate_configuration(
            minimum_value=self.minimum_value_c,
            maximum_value=self.maximum_value_c,
            maximum_absolute_rate=self.maximum_absolute_rate_c_s,
            minimum_stuck_change=self.minimum_stuck_change_c,
            stuck_persistence_s=self.stuck_persistence_s,
            violation_persistence_s=self.violation_persistence_s,
            unavailable_persistence_s=self.unavailable_persistence_s,
            recovery_time_s=self.recovery_time_s,
            last_valid_hold_time_s=self.last_valid_hold_time_s,
            channel_name="EGT validator",
        )


@dataclass(frozen=True)
class SensorValidationConfiguration:
    """Typed configuration for both validation channels."""

    rotor_speed: RotorSpeedValidationConfiguration = field(
        default_factory=RotorSpeedValidationConfiguration
    )
    exhaust_temperature: ExhaustTemperatureValidationConfiguration = field(
        default_factory=ExhaustTemperatureValidationConfiguration
    )
    command_change_threshold: float = 0.05

    def __post_init__(self) -> None:
        if self.command_change_threshold < 0.0:
            raise ValueError("command_change_threshold cannot be negative")


@dataclass(frozen=True)
class SensorValidationContext:
    """Narrow operating context used only to enable stuck-signal checks."""

    operating_state: EngineOperatingState = EngineOperatingState.OFF
    starter_commanded: bool = False
    ignition_commanded: bool = False
    fuel_enabled: bool = False
    fuel_command: float = 0.0
    throttle_command: float = 0.0


@dataclass(frozen=True)
class ChannelValidationResult:
    """Validated value and diagnostics for one sensor channel."""

    value: float | None
    health: ChannelHealth
    diagnostic_reason: ChannelDiagnosticReason
    value_is_held: bool


@dataclass(frozen=True)
class SensorValidationResult:
    """Complete validated sensor values and channel health diagnostics."""

    sensor_data: ValidatedSensorData
    rotor_speed: ChannelValidationResult
    exhaust_temperature: ChannelValidationResult
    aggregate_health: ChannelHealth


@dataclass
class _ChannelValidationState:
    """Time-based validation state retained for one channel."""

    health: ChannelHealth = ChannelHealth.VALID
    diagnostic_reason: ChannelDiagnosticReason = ChannelDiagnosticReason.NONE
    violation_elapsed_s: float = 0.0
    unavailable_elapsed_s: float = 0.0
    recovery_elapsed_s: float = 0.0
    invalid_elapsed_s: float = 0.0
    unchanged_elapsed_s: float = 0.0
    expected_change_remaining_s: float = 0.0
    elapsed_since_accepted_value_s: float = 0.0
    last_accepted_value: float | None = None
    last_observed_value: float | None = None
    last_valid_value: float | None = None


class SensorSignalValidator:
    """Validate raw measurements without using engine truth or control internals."""

    def __init__(
        self,
        configuration: SensorValidationConfiguration | None = None,
    ) -> None:
        self.configuration = configuration or SensorValidationConfiguration()
        self._rotor_speed_state = _ChannelValidationState()
        self._egt_state = _ChannelValidationState()
        self._previous_context: SensorValidationContext | None = None

    def update(
        self,
        raw_sensor_data: RawSensorData,
        context: SensorValidationContext,
        time_step_s: float,
    ) -> SensorValidationResult:
        """Validate both channels using deterministic simulation-time state."""

        if time_step_s <= 0.0:
            raise ValueError("time_step_s must be greater than zero")

        self._update_expected_change_windows(context, time_step_s)
        rotor_speed_result = self._validate_channel(
            value=raw_sensor_data.rotor_speed_rpm,
            state=self._rotor_speed_state,
            minimum_value=self.configuration.rotor_speed.minimum_value_rpm,
            maximum_value=self.configuration.rotor_speed.maximum_value_rpm,
            maximum_absolute_rate=(
                self.configuration.rotor_speed.maximum_absolute_rate_rpm_s
            ),
            minimum_stuck_change=(
                self.configuration.rotor_speed.minimum_stuck_change_rpm
            ),
            stuck_persistence_s=(
                self.configuration.rotor_speed.stuck_persistence_s
            ),
            violation_persistence_s=(
                self.configuration.rotor_speed.violation_persistence_s
            ),
            unavailable_persistence_s=(
                self.configuration.rotor_speed.unavailable_persistence_s
            ),
            recovery_time_s=self.configuration.rotor_speed.recovery_time_s,
            last_valid_hold_time_s=(
                self.configuration.rotor_speed.last_valid_hold_time_s
            ),
            time_step_s=time_step_s,
        )
        egt_result = self._validate_channel(
            value=raw_sensor_data.exhaust_temperature_c,
            state=self._egt_state,
            minimum_value=self.configuration.exhaust_temperature.minimum_value_c,
            maximum_value=self.configuration.exhaust_temperature.maximum_value_c,
            maximum_absolute_rate=(
                self.configuration.exhaust_temperature.maximum_absolute_rate_c_s
            ),
            minimum_stuck_change=(
                self.configuration.exhaust_temperature.minimum_stuck_change_c
            ),
            stuck_persistence_s=(
                self.configuration.exhaust_temperature.stuck_persistence_s
            ),
            violation_persistence_s=(
                self.configuration.exhaust_temperature.violation_persistence_s
            ),
            unavailable_persistence_s=(
                self.configuration.exhaust_temperature.unavailable_persistence_s
            ),
            recovery_time_s=(
                self.configuration.exhaust_temperature.recovery_time_s
            ),
            last_valid_hold_time_s=(
                self.configuration.exhaust_temperature.last_valid_hold_time_s
            ),
            time_step_s=time_step_s,
        )
        self._previous_context = context

        aggregate_health = max(
            rotor_speed_result.health,
            egt_result.health,
            key=_health_severity,
        )
        return SensorValidationResult(
            sensor_data=ValidatedSensorData(
                rotor_speed_rpm=rotor_speed_result.value,
                exhaust_temperature_c=egt_result.value,
            ),
            rotor_speed=rotor_speed_result,
            exhaust_temperature=egt_result,
            aggregate_health=aggregate_health,
        )

    def reset(self) -> None:
        """Clear timers, histories, held values, and validation health."""

        self._rotor_speed_state = _ChannelValidationState()
        self._egt_state = _ChannelValidationState()
        self._previous_context = None

    def _update_expected_change_windows(
        self,
        context: SensorValidationContext,
        time_step_s: float,
    ) -> None:
        """Enable stuck checks only while operating context expects movement."""

        rotor_configuration = self.configuration.rotor_speed
        egt_configuration = self.configuration.exhaust_temperature
        previous_context = self._previous_context
        fuel_changed = previous_context is not None and abs(
            context.fuel_command - previous_context.fuel_command
        ) >= self.configuration.command_change_threshold
        throttle_changed = previous_context is not None and abs(
            context.throttle_command - previous_context.throttle_command
        ) >= self.configuration.command_change_threshold

        rotor_change_expected = (
            context.starter_commanded
            or context.ignition_commanded
            or context.operating_state is EngineOperatingState.SHUTDOWN
            or fuel_changed
            or throttle_changed
        )
        egt_change_expected = (
            context.ignition_commanded
            or context.operating_state is EngineOperatingState.SHUTDOWN
            or fuel_changed
        )

        self._rotor_speed_state.expected_change_remaining_s = (
            self._updated_expectation_time(
                expected=rotor_change_expected,
                current_remaining_s=(
                    self._rotor_speed_state.expected_change_remaining_s
                ),
                persistence_s=rotor_configuration.stuck_persistence_s,
                time_step_s=time_step_s,
            )
        )
        self._egt_state.expected_change_remaining_s = (
            self._updated_expectation_time(
                expected=egt_change_expected,
                current_remaining_s=self._egt_state.expected_change_remaining_s,
                persistence_s=egt_configuration.stuck_persistence_s,
                time_step_s=time_step_s,
            )
        )

    @staticmethod
    def _updated_expectation_time(
        expected: bool,
        current_remaining_s: float,
        persistence_s: float,
        time_step_s: float,
    ) -> float:
        """Refresh or decrease one expected-change observation window."""

        if expected:
            return persistence_s
        return max(0.0, current_remaining_s - time_step_s)

    def _validate_channel(
        self,
        value: float | None,
        state: _ChannelValidationState,
        minimum_value: float,
        maximum_value: float,
        maximum_absolute_rate: float,
        minimum_stuck_change: float,
        stuck_persistence_s: float,
        violation_persistence_s: float,
        unavailable_persistence_s: float,
        recovery_time_s: float,
        last_valid_hold_time_s: float,
        time_step_s: float,
    ) -> ChannelValidationResult:
        """Run availability, range, rate, stuck, and debounce processing."""

        state.elapsed_since_accepted_value_s += time_step_s
        if value is None:
            state.unavailable_elapsed_s += time_step_s
            reason = ChannelDiagnosticReason.MEASUREMENT_UNAVAILABLE
            immediately_invalid = (
                unavailable_persistence_s <= 0.0
                or state.unavailable_elapsed_s + 1.0e-12
                >= unavailable_persistence_s
            )
            return self._apply_violation(
                state=state,
                reason=reason,
                force_invalid=immediately_invalid,
                violation_persistence_s=violation_persistence_s,
                last_valid_hold_time_s=last_valid_hold_time_s,
                time_step_s=time_step_s,
            )

        state.unavailable_elapsed_s = 0.0
        violation_reason = self._physical_range_violation(
            value,
            minimum_value,
            maximum_value,
        )
        if violation_reason is None:
            violation_reason = self._rate_violation(
                value=value,
                state=state,
                maximum_absolute_rate=maximum_absolute_rate,
            )
        if violation_reason is None:
            violation_reason = self._stuck_violation(
                value=value,
                state=state,
                minimum_stuck_change=minimum_stuck_change,
                stuck_persistence_s=stuck_persistence_s,
                time_step_s=time_step_s,
            )

        state.last_observed_value = value
        if violation_reason is not None:
            return self._apply_violation(
                state=state,
                reason=violation_reason,
                force_invalid=False,
                violation_persistence_s=violation_persistence_s,
                last_valid_hold_time_s=last_valid_hold_time_s,
                time_step_s=time_step_s,
            )

        if state.last_accepted_value is None or value != state.last_accepted_value:
            state.last_accepted_value = value
            state.elapsed_since_accepted_value_s = 0.0
        return self._apply_valid_measurement(
            value=value,
            state=state,
            recovery_time_s=recovery_time_s,
            time_step_s=time_step_s,
        )

    @staticmethod
    def _physical_range_violation(
        value: float,
        minimum_value: float,
        maximum_value: float,
    ) -> ChannelDiagnosticReason | None:
        """Return a range diagnostic when a value is physically implausible."""

        if value < minimum_value:
            return ChannelDiagnosticReason.BELOW_PHYSICAL_RANGE
        if value > maximum_value:
            return ChannelDiagnosticReason.ABOVE_PHYSICAL_RANGE
        return None

    @staticmethod
    def _rate_violation(
        value: float,
        state: _ChannelValidationState,
        maximum_absolute_rate: float,
    ) -> ChannelDiagnosticReason | None:
        """Compare a value with the previous accepted measurement."""

        if state.last_accepted_value is None:
            return None
        elapsed_s = max(state.elapsed_since_accepted_value_s, 1.0e-12)
        absolute_rate = abs(value - state.last_accepted_value) / elapsed_s
        if absolute_rate > maximum_absolute_rate:
            return ChannelDiagnosticReason.RATE_THRESHOLD_VIOLATION
        return None

    @staticmethod
    def _stuck_violation(
        value: float,
        state: _ChannelValidationState,
        minimum_stuck_change: float,
        stuck_persistence_s: float,
        time_step_s: float,
    ) -> ChannelDiagnosticReason | None:
        """Detect insufficient change only when context expects movement."""

        if state.expected_change_remaining_s <= 0.0:
            state.unchanged_elapsed_s = 0.0
            return None
        if state.last_observed_value is None or abs(
            value - state.last_observed_value
        ) >= minimum_stuck_change:
            state.unchanged_elapsed_s = 0.0
            return None

        state.unchanged_elapsed_s += time_step_s
        if state.unchanged_elapsed_s + 1.0e-12 >= stuck_persistence_s:
            return ChannelDiagnosticReason.STUCK_SIGNAL
        return None

    @staticmethod
    def _apply_violation(
        state: _ChannelValidationState,
        reason: ChannelDiagnosticReason,
        force_invalid: bool,
        violation_persistence_s: float,
        last_valid_hold_time_s: float,
        time_step_s: float,
    ) -> ChannelValidationResult:
        """Debounce a violation and provide bounded last-valid fallback."""

        state.recovery_elapsed_s = 0.0
        state.violation_elapsed_s += time_step_s
        was_invalid = state.health is ChannelHealth.INVALID
        should_invalidate = (
            force_invalid
            or was_invalid
            or state.violation_elapsed_s + 1.0e-12
            >= violation_persistence_s
        )
        state.health = (
            ChannelHealth.INVALID if should_invalidate else ChannelHealth.SUSPECT
        )
        state.diagnostic_reason = reason

        if state.health is ChannelHealth.INVALID:
            state.invalid_elapsed_s += time_step_s
        else:
            state.invalid_elapsed_s = 0.0

        may_hold = (
            state.last_valid_value is not None
            and (
                state.health is ChannelHealth.SUSPECT
                or state.invalid_elapsed_s <= last_valid_hold_time_s
            )
        )
        return ChannelValidationResult(
            value=state.last_valid_value if may_hold else None,
            health=state.health,
            diagnostic_reason=reason,
            value_is_held=may_hold,
        )

    @staticmethod
    def _apply_valid_measurement(
        value: float,
        state: _ChannelValidationState,
        recovery_time_s: float,
        time_step_s: float,
    ) -> ChannelValidationResult:
        """Accept valid input immediately or advance debounced recovery."""

        state.violation_elapsed_s = 0.0
        state.unavailable_elapsed_s = 0.0
        state.invalid_elapsed_s = 0.0
        state.last_valid_value = value

        if state.health is ChannelHealth.VALID:
            state.recovery_elapsed_s = 0.0
            state.diagnostic_reason = ChannelDiagnosticReason.NONE
        else:
            state.recovery_elapsed_s += time_step_s
            if state.recovery_elapsed_s + 1.0e-12 >= recovery_time_s:
                state.health = ChannelHealth.VALID
                state.diagnostic_reason = ChannelDiagnosticReason.NONE
                state.recovery_elapsed_s = 0.0
            else:
                state.health = ChannelHealth.SUSPECT
                state.diagnostic_reason = ChannelDiagnosticReason.RECOVERING

        return ChannelValidationResult(
            value=value,
            health=state.health,
            diagnostic_reason=state.diagnostic_reason,
            value_is_held=False,
        )


def _health_severity(health: ChannelHealth) -> int:
    """Return an ordering value for aggregate health calculation."""

    return {
        ChannelHealth.VALID: 0,
        ChannelHealth.SUSPECT: 1,
        ChannelHealth.INVALID: 2,
    }[health]


def _validate_configuration(
    minimum_value: float,
    maximum_value: float,
    maximum_absolute_rate: float,
    minimum_stuck_change: float,
    stuck_persistence_s: float,
    violation_persistence_s: float,
    unavailable_persistence_s: float,
    recovery_time_s: float,
    last_valid_hold_time_s: float,
    channel_name: str,
) -> None:
    """Validate common channel-configuration constraints."""

    if minimum_value > maximum_value:
        raise ValueError(f"{channel_name} minimum cannot exceed maximum")
    nonnegative_values = {
        "maximum absolute rate": maximum_absolute_rate,
        "minimum stuck change": minimum_stuck_change,
        "stuck persistence": stuck_persistence_s,
        "violation persistence": violation_persistence_s,
        "unavailable persistence": unavailable_persistence_s,
        "recovery time": recovery_time_s,
        "last-valid hold time": last_valid_hold_time_s,
    }
    for parameter_name, value in nonnegative_values.items():
        if value < 0.0:
            raise ValueError(f"{channel_name} {parameter_name} cannot be negative")
