"""PathSim-backed nonlinear grey-box physical engine model."""

import math
from dataclasses import asdict

from simulation.core.types import (
    ActuatorCommand,
    AmbientConditions,
    EngineOutputs,
    EngineState,
)
from simulation.plants.pathsim_greybox.adapter import PathSimEngineAdapter
from simulation.plants.pathsim_greybox.config import PathSimGreyBoxConfig
from simulation.plants.pathsim_greybox.equations import (
    GreyBoxInputs,
    GreyBoxStateVector,
    calculate_algebraic_terms,
    calculate_outputs,
)
from simulation.plants.types import (
    PathSimPlantDiagnostics,
    PlantDiagnostics,
    PlantModelKind,
    PlantSimulationError,
)


class PathSimGreyBoxEngineModel:
    """Initial unvalidated nonlinear educational engine-plant backend."""

    MODEL_VERSION = "0.1.0"

    def __init__(
        self,
        configuration: PathSimGreyBoxConfig | None = None,
        *,
        initial_ambient: AmbientConditions | None = None,
    ) -> None:
        self.configuration = configuration or PathSimGreyBoxConfig()
        self._ambient = initial_ambient or AmbientConditions()
        self._step_count = 0
        self._latest_step_success = True
        self._latest_error_indicator: float | None = None
        self._latest_internal_substeps = 0
        self._latest_fixed_step_s = 0.0
        self._latest_inputs = self._zero_inputs(self._ambient)
        initial_state = self._initial_state(self._ambient)
        self._adapter = PathSimEngineAdapter(
            self.configuration,
            initial_state,
        )
        self._state = self._engine_state(initial_state)
        self._latest_terms = calculate_algebraic_terms(
            initial_state,
            self._latest_inputs,
            self.configuration,
        )
        self._latest_outputs = EngineOutputs(
            estimated_thrust_n=0.0,
            estimated_fuel_flow_ml_min=0.0,
        )

    @property
    def model_id(self) -> str:
        return PlantModelKind.PATHSIM_GREYBOX_V1.value

    @property
    def display_name(self) -> str:
        return "PathSim nonlinear grey-box v1"

    @property
    def model_version(self) -> str:
        return self.MODEL_VERSION

    @property
    def state(self) -> EngineState:
        return self._state

    def reset(
        self,
        *,
        ambient: AmbientConditions | None = None,
    ) -> None:
        """Restore configured cold state and all PathSim solver diagnostics."""

        self._ambient = ambient or self._ambient
        initial_state = self._initial_state(self._ambient)
        self._adapter.reset(initial_state)
        self._step_count = 0
        self._latest_step_success = True
        self._latest_error_indicator = None
        self._latest_internal_substeps = 0
        self._latest_fixed_step_s = 0.0
        self._latest_inputs = self._zero_inputs(self._ambient)
        self._state = self._engine_state(initial_state)
        self._latest_terms = calculate_algebraic_terms(
            initial_state,
            self._latest_inputs,
            self.configuration,
        )
        self._latest_outputs = EngineOutputs(0.0, 0.0)

    def step(
        self,
        actuator_command: ActuatorCommand,
        ambient_conditions: AmbientConditions,
        time_step_s: float,
    ) -> EngineOutputs:
        """Advance PathSim exactly one scheduler-owned plant interval."""

        if not math.isfinite(time_step_s) or time_step_s <= 0.0:
            raise ValueError("time_step_s must be finite and greater than zero")
        inputs = GreyBoxInputs(
            fuel_command=actuator_command.fuel_command,
            starter_commanded=actuator_command.starter_commanded,
            ignition_commanded=actuator_command.ignition_commanded,
            fuel_enabled=actuator_command.fuel_enabled,
            ambient_temperature_c=ambient_conditions.temperature_c,
            ambient_pressure_pa=ambient_conditions.pressure_pa,
        )
        previous_time_s = self._adapter.time_s
        self._latest_inputs = inputs
        self._ambient = ambient_conditions
        try:
            result = self._adapter.advance(inputs, time_step_s)
            integrated_state = self._adapter.state
            self._latest_terms = calculate_algebraic_terms(
                integrated_state,
                inputs,
                self.configuration,
            )
            self._latest_outputs = calculate_outputs(
                integrated_state,
                inputs,
                self.configuration,
            )
            self._state = self._engine_state(integrated_state)
        except Exception as error:
            self._latest_step_success = False
            if isinstance(error, (PlantSimulationError, ValueError)):
                detail = str(error)
            else:
                detail = f"{type(error).__name__}: {error}"
            raise PlantSimulationError(
                "PathSim plant failed at "
                f"t={previous_time_s:.9f} s; state={self._adapter.state}; "
                f"inputs={inputs}: {detail}"
            ) from error

        expected_time_s = previous_time_s + time_step_s
        tolerance_s = 1.0e-12 * max(1.0, expected_time_s)
        if abs(self._adapter.time_s - expected_time_s) > tolerance_s:
            self._latest_step_success = False
            raise PlantSimulationError(
                "plant time diverged from requested scheduler interval"
            )
        self._step_count += 1
        self._latest_step_success = result.success
        self._latest_error_indicator = result.error_indicator
        self._latest_internal_substeps = result.internal_substeps
        self._latest_fixed_step_s = time_step_s / result.internal_substeps
        return self._latest_outputs

    def get_diagnostics(self) -> PlantDiagnostics:
        """Return common and PathSim-specific immutable diagnostics."""

        integrated_state = self._adapter.state
        return PlantDiagnostics(
            model_id=self.model_id,
            display_name=self.display_name,
            model_version=self.model_version,
            model_time_s=self._adapter.time_s,
            step_count=self._step_count,
            latest_rotor_speed_rpm=self._state.rotor_speed_rpm,
            latest_exhaust_temperature_c=(
                self._state.exhaust_temperature_c
            ),
            latest_thrust_n=self._latest_outputs.estimated_thrust_n,
            pathsim=PathSimPlantDiagnostics(
                pathsim_version=self._adapter.pathsim_version,
                solver_id=self.configuration.solver.solver_id,
                solver_mode="fixed explicit",
                fixed_step_s=self._effective_fixed_step_s(),
                internal_substep_count=(
                    self._latest_internal_substeps
                    or self.configuration.solver.internal_substep_count
                ),
                effective_fuel=integrated_state.effective_fuel,
                normalized_speed=integrated_state.normalized_speed,
                gas_temperature_c=integrated_state.gas_temperature_c,
                combustion_effectiveness=(
                    self._latest_terms.combustion_effectiveness
                ),
                starter_torque=self._latest_terms.starter_torque,
                turbine_torque=self._latest_terms.turbine_torque,
                compressor_load=self._latest_terms.compressor_load,
                friction_load=self._latest_terms.friction_load,
                equilibrium_temperature_c=(
                    self._latest_terms.equilibrium_temperature_c
                ),
                latest_integration_success=self._latest_step_success,
                latest_solver_error_indicator=self._latest_error_indicator,
                solver_step_count=self._adapter.solver_step_count,
                total_solver_evaluations=(
                    self._adapter.total_solver_evaluations
                ),
                total_solver_iterations=(
                    self._adapter.total_solver_iterations
                ),
            ),
        )

    def get_metadata(self) -> dict[str, object]:
        """Return complete static configuration, assumptions, and limitations."""

        initial_state = self._initial_state(self._ambient)
        return {
            "plant_model_id": self.model_id,
            "plant_display_name": self.display_name,
            "plant_model_version": self.model_version,
            "configuration": asdict(self.configuration),
            "initial_conditions": asdict(initial_state),
            "pathsim_package_version": self._adapter.pathsim_version,
            "solver_configuration": asdict(self.configuration.solver),
            "solver_api": "Simulation.timestep(dt, adaptive=False)",
            "state_names": (
                "effective_fuel",
                "normalized_speed",
                "gas_temperature_c",
            ),
            "model_assumptions": (
                "All parameters are unvalidated development assumptions",
                "Single normalized spool with effective torque coefficients",
                "Combustion support depends only on plant inputs and states",
                "Ambient pressure applies only a bounded thrust correction",
            ),
            "model_limitations": (
                "Not a validated model of a specific turbine engine",
                "No compressor or turbine maps",
                "No surge, choking, chemistry, or multi-spool dynamics",
                "Fixed-step RK4 is not intended for stiff dynamics",
            ),
        }

    def _initial_state(
        self,
        ambient: AmbientConditions,
    ) -> GreyBoxStateVector:
        initial = self.configuration.initial_conditions
        return GreyBoxStateVector(
            effective_fuel=initial.effective_fuel,
            normalized_speed=initial.normalized_speed,
            gas_temperature_c=max(
                self.configuration.minimum_gas_temperature_c,
                ambient.temperature_c
                if initial.gas_temperature_c is None
                else initial.gas_temperature_c,
            ),
        )

    def _engine_state(self, state: GreyBoxStateVector) -> EngineState:
        return EngineState(
            rotor_speed_rpm=(
                state.normalized_speed
                * self.configuration.maximum_speed_rpm
            ),
            exhaust_temperature_c=state.gas_temperature_c,
        )

    def _effective_fixed_step_s(self) -> float:
        if self.configuration.solver.internal_step_s is not None:
            return self.configuration.solver.internal_step_s
        return self._latest_fixed_step_s

    @staticmethod
    def _zero_inputs(ambient: AmbientConditions) -> GreyBoxInputs:
        return GreyBoxInputs(
            fuel_command=0.0,
            starter_commanded=False,
            ignition_commanded=False,
            fuel_enabled=False,
            ambient_temperature_c=ambient.temperature_c,
            ambient_pressure_pa=ambient.pressure_pa,
        )
