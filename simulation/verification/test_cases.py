"""Controlled formal test-case specifications for the FADEC baseline."""

import math
import re
from dataclasses import dataclass
from enum import Enum

from simulation.configuration._serialization import configuration_to_dict
from simulation.configuration.aerodesignworks_b350_stg import (
    AERODESIGNWORKS_B350_STG_PROFILE_ID,
)
from simulation.configuration.jetcat_p1000_pro import (
    JETCAT_P1000_PRO_PROFILE_ID,
)
from simulation.configuration.profiles import REFERENCE_ENGINE_PROFILE_ID
from simulation.operation.engine_state import EngineOperatingState
from simulation.plants.types import PlantModelKind
from simulation.verification.baseline import (
    RequirementBaseline,
    fadec_control_requirements_baseline,
)


class TestCaseCatalogStatus(Enum):
    """Lifecycle state of a controlled test-case catalog."""

    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class VerificationLevel(Enum):
    """System level at which a test case is intended to provide evidence."""

    UNIT = "UNIT"
    SOFTWARE_IN_THE_LOOP = "SIL"
    HARDWARE_IN_THE_LOOP = "HIL"
    ENGINE_BENCH = "ENGINE_BENCH"


class TestCaseImplementationStatus(Enum):
    """Current executable implementation coverage of a formal test case."""

    EXECUTABLE_SCENARIO = "EXECUTABLE_SCENARIO"
    PARTIAL_AUTOMATION = "PARTIAL_AUTOMATION"
    PLANNED = "PLANNED"


@dataclass(frozen=True)
class TestEnvironment:
    """One deterministic ambient and random-seed test condition."""

    name: str
    ambient_temperature_c: float | None
    ambient_pressure_pa: float | None
    random_seed: int

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("test environment name cannot be empty")
        values = (self.ambient_temperature_c, self.ambient_pressure_pa)
        if (values[0] is None) != (values[1] is None):
            raise ValueError(
                "ambient temperature and pressure must both be defined or unresolved"
            )
        if self.ambient_temperature_c is not None and not math.isfinite(
            self.ambient_temperature_c
        ):
            raise ValueError("ambient temperature must be finite")
        if self.ambient_pressure_pa is not None and (
            not math.isfinite(self.ambient_pressure_pa)
            or self.ambient_pressure_pa <= 0.0
        ):
            raise ValueError("ambient pressure must be finite and greater than zero")

    @property
    def is_resolved(self) -> bool:
        """Return whether the ambient values are ready for execution."""

        return (
            self.ambient_temperature_c is not None
            and self.ambient_pressure_pa is not None
        )


@dataclass(frozen=True)
class TestCaseResultRules:
    """Common deterministic interpretation of formal test outcomes."""

    pass_rule: str
    fail_rule: str
    error_rule: str
    not_evaluated_rule: str
    not_applicable_rule: str

    def __post_init__(self) -> None:
        for field_name, value in (
            ("pass_rule", self.pass_rule),
            ("fail_rule", self.fail_rule),
            ("error_rule", self.error_rule),
            ("not_evaluated_rule", self.not_evaluated_rule),
            ("not_applicable_rule", self.not_applicable_rule),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} cannot be empty")


@dataclass(frozen=True)
class TestCaseSpecification:
    """Immutable formal procedure and trace links for one test case."""

    test_case_id: str
    title: str
    purpose: str
    verification_level: VerificationLevel
    implementation_status: TestCaseImplementationStatus
    linked_requirement_ids: tuple[str, ...]
    applicable_profile_ids: tuple[str, ...]
    applicable_plant_models: tuple[PlantModelKind, ...]
    applicability_notes: str
    initial_state: EngineOperatingState
    preconditions: tuple[str, ...]
    environments: tuple[TestEnvironment, ...]
    procedure_steps: tuple[str, ...]
    maximum_duration_s: float
    termination_condition: str
    observed_signals: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    scenario_ids: tuple[str, ...] = ()
    automated_test_references: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if re.fullmatch(r"TC-[A-Z]+-\d{3}", self.test_case_id) is None:
            raise ValueError("test_case_id must match TC-<DOMAIN>-<NNN>")
        for field_name, value in (
            ("title", self.title),
            ("purpose", self.purpose),
            ("applicability_notes", self.applicability_notes),
            ("termination_condition", self.termination_condition),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} cannot be empty")
        for collection_name, values in (
            ("linked requirement IDs", self.linked_requirement_ids),
            ("applicable profile IDs", self.applicable_profile_ids),
            ("applicable plant models", self.applicable_plant_models),
            ("preconditions", self.preconditions),
            ("environments", self.environments),
            ("procedure steps", self.procedure_steps),
            ("observed signals", self.observed_signals),
            ("acceptance criteria", self.acceptance_criteria),
        ):
            if not values:
                raise ValueError(f"{collection_name} cannot be empty")
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {collection_name} are not allowed")
        for requirement_id in self.linked_requirement_ids:
            if re.fullmatch(r"FADEC-[A-Z]+-\d{3}", requirement_id) is None:
                raise ValueError("linked requirement IDs must use FADEC IDs")
        for scenario_id in self.scenario_ids:
            if re.fullmatch(r"SCN-[A-Z0-9-]+-\d{3}", scenario_id) is None:
                raise ValueError("scenario IDs must use stable SCN IDs")
        for reference in self.automated_test_references:
            if not reference.startswith("tests/") or "::" not in reference:
                raise ValueError(
                    "automated test references must be pytest node references"
                )
        if self.maximum_duration_s <= 0.0 or not math.isfinite(
            self.maximum_duration_s
        ):
            raise ValueError("maximum_duration_s must be finite and positive")
        if (
            self.implementation_status
            is TestCaseImplementationStatus.EXECUTABLE_SCENARIO
            and not self.scenario_ids
        ):
            raise ValueError("executable test cases require scenario IDs")
        if (
            self.implementation_status
            is TestCaseImplementationStatus.PARTIAL_AUTOMATION
            and not self.automated_test_references
        ):
            raise ValueError("partially automated test cases require test references")
        if self.implementation_status is TestCaseImplementationStatus.PLANNED and (
            self.scenario_ids or self.automated_test_references
        ):
            raise ValueError("planned test cases cannot claim executable references")
        if (
            self.implementation_status
            is not TestCaseImplementationStatus.PLANNED
            and not all(environment.is_resolved for environment in self.environments)
        ):
            raise ValueError("executable test cases require resolved environments")


@dataclass(frozen=True)
class TestCaseCatalog:
    """Versioned catalog of formal tests controlled against one baseline."""

    catalog_id: str
    version: str
    status: TestCaseCatalogStatus
    requirements_baseline_id: str
    requirements_baseline_version: str
    controlled_requirement_ids: tuple[str, ...]
    result_rules: TestCaseResultRules
    test_cases: tuple[TestCaseSpecification, ...]

    def __post_init__(self) -> None:
        for field_name, value in (
            ("catalog_id", self.catalog_id),
            ("version", self.version),
            ("requirements_baseline_id", self.requirements_baseline_id),
            ("requirements_baseline_version", self.requirements_baseline_version),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} cannot be empty")
        if not self.controlled_requirement_ids:
            raise ValueError("controlled_requirement_ids cannot be empty")
        if not self.test_cases:
            raise ValueError("test_cases cannot be empty")
        test_case_ids = tuple(case.test_case_id for case in self.test_cases)
        if len(test_case_ids) != len(set(test_case_ids)):
            raise ValueError("test-case IDs must be unique")
        traced_requirement_ids = {
            requirement_id
            for case in self.test_cases
            for requirement_id in case.linked_requirement_ids
        }
        if traced_requirement_ids != set(self.controlled_requirement_ids):
            raise ValueError(
                "test-case requirement links must exactly cover the baseline"
            )

    def test_case(self, test_case_id: str) -> TestCaseSpecification:
        """Return one specification by exact stable ID."""

        for test_case in self.test_cases:
            if test_case.test_case_id == test_case_id:
                return test_case
        raise KeyError(f"unknown test case: {test_case_id}")

    def for_requirement(
        self,
        requirement_id: str,
    ) -> tuple[TestCaseSpecification, ...]:
        """Return all test cases linked to one baseline requirement."""

        return tuple(
            test_case
            for test_case in self.test_cases
            if requirement_id in test_case.linked_requirement_ids
        )

    def for_scenario(
        self,
        scenario_id: str,
    ) -> tuple[TestCaseSpecification, ...]:
        """Return all formal test cases implemented by one scenario."""

        return tuple(
            test_case
            for test_case in self.test_cases
            if scenario_id in test_case.scenario_ids
        )

    def requirement_ids_for_scenario(self, scenario_id: str) -> tuple[str, ...]:
        """Return stable baseline IDs traced through one scenario."""

        linked = {
            requirement_id
            for test_case in self.for_scenario(scenario_id)
            for requirement_id in test_case.linked_requirement_ids
        }
        return tuple(
            requirement_id
            for requirement_id in self.controlled_requirement_ids
            if requirement_id in linked
        )

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-compatible catalog snapshot."""

        return configuration_to_dict(self)


_ALL_PROFILES = (
    REFERENCE_ENGINE_PROFILE_ID,
    JETCAT_P1000_PRO_PROFILE_ID,
    AERODESIGNWORKS_B350_STG_PROFILE_ID,
)

_ALL_PLANTS = (
    PlantModelKind.FIRST_ORDER,
    PlantModelKind.PATHSIM_GREYBOX_V1,
)

_NOMINAL_ENVIRONMENT = TestEnvironment(
    name="ISA sea level",
    ambient_temperature_c=15.0,
    ambient_pressure_pa=101_325.0,
    random_seed=0,
)

_DEFAULT_APPLICABILITY = (
    "Execute for every compatible engine profile and supported plant backend. "
    "The B350STG result is provisional family-proxy evidence only."
)

_RESULT_RULES = TestCaseResultRules(
    pass_rule=(
        "The procedure completes and every linked acceptance criterion evaluates "
        "PASS with all required evidence available."
    ),
    fail_rule=(
        "Any completed evaluation outside a linked acceptance criterion evaluates "
        "FAIL."
    ),
    error_rule=(
        "An execution, infrastructure, serialization, or evaluator error evaluates "
        "ERROR and cannot be counted as compliance evidence."
    ),
    not_evaluated_rule=(
        "A missing required signal, action, terminal condition, or incomplete run "
        "evaluates NOT_EVALUATED."
    ),
    not_applicable_rule=(
        "NOT_APPLICABLE requires an explicit profile or backend exclusion in the "
        "controlled applicability data and a recorded rationale."
    ),
)


def _acceptance_criteria(
    baseline: RequirementBaseline,
    requirement_ids: tuple[str, ...],
    additional: tuple[str, ...] = (),
) -> tuple[str, ...]:
    return tuple(
        baseline.requirement(requirement_id).acceptance_criteria
        for requirement_id in requirement_ids
    ) + additional


def _test_case(
    baseline: RequirementBaseline,
    test_case_id: str,
    title: str,
    purpose: str,
    requirement_ids: tuple[str, ...],
    implementation_status: TestCaseImplementationStatus,
    preconditions: tuple[str, ...],
    procedure_steps: tuple[str, ...],
    maximum_duration_s: float,
    termination_condition: str,
    observed_signals: tuple[str, ...],
    *,
    verification_level: VerificationLevel = VerificationLevel.SOFTWARE_IN_THE_LOOP,
    initial_state: EngineOperatingState = EngineOperatingState.OFF,
    environments: tuple[TestEnvironment, ...] = (_NOMINAL_ENVIRONMENT,),
    scenario_ids: tuple[str, ...] = (),
    automated_test_references: tuple[str, ...] = (),
    additional_acceptance: tuple[str, ...] = (),
) -> TestCaseSpecification:
    return TestCaseSpecification(
        test_case_id=test_case_id,
        title=title,
        purpose=purpose,
        verification_level=verification_level,
        implementation_status=implementation_status,
        linked_requirement_ids=requirement_ids,
        applicable_profile_ids=_ALL_PROFILES,
        applicable_plant_models=_ALL_PLANTS,
        applicability_notes=_DEFAULT_APPLICABILITY,
        initial_state=initial_state,
        preconditions=preconditions,
        environments=environments,
        procedure_steps=procedure_steps,
        maximum_duration_s=maximum_duration_s,
        termination_condition=termination_condition,
        observed_signals=observed_signals,
        acceptance_criteria=_acceptance_criteria(
            baseline,
            requirement_ids,
            additional_acceptance,
        ),
        scenario_ids=scenario_ids,
        automated_test_references=automated_test_references,
    )


def fadec_test_case_catalog() -> TestCaseCatalog:
    """Return the draft formal test catalog for the control baseline."""

    baseline = fadec_control_requirements_baseline()
    executable = TestCaseImplementationStatus.EXECUTABLE_SCENARIO
    partial = TestCaseImplementationStatus.PARTIAL_AUTOMATION
    test_cases = (
        _test_case(
            baseline,
            "TC-OPS-001",
            "Normal start to idle",
            "Verify the ordered normal start sequence and bounded time to IDLE.",
            ("FADEC-OPS-001", "FADEC-OPS-002"),
            executable,
            (
                "Engine, controller, sensors, validator, and scheduler are reset.",
                "Both sensor channels are VALID and no fault is active.",
            ),
            (
                "Hold throttle at 0.0 and issue one start request at 0.10 s.",
                "Allow the state machine to complete CRANKING and IGNITION.",
                "Continue until IDLE is observed or the scenario times out.",
            ),
            25.0,
            "IDLE is observed and the lifecycle scenario later completes in OFF.",
            (
                "simulation_time_s",
                "operating_state",
                "starter_commanded",
                "ignition_commanded",
                "allowed_fuel_command",
            ),
            scenario_ids=("SCN-NORMAL-001",),
        ),
        _test_case(
            baseline,
            "TC-OPS-002",
            "Normal shutdown",
            "Verify deterministic shutdown from a running condition to OFF.",
            ("FADEC-OPS-003",),
            executable,
            (
                "The engine has completed a normal start.",
                "The system is in IDLE or RUNNING without an active fault.",
            ),
            (
                "Return the throttle demand to 0.0.",
                "Issue one shutdown request after IDLE is reached.",
                "Continue until OFF is observed or the scenario times out.",
            ),
            32.0,
            "OFF is observed after the shutdown request.",
            (
                "simulation_time_s",
                "operating_state",
                "shutdown_requested",
                "allowed_fuel_command",
                "rotor_speed_rpm",
            ),
            scenario_ids=("SCN-NORMAL-001", "SCN-TRANSIENT-002"),
        ),
        _test_case(
            baseline,
            "TC-OPS-003",
            "Fault reset interlock",
            "Verify that reset cannot clear FAULT while the rotor is turning.",
            ("FADEC-OPS-004",),
            executable,
            (
                "The isolated state machine is reset.",
                "A fault request can be applied at controlled rotor speeds.",
            ),
            (
                "Enter FAULT and request reset above the stopped-speed threshold.",
                "Confirm FAULT is retained.",
                "Reduce validated speed below the threshold and request reset.",
                "Confirm the state transitions to OFF.",
            ),
            30.0,
            "Both reset cases have been evaluated.",
            ("operating_state", "validated_rotor_speed_rpm", "reset_requested"),
            verification_level=VerificationLevel.SOFTWARE_IN_THE_LOOP,
            scenario_ids=("SCN-OPS-003",),
            automated_test_references=(
                "tests/unit/test_engine_state_machine.py::"
                "test_fault_reset_is_rejected_while_rotor_is_turning",
                "tests/unit/test_engine_state_machine.py::"
                "test_fault_reset_succeeds_when_rotor_is_stopped",
            ),
        ),
        _test_case(
            baseline,
            "TC-START-001",
            "Hot-start protection",
            "Verify immediate safe fuel termination at the start EGT limit.",
            ("FADEC-START-001",),
            executable,
            (
                "A controllable EGT fault stimulus is available during IGNITION.",
                "The selected profile defines a transient EGT limit.",
            ),
            (
                "Start the engine and wait for IGNITION.",
                "Drive validated EGT to the transient limit.",
                "Measure protection-task activation, fuel cutoff, and final state.",
            ),
            8.0,
            "Fuel cutoff is observed or the start-protection timeout expires.",
            (
                "simulation_time_s",
                "operating_state",
                "validated_exhaust_temperature_c",
                "egt_maximum_temperature_c",
                "allowed_fuel_command",
                "critical_protection_fault_request",
            ),
            scenario_ids=("SCN-START-001",),
        ),
        _test_case(
            baseline,
            "TC-START-002",
            "Hung-start timeout",
            "Verify safe termination when a start cannot reach IDLE.",
            ("FADEC-START-002",),
            executable,
            (
                "A repeatable plant or sensor stimulus can prevent start completion.",
                "The start timeout is configured to 10.0 s.",
            ),
            (
                "Apply the hung-start stimulus and issue a start request.",
                "Hold the condition so that IDLE cannot be reached.",
                "Observe state and actuator commands through the timeout.",
            ),
            12.0,
            "FAULT and zero fuel are observed or the test duration expires.",
            (
                "simulation_time_s",
                "operating_state",
                "rotor_speed_rpm",
                "exhaust_temperature_c",
                "allowed_fuel_command",
            ),
            scenario_ids=("SCN-START-002",),
        ),
        _test_case(
            baseline,
            "TC-SPD-001",
            "Throttle-to-speed schedule",
            "Verify clamping and linear scheduling at and beyond both boundaries.",
            ("FADEC-SPD-001",),
            executable,
            (
                "A valid profile-specific idle and maximum speed are configured.",
                "The scheduler is reset and used without controller integration.",
            ),
            (
                "Evaluate throttle inputs below, at, between, and above the bounds.",
                "Compare each result with the analytical linear schedule.",
                "Repeat for every controlled engine profile.",
            ),
            16.0,
            "Every defined throttle input has been evaluated.",
            ("throttle_command", "speed_setpoint_rpm"),
            verification_level=VerificationLevel.SOFTWARE_IN_THE_LOOP,
            scenario_ids=("SCN-SPD-001",),
            automated_test_references=(
                "tests/unit/test_speed_controller.py::"
                "test_scheduler_maps_clamped_throttle_to_speed",
            ),
        ),
        _test_case(
            baseline,
            "TC-SPD-002",
            "Closed-loop throttle transient",
            "Verify settling error, dwell time, settling time, and overshoot.",
            ("FADEC-SPD-002", "FADEC-SPD-003"),
            executable,
            (
                "The engine has reached stable IDLE with VALID sensors.",
                "No protection or injected fault is active before the step.",
            ),
            (
                "Start the engine and wait for IDLE.",
                "Command the defined large throttle increase.",
                "Hold demand and capture setpoint and validated rotor speed.",
                "Evaluate overshoot and the continuous settling dwell.",
            ),
            24.0,
            "The settling dwell is complete or the scenario duration expires.",
            (
                "simulation_time_s",
                "throttle_command",
                "speed_setpoint_rpm",
                "validated_rotor_speed_rpm",
                "speed_error_rpm",
            ),
            scenario_ids=("SCN-TRANSIENT-001",),
        ),
        _test_case(
            baseline,
            "TC-ACT-001",
            "Fuel-command bounds",
            "Verify normalized requested and applied fuel bounds across the campaign.",
            ("FADEC-ACT-001",),
            executable,
            (
                "Telemetry records requested and final fuel on every evaluated step.",
                "All mandatory normal, transient, fault, and protection runs execute.",
            ),
            (
                "Execute every linked scenario with deterministic configuration.",
                "Inspect all requested and applied fuel samples.",
                "Aggregate the invariant result across all linked runs.",
            ),
            38.0,
            "Every linked scenario reaches its own terminal condition.",
            ("requested_fuel_command", "allowed_fuel_command"),
            scenario_ids=(
                "SCN-NORMAL-001",
                "SCN-TRANSIENT-001",
                "SCN-TRANSIENT-002",
                "SCN-FAULT-001",
                "SCN-FAULT-002",
                "SCN-PROT-001",
                "SCN-PROT-002",
            ),
        ),
        _test_case(
            baseline,
            "TC-ACT-002",
            "Safe-state fuel cutoff",
            "Verify that OFF and FAULT never sustain a nonzero final fuel command.",
            ("FADEC-ACT-002",),
            executable,
            (
                "The normal lifecycle and hard-overspeed scenarios are available.",
                "Final actuator commands are sampled with operating state.",
            ),
            (
                "Execute a normal lifecycle containing OFF intervals.",
                "Execute a hard-overspeed transition to FAULT.",
                "Inspect final fuel for every OFF and FAULT sample.",
            ),
            38.0,
            "Both linked scenarios complete or explicitly time out.",
            ("operating_state", "allowed_fuel_command", "fuel_enabled"),
            scenario_ids=("SCN-NORMAL-001", "SCN-PROT-002"),
        ),
        _test_case(
            baseline,
            "TC-ACT-003",
            "Starter disengagement",
            "Verify that the starter is inactive throughout RUNNING.",
            ("FADEC-ACT-003",),
            executable,
            (
                "A normal lifecycle enters RUNNING.",
                "Starter state and operating state are sampled together.",
            ),
            (
                "Execute the normal start and advance throttle into RUNNING.",
                "Inspect every starter command while RUNNING is active.",
            ),
            25.0,
            "The normal lifecycle completes in OFF.",
            ("operating_state", "starter_commanded"),
            scenario_ids=("SCN-NORMAL-001",),
        ),
        _test_case(
            baseline,
            "TC-EGT-001",
            "EGT fuel-limiter characteristic",
            "Verify monotonic fuel restriction through the configured EGT region.",
            ("FADEC-EGT-001",),
            executable,
            (
                "The profile-specific intervention and maximum EGT are configured.",
                "Requested fuel is held constant during the temperature sweep.",
            ),
            (
                "Start below the intervention temperature.",
                "Sweep validated EGT through intervention and maximum temperatures.",
                "Record the resulting EGT upper fuel limit at every point.",
            ),
            16.0,
            "The complete configured EGT sweep has been evaluated.",
            (
                "validated_exhaust_temperature_c",
                "requested_fuel_command",
                "egt_fuel_limit",
                "allowed_fuel_command",
            ),
            scenario_ids=("SCN-PROT-003",),
            automated_test_references=(
                "tests/unit/test_exhaust_temperature_limiter.py::"
                "test_limiter_progressively_reduces_fuel_in_intervention_region",
                "tests/unit/test_exhaust_temperature_limiter.py::"
                "test_limiter_reduces_fuel_more_strongly_at_maximum_temperature",
                "tests/unit/test_exhaust_temperature_limiter.py::"
                "test_limiter_never_increases_requested_fuel",
            ),
        ),
        _test_case(
            baseline,
            "TC-EGT-002",
            "System transient EGT limit",
            "Verify true peak EGT against the selected engine operating envelope.",
            ("FADEC-EGT-002",),
            executable,
            (
                "The selected EngineDefinition has an evidence-backed transient limit.",
                "Normal and worst-case transient stimuli are formally defined.",
            ),
            (
                "Execute start, acceleration, deceleration, and shutdown transients.",
                "Capture true EGT at the plant integration rate.",
                "Compare the aggregate peak with the profile transient limit.",
            ),
            38.0,
            "Every defined thermal transient has completed.",
            (
                "simulation_time_s",
                "exhaust_temperature_c",
                "egt_maximum_temperature_c",
                "active_protection_limiter",
            ),
            scenario_ids=(
                "SCN-NORMAL-001",
                "SCN-TRANSIENT-001",
                "SCN-TRANSIENT-002",
            ),
        ),
        _test_case(
            baseline,
            "TC-ACC-001",
            "Rotor-acceleration limiting",
            "Verify bounded acceleration during a large positive throttle step.",
            ("FADEC-ACC-001",),
            executable,
            (
                "The engine is stable at IDLE with VALID rotor-speed feedback.",
                "The profile acceleration thresholds and tolerance are recorded.",
            ),
            (
                "Command the defined large throttle step.",
                "Hold demand through limiter activation and recovery.",
                "Evaluate acceleration and limiter-event evidence.",
            ),
            24.0,
            "The acceleration evaluation window completes.",
            (
                "rotor_acceleration_rpm_per_s",
                "acceleration_fuel_limit",
                "active_protection_limiter",
                "allowed_fuel_command",
            ),
            scenario_ids=("SCN-TRANSIENT-001",),
        ),
        _test_case(
            baseline,
            "TC-DEC-001",
            "Fuel-deceleration limiting",
            "Verify bounded fuel reduction without delaying a requested shutdown.",
            ("FADEC-DEC-001",),
            executable,
            (
                "The engine is stable in RUNNING at the defined high throttle.",
                "The deceleration rate calibration is recorded.",
            ),
            (
                "Command the defined rapid throttle reduction.",
                "Observe the deceleration lower fuel bound.",
                "Request shutdown and verify that safety cutoff overrides the ramp.",
            ),
            32.0,
            "The system reaches OFF after the shutdown request.",
            (
                "requested_fuel_command",
                "deceleration_minimum_fuel_command",
                "allowed_fuel_command",
                "operating_state",
            ),
            scenario_ids=("SCN-TRANSIENT-002",),
        ),
        _test_case(
            baseline,
            "TC-OVS-001",
            "Soft-overspeed intervention",
            "Verify progressive speed recovery without hard cutoff or FAULT.",
            ("FADEC-OVS-001",),
            executable,
            (
                "The engine is running below the soft-overspeed threshold.",
                "A validated-speed stimulus can enter only the soft region.",
            ),
            (
                "Apply the defined soft-overspeed stimulus.",
                "Observe overspeed fuel restriction and recovery.",
                "Confirm no hard-cutoff or automatic-fault event occurs.",
            ),
            36.0,
            "The soft-overspeed recovery and shutdown sequence completes.",
            (
                "validated_rotor_speed_rpm",
                "speed_ratio",
                "overspeed_fuel_limit",
                "hard_overspeed_active",
                "critical_protection_fault_request",
            ),
            scenario_ids=("SCN-PROT-001",),
        ),
        _test_case(
            baseline,
            "TC-OVS-002",
            "Hard-overspeed cutoff",
            "Verify bounded-latency zero fuel and transition to FAULT.",
            ("FADEC-OVS-002",),
            executable,
            (
                "The engine is in RUNNING with VALID speed feedback.",
                "A validated-speed stimulus can reach the hard threshold.",
            ),
            (
                "Apply the hard-overspeed stimulus.",
                "Measure time from hard activation to zero final fuel.",
                "Continue until FAULT is observed.",
            ),
            38.0,
            "FAULT and zero fuel are observed.",
            (
                "simulation_time_s",
                "validated_rotor_speed_rpm",
                "hard_overspeed_active",
                "allowed_fuel_command",
                "operating_state",
            ),
            scenario_ids=("SCN-PROT-002",),
        ),
        _test_case(
            baseline,
            "TC-PROT-001",
            "Protection arbitration",
            "Verify the most restrictive valid limit and absolute cutoff priority.",
            ("FADEC-PROT-001",),
            executable,
            (
                "Candidate upper and lower limits can be independently controlled.",
                "Manager state is reset before each arbitration combination.",
            ),
            (
                "Evaluate single and concurrent upper-limit combinations.",
                "Evaluate lower-bound conflicts with every safety upper limit.",
                "Activate hard cutoff with competing nonzero limits.",
                "Compare final fuel and diagnostics with analytical arbitration.",
            ),
            38.0,
            "Every defined arbitration combination has been evaluated.",
            (
                "requested_fuel_command",
                "allowed_fuel_command",
                "constraining_protection_limiters",
                "protection_hard_cutoff_active",
                "protection_arbitration_conflict",
            ),
            verification_level=VerificationLevel.SOFTWARE_IN_THE_LOOP,
            scenario_ids=("SCN-PROT-003", "SCN-PROT-002"),
            automated_test_references=(
                "tests/unit/test_protection_manager.py::"
                "test_smallest_active_upper_fuel_limit_is_selected",
                "tests/unit/test_protection_manager.py::"
                "test_deceleration_lower_bound_cannot_override_safety_upper_limit",
                "tests/unit/test_protection_manager.py::"
                "test_hard_cutoff_always_produces_zero_fuel",
            ),
        ),
        _test_case(
            baseline,
            "TC-SENS-001",
            "No plant-truth fallback",
            "Verify that unavailable measurements never reveal true plant values.",
            ("FADEC-SENS-001",),
            executable,
            (
                "The engine is RUNNING with both sensor channels VALID.",
                "Plant truth and validated values are separately observable.",
            ),
            (
                "Execute the RPM dropout scenario and inspect validated feedback.",
                "Execute the EGT dropout scenario and inspect validated feedback.",
                "Confirm held values expire without being replaced by truth.",
            ),
            24.0,
            "Both dropout scenarios reach their expected safe terminal state.",
            (
                "rotor_speed_rpm",
                "validated_rotor_speed_rpm",
                "exhaust_temperature_c",
                "validated_exhaust_temperature_c",
            ),
            scenario_ids=("SCN-FAULT-001", "SCN-FAULT-002"),
        ),
        _test_case(
            baseline,
            "TC-SENS-002",
            "Rotor-speed dropout response",
            "Verify detection, bounded fault response, and fuel cutoff.",
            ("FADEC-SENS-002",),
            executable,
            (
                "The engine is RUNNING with rotor-speed health VALID.",
                "No other sensor fault or protection cutoff is active.",
            ),
            (
                "Inject a rotor-speed dropout at the defined scenario point.",
                "Measure invalidation, FAULT transition, and fuel-cutoff timing.",
                "Continue until FAULT is stable.",
            ),
            24.0,
            "FAULT and zero fuel are observed after dropout.",
            (
                "simulation_time_s",
                "rotor_speed_health",
                "automatic_sensor_fault_request_active",
                "allowed_fuel_command",
                "operating_state",
            ),
            scenario_ids=("SCN-FAULT-001",),
        ),
        _test_case(
            baseline,
            "TC-SENS-003",
            "EGT dropout response",
            "Verify detection, bounded fault response, and fuel cutoff.",
            ("FADEC-SENS-003",),
            executable,
            (
                "The engine is RUNNING with EGT health VALID.",
                "No other sensor fault or protection cutoff is active.",
            ),
            (
                "Inject an EGT dropout at the defined scenario point.",
                "Measure invalidation, FAULT transition, and fuel-cutoff timing.",
                "Continue until FAULT is stable.",
            ),
            24.0,
            "FAULT and zero fuel are observed after dropout.",
            (
                "simulation_time_s",
                "exhaust_temperature_health",
                "automatic_sensor_fault_request_active",
                "allowed_fuel_command",
                "operating_state",
            ),
            scenario_ids=("SCN-FAULT-002",),
        ),
        _test_case(
            baseline,
            "TC-SENS-004",
            "Sensor fault and recovery matrix",
            "Verify every supported fault class and deterministic recovery by channel.",
            ("FADEC-SENS-004",),
            executable,
            (
                "Both channels start VALID at a stable operating condition.",
                "Fault magnitude and duration are defined for each matrix cell.",
            ),
            (
                "Apply bias, drift, stuck, dropout, forced, and noise faults to RPM.",
                "Clear each fault and measure validation recovery.",
                "Repeat the complete matrix for EGT.",
                "Confirm bounded fuel and deterministic results for the fixed seed.",
            ),
            25.0,
            "Every fault/channel/recovery matrix cell has been evaluated.",
            (
                "rotor_speed_fault_type",
                "exhaust_temperature_fault_type",
                "rotor_speed_health",
                "exhaust_temperature_health",
                "allowed_fuel_command",
            ),
            scenario_ids=("SCN-SENS-004", "SCN-SENS-005"),
            automated_test_references=(
                "tests/unit/test_sensor_fault_injection.py::"
                "test_bias_fault_adds_configured_offset",
                "tests/unit/test_sensor_fault_injection.py::"
                "test_stuck_current_fault_freezes_activation_value",
                "tests/unit/test_sensor_fault_injection.py::"
                "test_dropout_produces_explicit_unavailable_measurement",
                "tests/unit/test_sensor_fault_injection.py::"
                "test_forced_value_fault_publishes_configured_value",
                "tests/unit/test_sensor_fault_injection.py::"
                "test_excessive_noise_fault_is_deterministic_with_fixed_seed",
                "tests/unit/test_sensor_fault_injection.py::"
                "test_drift_increases_with_elapsed_fault_time",
                "tests/unit/test_sensor_fault_injection.py::"
                "test_clearing_fault_restores_normal_sensor_model_output",
                "tests/unit/test_sensor_fault_injection.py::"
                "test_rotor_speed_and_egt_faults_operate_independently",
            ),
        ),
        _test_case(
            baseline,
            "TC-SCH-001",
            "Scheduler release integrity",
            "Verify zero missed logical releases for every approved preset.",
            ("FADEC-SCH-001",),
            executable,
            (
                "The controlled scheduler presets are available and immutable.",
                "Each scenario starts from scheduler tick zero.",
            ),
            (
                "Execute every linked scheduler regression scenario.",
                "Inspect missed-release diagnostics on every captured snapshot.",
                "Aggregate the maximum count across presets and behaviors.",
            ),
            25.0,
            "Every linked scheduler scenario completes.",
            ("scheduler_preset", "scheduler_tick", "scheduler_missed_release_count"),
            scenario_ids=(
                "SCN-SCHED-001",
                "SCN-SCHED-002",
                "SCN-SCHED-003",
                "SCN-SCHED-004",
            ),
        ),
        _test_case(
            baseline,
            "TC-SCH-002",
            "Scheduler order and execution counts",
            "Verify deterministic same-tick order and exact integer release counts.",
            ("FADEC-SCH-002",),
            executable,
            (
                "Task periods, phases, and priorities are recorded in metadata.",
                "Each scenario starts from scheduler tick zero.",
            ),
            (
                "Execute every linked scheduler regression scenario.",
                "Compare same-tick task sequences with configured priority.",
                "Compare execution counts with analytical integer releases.",
            ),
            25.0,
            "Every linked scheduler scenario completes.",
            (
                "scheduler_tick",
                "scheduler_tasks_executed_current_tick",
                "sensor_execution_count",
                "controller_execution_count",
                "protection_execution_count",
                "state_machine_execution_count",
            ),
            scenario_ids=(
                "SCN-SCHED-001",
                "SCN-SCHED-002",
                "SCN-SCHED-003",
                "SCN-SCHED-004",
            ),
        ),
        _test_case(
            baseline,
            "TC-ENV-001",
            "Ambient operating-envelope campaign",
            "Establish controlled SIL evidence before physical ambient modelling.",
            ("FADEC-ENV-001",),
            partial,
            (
                "Project-selected SIL challenge points are explicitly identified.",
                "The plant backend supports controlled ambient initialization.",
                "Physical ambient sensitivity is not claimed by this campaign.",
            ),
            (
                "Execute the lifecycle at low, nominal, and high SIL points.",
                "Verify the ambient inputs recorded in every snapshot.",
                "Require finite plant outputs and bounded final fuel commands.",
            ),
            300.0,
            "Every defined SIL ambient challenge completes with controlled inputs.",
            (
                "ambient_temperature_c",
                "ambient_pressure_pa",
                "plant_model_id",
                "overall_verification_result",
            ),
            environments=(
                TestEnvironment("SIL low challenge", -20.0, 80_000.0, 0),
                _NOMINAL_ENVIRONMENT,
                TestEnvironment("SIL high challenge", 40.0, 105_000.0, 0),
            ),
            scenario_ids=("SCN-ENV-001", "SCN-ENV-002", "SCN-ENV-003"),
            automated_test_references=(
                "tests/integration/test_scenario_verification.py::"
                "test_ambient_challenge_scenarios_propagate_controlled_inputs",
            ),
            additional_acceptance=(
                "These SIL results do not establish physical ambient-envelope "
                "compliance until an ambient-sensitive validated plant is used.",
            ),
        ),
    )
    return TestCaseCatalog(
        catalog_id="MINI-FADEC-TEST-CASES",
        version="0.1.0",
        status=TestCaseCatalogStatus.DRAFT,
        requirements_baseline_id=baseline.baseline_id,
        requirements_baseline_version=baseline.version,
        controlled_requirement_ids=tuple(
            requirement.requirement_id for requirement in baseline.requirements
        ),
        result_rules=_RESULT_RULES,
        test_cases=test_cases,
    )


__all__ = (
    "TestCaseCatalog",
    "TestCaseCatalogStatus",
    "TestCaseImplementationStatus",
    "TestCaseResultRules",
    "TestCaseSpecification",
    "TestEnvironment",
    "VerificationLevel",
    "fadec_test_case_catalog",
)
