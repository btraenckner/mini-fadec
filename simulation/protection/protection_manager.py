"""Centralized deterministic arbitration of all normal fuel protection."""

from dataclasses import dataclass

from simulation.core.types import ActuatorCommand, SensorData, ValidatedSensorData
from simulation.operation.engine_state import EngineOperatingState
from simulation.protection.acceleration_limiter import (
    AccelerationLimiter,
    RotorAccelerationEstimator,
)
from simulation.protection.deceleration_limiter import DecelerationLimiter
from simulation.protection.exhaust_temperature_limiter import (
    ExhaustTemperatureLimiter,
)
from simulation.protection.overspeed_limiter import OverspeedLimiter
from simulation.protection.types import (
    FuelArbitrationResult,
    FuelLimitCandidates,
    ProtectionContext,
    ProtectionDiagnosticReason,
    ProtectionLimiter,
    ProtectionResult,
)


@dataclass(frozen=True)
class ProtectionManagerParameters:
    """Physical fuel bounds and numeric arbitration tolerance."""

    minimum_fuel_command: float = 0.0
    maximum_fuel_command: float = 1.0
    equal_limit_tolerance: float = 1.0e-9

    def __post_init__(self) -> None:
        if self.minimum_fuel_command > self.maximum_fuel_command:
            raise ValueError("minimum fuel command cannot exceed maximum")
        if self.equal_limit_tolerance < 0.0:
            raise ValueError("equal limit tolerance cannot be negative")


class ProtectionManager:
    """Evaluate protection functions and select the final fuel authority."""

    _DIAGNOSTIC_PRIORITY = (
        ProtectionLimiter.HARD_CUTOFF,
        ProtectionLimiter.SENSOR_FAULT,
        ProtectionLimiter.OVERSPEED,
        ProtectionLimiter.EGT,
        ProtectionLimiter.ACCELERATION,
        ProtectionLimiter.DECELERATION,
        ProtectionLimiter.STATE,
    )
    _STATE_HARD_CUTOFFS = frozenset(
        {
            EngineOperatingState.OFF,
            EngineOperatingState.SHUTDOWN,
            EngineOperatingState.FAULT,
        }
    )

    def __init__(
        self,
        egt_limiter: ExhaustTemperatureLimiter | None = None,
        acceleration_estimator: RotorAccelerationEstimator | None = None,
        acceleration_limiter: AccelerationLimiter | None = None,
        deceleration_limiter: DecelerationLimiter | None = None,
        overspeed_limiter: OverspeedLimiter | None = None,
        parameters: ProtectionManagerParameters | None = None,
    ) -> None:
        self.egt_limiter = egt_limiter or ExhaustTemperatureLimiter()
        self.acceleration_estimator = (
            acceleration_estimator or RotorAccelerationEstimator()
        )
        self.acceleration_limiter = (
            acceleration_limiter or AccelerationLimiter()
        )
        self.deceleration_limiter = (
            deceleration_limiter or DecelerationLimiter()
        )
        self.overspeed_limiter = overspeed_limiter or OverspeedLimiter()
        self.parameters = parameters or ProtectionManagerParameters()
        self._previous_operating_state: EngineOperatingState | None = None
        self._last_result = self._initial_result()

    @property
    def last_result(self) -> ProtectionResult:
        """Return the most recent complete protection diagnostics."""

        return self._last_result

    def apply(
        self,
        requested_fuel_command: float,
        sensor_data: ValidatedSensorData,
        context: ProtectionContext,
        time_step_s: float,
    ) -> ProtectionResult:
        """Evaluate every candidate and determine the final fuel command."""

        if time_step_s <= 0.0:
            raise ValueError("time_step_s must be greater than zero")

        if (
            self._previous_operating_state is not None
            and context.operating_state is not self._previous_operating_state
        ):
            self.acceleration_estimator.reset()
            self.acceleration_limiter.reset()

        requested_fuel = self._clamp(requested_fuel_command)
        acceleration_estimate = self.acceleration_estimator.update(
            sensor_data.rotor_speed_rpm,
            time_step_s,
        )
        acceleration_result = self.acceleration_limiter.evaluate(
            requested_fuel_command=requested_fuel,
            acceleration_estimate=acceleration_estimate,
            operating_state=context.operating_state,
            time_step_s=time_step_s,
        )
        overspeed_result = self.overspeed_limiter.evaluate(
            requested_fuel_command=requested_fuel,
            rotor_speed_rpm=sensor_data.rotor_speed_rpm,
            operating_state=context.operating_state,
            time_step_s=time_step_s,
        )
        base_hard_cutoff = (
            context.sensor_critical_condition
            or context.operating_state in self._STATE_HARD_CUTOFFS
        )
        if base_hard_cutoff:
            egt_fuel_limit, egt_active = requested_fuel, False
        else:
            egt_fuel_limit, egt_active = self._egt_limit(
                requested_fuel=requested_fuel,
                sensor_data=sensor_data,
                time_step_s=time_step_s,
            )

        state_maximum = (
            self.parameters.maximum_fuel_command
            if context.fuel_enabled
            else self.parameters.minimum_fuel_command
        )
        hard_cutoff_sources = self._hard_cutoff_sources(
            context=context,
            hard_overspeed_active=overspeed_result.hard_active,
        )
        deceleration_result = self.deceleration_limiter.evaluate(
            requested_fuel_command=requested_fuel,
            operating_state=context.operating_state,
            time_step_s=time_step_s,
            bypass=bool(hard_cutoff_sources),
        )
        candidates = FuelLimitCandidates(
            requested_fuel_command=requested_fuel,
            egt_fuel_limit=egt_fuel_limit,
            egt_active=egt_active,
            acceleration_fuel_limit=acceleration_result.fuel_limit,
            acceleration_active=acceleration_result.active,
            overspeed_fuel_limit=overspeed_result.fuel_limit,
            overspeed_active=(
                overspeed_result.hard_active
                or overspeed_result.fuel_limit
                < requested_fuel - self.parameters.equal_limit_tolerance
            ),
            deceleration_minimum_fuel_command=(
                deceleration_result.minimum_fuel_command
            ),
            deceleration_active=deceleration_result.active,
            state_maximum_fuel_command=state_maximum,
        )
        arbitration = self.arbitrate(
            candidates,
            hard_cutoff_sources=hard_cutoff_sources,
        )
        diagnostic_reasons = self._diagnostic_reasons(
            egt_active=egt_active,
            acceleration_active=acceleration_result.active,
            deceleration_active=deceleration_result.active,
            soft_overspeed_active=overspeed_result.soft_active,
            hard_overspeed_active=overspeed_result.hard_active,
            state_limited=state_maximum < self.parameters.maximum_fuel_command,
            state_hard_cutoff=(
                context.operating_state in self._STATE_HARD_CUTOFFS
            ),
            sensor_critical=context.sensor_critical_condition,
            arbitration_conflict=arbitration.arbitration_conflict,
        )

        acceleration = acceleration_estimate.acceleration_rpm_per_s
        result = ProtectionResult(
            requested_fuel_command=requested_fuel_command,
            final_fuel_command=arbitration.final_fuel_command,
            egt_fuel_limit=egt_fuel_limit,
            acceleration_fuel_limit=acceleration_result.fuel_limit,
            overspeed_fuel_limit=overspeed_result.fuel_limit,
            deceleration_minimum_fuel_command=(
                deceleration_result.minimum_fuel_command
            ),
            state_maximum_fuel_command=state_maximum,
            active_limiter=arbitration.active_limiter,
            constraining_limiters=arbitration.constraining_limiters,
            rotor_acceleration_rpm_per_s=acceleration,
            rotor_deceleration_rpm_per_s=(
                None if acceleration is None else max(-acceleration, 0.0)
            ),
            speed_ratio=overspeed_result.speed_ratio,
            soft_overspeed_active=overspeed_result.soft_active,
            hard_overspeed_active=overspeed_result.hard_active,
            hard_cutoff_active=bool(hard_cutoff_sources),
            critical_protection_fault_request=(
                context.sensor_critical_condition
                or overspeed_result.critical_fault_request
            ),
            arbitration_conflict=arbitration.arbitration_conflict,
            diagnostic_reasons=diagnostic_reasons,
        )
        self._retain_state(result, context.operating_state)
        return result

    def arbitrate(
        self,
        candidates: FuelLimitCandidates,
        *,
        hard_cutoff_sources: tuple[ProtectionLimiter, ...] = (),
    ) -> FuelArbitrationResult:
        """Combine typed upper/lower limits with safety-cutoff precedence."""

        tolerance = self.parameters.equal_limit_tolerance
        requested_fuel = self._clamp(candidates.requested_fuel_command)
        upper_limits: list[tuple[ProtectionLimiter, float]] = [
            (
                ProtectionLimiter.STATE,
                self._clamp(candidates.state_maximum_fuel_command),
            )
        ]
        if candidates.egt_active:
            upper_limits.append(
                (ProtectionLimiter.EGT, self._clamp(candidates.egt_fuel_limit))
            )
        if candidates.acceleration_active:
            upper_limits.append(
                (
                    ProtectionLimiter.ACCELERATION,
                    self._clamp(candidates.acceleration_fuel_limit),
                )
            )
        if candidates.overspeed_active:
            upper_limits.append(
                (
                    ProtectionLimiter.OVERSPEED,
                    self._clamp(candidates.overspeed_fuel_limit),
                )
            )

        if hard_cutoff_sources:
            constraining = self._ordered_limiters(
                (*hard_cutoff_sources, ProtectionLimiter.HARD_CUTOFF)
            )
            return FuelArbitrationResult(
                final_fuel_command=0.0,
                active_limiter=ProtectionLimiter.HARD_CUTOFF,
                constraining_limiters=constraining,
                arbitration_conflict=False,
            )

        safety_upper = min(limit for _, limit in upper_limits)
        lower_allowed = self._clamp(
            max(
                self.parameters.minimum_fuel_command,
                candidates.deceleration_minimum_fuel_command,
            )
        )
        arbitration_conflict = lower_allowed > safety_upper + tolerance
        if arbitration_conflict:
            final_fuel = safety_upper
        else:
            final_fuel = min(max(requested_fuel, lower_allowed), safety_upper)

        constraining_limiters: list[ProtectionLimiter] = []
        demand_before_safety = max(requested_fuel, lower_allowed)
        safety_is_constraining = (
            safety_upper < demand_before_safety - tolerance
            or arbitration_conflict
        )
        if safety_is_constraining:
            constraining_limiters.extend(
                limiter
                for limiter, limit in upper_limits
                if abs(limit - safety_upper) <= tolerance
            )
        if (
            candidates.deceleration_active
            and lower_allowed > requested_fuel + tolerance
        ):
            constraining_limiters.append(ProtectionLimiter.DECELERATION)

        constraining = self._ordered_limiters(tuple(constraining_limiters))
        active_limiter = (
            constraining[0] if constraining else ProtectionLimiter.NONE
        )
        return FuelArbitrationResult(
            final_fuel_command=self._clamp(final_fuel),
            active_limiter=active_limiter,
            constraining_limiters=constraining,
            arbitration_conflict=arbitration_conflict,
        )

    def reset(self) -> None:
        """Clear all retained protection estimates and diagnostics."""

        self.acceleration_estimator.reset()
        self.acceleration_limiter.reset()
        self.deceleration_limiter.reset()
        self.overspeed_limiter.reset()
        self._previous_operating_state = None
        self._last_result = self._initial_result()

    def _egt_limit(
        self,
        requested_fuel: float,
        sensor_data: ValidatedSensorData,
        time_step_s: float,
    ) -> tuple[float, bool]:
        if (
            sensor_data.rotor_speed_rpm is None
            or sensor_data.exhaust_temperature_c is None
        ):
            return requested_fuel, False

        protected_command = self.egt_limiter.apply(
            requested_command=ActuatorCommand(fuel_command=requested_fuel),
            sensor_data=SensorData(
                rotor_speed_rpm=sensor_data.rotor_speed_rpm,
                exhaust_temperature_c=sensor_data.exhaust_temperature_c,
            ),
            time_step_s=time_step_s,
        )
        fuel_limit = self._clamp(protected_command.fuel_command)
        return (
            fuel_limit,
            fuel_limit
            < requested_fuel - self.parameters.equal_limit_tolerance,
        )

    def _hard_cutoff_sources(
        self,
        context: ProtectionContext,
        hard_overspeed_active: bool,
    ) -> tuple[ProtectionLimiter, ...]:
        sources: list[ProtectionLimiter] = []
        if context.operating_state in self._STATE_HARD_CUTOFFS:
            sources.append(ProtectionLimiter.STATE)
        if context.sensor_critical_condition:
            sources.append(ProtectionLimiter.SENSOR_FAULT)
        if hard_overspeed_active:
            sources.append(ProtectionLimiter.OVERSPEED)
        return tuple(sources)

    @staticmethod
    def _diagnostic_reasons(
        *,
        egt_active: bool,
        acceleration_active: bool,
        deceleration_active: bool,
        soft_overspeed_active: bool,
        hard_overspeed_active: bool,
        state_limited: bool,
        state_hard_cutoff: bool,
        sensor_critical: bool,
        arbitration_conflict: bool,
    ) -> tuple[ProtectionDiagnosticReason, ...]:
        reasons: list[ProtectionDiagnosticReason] = []
        if egt_active:
            reasons.append(ProtectionDiagnosticReason.EGT_LIMITING)
        if acceleration_active:
            reasons.append(ProtectionDiagnosticReason.ACCELERATION_LIMITING)
        if deceleration_active:
            reasons.append(ProtectionDiagnosticReason.DECELERATION_LIMITING)
        if soft_overspeed_active:
            reasons.append(ProtectionDiagnosticReason.SOFT_OVERSPEED)
        if hard_overspeed_active:
            reasons.append(ProtectionDiagnosticReason.HARD_OVERSPEED)
        if state_limited:
            reasons.append(ProtectionDiagnosticReason.STATE_FUEL_LIMIT)
        if state_hard_cutoff:
            reasons.append(ProtectionDiagnosticReason.STATE_HARD_CUTOFF)
        if sensor_critical:
            reasons.append(ProtectionDiagnosticReason.SENSOR_CRITICAL_CUTOFF)
        if arbitration_conflict:
            reasons.append(ProtectionDiagnosticReason.ARBITRATION_CONFLICT)
        return tuple(reasons) or (ProtectionDiagnosticReason.NONE,)

    def _retain_state(
        self,
        result: ProtectionResult,
        operating_state: EngineOperatingState,
    ) -> None:
        if result.hard_cutoff_active:
            self.deceleration_limiter.reset()
            self.acceleration_estimator.reset()
            self.acceleration_limiter.reset()
        else:
            self.deceleration_limiter.retain_final_fuel_command(
                result.final_fuel_command
            )
        self._previous_operating_state = operating_state
        self._last_result = result

    def _ordered_limiters(
        self,
        limiters: tuple[ProtectionLimiter, ...],
    ) -> tuple[ProtectionLimiter, ...]:
        unique_limiters = set(limiters)
        return tuple(
            limiter
            for limiter in self._DIAGNOSTIC_PRIORITY
            if limiter in unique_limiters
        )

    def _clamp(self, value: float) -> float:
        return max(
            self.parameters.minimum_fuel_command,
            min(value, self.parameters.maximum_fuel_command),
        )

    @staticmethod
    def _initial_result() -> ProtectionResult:
        return ProtectionResult(
            requested_fuel_command=0.0,
            final_fuel_command=0.0,
            egt_fuel_limit=0.0,
            acceleration_fuel_limit=0.0,
            overspeed_fuel_limit=0.0,
            deceleration_minimum_fuel_command=0.0,
            state_maximum_fuel_command=0.0,
            active_limiter=ProtectionLimiter.HARD_CUTOFF,
            constraining_limiters=(
                ProtectionLimiter.HARD_CUTOFF,
                ProtectionLimiter.STATE,
            ),
            rotor_acceleration_rpm_per_s=None,
            rotor_deceleration_rpm_per_s=None,
            speed_ratio=0.0,
            soft_overspeed_active=False,
            hard_overspeed_active=False,
            hard_cutoff_active=True,
            critical_protection_fault_request=False,
            arbitration_conflict=False,
            diagnostic_reasons=(
                ProtectionDiagnosticReason.STATE_HARD_CUTOFF,
            ),
        )
