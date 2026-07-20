"""Unit tests for interactive simulation command parsing."""

from io import StringIO

import pytest

from simulation.application.interactive_simulation import (
    InteractiveEngineSimulation,
    parse_command,
)


@pytest.mark.parametrize(
    "command_name",
    ["help", "start", "shutdown", "status", "fault", "reset", "quit"],
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
    "command_text",
    ["", "unknown", "start now", "throttle", "throttle fast"],
)
def test_parse_command_rejects_malformed_commands(command_text: str) -> None:
    with pytest.raises(ValueError):
        parse_command(command_text)


def test_status_displays_true_and_measured_sensor_telemetry() -> None:
    output_stream = StringIO()
    simulation = InteractiveEngineSimulation(output_stream=output_stream)

    simulation._print_status(simulation.coordinator.snapshot)

    status_text = output_stream.getvalue()
    assert "true/measured speed=" in status_text
    assert "true/measured EGT=" in status_text
    assert "error=" in status_text
    assert "sample periods=0.010/0.020 s" in status_text
