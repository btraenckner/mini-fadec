"""Unit tests for centralized deterministic fuel arbitration."""

import pytest

from simulation.core.types import ValidatedSensorData
from simulation.operation.engine_state import EngineOperatingState
from simulation.protection.protection_manager import ProtectionManager
from simulation.protection.types import (
    FuelLimitCandidates,
    ProtectionContext,
    ProtectionDiagnosticReason,
    ProtectionLimiter,
)


def _candidates(
    *,
    requested: float = 0.8,
    egt_limit: float = 0.8,
    egt_active: bool = False,
    acceleration_limit: float = 0.8,
    acceleration_active: bool = False,
    overspeed_limit: float = 0.8,
    overspeed_active: bool = False,
    deceleration_minimum: float = 0.0,
    deceleration_active: bool = False,
    state_maximum: float = 1.0,
) -> FuelLimitCandidates:
    return FuelLimitCandidates(
        requested_fuel_command=requested,
        egt_fuel_limit=egt_limit,
        egt_active=egt_active,
        acceleration_fuel_limit=acceleration_limit,
        acceleration_active=acceleration_active,
        overspeed_fuel_limit=overspeed_limit,
        overspeed_active=overspeed_active,
        deceleration_minimum_fuel_command=deceleration_minimum,
        deceleration_active=deceleration_active,
        state_maximum_fuel_command=state_maximum,
    )


def test_no_active_limits_passes_requested_fuel_through() -> None:
    result = ProtectionManager().arbitrate(_candidates(requested=0.7))

    assert result.final_fuel_command == pytest.approx(0.7)
    assert result.active_limiter is ProtectionLimiter.NONE


def test_smallest_active_upper_fuel_limit_is_selected() -> None:
    result = ProtectionManager().arbitrate(
        _candidates(
            requested=0.9,
            egt_limit=0.7,
            egt_active=True,
            acceleration_limit=0.5,
            acceleration_active=True,
        )
    )

    assert result.final_fuel_command == pytest.approx(0.5)
    assert result.active_limiter is ProtectionLimiter.ACCELERATION


def test_largest_lower_limit_is_selected_without_safety_conflict() -> None:
    result = ProtectionManager().arbitrate(
        _candidates(
            requested=0.2,
            deceleration_minimum=0.6,
            deceleration_active=True,
        )
    )

    assert result.final_fuel_command == pytest.approx(0.6)
    assert result.active_limiter is ProtectionLimiter.DECELERATION
    assert result.arbitration_conflict is False


@pytest.mark.parametrize(
    ("limiter", "candidate_arguments"),
    [
        (
            ProtectionLimiter.EGT,
            {"egt_limit": 0.4, "egt_active": True},
        ),
        (
            ProtectionLimiter.OVERSPEED,
            {"overspeed_limit": 0.4, "overspeed_active": True},
        ),
    ],
)
def test_deceleration_lower_bound_cannot_override_safety_upper_limit(
    limiter: ProtectionLimiter,
    candidate_arguments: dict[str, float | bool],
) -> None:
    result = ProtectionManager().arbitrate(
        _candidates(
            requested=0.2,
            deceleration_minimum=0.6,
            deceleration_active=True,
            **candidate_arguments,
        )
    )

    assert result.final_fuel_command == pytest.approx(0.4)
    assert result.active_limiter is limiter
    assert ProtectionLimiter.DECELERATION in result.constraining_limiters
    assert result.arbitration_conflict


def test_hard_cutoff_always_produces_zero_fuel() -> None:
    result = ProtectionManager().arbitrate(
        _candidates(
            requested=1.0,
            deceleration_minimum=0.9,
            deceleration_active=True,
        ),
        hard_cutoff_sources=(ProtectionLimiter.OVERSPEED,),
    )

    assert result.final_fuel_command == pytest.approx(0.0)
    assert result.active_limiter is ProtectionLimiter.HARD_CUTOFF


@pytest.mark.parametrize(
    ("requested", "expected"),
    [(-1.0, 0.0), (0.5, 0.5), (2.0, 1.0)],
)
def test_requested_fuel_is_clamped_to_physical_bounds(
    requested: float,
    expected: float,
) -> None:
    result = ProtectionManager().arbitrate(_candidates(requested=requested))

    assert result.final_fuel_command == pytest.approx(expected)


def test_equal_limits_use_priority_and_report_every_constraint() -> None:
    result = ProtectionManager().arbitrate(
        _candidates(
            requested=0.9,
            egt_limit=0.4,
            egt_active=True,
            acceleration_limit=0.4,
            acceleration_active=True,
            overspeed_limit=0.4,
            overspeed_active=True,
        )
    )

    assert result.active_limiter is ProtectionLimiter.OVERSPEED
    assert result.constraining_limiters == (
        ProtectionLimiter.OVERSPEED,
        ProtectionLimiter.EGT,
        ProtectionLimiter.ACCELERATION,
    )


def test_state_limit_is_applied_and_reported() -> None:
    result = ProtectionManager().arbitrate(
        _candidates(requested=0.8, state_maximum=0.0)
    )

    assert result.final_fuel_command == pytest.approx(0.0)
    assert result.active_limiter is ProtectionLimiter.STATE


def test_sensor_hard_cutoff_reports_priority_sources() -> None:
    result = ProtectionManager().arbitrate(
        _candidates(requested=0.8),
        hard_cutoff_sources=(
            ProtectionLimiter.SENSOR_FAULT,
            ProtectionLimiter.OVERSPEED,
        ),
    )

    assert result.constraining_limiters == (
        ProtectionLimiter.HARD_CUTOFF,
        ProtectionLimiter.SENSOR_FAULT,
        ProtectionLimiter.OVERSPEED,
    )


def test_apply_reports_arbitration_diagnostics_and_valid_bounds() -> None:
    manager = ProtectionManager()
    result = manager.apply(
        requested_fuel_command=0.7,
        sensor_data=ValidatedSensorData(
            rotor_speed_rpm=80_000.0,
            exhaust_temperature_c=640.0,
        ),
        context=ProtectionContext(
            operating_state=EngineOperatingState.RUNNING,
            fuel_enabled=True,
        ),
        time_step_s=0.01,
    )

    assert 0.0 <= result.final_fuel_command <= 1.0
    assert result.diagnostic_reasons == (ProtectionDiagnosticReason.NONE,)


def test_reset_clears_retained_arbitration_state() -> None:
    manager = ProtectionManager()
    context = ProtectionContext(
        operating_state=EngineOperatingState.RUNNING,
        fuel_enabled=True,
    )
    sensor_data = ValidatedSensorData(
        rotor_speed_rpm=80_000.0,
        exhaust_temperature_c=640.0,
    )
    manager.apply(0.8, sensor_data, context, 0.01)
    manager.apply(0.0, sensor_data, context, 0.01)

    manager.reset()

    assert manager.deceleration_limiter.previous_final_fuel_command is None
    assert manager.last_result.final_fuel_command == pytest.approx(0.0)


@pytest.mark.parametrize("time_step_s", [0.0, -0.01])
def test_manager_rejects_invalid_time_step(time_step_s: float) -> None:
    with pytest.raises(ValueError, match="time_step_s"):
        ProtectionManager().apply(
            0.5,
            ValidatedSensorData(80_000.0, 600.0),
            ProtectionContext(EngineOperatingState.RUNNING, True),
            time_step_s,
        )
