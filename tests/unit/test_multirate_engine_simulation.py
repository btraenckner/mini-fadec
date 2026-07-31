"""Application-level tests for explicit multi-rate timing contracts."""

from collections.abc import Mapping

import pytest

from simulation.application.engine_simulation import (
    EngineSimulationCoordinator,
    EngineSimulationSnapshot,
)
from simulation.controllers.speed_controller import PIEngineSpeedController
from simulation.core.types import (
    ActuatorCommand,
    AmbientConditions,
    ControlRequest,
    EngineOutputs,
    EngineState,
    RawSensorData,
    SensorData,
)
from simulation.models.engine_model import FirstOrderEngineModel
from simulation.operation.engine_state import EngineOperatingState
from simulation.operation.state_machine import EngineOperationRequest
from simulation.protection.protection_manager import ProtectionManager
from simulation.protection.types import ProtectionContext, ProtectionResult
from simulation.scheduling.config import SchedulerConfig
from simulation.scheduling.presets import (
    ACTUATOR_TASK,
    COMMAND_TASK,
    CONTROLLER_TASK,
    DASHBOARD_TASK,
    EVENT_MONITOR_TASK,
    PLANT_TASK,
    PROTECTION_TASK,
    SENSOR_TASK,
    SNAPSHOT_TASK,
    STATE_MACHINE_TASK,
    TASK_PRIORITIES,
    TELEMETRY_TASK,
    VALIDATION_TASK,
)
from simulation.scheduling.task import PeriodicTaskDefinition
from simulation.telemetry.interfaces import SnapshotSink
from simulation.validation.sensor_validation import (
    SensorSignalValidator,
    SensorValidationContext,
    SensorValidationResult,
)


_TASK_NAMES = (
    COMMAND_TASK,
    STATE_MACHINE_TASK,
    SENSOR_TASK,
    VALIDATION_TASK,
    CONTROLLER_TASK,
    PROTECTION_TASK,
    ACTUATOR_TASK,
    PLANT_TASK,
    SNAPSHOT_TASK,
    EVENT_MONITOR_TASK,
    TELEMETRY_TASK,
    DASHBOARD_TASK,
)


def _config(
    period_ticks: Mapping[str, int] | None = None,
) -> SchedulerConfig:
    periods = {
        COMMAND_TASK: 1,
        STATE_MACHINE_TASK: 4,
        SENSOR_TASK: 3,
        VALIDATION_TASK: 3,
        CONTROLLER_TASK: 4,
        PROTECTION_TASK: 2,
        ACTUATOR_TASK: 2,
        PLANT_TASK: 1,
        SNAPSHOT_TASK: 1,
        EVENT_MONITOR_TASK: 1,
        TELEMETRY_TASK: 5,
        DASHBOARD_TASK: 7,
    }
    periods.update(period_ticks or {})
    return SchedulerConfig(
        preset_name="application-test",
        base_tick_s=0.001,
        tasks=tuple(
            PeriodicTaskDefinition(
                name=name,
                period_ticks=periods[name],
                phase_offset_ticks=0,
                priority=TASK_PRIORITIES[name],
            )
            for name in _TASK_NAMES
        ),
    )


class _RecordingSensorModel:
    def __init__(self) -> None:
        self.time_steps_s: list[float] = []

    def measure(
        self,
        engine_state: EngineState,
        time_step_s: float,
    ) -> SensorData:
        self.time_steps_s.append(time_step_s)
        return SensorData(
            rotor_speed_rpm=engine_state.rotor_speed_rpm,
            exhaust_temperature_c=engine_state.exhaust_temperature_c,
        )


class _SequenceSensorModel:
    def __init__(self) -> None:
        self.release_count = 0

    def measure(
        self,
        engine_state: EngineState,
        time_step_s: float,
    ) -> SensorData:
        del engine_state, time_step_s
        self.release_count += 1
        return SensorData(
            rotor_speed_rpm=float(self.release_count * 10),
            exhaust_temperature_c=450.0,
        )


class _RecordingValidator(SensorSignalValidator):
    def __init__(self) -> None:
        super().__init__()
        self.time_steps_s: list[float] = []

    def update(
        self,
        raw_sensor_data: RawSensorData,
        context: SensorValidationContext,
        time_step_s: float,
    ) -> SensorValidationResult:
        self.time_steps_s.append(time_step_s)
        return super().update(raw_sensor_data, context, time_step_s)


class _RecordingController(PIEngineSpeedController):
    def __init__(self) -> None:
        super().__init__()
        self.time_steps_s: list[float] = []

    def update(
        self,
        control_request: ControlRequest,
        sensor_data: SensorData,
        time_step_s: float,
    ) -> ActuatorCommand:
        self.time_steps_s.append(time_step_s)
        return super().update(control_request, sensor_data, time_step_s)


class _RecordingProtectionManager(ProtectionManager):
    def __init__(self) -> None:
        super().__init__()
        self.time_steps_s: list[float] = []

    def apply(
        self,
        requested_fuel_command: float,
        sensor_data: SensorData,
        context: ProtectionContext,
        time_step_s: float,
    ) -> ProtectionResult:
        self.time_steps_s.append(time_step_s)
        return super().apply(
            requested_fuel_command,
            sensor_data,
            context,
            time_step_s,
        )


class _RecordingEngineModel(FirstOrderEngineModel):
    def __init__(self) -> None:
        super().__init__()
        self.time_steps_s: list[float] = []

    def step(
        self,
        actuator_command: ActuatorCommand,
        ambient_conditions: AmbientConditions,
        time_step_s: float,
    ) -> EngineOutputs:
        self.time_steps_s.append(time_step_s)
        return super().step(
            actuator_command,
            ambient_conditions,
            time_step_s,
        )


class _SnapshotCollector(SnapshotSink):
    def __init__(self) -> None:
        self.snapshots: list[EngineSimulationSnapshot] = []

    def publish(self, snapshot: EngineSimulationSnapshot) -> None:
        self.snapshots.append(snapshot)


def _advance_to_running(coordinator: EngineSimulationCoordinator) -> None:
    coordinator.submit_request(
        EngineOperationRequest(startup_requested=True)
    )
    throttle_submitted = False
    for _ in range(10_000):
        coordinator.step_one_tick()
        if (
            coordinator.snapshot.operating_state is EngineOperatingState.IDLE
            and not throttle_submitted
        ):
            coordinator.submit_request(
                EngineOperationRequest(throttle_command=0.5)
            )
            throttle_submitted = True
        if (
            coordinator.snapshot.operating_state
            is EngineOperatingState.RUNNING
        ):
            return
    raise AssertionError("engine did not reach RUNNING")


def test_components_receive_their_own_effective_periods() -> None:
    sensor = _RecordingSensorModel()
    validator = _RecordingValidator()
    controller = _RecordingController()
    protection = _RecordingProtectionManager()
    engine = _RecordingEngineModel()
    coordinator = EngineSimulationCoordinator(
        engine_model=engine,
        speed_controller=controller,
        protection_manager=protection,
        sensor_model=sensor,
        sensor_validator=validator,
        scheduler_config=_config(),
    )

    _advance_to_running(coordinator)

    assert sensor.time_steps_s
    assert all(value == pytest.approx(0.003) for value in sensor.time_steps_s)
    assert validator.time_steps_s
    assert all(
        value == pytest.approx(0.003) for value in validator.time_steps_s
    )
    assert controller.time_steps_s
    assert all(
        value == pytest.approx(0.004) for value in controller.time_steps_s
    )
    assert protection.time_steps_s
    assert all(
        value == pytest.approx(0.002) for value in protection.time_steps_s
    )
    assert engine.time_steps_s
    assert all(value == pytest.approx(0.001) for value in engine.time_steps_s)
    assert 0.007 not in (
        sensor.time_steps_s
        + validator.time_steps_s
        + controller.time_steps_s
        + protection.time_steps_s
        + engine.time_steps_s
    )


def test_sensor_output_is_held_between_central_sensor_releases() -> None:
    collector = _SnapshotCollector()
    coordinator = EngineSimulationCoordinator(
        sensor_model=_SequenceSensorModel(),
        scheduler_config=_config(),
        snapshot_sinks=(collector,),
    )

    for _ in range(7):
        coordinator.step_one_tick()

    assert [
        snapshot.measured_rotor_speed_rpm
        for snapshot in collector.snapshots
    ] == pytest.approx([10.0, 10.0, 10.0, 20.0, 20.0, 20.0, 30.0])


def test_controller_and_actuator_outputs_hold_between_releases() -> None:
    collector = _SnapshotCollector()
    coordinator = EngineSimulationCoordinator(
        scheduler_config=_config(),
        snapshot_sinks=(collector,),
    )
    _advance_to_running(coordinator)
    collector.snapshots.clear()

    for _ in range(12):
        coordinator.step_one_tick()

    for previous, current in zip(
        collector.snapshots,
        collector.snapshots[1:],
    ):
        if CONTROLLER_TASK not in (
            current.scheduler_tasks_executed_current_tick
        ):
            assert current.requested_fuel_command == pytest.approx(
                previous.requested_fuel_command
            )
        if ACTUATOR_TASK not in current.scheduler_tasks_executed_current_tick:
            assert current.allowed_fuel_command == pytest.approx(
                previous.allowed_fuel_command
            )


def test_tick_zero_order_and_plant_execution_are_exact() -> None:
    engine = _RecordingEngineModel()
    coordinator = EngineSimulationCoordinator(
        engine_model=engine,
        scheduler_config=_config(),
    )

    coordinator.step_one_tick()
    tick_zero_order = (
        coordinator.snapshot.scheduler_tasks_executed_current_tick
    )
    for _ in range(19):
        coordinator.step_one_tick()

    diagnostics = coordinator.scheduler_diagnostics()
    assert tick_zero_order == _TASK_NAMES
    assert diagnostics.tasks[7].task_name == PLANT_TASK
    assert diagnostics.tasks[7].execution_count == 20
    assert len(engine.time_steps_s) == 20
    assert diagnostics.total_missed_release_count == 0


def test_dashboard_publication_does_not_execute_control_or_plant_tasks() -> None:
    collector = _SnapshotCollector()
    coordinator = EngineSimulationCoordinator(
        scheduler_config=_config(),
    )
    coordinator.add_dashboard_sink(collector)
    for _ in range(8):
        coordinator.step_one_tick()

    diagnostics = {
        task.task_name: task
        for task in coordinator.scheduler_diagnostics().tasks
    }
    assert len(collector.snapshots) == 2
    assert diagnostics[DASHBOARD_TASK].execution_count == 2
    assert diagnostics[PLANT_TASK].execution_count == 8
    assert diagnostics[CONTROLLER_TASK].execution_count == 2
