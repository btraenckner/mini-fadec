"""End-to-end tests for structured, reproducible run artifacts."""

import csv
from datetime import datetime, timezone
from pathlib import Path

from simulation.application.engine_simulation import EngineSimulationCoordinator
from simulation.application.simulation_service import SimulationService
from simulation.operation.engine_state import EngineOperatingState
from simulation.protection.types import ProtectionLimiter
from simulation.sensors.fault_injection import (
    DriftSensorFault,
    DropoutSensorFault,
    SensorChannel,
)
from simulation.sensors.sensor_model import (
    ConfigurableSensorModel,
    ExhaustTemperatureSensorConfiguration,
    RotorSpeedSensorConfiguration,
    SensorModelConfiguration,
)
from simulation.telemetry.events import EventType
from simulation.telemetry.metadata import GitMetadata
from simulation.telemetry.recorder import RunRecorder, RunRecorderParameters


def _zero_noise_coordinator() -> EngineSimulationCoordinator:
    return EngineSimulationCoordinator(
        sensor_model=ConfigurableSensorModel(
            SensorModelConfiguration(
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
    )


def _service(base_directory: Path) -> SimulationService:
    recorder = RunRecorder(
        RunRecorderParameters(
            base_directory=base_directory,
            telemetry_sampling_period_s=0.05,
        ),
        wall_clock=lambda: datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc),
        git_metadata_provider=lambda _: GitMetadata(),
    )
    return SimulationService(
        coordinator=_zero_noise_coordinator(),
        recorder=recorder,
        time_step_s=0.01,
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as csv_file:
        return list(csv.DictReader(csv_file))


def _advance_to_idle(service: SimulationService) -> None:
    service.request_start()
    for _ in range(1_000):
        if service.step().operating_state is EngineOperatingState.IDLE:
            return
    raise AssertionError("engine did not reach IDLE")


def _advance_to_running(
    service: SimulationService,
    throttle_demand: float,
) -> None:
    _advance_to_idle(service)
    for _ in range(10):
        service.step()
    service.set_throttle(throttle_demand)
    for _ in range(1_000):
        if service.step().operating_state is EngineOperatingState.RUNNING:
            return
    raise AssertionError("engine did not reach RUNNING")


def _record_complete_lifecycle(base_directory: Path) -> tuple[
    list[dict[str, str]],
    list[dict[str, str]],
    EngineOperatingState,
]:
    service = _service(base_directory)
    run_directory = service.start_recording("normal_lifecycle")
    _advance_to_idle(service)
    for _ in range(10):
        service.step()

    service.add_marker("large throttle step")
    service.set_throttle(1.0)
    limiter_observed = False
    egt_limit_observed = False
    for _ in range(1_500):
        snapshot = service.step()
        limiter_observed = limiter_observed or (
            ProtectionLimiter.ACCELERATION
            in snapshot.constraining_protection_limiters
        )
        egt_limit_observed = egt_limit_observed or snapshot.egt_limiter_active
        if (
            snapshot.operating_state is EngineOperatingState.RUNNING
            and limiter_observed
            and egt_limit_observed
            and snapshot.rotor_speed_rpm > 50_000.0
        ):
            break
    else:
        raise AssertionError("expected protection activity was not observed")

    service.request_shutdown()
    for _ in range(2_000):
        snapshot = service.step()
        if snapshot.operating_state is EngineOperatingState.OFF:
            break
    else:
        raise AssertionError("engine did not complete shutdown")

    service.stop_recording()
    return (
        _read_csv(run_directory / "telemetry.csv"),
        _read_csv(run_directory / "events.csv"),
        service.get_latest_snapshot().operating_state,
    )


def test_normal_lifecycle_protection_and_events_are_recorded(
    tmp_path: Path,
) -> None:
    telemetry, events, final_state = _record_complete_lifecycle(tmp_path)

    sampled_states = {row["operating_state"] for row in telemetry}
    transition_states = [
        row["new_value"].strip('"')
        for row in events
        if row["event_type"] == EventType.ENGINE_STATE_CHANGED.value
    ]
    event_types = {row["event_type"] for row in events}

    assert sampled_states >= {
        "OFF",
        "CRANKING",
        "IGNITION",
        "IDLE",
        "RUNNING",
        "SHUTDOWN",
    }
    assert transition_states == [
        "CRANKING",
        "IGNITION",
        "IDLE",
        "RUNNING",
        "SHUTDOWN",
        "OFF",
    ]
    assert EventType.LIMITER_ACTIVATED.value in event_types
    assert EventType.USER_MARKER.value in event_types
    assert any(
        float(row["egt_fuel_limit"])
        < float(row["requested_fuel_command"])
        for row in telemetry
    )
    assert all(
        0.0 <= float(row["allowed_fuel_command"]) <= 1.0
        for row in telemetry
    )
    assert final_state is EngineOperatingState.OFF


def test_identical_runs_have_equivalent_telemetry_and_event_sequences(
    tmp_path: Path,
) -> None:
    first = _record_complete_lifecycle(tmp_path / "first")
    second = _record_complete_lifecycle(tmp_path / "second")

    assert first == second


def test_sensor_fault_records_health_cutoff_and_automatic_fault(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    run_directory = service.start_recording("sensor_fault")
    _advance_to_running(service, throttle_demand=0.5)
    service.inject_sensor_fault(
        SensorChannel.ROTOR_SPEED,
        DropoutSensorFault(),
    )
    fault_snapshot = service.step()
    service.stop_recording()

    event_types = {
        row["event_type"]
        for row in _read_csv(run_directory / "events.csv")
    }
    assert fault_snapshot.operating_state is EngineOperatingState.FAULT
    assert EventType.SENSOR_FAULT_INJECTED.value in event_types
    assert EventType.SENSOR_HEALTH_CHANGED.value in event_types
    assert EventType.AUTOMATIC_FAULT_REQUESTED.value in event_types
    assert EventType.SAFETY_FUEL_CUTOFF.value in event_types


def test_hard_overspeed_records_intervention_cutoff_and_fault(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    run_directory = service.start_recording("hard_overspeed")
    _advance_to_running(service, throttle_demand=0.6)
    for _ in range(600):
        service.step()
    service.inject_sensor_fault(
        SensorChannel.ROTOR_SPEED,
        DriftSensorFault(rate_per_second=8_000.0),
    )
    for _ in range(1_500):
        snapshot = service.step()
        if snapshot.operating_state is EngineOperatingState.FAULT:
            break
    else:
        raise AssertionError("hard overspeed did not request FAULT")
    service.stop_recording()

    event_types = {
        row["event_type"]
        for row in _read_csv(run_directory / "events.csv")
    }
    assert EventType.SOFT_OVERSPEED_ACTIVATED.value in event_types
    assert EventType.HARD_OVERSPEED_ACTIVATED.value in event_types
    assert EventType.CRITICAL_PROTECTION_REQUESTED.value in event_types
    assert EventType.SAFETY_FUEL_CUTOFF.value in event_types
    assert EventType.AUTOMATIC_FAULT_REQUESTED.value in event_types
