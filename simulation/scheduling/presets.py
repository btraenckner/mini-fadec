"""Explicit development timing presets for the Mini-FADEC scheduler."""

from dataclasses import dataclass

from simulation.scheduling.config import SchedulerConfig, task_from_seconds


COMMAND_TASK = "command"
STATE_MACHINE_TASK = "state_machine"
SENSOR_TASK = "sensor"
VALIDATION_TASK = "validation"
CONTROLLER_TASK = "controller"
PROTECTION_TASK = "protection"
ACTUATOR_TASK = "actuator"
PLANT_TASK = "plant"
SNAPSHOT_TASK = "snapshot"
EVENT_MONITOR_TASK = "event_monitor"
TELEMETRY_TASK = "telemetry"
DASHBOARD_TASK = "dashboard"

TASK_PRIORITIES = {
    COMMAND_TASK: 10,
    STATE_MACHINE_TASK: 20,
    SENSOR_TASK: 30,
    VALIDATION_TASK: 40,
    CONTROLLER_TASK: 50,
    PROTECTION_TASK: 60,
    ACTUATOR_TASK: 70,
    PLANT_TASK: 80,
    SNAPSHOT_TASK: 90,
    EVENT_MONITOR_TASK: 100,
    TELEMETRY_TASK: 110,
    DASHBOARD_TASK: 120,
}


@dataclass(frozen=True)
class _PresetPeriods:
    command_s: float
    state_machine_s: float
    sensor_s: float
    validation_s: float
    controller_s: float
    protection_s: float
    actuator_s: float
    plant_s: float
    snapshot_s: float
    event_monitor_s: float
    telemetry_s: float
    dashboard_s: float


def _build_preset(
    name: str,
    periods: _PresetPeriods,
    *,
    mandatory_regression: bool,
    base_tick_s: float = 0.001,
) -> SchedulerConfig:
    period_by_task = (
        (COMMAND_TASK, periods.command_s),
        (STATE_MACHINE_TASK, periods.state_machine_s),
        (SENSOR_TASK, periods.sensor_s),
        (VALIDATION_TASK, periods.validation_s),
        (CONTROLLER_TASK, periods.controller_s),
        (PROTECTION_TASK, periods.protection_s),
        (ACTUATOR_TASK, periods.actuator_s),
        (PLANT_TASK, periods.plant_s),
        (SNAPSHOT_TASK, periods.snapshot_s),
        (EVENT_MONITOR_TASK, periods.event_monitor_s),
        (TELEMETRY_TASK, periods.telemetry_s),
        (DASHBOARD_TASK, periods.dashboard_s),
    )
    return SchedulerConfig(
        preset_name=name,
        base_tick_s=base_tick_s,
        tasks=tuple(
            task_from_seconds(
                name=task_name,
                base_tick_s=base_tick_s,
                period_s=period_s,
                priority=TASK_PRIORITIES[task_name],
            )
            for task_name, period_s in period_by_task
        ),
        mandatory_regression=mandatory_regression,
    )


def single_rate_reference() -> SchedulerConfig:
    """Return the mandatory single-rate behavioral reference preset."""

    base_tick_s = 0.001
    return _build_preset(
        "single-rate",
        _PresetPeriods(
            command_s=base_tick_s,
            state_machine_s=base_tick_s,
            sensor_s=base_tick_s,
            validation_s=base_tick_s,
            controller_s=base_tick_s,
            protection_s=base_tick_s,
            actuator_s=base_tick_s,
            plant_s=base_tick_s,
            snapshot_s=base_tick_s,
            event_monitor_s=base_tick_s,
            telemetry_s=base_tick_s,
            dashboard_s=0.050,
        ),
        mandatory_regression=True,
        base_tick_s=base_tick_s,
    )


def nominal_multirate() -> SchedulerConfig:
    """Return the default unvalidated multi-rate development assumption."""

    return _build_preset(
        "nominal-multirate",
        _PresetPeriods(
            command_s=0.001,
            state_machine_s=0.020,
            sensor_s=0.005,
            validation_s=0.005,
            controller_s=0.010,
            protection_s=0.005,
            actuator_s=0.005,
            plant_s=0.001,
            snapshot_s=0.020,
            event_monitor_s=0.020,
            telemetry_s=0.050,
            dashboard_s=0.050,
        ),
        mandatory_regression=True,
    )


def slow_controller() -> SchedulerConfig:
    """Return an experimental controller-rate sensitivity preset."""

    nominal = nominal_multirate()
    return _replace_periods(
        nominal,
        name="slow-controller",
        replacements={CONTROLLER_TASK: 0.050},
        mandatory_regression=False,
    )


def slow_sensors() -> SchedulerConfig:
    """Return an experimental sensor-latency sensitivity preset."""

    nominal = nominal_multirate()
    return _replace_periods(
        nominal,
        name="slow-sensors",
        replacements={
            SENSOR_TASK: 0.020,
            VALIDATION_TASK: 0.020,
        },
        mandatory_regression=False,
    )


def stress_timing() -> SchedulerConfig:
    """Return an intentionally coarse experimental timing preset."""

    return _build_preset(
        "stress-timing",
        _PresetPeriods(
            command_s=0.001,
            state_machine_s=0.050,
            sensor_s=0.020,
            validation_s=0.020,
            controller_s=0.050,
            protection_s=0.020,
            actuator_s=0.010,
            plant_s=0.001,
            snapshot_s=0.050,
            event_monitor_s=0.050,
            telemetry_s=0.100,
            dashboard_s=0.100,
        ),
        mandatory_regression=False,
    )


def list_scheduler_presets() -> tuple[SchedulerConfig, ...]:
    """Return independent immutable configurations in stable display order."""

    return (
        single_rate_reference(),
        nominal_multirate(),
        slow_controller(),
        slow_sensors(),
        stress_timing(),
    )


def get_scheduler_preset(name: str) -> SchedulerConfig:
    """Return one independently constructed preset by stable name."""

    normalized_name = name.strip().lower()
    for preset in list_scheduler_presets():
        if preset.preset_name == normalized_name:
            return preset
    raise KeyError(f"unknown scheduler preset: {name}")


def _replace_periods(
    source: SchedulerConfig,
    *,
    name: str,
    replacements: dict[str, float],
    mandatory_regression: bool,
) -> SchedulerConfig:
    tasks = tuple(
        task_from_seconds(
            name=task.name,
            base_tick_s=source.base_tick_s,
            period_s=replacements.get(
                task.name,
                task.period_ticks * source.base_tick_s,
            ),
            phase_offset_s=(
                task.phase_offset_ticks * source.base_tick_s
            ),
            priority=task.priority,
            enabled=task.enabled,
        )
        for task in source.tasks
    )
    return SchedulerConfig(
        preset_name=name,
        base_tick_s=source.base_tick_s,
        tasks=tasks,
        execution_convention=source.execution_convention,
        mandatory_regression=mandatory_regression,
    )

