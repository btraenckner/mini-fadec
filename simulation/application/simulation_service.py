"""Application-facing control boundary for simulation clients."""

from dataclasses import replace
from pathlib import Path

from simulation.application.composition import create_configured_coordinator
from simulation.application.engine_simulation import EngineSimulationCoordinator
from simulation.configuration.engine_definition import EngineDefinition
from simulation.configuration.fadec_calibration import FadecCalibration
from simulation.configuration.profiles import (
    reference_engine_definition,
    reference_fadec_calibration,
)
from simulation.core.types import AmbientConditions
from simulation.operation.state_machine import EngineOperationRequest
from simulation.operation.engine_state import EngineOperatingState
from simulation.plants.config import PlantSelectionConfig
from simulation.plants.factory import plant_selection_for
from simulation.plants.types import (
    PlantDiagnostics,
    PlantModelKind,
    PlantSimulationError,
)
from simulation.scheduling.config import (
    SchedulerConfig,
    SchedulingMode,
    seconds_to_ticks,
)
from simulation.scheduling.diagnostics import (
    SCHEDULER_SCHEMA_VERSION,
    SchedulerDiagnostics,
)
from simulation.scheduling.presets import get_scheduler_preset
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
        scheduler_config: SchedulerConfig | None = None,
        plant_config: PlantSelectionConfig | None = None,
        scheduling_mode: SchedulingMode = SchedulingMode.UNPACED,
        *,
        engine_definition: EngineDefinition | None = None,
        fadec_calibration: FadecCalibration | None = None,
        sensor_random_seed: int | None = 0,
        ambient_conditions: AmbientConditions | None = None,
        time_step_s: float = 0.01,
    ) -> None:
        if coordinator is not None and (
            scheduler_config is not None
            or plant_config is not None
            or engine_definition is not None
            or fadec_calibration is not None
            or ambient_conditions is not None
        ):
            raise ValueError(
                "runtime configuration can be provided only when constructing "
                "the coordinator"
            )
        if engine_definition is not None and plant_config is not None:
            raise ValueError(
                "provide either engine_definition or plant_config, not both"
            )
        if time_step_s <= 0.0:
            raise ValueError("time_step_s must be greater than zero")

        self.engine_definition: EngineDefinition | None = None
        self.fadec_calibration: FadecCalibration | None = None
        self.sensor_random_seed = sensor_random_seed
        if coordinator is None:
            self.engine_definition = (
                engine_definition
                or reference_engine_definition(plant=plant_config)
            )
            self.fadec_calibration = (
                fadec_calibration or reference_fadec_calibration()
            )
            coordinator = create_configured_coordinator(
                self.engine_definition,
                self.fadec_calibration,
                scheduler_config=scheduler_config,
                sensor_random_seed=sensor_random_seed,
                ambient_conditions=ambient_conditions,
            )
        self.coordinator = coordinator
        seconds_to_ticks(
            time_step_s,
            self.coordinator.scheduler_config.base_tick_s,
            field_name="time_step_s",
        )
        self.recorder = recorder or RunRecorder()
        self.time_step_s = time_step_s
        self.scheduling_mode = scheduling_mode

        self._throttle_demand = 0.0
        self._startup_requested = False
        self._shutdown_requested = False
        self._fault_requested = False
        self._reset_requested = False

        self.coordinator.add_telemetry_sink(self.recorder)
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
        """Advance an exact scheduler duration and consume queued commands."""

        step_size_s = self.time_step_s if time_step_s is None else time_step_s
        request = self._consume_operation_request()
        try:
            return self.coordinator.step(
                request=request,
                time_step_s=step_size_s,
            )
        except PlantSimulationError:
            self.stop_recording(completed=False)
            raise

    def step_one_tick(self) -> SimulationSnapshot:
        """Advance exactly one scheduler base tick through the shared path."""

        self.coordinator.submit_request(self._consume_operation_request())
        try:
            return self.coordinator.step_one_tick()
        except PlantSimulationError:
            self.stop_recording(completed=False)
            raise

    @property
    def base_tick_s(self) -> float:
        """Return the central scheduler base tick."""

        return self.coordinator.scheduler_config.base_tick_s

    @property
    def current_simulation_time_s(self) -> float:
        """Return authoritative logical time independent of snapshot rate."""

        return self.coordinator.scheduler.current_time_s

    def get_scheduler_diagnostics(self) -> SchedulerDiagnostics:
        """Return immutable full timing diagnostics for application clients."""

        return self.coordinator.scheduler_diagnostics()

    def get_plant_diagnostics(self) -> PlantDiagnostics:
        """Return immutable diagnostics for the selected physical plant."""

        return self.coordinator.engine_model.get_diagnostics()

    def get_plant_metadata(self) -> dict[str, object]:
        """Return a fresh serializable description of the selected plant."""

        return self.coordinator.engine_model.get_metadata()

    def select_plant_model(
        self,
        selection: PlantSelectionConfig | PlantModelKind | str,
    ) -> PlantSelectionConfig:
        """Select a fresh plant only while OFF and not recording."""

        selected_config = (
            selection
            if isinstance(selection, PlantSelectionConfig)
            else plant_selection_for(
                selection,
                base=self.coordinator.plant_config,
            )
        )
        if selected_config == self.coordinator.plant_config:
            return selected_config
        if self.recorder.is_recording:
            message = "plant model cannot change while recording is active"
            self._emit_plant_rejection(message)
            raise RuntimeError(message)
        if self.coordinator.snapshot.operating_state is not EngineOperatingState.OFF:
            message = "plant model can change only while the engine is OFF"
            self._emit_plant_rejection(message)
            raise RuntimeError(message)

        previous_model_id = self.coordinator.engine_model.model_id
        scheduler_config = self.coordinator.scheduler_config
        ambient_conditions = self.coordinator.ambient_conditions
        self.coordinator.stop_scheduler()
        updated_definition = None
        if (
            self.engine_definition is not None
            and self.fadec_calibration is not None
        ):
            updated_definition = replace(
                self.engine_definition,
                plant=selected_config,
            )
            replacement = create_configured_coordinator(
                updated_definition,
                self.fadec_calibration,
                scheduler_config=scheduler_config,
                sensor_random_seed=self.sensor_random_seed,
                ambient_conditions=ambient_conditions,
            )
        else:
            replacement = EngineSimulationCoordinator(
                plant_config=selected_config,
                scheduler_config=scheduler_config,
                ambient_conditions=ambient_conditions,
            )
        if updated_definition is not None:
            self.engine_definition = updated_definition
        self._attach_coordinator(replacement)
        self.coordinator.event_log.emit(
            0.0,
            EventCategory.SYSTEM,
            EventType.PLANT_MODEL_SELECTED,
            EventSeverity.INFO,
            "plant_factory",
            f"Plant model selected: {replacement.engine_model.display_name}",
            old_value=previous_model_id,
            new_value=replacement.engine_model.model_id,
        )
        self.coordinator.event_log.emit(
            0.0,
            EventCategory.SYSTEM,
            EventType.PLANT_RESET,
            EventSeverity.INFO,
            "plant_factory",
            "Plant and retained application state reset",
            new_value=replacement.engine_model.model_id,
        )
        return selected_config

    def select_scheduler_preset(self, preset_name: str) -> SchedulerConfig:
        """Select a preset only while stopped, resetting all retained state."""

        try:
            selected_config = get_scheduler_preset(preset_name)
        except KeyError:
            self._emit_scheduler_rejection(
                f"Unknown scheduler preset: {preset_name}"
            )
            raise
        if (
            selected_config.preset_name
            == self.coordinator.scheduler_config.preset_name
        ):
            return selected_config
        if self.recorder.is_recording:
            message = (
                "scheduler preset cannot change while recording is active"
            )
            self._emit_scheduler_rejection(message)
            raise RuntimeError(message)
        if self.coordinator.snapshot.operating_state is not EngineOperatingState.OFF:
            message = "scheduler preset can change only while the engine is OFF"
            self._emit_scheduler_rejection(message)
            raise RuntimeError(message)
        previous_preset = self.coordinator.scheduler_config.preset_name
        self.coordinator.stop_scheduler()
        if (
            self.engine_definition is not None
            and self.fadec_calibration is not None
        ):
            replacement = create_configured_coordinator(
                self.engine_definition,
                self.fadec_calibration,
                scheduler_config=selected_config,
                sensor_random_seed=self.sensor_random_seed,
                ambient_conditions=self.coordinator.ambient_conditions,
            )
        else:
            replacement = EngineSimulationCoordinator(
                scheduler_config=selected_config,
                plant_config=self.coordinator.plant_config,
                ambient_conditions=self.coordinator.ambient_conditions,
            )
        self._attach_coordinator(replacement)
        self.coordinator.event_log.emit(
            0.0,
            EventCategory.SYSTEM,
            EventType.SCHEDULER_PRESET_SELECTED,
            EventSeverity.INFO,
            "scheduler",
            f"Scheduler preset selected: {selected_config.preset_name}",
            old_value=previous_preset,
            new_value=selected_config.preset_name,
        )
        self.coordinator.event_log.emit(
            0.0,
            EventCategory.SYSTEM,
            EventType.SCHEDULER_RESET,
            EventSeverity.INFO,
            "scheduler",
            "Scheduler timing and retained application state reset",
            new_value=selected_config.preset_name,
        )
        return selected_config

    def _emit_plant_rejection(self, message: str) -> None:
        self.coordinator.event_log.emit(
            self.current_simulation_time_s,
            EventCategory.SYSTEM,
            EventType.PLANT_CONFIGURATION_REJECTED,
            EventSeverity.WARNING,
            "plant_factory",
            message,
            old_value=self.coordinator.engine_model.model_id,
        )

    def _attach_coordinator(
        self,
        coordinator: EngineSimulationCoordinator,
    ) -> None:
        """Attach existing sinks and clear held application commands."""

        self.coordinator = coordinator
        self.coordinator.add_telemetry_sink(self.recorder)
        self.coordinator.event_log.add_sink(self.recorder)
        self._throttle_demand = 0.0
        self._startup_requested = False
        self._shutdown_requested = False
        self._fault_requested = False
        self._reset_requested = False

    def _emit_scheduler_rejection(self, message: str) -> None:
        """Record an immutable timing-change rejection before raising."""

        self.coordinator.event_log.emit(
            self.current_simulation_time_s,
            EventCategory.SYSTEM,
            EventType.SCHEDULER_CONFIGURATION_REJECTED,
            EventSeverity.WARNING,
            "scheduler",
            message,
            old_value=self.coordinator.scheduler_config.preset_name,
        )

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

        self.coordinator.stop_scheduler()
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

        plant_metadata = self.coordinator.engine_model.get_metadata()
        plant_configuration = plant_metadata.get("configuration", {})
        if not isinstance(plant_configuration, dict):
            plant_configuration = {}
        controller_parameters = self.coordinator.speed_controller.parameters
        egt_parameters = self.coordinator.egt_limiter.parameters
        overspeed_parameters = (
            self.coordinator.protection_manager.overspeed_limiter.parameters
        )
        configuration_summary = (
            (
                "engine_definition_id",
                None
                if self.engine_definition is None
                else self.engine_definition.engine_id,
            ),
            (
                "engine_definition_version",
                None
                if self.engine_definition is None
                else self.engine_definition.definition_version,
            ),
            (
                "fadec_calibration_id",
                None
                if self.fadec_calibration is None
                else self.fadec_calibration.calibration_id,
            ),
            (
                "fadec_calibration_version",
                None
                if self.fadec_calibration is None
                else self.fadec_calibration.calibration_version,
            ),
            ("plant_model_id", self.coordinator.engine_model.model_id),
            (
                "engine_idle_speed_rpm",
                plant_configuration.get("idle_speed_rpm"),
            ),
            (
                "engine_maximum_speed_rpm",
                plant_configuration.get("maximum_speed_rpm"),
            ),
            (
                "engine_exhaust_temperature_time_constant_s",
                plant_configuration.get(
                    "exhaust_temperature_time_constant_s",
                    plant_configuration.get("thermal_time_constant_s"),
                ),
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
            scheduler_schema_version=SCHEDULER_SCHEMA_VERSION,
            scheduler_preset=(
                self.coordinator.scheduler_config.preset_name
            ),
            scheduler_base_tick_s=(
                self.coordinator.scheduler_config.base_tick_s
            ),
            scheduler_task_definitions=tuple(
                (
                    task.name,
                    task.period_ticks,
                    task.phase_offset_ticks,
                    task.priority,
                    task.enabled,
                )
                for task in self.coordinator.scheduler_config.tasks
            ),
            scheduler_execution_convention=(
                self.coordinator.scheduler_config.execution_convention.value
            ),
            simulation_scheduling_mode=self.scheduling_mode.value,
            configuration_summary=configuration_summary,
            engine_definition=(
                {}
                if self.engine_definition is None
                else self.engine_definition.to_dict()
            ),
            fadec_calibration=(
                {}
                if self.fadec_calibration is None
                else self.fadec_calibration.to_dict()
            ),
            repository_root=Path(__file__).resolve().parents[2],
            plant_metadata=plant_metadata,
        )

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(value, maximum))
