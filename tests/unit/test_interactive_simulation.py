"""Unit tests for interactive simulation command parsing."""

from io import StringIO

import pytest

from simulation.application.interactive_simulation import (
    InteractiveEngineSimulation,
    parse_command,
)
from simulation.operation.state_machine import EngineOperationRequest
from simulation.sensors.fault_injection import SensorChannel


@pytest.mark.parametrize(
    "command_name",
    [
        "help",
        "start",
        "shutdown",
        "status",
        "protection",
        "fault",
        "faults",
        "reset",
        "clear_faults",
        "runs",
        "quit",
    ],
)
def test_parse_command_accepts_commands_without_values(
    command_name: str,
) -> None:
    command = parse_command(command_name)

    assert command.name == command_name
    assert command.value is None


def test_parse_command_accepts_numeric_throttle() -> None:
    command = parse_command("throttle 0.7")

    assert command.name == "throttle"
    assert command.value == pytest.approx(0.7)


@pytest.mark.parametrize(
    ("command_text", "action", "text"),
    [
        ("record start", "start", None),
        ("record start normal_run", "start", "normal_run"),
        ("record stop", "stop", None),
        ("record status", "status", None),
    ],
)
def test_parse_command_accepts_recording_commands(
    command_text: str,
    action: str,
    text: str | None,
) -> None:
    command = parse_command(command_text)

    assert command.name == "record"
    assert command.argument == action
    assert command.text == text


def test_parse_command_preserves_complete_marker_text() -> None:
    command = parse_command("mark before large throttle step")

    assert command.name == "mark"
    assert command.text == "before large throttle step"


@pytest.mark.parametrize(
    ("command_text", "fault_name", "expected_value"),
    [
        ("inject rpm_bias 5000", "rpm_bias", 5_000.0),
        ("inject egt_bias 40", "egt_bias", 40.0),
        ("inject rpm_stuck", "rpm_stuck", None),
        ("inject egt_stuck 650", "egt_stuck", 650.0),
        ("inject rpm_dropout", "rpm_dropout", None),
        ("inject egt_dropout", "egt_dropout", None),
        ("inject rpm_value 160000", "rpm_value", 160_000.0),
        ("inject egt_value 1000", "egt_value", 1_000.0),
        ("inject rpm_noise 1000", "rpm_noise", 1_000.0),
        ("inject egt_noise 20", "egt_noise", 20.0),
        ("inject rpm_drift 500", "rpm_drift", 500.0),
        ("inject egt_drift -2", "egt_drift", -2.0),
    ],
)
def test_parse_command_accepts_sensor_fault_injection(
    command_text: str,
    fault_name: str,
    expected_value: float | None,
) -> None:
    command = parse_command(command_text)

    assert command.name == "inject"
    assert command.argument == fault_name
    assert command.value == expected_value


@pytest.mark.parametrize("channel", ["rpm", "egt"])
def test_parse_command_accepts_channel_fault_clear(channel: str) -> None:
    command = parse_command(f"clear_fault {channel}")

    assert command.name == "clear_fault"
    assert command.argument == channel


@pytest.mark.parametrize(
    "command_text",
    [
        "",
        "unknown",
        "start now",
        "throttle",
        "throttle fast",
        "inject",
        "inject unknown 1",
        "inject rpm_bias",
        "inject rpm_dropout 1",
        "inject rpm_noise -1",
        "clear_fault",
        "clear_fault speed",
        "record",
        "record unknown",
        "record stop now",
        "record start too many names",
        "mark",
    ],
)
def test_parse_command_rejects_malformed_commands(command_text: str) -> None:
    with pytest.raises(ValueError):
        parse_command(command_text)


def test_status_displays_raw_validated_and_health_telemetry() -> None:
    output_stream = StringIO()
    simulation = InteractiveEngineSimulation(output_stream=output_stream)

    simulation._print_status(simulation.coordinator.snapshot)

    status_text = output_stream.getvalue()
    assert "Rotor speed: truth=" in status_text
    assert "raw=" in status_text
    assert "validated=" in status_text
    assert "health=VALID" in status_text
    assert "EGT: truth=" in status_text
    assert "Sensor health=VALID" in status_text
    assert "automatic FAULT=False" in status_text
    assert "sample periods=0.010/0.020 s" in status_text
    assert "Protection: active=HARD_CUTOFF" in status_text
    assert "limits EGT/acceleration/overspeed=" in status_text
    assert "deceleration minimum=" in status_text


def test_protection_command_displays_complete_arbitration_telemetry() -> None:
    output_stream = StringIO()
    simulation = InteractiveEngineSimulation(output_stream=output_stream)

    simulation._print_protection(simulation.coordinator.snapshot)

    protection_text = output_stream.getvalue()
    assert "requested fuel:" in protection_text
    assert "final fuel:" in protection_text
    assert "active limiter:" in protection_text
    assert "constraining:" in protection_text
    assert "EGT upper limit:" in protection_text
    assert "acceleration limit:" in protection_text
    assert "overspeed limit:" in protection_text
    assert "deceleration minimum:" in protection_text
    assert "rotor acceleration:" in protection_text
    assert "speed ratio:" in protection_text
    assert "soft overspeed:" in protection_text
    assert "hard overspeed:" in protection_text
    assert "critical FAULT:" in protection_text


def test_interactive_commands_inject_list_and_clear_faults() -> None:
    output_stream = StringIO()
    simulation = InteractiveEngineSimulation(output_stream=output_stream)
    simulation._command_queue.put("inject rpm_bias 5000")
    simulation._command_queue.put("faults")

    simulation._process_queued_commands()

    assert simulation.coordinator.sensor_fault_injector.is_active(
        SensorChannel.ROTOR_SPEED
    )
    assert "bias +5000 rpm" in output_stream.getvalue()

    simulation._command_queue.put("clear_fault rpm")
    simulation._process_queued_commands()

    assert not simulation.coordinator.sensor_fault_injector.is_active(
        SensorChannel.ROTOR_SPEED
    )


def test_status_displays_dropout_as_unavailable() -> None:
    output_stream = StringIO()
    simulation = InteractiveEngineSimulation(output_stream=output_stream)
    simulation._command_queue.put("inject egt_dropout")
    simulation._process_queued_commands()
    snapshot = simulation.coordinator.step(
        EngineOperationRequest(),
        time_step_s=0.01,
    )

    simulation._print_status(snapshot)

    assert "raw=unavailable" in output_stream.getvalue()
    assert "health=INVALID" in output_stream.getvalue()
