"""Headless unit tests for the Matplotlib live engine dashboard."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

from simulation.application.live_dashboard import LiveEngineDashboard  # noqa: E402
from simulation.operation.engine_state import EngineOperatingState  # noqa: E402


def test_dashboard_advances_and_refreshes_live_signals() -> None:
    dashboard = LiveEngineDashboard()
    dashboard.dashboard_simulation.controls.request_startup()

    snapshot = dashboard.advance_and_refresh(elapsed_wall_time_s=0.02)

    assert snapshot.operating_state is EngineOperatingState.CRANKING
    assert len(dashboard.dashboard_simulation.history.times_s) == 2
    assert len(dashboard._rotor_speed_line.get_xdata()) == 2
    assert len(dashboard._measured_rotor_speed_line.get_xdata()) == 2
    assert len(dashboard._measured_egt_line.get_xdata()) == 2
    assert "RPM T/M/E" in dashboard._telemetry_text.get_text()
    assert "Sample R/E" in dashboard._telemetry_text.get_text()
    dashboard.close(save_result=False)


def test_dashboard_saves_final_figure(tmp_path: Path) -> None:
    result_path = tmp_path / "dashboard.png"
    dashboard = LiveEngineDashboard(result_path=result_path)
    dashboard.advance_and_refresh(elapsed_wall_time_s=0.02)

    dashboard.save_figure()

    assert result_path.is_file()
    dashboard.close(save_result=False)
