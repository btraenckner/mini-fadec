# PathSim in Mini-FADEC

Sprint 14 uses PathSim 0.24.0 as one selectable physical engine-plant
backend. It integrates a transparent three-state nonlinear grey-box model and
returns the same project-owned `EngineState` and `EngineOutputs` types as the
first-order reference plant.

PathSim models only physical response. The Mini-FADEC deterministic scheduler
remains the sole time authority and continues to execute the state machine,
sensor sampling and fault injection, validation, controller, protection
manager, actuator hold, snapshots, telemetry, scenarios, and dashboard. At one
plant release, the held `ActuatorCommand` is passed to the selected plant, the
plant advances exactly one plant period, and simulated sensors subsequently
sample the new engine truth. PathSim never runs a second application loop.

The production boundary is under `simulation/plants/`:

- `interfaces.py` defines the project-owned `EnginePlant` protocol.
- `factory.py` explicitly constructs one of the two registered backends.
- `first_order/` configures the regression-reference model.
- `pathsim_greybox/` contains configuration, equations, the PathSim adapter,
  and the initial nonlinear model.

All PathSim parameters are **unvalidated development assumptions**. The model
is educational and is not a validated representation of a particular
commercial engine.

## Setup and examples

Install the existing development environment, including the exact PathSim pin:

```bash
python -m pip install -r requirements-dev.txt
```

Run the learning examples from the repository root:

```bash
python -m simulation.examples.pathsim.01_minimal_ode
python -m simulation.examples.pathsim.02_greybox_open_loop
python -m simulation.examples.pathsim.03_compare_plant_models
```

The plotting examples write to `results/pathsim/`. The comparison intentionally
demonstrates structural differences; the models are not expected to match.

List or run PathSim scenarios with the shared scenario CLI:

```bash
python -m simulation.scenarios.cli plants
python -m simulation.scenarios.cli run SCN-PLANT-PS-001 \
  --plant pathsim_greybox_v1
```

In the live dashboard, open `PLANT: FO`, select the backend while the engine is
OFF, and inspect the read-only configuration and PathSim dynamic diagnostics.

