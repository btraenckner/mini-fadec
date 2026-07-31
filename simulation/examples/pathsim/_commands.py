"""Shared deterministic command sequence for PathSim learning examples."""

from simulation.core.types import ActuatorCommand


def actuator_schedule(time_s: float) -> ActuatorCommand:
    """Return the documented twenty-second open-loop input sequence."""

    if time_s < 1.0:
        return ActuatorCommand(
            fuel_command=0.0,
            starter_commanded=True,
            fuel_enabled=False,
        )
    if time_s < 3.0:
        return ActuatorCommand(
            fuel_command=0.25,
            starter_commanded=True,
            ignition_commanded=True,
            fuel_enabled=True,
        )
    if time_s < 8.0:
        return ActuatorCommand(fuel_command=0.35)
    if time_s < 12.0:
        return ActuatorCommand(fuel_command=0.75)
    if time_s < 16.0:
        return ActuatorCommand(fuel_command=0.20)
    return ActuatorCommand(fuel_command=0.0, fuel_enabled=False)
