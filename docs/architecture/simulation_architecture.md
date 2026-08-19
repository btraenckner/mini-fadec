# Simulation Architecture

## Purpose

The simulation provides modular plant, control, protection, and operator layers
for Mini-FADEC development. The engine remains a deliberately simplified
single-spool grey-box model rather than a validated thermodynamic model.

## Signal Architecture

Closed-loop operation separates physical truth from the signals observed by
the FADEC:

```text
Engine truth
    -> sensor effects
    -> fault injection
    -> raw measurement
    -> validation
    -> validated data
    -> state machine / controller / protection
    -> actuator command
    -> engine truth
```

`EngineState` is owned and updated by the engine plant. The sensor model reads
that narrowly scoped state without modifying it. Simulation-only fault
injection operates after normal sensor effects and publishes `RawSensorData`,
whose optional values represent dropout explicitly. Validation publishes
`ValidatedSensorData` and health diagnostics. State transitions, speed
feedback, and EGT protection use only validated values; only plant integration
and simulation-only diagnostic comparisons use truth directly.

## Main Modules

- `simulation/configuration/` separates versioned physical engine definitions
  from versioned FADEC calibration and validates their compatibility before a
  runtime is created.
- `simulation/models/` contains rotor-speed and EGT plant dynamics plus
  algebraic thrust and fuel-flow estimates.
- `simulation/sensors/` converts engine truth into measured rotor speed and
  EGT and contains simulation-only fault injection.
- `simulation/validation/` checks availability, physical range, rate of change,
  and context-dependent stuck behavior.
- `simulation/operation/` owns the explicit engine operating-state machine.
- `simulation/controllers/` schedules demanded speed and calculates requested
  fuel.
- `simulation/protection/` estimates rotor acceleration, evaluates EGT,
  acceleration, deceleration, and overspeed protection, and centrally
  arbitrates the final fuel command.
- `simulation/scheduling/` owns immutable periodic-task definitions,
  integer-tick release logic, timing presets, and runtime diagnostics.
- `simulation/application/` composes the components and provides terminal and
  graphical interactive applications.
- `simulation/telemetry/` owns the canonical runtime snapshot, typed events,
  stable serializers, run metadata, and deterministic CSV recorder.
- `simulation/tools/` provides offline run inspection and plotting without
  participating in the live simulation loop.
- `simulation/examples/` contains open-loop and closed-loop demonstrations.

The component boundaries use the protocols and data types in
`simulation/core/`. Open-loop plant-only examples may inspect truth directly;
closed-loop examples route feedback through fault injection and validation.

## Engine Definition and FADEC Calibration

Application construction has two independent typed inputs:

- `EngineDefinition` describes what the software is connected to: engine
  identity and version, published hardware facts and their provenance,
  selected plant backend and parameters, installed sensor behavior, actuator
  command capability, and the approved physical operating envelope.
- `FadecCalibration` describes how the control software is tuned for that
  engine: throttle-to-speed schedule, controller gains, state-machine
  thresholds, sensor validation, and every centralized fuel-protection value.

`create_application()` is the shared composition path for the dashboard and
scenario runner. It validates the engine/calibration pair before constructing
the plant or any stateful controller. Direct low-level component injection into
`EngineSimulationCoordinator` remains available for focused tests.

Compatibility validation rejects a calibration targeted at another engine,
speed schedules or protection thresholds outside the operating envelope,
sensor and validator ranges that cannot observe the protected limits,
inconsistent start thresholds, unsupported starter or ignition commands, and
fuel ranges outside the actuator interface. Dashboard plant and scheduler
changes rebuild the runtime while retaining the same engine identity and FADEC
calibration.

An `EngineConfigurationProfile` pairs one compatible definition and
calibration with a stable ID and evidence level. The dashboard can select a
profile only while `OFF`; it reconstructs the whole runtime but preserves the
chosen First-order or PathSim backend. The scenario runner receives the same
profile ID, so runner recordings retain profile traceability rather than
silently returning to the reference engine.

Every recording captures the complete serialized engine definition and FADEC
calibration in `metadata.json`, together with their identifiers and versions.
This makes a result traceable to both the physical assumptions and software
tuning that produced it. See
[`docs/configuration/engine_definition_and_fadec_calibration.md`](../configuration/engine_definition_and_fadec_calibration.md)
for the intended customization workflow.

## Sensor Model

Rotor speed and EGT have independent typed signal-effect configuration. Each
central sensor-task release applies the following explicit sequence:

1. Read the true physical value.
2. Add constant bias.
3. Add optional Gaussian noise.
4. Quantize around zero when the quantization step is nonzero.
5. Clamp to the measurable range.
6. Publish both channels together.

The sensor model contains no private elapsed-time accumulator. The central
scheduler decides when `measure()` is called, and the coordinator holds its
result until the next sensor-task release. Legacy channel
`sample_period_s` values remain available as modelling metadata but do not
create a second scheduling authority.

Each sensor-model instance owns its random generator; global random state is
not used. A fixed seed gives repeatable measurements and simulation runs.
Setting the seed to `None` enables non-reproducible demonstration noise.
Reset clears retained measurements and restores the initial random state
without resetting the engine plant.

The default values are initial modelling assumptions, not validated hardware
specifications. Rotor speed uses 50 rpm noise, 10 rpm quantization, and a
0 to 150,000 rpm range. EGT uses 1 °C noise, 0.5 °C quantization, and a
-50 to 1,000 °C range. The active scheduler preset defines their common
runtime release period.

## Fault Injection

Each channel supports one active typed fault: constant bias, stuck-current or
stuck-explicit value, dropout, forced value, additional Gaussian noise, or
linear drift. Activating a new fault explicitly replaces the previous fault on
that channel. Rotor-speed and EGT faults remain independent. Fault noise uses
an instance-owned seeded random generator, and drift uses accumulated
simulation time. Clearing a fault resets its channel runtime state but does not
reset validator recovery state.

## Signal Validation

Channel health has three states:

- `VALID`: all checks pass and the current raw value is accepted.
- `SUSPECT`: a debounced plausibility violation or recovery is in progress;
  the channel remains temporarily usable.
- `INVALID`: the signal is unavailable or a violation persisted beyond its
  configured threshold.

Dropout is immediately `INVALID` by default. Range, rate, and stuck violations
first become `SUSPECT` and become `INVALID` after 0.10 s. Valid input must then
persist for 0.20 s before recovery to `VALID`. Stuck checks are enabled only by
narrow operating context such as starter, ignition, changing commands, or
shutdown, avoiding false detection for a legitimately stopped engine.

Initial validation bounds are 0 to 145,000 rpm and -50 to 950 °C. Rate limits
are 100,000 rpm/s and 1,500 °C/s; these values accommodate the current plant's
normal startup and transient behavior and are not validated hardware limits.

During a violation, the validator uses the last known valid value rather than
truth. For an `INVALID` channel this held value expires after 0.20 s, after
which the validated value is explicitly unavailable. Recovery may use current
plausible raw data while health remains `SUSPECT`. Engine truth is never used
as a fallback.

## Critical Fault Response

A policy outside both validator and state machine maps health to FADEC action:

- Invalid rotor speed in CRANKING, IGNITION, IDLE, or RUNNING requests the
  existing FAULT transition and immediate fuel cutoff.
- Suspect EGT continues temporarily with a warning and validated or held EGT
  protection.
- Invalid EGT in IGNITION, IDLE, or RUNNING requests FAULT and fuel cutoff.
- Invalid EGT in OFF or SHUTDOWN is reported without creating an unsafe
  actuator command or preventing shutdown.

Manual FAULT remains available. A reset request is passed to the state machine
only after both sensor channels recover to `VALID`; the existing stopped-speed
condition still applies.

## Central Fuel Protection

The `ProtectionManager` is the sole normal fuel authority after the speed
controller. The controller regulates speed, the state machine supervises the
operating mode, and the validator determines signal health; none of those
components selects between protection fuel limits.

```text
Validated sensors
    -> speed controller
    -> requested fuel
    -> Protection Manager
       -> EGT upper limit
       -> acceleration upper limit
       -> overspeed upper limit
       -> deceleration lower limit
       -> state and fault constraints
    -> final fuel
    -> actuator command
    -> engine model
```

The manager clamps fuel to 0.0 through 1.0 and evaluates candidate upper
limits from requested fuel, EGT protection, acceleration protection,
overspeed protection, and the current state's maximum. Its lower bounds are
the global minimum and the normal-operation deceleration minimum. In the
absence of a conflict, arbitration is equivalent to:

```text
upper_allowed = min(requested, EGT, acceleration, overspeed, state maximum)
lower_allowed = max(global minimum, deceleration minimum)
final fuel = max(lower_allowed, upper_allowed)
```

If a lower bound exceeds a safety upper limit, the safety upper limit wins and
an arbitration-conflict diagnostic is reported. OFF, SHUTDOWN, FAULT, a
critical sensor condition, or hard overspeed bypasses every lower bound and
commands exactly zero fuel. Thus normal deceleration protection can never
defeat a shutdown or safety cutoff.

`ProtectionResult` retains the requested and final commands, every candidate
limit, estimated acceleration and deceleration, speed ratio, overspeed flags,
fault and cutoff requests, and typed diagnostic reasons. Equal limiting
values are all reported within a numeric tolerance. The deterministic primary
diagnostic priority is HARD_CUTOFF, SENSOR_FAULT, OVERSPEED, EGT,
ACCELERATION, DECELERATION, STATE, then NONE. This priority labels the result;
it does not change numeric arbitration.

Rotor acceleration is calculated only from consecutive validated speed
samples. The first valid sample initializes the estimator at zero, state
changes and resets clear its history, and unavailable validated speed produces
no estimate. A configurable first-order filter with a 0.05 s time constant
reduces measurement-noise sensitivity. This adds a small, deterministic delay.

The initial acceleration intervention region is 12,000 to 20,000 rpm/s.
Above the soft threshold the acceleration upper limit decreases linearly
toward zero. Fuel restriction is immediate, while release is limited to 1.0
command unit/s to avoid limit cycling. Acceleration protection is enabled in
IDLE and RUNNING, preserving CRANKING and IGNITION behavior.

The deceleration limiter is a normal-operation lower bound based on the prior
manager-approved command. It permits fuel to decrease by at most 0.5 command
unit/s in IDLE and RUNNING. It is reset or bypassed during cutoff conditions.

Overspeed thresholds are derived from the controller scheduler's configured
maximum normal speed. Soft intervention begins at 1.03 times that speed and
linearly reduces the upper fuel limit. At exactly 1.08 times maximum normal
speed, or above, the manager commands immediate zero fuel and requests the
state machine's FAULT path. Protection receives validated speed and EGT only;
the existing sensor-fault response policy supplies the manager with an
explicit critical-sensor condition rather than duplicating validation rules.

All filter constants, limiter thresholds, ratios, and slew rates in this
section are unvalidated grey-box simulation assumptions, not certified engine
limits.

## Deterministic Multi-Rate Scheduling

`DeterministicScheduler` is the only logical execution authority. Time is an
integer base-tick index; authoritative simulation time is derived as
`tick * base_tick_s`. Periods and phase offsets are validated as exact integer
multiples when configuration is constructed. No floating-point deadline
accumulation, component-owned timer, dashboard timer, or scenario-specific
stepping loop releases FADEC work.

The execution convention is `SAMPLE_CONTROL_THEN_INTEGRATE`. Tasks released on
the same tick execute by explicit priority, then stable name:

1. command capture,
2. operating-state supervision,
3. sensor sampling and fault injection,
4. signal validation and sensor-fault response,
5. speed controller,
6. centralized protection,
7. final actuator application,
8. one plant integration,
9. coherent snapshot publication,
10. event monitoring,
11. telemetry publication,
12. dashboard publication.

Every task receives its own configured effective period. Controller integration
uses the controller period, protection filters use the protection period,
validation persistence uses the validation period, and the plant is integrated
exactly once per plant release. Outputs are retained between releases: sensor
data, validated data, requested fuel, protected fuel, and applied actuator
commands all have explicit sample-and-hold behavior. Hard cutoff conditions
override a held normal fuel demand at the next actuator release.

The nominal development preset is:

| Task | Period | Phase | Priority |
|---|---:|---:|---:|
| Command | 1 ms | 0 ms | 10 |
| State machine | 20 ms | 0 ms | 20 |
| Sensor | 5 ms | 0 ms | 30 |
| Validation | 5 ms | 0 ms | 40 |
| Controller | 10 ms | 0 ms | 50 |
| Protection | 5 ms | 0 ms | 60 |
| Actuator | 5 ms | 0 ms | 70 |
| Plant | 1 ms | 0 ms | 80 |
| Snapshot | 5 ms | 0 ms | 90 |
| Event monitor | 5 ms | 0 ms | 100 |
| Telemetry | 50 ms | 0 ms | 110 |
| Dashboard | 50 ms | 0 ms | 120 |

Tick zero is a valid release. Non-zero phase offsets are supported and tested;
priority remains authoritative when phased tasks coincide. The `single-rate`,
`nominal-multirate`, `slow-controller`, `slow-sensors`, and `stress-timing`
presets are independently constructed immutable values. Single-rate and
nominal multi-rate are mandatory regression presets. Coarser presets are
explicit experimental sensitivity configurations and are never defaults.

Diagnostics expose the active preset, base tick, current tick and time, last
same-tick order, missed-release total, and per-task period, phase, priority,
release and execution counts, last execution, next release, skipped
executions, and missed releases. Logical missed releases occur only if a
caller deliberately advances tick state without processing intervening
releases; normal unpaced execution processes every tick.

`SimulationService.step_one_tick()` is the shared primitive for manual,
scenario, and dashboard adapters. The older `step(time_step_s)` API remains a
compatibility grouping operation and accepts only exact base-tick multiples.
Changing presets constructs a fresh coordinator and clears retained timing
and sample-and-hold state. It is allowed only while the engine is OFF and
recording is inactive; rejected and accepted changes produce structured
scheduler events.

## Runtime Observability and Run Recording

`SimulationSnapshot` is the one canonical observable representation of a
snapshot-task release. The coordinator constructs it after plant integration
and publishes the same immutable value to registered `SnapshotSink` adapters.
Telemetry and dashboard sinks have separate scheduler-controlled release
tasks and consume the latest held snapshot; their rates cannot execute the
plant or FADEC. Terminal status, run recording, automated scenarios, and
dashboard views therefore do not reconstruct signals from component
internals. Truth, raw measurements, validated signals, requested fuel,
protection candidates, and final applied fuel remain explicitly distinguished.
Unavailable sensor and derived values remain `None`; serializers do not turn
them into zero.

```text
Operator / future dashboard
        | commands
        v
SimulationService
        |
        v
Simulation coordinator
        |
        v
SimulationSnapshot
   +------------+------------+---------------+------------------+
   |            |            |               |
   v            v            v               v
Terminal     Recorder    Event monitor   Live dashboard
```

`SimulationService` is the application control boundary. It owns persistent
throttle demand and one-shot start, shutdown, manual-fault, and reset requests.
It also exposes typed fault injection and clearing, the latest snapshot, a
bounded immutable recent-event view, snapshot-sink registration, recording
lifecycle operations, markers, and recent-run discovery. Terminal and live
dashboard controls call this service rather than mutating the model,
controller, validator, state machine, or Protection Manager. A later UI may
use the same in-process interface or add a narrow transport adapter around it;
the UI must not calculate control values, decide transitions, parse terminal
text, or read component internals.

The current live dashboard uses this service directly. Its run-name field and
record/stop buttons control the same recorder lifecycle as the terminal, show
live sample and event counts, and finalize an active recording when the
dashboard window closes. A Manual/Runner switch explicitly transfers command
ownership. Runner mode exposes the deterministic regression library through a
dropdown and advances the selected `ScenarioRunner` incrementally from the
dashboard timer. Scenario actions exclusively own engine, sensor, and
recording commands during that mode, so conflicting manual widgets are
disabled until the run finishes or is cancelled and the operator switches
back to manual mode.

The dashboard timing overlay displays the active preset, base tick, current
logical time and tick, missed releases, and the complete per-task timing
table. It is read-only: preset definitions are maintained in
`simulation/scheduling/presets.py`, while scenarios select presets through
their configuration overrides. The overlay refreshes at the UI rate and is
strictly observational; it never releases control or plant tasks.

### Telemetry and event schemas

Snapshot serialization uses an explicit ordered `TELEMETRY_FIELDS` schema.
Enums become their stable string values, immutable parameter and diagnostic
tuples become compact JSON, and optional values become empty CSV cells while
remaining `None` in the Python API. The current telemetry schema version is
`1.1`. Renaming, removing, or changing the meaning of a field requires a
schema-version change; compatible field additions require deliberate review
of the explicit header.

`SimulationEvent` records authoritative simulation time, a deterministic
sequence, category, type, severity, source, message, optional diagnostic code,
and JSON-safe old and new values. Explicit operator actions are emitted by the
service. A central `SimulationEventMonitor` compares consecutive snapshots to
detect state and health transitions, light-off, protection faults, safety
cutoff, reset results, and debounced limiter changes. Persistent conditions do
not create an event every cycle. Recent events are held in a configurable
bounded deque and exposed as an immutable tuple. The event schema is versioned
independently at `1.0`.

### Deterministic sampling and recorder lifecycle

`RunRecorder` writes the initial snapshot immediately and thereafter receives
held snapshots only from the central telemetry task (50 ms in the nominal
preset). Its compatibility `publish()` path retains deterministic
simulation-time sampling for adapters outside the centrally scheduled
composition. Identical
initial state, configuration, random seed, time step, and operator sequence
therefore produce equivalent telemetry and event CSV content.

Starting a recording creates a sanitized, unique directory under the
configurable `artifacts/runs/` base. Existing directories are never
overwritten:

```text
artifacts/runs/2026-07-20_143505_normal_run/
  telemetry.csv
  events.csv
  metadata.json
```

Metadata is written at start as incomplete and finalized at stop with sample
and event counts. It includes all schema versions, simulation and telemetry
timing, sensor seed, explicit component identifiers, selected configuration,
Git commit/branch/dirty state when available, Python and platform identity,
wall-clock recording boundaries, and completion status. Git discovery occurs
once and fails gracefully outside a repository. Wall-clock values only name
and identify artifacts; they never drive simulation, sampling, events, or
control.

The recorder keeps CSV files open for the session, flushes in bounded batches,
and closes them in normal stop, context-manager cleanup, terminal quit,
`Ctrl+C`, and application `finally` paths. Starting twice is rejected;
stopping while inactive is safe; restarting always creates a new directory.
Generated run directories are ignored by Git.

The interactive terminal adds `record start [run_name]`, `record stop`,
`record status`, `mark <text>`, and `runs`. Offline artifacts can be inspected
with:

```text
python -m simulation.tools.inspect_run artifacts/runs/<run-directory>
python -m simulation.tools.plot_run artifacts/runs/<run-directory>
```

The inspector uses only the standard library. Plotting uses the project's
existing matplotlib dependency and reads persisted CSV after the run; it is
never called from live integration.

## Deterministic Scenario Verification

Sprint 12 adds a non-interactive execution path for repeatable project-level
simulation verification. It is deliberately separate from engine physics,
control, protection, signal validation, telemetry capture, and terminal or
dashboard presentation:

```text
Terminal / future dashboard / CLI
                |
                v
        Scenario execution API
                |
                v
          ScenarioRunner
          +-- actions
          +-- triggers
          +-- conditions
          +-- progress
                |
                v
        SimulationService
                |
                v
      SimulationSnapshot + Events
                |
                v
     Requirement evaluators
                |
                v
         ScenarioResult
                |
                v
 JSON report + Markdown report
```

`simulation.scenarios` owns immutable scenario definitions, typed actions,
simulation-time triggers, read-only conditions, deterministic execution, the
explicit regression library, serialization, and the CLI. Actions call only
the existing `SimulationService` methods. They do not access or mutate the
engine model, controller, state machine, validator, fault injector, or
Protection Manager. Conditions inspect only the latest or captured immutable
snapshots, structured events, and immutable action results.

`simulation.verification` owns requirement identity and criticality, focused
evaluators, explicit evidence, result aggregation, standards-compliant JSON,
and concise Markdown reports. Evaluators consume the same captured snapshots,
events, and action outcomes used by other application clients. Operational
requirements use validated values and final actuator commands. Engine truth
remains available only for requirements explicitly identified as
simulation-only.

### Scenario definitions, actions, and sequencing

A `Scenario` has a stable ID, name, description, maximum duration, optional
fixed-step override, recording configuration, immutable action and requirement
tuples, tags, expected terminal condition, narrow configuration overrides, and
an optional deterministic seed. Construction rejects empty IDs, nonpositive
timing, duplicate action or requirement IDs, invalid triggers, unknown action
dependencies, and unsupported overrides. Supported overrides are currently
the artifact base directory, telemetry sampling period, sensor random seed,
and scheduler preset; shared global configuration is never mutated.

Actions include engine start, normalized throttle changes, shutdown, reset,
manual fault request, typed sensor-fault injection and clearing, markers, and
recording start and stop. Each action has an ID, description, trigger,
required-success policy, and optional timeout. Runtime `ActionResult` values
distinguish `PENDING`, `EXECUTED`, `SKIPPED`, `FAILED`, and `TIMED_OUT`.
The runner evaluates definitions in stable tuple order and executes each action
at most once.

`AtTimeTrigger` becomes due when simulation time reaches or crosses its
inclusive boundary. A numeric tolerance prevents accumulated floating-point
time from delaying an exact boundary. `WhenConditionTrigger` wraps one typed
condition and an optional simulation-time timeout. Reusable conditions cover
current or previously reached engine state, validated rotor-speed and EGT
thresholds, throttle demand, limiter state, sensor health, critical protection,
typed events, action completion, and elapsed simulation time after an action.
`AllConditions` supports small explicit dependencies without creating a
general workflow or expression language.

An example definition follows the same shape as the library scenarios:

```python
Scenario(
    scenario_id="SCN-NORMAL-001",
    name="normal_start_run_shutdown",
    description="Normal startup, operation, and shutdown.",
    max_duration_s=25.0,
    actions=(
        StartEngineAction(
            action_id="start",
            description="Request startup",
            trigger=AtTimeTrigger(0.1),
        ),
        SetThrottleAction(
            action_id="run",
            description="Set running demand after IDLE",
            trigger=WhenConditionTrigger(
                EngineStateEqualsCondition(EngineOperatingState.IDLE),
                timeout_s=12.0,
            ),
            throttle_demand=0.55,
        ),
    ),
    requirements=(...),
    tags=("normal", "lifecycle"),
    expected_terminal_condition=EngineStateEqualsCondition(
        EngineOperatingState.OFF
    ),
)
```

### Runner, progress, and determinism

`ScenarioRunner` creates a fresh `SimulationService` composition for every
scenario, optionally starts the Sprint 11 recorder, executes due actions,
steps the service one scheduler base tick at a time, captures the canonical
snapshots and typed events, checks
termination, evaluates requirements, finalizes recording, and writes reports.
Its default loop has no wall-clock sleeping. Scenario triggers, timeouts,
settling windows, response times, maximum duration, and event times use only
simulation time. Wall-clock time is limited to run naming, generated-at
metadata, execution-performance measurement, and the real-time-factor report.
An explicitly enabled paced mode may sleep once per scheduler base tick.

The synchronous `run_scenario(scenario)` function is the simplest entry point.
The live dashboard uses `prepare_scenario`, `step_scenario`,
`get_scenario_progress`, and `cancel_scenario` to expose the same execution
through its graphical controls without terminal output or UI dependencies in
the runner. `ScenarioProgress` includes the scenario ID, simulation time and
duration, execution state, engine state, action counts, active recording
directory, latest snapshot, recent events, action results, and partial
requirement status. All collections returned to clients are immutable tuples.

With the same scenario, seed, time step, initial composition, and
configuration, action order and time, snapshot and event sequences,
requirement outcomes, scheduler counts and ordering, and overall result are
deterministic. Normalization
removes only documented nondeterministic fields such as wall-clock execution
duration, real-time factor, and filesystem paths.

### Requirement and evidence model

Requirements have stable IDs, descriptions, categories, criticality, an
explicit evaluator, and optional applicability text. Categories cover state
sequence and timing, signal limits, steady state, transients, protection,
sensor-fault response, actuator safety, logical invariants, and scheduler
timing. Criticality is
`INFO`, `MINOR`, `MAJOR`, or `CRITICAL`; these are project classifications and
do not claim aerospace certification compliance.

The initial evaluator set covers state reached, state reached within a time,
state transition sequence, signal maximum and minimum, signal band, settling
time with continuous dwell, overshoot, acceleration limit, actuator
invariants, event observed or absent, sensor fault response time, fuel-cutoff
response, limiter intervention, sensor-health transition, explicit
no-truth-fallback behavior, scheduler preset match, exact task count and rate
ratio, no missed release, and deterministic task order. Missing evidence
becomes `NOT_EVALUATED` or
`NOT_APPLICABLE`; evaluator exceptions become `ERROR` and can never pass.

`RequirementEvidence` uses explicit optional fields for measured and expected
values, bounds, tolerance, margin, evaluation and violation times, state,
action or event identity, maximum violation, and diagnostics. It contains no
live simulation object. Numeric boundaries are inclusive within their stated
tolerance, and unavailable values remain `None` rather than becoming zero.

Overall PASS requires completed execution, no required action failure or
timeout, no impacting requirement failure, and successful report generation.
Any `CRITICAL`, `MAJOR`, or `MINOR` failure fails the scenario. An `INFO`
failure is a warning by default and may leave the scenario PASS. Any evaluator
`ERROR`, execution error, timeout, or report error fails the scenario. An
explicit cancellation returns `CANCELLED` and still finalizes artifacts.

### Scenario library, CLI, and artifacts

The mandatory registry contains normal lifecycle, large throttle step, rapid
throttle reduction, RPM dropout, EGT dropout, soft overspeed, hard overspeed,
and four scheduler regressions: single-rate lifecycle, nominal multi-rate
lifecycle, nominal multi-rate throttle transient, and nominal multi-rate RPM
dropout. Experimental slow-controller and slow-sensor scenarios are available
individually. The slow-sensor case intentionally retains the 10 ms cutoff
requirement to expose degraded latency and is excluded from mandatory
`run-all`. Fault and overspeed scenarios create their inputs through the
existing typed sensor-fault path so validation and protection are not
bypassed.

Use the non-interactive CLI as follows:

```text
python -m simulation.scenarios.cli list
python -m simulation.scenarios.cli show normal_start_run_shutdown
python -m simulation.scenarios.cli presets
python -m simulation.scenarios.cli run normal_start_run_shutdown --scheduler nominal-multirate
python -m simulation.scenarios.cli run SCN-SCHED-001
python -m simulation.scenarios.cli run-all
```

`run` returns zero only for PASS. `run-all` returns nonzero if any registered
scenario fails. Core runner methods never print; only the CLI adapter formats
terminal summaries.

Every recorded scenario extends the unique Sprint 11 run directory:

```text
artifacts/runs/<unique-scenario-run>/
  telemetry.csv
  events.csv
  metadata.json
  scenario.json
  requirements.json
  report.md
```

If automatic full-run recording is disabled and no recording action starts a
session, finalization still creates a recorder-backed diagnostic directory
with the final snapshot so controlled failures and cancellations retain the
same report artifact structure without duplicating CSV-writing logic.

`scenario.json` uses explicit action, trigger, condition, and evaluator type
names plus parameters. `requirements.json` contains schema version, aggregate
status and counts, scheduler preset and full task configuration, action
results, requirement evidence, and artifact paths.
JSON serialization rejects nonstandard NaN and Infinity values by converting
unavailable numeric evidence to `null`. `report.md` summarizes execution,
actions, requirements, failures, evidence, source revision, and artifact
links without embedding telemetry tables. Existing report files are never
overwritten. Scenario identity, status, and counts are added to finalized run
metadata.

To extend the framework, add a small immutable action whose `execute` method
uses the narrow application-service protocol; add a condition that reads only
`ConditionContext`; add an evaluator that returns `EvaluationOutcome` with
typed evidence; or add a scenario factory to the explicit ordered library.
New definitions must also be supported by explicit serialization and focused
tests. A future dashboard can call the runner and progress interfaces directly
and render snapshots, events, action state, and final results without reading
low-level component state.

## Current Limitations

The simulation does not model redundant sensors, voting, analytical signal
reconstruction, sensor filters, model-based diagnosis, communication-bus
faults, or hardware drivers. Injected faults are simulation controls rather
than production FADEC functionality. Detailed compressor maps, combustion
chemistry, environmental corrections, actuator dynamics, and real-time
hardware communication also remain outside the current scope. Acceleration and
deceleration protection are simplified signal- and command-rate constraints;
they do not model compressor surge margin, flameout, or combustor stability.
Overspeed protection assumes one validated speed channel and does not model
redundant trip hardware.

Run recording and scenario verification currently use synchronous local file
I/O and retain one scenario's evidence in memory. They do not provide database
indexing, networking, background workers, cross-version migration, online
streaming verification, campaigns, optimization, a YAML language, or live
comparison of loaded historical runs. Partial progress reports requirement
definitions as not yet evaluated; authoritative evaluation is post-run.
Wall-clock and Git metadata are identification aids rather than deterministic
comparison fields.

The scheduler is a deterministic logical-time development model, not an
operating-system real-time scheduler. It does not model execution duration,
jitter, preemption, CPU overload, deadlines, or hardware interrupts. Current
periods, priorities, and phase choices are unvalidated development assumptions.
The dashboard is refreshed by Matplotlib wall-clock callbacks, but those
callbacks only request logical base ticks and render held results.

This framework is a simulation and development verification environment. It
is not a certified aerospace verification tool and does not implement a
DO-178C process, formal external traceability, hardware-in-the-loop transport,
or independent safety assurance.
