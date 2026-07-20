# Simulation Architecture

## Purpose

The simulation provides modular plant, control, protection, and operator layers
for Mini-FADEC development. The engine remains a deliberately simplified
single-spool grey-box model rather than a validated thermodynamic model.

## Signal Architecture

Closed-loop operation separates physical truth from the signals observed by
the FADEC:

```text
Operator request
      |
      v
State machine -> speed controller -> EGT protection -> actuator command
      ^                 ^                 ^                  |
      |                 |                 |                  v
      +---------- SensorData <--- Sensor model <--- EngineState
                         measured values          physical truth
                                                      |
                                                      v
                                           diagnostics and plots
```

`EngineState` is owned and updated by the engine plant. The sensor model reads
that narrowly scoped state without modifying it and publishes `SensorData`.
State transitions based on engine conditions, speed feedback, and EGT
protection all use `SensorData`; only plant integration and simulation-only
diagnostics use truth directly.

## Main Modules

- `simulation/models/` contains rotor-speed and EGT plant dynamics plus
  algebraic thrust and fuel-flow estimates.
- `simulation/sensors/` converts engine truth into measured rotor speed and
  EGT.
- `simulation/operation/` owns the explicit engine operating-state machine.
- `simulation/controllers/` schedules demanded speed and calculates requested
  fuel.
- `simulation/protection/` limits the requested command using measured EGT.
- `simulation/application/` composes the components and provides terminal and
  graphical interactive applications.
- `simulation/examples/` contains open-loop and closed-loop demonstrations.

The component boundaries use the protocols and data types in
`simulation/core/`. Open-loop plant-only examples may inspect truth directly;
closed-loop examples route feedback through the sensor model.

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

## Fixed-Step Execution

For each coordinated simulation step:

1. Sample or retain measured engine signals.
2. Evaluate operating-state transitions from operator requests and measured
   conditions.
3. Calculate open-loop start fuel or closed-loop requested fuel.
4. Apply EGT protection using measured temperature.
5. Advance the physical engine model with the allowed actuator command.
6. Record truth, measurements, commands, errors, and derived outputs.

## Current Limitations

The simulation does not yet model sensor faults, stuck signals, dropouts,
runtime bias changes, signal-validity states, redundant sensors, or sensor
filters. Fault injection and signal validation are deferred to Sprint 9.
Detailed compressor maps, combustion chemistry, environmental corrections,
actuator dynamics, and real-time hardware communication are also outside the
current model scope.
