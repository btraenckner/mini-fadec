"""Application-facing control boundary for simulation clients."""

from pathlib import Path

from simulation.application.engine_simulation import EngineSimulationCoordinator
from simulation.operation.state_machine import EngineOperationRequest
from simulation.sensors.fault_injection import (
    SensorChannel,
    SensorFaultDefinition,
)
from simulation.sensors.sensor_model import ConfigurableSensorModel
from simulation.telemetry.events import (
    EventCategory,
    EventSeverity,
    EventType,
    SimulationEvent,
)
from simulation.telemetry.interfaces import SnapshotSink
from simulation.telemetry.metadata import RunMetadataContext
from simulation.telemetry.recorder import (
    RunRecorder,
    RunRecordingSummary,
)
from simulation.telemetry.snapshot import SimulationSnapshot


class SimulationService:
    """Coordinate operator commands and read-only runtime observability."""

    def __init__(
        self,
        coordinator: EngineSimulationCoordinator | None = None,
        recorder: RunRecorder | None = None,
        *,
        time_step_s: float = 0.01,
    ) -> None:
        if time_step_s <= 0.0:
            raise ValueError("time_step_s must be greater than zero")
        self.coordinator = coordinator or EngineSimulationCoordinator()
        self.recorder = recorder or RunRecorder()
        self.time_step_s = time_step_s

        self._throttle_demand = 0.0
        self._startup_requested = False
        self._shutdown_requested = False
        self._fault_requested = False
        self._reset_requested = False

        self.coordinator.add_snapshot_sink(self.recorder)
        self.coordinator.event_log.add_sink(self.recorder)

    def request_start(self) -> None:
        """Queue one startup request for the next simulation step."""

        self._startup_requested = True
        self._emit_operator_event(
            EventType.STARTUP_REQUESTED,
            "Engine startup requested",
        )

    def set_throttle(self, throttle_demand: float) -> float:
        """Set and return the clamped persistent throttle demand."""

        clamped_demand = self._clamp(throttle_demand, 0.0, 1.0)
        previous_demand = self._throttle_demand
        self._throttle_demand = clamped_demand
        if abs(clamped_demand - previous_demand) > 1.0e-12:
            self._emit_operator_event(
                EventType.THROTTLE_CHANGED,
                f"Throttle demand changed to {clamped_demand:.3f}",
                old_value=previous_demand,
                new_value=clamped_demand,
            )
        return clamped_demand

    def request_shutdown(self) -> None:
        """Queue one controlled shutdown request."""

        self._shutdown_requested = True
        self._emit_operator_event(
            EventType.SHUTDOWN_REQUESTED,
            "Engine shutdown requested",
        )

    def request_fault(self) -> None:
        """Queue one manual FAULT request."""

        self._fault_requested = True
        self._emit_operator_event(
            EventType.MANUAL_FAULT_REQUESTED,
            "Manual engine FAULT requested",
            severity=EventSeverity.WARNING,
        )

    def request_reset(self) -> None:
        """Queue one FADEC reset request."""

        self._reset_requested = True
        self._emit_operator_event(
            EventType.RESET_REQUESTED,
            "FADEC reset requested",
        )

    def inject_sensor_fault(
        self,
        channel: SensorChannel,
        fault: SensorFaultDefinition,
    ) -> None:
        """Inject a typed simulation-only sensor fault."""

        self.coordinator.inject_sensor_fault(channel, fault)

    def clear_sensor_fault(self, channel: SensorChannel) -> None:
        """Clear one injected sensor fault."""

        self.coordinator.clear_sensor_fault(channel)

    def clear_sensor_faults(self) -> None:
        """Clear all injected sensor faults."""

        self.coordinator.clear_sensor_faults()

    def describe_sensor_fault(self, channel: SensorChannel) -> str:
        """Return the stable public description of one injected fault."""

        return self.coordinator.describe_sensor_fault(channel)

    def step(self, time_step_s: float | None = None) -> SimulationSnapshot:
        """Advance one deterministic step and consume queued one-shot commands."""

        step_size_s = self.time_step_s if time_step_s is None else time_step_s
        request = self._consume_operation_request()
        return self.coordinator.step(request=request, time_step_s=step_size_s)

    def apply_request(self, request: EngineOperationRequest) -> None:
        """Translate an existing application request into service commands."""

        self.set_throttle(request.throttle_command)
        if request.startup_requested:
            self.request_start()
        if request.shutdown_requested:
            self.request_shutdown()
        if request.fault_requested:
            self.request_fault()
        if request.reset_requested:
            self.request_reset()

    def start_recording(self, run_name: str | None = None) -> Path:
        """Start one run recording and emit its first structured event."""

        run_directory = self.recorder.start_recording(
            initial_snapshot=self.get_latest_snapshot(),
            metadata_context=self._metadata_context(),
            run_name=run_name,
        )
        self.coordinator.event_log.emit(
            self.get_latest_snapshot().simulation_time_s,
            EventCategory.RECORDING,
            EventType.RECORDING_STARTED,
            EventSeverity.INFO,
            "run_recorder",
            "Recording started",
            new_value=(
                self.recorder.status.run_name
                if self.recorder.status is not None
                else "run"
            ),
        )
        return run_directory

    def stop_recording(
        self,
        *,
        completed: bool = True,
    ) -> RunRecordingSummary | None:
        """Emit a stop event, finalize run metadata, and close run files."""

        if not self.recorder.is_recording:
            return None
        self.coordinator.event_log.emit(
            self.get_latest_snapshot().simulation_time_s,
            EventCategory.RECORDING,
            EventType.RECORDING_STOPPED,
            EventSeverity.INFO,
            "run_recorder",
            "Recording stopped",
        )
        return self.recorder.stop_recording(completed=completed)

    def add_marker(self, text: str) -> SimulationEvent:
        """Add one non-empty operator marker without altering the simulation."""

        marker_text = text.strip()
        if not marker_text:
            raise ValueError("marker text cannot be empty")
        return self.coordinator.event_log.emit(
            self.get_latest_snapshot().simulation_time_s,
            EventCategory.OPERATOR_COMMAND,
            EventType.USER_MARKER,
            EventSeverity.INFO,
            "operator",
            marker_text,
            new_value=marker_text,
        )

    def get_latest_snapshot(self) -> SimulationSnapshot:
        """Return the latest immutable canonical runtime snapshot."""

        return self.coordinator.snapshot

    def get_recent_events(self) -> tuple[SimulationEvent, ...]:
        """Return an immutable bounded view of recent structured events."""

        return self.coordinator.event_log.events

    def get_recording_status(self) -> RunRecordingSummary | None:
        """Return current or most recently finalized recording status."""

        return self.recorder.status

    def list_recent_runs(self, maximum_runs: int = 5) -> tuple[Path, ...]:
        """List recent run directories without loading their contents."""

        if maximum_runs <= 0:
            return ()
        base_directory = self.recorder.parameters.base_directory
        if not base_directory.exists():
            return ()
        run_directories = sorted(
            (path for path in base_directory.iterdir() if path.is_dir()),
            key=lambda path: path.name,
            reverse=True,
        )
        return tuple(run_directories[:maximum_runs])

    def add_snapshot_sink(self, sink: SnapshotSink) -> None:
        """Publish subsequent canonical snapshots to another client adapter."""

        self.coordinator.add_snapshot_sink(sink)

    def remove_snapshot_sink(self, sink: SnapshotSink) -> None:
        """Remove a registered client adapter."""

        self.coordinator.remove_snapshot_sink(sink)

    def close(self, *, completed: bool = False) -> None:
        """Finalize any active recording during application cleanup."""

        self.stop_recording(completed=completed)

    def _consume_operation_request(self) -> EngineOperationRequest:
        request = EngineOperationRequest(
            throttle_command=self._throttle_demand,
            startup_requested=self._startup_requested,
            shutdown_requested=self._shutdown_requested,
            fault_requested=self._fault_requested,
            reset_requested=self._reset_requested,
        )
        self._startup_requested = False
        self._shutdown_requested = False
        self._fault_requested = False
        self._reset_requested = False
        return request

    def _emit_operator_event(
        self,
        event_type: EventType,
        message: str,
        *,
        severity: EventSeverity = EventSeverity.INFO,
        old_value: str | int | float | bool | None = None,
        new_value: str | int | float | bool | None = None,
    ) -> SimulationEvent:
        return self.coordinator.event_log.emit(
            self.get_latest_snapshot().simulation_time_s,
            EventCategory.OPERATOR_COMMAND,
            event_type,
            severity,
            "operator",
            message,
            old_value=old_value,
            new_value=new_value,
        )

    def _metadata_context(self) -> RunMetadataContext:
        sensor_seed = None
        if isinstance(self.coordinator.sensor_model, ConfigurableSensorModel):
            sensor_seed = self.coordinator.sensor_model.configuration.random_seed

        engine_parameters = self.coordinator.engine_model.parameters
        controller_parameters = self.coordinator.speed_controller.parameters
        egt_parameters = self.coordinator.egt_limiter.parameters
        overspeed_parameters = (
            self.coordinator.protection_manager.overspeed_limiter.parameters
        )
        configuration_summary = (
            ("engine_idle_speed_rpm", engine_parameters.idle_speed_rpm),
            ("engine_maximum_speed_rpm", engine_parameters.maximum_speed_rpm),
            (
                "engine_exhaust_temperature_time_constant_s",
                engine_parameters.exhaust_temperature_time_constant_s,
            ),
            (
                "controller_proportional_gain",
                controller_parameters.proportional_gain,
            ),
            ("controller_integral_gain", controller_parameters.integral_gain),
            (
                "egt_intervention_temperature_c",
                egt_parameters.intervention_exhaust_temperature_c,
            ),
            (
                "egt_maximum_temperature_c",
                egt_parameters.maximum_exhaust_temperature_c,
            ),
            (
                "soft_overspeed_speed_rpm",
                overspeed_parameters.soft_overspeed_speed_rpm,
            ),
            (
                "hard_overspeed_speed_rpm",
                overspeed_parameters.hard_overspeed_speed_rpm,
            ),
        )
        return RunMetadataContext(
            simulation_time_step_s=self.time_step_s,
            sensor_random_seed=sensor_seed,
            engine_model_identifier=type(self.coordinator.engine_model).__name__,
            controller_identifier=type(
                self.coordinator.speed_controller
            ).__name__,
            protection_manager_identifier=type(
                self.coordinator.protection_manager
            ).__name__,
            configuration_summary=configuration_summary,
            repository_root=Path(__file__).resolve().parents[2],
        )

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(value, maximum))
