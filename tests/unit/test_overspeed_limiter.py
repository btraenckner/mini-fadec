"""Unit tests for independent validated-speed overspeed protection."""

import pytest

from simulation.operation.engine_state import EngineOperatingState
from simulation.protection.overspeed_limiter import (
    OverspeedLimiter,
    OverspeedLimiterParameters,
)


def test_overspeed_thresholds_are_derived_from_maximum_normal_speed() -> None:
    parameters = OverspeedLimiterParameters(maximum_normal_speed_rpm=100_000.0)

    assert parameters.soft_overspeed_speed_rpm == pytest.approx(103_000.0)
    assert parameters.hard_overspeed_speed_rpm == pytest.approx(108_000.0)


def test_speed_below_soft_threshold_does_not_intervene() -> None:
    limiter = OverspeedLimiter()
    result = limiter.evaluate(
        0.8,
        limiter.parameters.soft_overspeed_speed_rpm - 1.0,
        EngineOperatingState.RUNNING,
        0.01,
    )

    assert result.fuel_limit == pytest.approx(0.8)
    assert result.soft_active is False


def test_exact_soft_threshold_is_active_without_discontinuous_reduction() -> None:
    limiter = OverspeedLimiter()
    result = limiter.evaluate(
        0.8,
        limiter.parameters.soft_overspeed_speed_rpm,
        EngineOperatingState.RUNNING,
        0.01,
    )

    assert result.fuel_limit == pytest.approx(0.8)
    assert result.soft_active
    assert result.hard_active is False


def test_speed_between_thresholds_progressively_reduces_fuel() -> None:
    limiter = OverspeedLimiter()
    midpoint_speed = (
        limiter.parameters.soft_overspeed_speed_rpm
        + limiter.parameters.hard_overspeed_speed_rpm
    ) / 2.0

    result = limiter.evaluate(
        0.8,
        midpoint_speed,
        EngineOperatingState.RUNNING,
        0.01,
    )

    assert result.fuel_limit == pytest.approx(0.4)
    assert result.soft_active
    assert result.hard_active is False


@pytest.mark.parametrize("speed_offset", [0.0, 10_000.0])
def test_speed_at_or_above_hard_threshold_commands_cutoff_and_fault(
    speed_offset: float,
) -> None:
    limiter = OverspeedLimiter()
    result = limiter.evaluate(
        0.0,
        limiter.parameters.hard_overspeed_speed_rpm + speed_offset,
        EngineOperatingState.RUNNING,
        0.01,
    )

    assert result.fuel_limit == pytest.approx(0.0)
    assert result.hard_active
    assert result.critical_fault_request


def test_overspeed_restriction_is_independent_of_controller_request() -> None:
    limiter = OverspeedLimiter()
    speed = limiter.parameters.hard_overspeed_speed_rpm

    results = [
        limiter.evaluate(request, speed, EngineOperatingState.RUNNING, 0.01)
        for request in (0.0, 0.5, 1.0)
    ]

    assert all(result.fuel_limit == 0.0 for result in results)
    assert all(result.critical_fault_request for result in results)


def test_overspeed_uses_supplied_validated_speed() -> None:
    limiter = OverspeedLimiter()
    result = limiter.evaluate(
        0.7,
        rotor_speed_rpm=None,
        operating_state=EngineOperatingState.RUNNING,
        time_step_s=0.01,
    )

    assert result.speed_ratio is None
    assert result.soft_active is False
    assert result.fuel_limit == pytest.approx(0.7)


def test_overspeed_is_disabled_in_safe_nonrunning_states() -> None:
    limiter = OverspeedLimiter()

    for state in (
        EngineOperatingState.OFF,
        EngineOperatingState.SHUTDOWN,
        EngineOperatingState.FAULT,
    ):
        result = limiter.evaluate(0.7, 145_000.0, state, 0.01)
        assert result.hard_active is False
        assert result.fuel_limit == pytest.approx(0.7)


def test_reset_preserves_stateless_deterministic_behavior() -> None:
    limiter = OverspeedLimiter()
    speed = limiter.parameters.soft_overspeed_speed_rpm + 1_000.0
    first = limiter.evaluate(0.8, speed, EngineOperatingState.RUNNING, 0.01)

    limiter.reset()
    second = limiter.evaluate(0.8, speed, EngineOperatingState.RUNNING, 0.01)

    assert first == second


@pytest.mark.parametrize("time_step_s", [0.0, -0.01])
def test_overspeed_rejects_invalid_time_step(time_step_s: float) -> None:
    with pytest.raises(ValueError, match="time_step_s"):
        OverspeedLimiter().evaluate(
            0.5,
            100_000.0,
            EngineOperatingState.RUNNING,
            time_step_s,
        )
