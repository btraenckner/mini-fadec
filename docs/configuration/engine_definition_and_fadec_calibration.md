# Engine Definition and FADEC Calibration

## Configuration Boundary

Keep facts about the engine and its installed interfaces in an
`EngineDefinition`. Keep values that may be tuned without changing the engine
in a `FadecCalibration`.

| Engine definition | FADEC calibration |
|---|---|
| Plant backend and physical parameters | Throttle-to-speed schedule |
| Sensor ranges, noise, and quantization | PI controller gains and fuel range |
| Fuel, starter, and ignition command capability | Start and shutdown thresholds |
| Continuous and transient operating limits | Signal-validation thresholds |
| Engine identity and definition version | Protection thresholds and rates |

The project-owned starting profiles are created by
`reference_engine_definition()` and `reference_fadec_calibration()` in
`simulation/configuration/profiles.py`. They preserve the behavior that existed
before this configuration layer was introduced.

## Defining Another Engine

Create a fresh immutable profile rather than changing a stateful runtime
object. `dataclasses.replace()` is useful when only a few values differ:

```python
from dataclasses import replace

from simulation.application.factory import create_application
from simulation.configuration import (
    reference_engine_definition,
    reference_fadec_calibration,
)

engine = reference_engine_definition()
engine = replace(
    engine,
    engine_id="my-engine",
    display_name="My single-spool engine",
    definition_version="0.1.0",
)

calibration = reference_fadec_calibration()
calibration = replace(
    calibration,
    calibration_id="my-engine-initial-calibration",
    calibration_version="0.1.0",
    target_engine_id=engine.engine_id,
)

simulation = create_application(
    engine_definition=engine,
    fadec_calibration=calibration,
)
```

For a substantially different engine, construct `EngineDefinition` and its
nested dataclasses explicitly. Give each intentional physical change a new
`definition_version`. Tune a separate `FadecCalibration` and increment its
`calibration_version` when control or protection values change.

## Validation and Testing Workflow

1. Enter the engine plant, sensor, actuator, and operating-envelope data.
2. Create a calibration targeted to the exact `engine_id`.
3. Construct the application. Incompatible inputs fail before simulation
   startup with all detected issues in one exception.
4. Run deterministic scenarios across normal operation, limits, faults, and
   environmental cases.
5. Inspect telemetry and requirements, adjust calibration, and rerun without
   modifying the engine definition unless a physical assumption changed.

Recorded `metadata.json` files contain complete `engine_definition` and
`fadec_calibration` snapshots. They are the authoritative record of which
configuration produced a run.

These profiles remain grey-box development inputs. Their version identifiers
provide traceability; they do not imply that an engine model or calibration is
validated or certified.
