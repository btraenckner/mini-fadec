"""Unit tests for validated rotor-acceleration protection."""

import pytest

from simulation.operation.engine_state import EngineOperatingState
from simulation.protection.acceleration_limiter import (
    AccelerationLimiter,
    RotorAccelerationEstimator,
    RotorAccelerationEstimatorParameters,
)
from simulation.protection.types import AccelerationEstimate


def _estimate(acceleration_rpm_per_s: float) -> AccelerationEstimate:
    return AccelerationEstimate(
        acceleration_rpm_per_s=acceleration_rpm_per_s,
        initialized_from_previous_sample=True,
    )


@pytest.mark.parametrize("acceleration", [0.0, 11_999.0, 12_000.0])
def test_acceleration_at_or_below_soft_limit_does_not_intervene(
    acceleration: float,
) -> None:
    result = AccelerationLimiter().evaluate(
        0.8,
        _estimate(acceleration),
        EngineOperatingState.RUNNING,
        0.01,
    )

    assert result.fuel_limit == pytest.approx(0.8)
    assert result.active is False


def test_acceleration_between_thresholds_progressively_reduces_fuel() -> None:
    result = AccelerationLimiter().evaluate(
        0.8,
        _estimate(16_000.0),
        EngineOperatingState.RUNNING,
        0.01,
    )

    assert result.intervention_fraction == pytest.approx(0.5)
    assert result.fuel_limit == pytest.approx(0.4)
    assert result.active


@pytest.mark.parametrize("acceleration", [20_000.0, 30_000.0])
def test_acceleration_at_or_above_hard_limit_applies_strong_restriction(
    acceleration: float,
) -> None:
    result = AccelerationLimiter().evaluate(
        1.0,
        _estimate(acceleration),
        EngineOperatingState.RUNNING,
        0.01,
    )

    assert result.fuel_limit == pytest.approx(0.0)
    assert result.intervention_fraction == pytest.approx(1.0)


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
def test_acceleration_limiter_is_disabled_outside_closed_loop_states(
    state: EngineOperatingState,
) -> None:
    result = AccelerationLimiter().evaluate(
        0.75,
        _estimate(30_000.0),
        state,
        0.01,
    )

    assert result.fuel_limit == pytest.approx(0.75)
    assert result.active is False


def test_acceleration_limit_never_exceeds_requested_fuel() -> None:
    result = AccelerationLimiter().evaluate(
        0.3,
        _estimate(18_000.0),
        EngineOperatingState.RUNNING,
        0.01,
    )

    assert 0.0 <= result.fuel_limit <= 0.3


def test_acceleration_limit_releases_at_configured_rate() -> None:
    limiter = AccelerationLimiter()
    restricted = limiter.evaluate(
        1.0,
        _estimate(20_000.0),
        EngineOperatingState.RUNNING,
        0.01,
    )

    releasing = limiter.evaluate(
        1.0,
        _estimate(0.0),
        EngineOperatingState.RUNNING,
        0.01,
    )

    assert restricted.fuel_limit == pytest.approx(0.0)
    assert releasing.fuel_limit == pytest.approx(0.01)
    assert releasing.active


def test_acceleration_limiter_reset_clears_retained_release_limit() -> None:
    limiter = AccelerationLimiter()
    limiter.evaluate(
        1.0,
        _estimate(20_000.0),
        EngineOperatingState.RUNNING,
        0.01,
    )

    limiter.reset()
    result = limiter.evaluate(
        1.0,
        _estimate(0.0),
        EngineOperatingState.RUNNING,
        0.01,
    )

    assert result.fuel_limit == pytest.approx(1.0)
    assert result.active is False


def test_first_estimator_sample_does_not_create_false_spike() -> None:
    estimator = RotorAccelerationEstimator()

    result = estimator.update(100_000.0, 0.01)

    assert result.acceleration_rpm_per_s == pytest.approx(0.0)
    assert result.initialized_from_previous_sample is False


def test_estimator_reset_clears_previous_speed() -> None:
    estimator = RotorAccelerationEstimator(
        RotorAccelerationEstimatorParameters(filter_time_constant_s=0.0)
    )
    estimator.update(50_000.0, 0.01)
    estimator.update(50_100.0, 0.01)

    estimator.reset()
    result = estimator.update(120_000.0, 0.01)

    assert result.acceleration_rpm_per_s == pytest.approx(0.0)
    assert result.initialized_from_previous_sample is False


def test_estimator_handles_unavailable_validated_speed() -> None:
    estimator = RotorAccelerationEstimator()
    estimator.update(50_000.0, 0.01)

    unavailable_result = estimator.update(None, 0.01)

    assert unavailable_result.acceleration_rpm_per_s is None
    assert unavailable_result.initialized_from_previous_sample is False


def test_fixed_valid_speed_sequence_is_deterministic() -> None:
    sequence = [50_000.0, 50_100.0, 50_150.0, 50_250.0]

    def estimates() -> list[float | None]:
        estimator = RotorAccelerationEstimator()
        return [estimator.update(speed, 0.01).acceleration_rpm_per_s for speed in sequence]

    assert estimates() == estimates()


@pytest.mark.parametrize("time_step_s", [0.0, -0.01])
def test_acceleration_components_reject_invalid_time_step(
    time_step_s: float,
) -> None:
    with pytest.raises(ValueError, match="time_step_s"):
        RotorAccelerationEstimator().update(50_000.0, time_step_s)
    with pytest.raises(ValueError, match="time_step_s"):
        AccelerationLimiter().evaluate(
            0.5,
            _estimate(15_000.0),
            EngineOperatingState.RUNNING,
            time_step_s,
        )
