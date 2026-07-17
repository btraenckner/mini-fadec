"""Unit tests for interactive simulation command parsing."""

import pytest

from simulation.application.interactive_simulation import parse_command


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
