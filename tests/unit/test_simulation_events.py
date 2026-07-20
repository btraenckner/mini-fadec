"""Unit tests for typed transition events and bounded event retention."""

from dataclasses import replace
import json

from simulation.application.engine_simulation import EngineSimulationCoordinator
from simulation.application.simulation_service import SimulationService
from simulation.operation.engine_state import EngineOperatingState
from simulation.protection.types import ProtectionLimiter
from simulation.sensors.fault_injection import BiasSensorFault, SensorChannel
from simulation.telemetry.events import (
    EVENT_FIELDS,
    EventCategory,
    EventSeverity,
    EventType,
    SimulationEventLog,
    SimulationEventMonitor,
    event_to_row,
)
from simulation.validation.sensor_validation import ChannelHealth


def test_state_transition_emits_once_and_unchanged_state_does_not_repeat() -> None:
    initial = EngineSimulationCoordinator().snapshot
    event_log = SimulationEventLog()
    monitor = SimulationEventMonitor(event_log, initial)
    cranking = replace(
        initial,
        simulation_time_s=0.01,
        operating_state=EngineOperatingState.CRANKING,
    )

    monitor.observe(cranking)
    monitor.observe(replace(cranking, simulation_time_s=0.02))

    state_events = [
        event
        for event in event_log.events
        if event.event_type is EventType.ENGINE_STATE_CHANGED
    ]
    assert len(state_events) == 1
    assert state_events[0].old_value == "OFF"
    assert state_events[0].new_value == "CRANKING"


def test_limiter_activation_persistence_and_release_are_debounced() -> None:
    initial = EngineSimulationCoordinator().snapshot
    event_log = SimulationEventLog()
    monitor = SimulationEventMonitor(event_log, initial, limiter_dwell_s=0.05)
    active = replace(
        initial,
        simulation_time_s=0.01,
        active_protection_limiter=ProtectionLimiter.ACCELERATION,
    )
    monitor.observe(active)
    monitor.observe(replace(active, simulation_time_s=0.07))
    monitor.observe(replace(active, simulation_time_s=0.20))
    released = replace(
        active,
        simulation_time_s=0.21,
        active_protection_limiter=ProtectionLimiter.NONE,
    )
    monitor.observe(released)
    monitor.observe(replace(released, simulation_time_s=0.27))

    event_types = [event.event_type for event in event_log.events]
    assert event_types.count(EventType.LIMITER_ACTIVATED) == 1
    assert event_types.count(EventType.LIMITER_RELEASED) == 1
    assert event_types.count(EventType.ACTIVE_LIMITER_CHANGED) == 2


def test_sensor_health_and_hard_overspeed_transitions_are_typed() -> None:
    initial = EngineSimulationCoordinator().snapshot
    event_log = SimulationEventLog()
    monitor = SimulationEventMonitor(event_log, initial)
    invalid = replace(
        initial,
        simulation_time_s=0.01,
        rotor_speed_health=ChannelHealth.INVALID,
        hard_overspeed_active=True,
        critical_protection_fault_request=True,
    )

    monitor.observe(invalid)

    event_types = {event.event_type for event in event_log.events}
    assert EventType.SENSOR_HEALTH_CHANGED in event_types
    assert EventType.HARD_OVERSPEED_ACTIVATED in event_types
    assert EventType.CRITICAL_PROTECTION_REQUESTED in event_types
    hard_event = next(
        event
        for event in event_log.events
        if event.event_type is EventType.HARD_OVERSPEED_ACTIVATED
    )
    assert hard_event.severity is EventSeverity.CRITICAL


def test_fault_events_and_user_marker_are_recorded_by_public_services() -> None:
    coordinator = EngineSimulationCoordinator()
    service = SimulationService(coordinator=coordinator)

    service.inject_sensor_fault(
        SensorChannel.ROTOR_SPEED,
        BiasSensorFault(offset=100.0),
    )
    service.clear_sensor_fault(SensorChannel.ROTOR_SPEED)
    marker = service.add_marker("before throttle step")

    event_types = [event.event_type for event in service.get_recent_events()]
    assert EventType.SENSOR_FAULT_INJECTED in event_types
    assert EventType.SENSOR_FAULT_CLEARED in event_types
    assert marker.event_type is EventType.USER_MARKER
    assert marker.message == "before throttle step"


def test_event_sequences_serialization_and_bounded_storage_are_stable() -> None:
    event_log = SimulationEventLog(maximum_events=2)
    for index in range(3):
        event_log.emit(
            float(index),
            EventCategory.SYSTEM,
            EventType.LEGACY_MESSAGE,
            EventSeverity.INFO,
            "test",
            f"event {index}",
            old_value=None,
            new_value=index,
        )

    events = event_log.events
    row = event_to_row(events[-1])

    assert [event.event_sequence for event in events] == [2, 3]
    assert tuple(row) == EVENT_FIELDS
    assert row["old_value"] == "null"
    assert json.loads(str(row["new_value"])) == 2
