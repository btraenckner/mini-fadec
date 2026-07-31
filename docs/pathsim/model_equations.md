# PathSim grey-box model equations

The initial `pathsim_greybox_v1` model is a normalized, single-spool,
three-state teaching model. Every coefficient below is an unvalidated
development assumption. “Effective” units mean the coefficient is consistent
inside the documented normalized equations, not a measured SI torque.

## States, inputs, and outputs

| Symbol | Software name | Meaning | Bound / unit |
|---|---|---|---|
| `f_eff` | `effective_fuel` | Lagged physical fuel/combustion input | `[0, 1]`, normalized |
| `n` | `normalized_speed` | Spool speed divided by maximum RPM | `[0, 1.15]`, normalized |
| `T_g` | `gas_temperature_c` | Exhaust gas temperature state | `>= -80 °C` |
| `f_cmd` | `fuel_command` | Held FADEC fuel command | clamped `[0, 1]` |
| `u_s` | `starter_commanded` | Starter input | Boolean |
| `u_i` | `ignition_commanded` | Ignition support input | Boolean |
| `u_f` | `fuel_enabled` | Fuel-enable input | Boolean |
| `T_amb` | `ambient_temperature_c` | Ambient temperature | °C |
| `p_amb` | `ambient_pressure_pa` | Ambient pressure | Pa, positive |
| `N` | `rotor_speed_rpm` | Engine-truth rotor speed | rpm |
| `T_g` | `exhaust_temperature_c` | Engine-truth EGT | °C |
| `F` | `estimated_thrust_n` | Algebraic thrust estimate | N, non-negative |
| `Q_f` | `estimated_fuel_flow_ml_min` | Effective fuel-flow estimate | ml/min, non-negative |

## Fuel-system lag

Fuel is commanded to zero whenever `fuel_enabled` is false; there is no hidden
minimum fuel inside the plant.

```text
f_in = clamp(f_cmd, 0, 1) when fuel is enabled, otherwise 0
df_eff/dt = (f_in - f_eff) / tau_f
```

The state is clipped to `[0, 1]` after each exact solver substep. A hard FADEC
cutoff therefore changes `f_in` immediately, while the physical state decays
with `tau_f`.

## Combustion effectiveness

The plant does not know the FADEC operating states. A cubic smoothstep provides
speed sustain between `n_lightoff` and `n_full`:

```text
z = clamp((n - n_lightoff) / (n_full - n_lightoff), 0, 1)
speed_sustain = z² (3 - 2z)
ignition_support = ignition_effectiveness when ignition is commanded, else 0
eta_comb = clamp(max(speed_sustain, ignition_support), 0, 1)
```

`eta_comb` is zero if fuel is disabled or no effective fuel remains. This is a
simple bounded startup aid, not combustion chemistry or flameout hysteresis.

## Normalized spool dynamics

```text
tau_starter    = K_s u_s
tau_turbine    = K_t f_eff eta_comb
tau_compressor = K_c n²
tau_friction   = K_l n

dn/dt = (tau_starter + tau_turbine
         - tau_compressor - tau_friction) / J_n
N = n N_max
```

The torque terms have effective normalized acceleration units. At zero speed,
a negative derivative is suppressed. Positive drift above the configured
maximum normalized speed is suppressed, and post-step clipping enforces the
documented state domain.

## Thermal dynamics

```text
Delta_T_comb = eta_comb (T_base + a1 f_eff + a2 f_eff²)
T_eq = max(T_min, T_amb + Delta_T_comb - a3 n)
dT_g/dt = (T_eq - T_g) / tau_T
```

The temperature equation is a thermal lag around a deliberately simple
equilibrium relation. It is not a Brayton-cycle station model. The lower guard
prevents integration below `T_min`.

## Algebraic outputs

```text
C_ambient = clamp(p_amb / 101325, 0.5, 1.2)
F = max(0, F_max n^p_F C_ambient)
Q_f = Q_f,max clamp(f_eff, 0, 1)
```

Only thrust receives the simple pressure correction. No nozzle, corrected
mass-flow, or choking model is implied.

## Default parameters

| Configuration field | Default | Unit / effective unit |
|---|---:|---|
| `fuel_time_constant_s` | 0.15 | s |
| `normalized_inertia` | 1.0 | effective normalized inertia |
| `starter_torque_gain_per_s` | 0.12 | effective normalized acceleration, 1/s |
| `turbine_torque_gain_per_s` | 0.85 | effective normalized acceleration, 1/s |
| `compressor_load_gain_per_s` | 0.55 | effective normalized acceleration, 1/s |
| `friction_load_gain_per_s` | 0.04 | effective normalized acceleration, 1/s |
| `minimum_lightoff_speed_ratio` | 0.08 | normalized |
| `full_combustion_speed_ratio` | 0.28 | normalized |
| `ignition_effectiveness` | 0.95 | normalized |
| `combustion_base_temperature_rise_c` | 350 | °C |
| `linear_fuel_temperature_gain_c` | 1000 | °C per normalized fuel |
| `quadratic_fuel_temperature_gain_c` | 300 | °C per normalized fuel² |
| `speed_temperature_cooling_gain_c` | 100 | °C per normalized speed |
| `thermal_time_constant_s` | 0.35 | s |
| `maximum_speed_rpm` | 128000 | rpm |
| `maximum_normalized_speed` | 1.15 | normalized |
| `maximum_thrust_n` | 140 | N |
| `thrust_speed_exponent` | 2.0 | dimensionless |
| `maximum_fuel_flow_ml_min` | 480 | ml/min |
| `minimum_gas_temperature_c` | -80 | °C |

Cold defaults are `f_eff=0`, `n=0`, and `T_g=T_amb`. The solver default is
classical fixed-step RK4 with one internal substep per scheduler plant period.

## Signal flow

```text
Fuel command
    ↓
Fuel lag state
    ↓
Combustion effectiveness
    ↓
Turbine torque ─────┐
                    ↓
Starter torque → spool dynamics ← compressor and friction loads
                    ↓
             normalized speed
                    ↓
         RPM, thrust and cooling influence

Fuel + speed + ambient
           ↓
  temperature equilibrium
           ↓
      thermal lag state
           ↓
             EGT
```

## Limitations

The model has no compressor/turbine maps, surge, corrected flow, nozzle
choking, combustion chemistry, detailed atmosphere, multiple spools,
actuator maps, guide vanes, bleed system, or physical validation. State
clipping is a numerical domain guard and can conceal that an unsuitable
parameter set is driving into a boundary; diagnostics must be inspected during
tuning.

