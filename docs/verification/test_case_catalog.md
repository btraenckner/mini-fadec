# Mini-FADEC Formal Test-Case Catalog

## Document control

| Field | Value |
|---|---|
| Catalog ID | `MINI-FADEC-TEST-CASES` |
| Version | `0.1.0` |
| Status | `DRAFT` |
| Requirements baseline | `MINI-FADEC-CONTROL-REQ` version `0.1.0` |
| Machine-readable source | `simulation/verification/test_cases.py` |

The machine-readable source is normative for procedure fields and trace
links. This document is its review index. Both remain draft until the
requirements, applicability, limits, procedures, and evidence rules receive
engineering approval.

## Specification content

Every test specification controls its purpose, verification level, linked
`FADEC-*` requirements, applicable engine profiles and plant backends,
initial state, preconditions, ambient conditions, deterministic seed,
procedure, maximum duration, termination condition, observed signals,
acceptance criteria, scenario links, and automated-test references.

All nominal cases use 15 °C, 101,325 Pa, and random seed 0. They are intended
for the reference, JetCat P1000-PRO, and provisional AeroDesignWorks B350STG
profiles with both supported plant backends. Compatibility is checked before
execution. B350STG results remain family-proxy evidence and cannot support a
physical-engine compliance claim.

`EXECUTABLE_SCENARIO` identifies an existing scenario trace, not a PASS.
`PARTIAL_AUTOMATION` identifies useful unit automation without a complete
formal scenario evidence package. `PLANNED` identifies an open implementation
gap.

## Operating-state and start test cases

### TC-OPS-001 — Normal start to idle

- Requirements: `FADEC-OPS-001`, `FADEC-OPS-002`
- Level/status: `SIL` / `EXECUTABLE_SCENARIO`
- Scenario: `SCN-NORMAL-001`
- Preconditions: Reset system, healthy sensors, no injected fault, throttle
  at 0.0.
- Procedure: Issue start at 0.10 s; observe `OFF`, `CRANKING`, `IGNITION`, and
  `IDLE`; retain the lifecycle recording through normal shutdown.
- Evidence: State sequence, state timing, starter, ignition, and final fuel.
- Duration/termination: 25 s maximum; `IDLE` must be observed and the complete
  linked lifecycle must terminate in `OFF`.

### TC-OPS-002 — Normal shutdown

- Requirement: `FADEC-OPS-003`
- Level/status: `SIL` / `EXECUTABLE_SCENARIO`
- Scenarios: `SCN-NORMAL-001`, `SCN-TRANSIENT-002`
- Preconditions: Started engine in `IDLE` or `RUNNING`, healthy sensors, no
  fault.
- Procedure: Return to idle, issue shutdown, and continue until `OFF`.
- Evidence: Shutdown-action time, state sequence, true speed, and final fuel.
- Duration/termination: 32 s maximum across the linked scenarios; `OFF` must
  follow shutdown.

### TC-OPS-003 — Fault reset interlock

- Requirement: `FADEC-OPS-004`
- Level/status: `SIL` / `PARTIAL_AUTOMATION`
- Current automation: State-machine reset rejection and acceptance unit tests.
- Procedure: Request reset in `FAULT` above the stopped-speed threshold, then
  repeat below the threshold.
- Evidence gap: An integrated scenario and report artifact are still required.

### TC-START-001 — Hot-start protection

- Requirement: `FADEC-START-001`
- Level/status: `SIL` / `PLANNED`
- Procedure: Enter `IGNITION`, drive validated EGT to the profile transient
  limit, and measure protection-task activation and fuel cutoff.
- Evidence: Validated EGT, configured limit, final fuel, state, and fault
  request.
- Duration/termination: 15 s maximum; stop after safe cutoff or timeout.

### TC-START-002 — Hung-start timeout

- Requirement: `FADEC-START-002`
- Level/status: `SIL` / `PLANNED`
- Procedure: Apply a controlled stimulus that prevents `IDLE`, request start,
  and retain the stimulus through the 10 s start timeout.
- Evidence: State timing, speed, EGT, and final fuel.
- Duration/termination: 12 s maximum; `FAULT` and zero fuel are required.

## Speed-control and actuator test cases

### TC-SPD-001 — Throttle-to-speed schedule

- Requirement: `FADEC-SPD-001`
- Level/status: `UNIT` / `PARTIAL_AUTOMATION`
- Procedure: Evaluate throttle below, at, between, and above 0.0 and 1.0 for
  every controlled profile; compare with the analytical linear schedule.
- Current automation: Scheduler clamping and interpolation unit test.
- Evidence gap: Profile-parameterized formal result aggregation is required.

### TC-SPD-002 — Closed-loop throttle transient

- Requirements: `FADEC-SPD-002`, `FADEC-SPD-003`
- Level/status: `SIL` / `EXECUTABLE_SCENARIO`
- Scenario: `SCN-TRANSIENT-001`
- Procedure: Start to stable idle, command the large throttle increase, hold
  demand, and evaluate overshoot plus the continuous settling dwell.
- Evidence: Setpoint, validated speed, speed error, peak, and dwell time.
- Duration/termination: 24 s maximum; stop after the settling window.

### TC-ACT-001 — Fuel-command bounds

- Requirement: `FADEC-ACT-001`
- Level/status: `SIL` / `EXECUTABLE_SCENARIO`
- Scenarios: All linked normal, transient, fault, and protection regressions.
- Procedure: Inspect every requested and applied fuel sample and aggregate the
  invariant across the campaign.
- Evidence: `requested_fuel_command` and `allowed_fuel_command`.

### TC-ACT-002 — Safe-state fuel cutoff

- Requirement: `FADEC-ACT-002`
- Level/status: `SIL` / `EXECUTABLE_SCENARIO`
- Scenarios: `SCN-NORMAL-001`, `SCN-PROT-002`
- Procedure: Inspect every final fuel command recorded in `OFF` and `FAULT`.
- Evidence: State, final fuel, and fuel-enable command.

### TC-ACT-003 — Starter disengagement

- Requirement: `FADEC-ACT-003`
- Level/status: `SIL` / `EXECUTABLE_SCENARIO`
- Scenario: `SCN-NORMAL-001`
- Procedure: Inspect every starter command while the lifecycle is in
  `RUNNING`.
- Evidence: State and starter command.

## Protection test cases

### TC-EGT-001 — EGT fuel-limiter characteristic

- Requirement: `FADEC-EGT-001`
- Level/status: `SIL` / `PARTIAL_AUTOMATION`
- Procedure: Hold requested fuel constant and sweep validated EGT from below
  intervention through the maximum temperature.
- Current automation: Isolated EGT-limiter monotonicity and bound tests.
- Evidence gap: Integrated sensor-to-final-actuator scenario evidence.

### TC-EGT-002 — System transient EGT limit

- Requirement: `FADEC-EGT-002`
- Level/status: `SIL` / `PLANNED`
- Procedure: Execute defined start, acceleration, deceleration, and shutdown
  transients and capture true EGT at plant integration rate.
- Evidence: Aggregate true EGT peak and profile transient EGT limit.
- Duration/termination: 38 s maximum per transient scenario.

### TC-ACC-001 — Rotor-acceleration limiting

- Requirement: `FADEC-ACC-001`
- Level/status: `SIL` / `EXECUTABLE_SCENARIO`
- Scenario: `SCN-TRANSIENT-001`
- Procedure: Apply a large positive throttle step and evaluate acceleration,
  limiter activation, and allowed fuel through recovery.

### TC-DEC-001 — Fuel-deceleration limiting

- Requirement: `FADEC-DEC-001`
- Level/status: `SIL` / `EXECUTABLE_SCENARIO`
- Scenario: `SCN-TRANSIENT-002`
- Procedure: Apply the rapid throttle reduction, observe the lower fuel bound,
  then verify shutdown overrides the normal deceleration ramp.

### TC-OVS-001 — Soft-overspeed intervention

- Requirement: `FADEC-OVS-001`
- Level/status: `SIL` / `EXECUTABLE_SCENARIO`
- Scenario: `SCN-PROT-001`
- Procedure: Enter only the soft-overspeed region; verify fuel restriction and
  recovery without hard cutoff or automatic `FAULT`.

### TC-OVS-002 — Hard-overspeed cutoff

- Requirement: `FADEC-OVS-002`
- Level/status: `SIL` / `EXECUTABLE_SCENARIO`
- Scenario: `SCN-PROT-002`
- Procedure: Reach the hard threshold and measure time to zero final fuel and
  transition to `FAULT`.

### TC-PROT-001 — Protection arbitration

- Requirement: `FADEC-PROT-001`
- Level/status: `UNIT` / `PARTIAL_AUTOMATION`
- Procedure: Evaluate individual and concurrent upper limits, lower-bound
  conflicts, equal limits, and hard cutoff with competing nonzero limits.
- Current automation: Restrictive-upper-limit, safety-conflict, and hard-cutoff
  manager unit tests.
- Evidence gap: Complete controlled input-combination coverage and evidence
  artifact.

## Sensor and scheduler test cases

### TC-SENS-001 — No plant-truth fallback

- Requirement: `FADEC-SENS-001`
- Level/status: `SIL` / `EXECUTABLE_SCENARIO`
- Scenarios: `SCN-FAULT-001`, `SCN-FAULT-002`
- Procedure: Drop out each channel, let held values expire, and confirm that
  validated feedback never becomes plant truth.

### TC-SENS-002 — Rotor-speed dropout response

- Requirement: `FADEC-SENS-002`
- Level/status: `SIL` / `EXECUTABLE_SCENARIO`
- Scenario: `SCN-FAULT-001`
- Procedure: Inject dropout in `RUNNING` and measure invalidation, `FAULT`, and
  zero-fuel response time.

### TC-SENS-003 — EGT dropout response

- Requirement: `FADEC-SENS-003`
- Level/status: `SIL` / `EXECUTABLE_SCENARIO`
- Scenario: `SCN-FAULT-002`
- Procedure: Inject dropout in `RUNNING` and measure invalidation, `FAULT`, and
  zero-fuel response time.

### TC-SENS-004 — Sensor fault and recovery matrix

- Requirement: `FADEC-SENS-004`
- Level/status: `SIL` / `PARTIAL_AUTOMATION`
- Procedure: Apply bias, drift, stuck, dropout, forced-value, and excessive
  noise faults independently to RPM and EGT; clear every fault and measure
  validation recovery.
- Current automation: Fault-injector behavior, independence, deterministic
  noise, and clear-fault unit tests.
- Evidence gap: Complete integrated fault/channel/recovery matrix.

### TC-SCH-001 — Scheduler release integrity

- Requirement: `FADEC-SCH-001`
- Level/status: `SIL` / `EXECUTABLE_SCENARIO`
- Scenarios: `SCN-SCHED-001` through `SCN-SCHED-004`
- Procedure: Execute every approved preset and aggregate the maximum missed
  logical release count.

### TC-SCH-002 — Scheduler order and execution counts

- Requirement: `FADEC-SCH-002`
- Level/status: `SIL` / `EXECUTABLE_SCENARIO`
- Scenarios: `SCN-SCHED-001` through `SCN-SCHED-004`
- Procedure: Compare same-tick task order with priority and counts with exact
  integer periods and phases.

## Operating-envelope test case

### TC-ENV-001 — Ambient operating-envelope campaign

- Requirement: `FADEC-ENV-001`
- Level/status: `SIL` / `PLANNED`
- Procedure: Resolve profile-specific low, nominal, and high ambient corners;
  execute all applicable critical scenarios at every corner.
- Evidence: Ambient conditions, controlled profile/backend, and aggregate
  critical requirement status.
- Open prerequisite: The approved ambient domain is not yet represented by
  every `EngineDefinition`; unresolved corners are deliberately stored as
  unresolved rather than populated with invented limits.

## Result interpretation

- `PASS`: The procedure completes and every linked criterion passes with all
  required evidence.
- `FAIL`: At least one completed criterion evaluation is outside its limit.
- `ERROR`: Execution, infrastructure, serialization, or evaluation failed.
- `NOT_EVALUATED`: Required data, action, terminal state, or run completion is
  missing.
- `NOT_APPLICABLE`: A controlled profile/backend exclusion and rationale exist;
  unsupported configurations must never be counted as passing.

## Catalog summary

| Implementation status | Test cases |
|---|---:|
| `EXECUTABLE_SCENARIO` | 15 |
| `PARTIAL_AUTOMATION` | 5 |
| `PLANNED` | 4 |
| Total | 24 |
