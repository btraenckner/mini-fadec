"""Tests for the non-interactive scenario command-line adapter."""

import pytest

from simulation.scenarios.cli import main as cli_main


def test_cli_list_and_show_return_success(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli_main(["list"]) == 0
    assert "SCN-NORMAL-001" in capsys.readouterr().out

    assert cli_main(["show", "normal_start_run_shutdown"]) == 0
    shown = capsys.readouterr().out
    assert "StateSequenceRequirementEvaluator" in shown
    assert "max_duration_s" in shown
