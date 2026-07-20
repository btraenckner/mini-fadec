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
- `simulation/protection/` limits the requested command using measured EGT.
- `simulation/application/` composes the components and provides terminal and
  graphical interactive applications.
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

## Fixed-Step Execution

For each coordinated simulation step:

1. Sample or retain nominal sensor signals.
2. Apply active simulation-only faults.
3. Validate raw measurements and update channel health.
4. Determine warnings, automatic FAULT request, and safe fuel cutoff.
5. Evaluate operating-state transitions using validated conditions.
6. Calculate requested fuel and apply EGT protection using validated data.
7. Advance the physical engine model with the allowed actuator command.
8. Record truth, raw and validated values, diagnostics, events, and outputs.

## Current Limitations

The simulation does not model redundant sensors, voting, analytical signal
reconstruction, sensor filters, model-based diagnosis, communication-bus
faults, or hardware drivers. Injected faults are simulation controls rather
than production FADEC functionality. Detailed compressor maps, combustion
chemistry, environmental corrections, actuator dynamics, and real-time
hardware communication also remain outside the current scope.
