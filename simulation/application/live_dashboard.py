"""Matplotlib-based live dashboard for the Mini-FADEC simulation."""

from pathlib import Path
import time

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch
from matplotlib.ticker import FuncFormatter
from matplotlib.widgets import AxesWidget, Button, RadioButtons, Slider, TextBox

from simulation.application.dashboard_model import (
    DashboardFaultType,
    DashboardOperatingMode,
    DashboardSimulation,
)
from simulation.application.engine_simulation import EngineSimulationSnapshot
from simulation.operation.engine_state import EngineOperatingState
from simulation.scenarios.runner import ScenarioExecutionState
from simulation.sensors.fault_injection import SensorChannel
from simulation.validation.sensor_validation import ChannelHealth
from simulation.verification.results import ScenarioOverallStatus


class LiveEngineDashboard:
    """Display live engine signals and graphical operator controls."""

    _BACKGROUND_COLOR = "#08111f"
    _PANEL_COLOR = "#101d30"
    _PLOT_COLOR = "#0d1828"
    _BORDER_COLOR = "#263950"
    _TEXT_COLOR = "#e9f0f8"
    _MUTED_TEXT_COLOR = "#8fa3b8"
    _GRID_COLOR = "#263950"
    _ACCENT_COLOR = "#3aa6ff"
    _SUCCESS_COLOR = "#31c48d"
    _WARNING_COLOR = "#f4b740"
    _DANGER_COLOR = "#f05d5e"

    def __init__(
        self,
        dashboard_simulation: DashboardSimulation | None = None,
        *,
        refresh_interval_s: float = 0.05,
        history_window_s: float = 60.0,
        result_path: Path | str = "results/05_live_engine_dashboard.png",
    ) -> None:
        self.dashboard_simulation = (
            dashboard_simulation or DashboardSimulation()
        )
        self.refresh_interval_s = refresh_interval_s
        self.history_window_s = history_window_s
        self.result_path = Path(result_path)

        self._closed = False
        self._last_displayed_event_sequence = 0
        self._last_update_time = time.monotonic()
        self._figure, self._plot_axes = self._create_figure()
        self._create_status_panel()
        self._create_controls()
        self._create_sensor_fault_controls()
        self._create_scenario_controls()
        self._create_timing_panel()
        self._create_signal_plots()
        self._manual_control_widgets = (
            self._throttle_slider,
            self._start_button,
            self._shutdown_button,
            self._fault_button,
            self._reset_button,
            self._recording_run_name_text_box,
            self._recording_start_button,
            self._recording_stop_button,
            self._fault_channel_selector,
            self._fault_type_selector,
            self._fault_value_text_box,
            self._inject_sensor_fault_button,
            self._clear_sensor_fault_button,
            self._clear_all_sensor_faults_button,
        )
        self._update_runner_control_states()

        self._timer = self._figure.canvas.new_timer(
            interval=max(1, int(self.refresh_interval_s * 1_000.0))
        )
        self._timer.add_callback(self._on_timer)
        self._figure.canvas.mpl_connect("close_event", self._on_figure_close)
        self._refresh_dashboard(
            self.dashboard_simulation.get_latest_snapshot()
        )

    @property
    def figure(self) -> plt.Figure:
        """Return the dashboard figure for display or testing."""

        return self._figure

    def run(self) -> None:
        """Start live updates and block until the dashboard window closes."""

        self._last_update_time = time.monotonic()
        self._timer.start()
        plt.show()

    def advance_and_refresh(
        self,
        elapsed_wall_time_s: float,
    ) -> EngineSimulationSnapshot:
        """Advance the simulation and refresh all dashboard elements."""

        snapshot = self.dashboard_simulation.advance(elapsed_wall_time_s)
        self._refresh_dashboard(snapshot)
        return snapshot

    def save_figure(self) -> None:
        """Save the current dashboard view to the configured result path."""

        self.result_path.parent.mkdir(parents=True, exist_ok=True)
        self._figure.savefig(self.result_path, dpi=150)

    def close(self, *, save_result: bool = True) -> None:
        """Stop live updates, optionally save, and close the window."""

        if self._closed:
            return
        self._finalize_dashboard_recording()
        if save_result:
            self.save_figure()
        self._closed = True
        self._timer.stop()
        plt.close(self._figure)

    def _create_figure(self) -> tuple[plt.Figure, tuple[Axes, ...]]:
        """Create the dashboard window and live-signal axes."""

        figure, plot_axes = plt.subplots(
            nrows=4,
            ncols=1,
            sharex=True,
            figsize=(17.5, 10.0),
            facecolor=self._BACKGROUND_COLOR,
        )
        figure.subplots_adjust(
            left=0.415,
            right=0.98,
            bottom=0.07,
            top=0.89,
            hspace=0.30,
        )
        figure.canvas.manager.set_window_title("Mini-FADEC Live Dashboard")
        figure.suptitle(
            "MINI-FADEC  /  LIVE ENGINE TEST",
            x=0.02,
            y=0.972,
            horizontalalignment="left",
            fontsize=17,
            fontweight="bold",
            color=self._TEXT_COLOR,
        )
        figure.text(
            0.98,
            0.968,
            "REAL-TIME CONTROL & SENSOR FAULT LAB",
            horizontalalignment="right",
            fontsize=8.5,
            color=self._MUTED_TEXT_COLOR,
        )
        return figure, tuple(plot_axes)

    def _create_status_panel(self) -> None:
        """Create the operating-state and telemetry text panel."""

        self._add_panel((0.018, 0.650, 0.345, 0.260), "ENGINE STATUS")
        self._state_text = self._figure.text(
            0.032,
            0.845,
            "OFF",
            fontsize=14,
            fontweight="bold",
            color="white",
            bbox={
                "boxstyle": "round,pad=0.38",
                "facecolor": "0.35",
                "edgecolor": "none",
            },
        )
        self._sensor_health_text = self._figure.text(
            0.14,
            0.847,
            "SENSORS  VALID",
            fontsize=9,
            fontweight="bold",
            color=self._BACKGROUND_COLOR,
            bbox={
                "boxstyle": "round,pad=0.38",
                "facecolor": self._SUCCESS_COLOR,
                "edgecolor": "none",
            },
        )
        self._time_text = self._figure.text(
            0.35,
            0.848,
            "T+  0.00 s",
            horizontalalignment="right",
            fontsize=9,
            family="monospace",
            color=self._MUTED_TEXT_COLOR,
        )
        self._telemetry_text = self._figure.text(
            0.032,
            0.805,
            "",
            fontsize=6.9,
            family="monospace",
            verticalalignment="top",
            linespacing=1.12,
            color=self._TEXT_COLOR,
        )
        self._add_panel((0.026, 0.657, 0.329, 0.028))
        self._transition_text = self._figure.text(
            0.038,
            0.666,
            "●  System ready",
            fontsize=8,
            color=self._MUTED_TEXT_COLOR,
            wrap=True,
        )

    def _create_scenario_controls(self) -> None:
        """Create the mode switch, scenario dropdown, and runner controls."""

        self._add_panel((0.408, 0.922, 0.572, 0.038))
        self._mode_switch_button = self._create_button(
            bounds=(0.417, 0.928, 0.095, 0.026),
            label="MANUAL  ●○",
            color="#234e70",
            callback=self._on_mode_switch,
        )
        self._scenario_dropdown_button = self._create_button(
            bounds=(0.520, 0.928, 0.205, 0.026),
            label="",
            color="#263950",
            callback=self._on_scenario_dropdown,
        )

        scenario_labels = tuple(
            f"{scenario.scenario_id} | "
            f"{self._shorten(scenario.name.replace('_', ' '), 21)}"
            for scenario in self.dashboard_simulation.scenarios
        )
        dropdown_axis = self._figure.add_axes((0.520, 0.700, 0.205, 0.218))
        self._style_widget_axis(dropdown_axis)
        dropdown_axis.set_zorder(20)
        self._scenario_dropdown_selector = RadioButtons(
            dropdown_axis,
            scenario_labels,
            active=0,
            activecolor=self._ACCENT_COLOR,
            radio_props={
                "edgecolor": self._MUTED_TEXT_COLOR,
                "linewidth": 0.8,
                "s": 28.0,
            },
        )
        for label in self._scenario_dropdown_selector.labels:
            label.set_fontsize(7)
            label.set_color(self._TEXT_COLOR)
        self._scenario_dropdown_selector.on_clicked(
            self._on_scenario_selected
        )
        dropdown_axis.set_visible(False)
        self._scenario_dropdown_axis = dropdown_axis
        self._scenario_dropdown_labels = scenario_labels

        self._scenario_progress_text = self._figure.text(
            0.733,
            0.937,
            "MANUAL CONTROL",
            fontsize=6.5,
            family="monospace",
            color=self._MUTED_TEXT_COLOR,
            verticalalignment="center",
        )
        self._timing_panel_button = self._create_button(
            bounds=(0.778, 0.928, 0.055, 0.026),
            label="TIMING",
            color="#263950",
            callback=self._on_timing_panel,
        )
        self._run_scenario_button = self._create_button(
            bounds=(0.840, 0.928, 0.050, 0.026),
            label="RUN",
            color="#176c54",
            callback=self._on_run_scenario,
        )
        self._cancel_scenario_button = self._create_button(
            bounds=(0.900, 0.928, 0.070, 0.026),
            label="CANCEL",
            color="#762f3a",
            callback=self._on_cancel_scenario,
        )
        self._update_scenario_status()

    def _create_timing_panel(self) -> None:
        """Create a modal scheduler diagnostics and preset-selection panel."""

        panel_axis = self._figure.add_axes((0.425, 0.12, 0.55, 0.75))
        panel_axis.set_facecolor(self._PANEL_COLOR)
        panel_axis.set_zorder(30)
        panel_axis.set_xticks(())
        panel_axis.set_yticks(())
        for spine in panel_axis.spines.values():
            spine.set_color(self._BORDER_COLOR)
            spine.set_linewidth(1.2)
        panel_axis.text(
            0.035,
            0.955,
            "SCHEDULER / TIMING",
            transform=panel_axis.transAxes,
            fontsize=11,
            fontweight="bold",
            color=self._TEXT_COLOR,
            verticalalignment="top",
        )
        self._timing_summary_text = panel_axis.text(
            0.035,
            0.895,
            "",
            transform=panel_axis.transAxes,
            fontsize=7.5,
            family="monospace",
            color=self._MUTED_TEXT_COLOR,
            verticalalignment="top",
        )
        panel_axis.text(
            0.035,
            0.805,
            "PRESET",
            transform=panel_axis.transAxes,
            fontsize=7.5,
            fontweight="bold",
            color=self._MUTED_TEXT_COLOR,
        )
        self._timing_table_text = panel_axis.text(
            0.305,
            0.815,
            "",
            transform=panel_axis.transAxes,
            fontsize=6.7,
            family="monospace",
            color=self._TEXT_COLOR,
            verticalalignment="top",
            linespacing=1.35,
        )
        self._timing_instruction_text = panel_axis.text(
            0.035,
            0.045,
            "Preset changes are accepted only while the simulation is stopped.",
            transform=panel_axis.transAxes,
            fontsize=7,
            color=self._MUTED_TEXT_COLOR,
        )

        preset_labels = (
            self.dashboard_simulation.available_scheduler_presets()
        )
        selected_preset_index = preset_labels.index(
            self.dashboard_simulation.selected_scheduler_preset
        )
        preset_axis = self._figure.add_axes((0.445, 0.39, 0.135, 0.30))
        self._style_widget_axis(preset_axis)
        preset_axis.set_zorder(31)
        self._timing_preset_selector = RadioButtons(
            preset_axis,
            preset_labels,
            active=selected_preset_index,
            activecolor=self._ACCENT_COLOR,
            radio_props={
                "edgecolor": self._MUTED_TEXT_COLOR,
                "linewidth": 0.8,
                "s": 30.0,
            },
        )
        for label in self._timing_preset_selector.labels:
            label.set_fontsize(7.2)
            label.set_color(self._TEXT_COLOR)
        self._timing_preset_selector.on_clicked(
            self._on_timing_preset_selected
        )

        close_button = self._create_button(
            bounds=(0.907, 0.823, 0.050, 0.028),
            label="CLOSE",
            color="#263950",
            callback=self._on_timing_panel,
        )
        close_button.ax.set_zorder(31)
        self._timing_panel_axis = panel_axis
        self._timing_preset_axis = preset_axis
        self._timing_close_button = close_button
        self._timing_panel_visible = False
        self._set_timing_panel_visible(False)

    def _create_controls(self) -> None:
        """Create throttle lever and operator command buttons."""

        self._add_panel((0.018, 0.215, 0.067, 0.43), "THROTTLE")
        throttle_axis = self._figure.add_axes((0.028, 0.285, 0.046, 0.285))
        throttle_axis.set_facecolor(self._PANEL_COLOR)
        self._throttle_slider = Slider(
            ax=throttle_axis,
            label="",
            valmin=0.0,
            valmax=1.0,
            valinit=0.0,
            valstep=0.01,
            orientation="vertical",
            color=self._ACCENT_COLOR,
        )
        throttle_axis.set_xlim(0.0, 1.0)
        throttle_axis.set_ylim(-0.08, 1.08)
        throttle_axis.set_axis_off()
        self._throttle_slider.track.set_visible(False)
        self._throttle_slider.poly.set_visible(False)
        self._throttle_slider.hline.set_visible(False)
        self._throttle_slider._handle.set_visible(False)
        self._throttle_slider.valtext.set_visible(False)
        self._create_throttle_lever(throttle_axis)
        self._throttle_slider.on_changed(self._on_throttle_changed)
        self._figure.text(
            0.051,
            0.582,
            "MAX",
            horizontalalignment="center",
            fontsize=6.5,
            fontweight="bold",
            color=self._MUTED_TEXT_COLOR,
        )
        self._figure.text(
            0.051,
            0.272,
            "IDLE",
            horizontalalignment="center",
            fontsize=6.5,
            fontweight="bold",
            color=self._MUTED_TEXT_COLOR,
        )
        self._throttle_value_text = self._figure.text(
            0.0515,
            0.240,
            "0%",
            horizontalalignment="center",
            fontsize=12,
            fontweight="bold",
            color=self._ACCENT_COLOR,
        )

        self._add_panel((0.018, 0.025, 0.345, 0.175), "ENGINE COMMANDS")

        self._start_button = self._create_button(
            bounds=(0.032, 0.125, 0.068, 0.035),
            label="START",
            color="#176c54",
            callback=self._on_start,
        )
        self._shutdown_button = self._create_button(
            bounds=(0.108, 0.125, 0.082, 0.035),
            label="SHUTDOWN",
            color="#72561d",
            callback=self._on_shutdown,
        )
        self._fault_button = self._create_button(
            bounds=(0.198, 0.125, 0.068, 0.035),
            label="FAULT",
            color="#762f3a",
            callback=self._on_fault,
        )
        self._reset_button = self._create_button(
            bounds=(0.274, 0.125, 0.075, 0.035),
            label="RESET",
            color="#234e70",
            callback=self._on_reset,
        )
        self._create_recording_controls()
        self._quit_button = self._create_button(
            bounds=(0.244, 0.035, 0.105, 0.035),
            label="SAVE & QUIT",
            color="#263950",
            callback=self._on_quit,
        )

    def _create_recording_controls(self) -> None:
        """Create dashboard-native run recording controls and status."""

        run_name_axis = self._figure.add_axes((0.072, 0.080, 0.165, 0.032))
        self._style_widget_axis(run_name_axis)
        self._recording_run_name_text_box = TextBox(
            run_name_axis,
            "RUN  ",
            initial="dashboard_run",
            color=self._PLOT_COLOR,
            hovercolor="#15263d",
        )
        self._recording_run_name_text_box.label.set_color(
            self._MUTED_TEXT_COLOR
        )
        self._recording_run_name_text_box.label.set_fontsize(7)
        self._recording_run_name_text_box.text_disp.set_color(self._TEXT_COLOR)

        self._recording_status_text = self._figure.text(
            0.247,
            0.089,
            "REC OFF",
            fontsize=7,
            fontweight="bold",
            family="monospace",
            color=self._MUTED_TEXT_COLOR,
        )
        self._recording_start_button = self._create_button(
            bounds=(0.032, 0.035, 0.095, 0.035),
            label="● RECORD",
            color="#8a3041",
            callback=self._on_start_recording,
        )
        self._recording_stop_button = self._create_button(
            bounds=(0.137, 0.035, 0.097, 0.035),
            label="■ STOP REC",
            color="#263950",
            callback=self._on_stop_recording,
        )

    def _create_throttle_lever(self, axis: Axes) -> None:
        """Draw a jet-style moving lever over the functional slider axis."""

        gate = FancyBboxPatch(
            (0.39, 0.0),
            0.22,
            1.0,
            boxstyle="round,pad=0.02,rounding_size=0.08",
            facecolor="#050a12",
            edgecolor=self._BORDER_COLOR,
            linewidth=1.2,
            zorder=1,
        )
        axis.add_patch(gate)
        for gate_position in (0.25, 0.50, 0.75):
            axis.plot(
                (0.35, 0.65),
                (gate_position, gate_position),
                color=self._BORDER_COLOR,
                linewidth=0.8,
                zorder=2,
            )

        (self._throttle_lever_shaft,) = axis.plot(
            (0.50, 0.50),
            (-0.04, 0.0),
            color="#8596a9",
            linewidth=5.0,
            solid_capstyle="round",
            zorder=3,
        )
        axis.scatter(
            (0.50,),
            (-0.04,),
            s=75,
            facecolor="#1c2c40",
            edgecolor="#aab8c7",
            linewidth=1.0,
            zorder=4,
        )
        self._throttle_lever_grip = FancyBboxPatch(
            (0.10, -0.05),
            0.80,
            0.10,
            boxstyle="round,pad=0.015,rounding_size=0.05",
            facecolor="#17273a",
            edgecolor="#d9e2ec",
            linewidth=1.3,
            zorder=5,
        )
        axis.add_patch(self._throttle_lever_grip)
        (self._throttle_lever_highlight,) = axis.plot(
            (0.22, 0.78),
            (0.018, 0.018),
            color=self._ACCENT_COLOR,
            linewidth=2.0,
            solid_capstyle="round",
            zorder=6,
        )

    def _update_throttle_lever(self, throttle_command: float) -> None:
        """Move the custom shaft and grip to the selected throttle position."""

        self._throttle_lever_shaft.set_ydata((-0.04, throttle_command))
        self._throttle_lever_grip.set_y(throttle_command - 0.05)
        self._throttle_lever_highlight.set_ydata(
            (throttle_command + 0.018, throttle_command + 0.018)
        )

    def _create_sensor_fault_controls(self) -> None:
        """Create fault selection, injection, and recovery controls."""

        fault_controls = self.dashboard_simulation.sensor_fault_controls
        self._add_panel((0.095, 0.215, 0.268, 0.43), "SENSOR FAULT INJECTION")
        self._figure.text(
            0.108,
            0.592,
            "TARGET",
            fontsize=7,
            fontweight="bold",
            color=self._MUTED_TEXT_COLOR,
        )
        self._figure.text(
            0.225,
            0.592,
            "FAULT MODE",
            fontsize=7,
            fontweight="bold",
            color=self._MUTED_TEXT_COLOR,
        )

        channel_axis = self._figure.add_axes((0.108, 0.525, 0.105, 0.06))
        self._style_widget_axis(channel_axis)
        channel_labels = ("Rotor speed", "EGT")
        active_channel_index = (
            0
            if fault_controls.selected_channel is SensorChannel.ROTOR_SPEED
            else 1
        )
        self._fault_channel_selector = RadioButtons(
            channel_axis,
            channel_labels,
            active=active_channel_index,
            activecolor=self._ACCENT_COLOR,
            radio_props={
                "edgecolor": self._MUTED_TEXT_COLOR,
                "linewidth": 0.8,
                "s": 32.0,
            },
        )
        for label in self._fault_channel_selector.labels:
            label.set_fontsize(8)
            label.set_color(self._TEXT_COLOR)
        self._fault_channel_selector.on_clicked(
            self._on_fault_channel_changed
        )

        fault_type_axis = self._figure.add_axes((0.225, 0.44, 0.125, 0.145))
        self._style_widget_axis(fault_type_axis)
        fault_labels = tuple(fault_type.value for fault_type in DashboardFaultType)
        active_fault_type_index = list(DashboardFaultType).index(
            fault_controls.selected_fault_type
        )
        self._fault_type_selector = RadioButtons(
            fault_type_axis,
            fault_labels,
            active=active_fault_type_index,
            activecolor=self._DANGER_COLOR,
            radio_props={
                "edgecolor": self._MUTED_TEXT_COLOR,
                "linewidth": 0.8,
                "s": 32.0,
            },
        )
        for label in self._fault_type_selector.labels:
            label.set_fontsize(8)
            label.set_color(self._TEXT_COLOR)
        self._fault_type_selector.on_clicked(self._on_fault_type_changed)

        value_axis = self._figure.add_axes((0.125, 0.38, 0.225, 0.035))
        self._style_widget_axis(value_axis)
        self._fault_value_text_box = TextBox(
            value_axis,
            "Value ",
            initial=fault_controls.value_text,
            color=self._PLOT_COLOR,
            hovercolor="#15263d",
        )
        self._fault_value_text_box.label.set_color(self._TEXT_COLOR)
        self._fault_value_text_box.text_disp.set_color(self._TEXT_COLOR)
        self._fault_value_text_box.on_submit(self._on_fault_value_changed)
        self._fault_value_hint_text = self._figure.text(
            0.108,
            0.355,
            fault_controls.value_hint(),
            fontsize=7,
            color=self._MUTED_TEXT_COLOR,
        )

        self._inject_sensor_fault_button = self._create_button(
            bounds=(0.108, 0.300, 0.115, 0.04),
            label="INJECT / REPLACE",
            color="#762f3a",
            callback=self._on_inject_sensor_fault,
        )
        self._clear_sensor_fault_button = self._create_button(
            bounds=(0.233, 0.300, 0.117, 0.04),
            label="CLEAR CHANNEL",
            color="#234e70",
            callback=self._on_clear_sensor_fault,
        )
        self._clear_all_sensor_faults_button = self._create_button(
            bounds=(0.108, 0.252, 0.242, 0.035),
            label="CLEAR ALL SENSOR FAULTS",
            color="#263950",
            callback=self._on_clear_all_sensor_faults,
        )
        self._fault_feedback_text = self._figure.text(
            0.108,
            0.228,
            fault_controls.last_action_message,
            fontsize=7,
            color=self._MUTED_TEXT_COLOR,
            wrap=True,
        )

    def _create_button(
        self,
        bounds: tuple[float, float, float, float],
        label: str,
        color: str,
        callback: object,
    ) -> Button:
        """Create and connect one dashboard button."""

        button_axis = self._figure.add_axes(bounds)
        self._style_widget_axis(button_axis)
        button = Button(
            button_axis,
            label,
            color=color,
            hovercolor=self._ACCENT_COLOR,
        )
        button.label.set_color(self._TEXT_COLOR)
        button.label.set_fontsize(8)
        button.label.set_fontweight("bold")
        button.on_clicked(callback)
        return button

    def _add_panel(
        self,
        bounds: tuple[float, float, float, float],
        title: str | None = None,
    ) -> None:
        """Add one rounded dashboard card in figure coordinates."""

        left, bottom, width, height = bounds
        panel = FancyBboxPatch(
            (left, bottom),
            width,
            height,
            boxstyle="round,pad=0.004,rounding_size=0.008",
            transform=self._figure.transFigure,
            facecolor=self._PANEL_COLOR,
            edgecolor=self._BORDER_COLOR,
            linewidth=0.8,
            zorder=-5,
        )
        self._figure.add_artist(panel)
        if title is not None:
            self._figure.text(
                left + 0.012,
                bottom + height - 0.025,
                title,
                fontsize=8,
                fontweight="bold",
                color=self._MUTED_TEXT_COLOR,
            )

    def _style_widget_axis(self, axis: Axes) -> None:
        """Apply the common dark style to an interactive widget axis."""

        axis.set_facecolor(self._PLOT_COLOR)
        for spine in axis.spines.values():
            spine.set_color(self._BORDER_COLOR)
            spine.set_linewidth(0.8)

    def _create_signal_plots(self) -> None:
        """Configure live signal lines, labels, limits, and legends."""

        speed_axis, egt_axis, fuel_axis, thrust_axis = self._plot_axes

        (self._speed_setpoint_line,) = speed_axis.plot(
            [],
            [],
            linestyle="--",
            color=self._WARNING_COLOR,
            linewidth=1.5,
            label="Setpoint",
        )
        (self._rotor_speed_line,) = speed_axis.plot(
            [],
            [],
            color="#98a9bc",
            linewidth=1.2,
            label="True",
        )
        (self._measured_rotor_speed_line,) = speed_axis.plot(
            [],
            [],
            color=self._ACCENT_COLOR,
            linewidth=1.5,
            label="Measured",
        )
        (self._validated_rotor_speed_line,) = speed_axis.plot(
            [],
            [],
            linestyle=":",
            color=self._SUCCESS_COLOR,
            linewidth=2.0,
            label="Validated",
        )
        self._set_plot_title(speed_axis, "ROTOR SPEED")
        speed_axis.set_ylabel("rpm")
        speed_axis.set_ylim(0.0, 165_000.0)
        speed_axis.yaxis.set_major_formatter(
            FuncFormatter(self._format_thousands_tick)
        )
        self._style_legend(speed_axis, number_of_columns=4)

        (self._egt_line,) = egt_axis.plot(
            [],
            [],
            color="#98a9bc",
            linewidth=1.2,
            label="True",
        )
        (self._measured_egt_line,) = egt_axis.plot(
            [],
            [],
            color=self._ACCENT_COLOR,
            linewidth=1.5,
            label="Measured",
        )
        (self._validated_egt_line,) = egt_axis.plot(
            [],
            [],
            linestyle=":",
            color=self._SUCCESS_COLOR,
            linewidth=2.0,
            label="Validated",
        )
        snapshot = self.dashboard_simulation.service.get_latest_snapshot()
        egt_axis.axhline(
            snapshot.egt_intervention_temperature_c,
            color=self._WARNING_COLOR,
            linestyle="--",
            linewidth=1.2,
            label="Intervention",
        )
        egt_axis.axhline(
            snapshot.egt_maximum_temperature_c,
            color=self._DANGER_COLOR,
            linestyle="--",
            linewidth=1.2,
            label="Limit",
        )
        self._set_plot_title(egt_axis, "EXHAUST GAS TEMPERATURE")
        egt_axis.set_ylabel("°C")
        egt_axis.set_ylim(0.0, 1_050.0)
        self._style_legend(egt_axis, number_of_columns=5)

        (self._requested_fuel_line,) = fuel_axis.plot(
            [],
            [],
            color="#98a9bc",
            linewidth=1.3,
            label="Requested",
        )
        (self._allowed_fuel_line,) = fuel_axis.plot(
            [],
            [],
            color=self._ACCENT_COLOR,
            linewidth=2.0,
            label="Allowed",
        )
        self._set_plot_title(fuel_axis, "FUEL COMMAND")
        fuel_axis.set_ylabel("normalized")
        fuel_axis.set_ylim(-0.05, 1.05)
        self._style_legend(fuel_axis, number_of_columns=2)

        (self._thrust_line,) = thrust_axis.plot(
            [],
            [],
            color="#a78bfa",
            linewidth=2.0,
            label="Estimated thrust",
        )
        self._set_plot_title(thrust_axis, "ESTIMATED THRUST")
        thrust_axis.set_xlabel("Simulation time [s]")
        thrust_axis.set_ylabel("N")
        thrust_axis.set_ylim(0.0, 150.0)
        self._style_legend(thrust_axis, number_of_columns=1)

        for axis in self._plot_axes:
            axis.set_facecolor(self._PLOT_COLOR)
            axis.tick_params(
                colors=self._MUTED_TEXT_COLOR,
                labelsize=8,
                length=3,
            )
            axis.xaxis.label.set_color(self._MUTED_TEXT_COLOR)
            axis.yaxis.label.set_color(self._MUTED_TEXT_COLOR)
            for spine in axis.spines.values():
                spine.set_color(self._BORDER_COLOR)
                spine.set_linewidth(0.8)
            axis.grid(
                color=self._GRID_COLOR,
                linewidth=0.7,
                alpha=0.75,
            )
            axis.set_xlim(0.0, min(10.0, self.history_window_s))

    def _set_plot_title(self, axis: Axes, title: str) -> None:
        """Add a compact, left-aligned signal title."""

        axis.set_title(
            title,
            loc="left",
            fontsize=9,
            fontweight="bold",
            color=self._TEXT_COLOR,
            pad=5,
        )

    def _style_legend(self, axis: Axes, number_of_columns: int) -> None:
        """Create a compact plot legend matching the dashboard theme."""

        legend = axis.legend(
            loc="upper right",
            ncol=number_of_columns,
            frameon=False,
            fontsize=7.5,
            handlelength=2.0,
            columnspacing=1.0,
        )
        for text in legend.get_texts():
            text.set_color(self._MUTED_TEXT_COLOR)

    def _on_timer(self) -> bool:
        """Advance and redraw from elapsed monotonic wall time."""

        if self._closed:
            return False

        current_time = time.monotonic()
        elapsed_wall_time_s = current_time - self._last_update_time
        self._last_update_time = current_time
        self.advance_and_refresh(elapsed_wall_time_s)
        return True

    def _refresh_dashboard(self, snapshot: EngineSimulationSnapshot) -> None:
        """Refresh live signal lines and dashboard status text."""

        history = self.dashboard_simulation.history
        self._set_line_data(
            self._speed_setpoint_line,
            history.times_s,
            history.speed_setpoints_rpm,
        )
        self._set_line_data(
            self._rotor_speed_line,
            history.times_s,
            history.rotor_speeds_rpm,
        )
        self._set_line_data(
            self._measured_rotor_speed_line,
            history.times_s,
            history.measured_rotor_speeds_rpm,
        )
        self._set_line_data(
            self._validated_rotor_speed_line,
            history.times_s,
            history.validated_rotor_speeds_rpm,
        )
        self._set_line_data(
            self._egt_line,
            history.times_s,
            history.exhaust_temperatures_c,
        )
        self._set_line_data(
            self._measured_egt_line,
            history.times_s,
            history.measured_exhaust_temperatures_c,
        )
        self._set_line_data(
            self._validated_egt_line,
            history.times_s,
            history.validated_exhaust_temperatures_c,
        )
        self._set_line_data(
            self._requested_fuel_line,
            history.times_s,
            history.requested_fuel_commands,
        )
        self._set_line_data(
            self._allowed_fuel_line,
            history.times_s,
            history.allowed_fuel_commands,
        )
        self._set_line_data(
            self._thrust_line,
            history.times_s,
            history.estimated_thrusts_n,
        )

        window_end_s = max(
            snapshot.simulation_time_s,
            min(10.0, self.history_window_s),
        )
        window_start_s = max(
            0.0,
            snapshot.simulation_time_s - self.history_window_s,
        )
        for axis in self._plot_axes:
            axis.set_xlim(window_start_s, window_end_s)

        self._update_status(snapshot)
        self._update_scenario_status()
        self._update_recording_status()
        self._update_timing_panel()
        self._figure.canvas.draw_idle()

    def _update_status(self, snapshot: EngineSimulationSnapshot) -> None:
        """Update operating-state, telemetry, and transition indicators."""

        state_color = self._state_color(snapshot.operating_state)
        self._state_text.set_text(snapshot.operating_state.value)
        self._state_text.get_bbox_patch().set_facecolor(state_color)
        self._sensor_health_text.set_text(
            f"SENSORS  {snapshot.aggregate_sensor_health.value}"
        )
        self._sensor_health_text.get_bbox_patch().set_facecolor(
            self._health_color(snapshot.aggregate_sensor_health)
        )
        self._time_text.set_text(f"T+ {snapshot.simulation_time_s:7.2f} s")
        self._telemetry_text.set_text(
            "RPM T/R/V  "
            f"{self._compact_value(snapshot.rotor_speed_rpm, decimals=0)}/"
            f"{self._compact_value(snapshot.measured_rotor_speed_rpm, decimals=0)}/"
            f"{self._compact_value(snapshot.validated_rotor_speed_rpm, decimals=0)}\n"
            f"RPM health {snapshot.rotor_speed_health.value:>7s} "
            f"Δ {self._compact_value(snapshot.rotor_speed_measurement_error_rpm, decimals=0, show_sign=True)} | "
            f"{snapshot.rotor_speed_diagnostic_reason.value}\n"
            f"    fault  {self._shorten(snapshot.rotor_speed_fault, 44)}\n"
            "EGT T/R/V  "
            f"{self._compact_value(snapshot.exhaust_temperature_c, decimals=1)}/"
            f"{self._compact_value(snapshot.measured_exhaust_temperature_c, decimals=1)}/"
            f"{self._compact_value(snapshot.validated_exhaust_temperature_c, decimals=1)}\n"
            f"EGT health {snapshot.exhaust_temperature_health.value:>7s} "
            f"Δ {self._compact_value(snapshot.exhaust_temperature_measurement_error_c, decimals=1, show_sign=True)} | "
            f"{snapshot.exhaust_temperature_diagnostic_reason.value}\n"
            f"    fault  {self._shorten(snapshot.exhaust_temperature_fault, 44)}\n"
            f"Sensors    {snapshot.aggregate_sensor_health.value:>7s} | "
            f"P {snapshot.active_protection_limiter.value} | "
            f"Auto {self._on_off(snapshot.automatic_sensor_fault_request_active)}\n"
            f"Fuel req/allow  {snapshot.requested_fuel_command:.3f}/"
            f"{snapshot.allowed_fuel_command:.3f} | "
            f"Throttle {snapshot.throttle_demand:.0%}\n"
            f"Starter {self._on_off(snapshot.starter_commanded):>3s} | "
            f"Ignition {self._on_off(snapshot.ignition_commanded):>3s} | "
            f"EGT limit {self._on_off(snapshot.egt_limiter_active):>3s}\n"
            f"Sample R/E {snapshot.rotor_speed_sensor_sample_period_s:.3f}/"
            f"{snapshot.exhaust_temperature_sensor_sample_period_s:.3f} s"
        )

        if snapshot.previous_operating_state is not snapshot.operating_state:
            self._transition_text.set_text(
                f"●  Transition  {snapshot.previous_operating_state.value} → "
                f"{snapshot.operating_state.value}"
            )
            self._transition_text.set_color(self._ACCENT_COLOR)

        events = self.dashboard_simulation.get_recent_events()
        if (
            events
            and events[-1].event_sequence
            > self._last_displayed_event_sequence
        ):
            latest_event = events[-1]
            self._transition_text.set_text(
                f"●  {latest_event.simulation_time_s:6.2f} s  /  "
                f"{latest_event.message}"
            )
            self._transition_text.set_color(self._WARNING_COLOR)
            self._last_displayed_event_sequence = latest_event.event_sequence

        self._update_throttle_lever(snapshot.throttle_demand)
        self._throttle_value_text.set_text(
            f"{snapshot.throttle_demand:.0%}"
        )

    def _on_throttle_changed(self, throttle_command: float) -> None:
        """Apply a persistent throttle demand from the slider."""

        if not self._manual_control_available():
            return
        self.dashboard_simulation.controls.set_throttle(throttle_command)
        self._update_throttle_lever(throttle_command)
        self._throttle_value_text.set_text(f"{throttle_command:.0%}")

    def _on_fault_channel_changed(self, channel_label: str) -> None:
        """Select the faulted sensor channel and refresh the value hint."""

        channel = (
            SensorChannel.ROTOR_SPEED
            if channel_label == "Rotor speed"
            else SensorChannel.EXHAUST_TEMPERATURE
        )
        fault_controls = self.dashboard_simulation.sensor_fault_controls
        fault_controls.select_channel(channel)
        self._refresh_fault_value_input()

    def _on_fault_type_changed(self, fault_type_label: str) -> None:
        """Select a typed fault and refresh its channel-specific value hint."""

        fault_type = next(
            fault_type
            for fault_type in DashboardFaultType
            if fault_type.value == fault_type_label
        )
        fault_controls = self.dashboard_simulation.sensor_fault_controls
        fault_controls.select_fault_type(fault_type)
        self._refresh_fault_value_input()

    def _on_fault_value_changed(self, value_text: str) -> None:
        """Retain the current fault value text for a later injection action."""

        self.dashboard_simulation.sensor_fault_controls.set_value_text(
            value_text
        )

    def _refresh_fault_value_input(self) -> None:
        """Refresh the suggested value and explanatory input hint."""

        fault_controls = self.dashboard_simulation.sensor_fault_controls
        self._fault_value_text_box.set_val(fault_controls.value_text)
        self._fault_value_hint_text.set_text(fault_controls.value_hint())

    def _on_inject_sensor_fault(self, _event: object) -> None:
        """Inject or replace the selected fault and report validation errors."""

        if not self._manual_control_available():
            return
        fault_controls = self.dashboard_simulation.sensor_fault_controls
        fault_controls.set_value_text(self._fault_value_text_box.text)
        try:
            message = fault_controls.inject(
                self.dashboard_simulation.service
            )
        except ValueError as error:
            self._set_fault_feedback(
                f"Invalid fault input: {error}",
                self._DANGER_COLOR,
            )
            return
        self._set_fault_feedback(message, self._DANGER_COLOR)

    def _on_clear_sensor_fault(self, _event: object) -> None:
        """Clear the selected channel and expose validator recovery."""

        if not self._manual_control_available():
            return
        message = self.dashboard_simulation.sensor_fault_controls.clear_selected(
            self.dashboard_simulation.service
        )
        self._set_fault_feedback(message, self._ACCENT_COLOR)

    def _on_clear_all_sensor_faults(self, _event: object) -> None:
        """Clear all channel faults and expose validator recovery."""

        if not self._manual_control_available():
            return
        message = self.dashboard_simulation.sensor_fault_controls.clear_all(
            self.dashboard_simulation.service
        )
        self._set_fault_feedback(message, self._ACCENT_COLOR)

    def _set_fault_feedback(self, message: str, color: str) -> None:
        """Update immediate dashboard feedback for a fault-control action."""

        self._fault_feedback_text.set_text(message)
        self._fault_feedback_text.set_color(color)
        self._figure.canvas.draw_idle()

    def _on_start(self, _event: object) -> None:
        """Queue a one-shot startup request."""

        if not self._manual_control_available():
            return
        self.dashboard_simulation.controls.request_startup()

    def _on_shutdown(self, _event: object) -> None:
        """Queue a one-shot shutdown request."""

        if not self._manual_control_available():
            return
        self.dashboard_simulation.controls.request_shutdown()

    def _on_fault(self, _event: object) -> None:
        """Queue a one-shot fault request."""

        if not self._manual_control_available():
            return
        self.dashboard_simulation.controls.request_fault()

    def _on_reset(self, _event: object) -> None:
        """Queue a one-shot fault-reset request."""

        if not self._manual_control_available():
            return
        self.dashboard_simulation.controls.request_reset()

    def _on_start_recording(self, _event: object) -> None:
        """Start recording using the run name entered in the dashboard."""

        if not self._manual_control_available():
            return
        run_name = self._recording_run_name_text_box.text.strip() or None
        try:
            run_directory = self.dashboard_simulation.service.start_recording(
                run_name
            )
        except (OSError, RuntimeError) as error:
            self._set_recording_feedback(
                f"Recording error: {error}",
                self._DANGER_COLOR,
            )
            return
        self._set_recording_feedback(
            f"Recording started  /  {run_directory.name}",
            self._DANGER_COLOR,
        )
        self._update_recording_status()

    def _on_stop_recording(self, _event: object) -> None:
        """Finalize the active dashboard recording safely."""

        if not self._manual_control_available():
            return
        try:
            summary = self.dashboard_simulation.service.stop_recording()
        except OSError as error:
            self._set_recording_feedback(
                f"Recording stop error: {error}",
                self._DANGER_COLOR,
            )
            return
        if summary is None:
            self._set_recording_feedback(
                "No recording is active",
                self._MUTED_TEXT_COLOR,
            )
        else:
            self._set_recording_feedback(
                "Recording saved  /  "
                f"{summary.telemetry_sample_count} samples  /  "
                f"{summary.event_count} events",
                self._SUCCESS_COLOR,
            )
        self._update_recording_status()

    def _update_recording_status(self) -> None:
        """Refresh recording activity and persisted row counters."""

        if self.dashboard_simulation.scenario_mode_active:
            progress = self.dashboard_simulation.scenario_progress
            result = self.dashboard_simulation.scenario_result
            if progress is not None and progress.current_recording_directory:
                status_text = "● SCN REC"
                status_color = self._DANGER_COLOR
            elif result is not None and result.run_directory is not None:
                status_text = "SCN SAVED"
                status_color = (
                    self._SUCCESS_COLOR
                    if result.overall_status is ScenarioOverallStatus.PASS
                    else self._WARNING_COLOR
                )
            else:
                status_text = "SCN READY"
                status_color = self._MUTED_TEXT_COLOR
            self._recording_status_text.set_text(status_text)
            self._recording_status_text.set_color(status_color)
            return

        service = self.dashboard_simulation.service
        status = service.get_recording_status()
        if status is None:
            status_text = "REC OFF"
            status_color = self._MUTED_TEXT_COLOR
        elif service.recorder.is_recording:
            status_text = (
                f"● REC {status.telemetry_sample_count}S/"
                f"{status.event_count}E"
            )
            status_color = self._DANGER_COLOR
        else:
            status_text = (
                f"SAVED {status.telemetry_sample_count}S/"
                f"{status.event_count}E"
            )
            status_color = self._SUCCESS_COLOR
        self._recording_status_text.set_text(status_text)
        self._recording_status_text.set_color(status_color)

    def _set_recording_feedback(self, message: str, color: str) -> None:
        """Show immediate recording feedback in the system event field."""

        self._transition_text.set_text(f"●  {message}")
        self._transition_text.set_color(color)
        self._figure.canvas.draw_idle()

    def _finalize_dashboard_recording(self) -> None:
        """Close an active recording when the dashboard itself closes."""

        try:
            self.dashboard_simulation.close()
        except OSError as error:
            self._set_recording_feedback(
                f"Recording cleanup error: {error}",
                self._DANGER_COLOR,
            )
        self._update_recording_status()

    def _on_mode_switch(self, _event: object) -> None:
        """Toggle explicitly between manual and scenario-runner ownership."""

        if self.dashboard_simulation.scenario_mode_active:
            try:
                snapshot = self.dashboard_simulation.return_to_manual_mode()
            except RuntimeError as error:
                self._set_scenario_feedback(str(error), self._WARNING_COLOR)
                return
            self._hide_scenario_dropdown()
            self._last_displayed_event_sequence = 0
            self._set_manual_controls_active(True)
            self._set_scenario_feedback(
                "Manual control restored",
                self._SUCCESS_COLOR,
            )
        else:
            try:
                snapshot = self.dashboard_simulation.enter_runner_mode()
            except RuntimeError as error:
                self._set_scenario_feedback(str(error), self._WARNING_COLOR)
                return
            self._set_manual_controls_active(False)
            self._set_scenario_feedback(
                "Runner mode ready  /  choose a scenario",
                self._ACCENT_COLOR,
            )
        self._update_runner_control_states()
        self._refresh_dashboard(snapshot)

    def _on_scenario_dropdown(self, _event: object) -> None:
        """Open or close the scenario selection dropdown."""

        if (
            not self.dashboard_simulation.scenario_mode_active
            or self.dashboard_simulation.scenario_is_running
        ):
            return
        is_open = self._scenario_dropdown_axis.get_visible()
        self._scenario_dropdown_axis.set_visible(not is_open)
        self._scenario_dropdown_selector.active = not is_open
        self._figure.canvas.draw_idle()

    def _on_timing_panel(self, _event: object) -> None:
        """Open or close the scheduler diagnostics overlay."""

        self._hide_scenario_dropdown()
        self._set_timing_panel_visible(not self._timing_panel_visible)
        self._update_timing_panel()
        self._figure.canvas.draw_idle()

    def _on_timing_preset_selected(self, preset_name: str) -> None:
        """Select an immutable scheduler preset while execution is stopped."""

        if getattr(self, "_timing_selection_callback_active", False):
            return
        try:
            selected_preset = (
                self.dashboard_simulation.select_scheduler_preset(
                    preset_name
                )
            )
        except (KeyError, RuntimeError) as error:
            self._set_scenario_feedback(str(error), self._WARNING_COLOR)
            self._restore_timing_preset_selection()
            return
        self._set_scenario_feedback(
            f"Scheduler preset selected  /  {selected_preset}",
            self._ACCENT_COLOR,
        )
        self._update_timing_panel()
        self._figure.canvas.draw_idle()

    def _restore_timing_preset_selection(self) -> None:
        """Restore the radio selection after a rejected timing change."""

        labels = tuple(
            label.get_text()
            for label in self._timing_preset_selector.labels
        )
        selected_index = labels.index(
            self.dashboard_simulation.selected_scheduler_preset
        )
        self._timing_selection_callback_active = True
        self._timing_preset_selector.set_active(selected_index)
        self._timing_selection_callback_active = False

    def _set_timing_panel_visible(self, visible: bool) -> None:
        """Show or hide every axis belonging to the timing overlay."""

        self._timing_panel_visible = visible
        self._timing_panel_axis.set_visible(visible)
        self._timing_preset_axis.set_visible(visible)
        self._timing_close_button.ax.set_visible(visible)
        self._timing_panel_button.label.set_text(
            "TIMING ▲" if visible else "TIMING"
        )

    def _update_timing_panel(self) -> None:
        """Refresh timing diagnostics at the normal dashboard UI rate."""

        diagnostics = self.dashboard_simulation.get_scheduler_diagnostics()
        self._timing_summary_text.set_text(
            f"Preset {diagnostics.preset_name}  |  "
            f"base {diagnostics.base_tick_s * 1_000.0:g} ms  |  "
            f"T+ {diagnostics.current_simulation_time_s:.3f} s  |  "
            f"tick {diagnostics.current_tick}  |  "
            f"missed {diagnostics.total_missed_release_count}"
        )
        table_lines = [
            "TASK          PERIOD PHASE PRI  EXECUTIONS   LAST      NEXT MISS",
        ]
        for task in diagnostics.tasks:
            last_execution = (
                "--"
                if task.last_execution_simulation_time_s is None
                else f"{task.last_execution_simulation_time_s:.3f}"
            )
            table_lines.append(
                f"{task.task_name[:13]:13s} "
                f"{task.effective_period_s * 1_000.0:5g} "
                f"{task.phase_offset_ticks * diagnostics.base_tick_s * 1_000.0:5g} "
                f"{task.priority:3d} "
                f"{task.execution_count:11d} "
                f"{last_execution:>7s} "
                f"{task.next_release_simulation_time_s:9.3f} "
                f"{task.missed_release_count:4d}"
            )
        self._timing_table_text.set_text("\n".join(table_lines))

        snapshot = self.dashboard_simulation.get_latest_snapshot()
        preset_change_allowed = (
            not self.dashboard_simulation.scenario_is_running
            and (
                self.dashboard_simulation.scenario_mode_active
                or snapshot.operating_state is EngineOperatingState.OFF
            )
        )
        self._timing_preset_selector.active = preset_change_allowed
        self._timing_preset_axis.set_alpha(
            1.0 if preset_change_allowed else 0.35
        )
        self._timing_instruction_text.set_color(
            self._MUTED_TEXT_COLOR
            if preset_change_allowed
            else self._WARNING_COLOR
        )

    def _on_scenario_selected(self, scenario_label: str) -> None:
        """Select one scenario from the runner-mode dropdown."""

        try:
            scenario_index = self._scenario_dropdown_labels.index(
                scenario_label
            )
            scenario = self.dashboard_simulation.select_scenario(
                scenario_index
            )
        except (RuntimeError, ValueError) as error:
            self._set_scenario_feedback(str(error), self._WARNING_COLOR)
            return
        self._hide_scenario_dropdown()
        self._set_scenario_feedback(
            f"Selected {scenario.scenario_id}  /  "
            f"{self._shorten(scenario.name, 24)}",
            self._MUTED_TEXT_COLOR,
        )
        self._update_scenario_status()
        self._update_recording_status()
        self._figure.canvas.draw_idle()

    def _on_run_scenario(self, _event: object) -> None:
        """Start the selected scenario and lock conflicting manual controls."""

        if not self.dashboard_simulation.scenario_mode_active:
            self._set_scenario_feedback(
                "Switch to runner mode before starting a scenario",
                self._WARNING_COLOR,
            )
            return
        self._hide_scenario_dropdown()
        try:
            progress = self.dashboard_simulation.start_selected_scenario()
        except RuntimeError as error:
            self._set_scenario_feedback(str(error), self._DANGER_COLOR)
            return
        self._last_displayed_event_sequence = 0
        self._set_manual_controls_active(False)
        self._update_runner_control_states()
        self._set_scenario_feedback(
            f"Scenario started  /  {progress.scenario_id}",
            self._ACCENT_COLOR,
        )
        self._refresh_dashboard(progress.latest_snapshot)

    def _on_cancel_scenario(self, _event: object) -> None:
        """Cancel a running scenario and retain its report for inspection."""

        if not self.dashboard_simulation.scenario_is_running:
            self._set_scenario_feedback(
                "No scenario is currently running",
                self._MUTED_TEXT_COLOR,
            )
            return
        result = self.dashboard_simulation.cancel_scenario()
        self._update_runner_control_states()
        self._set_scenario_feedback(
            f"Scenario cancelled  /  report in "
            f"{self._result_directory_name(result.run_directory)}",
            self._WARNING_COLOR,
        )
        self._refresh_dashboard(
            self.dashboard_simulation.get_latest_snapshot()
        )

    def _update_scenario_status(self) -> None:
        """Refresh selection, progress, action counts, and final verdict."""

        scenario = self.dashboard_simulation.selected_scenario
        compact_name = scenario.name.replace("_", " ")
        self._scenario_dropdown_button.label.set_text(
            f"{self._shorten(compact_name, 24)}  ▼"
        )

        progress = self.dashboard_simulation.scenario_progress
        result = self.dashboard_simulation.scenario_result
        if (
            self.dashboard_simulation.operating_mode
            is DashboardOperatingMode.MANUAL
        ):
            status_text = "MANUAL CONTROL"
            status_color = self._MUTED_TEXT_COLOR
        elif progress is not None and progress.execution_state is (
            ScenarioExecutionState.RUNNING
        ):
            executed_actions = progress.completed_action_count
            total_actions = (
                progress.completed_action_count
                + progress.pending_action_count
                + progress.failed_action_count
            )
            status_text = (
                f"RUN {progress.current_simulation_time_s:4.1f}/"
                f"{progress.maximum_duration_s:g}s  "
                f"A {executed_actions}/{total_actions}"
            )
            status_color = self._ACCENT_COLOR
        elif result is not None:
            status_text = (
                f"{result.overall_status.value}  "
                f"R {result.passed_requirement_count}/"
                f"{len(result.requirement_results)}"
            )
            status_color = (
                self._SUCCESS_COLOR
                if result.overall_status is ScenarioOverallStatus.PASS
                else self._DANGER_COLOR
            )
        elif progress is not None:
            status_text = progress.execution_state.value
            status_color = self._WARNING_COLOR
        else:
            status_text = "SCENARIO READY"
            status_color = self._MUTED_TEXT_COLOR

        self._scenario_progress_text.set_text(status_text)
        self._scenario_progress_text.set_color(status_color)
        self._mode_switch_button.label.set_text(
            "RUNNER  ○●"
            if self.dashboard_simulation.scenario_mode_active
            else "MANUAL  ●○"
        )
        self._mode_switch_button.ax.set_facecolor(
            "#176c54"
            if self.dashboard_simulation.scenario_mode_active
            else "#234e70"
        )
        if hasattr(self, "_manual_control_widgets"):
            self._update_runner_control_states()

    def _manual_control_available(self) -> bool:
        """Reject direct commands while scenario actions own the simulation."""

        if not self.dashboard_simulation.scenario_mode_active:
            return True
        self._set_scenario_feedback(
            "Scenario mode owns engine and sensor commands",
            self._WARNING_COLOR,
        )
        return False

    def _set_manual_controls_active(self, active: bool) -> None:
        """Enable or visually mute controls that conflict with scenarios."""

        for widget in self._manual_control_widgets:
            widget.active = active
            widget.ax.set_alpha(1.0 if active else 0.35)

    def _update_runner_control_states(self) -> None:
        """Enable only runner widgets valid for the current execution state."""

        runner_mode = self.dashboard_simulation.scenario_mode_active
        running = self.dashboard_simulation.scenario_is_running
        self._set_widget_active(
            self._mode_switch_button,
            not running,
        )
        self._set_widget_active(
            self._scenario_dropdown_button,
            runner_mode and not running,
        )
        self._set_widget_active(
            self._run_scenario_button,
            runner_mode and not running,
        )
        self._set_widget_active(
            self._cancel_scenario_button,
            runner_mode and running,
        )
        if not runner_mode or running:
            self._hide_scenario_dropdown()

    def _hide_scenario_dropdown(self) -> None:
        """Close and deactivate the scenario dropdown overlay."""

        self._scenario_dropdown_axis.set_visible(False)
        self._scenario_dropdown_selector.active = False

    @staticmethod
    def _set_widget_active(widget: AxesWidget, active: bool) -> None:
        """Set a Matplotlib widget's event and visual active state."""

        widget.active = active
        widget.ax.set_alpha(1.0 if active else 0.35)

    def _set_scenario_feedback(self, message: str, color: str) -> None:
        """Show immediate scenario-control feedback in the event field."""

        self._transition_text.set_text(f"●  {message}")
        self._transition_text.set_color(color)
        self._figure.canvas.draw_idle()

    @staticmethod
    def _result_directory_name(run_directory: Path | None) -> str:
        """Return a concise artifact directory name for scenario feedback."""

        return run_directory.name if run_directory is not None else "artifacts"

    def _on_quit(self, _event: object) -> None:
        """Save the final view and close the dashboard."""

        self.close(save_result=True)

    def _on_figure_close(self, _event: object) -> None:
        """Save final results when the window manager closes the figure."""

        if self._closed:
            return
        self._finalize_dashboard_recording()
        self.save_figure()
        self._closed = True
        self._timer.stop()

    @staticmethod
    def _set_line_data(
        line: Line2D,
        times_s: list[float],
        values: list[float | None],
    ) -> None:
        """Set both axes of one live signal line."""

        line.set_data(times_s, values)

    @staticmethod
    def _format_thousands_tick(value: float, _position: float) -> str:
        """Format a rotor-speed axis value using a compact thousands suffix."""

        if value == 0.0:
            return "0"
        return f"{value / 1_000.0:g}k"

    @staticmethod
    def _compact_value(
        value: float | None,
        *,
        decimals: int,
        show_sign: bool = False,
    ) -> str:
        """Format telemetry within a bounded width, including extreme faults."""

        if value is None:
            return "--"

        sign = "+" if show_sign else ""
        if abs(value) >= 10_000_000.0:
            return format(value, f"{sign}.2e")
        return format(value, f"{sign}.{decimals}f")

    @staticmethod
    def _shorten(value: str, maximum_characters: int) -> str:
        """Keep diagnostic text inside the fixed-width status card."""

        if len(value) <= maximum_characters:
            return value
        return f"{value[: maximum_characters - 1]}…"

    @staticmethod
    def _on_off(value: bool) -> str:
        """Return a concise boolean status label."""

        return "ON" if value else "OFF"

    @staticmethod
    def _state_color(state: EngineOperatingState) -> str:
        """Return a status color for an engine operating state."""

        state_colors = {
            EngineOperatingState.OFF: "#53657a",
            EngineOperatingState.CRANKING: "#2878b5",
            EngineOperatingState.IGNITION: "#a36b14",
            EngineOperatingState.IDLE: "#21845f",
            EngineOperatingState.RUNNING: "#167252",
            EngineOperatingState.SHUTDOWN: "#806523",
            EngineOperatingState.FAULT: "#9b3242",
        }
        return state_colors[state]

    @classmethod
    def _health_color(cls, health: ChannelHealth) -> str:
        """Return a high-contrast color for aggregate sensor health."""

        health_colors = {
            ChannelHealth.VALID: cls._SUCCESS_COLOR,
            ChannelHealth.SUSPECT: cls._WARNING_COLOR,
            ChannelHealth.INVALID: cls._DANGER_COLOR,
        }
        return health_colors[health]
