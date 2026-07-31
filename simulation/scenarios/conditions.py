"""Typed read-only conditions for deterministic scenario sequencing."""

from dataclasses import dataclass
from typing import Mapping, Protocol

from simulation.operation.engine_state import EngineOperatingState
from simulation.protection.types import ProtectionLimiter
from simulation.sensors.fault_injection import SensorChannel
from simulation.telemetry.events import EventType, SimulationEvent
from simulation.telemetry.snapshot import SimulationSnapshot
from simulation.validation.sensor_validation import ChannelHealth


class ActionResultView(Protocol):
    """Narrow action-result view used by dependency conditions."""

    @property
    def status_name(self) -> str:
        """Return the stable execution-status name."""
        ...

    @property
    def execution_time_s(self) -> float | None:
        """Return the action execution time when available."""
        ...


@dataclass(frozen=True)
class ConditionContext:
    """Immutable observable data available to scenario conditions."""

    latest_snapshot: SimulationSnapshot
    snapshots: tuple[SimulationSnapshot, ...]
    recent_events: tuple[SimulationEvent, ...]
    action_results: Mapping[str, ActionResultView]


class ScenarioCondition(Protocol):
    """Public protocol implemented by typed scenario conditions."""

    def evaluate(self, context: ConditionContext) -> bool:
        """Evaluate only immutable snapshots, events, and action results."""
        ...


@dataclass(frozen=True)
class EngineStateEqualsCondition:
    """Match the current engine operating state."""

    target_state: EngineOperatingState

    def evaluate(self, context: ConditionContext) -> bool:
        return context.latest_snapshot.operating_state is self.target_state


@dataclass(frozen=True)
class EngineStateReachedCondition:
    """Match once an engine operating state has appeared in captured evidence."""

    target_state: EngineOperatingState

    def evaluate(self, context: ConditionContext) -> bool:
        return any(
            snapshot.operating_state is self.target_state
            for snapshot in context.snapshots
        )


@dataclass(frozen=True)
class ValidatedRotorSpeedAboveCondition:
    """Match an available validated speed at or above an inclusive threshold."""

    threshold_rpm: float

    def evaluate(self, context: ConditionContext) -> bool:
        value = context.latest_snapshot.validated_rotor_speed_rpm
        return value is not None and value >= self.threshold_rpm


@dataclass(frozen=True)
class ValidatedRotorSpeedBelowCondition:
    """Match an available validated speed at or below an inclusive threshold."""

    threshold_rpm: float

    def evaluate(self, context: ConditionContext) -> bool:
        value = context.latest_snapshot.validated_rotor_speed_rpm
        return value is not None and value <= self.threshold_rpm


@dataclass(frozen=True)
class ValidatedEgtAboveCondition:
    """Match an available validated EGT at or above an inclusive threshold."""

    threshold_c: float

    def evaluate(self, context: ConditionContext) -> bool:
        value = context.latest_snapshot.validated_exhaust_temperature_c
        return value is not None and value >= self.threshold_c


@dataclass(frozen=True)
class ValidatedEgtBelowCondition:
    """Match an available validated EGT at or below an inclusive threshold."""

    threshold_c: float

    def evaluate(self, context: ConditionContext) -> bool:
        value = context.latest_snapshot.validated_exhaust_temperature_c
        return value is not None and value <= self.threshold_c


@dataclass(frozen=True)
class ThrottleDemandAtLeastCondition:
    """Match normalized throttle demand at or above an inclusive threshold."""

    threshold: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.threshold <= 1.0:
            raise ValueError("throttle threshold must be between zero and one")

    def evaluate(self, context: ConditionContext) -> bool:
        return context.latest_snapshot.throttle_demand >= self.threshold


@dataclass(frozen=True)
class ActiveLimiterEqualsCondition:
    """Match the current primary protection limiter."""

    target_limiter: ProtectionLimiter

    def evaluate(self, context: ConditionContext) -> bool:
        return (
            context.latest_snapshot.active_protection_limiter
            is self.target_limiter
        )


@dataclass(frozen=True)
class LimiterInactiveCondition:
    """Match when no normal protection limiter is active."""

    def evaluate(self, context: ConditionContext) -> bool:
        return (
            context.latest_snapshot.active_protection_limiter
            is ProtectionLimiter.NONE
        )


@dataclass(frozen=True)
class SensorHealthEqualsCondition:
    """Match one channel's current validation health."""

    channel: SensorChannel
    target_health: ChannelHealth

    def evaluate(self, context: ConditionContext) -> bool:
        snapshot = context.latest_snapshot
        health = (
            snapshot.rotor_speed_health
            if self.channel is SensorChannel.ROTOR_SPEED
            else snapshot.exhaust_temperature_health
        )
        return health is self.target_health


@dataclass(frozen=True)
class CriticalProtectionRequestActiveCondition:
    """Match an active critical protection request."""

    def evaluate(self, context: ConditionContext) -> bool:
        return context.latest_snapshot.critical_protection_fault_request


@dataclass(frozen=True)
class EventTypeObservedCondition:
    """Match a typed event, optionally narrowed by source and diagnostic code."""

    event_type: EventType
    source: str | None = None
    diagnostic_code: str | None = None

    def evaluate(self, context: ConditionContext) -> bool:
        return any(
            event.event_type is self.event_type
            and (self.source is None or event.source == self.source)
            and (
                self.diagnostic_code is None
                or event.diagnostic_code == self.diagnostic_code
            )
            for event in context.recent_events
        )


@dataclass(frozen=True)
class ActionExecutedCondition:
    """Match another action's execution, optionally requiring success."""

    action_id: str
    require_success: bool = True

    def __post_init__(self) -> None:
        if not self.action_id.strip():
            raise ValueError("dependency action_id cannot be empty")

    def evaluate(self, context: ConditionContext) -> bool:
        result = context.action_results.get(self.action_id)
        if result is None:
            return False
        if self.require_success:
            return result.status_name == "EXECUTED"
        return result.status_name not in {"PENDING", "TIMED_OUT"}


@dataclass(frozen=True)
class ElapsedAfterActionCondition:
    """Match after a configured simulation-time delay from another action."""

    action_id: str
    elapsed_s: float
    require_success: bool = True

    def __post_init__(self) -> None:
        if not self.action_id.strip():
            raise ValueError("reference action_id cannot be empty")
        if self.elapsed_s < 0.0:
            raise ValueError("elapsed_s cannot be negative")

    def evaluate(self, context: ConditionContext) -> bool:
        result = context.action_results.get(self.action_id)
        if result is None or result.execution_time_s is None:
            return False
        if self.require_success and result.status_name != "EXECUTED":
            return False
        return (
            context.latest_snapshot.simulation_time_s
            + _time_tolerance(context.latest_snapshot.simulation_time_s)
            >= result.execution_time_s + self.elapsed_s
        )


@dataclass(frozen=True)
class AllConditions:
    """Match when every explicitly typed child condition matches."""

    conditions: tuple[ScenarioCondition, ...]

    def __post_init__(self) -> None:
        if not self.conditions:
            raise ValueError("AllConditions requires at least one condition")

    def evaluate(self, context: ConditionContext) -> bool:
        return all(condition.evaluate(context) for condition in self.conditions)


def _time_tolerance(value: float) -> float:
    return 1.0e-12 * max(1.0, abs(value))
