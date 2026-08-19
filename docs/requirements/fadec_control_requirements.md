# Mini-FADEC Control Software Requirements

## Document control

| Field | Value |
|---|---|
| Baseline ID | `MINI-FADEC-CONTROL-REQ` |
| Version | `0.1.0` |
| Status | `DRAFT` |
| Machine-readable source | `simulation/verification/baseline.py` |
| Applicability | All compatible engine profiles unless stated otherwise |

Version `0.1.0` is a proposed baseline for engineering review. Its IDs are
stable for test development, but the limits, criticalities, and scope are not
approved until the baseline is reviewed and promoted to `APPROVED` version
`1.0.0`.

## Scope and claim boundary

This baseline covers Mini-FADEC operating-state management, closed-loop speed
control, actuator commands, centralized fuel protection, validated-sensor fault
response, and deterministic scheduling. It does not define engine mechanical
design, fuel-system hardware reliability, electrical hardware, or installation
safety.

Passing software-in-the-loop tests demonstrates compliance against the exact
recorded `EngineDefinition`, `FadecCalibration`, plant backend, and software
revision. It does not by itself demonstrate compliance on a physical engine.
The AeroDesignWorks B350STG profile remains a provisional family proxy, so its
results cannot be presented as B350STG engine-validation evidence.

## Normative language and classification

`Shall` identifies a mandatory requirement. `CRITICAL` means that failure
invalidates the verification campaign and can defeat a safety function.
`MAJOR` means that failure invalidates required operating or performance
behavior. Project-selected limits without manufacturer evidence must be
reviewed when better engine data become available.

## Operating-state requirements

### FADEC-OPS-001 — Normal start sequence

- Requirement: The control software shall execute `OFF`, `CRANKING`,
  `IGNITION`, and `IDLE` in that order after a valid start request.
- Acceptance: The recorded state sequence contains those states in order with
  no intervening `FAULT` state.
- Criticality: `CRITICAL`
- Source: Project operating-state concept
- Planned test: `TC-OPS-001`

### FADEC-OPS-002 — Start completion time

- Requirement: The control software shall command a start that reaches `IDLE`
  within 10 seconds of a valid start request.
- Acceptance: `IDLE` is first observed no later than 10.0 s after the start
  action.
- Criticality: `MAJOR`
- Source: Current Mini-FADEC development target
- Planned test: `TC-OPS-001`

### FADEC-OPS-003 — Normal shutdown time

- Requirement: The control software shall reach `OFF` within 8 seconds of a
  valid shutdown request.
- Acceptance: `OFF` is first observed no later than 8.0 s after the shutdown
  action.
- Criticality: `MAJOR`
- Source: Current Mini-FADEC development target
- Planned test: `TC-OPS-002`

### FADEC-OPS-004 — Fault reset interlock

- Requirement: The control software shall accept a reset from `FAULT` only
  when validated rotor speed is at or below the configured stopped-speed
  threshold.
- Acceptance: Reset above the stopped threshold leaves the state at `FAULT`;
  reset at or below the threshold transitions to `OFF`.
- Criticality: `CRITICAL`
- Source: Engine-state-machine safety interlock
- Planned test: `TC-OPS-003`

## Start-protection requirements

### FADEC-START-001 — Hot-start protection

- Requirement: The control software shall terminate fuel delivery during start
  when validated EGT reaches the engine transient EGT limit.
- Acceptance: Fuel reaches 0.0 no later than one protection-task period after
  validated EGT reaches the transient limit during `IGNITION`.
- Criticality: `CRITICAL`
- Source: `EngineDefinition` transient EGT limit
- Planned test: `TC-START-001`

### FADEC-START-002 — Hung-start timeout

- Requirement: The control software shall terminate an unsuccessful start that
  does not reach `IDLE` within 10 seconds.
- Acceptance: The system enters `FAULT` and commands fuel off no later than
  10.0 s after start when `IDLE` has not been reached.
- Criticality: `CRITICAL`
- Source: Current Mini-FADEC development target
- Planned test: `TC-START-002`

## Speed-control requirements

### FADEC-SPD-001 — Throttle-to-speed schedule

- Requirement: The control software shall clamp throttle demand to 0.0 through
  1.0 and schedule speed between the configured idle and maximum continuous
  engine speeds.
- Acceptance: Throttle below 0.0 maps to idle, throttle above 1.0 maps to
  maximum continuous speed, and intermediate values map linearly.
- Criticality: `MAJOR`
- Source: `EngineDefinition` operating envelope
- Planned test: `TC-SPD-001`

### FADEC-SPD-002 — Speed settling

- Requirement: The closed-loop system shall settle within 2 percent of
  scheduled rotor speed for at least 0.5 seconds within 10 seconds of a
  throttle step.
- Acceptance: Validated speed remains within ±2.0% of setpoint for 0.5 s and
  first satisfies that dwell no later than 10.0 s after the step.
- Criticality: `MAJOR`
- Source: Current Mini-FADEC closed-loop performance target
- Planned test: `TC-SPD-002`

### FADEC-SPD-003 — Speed overshoot

- Requirement: The closed-loop system shall limit rotor-speed overshoot to less
  than 3 percent after a throttle increase.
- Acceptance: Maximum validated speed during the 8.0 s evaluation window is
  less than 103% of scheduled speed.
- Criticality: `MAJOR`
- Source: Current Mini-FADEC closed-loop performance target
- Planned test: `TC-SPD-002`

## Actuator-safety requirements

### FADEC-ACT-001 — Fuel-command bounds

- Requirement: The control software shall keep requested and applied normalized
  fuel commands between 0.0 and 1.0 inclusive.
- Acceptance: Every recorded requested and applied fuel command is in `[0, 1]`.
- Criticality: `CRITICAL`
- Source: `EngineDefinition` actuator interface
- Planned test: `TC-ACT-001`

### FADEC-ACT-002 — Safe-state fuel cutoff

- Requirement: The control software shall command zero fuel in `OFF` and
  `FAULT`.
- Acceptance: Every applied fuel sample in `OFF` or `FAULT` equals 0.0.
- Criticality: `CRITICAL`
- Source: Engine operating-state safety concept
- Planned test: `TC-ACT-002`

### FADEC-ACT-003 — Starter disengagement

- Requirement: The control software shall keep the starter command inactive in
  `RUNNING`.
- Acceptance: Every starter command recorded in `RUNNING` is false.
- Criticality: `CRITICAL`
- Source: Engine operating-state safety concept
- Planned test: `TC-ACT-003`

## Thermal and transient protection requirements

### FADEC-EGT-001 — EGT fuel limiting

- Requirement: The control software shall reduce the allowed fuel command when
  validated EGT exceeds the configured intervention temperature.
- Acceptance: Under constant requested fuel, allowed fuel is below requested
  fuel above intervention EGT and does not increase as EGT approaches the
  maximum limit.
- Criticality: `CRITICAL`
- Source: `FadecCalibration` EGT protection
- Planned test: `TC-EGT-001`

### FADEC-EGT-002 — Transient EGT limit

- Requirement: The closed-loop engine system shall not exceed the engine
  transient EGT limit during defined normal and transient tests.
- Acceptance: Maximum true EGT is less than or equal to the selected
  `EngineDefinition` transient EGT limit.
- Criticality: `CRITICAL`
- Source: `EngineDefinition` operating envelope
- Planned test: `TC-EGT-002`

### FADEC-ACC-001 — Rotor-acceleration limiting

- Requirement: The control software shall constrain estimated rotor
  acceleration to the configured hard acceleration limit during a defined
  large throttle step.
- Acceptance: Estimated acceleration does not exceed the selected calibration's
  hard acceleration limit plus its declared evaluation tolerance.
- Criticality: `MAJOR`
- Source: `FadecCalibration` acceleration protection
- Planned test: `TC-ACC-001`

### FADEC-DEC-001 — Fuel-deceleration limiting

- Requirement: The control software shall constrain rapid commanded fuel
  reduction using the configured deceleration limiter without preventing
  shutdown.
- Acceptance: The deceleration limiter activates after the defined reduction
  and the subsequent shutdown still reaches `OFF` within 8.0 s.
- Criticality: `MAJOR`
- Source: `FadecCalibration` deceleration protection
- Planned test: `TC-DEC-001`

### FADEC-OVS-001 — Soft-overspeed intervention

- Requirement: The control software shall constrain fuel at the configured soft
  overspeed threshold without requesting hard cutoff below the hard overspeed
  threshold.
- Acceptance: Soft-overspeed and fuel-constraint evidence are recorded, with no
  hard-cutoff or automatic-fault event in the soft-overspeed test.
- Criticality: `CRITICAL`
- Source: `FadecCalibration` overspeed protection
- Planned test: `TC-OVS-001`

### FADEC-OVS-002 — Hard-overspeed cutoff

- Requirement: The control software shall command zero fuel and request
  `FAULT` when validated speed reaches the configured hard-overspeed threshold.
- Acceptance: Zero fuel is observed within 0.01 s of hard-overspeed activation
  and the system subsequently reaches `FAULT`.
- Criticality: `CRITICAL`
- Source: `FadecCalibration` overspeed protection
- Planned test: `TC-OVS-002`

### FADEC-PROT-001 — Protection arbitration

- Requirement: The control software shall apply the most restrictive valid
  fuel limit and give hard cutoff priority over all nonzero limits.
- Acceptance: Allowed fuel equals the minimum valid limit unless a hard cutoff
  is active, in which case it equals 0.0.
- Criticality: `CRITICAL`
- Source: Central fuel-protection architecture
- Planned test: `TC-PROT-001`

## Sensor-feedback requirements

### FADEC-SENS-001 — Validated feedback only

- Requirement: Control and protection functions shall use validated sensor
  values and shall not fall back to true plant values after a measurement
  becomes unavailable.
- Acceptance: Dropout scenarios record no truth-fallback use for rotor speed or
  EGT.
- Criticality: `CRITICAL`
- Source: Sensor-validation architecture
- Planned test: `TC-SENS-001`

### FADEC-SENS-002 — Rotor-speed dropout response

- Requirement: The control software shall classify sustained rotor-speed
  dropout as `INVALID`, reach `FAULT` within 0.5 seconds, and command zero fuel.
- Acceptance: Rotor-speed health becomes `INVALID`, `FAULT` occurs within 0.5 s,
  and zero fuel is commanded within the evaluated response window.
- Criticality: `CRITICAL`
- Source: Sensor validation and automatic fault response
- Planned test: `TC-SENS-002`

### FADEC-SENS-003 — EGT dropout response

- Requirement: The control software shall classify sustained EGT dropout as
  `INVALID`, reach `FAULT` within 0.5 seconds, and command zero fuel.
- Acceptance: EGT health becomes `INVALID`, `FAULT` occurs within 0.5 s, and
  zero fuel is commanded within the evaluated response window.
- Criticality: `CRITICAL`
- Source: Sensor validation and automatic fault response
- Planned test: `TC-SENS-003`

### FADEC-SENS-004 — Sensor-fault coverage and recovery

- Requirement: The control software shall provide deterministic bounded
  behavior for bias, drift, stuck, dropout, forced-value, and excessive-noise
  faults and their recovery on both sensor channels.
- Acceptance: Every supported fault type is exercised on RPM and EGT; commands
  remain bounded and cleared signals recover according to debounce
  configuration.
- Criticality: `MAJOR`
- Source: Supported sensor fault-injection model
- Planned test: `TC-SENS-004`

## Scheduler requirements

### FADEC-SCH-001 — No missed logical releases

- Requirement: The control software scheduler shall execute with no missed
  logical task releases for approved scheduler presets.
- Acceptance: Scheduler diagnostics report zero missed releases for every
  approved preset in the verification campaign.
- Criticality: `CRITICAL`
- Source: Deterministic multi-rate scheduler architecture
- Planned test: `TC-SCH-001`

### FADEC-SCH-002 — Deterministic task order

- Requirement: The control software scheduler shall execute same-tick tasks in
  configured deterministic priority order and at exact integer release counts.
- Acceptance: Task-order checks pass and execution counts match configured
  periods and phases for every approved preset.
- Criticality: `CRITICAL`
- Source: Deterministic multi-rate scheduler architecture
- Planned test: `TC-SCH-002`

## Operating-envelope requirements

### FADEC-ENV-001 — Operating-envelope robustness

- Requirement: The closed-loop system shall satisfy all applicable critical
  requirements across the approved ambient temperature and pressure domain of
  the selected engine model.
- Acceptance: All critical requirements pass at each defined ambient corner;
  unsupported regions are `NOT_APPLICABLE` rather than treated as passing.
- Criticality: `CRITICAL`
- Source: `EngineDefinition` applicability and ambient interface
- Planned test: `TC-ENV-001`

## Approval and change control

Promotion to `APPROVED` requires review of every requirement statement,
criticality, numerical limit, source, and applicability. An approved baseline
is changed only by incrementing its version and documenting the rationale.
Changing software to make a failing test pass does not authorize changing the
requirement or acceptance criterion.
