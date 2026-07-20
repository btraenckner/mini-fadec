"""Strongly typed project-level simulation requirement definitions."""

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Protocol

from simulation.scenarios.actions import ActionResult
from simulation.telemetry.events import SimulationEvent
from simulation.telemetry.snapshot import SimulationSnapshot
from simulation.verification.evidence import RequirementEvidence


class RequirementCategory(Enum):
    STATE_SEQUENCE = "STATE_SEQUENCE"
    STATE_TIMING = "STATE_TIMING"
    SIGNAL_LIMIT = "SIGNAL_LIMIT"
    STEADY_STATE = "STEADY_STATE"
    TRANSIENT = "TRANSIENT"
    PROTECTION = "PROTECTION"
    SENSOR_FAULT_RESPONSE = "SENSOR_FAULT_RESPONSE"
    ACTUATOR_SAFETY = "ACTUATOR_SAFETY"
    LOGICAL_INVARIANT = "LOGICAL_INVARIANT"


class RequirementCriticality(Enum):
    INFO = "INFO"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class RequirementStatus(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_EVALUATED = "NOT_EVALUATED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    ERROR = "ERROR"


@dataclass(frozen=True)
class EvaluationContext:
    """Complete immutable evidence available to post-run evaluators."""

    snapshots: tuple[SimulationSnapshot, ...]
    events: tuple[SimulationEvent, ...]
    action_results: Mapping[str, ActionResult]
    time_step_s: float


@dataclass(frozen=True)
class EvaluationOutcome:
    """Evaluator output before requirement identity is attached."""

    status: RequirementStatus
    evidence: RequirementEvidence
    message: str
    diagnostic_code: str | None = None


class RequirementEvaluator(Protocol):
    """Stateless or immutable evaluator used by a typed requirement."""

    def evaluate(self, context: EvaluationContext) -> EvaluationOutcome:
        """Evaluate captured evidence without reading runtime internals."""
        ...


@dataclass(frozen=True)
class Requirement:
    """One stable requirement and its explicit evaluator."""

    requirement_id: str
    description: str
    category: RequirementCategory
    criticality: RequirementCriticality
    evaluator: RequirementEvaluator
    applicability: str | None = None
    info_failure_is_warning_only: bool = True

    def __post_init__(self) -> None:
        if not self.requirement_id.strip():
            raise ValueError("requirement_id cannot be empty")
        if not self.description.strip():
            raise ValueError("requirement description cannot be empty")
        if not callable(getattr(self.evaluator, "evaluate", None)):
            raise TypeError("requirement evaluator must implement evaluate")

