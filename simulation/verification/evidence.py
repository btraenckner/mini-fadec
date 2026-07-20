"""Serializable evidence captured by project-level requirement evaluators."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RequirementEvidence:
    """Explicit optional measurements supporting one requirement result."""

    measured_value: float | str | bool | None = None
    expected_value: float | str | bool | None = None
    lower_limit: float | None = None
    upper_limit: float | None = None
    tolerance: float | None = None
    margin: float | None = None
    evaluation_time_s: float | None = None
    start_time_s: float | None = None
    end_time_s: float | None = None
    elapsed_time_s: float | None = None
    engine_state: str | None = None
    relevant_action_id: str | None = None
    relevant_event_type: str | None = None
    first_violation_time_s: float | None = None
    maximum_violation: float | None = None
    diagnostic_message: str | None = None

