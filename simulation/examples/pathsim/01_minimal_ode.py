"""Integrate and reset one first-order ODE with the pinned PathSim API."""

from simulation.plants.pathsim_greybox.learning import run_minimal_ode_demo


def main() -> None:
    """Construct, single-step, inspect, and reset a PathSim simulation."""

    # Direct PathSim imports remain inside pathsim_greybox/learning.py, beside
    # the production adapter. Inspect that short helper to see ODE construction,
    # RK4 selection, the single-timestep API, state extraction, and reset.
    result = run_minimal_ode_demo()
    print(
        "after step:",
        f"success={result.success}",
        f"time={result.time_after_step_s:.1f}",
        f"state={result.state_after_step:.8f}",
        f"error={result.error_indicator}",
        f"evaluations={result.solver_evaluations}",
        f"iterations={result.solver_iterations}",
    )
    print(
        "after reset:",
        f"time={result.time_after_reset_s:.1f}",
        f"state={result.state_after_reset:.1f}",
    )


if __name__ == "__main__":
    main()
