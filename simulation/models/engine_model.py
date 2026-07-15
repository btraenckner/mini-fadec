"""Simplified dynamic engine model for the Mini-FADEC simulation."""

from dataclasses import dataclass

from simulation.core.types import (
    ActuatorCommand,
    AmbientConditions,
    EngineOutputs,
    EngineState,
)


@dataclass(frozen=True)
class EngineModelParameters:
    """Configuration parameters of the simplified engine model."""

    idle_speed_rpm: float = 39_000.0
    maximum_speed_rpm: float = 128_000.0
    speed_time_constant_s: float = 1.0

    idle_exhaust_temperature_c: float = 450.0
    maximum_exhaust_temperature_c: float = 720.0
    exhaust_temperature_time_constant_s: float = 0.5

    idle_thrust_n: float = 6.0
    maximum_thrust_n: float = 140.0

    idle_fuel_flow_ml_min: float = 100.0
    maximum_fuel_flow_ml_min: float = 480.0


class FirstOrderEngineModel:
    """First-order grey-box model of a running single-spool turbine."""

    def __init__(
        self,
        parameters: EngineModelParameters | None = None,
    ) -> None:
        self.parameters = parameters or EngineModelParameters()

        self._state = EngineState(
            rotor_speed_rpm=self.parameters.idle_speed_rpm,
            exhaust_temperature_c=(self.parameters.idle_exhaust_temperature_c),
        )

    @property
    def state(self) -> EngineState:
        """Return the current internal engine state."""

        return self._state

    def step(
        self,
        actuator_command: ActuatorCommand,
        ambient_conditions: AmbientConditions,
        time_step_s: float,
    ) -> EngineOutputs:
        """Advance the engine model by one simulation step."""

        if time_step_s <= 0.0:
            raise ValueError("time_step_s must be greater than zero")

        fuel_command = self._clamp(
            actuator_command.fuel_command,
            minimum=0.0,
            maximum=1.0,
        )

        target_speed_rpm = self.parameters.idle_speed_rpm + fuel_command * (
            self.parameters.maximum_speed_rpm - self.parameters.idle_speed_rpm
        )

        speed_derivative_rpm_s = (
            target_speed_rpm - self._state.rotor_speed_rpm
        ) / self.parameters.speed_time_constant_s

        self._state.rotor_speed_rpm += speed_derivative_rpm_s * time_step_s

        target_exhaust_temperature_c = (
            self.parameters.idle_exhaust_temperature_c
            + fuel_command
            * (
                self.parameters.maximum_exhaust_temperature_c
                - self.parameters.idle_exhaust_temperature_c
            )
        )

        exhaust_temperature_derivative_c_s = (
            target_exhaust_temperature_c - self._state.exhaust_temperature_c
        ) / self.parameters.exhaust_temperature_time_constant_s

        self._state.exhaust_temperature_c += (
            exhaust_temperature_derivative_c_s * time_step_s
        )

        # Ambient conditions are not yet used by the first model version.
        _ = ambient_conditions

        return self._calculate_outputs(fuel_command)

    def _calculate_outputs(
        self,
        fuel_command: float,
    ) -> EngineOutputs:
        """Calculate algebraic engine outputs."""

        normalized_speed = (
            self._state.rotor_speed_rpm - self.parameters.idle_speed_rpm
        ) / (self.parameters.maximum_speed_rpm - self.parameters.idle_speed_rpm)

        normalized_speed = self._clamp(
            normalized_speed,
            minimum=0.0,
            maximum=1.0,
        )

        estimated_thrust_n = (
            self.parameters.idle_thrust_n
            + (self.parameters.maximum_thrust_n - self.parameters.idle_thrust_n)
            * normalized_speed**2
        )

        estimated_fuel_flow_ml_min = (
            self.parameters.idle_fuel_flow_ml_min
            + fuel_command
            * (
                self.parameters.maximum_fuel_flow_ml_min
                - self.parameters.idle_fuel_flow_ml_min
            )
        )

        return EngineOutputs(
            estimated_thrust_n=estimated_thrust_n,
            estimated_fuel_flow_ml_min=estimated_fuel_flow_ml_min,
        )

    @staticmethod
    def _clamp(
        value: float,
        minimum: float,
        maximum: float,
    ) -> float:
        """Limit a value to a closed interval."""

        return max(minimum, min(value, maximum))
