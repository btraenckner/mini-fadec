"""Unit tests for normal-operation fuel decrease protection."""

import pytest

from simulation.operation.engine_state import EngineOperatingState
from simulation.protection.deceleration_limiter import DecelerationLimiter


def _primed_limiter(previous_fuel: float = 0.8) -> DecelerationLimiter:
    limiter = DecelerationLimiter()
    limiter.retain_final_fuel_command(previous_fuel)
    return limiter


def test_small_fuel_reduction_is_unchanged() -> None:
    result = _primed_limiter().evaluate(
        0.797,
        EngineOperatingState.RUNNING,
        0.01,
    )

    assert result.minimum_fuel_command == pytest.approx(0.795)
    assert result.active is False


def test_excessive_fuel_reduction_is_rate_limited() -> None:
    result = _primed_limiter().evaluate(
        0.2,
        EngineOperatingState.RUNNING,
        0.01,
    )

    assert result.minimum_fuel_command == pytest.approx(0.795)
    assert result.active


def test_deceleration_bound_depends_on_time_step() -> None:
    short_step = _primed_limiter().evaluate(
        0.0,
        EngineOperatingState.RUNNING,
        0.01,
    )
    long_step = _primed_limiter().evaluate(
        0.0,
        EngineOperatingState.RUNNING,
        0.10,
    )

    assert short_step.minimum_fuel_command == pytest.approx(0.795)
    assert long_step.minimum_fuel_command == pytest.approx(0.75)


def test_increasing_fuel_is_not_restricted() -> None:
    result = _primed_limiter(0.2).evaluate(
        0.8,
        EngineOperatingState.RUNNING,
        0.01,
    )

    assert result.active is False


@pytest.mark.parametrize(
    "state",
    [
        EngineOperatingState.OFF,
        EngineOperatingState.CRANKING,
        EngineOperatingState.IGNITION,
        EngineOperatingState.SHUTDOWN,
        EngineOperatingState.FAULT,
    ],
)
def test_deceleration_limiter_is_bypassed_outside_normal_operation(
    state: EngineOperatingState,
) -> None:
    result = _primed_limiter().evaluate(0.0, state, 0.01)

    assert result.minimum_fuel_command == pytest.approx(0.0)
    assert result.active is False


@pytest.mark.parametrize("bypass_reason", ["hard overspeed", "sensor fault"])
def test_safety_cutoff_bypasses_deceleration_limiter(
    bypass_reason: str,
) -> None:
    _ = bypass_reason
    result = _primed_limiter().evaluate(
        0.0,
        EngineOperatingState.RUNNING,
        0.01,
        bypass=True,
    )

    assert result.minimum_fuel_command == pytest.approx(0.0)
    assert result.active is False


def test_reset_clears_previous_final_command() -> None:
    limiter = _primed_limiter()

    limiter.reset()
    result = limiter.evaluate(0.0, EngineOperatingState.RUNNING, 0.01)

    assert limiter.previous_final_fuel_command is None
    assert result.active is False


def test_repeated_updates_produce_expected_downward_ramp() -> None:
    limiter = _primed_limiter()
    final_commands: list[float] = []

    for _ in range(3):
        result = limiter.evaluate(0.0, EngineOperatingState.RUNNING, 0.1)
        final_commands.append(result.minimum_fuel_command)
        limiter.retain_final_fuel_command(result.minimum_fuel_command)

    assert final_commands == pytest.approx([0.75, 0.70, 0.65])
    assert all(0.0 <= command <= 1.0 for command in final_commands)


@pytest.mark.parametrize("time_step_s", [0.0, -0.01])
def test_deceleration_limiter_rejects_invalid_time_step(
    time_step_s: float,
) -> None:
    with pytest.raises(ValueError, match="time_step_s"):
        DecelerationLimiter().evaluate(
            0.5,
            EngineOperatingState.RUNNING,
            time_step_s,
        )
