"""Non-blocking terminal application for an interactive engine simulation."""

import argparse
from dataclasses import dataclass
from queue import Empty, Queue
import sys
from threading import Thread
import time
from typing import TextIO

from simulation.application.engine_simulation import (
    EngineSimulationCoordinator,
    EngineSimulationSnapshot,
)
from simulation.application.simulation_service import SimulationService
from simulation.operation.engine_state import EngineOperatingState
from simulation.operation.state_machine import EngineOperationRequest
from simulation.protection.types import ProtectionLimiter
from simulation.sensors.fault_injection import (
    BiasSensorFault,
    DriftSensorFault,
    DropoutSensorFault,
    ExcessiveNoiseSensorFault,
    ForcedValueSensorFault,
    SensorChannel,
    StuckSensorFault,
)


@dataclass(frozen=True)
class ParsedCommand:
    """Parsed terminal command with an optional numeric value."""

    name: str
    argument: str | None = None
    value: float | None = None
    text: str | None = None


def parse_command(command_text: str) -> ParsedCommand:
    """Parse and validate one terminal command."""

    command_parts = command_text.strip().split()
    if not command_parts:
        raise ValueError("empty command")

    command_name = command_parts[0].lower()
    commands_without_values = {
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
    }
    if command_name in commands_without_values:
        if len(command_parts) != 1:
            raise ValueError(f"{command_name} does not accept a value")
        return ParsedCommand(name=command_name)

    if command_name == "throttle":
        if len(command_parts) != 2:
            raise ValueError("usage: throttle <value>")
        try:
            throttle_command = float(command_parts[1])
        except ValueError as error:
            raise ValueError("throttle value must be numeric") from error
        return ParsedCommand(name=command_name, value=throttle_command)

    if command_name == "clear_fault":
        if len(command_parts) != 2 or command_parts[1] not in {"rpm", "egt"}:
            raise ValueError("usage: clear_fault <rpm|egt>")
        return ParsedCommand(name=command_name, argument=command_parts[1])

    if command_name == "inject":
        return _parse_inject_command(command_parts)

    if command_name == "record":
        if len(command_parts) < 2 or command_parts[1] not in {
            "start",
            "stop",
            "status",
        }:
            raise ValueError("usage: record <start [run_name]|stop|status>")
        action = command_parts[1]
        if action == "start":
            if len(command_parts) > 3:
                raise ValueError("usage: record start [run_name]")
            run_name = command_parts[2] if len(command_parts) == 3 else None
            return ParsedCommand(name="record", argument=action, text=run_name)
        if len(command_parts) != 2:
            raise ValueError(f"record {action} does not accept a value")
        return ParsedCommand(name="record", argument=action)

    if command_name == "mark":
        marker_text = command_text.strip().partition(" ")[2].strip()
        if not marker_text:
            raise ValueError("usage: mark <text>")
        return ParsedCommand(name="mark", text=marker_text)

    raise ValueError(f"unknown command: {command_name}")


def _parse_inject_command(command_parts: list[str]) -> ParsedCommand:
    """Parse one sensor fault-injection command."""

    if len(command_parts) < 2:
        raise ValueError("usage: inject <fault> [value]")

    fault_name = command_parts[1]
    faults_requiring_value = {
        "rpm_bias",
        "egt_bias",
        "rpm_value",
        "egt_value",
        "rpm_noise",
        "egt_noise",
        "rpm_drift",
        "egt_drift",
    }
    stuck_faults = {"rpm_stuck", "egt_stuck"}
    dropout_faults = {"rpm_dropout", "egt_dropout"}

    if fault_name in faults_requiring_value:
        if len(command_parts) != 3:
            raise ValueError(f"usage: inject {fault_name} <value>")
    elif fault_name in stuck_faults:
        if len(command_parts) not in {2, 3}:
            raise ValueError(f"usage: inject {fault_name} [value]")
    elif fault_name in dropout_faults:
        if len(command_parts) != 2:
            raise ValueError(f"inject {fault_name} does not accept a value")
    else:
        raise ValueError(f"unknown sensor fault: {fault_name}")

    value = None
    if len(command_parts) == 3:
        try:
            value = float(command_parts[2])
        except ValueError as error:
            raise ValueError("sensor fault value must be numeric") from error
        if fault_name.endswith("_noise") and value < 0.0:
            raise ValueError("sensor fault noise cannot be negative")

    return ParsedCommand(name="inject", argument=fault_name, value=value)


class InteractiveEngineSimulation:
    """Run the coordinated simulation while processing queued commands."""

    def __init__(
        self,
        coordinator: EngineSimulationCoordinator | None = None,
        service: SimulationService | None = None,
        *,
        time_step_s: float = 0.01,
        telemetry_interval_s: float = 1.0,
        input_stream: TextIO = sys.stdin,
        output_stream: TextIO = sys.stdout,
    ) -> None:
        if coordinator is not None and service is not None:
            raise ValueError("provide either coordinator or service, not both")
        self.service = service or SimulationService(
            coordinator=coordinator,
            time_step_s=time_step_s,
        )
        # Compatibility view for existing callers; commands use the service.
        self.coordinator = self.service.coordinator
        self.time_step_s = time_step_s
        self.telemetry_interval_s = telemetry_interval_s
        self.input_stream = input_stream
        self.output_stream = output_stream

        self._command_queue: Queue[str | None] = Queue()
        self._running = True
        self._last_printed_event_sequence = 0

    def run(self) -> None:
        """Run continuously with wall-clock pacing and non-blocking input."""

        input_thread = Thread(target=self._read_input, daemon=True)
        input_thread.start()

        self._print_help()
        next_step_time = time.monotonic()
        next_telemetry_time_s = self.telemetry_interval_s

        completed = False
        try:
            while self._running:
                self._process_queued_commands()
                if not self._running:
                    break

                snapshot = self.service.step()
                self._print_new_events()

                if snapshot.simulation_time_s >= next_telemetry_time_s:
                    self._print_status(snapshot)
                    next_telemetry_time_s += self.telemetry_interval_s

                next_step_time += self.time_step_s
                delay_s = next_step_time - time.monotonic()
                if delay_s > 0.0:
                    time.sleep(delay_s)
                else:
                    next_step_time = time.monotonic()
            completed = True
        except KeyboardInterrupt:
            self._print("Simulation interrupted.")
        finally:
            self.service.close(completed=completed)

        self._print("Simulation stopped.")

    def _read_input(self) -> None:
        """Read terminal lines on a daemon thread without blocking simulation."""

        try:
            for command_text in self.input_stream:
                self._command_queue.put(command_text)
        finally:
            self._command_queue.put(None)

    def _process_queued_commands(self) -> None:
        """Process all available commands through the application service."""

        while True:
            try:
                command_text = self._command_queue.get_nowait()
            except Empty:
                break

            if command_text is None:
                self._running = False
                break

            try:
                command = parse_command(command_text)
            except ValueError as error:
                self._print(f"Invalid command: {error}")
                continue

            if command.name == "help":
                self._print_help()
            elif command.name == "start":
                self.service.request_start()
            elif command.name == "throttle":
                assert command.value is not None
                throttle = self.service.set_throttle(command.value)
                self._print(f"Throttle accepted: {throttle:.3f}")
            elif command.name == "shutdown":
                self.service.request_shutdown()
            elif command.name == "status":
                self._print_status(self.service.get_latest_snapshot())
            elif command.name == "protection":
                self._print_protection(self.service.get_latest_snapshot())
            elif command.name == "fault":
                self.service.request_fault()
            elif command.name == "faults":
                self._print_faults()
            elif command.name == "reset":
                self.service.request_reset()
            elif command.name == "inject":
                self._inject_sensor_fault(command)
            elif command.name == "clear_fault":
                self._clear_sensor_fault(command)
            elif command.name == "clear_faults":
                self.service.clear_sensor_faults()
                self._print("Cleared all injected sensor faults")
            elif command.name == "record":
                self._process_recording_command(command)
            elif command.name == "mark":
                assert command.text is not None
                self.service.add_marker(command.text)
                self._print(f"Marker recorded: {command.text}")
            elif command.name == "runs":
                self._print_recent_runs()
            elif command.name == "quit":
                self._running = False
                break

    def _inject_sensor_fault(self, command: ParsedCommand) -> None:
        """Convert a parsed request into one typed sensor fault definition."""

        assert command.argument is not None
        channel = (
            SensorChannel.ROTOR_SPEED
            if command.argument.startswith("rpm_")
            else SensorChannel.EXHAUST_TEMPERATURE
        )
        fault_kind = command.argument.split("_", maxsplit=1)[1]

        if fault_kind == "bias":
            assert command.value is not None
            fault = BiasSensorFault(offset=command.value)
        elif fault_kind == "stuck":
            fault = StuckSensorFault(value=command.value)
        elif fault_kind == "dropout":
            fault = DropoutSensorFault()
        elif fault_kind == "value":
            assert command.value is not None
            fault = ForcedValueSensorFault(value=command.value)
        elif fault_kind == "noise":
            assert command.value is not None
            fault = ExcessiveNoiseSensorFault(
                standard_deviation=command.value
            )
        else:
            assert command.value is not None
            fault = DriftSensorFault(rate_per_second=command.value)

        self.service.inject_sensor_fault(channel, fault)
        self._print(
            f"Injected {channel.value} sensor fault: "
            f"{self.service.describe_sensor_fault(channel)}"
        )

    def _clear_sensor_fault(self, command: ParsedCommand) -> None:
        """Clear the requested injected sensor fault channel."""

        assert command.argument is not None
        channel = (
            SensorChannel.ROTOR_SPEED
            if command.argument == "rpm"
            else SensorChannel.EXHAUST_TEMPERATURE
        )
        self.service.clear_sensor_fault(channel)
        self._print(f"Cleared {channel.value} sensor fault")

    def _print_faults(self) -> None:
        """Print active injected faults and current validator health."""

        snapshot = self.service.get_latest_snapshot()
        self._print(
            "Rotor-speed fault: "
            f"{self.service.describe_sensor_fault(SensorChannel.ROTOR_SPEED)} | "
            f"health: {snapshot.rotor_speed_health.value}\n"
            "EGT fault: "
            f"{self.service.describe_sensor_fault(SensorChannel.EXHAUST_TEMPERATURE)} | "
            f"health: {snapshot.exhaust_temperature_health.value}\n"
            f"Aggregate sensor health: {snapshot.aggregate_sensor_health.value}"
        )

    def _print_new_events(self) -> None:
        """Print newly recorded simulation events once."""

        events = self.service.get_recent_events()
        for event in events:
            if event.event_sequence <= self._last_printed_event_sequence:
                continue
            self._print(
                f"EVENT t={event.simulation_time_s:.2f} s: {event.message}"
            )
            self._last_printed_event_sequence = event.event_sequence

    def _print_transition(self, snapshot: EngineSimulationSnapshot) -> None:
        """Print a state transition immediately when one occurs."""

        if snapshot.previous_operating_state is not snapshot.operating_state:
            self._print(
                "State transition: "
                f"{snapshot.previous_operating_state.value} -> "
                f"{snapshot.operating_state.value}"
            )

    def _print_status(self, snapshot: EngineSimulationSnapshot) -> None:
        """Print one concise status record."""

        self._print(
            f"t={snapshot.simulation_time_s:6.2f} s | "
            f"state={snapshot.operating_state.value:8s} | "
            f"throttle={snapshot.throttle_demand:.3f}\n"
            "Rotor speed: "
            f"truth={snapshot.rotor_speed_rpm:.0f} rpm | "
            f"raw={self._format_value(snapshot.measured_rotor_speed_rpm, '.0f')} | "
            f"validated={self._format_validated_value(snapshot.validated_rotor_speed_rpm, snapshot.rotor_speed_value_is_held, '.0f')} | "
            f"error={self._format_value(snapshot.rotor_speed_measurement_error_rpm, '+.0f')} | "
            f"health={snapshot.rotor_speed_health.value} | "
            f"fault={snapshot.rotor_speed_fault} | "
            f"diagnostic={snapshot.rotor_speed_diagnostic_reason.value}\n"
            "EGT: "
            f"truth={snapshot.exhaust_temperature_c:.1f} °C | "
            f"raw={self._format_value(snapshot.measured_exhaust_temperature_c, '.1f')} | "
            f"validated={self._format_validated_value(snapshot.validated_exhaust_temperature_c, snapshot.exhaust_temperature_value_is_held, '.1f')} | "
            f"error={self._format_value(snapshot.exhaust_temperature_measurement_error_c, '+.1f')} | "
            f"health={snapshot.exhaust_temperature_health.value} | "
            f"fault={snapshot.exhaust_temperature_fault} | "
            f"diagnostic={snapshot.exhaust_temperature_diagnostic_reason.value}\n"
            f"Sensor health={snapshot.aggregate_sensor_health.value} | "
            f"automatic FAULT={snapshot.automatic_sensor_fault_request_active} | "
            f"response={snapshot.sensor_fault_response_reason} | "
            f"sample periods={snapshot.rotor_speed_sensor_sample_period_s:.3f}/"
            f"{snapshot.exhaust_temperature_sensor_sample_period_s:.3f} s | "
            f"fuel={snapshot.requested_fuel_command:.3f}/"
            f"{snapshot.allowed_fuel_command:.3f}\n"
            f"Protection: active={snapshot.active_protection_limiter.value} | "
            "constraining="
            f"{self._format_limiters(snapshot.constraining_protection_limiters)} | "
            f"hard cutoff={snapshot.protection_hard_cutoff_active} | "
            f"critical FAULT={snapshot.critical_protection_fault_request}\n"
            "Protection limits EGT/acceleration/overspeed="
            f"{snapshot.egt_fuel_limit:.3f}/"
            f"{snapshot.acceleration_fuel_limit:.3f}/"
            f"{snapshot.overspeed_fuel_limit:.3f} | "
            "deceleration minimum="
            f"{snapshot.deceleration_minimum_fuel_command:.3f} | "
            "acceleration="
            f"{self._format_optional(snapshot.rotor_acceleration_rpm_per_s, '.0f')} rpm/s | "
            f"speed ratio={self._format_optional(snapshot.speed_ratio, '.3f')} | "
            f"soft/hard overspeed={snapshot.soft_overspeed_active}/"
            f"{snapshot.hard_overspeed_active}"
        )

    def _print_protection(self, snapshot: EngineSimulationSnapshot) -> None:
        """Print the complete centralized fuel-protection result."""

        self._print(
            "Protection:\n"
            f"  requested fuel:        {snapshot.requested_fuel_command:.3f}\n"
            f"  final fuel:            {snapshot.allowed_fuel_command:.3f}\n"
            f"  active limiter:        {snapshot.active_protection_limiter.value}\n"
            "  constraining:          "
            f"{self._format_limiters(snapshot.constraining_protection_limiters)}\n"
            f"  EGT upper limit:       {snapshot.egt_fuel_limit:.3f}\n"
            "  acceleration limit:    "
            f"{snapshot.acceleration_fuel_limit:.3f}\n"
            f"  overspeed limit:       {snapshot.overspeed_fuel_limit:.3f}\n"
            "  deceleration minimum:  "
            f"{snapshot.deceleration_minimum_fuel_command:.3f}\n"
            f"  state maximum:         {snapshot.state_maximum_fuel_command:.3f}\n"
            "  rotor acceleration:    "
            f"{self._format_optional(snapshot.rotor_acceleration_rpm_per_s, '.0f')} rpm/s\n"
            "  rotor deceleration:    "
            f"{self._format_optional(snapshot.rotor_deceleration_rpm_per_s, '.0f')} rpm/s\n"
            f"  speed ratio:           {self._format_optional(snapshot.speed_ratio, '.3f')}\n"
            f"  soft overspeed:        {snapshot.soft_overspeed_active}\n"
            f"  hard overspeed:        {snapshot.hard_overspeed_active}\n"
            f"  hard cutoff:           {snapshot.protection_hard_cutoff_active}\n"
            "  critical FAULT:        "
            f"{snapshot.critical_protection_fault_request}\n"
            f"  arbitration conflict:  {snapshot.protection_arbitration_conflict}\n"
            "  diagnostics:           "
            + ", ".join(
                reason.value for reason in snapshot.protection_diagnostic_reasons
            )
        )

    def _print_help(self) -> None:
        """Print the available interactive commands."""

        self._print(
            "Commands: help, start, throttle <0.0..1.0>, shutdown, "
            "status, protection, fault, reset, faults, inject <fault> [value], "
            "clear_fault <rpm|egt>, clear_faults, record start [run_name], "
            "record stop, record status, mark <text>, runs, quit"
        )

    def _process_recording_command(self, command: ParsedCommand) -> None:
        """Start, stop, or report a run recording."""

        if command.argument == "start":
            try:
                run_directory = self.service.start_recording(command.text)
            except (OSError, RuntimeError) as error:
                self._print(f"Recording error: {error}")
                return
            self._print(f"Recording started: {run_directory}")
        elif command.argument == "stop":
            summary = self.service.stop_recording()
            if summary is None:
                self._print("No recording is active.")
            else:
                self._print(
                    "Recording stopped: "
                    f"{summary.telemetry_sample_count} samples, "
                    f"{summary.event_count} events"
                )
        else:
            self._print_recording_status()

    def _print_recording_status(self) -> None:
        """Print current or most recent recorder status."""

        status = self.service.get_recording_status()
        if status is None:
            self._print(
                "Recording inactive | no run | "
                f"period={self.service.recorder.parameters.telemetry_sampling_period_s:.3f} s"
            )
            return
        activity = "active" if self.service.recorder.is_recording else "inactive"
        self._print(
            f"Recording {activity} | status={status.completion_status} | "
            f"name={status.run_name} | directory={status.run_directory} | "
            f"samples={status.telemetry_sample_count} | "
            f"events={status.event_count} | "
            f"period={status.telemetry_sampling_period_s:.3f} s"
        )

    def _print_recent_runs(self) -> None:
        """Print a bounded list of recent run directories."""

        run_directories = self.service.list_recent_runs()
        if not run_directories:
            self._print("No recorded runs found.")
            return
        self._print("Recent runs:\n" + "\n".join(map(str, run_directories)))

    @staticmethod
    def _format_limiters(limiters: tuple[ProtectionLimiter, ...]) -> str:
        """Format enum-like limiter values without exposing collection syntax."""

        return ",".join(limiter.value for limiter in limiters) or "NONE"

    @staticmethod
    def _format_optional(value: float | None, specification: str) -> str:
        """Format optional protection telemetry."""

        return "unavailable" if value is None else format(value, specification)

    @staticmethod
    def _format_value(value: float | None, format_specification: str) -> str:
        """Format an optional raw value without converting dropout to zero."""

        if value is None:
            return "unavailable"
        return format(value, format_specification)

    @classmethod
    def _format_validated_value(
        cls,
        value: float | None,
        value_is_held: bool,
        format_specification: str,
    ) -> str:
        """Format an optional validated value and identify held fallback."""

        formatted_value = cls._format_value(value, format_specification)
        return f"{formatted_value} held" if value_is_held else formatted_value

    def _print(self, message: str) -> None:
        """Print to the configured application output stream."""

        print(message, file=self.output_stream, flush=True)

def run_scripted_smoke_test() -> None:
    """Run an accelerated startup and shutdown without terminal input."""

    coordinator = EngineSimulationCoordinator()
    time_step_s = 0.01
    throttle_command = 0.0
    startup_requested = True
    shutdown_requested = False
    running_time_s = 0.0
    previous_state = coordinator.snapshot.operating_state

    for _ in range(int(30.0 / time_step_s)):
        snapshot = coordinator.step(
            request=EngineOperationRequest(
                throttle_command=throttle_command,
                startup_requested=startup_requested,
                shutdown_requested=shutdown_requested,
            ),
            time_step_s=time_step_s,
        )
        startup_requested = False
        shutdown_requested = False

        if snapshot.operating_state is not previous_state:
            print(
                f"State transition: {previous_state.value} -> "
                f"{snapshot.operating_state.value}"
            )
            previous_state = snapshot.operating_state

        if snapshot.operating_state is EngineOperatingState.IDLE:
            throttle_command = 0.5
        elif snapshot.operating_state is EngineOperatingState.RUNNING:
            running_time_s += time_step_s
            if running_time_s >= 1.0:
                shutdown_requested = True
        elif (
            snapshot.operating_state is EngineOperatingState.OFF
            and snapshot.simulation_time_s > time_step_s
        ):
            print("Scripted startup and shutdown completed.")
            return

    raise RuntimeError("scripted startup and shutdown did not complete")


def main(arguments: list[str] | None = None) -> None:
    """Run the interactive application or its automated smoke test."""

    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="run an accelerated startup/shutdown validation",
    )
    parsed_arguments = argument_parser.parse_args(arguments)

    if parsed_arguments.smoke_test:
        run_scripted_smoke_test()
    else:
        InteractiveEngineSimulation().run()
