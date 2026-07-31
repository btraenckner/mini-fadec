# PathSim learning roadmap

Sprint 14 establishes a stable backend boundary and an inspectable first-draft
model. The following sub-sprints deliberately build understanding before
claiming fidelity.

## Sprint 14.1 — PathSim Model Anatomy and Manual Parameter Exploration

- Study PathSim blocks, connections, continuous states, and simulation reset.
- Walk through every grey-box equation and named diagnostic term.
- Optionally decompose the vector system into named subsystems where that
  improves learning without changing behavior.
- Perform one-parameter-at-a-time experiments.
- Add immutable parameter presets.
- Improve internal-state visualization in the dashboard.
- Examine fuel lag, inertia, torque coefficients, and thermal lag.

Extension points already prepared: small equation functions, grouped frozen
configuration, serializable metadata, read-only dashboard parameter display,
and the standalone plant example.

## Sprint 14.2 — Solver Convergence, Timestep Selection, and Simulation Performance

- Compare fixed RK4 with suitable adaptive and implicit solvers.
- Generate high-accuracy reference runs and systematic step-size studies.
- Quantify RPM, EGT, thrust, state, and event-time errors.
- Measure wall-clock runtime and real-time factor.
- Determine whether revised dynamics are stiff and profile bottlenecks.
- Select a justified dashboard solver configuration.

Extension points already prepared: typed `PathSimSolverConfig`, exact internal
substeps, solver/time counters, isolated API calls, and deterministic scenarios.
Sprint 14 does not implement adaptive dashboard tuning or a benchmark suite.

## Sprint 14.3 — Grey-Box Parameter Calibration and Model Fidelity

- Create synthetic calibration and validation datasets.
- Recover known parameters with bounded optimization.
- Study parameter sensitivity and identifiability.
- Fit rotor-speed and EGT transient behavior.
- Add justified ambient effects and refine thrust estimation.
- Consider lookup tables or operating-point-dependent coefficients only where
  evidence supports them.

Extension points already prepared: immutable grouped parameters, deterministic
serialization, named equations, repeatable reset, telemetry of internal states,
and isolated model-specific scenarios. Sprint 14 contains no automatic
calibration and makes no physical-validation claim.
