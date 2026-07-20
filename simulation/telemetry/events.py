"""Typed discrete events and deterministic snapshot transition monitoring."""

import json
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, TypeAlias

from simulation.operation.engine_state import EngineOperatingState
from simulation.protection.types import ProtectionLimiter
from simulation.telemetry.snapshot import SimulationSnapshot


EVENT_SCHEMA_VERSION = "1.0"


class EventCategory(Enum):
    """Stable high-level classification of simulation events."""

    OPERATOR_COMMAND = "OPERATOR_COMMAND"
    STATE_TRANSITION = "STATE_TRANSITION"
    START_SEQUENCE = "START_SEQUENCE"
    SENSOR_FAULT = "SENSOR_FAULT"
    SENSOR_HEALTH = "SENSOR_HEALTH"
    CONTROLLER = "CONTROLLER"
    PROTECTION = "PROTECTION"
    ACTUATOR = "ACTUATOR"
    RECORDING = "RECORDING"
    SYSTEM = "SYSTEM"


class EventSeverity(Enum):
    """Stable event severity levels."""

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class EventType(Enum):
    """Stable event identifiers used by logs and offline analysis."""

    RECORDING_STARTED = "RECORDING_STARTED"
    RECORDING_STOPPED = "RECORDING_STOPPED"
    USER_MARKER = "USER_MARKER"
    STARTUP_REQUESTED = "STARTUP_REQUESTED"
    SHUTDOWN_REQUESTED = "SHUTDOWN_REQUESTED"
    THROTTLE_CHANGED = "THROTTLE_CHANGED"
    MANUAL_FAULT_REQUESTED = "MANUAL_FAULT_REQUESTED"
    RESET_REQUESTED = "RESET_REQUESTED"
    RESET_ACCEPTED = "RESET_ACCEPTED"
    RESET_REJECTED = "RESET_REJECTED"
    ENGINE_STATE_CHANGED = "ENGINE_STATE_CHANGED"
    LIGHT_OFF_DETECTED = "LIGHT_OFF_DETECTED"
    SENSOR_FAULT_INJECTED = "SENSOR_FAULT_INJECTED"
    SENSOR_FAULT_CLEARED = "SENSOR_FAULT_CLEARED"
    SENSOR_HEALTH_CHANGED = "SENSOR_HEALTH_CHANGED"
    ACTIVE_LIMITER_CHANGED = "ACTIVE_LIMITER_CHANGED"
    LIMITER_ACTIVATED = "LIMITER_ACTIVATED"
    LIMITER_RELEASED = "LIMITER_RELEASED"
    SOFT_OVERSPEED_ACTIVATED = "SOFT_OVERSPEED_ACTIVATED"
    HARD_OVERSPEED_ACTIVATED = "HARD_OVERSPEED_ACTIVATED"
    CRITICAL_PROTECTION_REQUESTED = "CRITICAL_PROTECTION_REQUESTED"
    AUTOMATIC_FAULT_REQUESTED = "AUTOMATIC_FAULT_REQUESTED"
    SAFETY_FUEL_CUTOFF = "SAFETY_FUEL_CUTOFF"
    ARBITRATION_CONFLICT = "ARBITRATION_CONFLICT"
    LEGACY_MESSAGE = "LEGACY_MESSAGE"


EventValue: TypeAlias = str | int | float | bool | None


@dataclass(frozen=True)
class SimulationEvent:
    """One immutable structured event at authoritative simulation time."""

    simulation_time_s: float
    event_sequence: int
    category: EventCategory
    event_type: EventType
    severity: EventSeverity
    source: str
    message: str
    old_value: EventValue = None
    new_value: EventValue = None
    diagnostic_code: str | None = None


class EventSink(Protocol):
    """Synchronous consumer of structured simulation events."""

    def record_event(self, event: SimulationEvent) -> None:
        """Consume one immutable event."""
        ...


class SimulationEventLog:
    """Create sequenced events and retain a bounded immutable recent view."""

    def __init__(self, maximum_events: int = 2_000) -> None:
        if maximum_events <= 0:
            raise ValueError("maximum_events must be greater than zero")
        self._events: deque[SimulationEvent] = deque(maxlen=maximum_events)
        self._sinks: list[EventSink] = []
        self._next_sequence = 1

    @property
    def events(self) -> tuple[SimulationEvent, ...]:
        """Return an immutable bounded collection of recent events."""

        return tuple(self._events)

    def add_sink(self, sink: EventSink) -> None:
        if all(existing is not sink for existing in self._sinks):
            self._sinks.append(sink)

    def remove_sink(self, sink: EventSink) -> None:
        self._sinks = [existing for existing in self._sinks if existing is not sink]

    def emit(
        self,
        simulation_time_s: float,
        category: EventCategory,
        event_type: EventType,
        severity: EventSeverity,
        source: str,
        message: str,
        *,
        old_value: EventValue = None,
        new_value: EventValue = None,
        diagnostic_code: str | None = None,
    ) -> SimulationEvent:
        """Create, retain, and synchronously publish one sequenced event."""

        event = SimulationEvent(
            simulation_time_s=simulation_time_s,
            event_sequence=self._next_sequence,
            category=category,
            event_type=event_type,
            severity=severity,
            source=source,
            message=message,
            old_value=old_value,
            new_value=new_value,
            diagnostic_code=diagnostic_code,
        )
        self._next_sequence += 1
        self._events.append(event)
        for sink in tuple(self._sinks):
            sink.record_event(event)
        return event

    def record(self, simulation_time_s: float, message: str) -> None:
        """Record a compatibility message as a typed SYSTEM event."""

        self.emit(
            simulation_time_s,
            EventCategory.SYSTEM,
            EventType.LEGACY_MESSAGE,
            EventSeverity.INFO,
            "application",
            message,
        )

    def reset(self) -> None:
        self._events.clear()
        self._next_sequence = 1


EVENT_FIELDS = (
    "event_schema_version",
    "simulation_time_s",
    "event_sequence",
    "severity",
    "category",
    "event_type",
    "source",
    "diagnostic_code",
    "message",
    "old_value",
    "new_value",
)


def event_to_row(event: SimulationEvent) -> dict[str, str | int | float]:
    """Return one event row with stable field order and JSON-safe values."""

    return {
        "event_schema_version": EVENT_SCHEMA_VERSION,
        "simulation_time_s": event.simulation_time_s,
        "event_sequence": event.event_sequence,
        "severity": event.severity.value,
        "category": event.category.value,
        "event_type": event.event_type.value,
        "source": event.source,
        "diagnostic_code": event.diagnostic_code or "",
        "message": event.message,
        "old_value": json.dumps(event.old_value, ensure_ascii=False),
        "new_value": json.dumps(event.new_value, ensure_ascii=False),
    }


class SimulationEventMonitor:
    """Detect meaningful runtime transitions from consecutive snapshots."""

    def __init__(
        self,
        event_log: SimulationEventLog,
        initial_snapshot: SimulationSnapshot,
        limiter_dwell_s: float = 0.05,
    ) -> None:
        self.event_log = event_log
        self.limiter_dwell_s = limiter_dwell_s
        self._previous = initial_snapshot
        self._reported_limiter = initial_snapshot.active_protection_limiter
        self._pending_limiter = initial_snapshot.active_protection_limiter
        self._pending_limiter_since_s = initial_snapshot.simulation_time_s
        self._conflict_reported = initial_snapshot.protection_arbitration_conflict
        self._conflict_clear_since_s: float | None = None

    def observe(self, snapshot: SimulationSnapshot) -> None:
        """Emit events caused by one new canonical snapshot."""

        self._state_events(snapshot)
        self._sensor_events(snapshot)
        self._protection_events(snapshot)
        self._reset_events(snapshot)
        self._previous = snapshot

    def _state_events(self, snapshot: SimulationSnapshot) -> None:
        previous_state = self._previous.operating_state
        current_state = snapshot.operating_state
        if current_state is previous_state:
            return
        self.event_log.emit(
            snapshot.simulation_time_s,
            EventCategory.STATE_TRANSITION,
            EventType.ENGINE_STATE_CHANGED,
            EventSeverity.INFO,
            "engine_state_machine",
            f"Engine state {previous_state.value} -> {current_state.value}",
            old_value=previous_state.value,
            new_value=current_state.value,
        )
        if (
            previous_state is EngineOperatingState.IGNITION
            and current_state is EngineOperatingState.IDLE
        ):
            self.event_log.emit(
                snapshot.simulation_time_s,
                EventCategory.START_SEQUENCE,
                EventType.LIGHT_OFF_DETECTED,
                EventSeverity.INFO,
                "engine_state_machine",
                "Light-off and self-sustaining idle detected",
            )
        if (
            current_state is EngineOperatingState.FAULT
            and (
                snapshot.automatic_sensor_fault_request_active
                or snapshot.critical_protection_fault_request
            )
        ):
            protection_fault = snapshot.critical_protection_fault_request
            reason = (
                "CRITICAL_PROTECTION"
                if protection_fault
                else snapshot.sensor_fault_response_reason
            )
            self.event_log.emit(
                snapshot.simulation_time_s,
                EventCategory.STATE_TRANSITION,
                EventType.AUTOMATIC_FAULT_REQUESTED,
                EventSeverity.CRITICAL,
                "simulation_coordinator",
                f"Automatic FAULT request: {reason}",
                diagnostic_code=reason,
            )

    def _sensor_events(self, snapshot: SimulationSnapshot) -> None:
        channels = (
            (
                "Rotor-speed",
                self._previous.rotor_speed_health,
                snapshot.rotor_speed_health,
            ),
            (
                "EGT",
                self._previous.exhaust_temperature_health,
                snapshot.exhaust_temperature_health,
            ),
        )
        for name, previous_health, current_health in channels:
            if current_health is previous_health:
                continue
            severity = (
                EventSeverity.ERROR
                if current_health.value == "INVALID"
                else EventSeverity.WARNING
                if current_health.value == "SUSPECT"
                else EventSeverity.INFO
            )
            self.event_log.emit(
                snapshot.simulation_time_s,
                EventCategory.SENSOR_HEALTH,
                EventType.SENSOR_HEALTH_CHANGED,
                severity,
                "sensor_validator",
                f"{name} channel {previous_health.value} -> "
                f"{current_health.value}",
                old_value=previous_health.value,
                new_value=current_health.value,
                diagnostic_code=(
                    snapshot.rotor_speed_diagnostic_reason.value
                    if name == "Rotor-speed"
                    else snapshot.exhaust_temperature_diagnostic_reason.value
                ),
            )

    def _protection_events(self, snapshot: SimulationSnapshot) -> None:
        self._debounce_active_limiter(snapshot)
        if snapshot.soft_overspeed_active and not self._previous.soft_overspeed_active:
            self.event_log.emit(
                snapshot.simulation_time_s,
                EventCategory.PROTECTION,
                EventType.SOFT_OVERSPEED_ACTIVATED,
                EventSeverity.WARNING,
                "overspeed_limiter",
                "Soft overspeed intervention activated",
            )
        if snapshot.hard_overspeed_active and not self._previous.hard_overspeed_active:
            self.event_log.emit(
                snapshot.simulation_time_s,
                EventCategory.PROTECTION,
                EventType.HARD_OVERSPEED_ACTIVATED,
                EventSeverity.CRITICAL,
                "overspeed_limiter",
                "Hard overspeed fuel cutoff",
            )
        if (
            snapshot.critical_protection_fault_request
            and not self._previous.critical_protection_fault_request
        ):
            self.event_log.emit(
                snapshot.simulation_time_s,
                EventCategory.PROTECTION,
                EventType.CRITICAL_PROTECTION_REQUESTED,
                EventSeverity.CRITICAL,
                "protection_manager",
                "Critical protection FAULT request",
            )
        cutoff_active = (
            snapshot.allowed_fuel_command == 0.0
            and (
                snapshot.fuel_cutoff_due_to_sensor_invalidity
                or (
                    snapshot.protection_hard_cutoff_active
                    and snapshot.critical_protection_fault_request
                )
            )
        )
        previous_cutoff_active = (
            self._previous.allowed_fuel_command == 0.0
            and (
                self._previous.fuel_cutoff_due_to_sensor_invalidity
                or (
                    self._previous.protection_hard_cutoff_active
                    and self._previous.critical_protection_fault_request
                )
            )
        )
        if cutoff_active and not previous_cutoff_active:
            message = (
                "Fuel cut off due to sensor invalidity"
                if snapshot.fuel_cutoff_due_to_sensor_invalidity
                else "Fuel cut off by safety logic"
            )
            self.event_log.emit(
                snapshot.simulation_time_s,
                EventCategory.ACTUATOR,
                EventType.SAFETY_FUEL_CUTOFF,
                EventSeverity.CRITICAL,
                "protection_manager",
                message,
                old_value=self._previous.allowed_fuel_command,
                new_value=0.0,
            )
        self._arbitration_conflict_event(snapshot)

    def _debounce_active_limiter(self, snapshot: SimulationSnapshot) -> None:
        current = snapshot.active_protection_limiter
        if current is not self._pending_limiter:
            self._pending_limiter = current
            self._pending_limiter_since_s = snapshot.simulation_time_s
            return
        if (
            current is self._reported_limiter
            or snapshot.simulation_time_s - self._pending_limiter_since_s
            < self.limiter_dwell_s
        ):
            return

        previous = self._reported_limiter
        self.event_log.emit(
            snapshot.simulation_time_s,
            EventCategory.PROTECTION,
            EventType.ACTIVE_LIMITER_CHANGED,
            EventSeverity.WARNING,
            "protection_manager",
            f"Active fuel limiter {previous.value} -> {current.value}",
            old_value=previous.value,
            new_value=current.value,
        )
        labels = {
            ProtectionLimiter.ACCELERATION: "Acceleration limiter",
            ProtectionLimiter.DECELERATION: "Deceleration limiter",
        }
        if previous in labels:
            self.event_log.emit(
                snapshot.simulation_time_s,
                EventCategory.PROTECTION,
                EventType.LIMITER_RELEASED,
                EventSeverity.INFO,
                "protection_manager",
                f"{labels[previous]} released",
                old_value=previous.value,
                new_value=current.value,
            )
        if current in labels:
            self.event_log.emit(
                snapshot.simulation_time_s,
                EventCategory.PROTECTION,
                EventType.LIMITER_ACTIVATED,
                EventSeverity.WARNING,
                "protection_manager",
                f"{labels[current]} activated",
                old_value=previous.value,
                new_value=current.value,
            )
        self._reported_limiter = current

    def _arbitration_conflict_event(self, snapshot: SimulationSnapshot) -> None:
        if snapshot.protection_arbitration_conflict:
            self._conflict_clear_since_s = None
            if not self._conflict_reported:
                self.event_log.emit(
                    snapshot.simulation_time_s,
                    EventCategory.PROTECTION,
                    EventType.ARBITRATION_CONFLICT,
                    EventSeverity.WARNING,
                    "protection_manager",
                    "Fuel arbitration conflict; safety upper limit selected",
                )
                self._conflict_reported = True
            return
        if not self._conflict_reported:
            return
        if self._conflict_clear_since_s is None:
            self._conflict_clear_since_s = snapshot.simulation_time_s
        elif snapshot.simulation_time_s - self._conflict_clear_since_s >= 1.0:
            self._conflict_reported = False
            self._conflict_clear_since_s = None

    def _reset_events(self, snapshot: SimulationSnapshot) -> None:
        if not snapshot.reset_requested:
            return
        accepted = (
            self._previous.operating_state is EngineOperatingState.FAULT
            and snapshot.operating_state is EngineOperatingState.OFF
        )
        self.event_log.emit(
            snapshot.simulation_time_s,
            EventCategory.OPERATOR_COMMAND,
            EventType.RESET_ACCEPTED if accepted else EventType.RESET_REJECTED,
            EventSeverity.INFO if accepted else EventSeverity.WARNING,
            "engine_state_machine",
            "Reset accepted" if accepted else "Reset rejected",
            old_value=self._previous.operating_state.value,
            new_value=snapshot.operating_state.value,
        )
