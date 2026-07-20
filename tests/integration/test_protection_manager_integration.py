"""End-to-end tests for centralized fuel protection and arbitration."""

import math

import pytest

from simulation.application.engine_simulation import (
    EngineSimulationCoordinator,
    EngineSimulationSnapshot,
)
from simulation.controllers.speed_controller import PIEngineSpeedController
from simulation.core.types import ActuatorCommand, ControlRequest, SensorData
from simulation.operation.engine_state import EngineOperatingState
from simulation.operation.state_machine import EngineOperationRequest
from simulation.protection.types import ProtectionLimiter
from simulation.sensors.fault_injection import DriftSensorFault, SensorChannel
from simulation.sensors.sensor_model import (
    ConfigurableSensorModel,
    ExhaustTemperatureSensorConfiguration,
    RotorSpeedSensorConfiguration,
    SensorModelConfiguration,
)
from simulation.validation.sensor_validation import ChannelHealth


class FixedRunningFuelController(PIEngineSpeedController):
    """Provide deterministic demand while retaining the normal scheduler."""

    def update(
        self,
        control_request: ControlRequest,
        sensor_data: SensorData,
        time_step_s: float,
    ) -> ActuatorCommand:
        if time_step_s <= 0.0:
            raise ValueError("time_step_s must be greater than zero")
        fuel_command = 0.65 if control_request.throttle_command > 0.02 else 0.0
        return ActuatorCommand(fuel_command=fuel_command)


def _zero_noise_sensor_model() -> ConfigurableSensorModel:
    return ConfigurableSensorModel(
        configuration=SensorModelConfiguration(
            random_seed=0,
            rotor_speed=RotorSpeedSensorConfiguration(
                noise_standard_deviation_rpm=0.0,
                quantization_step_rpm=0.0,
            ),
            exhaust_temperature=ExhaustTemperatureSensorConfiguration(
                noise_standard_deviation_c=0.0,
                quantization_step_c=0.0,
            ),
        )
    )


def _advance_to_running(
    coordinator: EngineSimulationCoordinator,
    throttle_command: float,
) -> None:
    startup_requested = True
    for _ in range(1_000):
        active_throttle = (
            throttle_command
            if coordinator.snapshot.operating_state
            in {EngineOperatingState.IDLE, EngineOperatingState.RUNNING}
            else 0.0
        )
        snapshot = coordinator.step(
            EngineOperationRequest(
                throttle_command=active_throttle,
                startup_requested=startup_requested,
            ),
            time_step_s=0.01,
        )
        startup_requested = False
        if snapshot.operating_state is EngineOperatingState.RUNNING:
            return

    raise AssertionError("engine did not reach RUNNING")


def _run_large_acceleration_scenario() -> tuple[
    EngineSimulationCoordinator,
    list[EngineSimulationSnapshot],
]:
    coordinator = EngineSimulationCoordinator(
        sensor_model=_zero_noise_sensor_model()
    )
    startup_requested = True
    for _ in range(1_000):
        snapshot = coordinator.step(
            EngineOperationRequest(startup_requested=startup_requested),
            time_step_s=0.01,
        )
        startup_requested = False
        if snapshot.operating_state is EngineOperatingState.IDLE:
            break
    else:
        raise AssertionError("engine did not reach IDLE")

    snapshots = [
        coordinator.step(
            EngineOperationRequest(throttle_command=1.0),
            time_step_s=0.01,
        )
        for _ in range(800)
    ]
    return coordinator, snapshots


def test_small_throttle_change_does_not_activate_acceleration_protection() -> None:
    coordinator = EngineSimulationCoordinator(
        sensor_model=_zero_noise_sensor_model()
    )
    _advance_to_running(coordinator, throttle_command=0.3)
    for _ in range(500):
        coordinator.step(
            EngineOperationRequest(throttle_command=0.3),
            time_step_s=0.01,
        )

    snapshots = [
        coordinator.step(
            EngineOperationRequest(throttle_command=0.32),
            time_step_s=0.01,
        )
        for _ in range(100)
    ]

    assert all(
        ProtectionLimiter.ACCELERATION
        not in snapshot.constraining_protection_limiters
        for snapshot in snapshots
    )


def test_large_throttle_step_limits_acceleration_and_releases_stably() -> None:
    coordinator, snapshots = _run_large_acceleration_scenario()
    hard_limit = (
        coordinator.protection_manager.acceleration_limiter.parameters
        .hard_acceleration_limit_rpm_per_s
    )
    acceleration_active = [
        ProtectionLimiter.ACCELERATION
        in snapshot.constraining_protection_limiters
        for snapshot in snapshots
    ]
    settled_accelerations = [
        abs(snapshot.rotor_acceleration_rpm_per_s or 0.0)
        for snapshot in snapshots[10:]
    ]
    protection_edges = sum(
        current != previous
        for previous, current in zip(
            acceleration_active,
            acceleration_active[1:],
        )
    )

    assert any(acceleration_active)
    assert any(
        snapshot.allowed_fuel_command < snapshot.requested_fuel_command
        for snapshot in snapshots
        if ProtectionLimiter.ACCELERATION
        in snapshot.constraining_protection_limiters
    )
    assert max(settled_accelerations) <= 1.05 * hard_limit
    assert not any(acceleration_active[-200:])
    assert protection_edges <= 2
    assert all(
        math.isfinite(snapshot.allowed_fuel_command)
        and 0.0 <= snapshot.allowed_fuel_command <= 1.0
        for snapshot in snapshots
    )
    event_messages = [event.message for event in coordinator.event_log.events]
    assert event_messages.count("Acceleration limiter activated") == 1
    assert event_messages.count("Acceleration limiter released") == 1


def test_large_acceleration_scenario_is_deterministic() -> None:
    _, first = _run_large_acceleration_scenario()
    _, second = _run_large_acceleration_scenario()

    first_trace = [
        (
            snapshot.rotor_speed_rpm,
            snapshot.allowed_fuel_command,
            snapshot.active_protection_limiter,
        )
        for snapshot in first
    ]
    second_trace = [
        (
            snapshot.rotor_speed_rpm,
            snapshot.allowed_fuel_command,
            snapshot.active_protection_limiter,
        )
        for snapshot in second
    ]

    assert first_trace == second_trace


def test_rapid_demand_reduction_is_limited_but_shutdown_is_immediate() -> None:
    coordinator = EngineSimulationCoordinator(
        sensor_model=_zero_noise_sensor_model()
    )
    _advance_to_running(coordinator, throttle_command=0.7)
    for _ in range(800):
        coordinator.step(
            EngineOperationRequest(throttle_command=0.7),
            time_step_s=0.01,
        )

    deceleration_snapshot = coordinator.step(
        EngineOperationRequest(throttle_command=0.3),
        time_step_s=0.01,
    )
    assert ProtectionLimiter.DECELERATION in (
        deceleration_snapshot.constraining_protection_limiters
    )
    assert (
        deceleration_snapshot.allowed_fuel_command
        > deceleration_snapshot.requested_fuel_command
    )

    shutdown_snapshot = coordinator.step(
        EngineOperationRequest(shutdown_requested=True),
        time_step_s=0.01,
    )
    assert shutdown_snapshot.operating_state is EngineOperatingState.SHUTDOWN
    assert shutdown_snapshot.allowed_fuel_command == pytest.approx(0.0)
    assert shutdown_snapshot.protection_hard_cutoff_active


def test_validated_soft_and_hard_overspeed_follow_complete_fault_path() -> None:
    coordinator = EngineSimulationCoordinator(
        speed_controller=FixedRunningFuelController(),
        sensor_model=_zero_noise_sensor_model(),
    )
    _advance_to_running(coordinator, throttle_command=0.6)
    for _ in range(600):
        coordinator.step(
            EngineOperationRequest(throttle_command=0.6),
            time_step_s=0.01,
        )
    coordinator.inject_sensor_fault(
        SensorChannel.ROTOR_SPEED,
        DriftSensorFault(rate_per_second=8_000.0),
    )

    soft_snapshot = None
    hard_snapshot = None
    for _ in range(1_500):
        snapshot = coordinator.step(
            EngineOperationRequest(throttle_command=0.6),
            time_step_s=0.01,
        )
        if (
            soft_snapshot is None
            and snapshot.soft_overspeed_active
            and snapshot.overspeed_fuel_limit
            < snapshot.requested_fuel_command
        ):
            soft_snapshot = snapshot
        if snapshot.operating_state is EngineOperatingState.FAULT:
            hard_snapshot = snapshot
            break

    assert soft_snapshot is not None
    assert soft_snapshot.rotor_speed_health is ChannelHealth.VALID
    assert soft_snapshot.active_protection_limiter is ProtectionLimiter.OVERSPEED
    assert soft_snapshot.allowed_fuel_command < soft_snapshot.requested_fuel_command
    assert soft_snapshot.critical_protection_fault_request is False

    assert hard_snapshot is not None
    assert hard_snapshot.rotor_speed_health is ChannelHealth.VALID
    assert hard_snapshot.hard_overspeed_active
    assert hard_snapshot.critical_protection_fault_request
    assert hard_snapshot.allowed_fuel_command == pytest.approx(0.0)
    assert hard_snapshot.operating_state is EngineOperatingState.FAULT
    assert ProtectionLimiter.DECELERATION not in (
        hard_snapshot.constraining_protection_limiters
    )
    event_messages = [event.message for event in coordinator.event_log.events]
    assert event_messages.count("Soft overspeed intervention activated") == 1
    assert event_messages.count("Hard overspeed fuel cutoff") == 1
    assert event_messages.count("Critical protection FAULT request") == 1


def test_normal_sensor_noise_does_not_flood_protection_events() -> None:
    coordinator = EngineSimulationCoordinator()
    _advance_to_running(coordinator, throttle_command=0.3)
    for _ in range(500):
        coordinator.step(
            EngineOperationRequest(throttle_command=0.3),
            time_step_s=0.01,
        )
    coordinator.event_log.reset()

    for _ in range(500):
        coordinator.step(
            EngineOperationRequest(throttle_command=0.3),
            time_step_s=0.01,
        )

    protection_events = [
        event
        for event in coordinator.event_log.events
        if "limiter" in event.message.lower()
        or "arbitration conflict" in event.message.lower()
    ]
    assert len(protection_events) <= 2
