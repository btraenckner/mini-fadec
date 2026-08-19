"""Scheduled composition of engine operation, control, and plant dynamics."""

from collections import deque
from collections.abc import Iterable
from dataclasses import replace

from simulation.application.event_log import InMemoryEventLog
from simulation.application.sensor_fault_response import (
    SensorFaultResponse,
    SensorFaultResponsePolicy,
    SensorFaultResponseReason,
)
from simulation.controllers.speed_controller import PIEngineSpeedController
from simulation.core.interfaces import SensorModelInterface
from simulation.core.types import (
    ActuatorCommand,
    AmbientConditions,
    ControlRequest,
    EngineOutputs,
    RawSensorData,
    SensorData,
    ValidatedSensorData,
)
from simulation.operation.engine_state import EngineOperatingState
from simulation.operation.state_machine import (
    EngineOperatingCommand,
    EngineOperationRequest,
    EngineStateMachine,
)
from simulation.protection.exhaust_temperature_limiter import (
    ExhaustTemperatureLimiter,
)
from simulation.protection.overspeed_limiter import (
    OverspeedLimiter,
    OverspeedLimiterParameters,
)
from simulation.protection.protection_manager import ProtectionManager
from simulation.protection.types import (
    ProtectionContext,
    ProtectionDiagnosticReason,
    ProtectionResult,
)
from simulation.plants.config import PlantSelectionConfig
from simulation.plants.factory import (
    create_engine_plant,
    plant_selection_for,
)
from simulation.plants.interfaces import EnginePlant
from simulation.plants.types import PlantSimulationError
from simulation.scheduling.config import SchedulerConfig, seconds_to_ticks
from simulation.scheduling.diagnostics import (
    SCHEDULER_SCHEMA_VERSION,
    SchedulerDiagnostics,
)
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
    TELEMETRY_TASK,
    VALIDATION_TASK,
    nominal_multirate,
)
from simulation.scheduling.scheduler import (
    DeterministicScheduler,
    TaskExecutionContext,
)
from simulation.sensors.sensor_model import (
    ConfigurableSensorModel,
    SensorModelConfiguration,
)
from simulation.sensors.fault_injection import (
    SensorChannel,
    SensorFaultDefinition,
    SensorFaultInjector,
    sensor_fault_parameters,
    sensor_fault_type,
)
from simulation.telemetry.snapshot import (
    TELEMETRY_SCHEMA_VERSION,
    SimulationSnapshot,
)
from simulation.telemetry.interfaces import SnapshotSink
from simulation.telemetry.events import (
    EventCategory,
    EventSeverity,
    EventType,
    SimulationEventMonitor,
)
from simulation.validation.sensor_validation import (
    ChannelValidationResult,
    ChannelDiagnosticReason,
    ChannelHealth,
    SensorSignalValidator,
    SensorValidationContext,
    SensorValidationResult,
)


EngineSimulationSnapshot = SimulationSnapshot
"""Compatibility alias for the canonical telemetry-owned snapshot type."""


class EngineSimulationCoordinator:
    """Compose the operating state machine with control and engine dynamics."""

    def __init__(
        self,
        engine_model: EnginePlant | None = None,
        state_machine: EngineStateMachine | None = None,
        speed_controller: PIEngineSpeedController | None = None,
        egt_limiter: ExhaustTemperatureLimiter | None = None,
        protection_manager: ProtectionManager | None = None,
        sensor_model: SensorModelInterface | None = None,
        sensor_fault_injector: SensorFaultInjector | None = None,
        sensor_validator: SensorSignalValidator | None = None,
        sensor_fault_response_policy: SensorFaultResponsePolicy | None = None,
        event_log: InMemoryEventLog | None = None,
        snapshot_sinks: Iterable[SnapshotSink] = (),
        ambient_conditions: AmbientConditions | None = None,
        scheduler_config: SchedulerConfig | None = None,
        plant_config: PlantSelectionConfig | None = None,
    ) -> None:
        if engine_model is not None and plant_config is not None:
            raise ValueError(
                "provide either engine_model or plant_config, not both"
            )
        self.ambient_conditions = ambient_conditions or AmbientConditions()
        if engine_model is None:
            self.plant_config = plant_config or PlantSelectionConfig()
            self.engine_model = create_engine_plant(
                self.plant_config,
                initial_ambient=self.ambient_conditions,
            )
        else:
            self.engine_model = engine_model
            self.plant_config = plant_selection_for(engine_model.model_id)
        self.state_machine = state_machine or EngineStateMachine()
        self.speed_controller = speed_controller or PIEngineSpeedController()
        if protection_manager is not None and egt_limiter is not None:
            raise ValueError(
                "provide either protection_manager or egt_limiter, not both"
            )
        self.protection_manager = protection_manager or ProtectionManager(
            egt_limiter=egt_limiter or ExhaustTemperatureLimiter(),
            overspeed_limiter=OverspeedLimiter(
                parameters=OverspeedLimiterParameters(
                    maximum_normal_speed_rpm=(
                        self.speed_controller.scheduler.maximum_speed_rpm
                    )
                )
            ),
        )
        # Compatibility alias for callers that inspect EGT thresholds.
        self.egt_limiter = self.protection_manager.egt_limiter
        # Set random_seed=None for non-reproducible demonstration noise.
        self.sensor_model = sensor_model or ConfigurableSensorModel(
            configuration=SensorModelConfiguration(random_seed=0)
        )
        self.sensor_fault_injector = (
            sensor_fault_injector or SensorFaultInjector(random_seed=0)
        )
        self.sensor_validator = sensor_validator or SensorSignalValidator()
        self.sensor_fault_response_policy = (
            sensor_fault_response_policy or SensorFaultResponsePolicy()
        )
        self.event_log = event_log or InMemoryEventLog()
        self._snapshot_sinks = list(snapshot_sinks)
        self._telemetry_sinks: list[SnapshotSink] = []
        self._dashboard_sinks: list[SnapshotSink] = []
        self.scheduler_config = scheduler_config or nominal_multirate()

        self._simulation_time_s = 0.0
        self._step_index = 0
        self._snapshot_sequence_number = 0
        self._state_duration_s = 0.0
        self._previous_throttle_demand = 0.0
        self._speed_control_was_enabled = False
        self._last_nominal_sensor_data: SensorData | None = None
        self._command_queue: deque[EngineOperationRequest] = deque()
        self._held_throttle_demand = 0.0
        self._latched_startup_requested = False
        self._latched_shutdown_requested = False
        self._latched_fault_requested = False
        self._latched_reset_requested = False
        self._snapshot_startup_requested = False
        self._snapshot_shutdown_requested = False
        self._snapshot_fault_requested = False
        self._snapshot_reset_requested = False
        self._automatic_fault_transition_reason: (
            SensorFaultResponseReason | None
        ) = None
        self._critical_fault_transition_pending = False
        self._fuel_delivery_fault_active = False
        self._previous_operating_state_for_snapshot = self.state_machine.state
        self._state_entered_time_s = 0.0

        initial_sensor_data = SensorData(
            rotor_speed_rpm=self.engine_model.state.rotor_speed_rpm,
            exhaust_temperature_c=self.engine_model.state.exhaust_temperature_c,
        )
        self._held_nominal_sensor_data = initial_sensor_data
        self._held_raw_sensor_data = RawSensorData(
            rotor_speed_rpm=initial_sensor_data.rotor_speed_rpm,
            exhaust_temperature_c=initial_sensor_data.exhaust_temperature_c,
        )
        self._held_validation_result = self._initial_validation_result(
            initial_sensor_data
        )
        self._held_sensor_fault_response = (
            self.sensor_fault_response_policy.evaluate(
                self.state_machine.state,
                self._held_validation_result,
            )
        )
        self._held_operating_command = self.state_machine.update(
            EngineOperationRequest(),
            self._held_validation_result.sensor_data,
            self._task_period_s(STATE_MACHINE_TASK),
        )
        self._held_requested_command = ActuatorCommand(
            fuel_command=0.0,
            starter_commanded=False,
            ignition_commanded=False,
            fuel_enabled=False,
        )
        self._held_protection_result = self.protection_manager.last_result
        self._held_allowed_command = ActuatorCommand(
            fuel_command=0.0,
            starter_commanded=False,
            ignition_commanded=False,
            fuel_enabled=False,
        )
        self._held_applied_command = self._held_allowed_command
        self._held_engine_outputs = EngineOutputs(
            estimated_thrust_n=0.0,
            estimated_fuel_flow_ml_min=0.0,
        )
        self._snapshot = self._initial_snapshot()
        self.event_monitor = SimulationEventMonitor(
            self.event_log,
            initial_snapshot=self._snapshot,
        )
        self.scheduler = DeterministicScheduler(
            self.scheduler_config,
            {
                COMMAND_TASK: self._process_commands_task,
                STATE_MACHINE_TASK: self._state_machine_task,
                SENSOR_TASK: self._sensor_task,
                VALIDATION_TASK: self._validation_task,
                CONTROLLER_TASK: self._controller_task,
                PROTECTION_TASK: self._protection_task,
                ACTUATOR_TASK: self._actuator_task,
                PLANT_TASK: self._plant_task,
                SNAPSHOT_TASK: self._snapshot_task,
                EVENT_MONITOR_TASK: self._event_monitor_task,
                TELEMETRY_TASK: self._telemetry_task,
                DASHBOARD_TASK: self._dashboard_task,
            },
        )
        self._scheduler_run_started = False
        self._reported_missed_release_count = 0
        self.event_log.emit(
            0.0,
            EventCategory.SYSTEM,
            EventType.SCHEDULER_INITIALIZED,
            EventSeverity.INFO,
            "scheduler",
            f"Scheduler initialized with {self.scheduler_config.preset_name}",
            new_value=self.scheduler_config.preset_name,
        )

    @property
    def snapshot(self) -> EngineSimulationSnapshot:
        """Return the latest coordinated simulation snapshot."""

        return self._snapshot

    def add_snapshot_sink(self, sink: SnapshotSink) -> None:
        """Register one synchronous read-only snapshot consumer."""

        if all(existing is not sink for existing in self._snapshot_sinks):
            self._snapshot_sinks.append(sink)

    def remove_snapshot_sink(self, sink: SnapshotSink) -> None:
        """Remove one previously registered snapshot consumer."""

        self._snapshot_sinks = [
            existing for existing in self._snapshot_sinks if existing is not sink
        ]

    def add_telemetry_sink(self, sink: SnapshotSink) -> None:
        """Register a sink released only by the scheduler telemetry task."""

        if all(existing is not sink for existing in self._telemetry_sinks):
            self._telemetry_sinks.append(sink)

    def remove_telemetry_sink(self, sink: SnapshotSink) -> None:
        """Remove one scheduler-controlled telemetry sink."""

        self._telemetry_sinks = [
            existing
            for existing in self._telemetry_sinks
            if existing is not sink
        ]

    def add_dashboard_sink(self, sink: SnapshotSink) -> None:
        """Register a sink released only at the configured dashboard rate."""

        if all(existing is not sink for existing in self._dashboard_sinks):
            self._dashboard_sinks.append(sink)

    def submit_request(self, request: EngineOperationRequest) -> None:
        """Queue one immutable command request for deterministic FIFO capture."""

        self._command_queue.append(request)

    def step_one_tick(self) -> EngineSimulationSnapshot:
        """Advance exactly one scheduler base tick."""

        if not self._scheduler_run_started:
            self.event_log.emit(
                self.scheduler.current_time_s,
                EventCategory.SYSTEM,
                EventType.SCHEDULER_RUN_STARTED,
                EventSeverity.INFO,
                "scheduler",
                "Scheduler run started",
                new_value=self.scheduler_config.preset_name,
            )
            self._scheduler_run_started = True
        self.scheduler.step_one_tick()
        missed_releases = (
            self.scheduler.diagnostics().total_missed_release_count
        )
        if missed_releases > self._reported_missed_release_count:
            self.event_log.emit(
                self.scheduler.current_time_s,
                EventCategory.SYSTEM,
                EventType.SCHEDULER_MISSED_RELEASE,
                EventSeverity.WARNING,
                "scheduler",
                "Scheduler detected a missed logical task release",
                old_value=self._reported_missed_release_count,
                new_value=missed_releases,
            )
            self._reported_missed_release_count = missed_releases
        return self._snapshot

    def stop_scheduler(self) -> None:
        """Emit one meaningful logical run-stop event."""

        if not self._scheduler_run_started:
            return
        self.event_log.emit(
            self.scheduler.current_time_s,
            EventCategory.SYSTEM,
            EventType.SCHEDULER_RUN_STOPPED,
            EventSeverity.INFO,
            "scheduler",
            "Scheduler run stopped",
            old_value=self.scheduler_config.preset_name,
        )
        self._scheduler_run_started = False

    def scheduler_diagnostics(self) -> SchedulerDiagnostics:
        """Return immutable scheduler state for clients and dashboards."""

        return self.scheduler.diagnostics()

    def inject_sensor_fault(
        self,
        channel: SensorChannel,
        fault: SensorFaultDefinition,
    ) -> None:
        """Activate or replace a simulation-only fault on one sensor channel."""

        current_measurement = None
        if self._last_nominal_sensor_data is not None:
            current_measurement = (
                self._last_nominal_sensor_data.rotor_speed_rpm
                if channel is SensorChannel.ROTOR_SPEED
                else self._last_nominal_sensor_data.exhaust_temperature_c
            )
        self.sensor_fault_injector.activate(
            channel=channel,
            fault=fault,
            current_measurement=current_measurement,
        )
        description = self.sensor_fault_injector.describe(channel)
        self.event_log.emit(
            self._simulation_time_s,
            EventCategory.SENSOR_FAULT,
            EventType.SENSOR_FAULT_INJECTED,
            EventSeverity.WARNING,
            "sensor_fault_injector",
            f"Injected {channel.value} sensor fault: {description}",
            new_value=description,
            diagnostic_code=sensor_fault_type(fault),
        )

    def clear_sensor_fault(self, channel: SensorChannel) -> None:
        """Clear one injected fault without resetting validator recovery."""

        if not self.sensor_fault_injector.is_active(channel):
            return
        previous_description = self.sensor_fault_injector.describe(channel)
        self.sensor_fault_injector.clear(channel)
        self.event_log.emit(
            self._simulation_time_s,
            EventCategory.SENSOR_FAULT,
            EventType.SENSOR_FAULT_CLEARED,
            EventSeverity.INFO,
            "sensor_fault_injector",
            f"Cleared {channel.value} sensor fault",
            old_value=previous_description,
            new_value="none",
        )

    def clear_sensor_faults(self) -> None:
        """Clear all injected faults without bypassing validation recovery."""

        for channel in SensorChannel:
            self.clear_sensor_fault(channel)

    def describe_sensor_fault(self, channel: SensorChannel) -> str:
        """Return the stable public description of one injected fault."""

        return self.sensor_fault_injector.describe(channel)

    @property
    def fuel_delivery_fault_active(self) -> bool:
        """Return the simulation-only physical fuel-delivery fault state."""

        return self._fuel_delivery_fault_active

    def set_fuel_delivery_fault(self, active: bool) -> None:
        """Inject or clear a simulation-only loss of delivered plant fuel."""

        self._fuel_delivery_fault_active = bool(active)

    def _validation_context(
        self,
        request: EngineOperationRequest,
    ) -> SensorValidationContext:
        """Create narrowly scoped context from the previous coordinated step."""

        return SensorValidationContext(
            operating_state=self.state_machine.state,
            starter_commanded=self._held_applied_command.starter_commanded,
            ignition_commanded=self._held_applied_command.ignition_commanded,
            fuel_enabled=self._held_applied_command.fuel_enabled,
            fuel_command=self._held_applied_command.fuel_command,
            throttle_command=request.throttle_command,
        )

    @staticmethod
    def _effective_operation_request(
        request: EngineOperationRequest,
        validation_result: SensorValidationResult,
        sensor_fault_response: SensorFaultResponse,
    ) -> EngineOperationRequest:
        """Combine manual requests with automatic sensor fault response."""

        sensors_recovered = (
            validation_result.rotor_speed.health is ChannelHealth.VALID
            and validation_result.exhaust_temperature.health
            is ChannelHealth.VALID
        )
        return EngineOperationRequest(
            throttle_command=request.throttle_command,
            startup_requested=request.startup_requested,
            shutdown_requested=request.shutdown_requested,
            fault_requested=(
                request.fault_requested
                or sensor_fault_response.automatic_fault_requested
            ),
            reset_requested=request.reset_requested and sensors_recovered,
        )

    def step(
        self,
        request: EngineOperationRequest,
        time_step_s: float,
    ) -> EngineSimulationSnapshot:
        """Submit one request and run an exact scheduler duration."""

        self.submit_request(request)
        number_of_ticks = seconds_to_ticks(
            time_step_s,
            self.scheduler_config.base_tick_s,
            field_name="time_step_s",
        )
        for _ in range(number_of_ticks):
            self.step_one_tick()
        return self._snapshot

    def _process_commands_task(
        self,
        _context: TaskExecutionContext,
    ) -> None:
        """Capture queued immutable requests in deterministic FIFO order."""

        while self._command_queue:
            request = self._command_queue.popleft()
            self._held_throttle_demand = self._clamp(
                request.throttle_command,
                0.0,
                1.0,
            )
            self._latched_startup_requested |= request.startup_requested
            self._latched_shutdown_requested |= request.shutdown_requested
            self._latched_fault_requested |= request.fault_requested
            self._latched_reset_requested |= request.reset_requested
            self._snapshot_startup_requested |= request.startup_requested
            self._snapshot_shutdown_requested |= request.shutdown_requested
            self._snapshot_fault_requested |= request.fault_requested
            self._snapshot_reset_requested |= request.reset_requested

    def _state_machine_task(self, context: TaskExecutionContext) -> None:
        """Consume latched requests and update retained operating supervision."""

        previous_state = self.state_machine.state
        request = self._latched_operation_request()
        effective_request = self._effective_operation_request(
            request,
            self._held_validation_result,
            self._held_sensor_fault_response,
        )
        operating_command = self.state_machine.update(
            request=effective_request,
            sensor_data=self._held_validation_result.sensor_data,
            time_step_s=context.execution_period_s,
        )
        if self._speed_control_was_enabled and not (
            operating_command.speed_control_enabled
        ):
            self.speed_controller.reset()
        if operating_command.state is not previous_state:
            self._previous_operating_state_for_snapshot = previous_state
            self._state_entered_time_s = context.release_time_s
            if (
                previous_state is EngineOperatingState.FAULT
                and operating_command.state is not EngineOperatingState.FAULT
            ):
                self._automatic_fault_transition_reason = None
                self._critical_fault_transition_pending = False
        self._held_operating_command = operating_command
        self._speed_control_was_enabled = operating_command.speed_control_enabled
        self._latched_startup_requested = False
        self._latched_shutdown_requested = False
        self._latched_fault_requested = False
        self._latched_reset_requested = False

    def _sensor_task(self, context: TaskExecutionContext) -> None:
        """Sample current plant truth and hold raw measurements until released."""

        nominal_sensor_data = self.sensor_model.measure(
            engine_state=self.engine_model.state,
            time_step_s=context.execution_period_s,
        )
        self._last_nominal_sensor_data = nominal_sensor_data
        self._held_nominal_sensor_data = nominal_sensor_data
        self._held_raw_sensor_data = self.sensor_fault_injector.apply(
            sensor_data=nominal_sensor_data,
            time_step_s=context.execution_period_s,
        )

    def _validation_task(self, context: TaskExecutionContext) -> None:
        """Validate the held raw sample and retain health and fallback outputs."""

        request = self._latched_operation_request()
        self._held_validation_result = self.sensor_validator.update(
            raw_sensor_data=self._held_raw_sensor_data,
            context=self._validation_context(request),
            time_step_s=context.execution_period_s,
        )
        self._held_sensor_fault_response = (
            self.sensor_fault_response_policy.evaluate(
                operating_state=self.state_machine.state,
                validation_result=self._held_validation_result,
            )
        )
        if self._held_sensor_fault_response.automatic_fault_requested:
            self._latched_fault_requested = True
            self._automatic_fault_transition_reason = (
                self._held_sensor_fault_response.reason
            )

    def _controller_task(self, context: TaskExecutionContext) -> None:
        """Update or explicitly hold the requested actuator command."""

        operating_command = self._held_operating_command
        sensor_data = self._held_validation_result.sensor_data
        if (
            operating_command.speed_control_enabled
            and sensor_data.rotor_speed_rpm is not None
            and sensor_data.exhaust_temperature_c is not None
        ):
            self._held_requested_command = self._requested_actuator_command(
                operating_command=operating_command,
                sensor_data=sensor_data,
                time_step_s=context.execution_period_s,
            )
            return

        fuel_command = (
            operating_command.open_loop_fuel_command
            if not operating_command.speed_control_enabled
            else 0.0
        )
        self._held_requested_command = ActuatorCommand(
            fuel_command=fuel_command,
            starter_commanded=operating_command.starter_commanded,
            ignition_commanded=operating_command.ignition_commanded,
            fuel_enabled=operating_command.fuel_enabled,
        )

    def _protection_task(self, context: TaskExecutionContext) -> None:
        """Evaluate protection independently using the latest held request."""

        (
            self._held_allowed_command,
            self._held_protection_result,
        ) = self._protected_actuator_command(
            requested_command=self._held_requested_command,
            operating_command=self._held_operating_command,
            sensor_data=self._held_validation_result.sensor_data,
            sensor_critical_condition=(
                self._held_sensor_fault_response.fuel_cutoff_required
            ),
            time_step_s=context.execution_period_s,
        )
        if self._held_protection_result.critical_protection_fault_request:
            self._latched_fault_requested = True
            self._critical_fault_transition_pending = True

    def _actuator_task(self, _context: TaskExecutionContext) -> None:
        """Apply held protection output with immediate hard-cutoff precedence."""

        operating_command = self._held_operating_command
        hard_cutoff_required = (
            operating_command.state
            in {
                EngineOperatingState.OFF,
                EngineOperatingState.SHUTDOWN,
                EngineOperatingState.FAULT,
            }
            or self._held_sensor_fault_response.fuel_cutoff_required
            or self._held_protection_result.hard_cutoff_active
        )
        self._held_applied_command = ActuatorCommand(
            fuel_command=(
                0.0
                if hard_cutoff_required
                else self._held_allowed_command.fuel_command
            ),
            starter_commanded=operating_command.starter_commanded,
            ignition_commanded=operating_command.ignition_commanded,
            fuel_enabled=operating_command.fuel_enabled,
        )

    def _plant_task(self, context: TaskExecutionContext) -> None:
        """Integrate the plant once using the explicitly held actuator output."""

        plant_command = self._held_applied_command
        if self._fuel_delivery_fault_active:
            plant_command = replace(
                plant_command,
                fuel_command=0.0,
                fuel_enabled=False,
            )
        self._held_engine_outputs = self.engine_model.step(
            actuator_command=plant_command,
            ambient_conditions=self.ambient_conditions,
            time_step_s=context.execution_period_s,
        )
        self._simulation_time_s = (
            context.release_time_s + context.execution_period_s
        )
        plant_time_s = self.engine_model.get_diagnostics().model_time_s
        tolerance_s = 1.0e-12 * max(1.0, self._simulation_time_s)
        if abs(plant_time_s - self._simulation_time_s) > tolerance_s:
            raise PlantSimulationError(
                "scheduler and plant time diverged: "
                f"scheduler={self._simulation_time_s:.12f} s, "
                f"plant={plant_time_s:.12f} s"
            )
        self._step_index += 1

    def _snapshot_task(self, context: TaskExecutionContext) -> None:
        """Build and publish one coherent end-of-integration snapshot."""

        self._snapshot_sequence_number += 1
        self._state_duration_s = max(
            0.0,
            self._simulation_time_s - self._state_entered_time_s,
        )
        validation_result = self._held_validation_result
        protection_result = self._held_protection_result
        operating_command = self._held_operating_command
        raw_sensor_data = self._held_raw_sensor_data
        requested_command = self._held_requested_command
        allowed_command = self._held_applied_command
        sensor_fault_response = self._held_sensor_fault_response
        validated_speed_rpm = validation_result.sensor_data.rotor_speed_rpm
        throttle_demand = self._held_throttle_demand
        request = self._snapshot_operation_request()
        latest_operator_command = self._latest_operator_command(
            request,
            throttle_demand,
        )
        speed_setpoint_rpm = self._speed_setpoint_rpm(operating_command)
        scheduler_diagnostics = {
            task.task_name: task
            for task in self.scheduler.task_diagnostics()
        }
        plant_diagnostics = self.engine_model.get_diagnostics()
        current_tick_tasks = tuple(
            task.name
            for task in sorted(
                self.scheduler_config.tasks,
                key=lambda definition: (
                    definition.priority,
                    definition.name,
                ),
            )
            if task.enabled
            and context.current_tick >= task.phase_offset_ticks
            and (
                context.current_tick - task.phase_offset_ticks
            )
            % task.period_ticks
            == 0
        )
        self._snapshot = replace(
            self._snapshot,
            simulation_time_s=self._simulation_time_s,
            step_index=self._step_index,
            time_step_s=context.execution_period_s,
            snapshot_sequence_number=self._snapshot_sequence_number,
            startup_requested=request.startup_requested,
            shutdown_requested=request.shutdown_requested,
            reset_requested=request.reset_requested,
            fault_requested=request.fault_requested,
            throttle_demand=throttle_demand,
            latest_operator_command=latest_operator_command,
            previous_operating_state=(
                self._previous_operating_state_for_snapshot
            ),
            operating_state=operating_command.state,
            state_duration_s=self._state_duration_s,
            start_elapsed_s=self.state_machine.start_elapsed_s,
            start_timeout_triggered=(
                self.state_machine.start_timeout_triggered
            ),
            starter_commanded=allowed_command.starter_commanded,
            ignition_commanded=allowed_command.ignition_commanded,
            speed_control_enabled=operating_command.speed_control_enabled,
            fuel_enabled=allowed_command.fuel_enabled,
            throttle_command=operating_command.effective_throttle_command,
            speed_setpoint_rpm=speed_setpoint_rpm,
            speed_error_rpm=(
                speed_setpoint_rpm - validated_speed_rpm
                if operating_command.speed_control_enabled
                and validated_speed_rpm is not None
                else None
            ),
            requested_fuel_command=requested_command.fuel_command,
            rotor_speed_rpm=self.engine_model.state.rotor_speed_rpm,
            exhaust_temperature_c=(
                self.engine_model.state.exhaust_temperature_c
            ),
            estimated_thrust_n=self._held_engine_outputs.estimated_thrust_n,
            estimated_fuel_flow_ml_min=(
                self._held_engine_outputs.estimated_fuel_flow_ml_min
            ),
            measured_rotor_speed_rpm=raw_sensor_data.rotor_speed_rpm,
            measured_exhaust_temperature_c=(
                raw_sensor_data.exhaust_temperature_c
            ),
            validated_rotor_speed_rpm=validated_speed_rpm,
            validated_exhaust_temperature_c=(
                validation_result.sensor_data.exhaust_temperature_c
            ),
            rotor_speed_measurement_error_rpm=self._measurement_error(
                raw_sensor_data.rotor_speed_rpm,
                self.engine_model.state.rotor_speed_rpm,
            ),
            exhaust_temperature_measurement_error_c=self._measurement_error(
                raw_sensor_data.exhaust_temperature_c,
                self.engine_model.state.exhaust_temperature_c,
            ),
            rotor_speed_health=validation_result.rotor_speed.health,
            exhaust_temperature_health=(
                validation_result.exhaust_temperature.health
            ),
            aggregate_sensor_health=validation_result.aggregate_health,
            rotor_speed_diagnostic_reason=(
                validation_result.rotor_speed.diagnostic_reason
            ),
            exhaust_temperature_diagnostic_reason=(
                validation_result.exhaust_temperature.diagnostic_reason
            ),
            rotor_speed_value_is_held=(
                validation_result.rotor_speed.value_is_held
            ),
            exhaust_temperature_value_is_held=(
                validation_result.exhaust_temperature.value_is_held
            ),
            rotor_speed_fault=self.sensor_fault_injector.describe(
                SensorChannel.ROTOR_SPEED
            ),
            rotor_speed_fault_type=sensor_fault_type(
                self.sensor_fault_injector.active_fault(
                    SensorChannel.ROTOR_SPEED
                )
            ),
            rotor_speed_fault_parameters=sensor_fault_parameters(
                self.sensor_fault_injector.active_fault(
                    SensorChannel.ROTOR_SPEED
                )
            ),
            exhaust_temperature_fault=self.sensor_fault_injector.describe(
                SensorChannel.EXHAUST_TEMPERATURE
            ),
            exhaust_temperature_fault_type=sensor_fault_type(
                self.sensor_fault_injector.active_fault(
                    SensorChannel.EXHAUST_TEMPERATURE
                )
            ),
            exhaust_temperature_fault_parameters=sensor_fault_parameters(
                self.sensor_fault_injector.active_fault(
                    SensorChannel.EXHAUST_TEMPERATURE
                )
            ),
            fuel_delivery_fault_active=self._fuel_delivery_fault_active,
            allowed_fuel_command=allowed_command.fuel_command,
            egt_fuel_limit=protection_result.egt_fuel_limit,
            acceleration_fuel_limit=protection_result.acceleration_fuel_limit,
            overspeed_fuel_limit=protection_result.overspeed_fuel_limit,
            deceleration_minimum_fuel_command=(
                protection_result.deceleration_minimum_fuel_command
            ),
            state_maximum_fuel_command=(
                protection_result.state_maximum_fuel_command
            ),
            active_protection_limiter=protection_result.active_limiter,
            constraining_protection_limiters=(
                protection_result.constraining_limiters
            ),
            rotor_acceleration_rpm_per_s=(
                protection_result.rotor_acceleration_rpm_per_s
            ),
            rotor_deceleration_rpm_per_s=(
                protection_result.rotor_deceleration_rpm_per_s
            ),
            speed_ratio=protection_result.speed_ratio,
            soft_overspeed_active=protection_result.soft_overspeed_active,
            hard_overspeed_active=(
                protection_result.hard_overspeed_active
                or self._critical_fault_transition_pending
            ),
            protection_hard_cutoff_active=(
                protection_result.hard_cutoff_active
                or self._critical_fault_transition_pending
            ),
            critical_protection_fault_request=(
                protection_result.critical_protection_fault_request
                or self._critical_fault_transition_pending
            ),
            protection_arbitration_conflict=(
                protection_result.arbitration_conflict
            ),
            protection_diagnostic_reasons=(
                protection_result.diagnostic_reasons
            ),
            shutdown_fuel_cutoff_active=(
                operating_command.shutdown_fuel_cutoff_active
            ),
            egt_limiter_active=(
                ProtectionDiagnosticReason.EGT_LIMITING
                in protection_result.diagnostic_reasons
            ),
            automatic_sensor_fault_request_active=(
                sensor_fault_response.automatic_fault_requested
                or self._automatic_fault_transition_reason is not None
            ),
            sensor_fault_response_reason=(
                sensor_fault_response.reason.value
                if sensor_fault_response.automatic_fault_requested
                else (
                    self._automatic_fault_transition_reason.value
                    if self._automatic_fault_transition_reason is not None
                    else SensorFaultResponseReason.NONE.value
                )
            ),
            fuel_cutoff_due_to_sensor_invalidity=(
                sensor_fault_response.fuel_cutoff_required
                or self._automatic_fault_transition_reason is not None
            ),
            rotor_speed_sensor_sample_period_s=self._task_period_s(
                SENSOR_TASK
            ),
            exhaust_temperature_sensor_sample_period_s=self._task_period_s(
                SENSOR_TASK
            ),
            scheduler_schema_version=SCHEDULER_SCHEMA_VERSION,
            scheduler_preset=self.scheduler_config.preset_name,
            scheduler_tick=context.current_tick,
            scheduler_base_tick_s=self.scheduler_config.base_tick_s,
            scheduler_tasks_executed_current_tick=current_tick_tasks,
            scheduler_missed_release_count=sum(
                task.missed_release_count
                for task in scheduler_diagnostics.values()
            ),
            sensor_execution_count=scheduler_diagnostics[
                SENSOR_TASK
            ].execution_count,
            validation_execution_count=scheduler_diagnostics[
                VALIDATION_TASK
            ].execution_count,
            controller_execution_count=scheduler_diagnostics[
                CONTROLLER_TASK
            ].execution_count,
            protection_execution_count=scheduler_diagnostics[
                PROTECTION_TASK
            ].execution_count,
            state_machine_execution_count=scheduler_diagnostics[
                STATE_MACHINE_TASK
            ].execution_count,
            plant_model_id=plant_diagnostics.model_id,
            plant_display_name=plant_diagnostics.display_name,
            plant_model_version=plant_diagnostics.model_version,
            ambient_temperature_c=self.ambient_conditions.temperature_c,
            ambient_pressure_pa=self.ambient_conditions.pressure_pa,
            plant_time_s=plant_diagnostics.model_time_s,
            plant_step_count=plant_diagnostics.step_count,
            plant_diagnostics=plant_diagnostics.pathsim,
        )
        self._previous_throttle_demand = throttle_demand
        self._previous_operating_state_for_snapshot = operating_command.state
        self._clear_snapshot_request_flags()
        for sink in tuple(self._snapshot_sinks):
            sink.publish(self._snapshot)

    def _event_monitor_task(self, _context: TaskExecutionContext) -> None:
        """Detect meaningful transitions only at the configured monitor rate."""

        self.event_monitor.observe(self._snapshot)

    def _telemetry_task(self, _context: TaskExecutionContext) -> None:
        """Publish held snapshot rows only at the configured telemetry rate."""

        for sink in tuple(self._telemetry_sinks):
            publish_scheduled = getattr(sink, "publish_scheduled", None)
            if callable(publish_scheduled):
                publish_scheduled(self._snapshot)
            else:
                sink.publish(self._snapshot)

    def _dashboard_task(self, _context: TaskExecutionContext) -> None:
        """Publish a held snapshot without coupling UI refresh to control."""

        for sink in tuple(self._dashboard_sinks):
            sink.publish(self._snapshot)

    def _latched_operation_request(self) -> EngineOperationRequest:
        """Return the persistent throttle and currently latched one-shots."""

        return EngineOperationRequest(
            throttle_command=self._held_throttle_demand,
            startup_requested=self._latched_startup_requested,
            shutdown_requested=self._latched_shutdown_requested,
            fault_requested=self._latched_fault_requested,
            reset_requested=self._latched_reset_requested,
        )

    def _snapshot_operation_request(self) -> EngineOperationRequest:
        """Return commands accumulated since the previous publication."""

        return EngineOperationRequest(
            throttle_command=self._held_throttle_demand,
            startup_requested=self._snapshot_startup_requested,
            shutdown_requested=self._snapshot_shutdown_requested,
            fault_requested=self._snapshot_fault_requested,
            reset_requested=self._snapshot_reset_requested,
        )

    def _clear_snapshot_request_flags(self) -> None:
        self._snapshot_startup_requested = False
        self._snapshot_shutdown_requested = False
        self._snapshot_fault_requested = False
        self._snapshot_reset_requested = False

    def _task_period_s(self, task_name: str) -> float:
        definition = self.scheduler_config.task(task_name)
        return definition.period_ticks * self.scheduler_config.base_tick_s

    @staticmethod
    def _initial_validation_result(
        sensor_data: SensorData,
    ) -> SensorValidationResult:
        rotor_result = ChannelValidationResult(
            value=sensor_data.rotor_speed_rpm,
            health=ChannelHealth.VALID,
            diagnostic_reason=ChannelDiagnosticReason.NONE,
            value_is_held=False,
        )
        egt_result = ChannelValidationResult(
            value=sensor_data.exhaust_temperature_c,
            health=ChannelHealth.VALID,
            diagnostic_reason=ChannelDiagnosticReason.NONE,
            value_is_held=False,
        )
        return SensorValidationResult(
            sensor_data=ValidatedSensorData(
                rotor_speed_rpm=sensor_data.rotor_speed_rpm,
                exhaust_temperature_c=sensor_data.exhaust_temperature_c,
            ),
            rotor_speed=rotor_result,
            exhaust_temperature=egt_result,
            aggregate_health=ChannelHealth.VALID,
        )

    def _requested_actuator_command(
        self,
        operating_command: EngineOperatingCommand,
        sensor_data: ValidatedSensorData,
        time_step_s: float,
    ) -> ActuatorCommand:
        """Calculate the requested command for the current operating mode."""

        if operating_command.speed_control_enabled:
            complete_sensor_data = self._required_sensor_data(sensor_data)
            controller_command = self.speed_controller.update(
                control_request=ControlRequest(
                    throttle_command=(
                        operating_command.effective_throttle_command
                    )
                ),
                sensor_data=complete_sensor_data,
                time_step_s=time_step_s,
            )
            fuel_command = controller_command.fuel_command
        else:
            fuel_command = operating_command.open_loop_fuel_command

        return ActuatorCommand(
            fuel_command=fuel_command,
            starter_commanded=operating_command.starter_commanded,
            ignition_commanded=operating_command.ignition_commanded,
            fuel_enabled=operating_command.fuel_enabled,
        )

    def _protected_actuator_command(
        self,
        requested_command: ActuatorCommand,
        operating_command: EngineOperatingCommand,
        sensor_data: ValidatedSensorData,
        sensor_critical_condition: bool,
        time_step_s: float,
    ) -> tuple[ActuatorCommand, ProtectionResult]:
        """Apply the centralized protection manager to requested fuel."""

        protection_result = self.protection_manager.apply(
            requested_fuel_command=requested_command.fuel_command,
            sensor_data=sensor_data,
            context=ProtectionContext(
                operating_state=operating_command.state,
                fuel_enabled=operating_command.fuel_enabled,
                sensor_critical_condition=sensor_critical_condition,
            ),
            time_step_s=time_step_s,
        )
        return (
            ActuatorCommand(
                fuel_command=protection_result.final_fuel_command,
                starter_commanded=requested_command.starter_commanded,
                ignition_commanded=requested_command.ignition_commanded,
                fuel_enabled=requested_command.fuel_enabled,
            ),
            protection_result,
        )

    @staticmethod
    def _required_sensor_data(
        sensor_data: ValidatedSensorData,
    ) -> SensorData:
        """Return complete validated data or reject unsafe controller use."""

        if (
            sensor_data.rotor_speed_rpm is None
            or sensor_data.exhaust_temperature_c is None
        ):
            raise RuntimeError(
                "complete validated sensor data is required for closed-loop control"
            )
        return SensorData(
            rotor_speed_rpm=sensor_data.rotor_speed_rpm,
            exhaust_temperature_c=sensor_data.exhaust_temperature_c,
        )

    @staticmethod
    def _measurement_error(
        measured_value: float | None,
        true_value: float,
    ) -> float | None:
        """Return a simulation-only truth comparison when measurement exists."""

        if measured_value is None:
            return None
        return measured_value - true_value

    def _speed_setpoint_rpm(
        self,
        operating_command: EngineOperatingCommand,
    ) -> float:
        """Return the scheduled setpoint when speed control is enabled."""

        if not operating_command.speed_control_enabled:
            return 0.0

        return self.speed_controller.scheduler.get_speed_setpoint_rpm(
            operating_command.effective_throttle_command
        )

    def _latest_operator_command(
        self,
        request: EngineOperationRequest,
        throttle_demand: float,
    ) -> str:
        """Return a stable description of meaningful input on this step."""

        commands: list[str] = []
        if request.startup_requested:
            commands.append("start")
        if request.shutdown_requested:
            commands.append("shutdown")
        if request.fault_requested:
            commands.append("fault")
        if request.reset_requested:
            commands.append("reset")
        if abs(throttle_demand - self._previous_throttle_demand) > 1.0e-12:
            commands.append("throttle")
        return ",".join(commands) or "none"

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(value, maximum))

    def _initial_snapshot(self) -> EngineSimulationSnapshot:
        """Create the safe initial OFF-state snapshot."""

        protection_result = self.protection_manager.last_result
        plant_diagnostics = self.engine_model.get_diagnostics()
        return SimulationSnapshot(
            telemetry_schema_version=TELEMETRY_SCHEMA_VERSION,
            simulation_time_s=0.0,
            step_index=0,
            time_step_s=0.0,
            snapshot_sequence_number=0,
            startup_requested=False,
            shutdown_requested=False,
            reset_requested=False,
            fault_requested=False,
            throttle_demand=0.0,
            latest_operator_command="none",
            previous_operating_state=EngineOperatingState.OFF,
            operating_state=EngineOperatingState.OFF,
            state_duration_s=0.0,
            start_elapsed_s=0.0,
            start_timeout_triggered=False,
            starter_commanded=False,
            ignition_commanded=False,
            speed_control_enabled=False,
            fuel_enabled=False,
            throttle_command=0.0,
            speed_setpoint_rpm=0.0,
            speed_error_rpm=None,
            requested_fuel_command=0.0,
            rotor_speed_rpm=self.engine_model.state.rotor_speed_rpm,
            exhaust_temperature_c=self.engine_model.state.exhaust_temperature_c,
            estimated_thrust_n=0.0,
            estimated_fuel_flow_ml_min=0.0,
            measured_rotor_speed_rpm=self.engine_model.state.rotor_speed_rpm,
            validated_rotor_speed_rpm=self.engine_model.state.rotor_speed_rpm,
            rotor_speed_measurement_error_rpm=0.0,
            rotor_speed_health=ChannelHealth.VALID,
            rotor_speed_diagnostic_reason=ChannelDiagnosticReason.NONE,
            rotor_speed_value_is_held=False,
            rotor_speed_fault="none",
            rotor_speed_fault_type="none",
            rotor_speed_fault_parameters=(),
            measured_exhaust_temperature_c=(
                self.engine_model.state.exhaust_temperature_c
            ),
            validated_exhaust_temperature_c=(
                self.engine_model.state.exhaust_temperature_c
            ),
            exhaust_temperature_measurement_error_c=0.0,
            exhaust_temperature_health=ChannelHealth.VALID,
            exhaust_temperature_diagnostic_reason=(
                ChannelDiagnosticReason.NONE
            ),
            exhaust_temperature_value_is_held=False,
            exhaust_temperature_fault="none",
            exhaust_temperature_fault_type="none",
            exhaust_temperature_fault_parameters=(),
            fuel_delivery_fault_active=False,
            aggregate_sensor_health=ChannelHealth.VALID,
            rotor_speed_sensor_sample_period_s=(
                self._task_period_s(SENSOR_TASK)
            ),
            exhaust_temperature_sensor_sample_period_s=(
                self._task_period_s(SENSOR_TASK)
            ),
            scheduler_schema_version=SCHEDULER_SCHEMA_VERSION,
            scheduler_preset=self.scheduler_config.preset_name,
            scheduler_tick=0,
            scheduler_base_tick_s=self.scheduler_config.base_tick_s,
            scheduler_tasks_executed_current_tick=(),
            scheduler_missed_release_count=0,
            sensor_execution_count=0,
            validation_execution_count=0,
            controller_execution_count=0,
            protection_execution_count=0,
            state_machine_execution_count=0,
            allowed_fuel_command=0.0,
            egt_fuel_limit=protection_result.egt_fuel_limit,
            egt_intervention_temperature_c=(
                self.egt_limiter.parameters.intervention_exhaust_temperature_c
            ),
            egt_maximum_temperature_c=(
                self.egt_limiter.parameters.maximum_exhaust_temperature_c
            ),
            acceleration_fuel_limit=(
                protection_result.acceleration_fuel_limit
            ),
            overspeed_fuel_limit=protection_result.overspeed_fuel_limit,
            deceleration_minimum_fuel_command=(
                protection_result.deceleration_minimum_fuel_command
            ),
            state_maximum_fuel_command=(
                protection_result.state_maximum_fuel_command
            ),
            active_protection_limiter=protection_result.active_limiter,
            constraining_protection_limiters=(
                protection_result.constraining_limiters
            ),
            protection_diagnostic_reasons=(
                protection_result.diagnostic_reasons
            ),
            rotor_acceleration_rpm_per_s=(
                protection_result.rotor_acceleration_rpm_per_s
            ),
            rotor_deceleration_rpm_per_s=(
                protection_result.rotor_deceleration_rpm_per_s
            ),
            speed_ratio=protection_result.speed_ratio,
            soft_overspeed_active=(
                protection_result.soft_overspeed_active
            ),
            hard_overspeed_active=(
                protection_result.hard_overspeed_active
            ),
            protection_hard_cutoff_active=(
                protection_result.hard_cutoff_active
            ),
            critical_protection_fault_request=(
                protection_result.critical_protection_fault_request
            ),
            protection_arbitration_conflict=(
                protection_result.arbitration_conflict
            ),
            shutdown_fuel_cutoff_active=False,
            egt_limiter_active=False,
            automatic_sensor_fault_request_active=False,
            sensor_fault_response_reason=SensorFaultResponseReason.NONE.value,
            fuel_cutoff_due_to_sensor_invalidity=False,
            plant_model_id=plant_diagnostics.model_id,
            plant_display_name=plant_diagnostics.display_name,
            plant_model_version=plant_diagnostics.model_version,
            ambient_temperature_c=self.ambient_conditions.temperature_c,
            ambient_pressure_pa=self.ambient_conditions.pressure_pa,
            plant_time_s=plant_diagnostics.model_time_s,
            plant_step_count=plant_diagnostics.step_count,
            plant_diagnostics=plant_diagnostics.pathsim,
        )
