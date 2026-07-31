"""Isolated direct PathSim API demonstration used by learning example 01."""

from dataclasses import dataclass

import numpy as np
from pathsim import Simulation
from pathsim.blocks import ODE
from pathsim.solvers import RK4


@dataclass(frozen=True)
class MinimalOdeResult:
    """Values extracted before and after resetting the minimal ODE."""

    success: bool
    time_after_step_s: float
    state_after_step: float
    error_indicator: float
    solver_evaluations: int
    solver_iterations: int
    time_after_reset_s: float
    state_after_reset: float


def decay_derivative(
    state: np.ndarray,
    _inputs: np.ndarray,
    _time_s: float,
) -> np.ndarray:
    """Return dx/dt = -x for the minimal learning system."""

    return -state


def run_minimal_ode_demo() -> MinimalOdeResult:
    """Construct, single-step, inspect, and reset one PathSim ODE."""

    # The ODE block owns one continuous state initialized to x(0) = 1.
    ode = ODE(func=decay_derivative, initial_value=np.asarray((1.0,)))

    # Sprint 14 uses classical fixed-step RK4. This learning helper remains
    # inside the same version-sensitive boundary as the production adapter.
    simulation = Simulation(
        blocks=[ode],
        dt=0.1,
        Solver=RK4,
        log=False,
    )
    simulation.reset(time=0.0)

    # ``timestep`` is the supported PathSim 0.24 single-step API. It advances
    # only the requested interval; no independent long-running loop is started.
    success, error, _scale, evaluations, iterations = simulation.timestep(
        0.1,
        adaptive=False,
    )
    stepped_time_s = float(simulation.time)
    stepped_state = float(ode.state[0])

    simulation.reset(time=0.0)
    return MinimalOdeResult(
        success=bool(success),
        time_after_step_s=stepped_time_s,
        state_after_step=stepped_state,
        error_indicator=float(error),
        solver_evaluations=int(evaluations),
        solver_iterations=int(iterations),
        time_after_reset_s=float(simulation.time),
        state_after_reset=float(ode.state[0]),
    )
