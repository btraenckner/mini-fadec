"""Integration tests for measured feedback through the complete FADEC path."""

import pytest

from simulation.application.engine_simulation import EngineSimulationCoordinator
from simulation.controllers.speed_controller import PIEngineSpeedController
from simulation.core.types import (
    ActuatorCommand,
    AmbientConditions,
    ControlRequest,
    SensorData,
)
from simulation.models.engine_model import FirstOrderEngineModel
from simulation.operation.engine_state import EngineOperatingState
from simulation.operation.state_machine import EngineOperationRequest
from simulation.protection.exhaust_temperature_limiter import (
    ExhaustTemperatureLimiter,
)
from simulation.sensors.sensor_model import (
    ConfigurableSensorModel,
    ExhaustTemperatureSensorConfiguration,
    RotorSpeedSensorConfiguration,
    SensorModelConfiguration,
)


class RecordingSpeedController(PIEngineSpeedController):
    """PI controller that records the measurements it receives."""

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
    """EGT limiter that records the measurements it receives."""

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


def _advance_to_idle(
    coordinator: EngineSimulationCoordinator,
    time_step_s: float = 0.01,
) -> None:
    """Start an engine and advance until measured conditions establish idle."""

    startup_requested = True
    for _ in range(int(10.0 / time_step_s)):
        snapshot = coordinator.step(
            request=EngineOperationRequest(
                startup_requested=startup_requested,
            ),
            time_step_s=time_step_s,
        )
        startup_requested = False
        if snapshot.operating_state is EngineOperatingState.IDLE:
            return

    raise AssertionError("engine did not reach idle")


def test_controller_and_egt_protection_receive_measured_signals() -> None:
    speed_controller = RecordingSpeedController()
    egt_limiter = RecordingExhaustTemperatureLimiter()
    sensor_model = ConfigurableSensorModel(
        configuration=SensorModelConfiguration(
            rotor_speed=RotorSpeedSensorConfiguration(
                bias_rpm=1_000.0,
                noise_standard_deviation_rpm=0.0,
                quantization_step_rpm=0.0,
            ),
            exhaust_temperature=ExhaustTemperatureSensorConfiguration(
                bias_c=10.0,
                noise_standard_deviation_c=0.0,
                quantization_step_c=0.0,
                sample_period_s=0.01,
            ),
        )
    )
    coordinator = EngineSimulationCoordinator(
        speed_controller=speed_controller,
        egt_limiter=egt_limiter,
        sensor_model=sensor_model,
    )
    _advance_to_idle(coordinator)
    speed_controller.received_sensor_data.clear()
    egt_limiter.received_sensor_data.clear()
    true_speed_before_step_rpm = coordinator.engine_model.state.rotor_speed_rpm
    true_egt_before_step_c = (
        coordinator.engine_model.state.exhaust_temperature_c
    )

    snapshot = coordinator.step(
        request=EngineOperationRequest(throttle_command=0.5),
        time_step_s=0.01,
    )

    controller_measurement = speed_controller.received_sensor_data[-1]
    limiter_measurement = egt_limiter.received_sensor_data[-1]
    assert controller_measurement == limiter_measurement
    assert controller_measurement.rotor_speed_rpm == pytest.approx(
        true_speed_before_step_rpm + 1_000.0
    )
    assert controller_measurement.exhaust_temperature_c == pytest.approx(
        true_egt_before_step_c + 10.0
    )
    assert snapshot.measured_rotor_speed_rpm == pytest.approx(
        controller_measurement.rotor_speed_rpm
    )
    assert snapshot.measured_exhaust_temperature_c == pytest.approx(
        limiter_measurement.exhaust_temperature_c
    )


def test_small_sensor_noise_does_not_prevent_stable_idle_operation() -> None:
    coordinator = EngineSimulationCoordinator()
    _advance_to_idle(coordinator)
    fuel_commands: list[float] = []

    for _ in range(int(5.0 / 0.01)):
        snapshot = coordinator.step(
            request=EngineOperationRequest(throttle_command=0.0),
            time_step_s=0.01,
        )
        fuel_commands.append(snapshot.allowed_fuel_command)

    assert snapshot.operating_state is EngineOperatingState.IDLE
    assert snapshot.rotor_speed_rpm == pytest.approx(39_000.0, rel=0.02)
    assert all(0.0 <= command <= 1.0 for command in fuel_commands)


def test_rotor_speed_bias_produces_expected_steady_state_correction() -> None:
    engine_model = FirstOrderEngineModel.running_at_idle()
    controller = PIEngineSpeedController()
    sensor_model = ConfigurableSensorModel(
        configuration=SensorModelConfiguration(
            rotor_speed=RotorSpeedSensorConfiguration(
                bias_rpm=1_000.0,
                noise_standard_deviation_rpm=0.0,
                quantization_step_rpm=0.0,
            ),
            exhaust_temperature=ExhaustTemperatureSensorConfiguration(
                noise_standard_deviation_c=0.0,
                quantization_step_c=0.0,
            ),
        )
    )
    control_request = ControlRequest(throttle_command=0.5)
    time_step_s = 0.01

    for _ in range(int(15.0 / time_step_s)):
        sensor_data = sensor_model.measure(engine_model.state, time_step_s)
        actuator_command = controller.update(
            control_request,
            sensor_data,
            time_step_s,
        )
        engine_model.step(
            actuator_command,
            AmbientConditions(),
            time_step_s,
        )

    speed_setpoint_rpm = controller.scheduler.get_speed_setpoint_rpm(0.5)
    final_measurement = sensor_model.measure(engine_model.state, time_step_s)
    assert final_measurement.rotor_speed_rpm == pytest.approx(
        speed_setpoint_rpm,
        rel=0.01,
    )
    assert engine_model.state.rotor_speed_rpm == pytest.approx(
        speed_setpoint_rpm - 1_000.0,
        rel=0.01,
    )


def test_fixed_sensor_seed_makes_coordinated_simulation_deterministic() -> None:
    first_coordinator = EngineSimulationCoordinator()
    second_coordinator = EngineSimulationCoordinator()
    startup_requested = True

    for step_index in range(1_000):
        throttle_command = 0.6 if step_index >= 600 else 0.0
        request = EngineOperationRequest(
            throttle_command=throttle_command,
            startup_requested=startup_requested,
        )
        startup_requested = False

        first_snapshot = first_coordinator.step(request, time_step_s=0.01)
        second_snapshot = second_coordinator.step(request, time_step_s=0.01)

        assert first_snapshot == second_snapshot
        assert 0.0 <= first_snapshot.requested_fuel_command <= 1.0
        assert 0.0 <= first_snapshot.allowed_fuel_command <= 1.0
