"""Headless unit tests for the Matplotlib live engine dashboard."""

from datetime import datetime, timezone
import json
from pathlib import Path

import matplotlib
import pytest
from matplotlib.colors import to_rgba

matplotlib.use("Agg")

from simulation.application.live_dashboard import LiveEngineDashboard  # noqa: E402
from simulation.application.dashboard_model import DashboardSimulation  # noqa: E402
from simulation.application.simulation_service import SimulationService  # noqa: E402
from simulation.operation.engine_state import EngineOperatingState  # noqa: E402
from simulation.sensors.fault_injection import (  # noqa: E402
    BiasSensorFault,
    DropoutSensorFault,
    ForcedValueSensorFault,
    SensorChannel,
)
from simulation.validation.sensor_validation import ChannelHealth  # noqa: E402
from simulation.telemetry.metadata import GitMetadata  # noqa: E402
from simulation.telemetry.recorder import (  # noqa: E402
    RunRecorder,
    RunRecorderParameters,
)


def _recording_dashboard(tmp_path: Path) -> LiveEngineDashboard:
    recorder = RunRecorder(
        RunRecorderParameters(base_directory=tmp_path),
        wall_clock=lambda: datetime(2026, 7, 20, tzinfo=timezone.utc),
        git_metadata_provider=lambda _: GitMetadata(),
    )
    service = SimulationService(recorder=recorder)
    return LiveEngineDashboard(
        dashboard_simulation=DashboardSimulation(service=service)
    )


def test_dashboard_advances_and_refreshes_live_signals() -> None:
    dashboard = LiveEngineDashboard()
    dashboard.dashboard_simulation.controls.request_startup()

    snapshot = dashboard.advance_and_refresh(elapsed_wall_time_s=0.02)

    assert snapshot.operating_state is EngineOperatingState.CRANKING
    assert len(dashboard.dashboard_simulation.history.times_s) == 2
    assert len(dashboard._rotor_speed_line.get_xdata()) == 2
    assert len(dashboard._measured_rotor_speed_line.get_xdata()) == 2
    assert len(dashboard._validated_rotor_speed_line.get_xdata()) == 2
    assert len(dashboard._measured_egt_line.get_xdata()) == 2
    assert len(dashboard._validated_egt_line.get_xdata()) == 2
    assert "RPM T/R/V" in dashboard._telemetry_text.get_text()
    assert "Sensors" in dashboard._telemetry_text.get_text()
    assert "Sample R/E" in dashboard._telemetry_text.get_text()
    dashboard.close(save_result=False)


def test_dashboard_uses_grouped_dark_theme_and_live_status_indicators() -> None:
    dashboard = LiveEngineDashboard()

    assert dashboard.figure.get_facecolor() == to_rgba(
        dashboard._BACKGROUND_COLOR
    )
    assert tuple(
        axis.get_title(loc="left") for axis in dashboard._plot_axes
    ) == (
        "ROTOR SPEED",
        "EXHAUST GAS TEMPERATURE",
        "FUEL COMMAND",
        "ESTIMATED THRUST",
    )
    assert all(
        axis.get_facecolor() == to_rgba(dashboard._PLOT_COLOR)
        for axis in dashboard._plot_axes
    )
    dashboard.figure.canvas.draw()
    speed_tick_labels = tuple(
        label.get_text() for label in dashboard._plot_axes[0].get_yticklabels()
    )
    assert "150k" in speed_tick_labels
    assert "150000" not in speed_tick_labels

    dashboard._throttle_slider.set_val(0.65)
    dashboard.dashboard_simulation.coordinator.inject_sensor_fault(
        SensorChannel.EXHAUST_TEMPERATURE,
        DropoutSensorFault(),
    )
    dashboard.advance_and_refresh(0.01)

    assert dashboard._throttle_value_text.get_text() == "65%"
    assert dashboard._throttle_lever_grip.get_y() == pytest.approx(0.60)
    assert dashboard._throttle_lever_shaft.get_ydata()[-1] == pytest.approx(
        0.65
    )
    assert dashboard._sensor_health_text.get_text() == "SENSORS  INVALID"
    assert dashboard._sensor_health_text.get_bbox_patch().get_facecolor() == (
        to_rgba(dashboard._DANGER_COLOR)
    )
    dashboard.close(save_result=False)


def test_dashboard_spacing_separates_labels_events_and_left_panels() -> None:
    dashboard = LiveEngineDashboard()
    dashboard.figure.canvas.draw()

    panel_right = dashboard.figure.transFigure.transform((0.363, 0.0))[0]
    assert all(
        axis.yaxis.label.get_window_extent().x0 > panel_right
        for axis in dashboard._plot_axes
    )
    assert (
        dashboard._telemetry_text.get_window_extent().y0
        > dashboard._transition_text.get_window_extent().y1
    )
    dashboard.close(save_result=False)


def test_dashboard_saves_final_figure(tmp_path: Path) -> None:
    result_path = tmp_path / "dashboard.png"
    dashboard = LiveEngineDashboard(result_path=result_path)
    dashboard.advance_and_refresh(elapsed_wall_time_s=0.02)

    dashboard.save_figure()

    assert result_path.is_file()
    dashboard.close(save_result=False)


def test_dashboard_displays_unavailable_faulted_measurement() -> None:
    dashboard = LiveEngineDashboard()
    dashboard.dashboard_simulation.coordinator.inject_sensor_fault(
        SensorChannel.EXHAUST_TEMPERATURE,
        DropoutSensorFault(),
    )

    snapshot = dashboard.advance_and_refresh(elapsed_wall_time_s=0.02)

    assert snapshot.measured_exhaust_temperature_c is None
    assert "EGT health INVALID" in dashboard._telemetry_text.get_text()
    dashboard.close(save_result=False)


def test_dashboard_compacts_extreme_fault_values_inside_status_card() -> None:
    dashboard = LiveEngineDashboard()
    dashboard._fault_channel_selector.set_active(1)
    dashboard._fault_type_selector.set_active(3)
    dashboard._fault_value_text_box.set_val("1e300")
    dashboard._on_inject_sensor_fault(None)

    dashboard.advance_and_refresh(0.10)
    dashboard.figure.canvas.draw()

    telemetry = dashboard._telemetry_text.get_text()
    telemetry_bounds = dashboard._telemetry_text.get_window_extent()
    status_content_right = dashboard.figure.transFigure.transform(
        (0.355, 0.0)
    )[0]
    assert "1.00e+300" in telemetry
    assert telemetry_bounds.x1 <= status_content_right
    dashboard.close(save_result=False)


def test_dashboard_exposes_every_sensor_fault_type() -> None:
    dashboard = LiveEngineDashboard()

    channel_labels = tuple(
        label.get_text() for label in dashboard._fault_channel_selector.labels
    )
    fault_labels = tuple(
        label.get_text() for label in dashboard._fault_type_selector.labels
    )

    assert channel_labels == ("Rotor speed", "EGT")
    assert fault_labels == (
        "Bias",
        "Stuck",
        "Dropout",
        "Forced value",
        "Noise",
        "Drift",
    )
    dashboard.close(save_result=False)


def test_dashboard_widgets_inject_and_replace_a_selected_fault() -> None:
    dashboard = LiveEngineDashboard()
    dashboard._fault_channel_selector.set_active(1)
    dashboard._fault_value_text_box.set_val("25")

    dashboard._on_inject_sensor_fault(None)

    injector = dashboard.dashboard_simulation.coordinator.sensor_fault_injector
    assert injector.active_fault(
        SensorChannel.EXHAUST_TEMPERATURE
    ) == BiasSensorFault(offset=25.0)

    dashboard._fault_type_selector.set_active(3)
    dashboard._fault_value_text_box.set_val("1000")
    dashboard._on_inject_sensor_fault(None)

    assert injector.active_fault(
        SensorChannel.EXHAUST_TEMPERATURE
    ) == ForcedValueSensorFault(value=1000.0)
    assert "Injected EGT sensor" in dashboard._fault_feedback_text.get_text()
    dashboard.close(save_result=False)


def test_dashboard_clear_channel_exposes_validation_recovery() -> None:
    dashboard = LiveEngineDashboard()
    dashboard._fault_channel_selector.set_active(1)
    dashboard._fault_type_selector.set_active(2)
    dashboard._on_inject_sensor_fault(None)
    faulted_snapshot = dashboard.advance_and_refresh(0.01)

    assert faulted_snapshot.exhaust_temperature_health is ChannelHealth.INVALID

    dashboard._on_clear_sensor_fault(None)
    recovering_snapshot = dashboard.advance_and_refresh(0.01)
    recovered_snapshot = dashboard.advance_and_refresh(0.20)

    assert recovering_snapshot.exhaust_temperature_health is ChannelHealth.SUSPECT
    assert recovered_snapshot.exhaust_temperature_health is ChannelHealth.VALID
    assert "recovery in progress" in dashboard._fault_feedback_text.get_text()
    dashboard.close(save_result=False)


def test_dashboard_clear_all_removes_faults_from_both_channels() -> None:
    dashboard = LiveEngineDashboard()
    fault_controls = dashboard.dashboard_simulation.sensor_fault_controls
    coordinator = dashboard.dashboard_simulation.coordinator
    fault_controls.inject(coordinator)
    fault_controls.select_channel(SensorChannel.EXHAUST_TEMPERATURE)
    fault_controls.inject(coordinator)

    dashboard._on_clear_all_sensor_faults(None)

    assert all(
        not coordinator.sensor_fault_injector.is_active(channel)
        for channel in SensorChannel
    )
    assert "Cleared all" in dashboard._fault_feedback_text.get_text()
    dashboard.close(save_result=False)


@pytest.mark.parametrize("invalid_value", ["not-a-number", "nan"])
def test_dashboard_reports_invalid_fault_input_without_raising(
    invalid_value: str,
) -> None:
    dashboard = LiveEngineDashboard()
    dashboard._fault_value_text_box.set_val(invalid_value)

    dashboard._on_inject_sensor_fault(None)

    assert dashboard._fault_feedback_text.get_text().startswith(
        "Invalid fault input:"
    )
    dashboard.close(save_result=False)


def test_dashboard_starts_and_stops_named_recording(tmp_path: Path) -> None:
    dashboard = _recording_dashboard(tmp_path)
    dashboard._recording_run_name_text_box.set_val("dashboard test")

    dashboard._on_start_recording(None)
    dashboard.advance_and_refresh(0.12)

    service = dashboard.dashboard_simulation.service
    active_status = service.get_recording_status()
    assert active_status is not None
    assert service.recorder.is_recording
    assert active_status.run_name == "dashboard_test"
    assert dashboard._recording_status_text.get_text().startswith("● REC")

    dashboard._on_stop_recording(None)

    final_status = service.get_recording_status()
    assert final_status is not None
    assert service.recorder.is_recording is False
    assert final_status.telemetry_sample_count == 3
    assert final_status.event_count == 2
    assert dashboard._recording_status_text.get_text().startswith("SAVED")
    assert (final_status.run_directory / "telemetry.csv").is_file()
    assert (final_status.run_directory / "events.csv").is_file()
    dashboard.close(save_result=False)


def test_dashboard_reports_duplicate_recording_start_without_crashing(
    tmp_path: Path,
) -> None:
    dashboard = _recording_dashboard(tmp_path)
    dashboard._on_start_recording(None)

    dashboard._on_start_recording(None)

    assert "already active" in dashboard._transition_text.get_text()
    dashboard.close(save_result=False)


def test_dashboard_close_finalizes_active_recording(tmp_path: Path) -> None:
    dashboard = _recording_dashboard(tmp_path)
    dashboard._on_start_recording(None)
    service = dashboard.dashboard_simulation.service
    run_directory = service.recorder.current_run_directory
    assert run_directory is not None

    dashboard.close(save_result=False)

    with (run_directory / "metadata.json").open(encoding="utf-8") as file:
        metadata = json.load(file)
    assert service.recorder.is_recording is False
    assert metadata["completion_status"] == "complete"
