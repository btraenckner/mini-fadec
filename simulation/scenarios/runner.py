"""Deterministic unpaced scenario execution through the application service."""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from simulation.application.engine_simulation import EngineSimulationCoordinator
from simulation.application.simulation_service import SimulationService
from simulation.scenarios.actions import (
    ActionExecutionStatus,
    ActionResult,
    ScenarioAction,
)
from simulation.scenarios.conditions import ConditionContext
from simulation.scenarios.definitions import Scenario
from simulation.scenarios.triggers import WhenConditionTrigger
from simulation.sensors.fault_injection import SensorFaultInjector
from simulation.sensors.sensor_model import (
    ConfigurableSensorModel,
    SensorModelConfiguration,
)
from simulation.telemetry.events import SimulationEvent
from simulation.telemetry.recorder import RunRecorder, RunRecorderParameters
from simulation.telemetry.snapshot import SimulationSnapshot
from simulation.verification.report import write_verification_artifacts
from simulation.verification.requirements import (
    EvaluationContext,
    RequirementStatus,
)
from simulation.verification.results import (
    RequirementResult,
    ScenarioOverallStatus,
    ScenarioResult,
    evaluate_requirements,
    requirement_failure_impacts_scenario,
)


class ScenarioExecutionState(Enum):
    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class ScenarioProgress:
    """Immutable dashboard-ready view of scenario execution progress."""

    scenario_id: str
    current_simulation_time_s: float
    maximum_duration_s: float
    execution_state: ScenarioExecutionState
    current_engine_state: str
    completed_action_count: int
    pending_action_count: int
    failed_action_count: int
    current_recording_directory: Path | None
    latest_snapshot: SimulationSnapshot
    recent_events: tuple[SimulationEvent, ...]
    action_results: tuple[ActionResult, ...]
    partial_requirement_status: tuple[tuple[str, RequirementStatus], ...]


ServiceFactory = Callable[[Scenario], SimulationService]


class ScenarioRunner:
    """Execute one isolated scenario using simulation time as the only clock."""

    def __init__(
        self,
        service_factory: ServiceFactory | None = None,
        *,
        paced: bool = False,
        sleeper: Callable[[float], None] = time.sleep,
        performance_clock: Callable[[], float] = time.perf_counter,
        wall_clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._service_factory = service_factory or _default_service_factory
        self._paced = paced
        self._sleeper = sleeper
        self._performance_clock = performance_clock
        self._wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        self._scenario: Scenario | None = None
        self._service: SimulationService | None = None
        self._execution_state = ScenarioExecutionState.NOT_STARTED
        self._action_results: dict[str, ActionResult] = {}
        self._snapshots: list[SimulationSnapshot] = []
        self._events: list[SimulationEvent] = []
        self._last_event_sequence = 0
        self._run_directory: Path | None = None
        self._start_performance_time: float | None = None
        self._result: ScenarioResult | None = None
        self._exception_details: str | None = None

    @property
    def result(self) -> ScenarioResult | None:
        """Return the final typed result after controlled termination."""

        return self._result

    def prepare_scenario(self, scenario: Scenario) -> ScenarioProgress:
        """Create a fresh application composition and prepare one isolated run."""

        if self._execution_state is ScenarioExecutionState.RUNNING:
            raise RuntimeError("a scenario is already running")
        self._scenario = scenario
        self._service = self._service_factory(scenario)
        self._execution_state = ScenarioExecutionState.RUNNING
        self._action_results = {
            action.action_id: ActionResult(
                action_id=action.action_id,
                description=action.description,
                action_type=type(action).__name__,
                status=ActionExecutionStatus.PENDING,
                required_success=action.required_success,
            )
            for action in scenario.actions
        }
        self._snapshots = [self._service.get_latest_snapshot()]
        self._events = []
        self._last_event_sequence = 0
        self._run_directory = None
        self._result = None
        self._exception_details = None
        self._start_performance_time = self._performance_clock()

        try:
            if scenario.recording.enabled:
                run_name = scenario.recording.run_name or scenario.name
                self._run_directory = self._service.start_recording(run_name)
            self._capture_new_events()
            self._evaluate_due_actions()
            self._capture_new_events()
            self._check_termination()
        except Exception as error:
            self._fail_execution(error)
        return self.get_scenario_progress()

    def step_scenario(self) -> ScenarioProgress:
        """Advance one fixed step, execute due actions, and update progress."""

        if self._scenario is None or self._service is None:
            raise RuntimeError("no scenario has been prepared")
        if self._execution_state is not ScenarioExecutionState.RUNNING:
            return self.get_scenario_progress()

        try:
            self._evaluate_due_actions()
            self._capture_new_events()
            self._check_termination()
            if self._execution_state is ScenarioExecutionState.RUNNING:
                snapshot = self._service.step()
                self._snapshots.append(snapshot)
                self._capture_new_events()
                self._evaluate_due_actions()
                self._capture_new_events()
                self._check_termination()
                if (
                    self._paced
                    and self._execution_state is ScenarioExecutionState.RUNNING
                ):
                    self._sleeper(self._service.time_step_s)
        except Exception as error:
            self._fail_execution(error)
        return self.get_scenario_progress()

    def run_scenario(self, scenario: Scenario) -> ScenarioResult:
        """Run to controlled termination without terminal I/O or default pacing."""

        self.prepare_scenario(scenario)
        while self._execution_state is ScenarioExecutionState.RUNNING:
            self.step_scenario()
        if self._result is None:
            self._finalize_result()
        assert self._result is not None
        return self._result

    def cancel_scenario(self) -> ScenarioResult:
        """Cancel the active scenario and safely finalize recording and reports."""

        if self._scenario is None or self._service is None:
            raise RuntimeError("no scenario has been prepared")
        if self._execution_state is ScenarioExecutionState.RUNNING:
            self._execution_state = ScenarioExecutionState.CANCELLED
            self._mark_pending_actions(ActionExecutionStatus.SKIPPED)
            self._finalize_result()
        assert self._result is not None
        return self._result

    def get_scenario_progress(self) -> ScenarioProgress:
        """Return a defensive immutable progress snapshot for clients."""

        if self._scenario is None or self._service is None or not self._snapshots:
            raise RuntimeError("no scenario has been prepared")
        action_results = self._ordered_action_results()
        status = self._service.get_recording_status()
        partial = (
            tuple(
                (result.requirement_id, result.status)
                for result in self._result.requirement_results
            )
            if self._result is not None
            else tuple(
                (requirement.requirement_id, RequirementStatus.NOT_EVALUATED)
                for requirement in self._scenario.requirements
            )
        )
        return ScenarioProgress(
            scenario_id=self._scenario.scenario_id,
            current_simulation_time_s=self._snapshots[-1].simulation_time_s,
            maximum_duration_s=self._scenario.max_duration_s,
            execution_state=self._execution_state,
            current_engine_state=self._snapshots[-1].operating_state.value,
            completed_action_count=sum(
                result.status is ActionExecutionStatus.EXECUTED
                for result in action_results
            ),
            pending_action_count=sum(
                result.status is ActionExecutionStatus.PENDING
                for result in action_results
            ),
            failed_action_count=sum(
                result.status
                in {ActionExecutionStatus.FAILED, ActionExecutionStatus.TIMED_OUT}
                for result in action_results
            ),
            current_recording_directory=(
                status.run_directory
                if status is not None and self._service.recorder.is_recording
                else None
            ),
            latest_snapshot=self._snapshots[-1],
            recent_events=tuple(self._events[-50:]),
            action_results=action_results,
            partial_requirement_status=partial,
        )

    def _evaluate_due_actions(self) -> None:
        assert self._scenario is not None
        assert self._service is not None
        made_progress = True
        while made_progress and self._execution_state is ScenarioExecutionState.RUNNING:
            made_progress = False
            context = self._condition_context()
            for action in self._scenario.actions:
                current_result = self._action_results[action.action_id]
                if current_result.status is not ActionExecutionStatus.PENDING:
                    continue
                current_time_s = context.latest_snapshot.simulation_time_s
                if self._action_timed_out(action, current_time_s):
                    self._action_results[action.action_id] = ActionResult(
                        action_id=action.action_id,
                        description=action.description,
                        action_type=type(action).__name__,
                        status=ActionExecutionStatus.TIMED_OUT,
                        required_success=action.required_success,
                        execution_time_s=current_time_s,
                        message=(
                            f"Trigger {type(action.trigger).__name__} timed out at "
                            f"{current_time_s:.3f} s; latest state "
                            f"{context.latest_snapshot.operating_state.value}"
                        ),
                        diagnostic_code="ACTION_TRIGGER_TIMEOUT",
                    )
                    made_progress = True
                    if action.required_success:
                        self._execution_state = ScenarioExecutionState.FAILED
                        self._finalize_result()
                        return
                    continue
                if not action.trigger.is_due(context):
                    continue
                self._execute_action(action, current_time_s)
                self._capture_new_events()
                context = self._condition_context()
                made_progress = True
                if self._execution_state is not ScenarioExecutionState.RUNNING:
                    return

    def _execute_action(
        self,
        action: ScenarioAction,
        current_time_s: float,
    ) -> None:
        assert self._service is not None
        try:
            message = action.execute(self._service)
        except Exception as error:
            self._action_results[action.action_id] = ActionResult(
                action_id=action.action_id,
                description=action.description,
                action_type=type(action).__name__,
                status=ActionExecutionStatus.FAILED,
                required_success=action.required_success,
                execution_time_s=current_time_s,
                message=f"{type(error).__name__}: {error}",
                diagnostic_code="ACTION_EXECUTION_ERROR",
            )
            if action.required_success:
                self._execution_state = ScenarioExecutionState.FAILED
                self._exception_details = (
                    f"Required action {action.action_id} failed: "
                    f"{type(error).__name__}: {error}"
                )
                self._finalize_result()
            return
        self._action_results[action.action_id] = ActionResult(
            action_id=action.action_id,
            description=action.description,
            action_type=type(action).__name__,
            status=ActionExecutionStatus.EXECUTED,
            required_success=action.required_success,
            execution_time_s=current_time_s,
            message=message,
        )

    def _action_timed_out(
        self,
        action: ScenarioAction,
        current_time_s: float,
    ) -> bool:
        trigger_timeout = (
            action.trigger.timeout_s
            if isinstance(action.trigger, WhenConditionTrigger)
            else None
        )
        deadlines = tuple(
            deadline
            for deadline in (trigger_timeout, action.timeout_s)
            if deadline is not None
        )
        if not deadlines:
            return False
        deadline = min(deadlines)
        tolerance_s = 1.0e-12 * max(1.0, current_time_s, deadline)
        return current_time_s > deadline + tolerance_s

    def _check_termination(self) -> None:
        if self._execution_state is not ScenarioExecutionState.RUNNING:
            return
        assert self._scenario is not None
        current_time_s = self._snapshots[-1].simulation_time_s
        if current_time_s + 1.0e-12 >= self._scenario.max_duration_s:
            self._execution_state = ScenarioExecutionState.TIMED_OUT
            self._mark_pending_actions(ActionExecutionStatus.TIMED_OUT)
            self._finalize_result()
            return
        actions_complete = all(
            result.status is not ActionExecutionStatus.PENDING
            for result in self._action_results.values()
        )
        terminal_condition_met = (
            self._scenario.expected_terminal_condition is None
            or self._scenario.expected_terminal_condition.evaluate(
                self._condition_context()
            )
        )
        if actions_complete and terminal_condition_met:
            self._execution_state = ScenarioExecutionState.COMPLETED
            self._finalize_result()

    def _condition_context(self) -> ConditionContext:
        return ConditionContext(
            latest_snapshot=self._snapshots[-1],
            snapshots=tuple(self._snapshots),
            recent_events=tuple(self._events),
            action_results=self._action_results,
        )

    def _capture_new_events(self) -> None:
        assert self._service is not None
        for event in self._service.get_recent_events():
            if event.event_sequence <= self._last_event_sequence:
                continue
            self._events.append(event)
            self._last_event_sequence = event.event_sequence

    def _fail_execution(self, error: Exception) -> None:
        self._execution_state = ScenarioExecutionState.FAILED
        self._exception_details = f"{type(error).__name__}: {error}"
        self._mark_pending_actions(ActionExecutionStatus.SKIPPED)
        self._finalize_result()

    def _mark_pending_actions(self, status: ActionExecutionStatus) -> None:
        current_time_s = self._snapshots[-1].simulation_time_s
        for action_id, result in tuple(self._action_results.items()):
            if result.status is not ActionExecutionStatus.PENDING:
                continue
            self._action_results[action_id] = ActionResult(
                action_id=result.action_id,
                description=result.description,
                action_type=result.action_type,
                status=status,
                required_success=result.required_success,
                execution_time_s=current_time_s,
                message=(
                    "Scenario duration expired before trigger"
                    if status is ActionExecutionStatus.TIMED_OUT
                    else "Action skipped after scenario termination"
                ),
                diagnostic_code=(
                    "SCENARIO_TIMEOUT"
                    if status is ActionExecutionStatus.TIMED_OUT
                    else "SCENARIO_TERMINATED"
                ),
            )

    def _finalize_result(self) -> None:
        if self._result is not None:
            return
        assert self._scenario is not None
        assert self._service is not None
        self._capture_new_events()
        recording_error: str | None = None
        try:
            existing_recording = self._service.get_recording_status()
            if existing_recording is not None:
                self._run_directory = existing_recording.run_directory
            elif self._run_directory is None:
                # Verification reports always need an isolated artifact
                # directory. When automatic recording was disabled and no
                # action started it, create a final diagnostic sample through
                # the existing recorder instead of duplicating CSV logic.
                self._run_directory = self._service.start_recording(
                    f"scenario_{self._scenario.name}_diagnostics"
                )
                self._capture_new_events()
            status = self._service.stop_recording(
                completed=self._execution_state
                is ScenarioExecutionState.COMPLETED
            )
            if status is not None:
                self._run_directory = status.run_directory
            self._capture_new_events()
        except Exception as error:
            recording_error = f"{type(error).__name__}: {error}"
            self._service.close(completed=False)

        evaluation_context = EvaluationContext(
            snapshots=tuple(self._snapshots),
            events=tuple(self._events),
            action_results=self._action_results,
            time_step_s=self._service.time_step_s,
        )
        requirement_results = evaluate_requirements(
            self._scenario.requirements,
            evaluation_context,
        )
        overall_status = self._overall_status(requirement_results)
        if recording_error is not None:
            overall_status = ScenarioOverallStatus.FAIL
            self._exception_details = _join_errors(
                self._exception_details,
                f"Recording finalization failed: {recording_error}",
            )

        end_performance_time = self._performance_clock()
        start_performance_time = self._start_performance_time or end_performance_time
        wall_duration_s = max(0.0, end_performance_time - start_performance_time)
        simulation_start_s = self._snapshots[0].simulation_time_s
        simulation_end_s = self._snapshots[-1].simulation_time_s
        simulated_duration_s = simulation_end_s - simulation_start_s
        real_time_factor = (
            simulated_duration_s / wall_duration_s
            if wall_duration_s > 0.0
            else None
        )
        passed_count = sum(
            result.status is RequirementStatus.PASS
            for result in requirement_results
        )
        failed_count = sum(
            result.status in {RequirementStatus.FAIL, RequirementStatus.ERROR}
            for result in requirement_results
        )
        not_evaluated_count = sum(
            result.status
            in {RequirementStatus.NOT_EVALUATED, RequirementStatus.NOT_APPLICABLE}
            for result in requirement_results
        )
        critical_failure_count = sum(
            result.status in {RequirementStatus.FAIL, RequirementStatus.ERROR}
            and result.criticality.value == "CRITICAL"
            for result in requirement_results
        )
        metadata_path = (
            self._run_directory / "metadata.json"
            if self._run_directory is not None
            else None
        )
        telemetry_path = (
            self._run_directory / "telemetry.csv"
            if self._run_directory is not None
            else None
        )
        event_path = (
            self._run_directory / "events.csv"
            if self._run_directory is not None
            else None
        )
        scenario_path = (
            self._run_directory / "scenario.json"
            if self._run_directory is not None
            else None
        )
        requirements_path = (
            self._run_directory / "requirements.json"
            if self._run_directory is not None
            else None
        )
        report_path = (
            self._run_directory / "report.md"
            if self._run_directory is not None
            else None
        )
        summary = (
            f"{overall_status.value}: {passed_count} passed, "
            f"{failed_count} failed, {not_evaluated_count} not evaluated"
        )
        self._result = ScenarioResult(
            scenario_id=self._scenario.scenario_id,
            scenario_name=self._scenario.name,
            overall_status=overall_status,
            execution_status=self._execution_state.value,
            simulation_start_time_s=simulation_start_s,
            simulation_end_time_s=simulation_end_s,
            simulated_duration_s=simulated_duration_s,
            wall_clock_execution_duration_s=wall_duration_s,
            real_time_factor=real_time_factor,
            final_engine_state=self._snapshots[-1].operating_state,
            action_results=self._ordered_action_results(),
            requirement_results=requirement_results,
            passed_requirement_count=passed_count,
            failed_requirement_count=failed_count,
            not_evaluated_requirement_count=not_evaluated_count,
            critical_failure_count=critical_failure_count,
            run_directory=self._run_directory,
            metadata_path=metadata_path,
            telemetry_path=telemetry_path,
            event_path=event_path,
            requirements_path=requirements_path,
            scenario_path=scenario_path,
            report_path=report_path,
            summary=summary,
            exception_details=self._exception_details,
        )
        if self._run_directory is not None:
            try:
                write_verification_artifacts(
                    self._scenario,
                    self._result,
                    self._run_directory,
                    generated_at=self._wall_clock(),
                    git_commit=_metadata_git_commit(metadata_path),
                )
            except Exception as error:
                self._exception_details = _join_errors(
                    self._exception_details,
                    f"Report generation failed: {type(error).__name__}: {error}",
                )
                self._result = replace(
                    self._result,
                    overall_status=ScenarioOverallStatus.FAIL,
                    summary=f"FAIL: report generation failed; {summary}",
                    exception_details=self._exception_details,
                )
        # Authoritative evidence is persisted and attached to the typed result.
        # Retain only the dashboard progress window after final evaluation so a
        # sequence of scenarios cannot accumulate completed-run telemetry.
        self._snapshots = [self._snapshots[-1]]
        self._events = self._events[-50:]

    def _overall_status(
        self,
        requirement_results: tuple[RequirementResult, ...],
    ) -> ScenarioOverallStatus:
        assert self._scenario is not None
        if self._execution_state is ScenarioExecutionState.CANCELLED:
            return ScenarioOverallStatus.CANCELLED
        if self._execution_state is not ScenarioExecutionState.COMPLETED:
            return ScenarioOverallStatus.FAIL
        if any(
            result.required_success
            and result.status
            in {ActionExecutionStatus.FAILED, ActionExecutionStatus.TIMED_OUT}
            for result in self._action_results.values()
        ):
            return ScenarioOverallStatus.FAIL
        results_by_id = {
            result.requirement_id: result for result in requirement_results
        }
        if any(
            requirement_failure_impacts_scenario(
                requirement,
                results_by_id[requirement.requirement_id],
            )
            for requirement in self._scenario.requirements
        ):
            return ScenarioOverallStatus.FAIL
        return ScenarioOverallStatus.PASS

    def _ordered_action_results(self) -> tuple[ActionResult, ...]:
        assert self._scenario is not None
        return tuple(
            self._action_results[action.action_id]
            for action in self._scenario.actions
        )


def run_scenario(scenario: Scenario) -> ScenarioResult:
    """Convenience API for synchronous dashboard or CLI integration."""

    return ScenarioRunner().run_scenario(scenario)


def _default_service_factory(scenario: Scenario) -> SimulationService:
    overrides = dict(scenario.configuration_overrides)
    time_step_s = scenario.time_step_s or 0.01
    random_seed_value = overrides.get("sensor_random_seed", scenario.random_seed)
    random_seed = (
        None if random_seed_value is None else int(random_seed_value)
    )
    sensor_model = ConfigurableSensorModel(
        SensorModelConfiguration(random_seed=random_seed)
    )
    coordinator = EngineSimulationCoordinator(
        sensor_model=sensor_model,
        sensor_fault_injector=SensorFaultInjector(random_seed=random_seed),
    )
    base_directory = Path(
        str(overrides.get("artifact_base_directory", "artifacts/runs"))
    )
    telemetry_sampling_period_s = float(
        overrides.get("telemetry_sampling_period_s", 0.05)
    )
    recorder = RunRecorder(
        RunRecorderParameters(
            base_directory=base_directory,
            telemetry_sampling_period_s=telemetry_sampling_period_s,
        )
    )
    return SimulationService(
        coordinator=coordinator,
        recorder=recorder,
        time_step_s=time_step_s,
    )


def _metadata_git_commit(metadata_path: Path | None) -> str | None:
    if metadata_path is None or not metadata_path.exists():
        return None
    try:
        with metadata_path.open(encoding="utf-8") as metadata_file:
            value = json.load(metadata_file).get("git_commit")
    except (OSError, json.JSONDecodeError, AttributeError):
        return None
    return value if isinstance(value, str) else None


def _join_errors(existing: str | None, additional: str) -> str:
    return additional if existing is None else f"{existing}; {additional}"
