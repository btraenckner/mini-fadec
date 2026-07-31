"""Integrate and reset one first-order ODE with the pinned PathSim API."""

import numpy as np
from pathsim import Simulation
from pathsim.blocks import ODE
from pathsim.solvers import RK4


def decay_derivative(
    state: np.ndarray,
    _inputs: np.ndarray,
    _time_s: float,
) -> np.ndarray:
    """Return dx/dt = -x for the minimal learning system."""

    return -state


def main() -> None:
    """Construct, single-step, inspect, and reset a PathSim simulation."""

    # The ODE block owns one continuous state initialized to x(0) = 1.
    ode = ODE(func=decay_derivative, initial_value=np.asarray((1.0,)))

    # Mini-FADEC Sprint 14 uses classical fixed-step RK4. Production code wraps
    # these version-sensitive objects in pathsim_greybox/adapter.py.
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
    print(
        "after step:",
        f"success={success}",
        f"time={simulation.time:.1f}",
        f"state={float(ode.state[0]):.8f}",
        f"error={error}",
        f"evaluations={evaluations}",
        f"iterations={iterations}",
    )

    simulation.reset(time=0.0)
    print(
        "after reset:",
        f"time={simulation.time:.1f}",
        f"state={float(ode.state[0]):.1f}",
    )


if __name__ == "__main__":
    main()
