# Mini-FADEC

Mini-FADEC is a modular learning and development platform for embedded control systems, real-time software, simulation, and experimental gas turbine control.

The project is developed step by step, beginning with software engineering fundamentals and Python-based simulations before progressing toward embedded hardware, hardware-in-the-loop testing, and a stationary small gas turbine test bench.

## Project Objectives

* Learn professional software development with Git and GitHub
* Develop dynamic system models in Python
* Implement and test reusable control algorithms
* Learn embedded C and STM32 development
* Introduce real-time software and communication interfaces
* Build software-in-the-loop and hardware-in-the-loop test environments
* Develop a modular FADEC-like control architecture
* Integrate a safe, stationary experimental small gas turbine test bench

## Development Approach

The project follows an incremental and safety-oriented development process:

1. Development environment and version control
2. Python simulation framework
3. Dynamic system modelling
4. Closed-loop control simulation
5. Embedded C fundamentals
6. STM32 hardware integration
7. Real-time execution and communication
8. BLDC motor test bench
9. Hardware-in-the-loop testing
10. Experimental stationary gas turbine control

Simulation and low-power demonstrators are used before safety-critical hardware is introduced.

## Repository Structure


mini-fadec/
├── docs/          Project documentation and engineering decisions
├── embedded/      Embedded firmware and hardware-related software
├── simulation/    Dynamic models, controllers, and simulations
├── tests/         Automated software and integration tests
├── .gitignore
└── README.md


## Current Status

**Milestone:** Project Foundation v0.1

Current activities:

* Setting up the development environment
* Learning Git and GitHub
* Establishing the repository structure
* Preparing the Python simulation environment

## Safety Notice

This project is intended for educational and experimental purposes.

Motors, propellers, batteries, fuel systems, pumps, power electronics, and gas turbines can cause severe injury, fire, or property damage. Hardware testing must use suitable mechanical protection, independent emergency shutdown systems, fire protection, and controlled test conditions.

Safety-critical protection must never rely exclusively on software.

## License

A project license has not yet been selected.
