"""Versioned control-software requirements baseline and traceability links."""

import re
from dataclasses import dataclass
from enum import Enum

from simulation.configuration._serialization import configuration_to_dict
from simulation.verification.requirements import (
    RequirementCategory,
    RequirementCriticality,
)


class RequirementBaselineStatus(Enum):
    """Lifecycle state of a controlled requirements baseline."""

    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class VerificationMethod(Enum):
    """Primary method intended to provide requirement evidence."""

    TEST = "TEST"
    ANALYSIS = "ANALYSIS"
    INSPECTION = "INSPECTION"
    TEST_AND_ANALYSIS = "TEST_AND_ANALYSIS"


class TraceabilityCoverage(Enum):
    """Current executable coverage of one baseline requirement."""

    IMPLEMENTED = "IMPLEMENTED"
    PARTIAL = "PARTIAL"
    PLANNED = "PLANNED"


@dataclass(frozen=True)
class BaselineRequirement:
    """One controlled requirement with planned and executable trace links."""

    requirement_id: str
    title: str
    statement: str
    rationale: str
    category: RequirementCategory
    criticality: RequirementCriticality
    verification_method: VerificationMethod
    acceptance_criteria: str
    source: str
    applicability: tuple[str, ...]
    planned_test_case_ids: tuple[str, ...]
    scenario_ids: tuple[str, ...] = ()
    executable_requirement_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if re.fullmatch(r"FADEC-[A-Z]+-\d{3}", self.requirement_id) is None:
            raise ValueError(
                "requirement_id must match FADEC-<DOMAIN>-<NNN>"
            )
        for field_name, value in (
            ("title", self.title),
            ("statement", self.statement),
            ("rationale", self.rationale),
            ("acceptance_criteria", self.acceptance_criteria),
            ("source", self.source),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} cannot be empty")
        if " shall " not in f" {self.statement.lower()} ":
            raise ValueError("requirement statement must contain 'shall'")
        if not self.applicability:
            raise ValueError("applicability cannot be empty")
        if not self.planned_test_case_ids:
            raise ValueError("at least one planned test-case ID is required")
        for test_case_id in self.planned_test_case_ids:
            if re.fullmatch(r"TC-[A-Z]+-\d{3}", test_case_id) is None:
                raise ValueError(
                    "planned test-case ID must match TC-<DOMAIN>-<NNN>"
                )
        for collection_name, values in (
            ("applicability", self.applicability),
            ("planned test-case IDs", self.planned_test_case_ids),
            ("scenario IDs", self.scenario_ids),
            ("executable requirement IDs", self.executable_requirement_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {collection_name} are not allowed")

    @property
    def coverage(self) -> TraceabilityCoverage:
        """Return current scenario/evaluator coverage without hiding gaps."""

        if self.scenario_ids and self.executable_requirement_ids:
            return TraceabilityCoverage.IMPLEMENTED
        if self.scenario_ids or self.executable_requirement_ids:
            return TraceabilityCoverage.PARTIAL
        return TraceabilityCoverage.PLANNED


@dataclass(frozen=True)
class RequirementBaseline:
    """Immutable metadata and entries for one requirements baseline."""

    baseline_id: str
    version: str
    status: RequirementBaselineStatus
    title: str
    scope: str
    applicability: tuple[str, ...]
    requirements: tuple[BaselineRequirement, ...]

    def __post_init__(self) -> None:
        for field_name, value in (
            ("baseline_id", self.baseline_id),
            ("version", self.version),
            ("title", self.title),
            ("scope", self.scope),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} cannot be empty")
        if not self.applicability:
            raise ValueError("baseline applicability cannot be empty")
        if not self.requirements:
            raise ValueError("baseline must contain requirements")
        requirement_ids = tuple(
            requirement.requirement_id for requirement in self.requirements
        )
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("baseline requirement IDs must be unique")

    def requirement(self, requirement_id: str) -> BaselineRequirement:
        """Return one requirement by exact stable ID."""

        for requirement in self.requirements:
            if requirement.requirement_id == requirement_id:
                return requirement
        raise KeyError(f"unknown baseline requirement: {requirement_id}")

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-compatible baseline snapshot."""

        baseline = configuration_to_dict(self)
        serialized_requirements = baseline.get("requirements")
        if isinstance(serialized_requirements, list):
            for serialized, requirement in zip(
                serialized_requirements,
                self.requirements,
            ):
                if isinstance(serialized, dict):
                    serialized["coverage"] = requirement.coverage.value
        return baseline


_ALL_PROFILES = ("all-compatible-engine-profiles",)


def _requirement(
    requirement_id: str,
    title: str,
    statement: str,
    rationale: str,
    category: RequirementCategory,
    criticality: RequirementCriticality,
    acceptance_criteria: str,
    source: str,
    test_case_id: str,
    *,
    verification_method: VerificationMethod = VerificationMethod.TEST,
    scenario_ids: tuple[str, ...] = (),
    executable_requirement_ids: tuple[str, ...] = (),
) -> BaselineRequirement:
    return BaselineRequirement(
        requirement_id=requirement_id,
        title=title,
        statement=statement,
        rationale=rationale,
        category=category,
        criticality=criticality,
        verification_method=verification_method,
        acceptance_criteria=acceptance_criteria,
        source=source,
        applicability=_ALL_PROFILES,
        planned_test_case_ids=(test_case_id,),
        scenario_ids=scenario_ids,
        executable_requirement_ids=executable_requirement_ids,
    )


def fadec_control_requirements_baseline() -> RequirementBaseline:
    """Return the draft Mini-FADEC control requirements baseline."""

    return RequirementBaseline(
        baseline_id="MINI-FADEC-CONTROL-REQ",
        version="0.1.0",
        status=RequirementBaselineStatus.DRAFT,
        title="Mini-FADEC Control Software Requirements Baseline",
        scope=(
            "Closed-loop control, operating-state management, fuel protection, "
            "sensor-fault response, and deterministic scheduling in the "
            "Mini-FADEC development simulation."
        ),
        applicability=_ALL_PROFILES,
        requirements=(
            _requirement(
                "FADEC-OPS-001",
                "Normal start sequence",
                "The control software shall execute OFF, CRANKING, IGNITION, "
                "and IDLE in that order after a valid start request.",
                "Ordered states prevent fuel and ignition from being enabled "
                "before the required spool conditions exist.",
                RequirementCategory.STATE_SEQUENCE,
                RequirementCriticality.CRITICAL,
                "The recorded state sequence contains OFF, CRANKING, IGNITION, "
                "and IDLE in order with no intervening FAULT state.",
                "Project operating-state concept",
                "TC-OPS-001",
                scenario_ids=("SCN-NORMAL-001",),
                executable_requirement_ids=(
                    "REQ-NORMAL-STATE-SEQUENCE",
                    "REQ-NORMAL-NO-FAULT",
                ),
            ),
            _requirement(
                "FADEC-OPS-002",
                "Start completion time",
                "The control software shall command a start that reaches IDLE "
                "within 10 seconds of a valid start request.",
                "A bounded start time detects an unsuccessful start sequence.",
                RequirementCategory.STATE_TIMING,
                RequirementCriticality.MAJOR,
                "IDLE is first observed no later than 10.0 s after the start "
                "action.",
                "Current Mini-FADEC development target",
                "TC-OPS-001",
                scenario_ids=("SCN-NORMAL-001",),
                executable_requirement_ids=("REQ-NORMAL-IDLE-TIME",),
            ),
            _requirement(
                "FADEC-OPS-003",
                "Normal shutdown time",
                "The control software shall reach OFF within 8 seconds of a "
                "valid shutdown request.",
                "A bounded shutdown provides deterministic fuel cutoff and "
                "return to the safe stopped state.",
                RequirementCategory.STATE_TIMING,
                RequirementCriticality.MAJOR,
                "OFF is first observed no later than 8.0 s after the shutdown "
                "action.",
                "Current Mini-FADEC development target",
                "TC-OPS-002",
                scenario_ids=("SCN-NORMAL-001", "SCN-TRANSIENT-002"),
                executable_requirement_ids=(
                    "REQ-NORMAL-SHUTDOWN-TIME",
                    "REQ-DECEL-SHUTDOWN",
                ),
            ),
            _requirement(
                "FADEC-OPS-004",
                "Fault reset interlock",
                "The control software shall accept a reset from FAULT only when "
                "validated rotor speed is at or below the configured stopped "
                "speed threshold.",
                "Restarting state control while the rotor is turning can create "
                "an unsafe command sequence.",
                RequirementCategory.LOGICAL_INVARIANT,
                RequirementCriticality.CRITICAL,
                "Reset above the stopped threshold leaves the state at FAULT; "
                "reset at or below the threshold transitions to OFF.",
                "EngineStateMachine safety interlock",
                "TC-OPS-003",
                scenario_ids=("SCN-OPS-003",),
                executable_requirement_ids=(
                    "REQ-OPS-RESET-INTERLOCK",
                ),
            ),
            _requirement(
                "FADEC-START-001",
                "Hot-start protection",
                "The control software shall terminate fuel delivery during start "
                "when validated EGT reaches the engine transient EGT limit.",
                "Start fuel must not continue when the engine reaches its "
                "published transient thermal limit.",
                RequirementCategory.PROTECTION,
                RequirementCriticality.CRITICAL,
                "Fuel reaches 0.0 no later than one protection-task period after "
                "validated EGT reaches the transient limit during IGNITION.",
                "EngineDefinition transient EGT limit",
                "TC-START-001",
                scenario_ids=("SCN-START-001",),
                executable_requirement_ids=(
                    "REQ-START-HOT-FUEL-CUTOFF",
                ),
            ),
            _requirement(
                "FADEC-START-002",
                "Hung-start timeout",
                "The control software shall terminate an unsuccessful start that "
                "does not reach IDLE within 10 seconds.",
                "An indefinite CRANKING or IGNITION state can overheat the starter "
                "or continue unsafe fuel delivery.",
                RequirementCategory.STATE_TIMING,
                RequirementCriticality.CRITICAL,
                "The system enters FAULT and commands fuel off no later than "
                "10.0 s after start when IDLE has not been reached.",
                "Current Mini-FADEC development target",
                "TC-START-002",
                scenario_ids=("SCN-START-002",),
                executable_requirement_ids=(
                    "REQ-START-HUNG-TIMEOUT",
                ),
            ),
            _requirement(
                "FADEC-SPD-001",
                "Throttle-to-speed schedule",
                "The control software shall clamp throttle demand to 0.0 through "
                "1.0 and schedule speed between the configured idle and maximum "
                "continuous engine speeds.",
                "Bounded scheduling prevents commands outside the approved engine "
                "operating envelope.",
                RequirementCategory.SIGNAL_LIMIT,
                RequirementCriticality.MAJOR,
                "Throttle values below 0.0 map to idle, values above 1.0 map to "
                "maximum continuous speed, and intermediate values map linearly.",
                "EngineDefinition operating envelope",
                "TC-SPD-001",
                verification_method=VerificationMethod.TEST_AND_ANALYSIS,
                scenario_ids=("SCN-SPD-001",),
                executable_requirement_ids=(
                    "REQ-SPD-THROTTLE-SCHEDULE",
                ),
            ),
            _requirement(
                "FADEC-SPD-002",
                "Speed settling",
                "The closed-loop system shall settle within 2 percent of scheduled "
                "rotor speed for at least 0.5 seconds within 10 seconds of a "
                "throttle step.",
                "Bounded steady-state error and settling time define acceptable "
                "governor performance.",
                RequirementCategory.STEADY_STATE,
                RequirementCriticality.MAJOR,
                "Validated speed remains within ±2.0% of setpoint for 0.5 s and "
                "first satisfies that dwell no later than 10.0 s after the step.",
                "Current Mini-FADEC closed-loop performance target",
                "TC-SPD-002",
                scenario_ids=("SCN-TRANSIENT-001",),
                executable_requirement_ids=("REQ-TRANSIENT-SETTLING",),
            ),
            _requirement(
                "FADEC-SPD-003",
                "Speed overshoot",
                "The closed-loop system shall limit rotor-speed overshoot to less "
                "than 3 percent after a throttle increase.",
                "Overshoot margin reduces unnecessary protection intervention and "
                "mechanical loading.",
                RequirementCategory.TRANSIENT,
                RequirementCriticality.MAJOR,
                "Maximum validated speed during the 8.0 s evaluation window is "
                "less than 103% of scheduled speed.",
                "Current Mini-FADEC closed-loop performance target",
                "TC-SPD-002",
                scenario_ids=("SCN-TRANSIENT-001",),
                executable_requirement_ids=("REQ-TRANSIENT-OVERSHOOT",),
            ),
            _requirement(
                "FADEC-ACT-001",
                "Fuel-command bounds",
                "The control software shall keep requested and applied normalized "
                "fuel commands between 0.0 and 1.0 inclusive.",
                "The actuator interface accepts only normalized bounded commands.",
                RequirementCategory.ACTUATOR_SAFETY,
                RequirementCriticality.CRITICAL,
                "Every recorded requested and applied fuel command is in [0, 1].",
                "EngineDefinition actuator interface",
                "TC-ACT-001",
                scenario_ids=(
                    "SCN-NORMAL-001",
                    "SCN-TRANSIENT-001",
                    "SCN-TRANSIENT-002",
                    "SCN-FAULT-001",
                    "SCN-FAULT-002",
                    "SCN-PROT-001",
                    "SCN-PROT-002",
                ),
                executable_requirement_ids=(
                    "REQ-NORMAL-FUEL-BOUNDS",
                    "REQ-TRANSIENT-FUEL-BOUNDS",
                    "REQ-DECEL-FUEL-BOUNDS",
                    "REQ-RPM-FUEL-BOUNDS",
                    "REQ-EGT-FUEL-BOUNDS",
                    "REQ-SOFT-FUEL-BOUNDS",
                    "REQ-HARD-FUEL-BOUNDS",
                ),
            ),
            _requirement(
                "FADEC-ACT-002",
                "Safe-state fuel cutoff",
                "The control software shall command zero fuel in OFF and FAULT.",
                "OFF and FAULT are non-running safe states and must not sustain "
                "combustion.",
                RequirementCategory.ACTUATOR_SAFETY,
                RequirementCriticality.CRITICAL,
                "Every applied fuel sample in OFF or FAULT equals 0.0.",
                "Engine operating-state safety concept",
                "TC-ACT-002",
                scenario_ids=("SCN-NORMAL-001", "SCN-PROT-002"),
                executable_requirement_ids=(
                    "REQ-NORMAL-OFF-FUEL",
                    "REQ-HARD-FAULT-FUEL",
                ),
            ),
            _requirement(
                "FADEC-ACT-003",
                "Starter disengagement",
                "The control software shall keep the starter command inactive in "
                "RUNNING.",
                "Starter engagement at running speed can damage the starter system.",
                RequirementCategory.ACTUATOR_SAFETY,
                RequirementCriticality.CRITICAL,
                "Every starter command recorded in RUNNING is false.",
                "Engine operating-state safety concept",
                "TC-ACT-003",
                scenario_ids=("SCN-NORMAL-001",),
                executable_requirement_ids=("REQ-NORMAL-RUNNING-STARTER",),
            ),
            _requirement(
                "FADEC-EGT-001",
                "EGT fuel limiting",
                "The control software shall reduce the allowed fuel command when "
                "validated EGT exceeds the configured intervention temperature.",
                "Progressive intervention protects thermal margin before the hard "
                "temperature limit is reached.",
                RequirementCategory.PROTECTION,
                RequirementCriticality.CRITICAL,
                "Under constant requested fuel, allowed fuel above intervention "
                "EGT is below requested fuel and does not increase as EGT "
                "approaches the maximum limit.",
                "FadecCalibration EGT protection",
                "TC-EGT-001",
                scenario_ids=("SCN-PROT-003",),
                executable_requirement_ids=(
                    "REQ-EGT-LIMITER-CHARACTERISTIC",
                ),
            ),
            _requirement(
                "FADEC-EGT-002",
                "Transient EGT limit",
                "The closed-loop engine system shall not exceed the engine "
                "transient EGT limit during defined normal and transient tests.",
                "The engine operating envelope defines the allowable peak thermal "
                "condition.",
                RequirementCategory.SIGNAL_LIMIT,
                RequirementCriticality.CRITICAL,
                "Maximum true EGT is less than or equal to the selected "
                "EngineDefinition transient EGT limit.",
                "EngineDefinition operating envelope",
                "TC-EGT-002",
                scenario_ids=(
                    "SCN-NORMAL-001",
                    "SCN-TRANSIENT-001",
                    "SCN-TRANSIENT-002",
                ),
                executable_requirement_ids=(
                    "REQ-NORMAL-TRUE-EGT-LIMIT",
                    "REQ-TRANSIENT-TRUE-EGT-LIMIT",
                    "REQ-DECEL-TRUE-EGT-LIMIT",
                ),
            ),
            _requirement(
                "FADEC-ACC-001",
                "Rotor-acceleration limiting",
                "The control software shall constrain estimated rotor acceleration "
                "to the configured hard acceleration limit during a defined large "
                "throttle step.",
                "Acceleration limiting reduces surge and thermal-transient risk.",
                RequirementCategory.TRANSIENT,
                RequirementCriticality.MAJOR,
                "Estimated acceleration does not exceed the selected calibration's "
                "hard acceleration limit plus its declared evaluation tolerance.",
                "FadecCalibration acceleration protection",
                "TC-ACC-001",
                scenario_ids=("SCN-TRANSIENT-001",),
                executable_requirement_ids=(
                    "REQ-TRANSIENT-ACCEL-LIMITER",
                    "REQ-TRANSIENT-ACCEL-LIMIT",
                ),
            ),
            _requirement(
                "FADEC-DEC-001",
                "Fuel-deceleration limiting",
                "The control software shall constrain rapid commanded fuel "
                "reduction using the configured deceleration limiter without "
                "preventing shutdown.",
                "A bounded reduction helps maintain stable combustion while "
                "shutdown must retain higher priority.",
                RequirementCategory.PROTECTION,
                RequirementCriticality.MAJOR,
                "The deceleration limiter activates after the defined reduction "
                "and the subsequent shutdown still reaches OFF within 8.0 s.",
                "FadecCalibration deceleration protection",
                "TC-DEC-001",
                scenario_ids=("SCN-TRANSIENT-002",),
                executable_requirement_ids=(
                    "REQ-DECEL-LIMITER",
                    "REQ-DECEL-SHUTDOWN",
                ),
            ),
            _requirement(
                "FADEC-OVS-001",
                "Soft-overspeed intervention",
                "The control software shall constrain fuel at the configured soft "
                "overspeed threshold without requesting hard cutoff below the hard "
                "overspeed threshold.",
                "Progressive overspeed control should recover speed before a "
                "critical cutoff is required.",
                RequirementCategory.PROTECTION,
                RequirementCriticality.CRITICAL,
                "Soft-overspeed and fuel-constraint evidence are recorded, with no "
                "hard-cutoff or automatic-fault event in the soft test.",
                "FadecCalibration overspeed protection",
                "TC-OVS-001",
                scenario_ids=("SCN-PROT-001",),
                executable_requirement_ids=(
                    "REQ-SOFT-OVERSPEED-EVENT",
                    "REQ-SOFT-OVERSPEED-FUEL",
                    "REQ-SOFT-NO-HARD-CUTOFF",
                    "REQ-SOFT-NO-FAULT",
                ),
            ),
            _requirement(
                "FADEC-OVS-002",
                "Hard-overspeed cutoff",
                "The control software shall command zero fuel and request FAULT "
                "when validated speed reaches the configured hard overspeed "
                "threshold.",
                "Hard overspeed is a critical condition requiring deterministic "
                "fuel cutoff.",
                RequirementCategory.PROTECTION,
                RequirementCriticality.CRITICAL,
                "Zero fuel is observed within 0.01 s of hard-overspeed activation "
                "and the system subsequently reaches FAULT.",
                "FadecCalibration overspeed protection",
                "TC-OVS-002",
                scenario_ids=("SCN-PROT-002",),
                executable_requirement_ids=(
                    "REQ-HARD-OVERSPEED-EVENT",
                    "REQ-HARD-CRITICAL-REQUEST",
                    "REQ-HARD-FUEL-CUTOFF",
                    "REQ-HARD-FAULT",
                ),
            ),
            _requirement(
                "FADEC-PROT-001",
                "Protection arbitration",
                "The control software shall apply the most restrictive valid fuel "
                "limit and give hard cutoff priority over all nonzero limits.",
                "Independent protection functions must not overwrite a more "
                "restrictive safety command.",
                RequirementCategory.LOGICAL_INVARIANT,
                RequirementCriticality.CRITICAL,
                "For every protection cycle, allowed fuel equals the minimum valid "
                "limit unless a hard cutoff is active, in which case it is 0.0.",
                "Central fuel-protection architecture",
                "TC-PROT-001",
                verification_method=VerificationMethod.TEST_AND_ANALYSIS,
                scenario_ids=("SCN-PROT-003", "SCN-PROT-002"),
                executable_requirement_ids=(
                    "REQ-PROT-ARBITRATION-CONCURRENT",
                    "REQ-HARD-ARBITRATION-CUTOFF",
                ),
            ),
            _requirement(
                "FADEC-SENS-001",
                "Validated feedback only",
                "The control and protection functions shall use validated sensor "
                "values and shall not fall back to true plant values after a "
                "measurement becomes unavailable.",
                "Truth fallback would hide sensor failures in simulation and does "
                "not exist on real hardware.",
                RequirementCategory.SENSOR_FAULT_RESPONSE,
                RequirementCriticality.CRITICAL,
                "Dropout scenarios record no truth-fallback use for rotor speed or "
                "EGT.",
                "Sensor validation architecture",
                "TC-SENS-001",
                scenario_ids=("SCN-FAULT-001", "SCN-FAULT-002"),
                executable_requirement_ids=(
                    "REQ-RPM-NO-TRUTH-FALLBACK",
                    "REQ-EGT-NO-TRUTH-FALLBACK",
                ),
            ),
            _requirement(
                "FADEC-SENS-002",
                "Rotor-speed dropout response",
                "The control software shall classify sustained rotor-speed dropout "
                "as INVALID, reach FAULT within 0.5 seconds, and command zero fuel.",
                "Rotor speed is required for state transitions, governing, and "
                "overspeed protection.",
                RequirementCategory.SENSOR_FAULT_RESPONSE,
                RequirementCriticality.CRITICAL,
                "Rotor-speed health becomes INVALID, FAULT occurs within 0.5 s, "
                "and zero fuel is commanded within the evaluated response window.",
                "Sensor validation and automatic fault-response concept",
                "TC-SENS-002",
                scenario_ids=("SCN-FAULT-001",),
                executable_requirement_ids=(
                    "REQ-RPM-HEALTH",
                    "REQ-RPM-FAULT-RESPONSE",
                    "REQ-RPM-FUEL-CUTOFF",
                    "REQ-RPM-FAULT-FUEL",
                ),
            ),
            _requirement(
                "FADEC-SENS-003",
                "EGT dropout response",
                "The control software shall classify sustained EGT dropout as "
                "INVALID, reach FAULT within 0.5 seconds, and command zero fuel.",
                "EGT is required for light-off detection and thermal protection.",
                RequirementCategory.SENSOR_FAULT_RESPONSE,
                RequirementCriticality.CRITICAL,
                "EGT health becomes INVALID, FAULT occurs within 0.5 s, and zero "
                "fuel is commanded within the evaluated response window.",
                "Sensor validation and automatic fault-response concept",
                "TC-SENS-003",
                scenario_ids=("SCN-FAULT-002",),
                executable_requirement_ids=(
                    "REQ-EGT-HEALTH",
                    "REQ-EGT-FAULT-RESPONSE",
                    "REQ-EGT-FUEL-CUTOFF",
                    "REQ-EGT-FAULT-FUEL",
                ),
            ),
            _requirement(
                "FADEC-SENS-004",
                "Sensor-fault coverage and recovery",
                "The control software shall provide deterministic bounded behavior "
                "for bias, drift, stuck, dropout, forced-value, and excessive-noise "
                "faults and their recovery on both sensor channels.",
                "Plausible and implausible sensor failures require explicit "
                "detection and recovery evidence.",
                RequirementCategory.SENSOR_FAULT_RESPONSE,
                RequirementCriticality.MAJOR,
                "Every supported fault type is exercised on RPM and EGT; commands "
                "remain bounded and cleared signals recover according to debounce "
                "configuration.",
                "Supported sensor fault-injection model",
                "TC-SENS-004",
                scenario_ids=("SCN-SENS-004", "SCN-SENS-005"),
                executable_requirement_ids=(
                    "REQ-RPM-FAULT-MATRIX",
                    "REQ-EGT-FAULT-MATRIX",
                ),
            ),
            _requirement(
                "FADEC-SCH-001",
                "No missed logical releases",
                "The control software scheduler shall execute with no missed "
                "logical task releases for approved scheduler presets.",
                "Missed logical releases can invalidate control timing and response "
                "guarantees.",
                RequirementCategory.SCHEDULER_TIMING,
                RequirementCriticality.CRITICAL,
                "Scheduler diagnostics report zero missed releases for every "
                "approved preset in the verification campaign.",
                "Deterministic multi-rate scheduler architecture",
                "TC-SCH-001",
                scenario_ids=(
                    "SCN-SCHED-001",
                    "SCN-SCHED-002",
                    "SCN-SCHED-003",
                    "SCN-SCHED-004",
                ),
                executable_requirement_ids=(
                    "REQ-SCHED-001-NO-MISSED-RELEASES",
                    "REQ-SCHED-002-NO-MISSED-RELEASES",
                    "REQ-SCHED-003-NO-MISSED-RELEASES",
                    "REQ-SCHED-004-NO-MISSED-RELEASES",
                ),
            ),
            _requirement(
                "FADEC-SCH-002",
                "Deterministic task order",
                "The control software scheduler shall execute same-tick tasks in "
                "the configured deterministic priority order and at their exact "
                "integer release counts.",
                "Repeatable scheduling is required for reproducible control and "
                "fault-response evidence.",
                RequirementCategory.SCHEDULER_TIMING,
                RequirementCriticality.CRITICAL,
                "Task-order checks pass and execution counts match configured "
                "periods and phases for every approved preset.",
                "Deterministic multi-rate scheduler architecture",
                "TC-SCH-002",
                scenario_ids=(
                    "SCN-SCHED-001",
                    "SCN-SCHED-002",
                    "SCN-SCHED-003",
                    "SCN-SCHED-004",
                ),
                executable_requirement_ids=(
                    "REQ-SCHED-001-ORDER",
                    "REQ-SCHED-001-SENSOR-COUNT",
                    "REQ-SCHED-002-ORDER",
                    "REQ-SCHED-002-SENSOR-COUNT",
                    "REQ-SCHED-003-ORDER",
                    "REQ-SCHED-003-SENSOR-COUNT",
                    "REQ-SCHED-004-ORDER",
                    "REQ-SCHED-004-SENSOR-COUNT",
                ),
            ),
            _requirement(
                "FADEC-ENV-001",
                "Operating-envelope robustness",
                "The closed-loop system shall satisfy all applicable critical "
                "requirements across the approved ambient temperature and pressure "
                "domain of the selected engine model.",
                "A controller verified only at ISA sea-level conditions has not "
                "demonstrated operating-envelope robustness.",
                RequirementCategory.LOGICAL_INVARIANT,
                RequirementCriticality.CRITICAL,
                "All critical requirements pass at each defined ambient corner; "
                "unsupported profile regions are reported NOT_APPLICABLE rather "
                "than treated as passing.",
                "EngineDefinition applicability and ambient interface",
                "TC-ENV-001",
                scenario_ids=(
                    "SCN-ENV-001",
                    "SCN-ENV-002",
                    "SCN-ENV-003",
                ),
                executable_requirement_ids=(
                    "REQ-ENV-001-AMBIENT",
                    "REQ-ENV-002-AMBIENT",
                    "REQ-ENV-003-AMBIENT",
                ),
            ),
        ),
    )


__all__ = (
    "BaselineRequirement",
    "RequirementBaseline",
    "RequirementBaselineStatus",
    "TraceabilityCoverage",
    "VerificationMethod",
    "fadec_control_requirements_baseline",
)
