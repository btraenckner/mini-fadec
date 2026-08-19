"""Typed scenario actions routed through the application service boundary."""

import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from simulation.scenarios.triggers import ScenarioTrigger
from simulation.sensors.fault_injection import (
    SensorChannel,
    SensorFaultDefinition,
)
from simulation.telemetry.events import SimulationEvent
from simulation.telemetry.recorder import RunRecordingSummary


class ScenarioControlInterface(Protocol):
    """Narrow application-service surface available to scenario actions."""

    def request_start(self) -> None: ...

    def set_throttle(self, throttle_demand: float) -> float: ...

    def request_shutdown(self) -> None: ...

    def request_fault(self) -> None: ...

    def request_reset(self) -> None: ...

    def inject_sensor_fault(
        self,
        channel: SensorChannel,
        fault: SensorFaultDefinition,
    ) -> None: ...

    def clear_sensor_fault(self, channel: SensorChannel) -> None: ...

    def set_fuel_delivery_fault(self, active: bool) -> None: ...

    def add_marker(self, text: str) -> SimulationEvent: ...

    def start_recording(self, run_name: str | None = None) -> Path: ...

    def stop_recording(
        self,
        *,
        completed: bool = True,
    ) -> RunRecordingSummary | None: ...


class ActionExecutionStatus(Enum):
    """Lifecycle states of one scenario action execution."""

    PENDING = "PENDING"
    EXECUTED = "EXECUTED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"


@dataclass(frozen=True)
class ActionResult:
    """Immutable execution outcome for one scenario action."""

    action_id: str
    description: str
    action_type: str
    status: ActionExecutionStatus
    required_success: bool
    execution_time_s: float | None = None
    message: str = ""
    diagnostic_code: str | None = None

    @property
    def status_name(self) -> str:
        return self.status.value


@dataclass(frozen=True, kw_only=True)
class StartEngineAction:
    action_id: str
    description: str
    trigger: ScenarioTrigger
    required_success: bool = True
    timeout_s: float | None = None

    def execute(self, service: ScenarioControlInterface) -> str:
        service.request_start()
        return "startup requested"


@dataclass(frozen=True, kw_only=True)
class SetThrottleAction:
    action_id: str
    description: str
    trigger: ScenarioTrigger
    throttle_demand: float
    required_success: bool = True
    timeout_s: float | None = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.throttle_demand):
            raise ValueError("throttle demand must be finite")

    def execute(self, service: ScenarioControlInterface) -> str:
        accepted = service.set_throttle(self.throttle_demand)
        return f"throttle set to {accepted:.3f}"


@dataclass(frozen=True, kw_only=True)
class RequestShutdownAction:
    action_id: str
    description: str
    trigger: ScenarioTrigger
    required_success: bool = True
    timeout_s: float | None = None

    def execute(self, service: ScenarioControlInterface) -> str:
        service.request_shutdown()
        return "shutdown requested"


@dataclass(frozen=True, kw_only=True)
class RequestResetAction:
    action_id: str
    description: str
    trigger: ScenarioTrigger
    required_success: bool = True
    timeout_s: float | None = None

    def execute(self, service: ScenarioControlInterface) -> str:
        service.request_reset()
        return "reset requested"


@dataclass(frozen=True, kw_only=True)
class RequestManualFaultAction:
    action_id: str
    description: str
    trigger: ScenarioTrigger
    required_success: bool = True
    timeout_s: float | None = None

    def execute(self, service: ScenarioControlInterface) -> str:
        service.request_fault()
        return "manual fault requested"


@dataclass(frozen=True, kw_only=True)
class InjectSensorFaultAction:
    action_id: str
    description: str
    trigger: ScenarioTrigger
    channel: SensorChannel
    fault: SensorFaultDefinition
    required_success: bool = True
    timeout_s: float | None = None

    def execute(self, service: ScenarioControlInterface) -> str:
        service.inject_sensor_fault(self.channel, self.fault)
        return f"{self.channel.value} sensor fault injected"


@dataclass(frozen=True, kw_only=True)
class ClearSensorFaultAction:
    action_id: str
    description: str
    trigger: ScenarioTrigger
    channel: SensorChannel
    required_success: bool = True
    timeout_s: float | None = None

    def execute(self, service: ScenarioControlInterface) -> str:
        service.clear_sensor_fault(self.channel)
        return f"{self.channel.value} sensor fault cleared"


@dataclass(frozen=True, kw_only=True)
class SetFuelDeliveryFaultAction:
    """Control a simulation-only complete loss of physical fuel delivery."""

    action_id: str
    description: str
    trigger: ScenarioTrigger
    active: bool
    required_success: bool = True
    timeout_s: float | None = None

    def execute(self, service: ScenarioControlInterface) -> str:
        service.set_fuel_delivery_fault(self.active)
        return (
            "fuel-delivery fault injected"
            if self.active
            else "fuel-delivery fault cleared"
        )


@dataclass(frozen=True, kw_only=True)
class AddMarkerAction:
    action_id: str
    description: str
    trigger: ScenarioTrigger
    marker_text: str
    required_success: bool = True
    timeout_s: float | None = None

    def __post_init__(self) -> None:
        if not self.marker_text.strip():
            raise ValueError("marker text cannot be empty")

    def execute(self, service: ScenarioControlInterface) -> str:
        service.add_marker(self.marker_text)
        return "marker recorded"


@dataclass(frozen=True, kw_only=True)
class StartRecordingAction:
    action_id: str
    description: str
    trigger: ScenarioTrigger
    run_name: str | None = None
    required_success: bool = True
    timeout_s: float | None = None

    def execute(self, service: ScenarioControlInterface) -> str:
        run_directory = service.start_recording(self.run_name)
        return f"recording started at {run_directory}"


@dataclass(frozen=True, kw_only=True)
class StopRecordingAction:
    action_id: str
    description: str
    trigger: ScenarioTrigger
    required_success: bool = True
    timeout_s: float | None = None

    def execute(self, service: ScenarioControlInterface) -> str:
        summary = service.stop_recording(completed=True)
        if summary is None:
            raise RuntimeError("no recording is active")
        return "recording stopped"


ScenarioAction = (
    StartEngineAction
    | SetThrottleAction
    | RequestShutdownAction
    | RequestResetAction
    | RequestManualFaultAction
    | InjectSensorFaultAction
    | ClearSensorFaultAction
    | SetFuelDeliveryFaultAction
    | AddMarkerAction
    | StartRecordingAction
    | StopRecordingAction
)


def validate_action_definition(action: ScenarioAction) -> None:
    """Validate common action fields independently from runner state."""

    if not action.action_id.strip():
        raise ValueError("action_id cannot be empty")
    if not action.description.strip():
        raise ValueError(f"action {action.action_id!r} description cannot be empty")
    if action.timeout_s is not None and action.timeout_s <= 0.0:
        raise ValueError(
            f"action {action.action_id!r} timeout_s must be greater than zero"
        )
