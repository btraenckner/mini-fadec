# Public-Data Engine Profiles

Mini-FADEC includes two selectable real-engine examples. They are grey-box
simulation profiles, not manufacturer ECU calibrations and not evidence that
the FADEC is safe for real hardware. Every recorded run stores the full engine
definition, FADEC calibration, source references, assumptions, and profile
fidelity in `metadata.json`.

The profiles can be selected in the live dashboard under
`PLANT` > `SELECT ENGINE PROFILE`. The plant backend remains independently
selectable as either First-order or PathSim. Profile changes are accepted only
while the engine is `OFF` and recording is stopped.

## JetCat P1000-PRO

Profile ID: `jetcat-p1000-pro`

Fidelity: `public-data grey-box`

### Published manufacturer data represented in the profile

| Quantity | Published value |
|---|---:|
| Part number | 71157-0000 |
| Idle / maximum speed | 19,000 / 61,500 rpm |
| Idle / maximum thrust | 45 / 1,100 N |
| EGT range | 480-720 °C |
| Idle / full-load fuel flow | 550 / 2,900 ml/min |
| Mass | 11 kg |
| Diameter / length | 234 / 444 mm |
| Pressure ratio | 4.0 |
| Mass flow | 1.8 kg/s |
| Exhaust velocity | 2,200 km/h |
| Exhaust power | 336.1 kW |
| Specific fuel consumption | 0.127 kg/(N h) |
| Supply | 10-35 V |
| Maximum electrical starting power | approximately 300 W |
| Integrated generator | 500 W |
| Integrated DC/DC converter | 180 W / 16 A |

The public product information also describes an integrated ECU, brushless
starter-generator, two fuel pumps, three valves, fuel filter, dual
direct-kerosene ignition, barometric pressure measurement, automatic cooldown,
in-flight restart, safety shutdown input, telemetry, and PWM, serial, analog,
JetCat-bus, and CAN interfaces. The older basic-information sheet describes a
single axial turbine stage, two bearings, starts between -40 and +50 °C, a
0-6,000 m start-altitude range, 0-150 m/s start airspeed, and a 50-hour
inspection interval.

Sources:

- [JetCat P1000-PRO product specifications](https://www.jetcat.de/en/productdetails/produkte/jetcat/produkte/Professionell/P1000)
- [JetCat P1000-PRO basic technical information, 2021-02-16](https://www.jetcat.de/jetcat/produkte/pro/JetCat-P1000-BasicTechnicalInformation-2021-16-02.pdf)

### Model assumptions

JetCat does not publish spool, thermal, fuel-system, sensor, or closed-loop ECU
dynamics. The first-order time constants, start thresholds, sensor behavior,
PI gains, and protection rates are therefore initial engineering assumptions.
The First-order thrust curve is quadratic above idle. The PathSim thrust
exponent is fitted to the two published thrust/speed points. At ISA sea-level
conditions, both backends are calibrated to settle near 61,500 rpm and 1,100 N
without exceeding the 720 °C transient EGT limit.

## AeroDesignWorks B350STG

Profile ID: `aerodesignworks-b350-stg`

Fidelity: `provisional family proxy`

AeroDesignWorks publicly identifies the B350STG as a turbojet with an
integrated starter-generator and describes the series-produced B300 engine
series as the basis of its lower thrust range. A detailed public B350STG
datasheet or operating manual was not found. Consequently, no inferred B350
numbers are stored as published hardware facts.

Sources:

- [AeroDesignWorks product overview](https://www.aerodesignworks.com/en/)
- [AeroDesignWorks B300F operating manual](https://www.aerodesignworks.com/wp-content/uploads/OperatingManual_B300F.pdf)
- [AeroDesignWorks HORNET III ECU manual](https://www.aerodesignworks.com/wp-content/uploads/2022-04-27_hornet_manual_v3.0_en.pdf)

### B300F family-proxy data

The public B300F manual reports the following values. They are useful starting
points but are not B350STG specifications.

| Quantity | Published B300F value | B350STG model use |
|---|---:|---|
| Idle / maximum speed | 35,000 / 104,000 rpm | used as provisional schedule |
| Idle / maximum thrust | 15 / 300 N | maximum scaled to assumed 350 N |
| EGT range | 680-760 °C | used as provisional envelope |
| Maximum fuel flow | 980 ml/min | scaled by 350/300 in the plant model |
| Idle-to-full acceleration | 4.6 s | used to derive a first-order time constant |
| 65,000-rpm-to-full acceleration | 2.2 s | retained as provenance only |
| Diameter / length | 133 / 390 mm | not copied to B350 hardware facts |
| Mass | 2.65 kg | not copied to B350 hardware facts |
| Fuel | Jet A-1 or diesel with 5% oil | family information only |

The provisional simulation assumes that `B350` denotes 350 N maximum thrust.
It uses the B300F speed and EGT ranges, scales the B300F fuel flow and idle
thrust by 350/300, and uses the approximately cubic thrust/speed relationship
described in the HORNET III manual. Its start thresholds, sensors, PathSim
coefficients, PI gains, and protection rates are model assumptions. They must
be replaced or revalidated when B350STG manufacturer or test-bench data become
available.

## Recommended validation path

1. Obtain the exact engine revision, manufacturer limits, ECU logs, and sensor
   interface specifications.
2. Record steady-state points across throttle, ambient temperature, and
   pressure, followed by controlled transient tests.
3. Update only the physical `EngineDefinition` when evidence about the engine
   changes; increment its version.
4. Identify plant coefficients against the measurements, then tune the
   separate `FadecCalibration` and increment its version.
5. Create engine-specific scenarios and requirements. The existing scenario
   thresholds were developed for the Mini-FADEC reference engine and are not
   automatically certification criteria for either real-engine profile.
