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

## Sensor Model

Rotor speed and EGT have independent typed configuration. Each channel applies
the following explicit sequence:

1. Read the true physical value.
2. Add constant bias.
3. Add optional Gaussian noise.
4. Quantize around zero when the quantization step is nonzero.
5. Clamp to the measurable range.
6. Publish at the channel sample period and hold between samples.

The first update publishes both channels immediately. Later updates use
independent accumulated sample timing, so one channel may update while the
other holds its previous value.

Each sensor-model instance owns its random generator; global random state is
not used. A fixed seed gives repeatable measurements and simulation runs.
Setting the seed to `None` enables non-reproducible demonstration noise.
Reset clears retained measurements and timers and restores the initial random
state without resetting the engine plant.

The default values are initial modelling assumptions, not validated hardware
specifications. Rotor speed uses 50 rpm noise, 10 rpm quantization, a
0 to 150,000 rpm range, and a 0.01 s sample period. EGT uses 1 °C noise,
0.5 °C quantization, a -50 to 1,000 °C range, and a 0.02 s sample period.

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

## Fixed-Step Execution

For each coordinated simulation step:

1. Sample or retain nominal sensor signals.
2. Apply active simulation-only faults.
3. Validate raw measurements and update channel health.
4. Determine warnings, automatic FAULT request, and safe fuel cutoff.
5. Evaluate operating-state transitions using validated conditions.
6. Calculate requested fuel from startup strategy or closed-loop control.
7. Evaluate centralized fuel protection using validated data and operating
   context.
8. Advance the physical engine model with the manager-approved actuator
   command.
9. Record truth, raw and validated values, diagnostics, events, and outputs.

## Runtime Observability and Run Recording

`SimulationSnapshot` is the one canonical observable representation of a
simulation sampling instant. The coordinator constructs it after a complete
fixed step and synchronously publishes the same immutable value to registered
`SnapshotSink` adapters. Terminal status, run recording, automated scenarios,
and dashboard views therefore do not reconstruct signals from component
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
Terminal     Recorder    Event monitor   Future dashboard
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

### Telemetry and event schemas

Snapshot serialization uses an explicit ordered `TELEMETRY_FIELDS` schema.
Enums become their stable string values, immutable parameter and diagnostic
tuples become compact JSON, and optional values become empty CSV cells while
remaining `None` in the Python API. The current telemetry schema version is
`1.0`. Renaming, removing, or changing the meaning of a field requires a
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

`RunRecorder` may receive every coordinated snapshot but samples according to
simulation time, not wall-clock pacing. The first snapshot is written
immediately. Later rows are written only after configurable sampling deadlines
(0.05 s by default); deadline advancement accounts for skipped periods and a
small numeric tolerance prevents accumulated floating-point drift. Identical
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

Run recording currently uses synchronous local CSV I/O, one process, and one
schema family. It does not provide database indexing, networking, background
workers, automatic requirements evaluation, cross-version migration, or live
comparison of loaded historical runs. Wall-clock and Git metadata are
identification aids rather than deterministic comparison fields.
