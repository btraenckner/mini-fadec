"""Narrow PathSim 0.24 adapter for exact fixed-step plant integration."""

from dataclasses import dataclass
from importlib.metadata import version

import numpy as np
from pathsim import Simulation
from pathsim.blocks import DynamicalSystem
from pathsim.solvers import RK4

from simulation.plants.pathsim_greybox.config import (
    PathSimGreyBoxConfig,
    PathSimSolverConfig,
)
from simulation.plants.pathsim_greybox.equations import (
    GreyBoxInputs,
    GreyBoxStateVector,
    calculate_state_derivative,
    constrain_state,
)
from simulation.plants.types import PlantSimulationError


@dataclass(frozen=True)
class PathSimStepResult:
    """Project-owned result of one scheduler-requested integration interval."""

    success: bool
    error_indicator: float | None
    internal_substeps: int
    solver_evaluations: int
    solver_iterations: int


class PathSimEngineAdapter:
    """Own the only PathSim objects and version-sensitive production calls."""

    def __init__(
        self,
        configuration: PathSimGreyBoxConfig,
        initial_state: GreyBoxStateVector,
    ) -> None:
        self.configuration = configuration
        self.pathsim_version = version("pathsim")
        self._inputs = GreyBoxInputs(
            fuel_command=0.0,
            starter_commanded=False,
            ignition_commanded=False,
            fuel_enabled=False,
            ambient_temperature_c=initial_state.gas_temperature_c,
            ambient_pressure_pa=101_325.0,
        )
        self._initial_state = initial_state
        self._total_solver_evaluations = 0
        self._total_solver_iterations = 0
        self._solver_step_count = 0
        self._build_simulation()

    @property
    def time_s(self) -> float:
        """Return PathSim's authoritative internal simulation time."""

        return float(self._simulation.time)

    @property
    def state(self) -> GreyBoxStateVector:
        """Extract current PathSim state into an immutable project type."""

        return _array_to_state(self._system.state)

    @property
    def total_solver_evaluations(self) -> int:
        return self._total_solver_evaluations

    @property
    def total_solver_iterations(self) -> int:
        return self._total_solver_iterations

    @property
    def solver_step_count(self) -> int:
        return self._solver_step_count

    def advance(
        self,
        inputs: GreyBoxInputs,
        dt_s: float,
    ) -> PathSimStepResult:
        """Advance via non-deprecated ``Simulation.timestep`` exactly once or N times."""

        substep_count, substep_s = _resolve_substeps(
            self.configuration.solver,
            dt_s,
        )
        self._inputs = inputs
        start_time_s = self.time_s
        maximum_error = 0.0
        interval_evaluations = 0
        interval_iterations = 0
        try:
            for _ in range(substep_count):
                (
                    success,
                    error_indicator,
                    _scale,
                    evaluations,
                    iterations,
                ) = self._simulation.timestep(
                    substep_s,
                    adaptive=False,
                )
                if not success:
                    raise PlantSimulationError(
                        "PathSim RK4 reported an unsuccessful fixed step"
                    )
                constrained = constrain_state(
                    self.state,
                    self.configuration,
                )
                self._system.state = _state_to_array(constrained)
                maximum_error = max(maximum_error, float(error_indicator))
                interval_evaluations += int(evaluations)
                interval_iterations += int(iterations)
                self._solver_step_count += 1
        except PlantSimulationError:
            raise
        except Exception as error:
            raise PlantSimulationError(
                f"PathSim integration failed at t={self.time_s:.9f} s: "
                f"{type(error).__name__}: {error}"
            ) from error

        expected_time_s = start_time_s + dt_s
        tolerance_s = 1.0e-12 * max(1.0, abs(expected_time_s))
        if abs(self.time_s - expected_time_s) > tolerance_s:
            raise PlantSimulationError(
                "PathSim time mismatch: "
                f"expected {expected_time_s:.12f} s, "
                f"observed {self.time_s:.12f} s"
            )
        self._total_solver_evaluations += interval_evaluations
        self._total_solver_iterations += interval_iterations
        return PathSimStepResult(
            success=True,
            error_indicator=maximum_error,
            internal_substeps=substep_count,
            solver_evaluations=interval_evaluations,
            solver_iterations=interval_iterations,
        )

    def reset(self, initial_state: GreyBoxStateVector | None = None) -> None:
        """Rebuild the PathSim graph to clear all solver and block state."""

        if initial_state is not None:
            self._initial_state = initial_state
        self._total_solver_evaluations = 0
        self._total_solver_iterations = 0
        self._solver_step_count = 0
        self._build_simulation()

    def _build_simulation(self) -> None:
        """Construct one vector-valued dynamic system with classical RK4."""

        self._system = DynamicalSystem(
            func_dyn=self._state_derivative,
            func_alg=_state_output,
            initial_value=_state_to_array(self._initial_state),
        )
        configured_step_s = (
            self.configuration.solver.internal_step_s or 0.001
        )
        self._simulation = Simulation(
            blocks=[self._system],
            dt=configured_step_s,
            Solver=RK4,
            log=False,
            diagnostics=True,
        )
        self._simulation.reset(time=0.0)

    def _state_derivative(
        self,
        state: np.ndarray,
        _unused_inputs: np.ndarray,
        _time_s: float,
    ) -> np.ndarray:
        derivative = calculate_state_derivative(
            _array_to_state(state),
            self._inputs,
            self.configuration,
        )
        return _state_to_array(derivative)


def _state_output(
    state: np.ndarray,
    _inputs: np.ndarray,
    _time_s: float,
) -> np.ndarray:
    """Expose the dynamic state without adding an algebraic plant loop."""

    return state


def _resolve_substeps(
    solver: PathSimSolverConfig,
    dt_s: float,
) -> tuple[int, float]:
    if dt_s <= 0.0:
        raise ValueError("dt_s must be greater than zero")
    if solver.internal_step_s is None:
        return solver.internal_substep_count, (
            dt_s / solver.internal_substep_count
        )
    ratio = dt_s / solver.internal_step_s
    rounded_ratio = round(ratio)
    tolerance = 1.0e-12 * max(1.0, abs(ratio))
    if abs(ratio - rounded_ratio) > tolerance:
        raise ValueError(
            "internal_step_s must divide the requested plant interval exactly"
        )
    if rounded_ratio != solver.internal_substep_count:
        raise ValueError(
            "internal_substep_count does not match dt_s / internal_step_s"
        )
    return solver.internal_substep_count, solver.internal_step_s


def _state_to_array(state: GreyBoxStateVector) -> np.ndarray:
    return np.asarray(
        (
            state.effective_fuel,
            state.normalized_speed,
            state.gas_temperature_c,
        ),
        dtype=float,
    )


def _array_to_state(state: object) -> GreyBoxStateVector:
    values = np.asarray(state, dtype=float).reshape(3)
    return GreyBoxStateVector(
        effective_fuel=float(values[0]),
        normalized_speed=float(values[1]),
        gas_temperature_c=float(values[2]),
    )
