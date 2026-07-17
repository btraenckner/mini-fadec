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
from simulation.operation.engine_state import EngineOperatingState
from simulation.operation.state_machine import EngineOperationRequest


@dataclass(frozen=True)
class ParsedCommand:
    """Parsed terminal command with an optional numeric value."""

    name: str
    value: float | None = None


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
        "fault",
        "reset",
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

    raise ValueError(f"unknown command: {command_name}")


class InteractiveEngineSimulation:
    """Run the coordinated simulation while processing queued commands."""

    def __init__(
        self,
        coordinator: EngineSimulationCoordinator | None = None,
        *,
        time_step_s: float = 0.01,
        telemetry_interval_s: float = 1.0,
        input_stream: TextIO = sys.stdin,
        output_stream: TextIO = sys.stdout,
    ) -> None:
        self.coordinator = coordinator or EngineSimulationCoordinator()
        self.time_step_s = time_step_s
        self.telemetry_interval_s = telemetry_interval_s
        self.input_stream = input_stream
        self.output_stream = output_stream

        self._command_queue: Queue[str | None] = Queue()
        self._throttle_command = 0.0
        self._running = True

    def run(self) -> None:
        """Run continuously with wall-clock pacing and non-blocking input."""

        input_thread = Thread(target=self._read_input, daemon=True)
        input_thread.start()

        self._print_help()
        next_step_time = time.monotonic()
        next_telemetry_time_s = self.telemetry_interval_s

        try:
            while self._running:
                operation_request = self._process_queued_commands()
                if not self._running:
                    break

                snapshot = self.coordinator.step(
                    request=operation_request,
                    time_step_s=self.time_step_s,
                )
                self._print_transition(snapshot)

                if snapshot.simulation_time_s >= next_telemetry_time_s:
                    self._print_status(snapshot)
                    next_telemetry_time_s += self.telemetry_interval_s

                next_step_time += self.time_step_s
                delay_s = next_step_time - time.monotonic()
                if delay_s > 0.0:
                    time.sleep(delay_s)
                else:
                    next_step_time = time.monotonic()
        except KeyboardInterrupt:
            self._print("Simulation interrupted.")

        self._print("Simulation stopped.")

    def _read_input(self) -> None:
        """Read terminal lines on a daemon thread without blocking simulation."""

        try:
            for command_text in self.input_stream:
                self._command_queue.put(command_text)
        finally:
            self._command_queue.put(None)

    def _process_queued_commands(self) -> EngineOperationRequest:
        """Process all available commands and return one-step requests."""

        startup_requested = False
        shutdown_requested = False
        fault_requested = False
        reset_requested = False

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
                startup_requested = True
            elif command.name == "throttle":
                assert command.value is not None
                self._throttle_command = self._clamp(command.value, 0.0, 1.0)
                self._print(f"Throttle accepted: {self._throttle_command:.3f}")
            elif command.name == "shutdown":
                shutdown_requested = True
            elif command.name == "status":
                self._print_status(self.coordinator.snapshot)
            elif command.name == "fault":
                fault_requested = True
            elif command.name == "reset":
                reset_requested = True
            elif command.name == "quit":
                self._running = False
                break

        return EngineOperationRequest(
            throttle_command=self._throttle_command,
            startup_requested=startup_requested,
            shutdown_requested=shutdown_requested,
            fault_requested=fault_requested,
            reset_requested=reset_requested,
        )

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
            f"throttle={self._throttle_command:.3f} | "
            f"speed={snapshot.rotor_speed_rpm:9.0f} rpm | "
            f"EGT={snapshot.exhaust_temperature_c:6.1f} °C | "
            f"fuel={snapshot.requested_fuel_command:.3f}/"
            f"{snapshot.allowed_fuel_command:.3f} | "
            f"starter={snapshot.starter_commanded} | "
            f"ignition={snapshot.ignition_commanded} | "
            f"EGT-limit={snapshot.egt_limiter_active}"
        )

    def _print_help(self) -> None:
        """Print the available interactive commands."""

        self._print(
            "Commands: help, start, throttle <0.0..1.0>, shutdown, "
            "status, fault, reset, quit"
        )

    def _print(self, message: str) -> None:
        """Print to the configured application output stream."""

        print(message, file=self.output_stream, flush=True)

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        """Limit a value to a closed interval."""

        return max(minimum, min(value, maximum))


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
