# PathSim backend integration

## Stable plant boundary

Application code depends on the runtime-checkable `EnginePlant` protocol. A
plant exposes stable identity, current `EngineState`, `reset`, one-interval
`step`, immutable `PlantDiagnostics`, and fresh JSON-serializable metadata. No
PathSim block, solver, register, or simulation object crosses this boundary.

`PlantSelectionConfig` owns immutable grouped configuration for both backends.
`PlantModelKind` provides the persistence IDs `first_order` and
`pathsim_greybox_v1`. `create_engine_plant` is a small explicit factory; it does
not scan modules and never falls back to another model.

The existing first-order class implements this boundary in place, preserving
its old module import and equations. It remains the default and regression
reference.

## PathSim adapter and one-step execution

Only `simulation/plants/pathsim_greybox/adapter.py` owns production PathSim
objects and version-sensitive calls. It constructs one vector-valued
`DynamicalSystem`, one `Simulation`, and classical `pathsim.solvers.RK4`.

PathSim 0.24.0 exposes the supported non-deprecated API:

```python
simulation.timestep(dt_s, adaptive=False)
```

`Simulation.step` is a backward-compatibility wrapper and is intentionally not
used. `Simulation.run` is never called by the plant. If configured, an integer
number of fixed internal substeps must divide the scheduler interval exactly.
After every substep, documented state-domain guards are applied and extracted
into project-owned immutable types.

The adapter maps any construction/integration exception to
`PlantSimulationError`. The model adds current time, states, and held inputs.
There is no silent first-order fallback.

## Scheduler ownership and synchronization

The Sprint 13 deterministic scheduler calls the plant task once per release
with the held post-protection actuator command and exact task period. The plant
advances only that interval. Both the adapter and coordinator compare expected
time against PathSim time with a strict floating-point tolerance; divergence
raises `PlantSimulationError`.

The controller, protection manager, state machine, and sensor validation remain
outside the plant. Sensor models continue to consume engine truth only after a
plant execution, while operational feedback reaches the FADEC only through
validated sensor data.

## Reset and failure behavior

PathSim reset rebuilds the small simulation graph, restoring continuous initial
conditions, time zero, RK4 state, inputs, output cache, integration status, and
all counters. It does not reset any FADEC component. A complete application
replacement resets plant, sensors, controller, state machine, scheduler, and
held commands separately.

The service permits plant selection only while the engine is OFF and recording
is inactive. A successful selection creates a fresh coordinator. A production
plant error finalizes an active recording as incomplete, fails a scenario with
the diagnostic reason, or stops dashboard advancement and displays the error.

## Diagnostics and artifacts

Every snapshot includes plant ID, display name, model version, plant time, and
plant call count. A typed optional PathSim diagnostics object contains the
three states, combustion effectiveness, torque/load terms, equilibrium
temperature, solver steps/evaluations, and PathSim version. First-order
snapshots keep this object `None`.

Telemetry uses one stable schema for both backends. PathSim columns are blank
for first-order runs. Run metadata stores static configuration, actual initial
conditions, solver settings/API, package version, assumptions, and limitations.
Scenario results/reports and the run-inspection utility identify the effective
plant.

## Dashboard and scenarios

The dashboard selector invokes the same service/factory as other clients. It
cannot manipulate PathSim blocks or arbitrary state. Parameters are read-only
in Sprint 14. Scenario priority is:

1. typed scenario `plant_config_override`,
2. runner/application/CLI selection,
3. the project default first-order plant.

Existing regression scenarios have no override and remain first-order. The
PathSim smoke, provisional lifecycle, and fuel-step scenarios form a separate
development group with broad model-specific requirements.
