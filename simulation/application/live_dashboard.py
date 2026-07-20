"""Matplotlib-based live dashboard for the Mini-FADEC simulation."""

from pathlib import Path
import time

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.lines import Line2D
from matplotlib.widgets import Button, Slider

from simulation.application.dashboard_model import DashboardSimulation
from simulation.application.engine_simulation import EngineSimulationSnapshot
from simulation.operation.engine_state import EngineOperatingState


class LiveEngineDashboard:
    """Display live engine signals and graphical operator controls."""

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
        self._last_update_time = time.monotonic()
        self._figure, self._plot_axes = self._create_figure()
        self._create_status_panel()
        self._create_controls()
        self._create_signal_plots()

        self._timer = self._figure.canvas.new_timer(
            interval=max(1, int(self.refresh_interval_s * 1_000.0))
        )
        self._timer.add_callback(self._on_timer)
        self._figure.canvas.mpl_connect("close_event", self._on_figure_close)
        self._refresh_dashboard(self.dashboard_simulation.coordinator.snapshot)

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
            figsize=(14.0, 9.0),
        )
        figure.subplots_adjust(
            left=0.28,
            right=0.97,
            bottom=0.08,
            top=0.94,
            hspace=0.35,
        )
        figure.canvas.manager.set_window_title("Mini-FADEC Live Dashboard")
        figure.suptitle("Mini-FADEC Live Engine Dashboard", fontsize=16)
        return figure, tuple(plot_axes)

    def _create_status_panel(self) -> None:
        """Create the operating-state and telemetry text panel."""

        self._state_text = self._figure.text(
            0.025,
            0.91,
            "OFF",
            fontsize=19,
            fontweight="bold",
            color="white",
            bbox={
                "boxstyle": "round,pad=0.45",
                "facecolor": "0.35",
                "edgecolor": "none",
            },
        )
        self._telemetry_text = self._figure.text(
            0.025,
            0.84,
            "",
            fontsize=10,
            family="monospace",
            verticalalignment="top",
            linespacing=1.5,
        )
        self._transition_text = self._figure.text(
            0.025,
            0.59,
            "Ready",
            fontsize=9,
            color="0.3",
            wrap=True,
        )

    def _create_controls(self) -> None:
        """Create throttle lever and operator command buttons."""

        throttle_axis = self._figure.add_axes((0.055, 0.28, 0.035, 0.25))
        self._throttle_slider = Slider(
            ax=throttle_axis,
            label="Throttle",
            valmin=0.0,
            valmax=1.0,
            valinit=0.0,
            valstep=0.01,
            orientation="vertical",
            color="tab:blue",
        )
        self._throttle_slider.on_changed(self._on_throttle_changed)

        self._start_button = self._create_button(
            bounds=(0.025, 0.20, 0.095, 0.05),
            label="START",
            color="#b8e0b8",
            callback=self._on_start,
        )
        self._shutdown_button = self._create_button(
            bounds=(0.135, 0.20, 0.095, 0.05),
            label="SHUTDOWN",
            color="#f4d4a9",
            callback=self._on_shutdown,
        )
        self._fault_button = self._create_button(
            bounds=(0.025, 0.13, 0.095, 0.05),
            label="FAULT",
            color="#efaaaa",
            callback=self._on_fault,
        )
        self._reset_button = self._create_button(
            bounds=(0.135, 0.13, 0.095, 0.05),
            label="RESET",
            color="#c7d7ef",
            callback=self._on_reset,
        )
        self._quit_button = self._create_button(
            bounds=(0.025, 0.055, 0.205, 0.05),
            label="SAVE & QUIT",
            color="#d0d0d0",
            callback=self._on_quit,
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
        button = Button(button_axis, label, color=color, hovercolor="0.9")
        button.on_clicked(callback)
        return button

    def _create_signal_plots(self) -> None:
        """Configure live signal lines, labels, limits, and legends."""

        speed_axis, egt_axis, fuel_axis, thrust_axis = self._plot_axes

        (self._speed_setpoint_line,) = speed_axis.plot(
            [],
            [],
            linestyle="--",
            label="Setpoint",
        )
        (self._rotor_speed_line,) = speed_axis.plot([], [], label="True")
        (self._measured_rotor_speed_line,) = speed_axis.plot(
            [],
            [],
            label="Measured",
        )
        speed_axis.set_ylabel("Rotor speed\n[rpm]")
        speed_axis.set_ylim(0.0, 135_000.0)
        speed_axis.legend(loc="upper left")

        (self._egt_line,) = egt_axis.plot([], [], label="True EGT")
        (self._measured_egt_line,) = egt_axis.plot(
            [],
            [],
            label="Measured EGT",
        )
        egt_axis.axhline(
            self.dashboard_simulation.coordinator.egt_limiter.parameters.intervention_exhaust_temperature_c,
            color="tab:orange",
            linestyle="--",
            label="Intervention",
        )
        egt_axis.axhline(
            self.dashboard_simulation.coordinator.egt_limiter.parameters.maximum_exhaust_temperature_c,
            color="tab:red",
            linestyle="--",
            label="Limit",
        )
        egt_axis.set_ylabel("EGT [°C]")
        egt_axis.set_ylim(0.0, 750.0)
        egt_axis.legend(loc="upper left")

        (self._requested_fuel_line,) = fuel_axis.plot(
            [],
            [],
            label="Requested",
        )
        (self._allowed_fuel_line,) = fuel_axis.plot(
            [],
            [],
            label="Allowed",
        )
        fuel_axis.set_ylabel("Fuel command [-]")
        fuel_axis.set_ylim(-0.05, 1.05)
        fuel_axis.legend(loc="upper left")

        (self._thrust_line,) = thrust_axis.plot([], [], label="Thrust")
        thrust_axis.set_xlabel("Simulation time [s]")
        thrust_axis.set_ylabel("Thrust [N]")
        thrust_axis.set_ylim(0.0, 150.0)

        for axis in self._plot_axes:
            axis.grid()
            axis.set_xlim(0.0, min(10.0, self.history_window_s))

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
        self._figure.canvas.draw_idle()

    def _update_status(self, snapshot: EngineSimulationSnapshot) -> None:
        """Update operating-state, telemetry, and transition indicators."""

        state_color = self._state_color(snapshot.operating_state)
        self._state_text.set_text(snapshot.operating_state.value)
        self._state_text.get_bbox_patch().set_facecolor(state_color)
        self._telemetry_text.set_text(
            f"Time       {snapshot.simulation_time_s:7.2f} s\n"
            f"Throttle   {self.dashboard_simulation.controls.throttle_command:7.3f}\n"
            f"RPM T/M/E  {snapshot.rotor_speed_rpm:7.0f}/"
            f"{snapshot.measured_rotor_speed_rpm:.0f}/"
            f"{snapshot.rotor_speed_measurement_error_rpm:+.0f}\n"
            f"EGT T/M/E  {snapshot.exhaust_temperature_c:7.1f}/"
            f"{snapshot.measured_exhaust_temperature_c:.1f}/"
            f"{snapshot.exhaust_temperature_measurement_error_c:+.1f} °C\n"
            f"Sample R/E {snapshot.rotor_speed_sensor_sample_period_s:7.3f}/"
            f"{snapshot.exhaust_temperature_sensor_sample_period_s:.3f} s\n"
            f"Fuel req.  {snapshot.requested_fuel_command:7.3f}\n"
            f"Fuel allow {snapshot.allowed_fuel_command:7.3f}\n"
            f"Starter    {self._on_off(snapshot.starter_commanded):>7s}\n"
            f"Ignition   {self._on_off(snapshot.ignition_commanded):>7s}\n"
            f"EGT limit  {self._on_off(snapshot.egt_limiter_active):>7s}"
        )

        if snapshot.previous_operating_state is not snapshot.operating_state:
            self._transition_text.set_text(
                f"Transition: {snapshot.previous_operating_state.value} → "
                f"{snapshot.operating_state.value}"
            )

    def _on_throttle_changed(self, throttle_command: float) -> None:
        """Apply a persistent throttle demand from the slider."""

        self.dashboard_simulation.controls.set_throttle(throttle_command)

    def _on_start(self, _event: object) -> None:
        """Queue a one-shot startup request."""

        self.dashboard_simulation.controls.request_startup()

    def _on_shutdown(self, _event: object) -> None:
        """Queue a one-shot shutdown request."""

        self.dashboard_simulation.controls.request_shutdown()

    def _on_fault(self, _event: object) -> None:
        """Queue a one-shot fault request."""

        self.dashboard_simulation.controls.request_fault()

    def _on_reset(self, _event: object) -> None:
        """Queue a one-shot fault-reset request."""

        self.dashboard_simulation.controls.request_reset()

    def _on_quit(self, _event: object) -> None:
        """Save the final view and close the dashboard."""

        self.close(save_result=True)

    def _on_figure_close(self, _event: object) -> None:
        """Save final results when the window manager closes the figure."""

        if self._closed:
            return
        self.save_figure()
        self._closed = True
        self._timer.stop()

    @staticmethod
    def _set_line_data(
        line: Line2D,
        times_s: list[float],
        values: list[float],
    ) -> None:
        """Set both axes of one live signal line."""

        line.set_data(times_s, values)

    @staticmethod
    def _on_off(value: bool) -> str:
        """Return a concise boolean status label."""

        return "ON" if value else "OFF"

    @staticmethod
    def _state_color(state: EngineOperatingState) -> str:
        """Return a status color for an engine operating state."""

        state_colors = {
            EngineOperatingState.OFF: "#606060",
            EngineOperatingState.CRANKING: "#4178a8",
            EngineOperatingState.IGNITION: "#d17b0f",
            EngineOperatingState.IDLE: "#4b8f57",
            EngineOperatingState.RUNNING: "#247036",
            EngineOperatingState.SHUTDOWN: "#8b6d31",
            EngineOperatingState.FAULT: "#b22222",
        }
        return state_colors[state]
