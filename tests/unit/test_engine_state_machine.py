"""Unit tests for the engine operating state machine."""

import pytest

from simulation.core.types import SensorData
from simulation.operation.engine_state import EngineOperatingState
from simulation.operation.state_machine import (
    EngineOperationRequest,
    EngineStateMachine,
)


def sensor_data(
    rotor_speed_rpm: float = 0.0,
    exhaust_temperature_c: float = 15.0,
) -> SensorData:
    """Create sensor data for a state-machine transition test."""

    return SensorData(
        rotor_speed_rpm=rotor_speed_rpm,
        exhaust_temperature_c=exhaust_temperature_c,
    )


def update(
    state_machine: EngineStateMachine,
    request: EngineOperationRequest | None = None,
    sensors: SensorData | None = None,
) -> None:
    """Advance a state machine with concise test defaults."""

    state_machine.update(
        request=request or EngineOperationRequest(),
        sensor_data=sensors or sensor_data(),
        time_step_s=0.01,
    )


def advance_to_ignition(state_machine: EngineStateMachine) -> None:
    """Advance a state machine from OFF through CRANKING to IGNITION."""

    update(
        state_machine,
        request=EngineOperationRequest(startup_requested=True),
    )
    update(state_machine, sensors=sensor_data(rotor_speed_rpm=15_000.0))


def advance_to_idle(state_machine: EngineStateMachine) -> None:
    """Advance a state machine from OFF through startup to IDLE."""

    advance_to_ignition(state_machine)
    update(
        state_machine,
        sensors=sensor_data(
            rotor_speed_rpm=35_000.0,
            exhaust_temperature_c=500.0,
        ),
    )


def test_initial_state_is_off() -> None:
    assert EngineStateMachine().state is EngineOperatingState.OFF


def test_startup_request_transitions_off_to_cranking() -> None:
    state_machine = EngineStateMachine()

    update(
        state_machine,
        request=EngineOperationRequest(startup_requested=True),
    )

    assert state_machine.state is EngineOperatingState.CRANKING


def test_cranking_remains_active_below_ignition_speed() -> None:
    state_machine = EngineStateMachine()
    update(
        state_machine,
        request=EngineOperationRequest(startup_requested=True),
    )

    update(state_machine, sensors=sensor_data(rotor_speed_rpm=14_999.0))

    assert state_machine.state is EngineOperatingState.CRANKING


def test_ignition_speed_transitions_cranking_to_ignition() -> None:
    state_machine = EngineStateMachine()

    advance_to_ignition(state_machine)

    assert state_machine.state is EngineOperatingState.IGNITION


def test_light_off_and_self_sustaining_speed_transition_to_idle() -> None:
    state_machine = EngineStateMachine()

    advance_to_idle(state_machine)

    assert state_machine.state is EngineOperatingState.IDLE


def test_throttle_above_idle_transitions_idle_to_running() -> None:
    state_machine = EngineStateMachine()
    advance_to_idle(state_machine)

    update(
        state_machine,
        request=EngineOperationRequest(throttle_command=0.5),
        sensors=sensor_data(39_000.0, 500.0),
    )

    assert state_machine.state is EngineOperatingState.RUNNING


def test_idle_throttle_transitions_running_to_idle() -> None:
    state_machine = EngineStateMachine()
    advance_to_idle(state_machine)
    update(
        state_machine,
        request=EngineOperationRequest(throttle_command=0.5),
        sensors=sensor_data(39_000.0, 500.0),
    )

    update(
        state_machine,
        request=EngineOperationRequest(throttle_command=0.0),
        sensors=sensor_data(80_000.0, 550.0),
    )

    assert state_machine.state is EngineOperatingState.IDLE


@pytest.mark.parametrize(
    "initial_state",
    [EngineOperatingState.IDLE, EngineOperatingState.RUNNING],
)
def test_shutdown_transitions_running_states_to_shutdown(
    initial_state: EngineOperatingState,
) -> None:
    state_machine = EngineStateMachine()
    advance_to_idle(state_machine)
    if initial_state is EngineOperatingState.RUNNING:
        update(
            state_machine,
            request=EngineOperationRequest(throttle_command=0.5),
            sensors=sensor_data(39_000.0, 500.0),
        )

    update(
        state_machine,
        request=EngineOperationRequest(shutdown_requested=True),
        sensors=sensor_data(39_000.0, 500.0),
    )

    assert state_machine.state is EngineOperatingState.SHUTDOWN


@pytest.mark.parametrize(
    "initial_state",
    [EngineOperatingState.CRANKING, EngineOperatingState.IGNITION],
)
def test_shutdown_during_startup_is_accepted(
    initial_state: EngineOperatingState,
) -> None:
    state_machine = EngineStateMachine()
    update(
        state_machine,
        request=EngineOperationRequest(startup_requested=True),
    )
    if initial_state is EngineOperatingState.IGNITION:
        update(state_machine, sensors=sensor_data(rotor_speed_rpm=15_000.0))

    update(
        state_machine,
        request=EngineOperationRequest(shutdown_requested=True),
        sensors=sensor_data(rotor_speed_rpm=15_000.0),
    )

    assert state_machine.state is EngineOperatingState.SHUTDOWN


def test_shutdown_remains_active_while_rotor_is_turning() -> None:
    state_machine = EngineStateMachine()
    advance_to_idle(state_machine)
    update(
        state_machine,
        request=EngineOperationRequest(shutdown_requested=True),
        sensors=sensor_data(39_000.0, 500.0),
    )

    update(state_machine, sensors=sensor_data(rotor_speed_rpm=501.0))

    assert state_machine.state is EngineOperatingState.SHUTDOWN


def test_stopped_rotor_transitions_shutdown_to_off() -> None:
    state_machine = EngineStateMachine()
    advance_to_idle(state_machine)
    update(
        state_machine,
        request=EngineOperationRequest(shutdown_requested=True),
        sensors=sensor_data(39_000.0, 500.0),
    )

    update(state_machine, sensors=sensor_data(rotor_speed_rpm=500.0))

    assert state_machine.state is EngineOperatingState.OFF


def test_fault_request_enters_fault_from_any_state() -> None:
    state_machine = EngineStateMachine()
    advance_to_idle(state_machine)

    command = state_machine.update(
        request=EngineOperationRequest(fault_requested=True),
        sensor_data=sensor_data(39_000.0, 500.0),
        time_step_s=0.01,
    )

    assert state_machine.state is EngineOperatingState.FAULT
    assert command.fuel_enabled is False
    assert command.starter_commanded is False
    assert command.ignition_commanded is False


def test_fault_reset_is_rejected_while_rotor_is_turning() -> None:
    state_machine = EngineStateMachine()
    update(
        state_machine,
        request=EngineOperationRequest(fault_requested=True),
    )

    update(
        state_machine,
        request=EngineOperationRequest(reset_requested=True),
        sensors=sensor_data(rotor_speed_rpm=501.0),
    )

    assert state_machine.state is EngineOperatingState.FAULT


def test_fault_reset_succeeds_when_rotor_is_stopped() -> None:
    state_machine = EngineStateMachine()
    update(
        state_machine,
        request=EngineOperationRequest(fault_requested=True),
    )

    update(
        state_machine,
        request=EngineOperationRequest(reset_requested=True),
        sensors=sensor_data(rotor_speed_rpm=500.0),
    )

    assert state_machine.state is EngineOperatingState.OFF
