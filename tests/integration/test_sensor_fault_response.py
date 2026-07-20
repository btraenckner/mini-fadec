"""Integration tests for validated sensor faults and FADEC responses."""

import math

import pytest

from simulation.application.engine_simulation import EngineSimulationCoordinator
from simulation.controllers.speed_controller import PIEngineSpeedController
from simulation.core.types import ActuatorCommand, ControlRequest, SensorData
from simulation.operation.engine_state import EngineOperatingState
from simulation.operation.state_machine import EngineOperationRequest
from simulation.protection.exhaust_temperature_limiter import (
    ExhaustTemperatureLimiter,
)
from simulation.sensors.fault_injection import (
    BiasSensorFault,
    DropoutSensorFault,
    ExcessiveNoiseSensorFault,
    SensorChannel,
)
from simulation.validation.sensor_validation import ChannelHealth


class RecordingSpeedController(PIEngineSpeedController):
    """Record validated controller inputs for separation assertions."""

    def __init__(self) -> None:
        super().__init__()
        self.received_sensor_data: list[SensorData] = []

    def update(
        self,
        control_request: ControlRequest,
        sensor_data: SensorData,
        time_step_s: float,
    ) -> ActuatorCommand:
        self.received_sensor_data.append(sensor_data)
        return super().update(control_request, sensor_data, time_step_s)


class RecordingExhaustTemperatureLimiter(ExhaustTemperatureLimiter):
    """Record validated protection inputs for separation assertions."""

    def __init__(self) -> None:
        super().__init__()
        self.received_sensor_data: list[SensorData] = []

    def apply(
        self,
        requested_command: ActuatorCommand,
        sensor_data: SensorData,
        time_step_s: float,
    ) -> ActuatorCommand:
        self.received_sensor_data.append(sensor_data)
        return super().apply(requested_command, sensor_data, time_step_s)


def _advance_to_running(
    coordinator: EngineSimulationCoordinator,
    throttle_command: float = 0.5,
) -> None:
    """Start the coordinated engine and establish RUNNING operation."""

    startup_requested = True
    for _ in range(1_000):
        requested_throttle = (
            throttle_command
            if coordinator.snapshot.operating_state
            in {EngineOperatingState.IDLE, EngineOperatingState.RUNNING}
            else 0.0
        )
        snapshot = coordinator.step(
            EngineOperationRequest(
                throttle_command=requested_throttle,
                startup_requested=startup_requested,
            ),
            time_step_s=0.01,
        )
        startup_requested = False
        if snapshot.operating_state is EngineOperatingState.RUNNING:
            return

    raise AssertionError("engine did not reach RUNNING")


def test_small_injected_bias_does_not_false_trigger_fault() -> None:
    coordinator = EngineSimulationCoordinator()
    _advance_to_running(coordinator)
    coordinator.inject_sensor_fault(
        SensorChannel.ROTOR_SPEED,
        BiasSensorFault(offset=100.0),
    )

    for _ in range(100):
        snapshot = coordinator.step(
            EngineOperationRequest(throttle_command=0.5),
            time_step_s=0.01,
        )

    assert snapshot.operating_state is EngineOperatingState.RUNNING
    assert snapshot.rotor_speed_health is ChannelHealth.VALID
    assert snapshot.automatic_sensor_fault_request_active is False


def test_rotor_speed_dropout_during_running_requests_fault_and_cuts_fuel() -> None:
    controller = RecordingSpeedController()
    coordinator = EngineSimulationCoordinator(speed_controller=controller)
    _advance_to_running(coordinator)
    controller.received_sensor_data.clear()
    coordinator.inject_sensor_fault(
        SensorChannel.ROTOR_SPEED,
        DropoutSensorFault(),
    )

    snapshot = coordinator.step(
        EngineOperationRequest(throttle_command=0.5),
        time_step_s=0.01,
    )

    assert snapshot.measured_rotor_speed_rpm is None
    assert snapshot.rotor_speed_health is ChannelHealth.INVALID
    assert snapshot.automatic_sensor_fault_request_active
    assert snapshot.operating_state is EngineOperatingState.FAULT
    assert snapshot.allowed_fuel_command == pytest.approx(0.0)
    assert snapshot.fuel_enabled is False
    assert snapshot.fuel_cutoff_due_to_sensor_invalidity
    assert controller.received_sensor_data == []


def test_egt_dropout_during_running_requests_fault_and_cuts_fuel() -> None:
    limiter = RecordingExhaustTemperatureLimiter()
    coordinator = EngineSimulationCoordinator(egt_limiter=limiter)
    _advance_to_running(coordinator)
    limiter.received_sensor_data.clear()
    coordinator.inject_sensor_fault(
        SensorChannel.EXHAUST_TEMPERATURE,
        DropoutSensorFault(),
    )

    snapshot = coordinator.step(
        EngineOperationRequest(throttle_command=0.5),
        time_step_s=0.01,
    )

    assert snapshot.measured_exhaust_temperature_c is None
    assert snapshot.exhaust_temperature_health is ChannelHealth.INVALID
    assert snapshot.automatic_sensor_fault_request_active
    assert snapshot.operating_state is EngineOperatingState.FAULT
    assert snapshot.allowed_fuel_command == pytest.approx(0.0)
    assert limiter.received_sensor_data == []


def test_egt_dropout_during_off_keeps_actuator_commands_safe() -> None:
    coordinator = EngineSimulationCoordinator()
    coordinator.inject_sensor_fault(
        SensorChannel.EXHAUST_TEMPERATURE,
        DropoutSensorFault(),
    )

    snapshot = coordinator.step(EngineOperationRequest(), time_step_s=0.01)

    assert snapshot.operating_state is EngineOperatingState.OFF
    assert snapshot.exhaust_temperature_health is ChannelHealth.INVALID
    assert snapshot.automatic_sensor_fault_request_active is False
    assert snapshot.allowed_fuel_command == pytest.approx(0.0)
    assert snapshot.starter_commanded is False
    assert snapshot.ignition_commanded is False
    assert snapshot.fuel_enabled is False


def test_fault_clear_requires_validation_recovery_before_safe_reset() -> None:
    coordinator = EngineSimulationCoordinator()
    _advance_to_running(coordinator)
    coordinator.inject_sensor_fault(
        SensorChannel.ROTOR_SPEED,
        DropoutSensorFault(),
    )
    coordinator.step(
        EngineOperationRequest(throttle_command=0.5),
        time_step_s=0.01,
    )

    for _ in range(1_000):
        snapshot = coordinator.step(EngineOperationRequest(), time_step_s=0.01)
        if snapshot.rotor_speed_rpm <= 500.0:
            break
    coordinator.clear_sensor_fault(SensorChannel.ROTOR_SPEED)

    recovering_snapshot = coordinator.step(
        EngineOperationRequest(reset_requested=True),
        time_step_s=0.01,
    )
    assert recovering_snapshot.rotor_speed_health is ChannelHealth.SUSPECT
    assert recovering_snapshot.operating_state is EngineOperatingState.FAULT

    for _ in range(20):
        recovered_snapshot = coordinator.step(
            EngineOperationRequest(),
            time_step_s=0.01,
        )
    assert recovered_snapshot.rotor_speed_health is ChannelHealth.VALID

    reset_snapshot = coordinator.step(
        EngineOperationRequest(reset_requested=True),
        time_step_s=0.01,
    )
    assert reset_snapshot.operating_state is EngineOperatingState.OFF


def test_controller_and_protection_receive_faulted_validated_values_not_truth() -> None:
    controller = RecordingSpeedController()
    limiter = RecordingExhaustTemperatureLimiter()
    coordinator = EngineSimulationCoordinator(
        speed_controller=controller,
        egt_limiter=limiter,
    )
    _advance_to_running(coordinator)
    for _ in range(100):
        coordinator.step(
            EngineOperationRequest(throttle_command=0.5),
            time_step_s=0.01,
        )
    controller.received_sensor_data.clear()
    limiter.received_sensor_data.clear()
    true_speed_before_step_rpm = coordinator.engine_model.state.rotor_speed_rpm
    coordinator.inject_sensor_fault(
        SensorChannel.ROTOR_SPEED,
        BiasSensorFault(offset=500.0),
    )

    snapshot = coordinator.step(
        EngineOperationRequest(throttle_command=0.5),
        time_step_s=0.01,
    )

    controller_data = controller.received_sensor_data[-1]
    limiter_data = limiter.received_sensor_data[-1]
    assert controller_data == limiter_data
    assert controller_data.rotor_speed_rpm == pytest.approx(
        true_speed_before_step_rpm + 500.0,
        abs=100.0,
    )
    assert controller_data.rotor_speed_rpm == pytest.approx(
        snapshot.validated_rotor_speed_rpm
    )
    assert controller_data.rotor_speed_rpm != pytest.approx(
        true_speed_before_step_rpm
    )


def test_fixed_seed_fault_scenario_is_repeatable_and_outputs_stay_bounded() -> None:
    first_coordinator = EngineSimulationCoordinator()
    second_coordinator = EngineSimulationCoordinator()
    for coordinator in (first_coordinator, second_coordinator):
        _advance_to_running(coordinator)
        coordinator.inject_sensor_fault(
            SensorChannel.EXHAUST_TEMPERATURE,
            ExcessiveNoiseSensorFault(standard_deviation=20.0),
        )

    for _ in range(100):
        first_snapshot = first_coordinator.step(
            EngineOperationRequest(throttle_command=0.5),
            time_step_s=0.01,
        )
        second_snapshot = second_coordinator.step(
            EngineOperationRequest(throttle_command=0.5),
            time_step_s=0.01,
        )

        assert first_snapshot == second_snapshot
        assert math.isfinite(first_snapshot.rotor_speed_rpm)
        assert math.isfinite(first_snapshot.exhaust_temperature_c)
        assert 0.0 <= first_snapshot.requested_fuel_command <= 1.0
        assert 0.0 <= first_snapshot.allowed_fuel_command <= 1.0
