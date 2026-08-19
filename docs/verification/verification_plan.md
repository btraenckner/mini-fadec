# Mini-FADEC Requirements Verification Plan

## Purpose

This plan defines how the draft control requirements baseline
`MINI-FADEC-CONTROL-REQ` version `0.1.0` will be reviewed, implemented as test
cases, executed, and reported. It controls evidence generation; it does not
claim that the simulation or its reports are certified verification tools.

The controlled draft test-case catalog is `MINI-FADEC-TEST-CASES` version
`0.1.0`. Its machine-readable source is
`simulation/verification/test_cases.py`; the human-readable index is
`docs/verification/test_case_catalog.md`.

## Verification levels

Evidence is classified so that a simulation result cannot be mistaken for a
physical-engine result:

1. **Unit verification** checks isolated algorithms and invariants.
2. **Software-in-the-loop (SIL)** checks the integrated control software
   against a recorded engine model and calibration.
3. **Hardware-in-the-loop (HIL)** will check compiled control software,
   interfaces, timing, and failure behavior with simulated plant signals.
4. **Engine-bench validation** will check the complete control system against
   independently instrumented physical-engine measurements.

The current campaign produces unit and SIL evidence only. Passing a JetCat
simulation proves behavior against the public-data grey-box profile, not the
physical P1000-PRO. The provisional B350STG profile cannot support a physical
B350STG compliance claim until it is replaced or correlated with test data.

## Controlled configuration

Every test result must identify:

- requirements baseline ID, version, and approval status;
- planned test-case ID and executable scenario ID;
- engine-definition ID and version;
- FADEC-calibration ID and version;
- plant backend and model version;
- scheduler preset and base tick;
- ambient conditions and sensor random seed;
- Git commit and artifact schema versions.

A result is not reusable after any of those controlled inputs changes unless
the affected tests are rerun or a documented impact analysis justifies reuse.

## Test-case specification requirements

Each formal test case in the controlled catalog defines:

- stable `TC-<DOMAIN>-<NNN>` ID;
- linked `FADEC-*` requirement IDs;
- purpose and verification level;
- applicable engine profiles and plant backends;
- initial state and preconditions;
- ambient conditions and deterministic random seed;
- timed actions, inputs, and injected faults;
- maximum duration and termination condition;
- evaluated signals, event evidence, limits, tolerances, and dwell times;
- explicit `PASS`, `FAIL`, `ERROR`, `NOT_EVALUATED`, and `NOT_APPLICABLE`
  behavior.

Implementation status is independent of a verification result:

- `EXECUTABLE_SCENARIO` means a deterministic scenario and post-run evidence
  are linked.
- `PARTIAL_AUTOMATION` means useful automated checks exist, but a complete
  formal scenario or evidence package is still missing.
- `PLANNED` means no executable evidence is claimed yet.

## Planned campaign groups

| Group | Primary test cases | Purpose |
|---|---|---|
| Operating states | `TC-OPS-001` through `TC-OPS-003` | Start, shutdown, and reset interlocks |
| Start protection | `TC-START-001`, `TC-START-002` | Hot and hung starts |
| Speed control | `TC-SPD-001`, `TC-SPD-002` | Schedule, settling, and overshoot |
| Actuators | `TC-ACT-001` through `TC-ACT-003` | Bounds and safe-state commands |
| Thermal protection | `TC-EGT-001`, `TC-EGT-002` | EGT limiting and peak temperature |
| Transient protection | `TC-ACC-001`, `TC-DEC-001` | Acceleration and deceleration limits |
| Overspeed | `TC-OVS-001`, `TC-OVS-002` | Soft recovery and hard cutoff |
| Arbitration | `TC-PROT-001` | Concurrent limiter precedence |
| Sensor faults | `TC-SENS-001` through `TC-SENS-004` | Validated feedback, dropout, fault matrix, recovery |
| Scheduling | `TC-SCH-001`, `TC-SCH-002` | Releases, counts, and task ordering |
| Environment | `TC-ENV-001` | Approved ambient-domain corners |

## Result rules

- Any `FAIL` or `ERROR` on a `CRITICAL` requirement fails the campaign.
- `NOT_EVALUATED` on a `CRITICAL` requirement prevents a compliance claim.
- `NOT_APPLICABLE` is valid only when the requirement's applicability data and
  report rationale explicitly exclude that configuration.
- A `MAJOR` failure fails the relevant operating or performance objective and
  requires correction or an approved deviation.
- A planned requirement without an executable trace remains an open coverage
  gap and cannot be counted as passing.
- Repeated deterministic runs must produce equivalent normalized results.

## Evidence package

The final campaign package should contain:

- baseline snapshot and human-readable requirements document;
- approved test-case specifications;
- requirement-to-test traceability matrix;
- scenario definitions;
- complete telemetry, event logs, and metadata;
- per-scenario requirement results and plots;
- aggregate requirement status, measured limits, margins, and open gaps;
- signed review record for assumptions, failures, deviations, and approval.

## Baseline review gate

Before the draft test cases are approved or used for a compliance campaign,
the baseline and catalog must be reviewed for:

1. correct system boundary and intended compliance claim;
2. completeness of normal, boundary, protection, and fault behavior;
3. credible sources for engine-dependent limits;
4. correct `CRITICAL` versus `MAJOR` classification;
5. measurable acceptance criteria without ambiguous wording;
6. correct applicability to reference, JetCat, and provisional B350 profiles;
7. explicit recognition of currently missing software functions.
