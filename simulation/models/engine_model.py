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

    # Initial grey-box start assumptions; these values are not physically validated.
    stopped_exhaust_temperature_c: float = 15.0
    ignition_enable_speed_rpm: float = 15_000.0
    starter_disengagement_speed_rpm: float = 35_000.0
    minimum_light_off_fuel_command: float = 0.1
    starter_time_constant_s: float = 0.8
    spool_down_time_constant_s: float = 1.5

    idle_speed_rpm: float = 39_000.0
    maximum_speed_rpm: float = 128_000.0
    speed_time_constant_s: float = 1.0

    idle_exhaust_temperature_c: float = 450.0
    # Initial grey-box assumptions; these values are not physically validated.
    fuel_egt_heating_gain_c: float = 310.0
    speed_egt_cooling_gain_c: float = 110.0
    acceleration_egt_gain_c: float = 200.0
    exhaust_temperature_time_constant_s: float = 0.5

    idle_thrust_n: float = 6.0
    maximum_thrust_n: float = 140.0

    idle_fuel_flow_ml_min: float = 100.0
    maximum_fuel_flow_ml_min: float = 480.0


class FirstOrderEngineModel:
    """First-order grey-box model of a single-spool turbine."""

    def __init__(
        self,
        parameters: EngineModelParameters | None = None,
        *,
        initially_running: bool = False,
    ) -> None:
        self.parameters = parameters or EngineModelParameters()
        self._combustion_lit = initially_running

        self._state = EngineState(
            rotor_speed_rpm=(
                self.parameters.idle_speed_rpm if initially_running else 0.0
            ),
            exhaust_temperature_c=(
                self.parameters.idle_exhaust_temperature_c
                if initially_running
                else self.parameters.stopped_exhaust_temperature_c
            ),
        )

    @classmethod
    def running_at_idle(
        cls,
        parameters: EngineModelParameters | None = None,
    ) -> "FirstOrderEngineModel":
        """Create an engine initialized as already running at idle."""

        return cls(parameters=parameters, initially_running=True)

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

        if not actuator_command.fuel_enabled:
            self._combustion_lit = False
        elif (
            actuator_command.ignition_commanded
            and fuel_command >= self.parameters.minimum_light_off_fuel_command
            and self._state.rotor_speed_rpm
            >= self.parameters.ignition_enable_speed_rpm
        ):
            self._combustion_lit = True

        if self._combustion_lit and actuator_command.fuel_enabled:
            target_speed_rpm = self.parameters.idle_speed_rpm + fuel_command * (
                self.parameters.maximum_speed_rpm
                - self.parameters.idle_speed_rpm
            )
            speed_time_constant_s = self.parameters.speed_time_constant_s
        elif actuator_command.starter_commanded:
            target_speed_rpm = self.parameters.starter_disengagement_speed_rpm
            speed_time_constant_s = self.parameters.starter_time_constant_s
        else:
            target_speed_rpm = 0.0
            speed_time_constant_s = self.parameters.spool_down_time_constant_s

        speed_derivative_rpm_s = (
            target_speed_rpm - self._state.rotor_speed_rpm
        ) / speed_time_constant_s

        self._state.rotor_speed_rpm += speed_derivative_rpm_s * time_step_s
        self._state.rotor_speed_rpm = max(self._state.rotor_speed_rpm, 0.0)

        if self._combustion_lit and actuator_command.fuel_enabled:
            normalized_speed = self._normalized_speed()
            excess_fuel_command = max(
                fuel_command - normalized_speed,
                0.0,
            )
            transient_heating_c = (
                self.parameters.acceleration_egt_gain_c * excess_fuel_command
            )
            target_exhaust_temperature_c = (
                self.parameters.idle_exhaust_temperature_c
                + self.parameters.fuel_egt_heating_gain_c * fuel_command
                - self.parameters.speed_egt_cooling_gain_c * normalized_speed
                + transient_heating_c
            )
        else:
            target_exhaust_temperature_c = (
                self.parameters.stopped_exhaust_temperature_c
            )

        exhaust_temperature_derivative_c_s = (
            target_exhaust_temperature_c - self._state.exhaust_temperature_c
        ) / self.parameters.exhaust_temperature_time_constant_s

        self._state.exhaust_temperature_c += (
            exhaust_temperature_derivative_c_s * time_step_s
        )

        # Ambient pressure and temperature effects are not yet modeled.
        _ = ambient_conditions

        return self._calculate_outputs(
            fuel_command=fuel_command,
            fuel_enabled=actuator_command.fuel_enabled,
        )

    def _calculate_outputs(
        self,
        fuel_command: float,
        fuel_enabled: bool,
    ) -> EngineOutputs:
        """Calculate algebraic engine outputs."""

        normalized_speed = self._normalized_speed()

        if self._combustion_lit and fuel_enabled:
            estimated_thrust_n = (
                self.parameters.idle_thrust_n
                + (
                    self.parameters.maximum_thrust_n
                    - self.parameters.idle_thrust_n
                )
                * normalized_speed**2
            )
        else:
            estimated_thrust_n = 0.0

        if fuel_enabled:
            estimated_fuel_flow_ml_min = (
                self.parameters.idle_fuel_flow_ml_min
                + fuel_command
                * (
                    self.parameters.maximum_fuel_flow_ml_min
                    - self.parameters.idle_fuel_flow_ml_min
                )
            )
        else:
            estimated_fuel_flow_ml_min = 0.0

        return EngineOutputs(
            estimated_thrust_n=estimated_thrust_n,
            estimated_fuel_flow_ml_min=estimated_fuel_flow_ml_min,
        )

    def _normalized_speed(self) -> float:
        """Return rotor speed normalized between idle and maximum speed."""

        normalized_speed = (
            self._state.rotor_speed_rpm - self.parameters.idle_speed_rpm
        ) / (self.parameters.maximum_speed_rpm - self.parameters.idle_speed_rpm)

        return self._clamp(
            normalized_speed,
            minimum=0.0,
            maximum=1.0,
        )

    @staticmethod
    def _clamp(
        value: float,
        minimum: float,
        maximum: float,
    ) -> float:
        """Limit a value to a closed interval."""

        return max(minimum, min(value, maximum))
