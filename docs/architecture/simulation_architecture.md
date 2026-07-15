# Simulation Architecture

## Purpose

The simulation environment provides a modular platform for developing and testing Mini-FADEC control functions before they are implemented on embedded hardware.

The initial simulation represents the running operation of a small single-spool model gas turbine. It is intentionally simplified and is intended for controller development, software testing, and later software-in-the-loop and hardware-in-the-loop integration.

## Architecture Overview

The simulation is divided into independent functional modules:

Throttle Command
       |
       v
Setpoint Scheduling
       |
       v
Engine Controller
       |
       v
Limiters
       |
       v
Fuel Command
       |
       v
Engine Model
       |
       +---- Rotor Speed
       |
       +---- Exhaust Gas Temperature
       |
       +---- Estimated Thrust
       |
       +---- Estimated Fuel Flow
       |
       v
Logging and Visualization

## Main Modules

### Engine Model

The engine model represents the dynamic response of the gas turbine.

Initial states:
- rotor speed
- exhaust gas temperature

Input:
- normalized fuel command

Outputs:
- rotor speed
- exhaust gas temperature
- estimated thrust
- estimated fuel flow

The first implementation uses a two-state grey-box model. Detailed compressor maps, combustion chemistry, and component-level thermodynamics are excluded from the initial version.

### Engine Controller

The engine controller calculates the required fuel command based on the requested operating point and measured engine values.

The initial controller will contain:

- rotor-speed controller
- minimum and maximum fuel limits
- acceleration limiter
- exhaust-gas-temperature limiter

The controller shall not directly depend on the internal implementation of the engine model.

### Setpoint Scheduling

The setpoint scheduler converts a normalized throttle command into a rotor-speed setpoint.

Input:
- normalized throttle command

Output:
- rotor-speed setpoint

The initial implementation uses a simple mapping between idle speed and maximum speed.

### Components

Component models represent sensors, actuators, and interfaces that may later be replaced by real hardware.

Planned components include:

- rotor-speed sensor
- exhaust-temperature sensor
- fuel-pump actuator
- throttle input

The first simulation may use ideal components. Sensor noise, delay, quantization, and actuator dynamics will be introduced later.

### Logging and Visualization

Logging and visualization modules record and display simulation signals.

Typical recorded signals include:
- simulation time
- throttle command
- rotor-speed setpoint
- rotor speed
- exhaust gas temperature
- fuel command
- estimated thrust
- estimated fuel flow
- active limiter states

Logging and plotting functions shall remain separate from the engine and controller logic.

## Software Structure

simulation/
├── models/
│   └── engine_model.py
├── controllers/
│   └── engine_controller.py
├── components/
│   ├── sensors.py
│   └── fuel_pump.py
├── utilities/
│   ├── logging.py
│   └── plotting.py
└── examples/
    └── open_loop_engine_simulation.py


The exact file structure may evolve as the project grows.

## Interfaces

### Engine Model Interface

Inputs:
- fuel_command
- time_step

Outputs:
- rotor_speed_rpm
- exhaust_temperature_c
- estimated_thrust_n
- estimated_fuel_flow_ml_min

### Controller Interface

Inputs:
- rotor_speed_setpoint_rpm
- measured_rotor_speed_rpm
- measured_exhaust_temperature_c
- time_step

Output:
- fuel_command

The normalized fuel command shall be limited to the range:

0.0 <= fuel_command <= 1.0


## Simulation Execution

The initial simulation uses a fixed time step.

For each simulation step:

1. Read the throttle command.
2. Calculate the rotor-speed setpoint.
3. Read simulated sensor values.
4. Calculate the controller output.
5. Apply protection and rate limits.
6. Update the engine model.
7. Calculate derived outputs.
8. Record simulation data.

## Initial Scope

The first simulation version includes:
- running operation between idle and maximum speed
- rotor-speed dynamics
- exhaust-temperature dynamics
- estimated thrust
- estimated fuel flow
- open-loop and closed-loop simulation
- deterministic execution with a fixed time step

## Excluded from the Initial Version

The following functions are initially excluded:
- engine start sequence
- ignition system
- starter motor
- fuel-valve sequencing
- shutdown and cooling sequence
- component failures
- altitude effects
- flight-speed effects
- detailed sensor dynamics
- real-time hardware communication

These functions may be introduced in later milestones.

## Design Principles

The simulation architecture shall follow these principles:

- separation of physical model and controller
- clear and stable interfaces
- independently testable modules
- minimal dependency between modules
- reproducible simulation results
- compatibility with future embedded and HIL implementations
- gradual replacement of simulated components with real hardware interfaces
