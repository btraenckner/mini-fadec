"""Rotor-speed scheduling and control for the Mini-FADEC simulation."""

from dataclasses import dataclass

from simulation.core.types import ActuatorCommand, ControlRequest, SensorData


@dataclass(frozen=True)
class LinearThrottleToSpeedScheduler:
    """Map a normalized throttle command to a rotor-speed setpoint."""

    idle_speed_rpm: float = 39_000.0
    maximum_speed_rpm: float = 128_000.0

    def get_speed_setpoint_rpm(self, throttle_command: float) -> float:
        """Return the rotor-speed setpoint for a throttle command."""

        clamped_throttle_command = self._clamp(
            throttle_command,
            minimum=0.0,
            maximum=1.0,
        )

        return self.idle_speed_rpm + clamped_throttle_command * (
            self.maximum_speed_rpm - self.idle_speed_rpm
        )

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        """Limit a value to a closed interval."""

        return max(minimum, min(value, maximum))


@dataclass(frozen=True)
class SpeedControllerParameters:
    """Configuration parameters of the PI rotor-speed controller."""

    proportional_gain: float = 3.4e-5
    integral_gain: float = 4.5e-5
    minimum_fuel_command: float = 0.0
    maximum_fuel_command: float = 1.0


class PIEngineSpeedController:
    """PI rotor-speed controller with scheduled fuel feedforward."""

    def __init__(
        self,
        scheduler: LinearThrottleToSpeedScheduler | None = None,
        parameters: SpeedControllerParameters | None = None,
    ) -> None:
        self.scheduler = scheduler or LinearThrottleToSpeedScheduler()
        self.parameters = parameters or SpeedControllerParameters()
        self._integral_error = 0.0

    def update(
        self,
        control_request: ControlRequest,
        sensor_data: SensorData,
        time_step_s: float,
    ) -> ActuatorCommand:
        """Calculate the fuel command for one control cycle."""

        if time_step_s <= 0.0:
            raise ValueError("time_step_s must be greater than zero")

        speed_setpoint_rpm = self.scheduler.get_speed_setpoint_rpm(
            control_request.throttle_command
        )
        speed_error_rpm = speed_setpoint_rpm - sensor_data.rotor_speed_rpm

        feedforward = (
            speed_setpoint_rpm - self.scheduler.idle_speed_rpm
        ) / (
            self.scheduler.maximum_speed_rpm - self.scheduler.idle_speed_rpm
        )

        unsaturated_fuel_command = self._calculate_unsaturated_command(
            feedforward=feedforward,
            speed_error_rpm=speed_error_rpm,
        )
        fuel_command = self._clamp_fuel_command(unsaturated_fuel_command)

        output_is_saturated_high = (
            unsaturated_fuel_command >= self.parameters.maximum_fuel_command
        )
        output_is_saturated_low = (
            unsaturated_fuel_command <= self.parameters.minimum_fuel_command
        )
        integration_drives_saturation = (
            output_is_saturated_high and speed_error_rpm > 0.0
        ) or (output_is_saturated_low and speed_error_rpm < 0.0)

        if not integration_drives_saturation:
            self._integral_error -= speed_error_rpm * time_step_s
            unsaturated_fuel_command = self._calculate_unsaturated_command(
                feedforward=feedforward,
                speed_error_rpm=speed_error_rpm,
            )
            fuel_command = self._clamp_fuel_command(unsaturated_fuel_command)

        return ActuatorCommand(fuel_command=fuel_command)

    def _calculate_unsaturated_command(
        self,
        feedforward: float,
        speed_error_rpm: float,
    ) -> float:
        """Calculate feedforward plus PI feedback before saturation."""

        correction = (
            self.parameters.proportional_gain * speed_error_rpm
            - self.parameters.integral_gain * self._integral_error
        )

        return feedforward + correction

    def _clamp_fuel_command(self, fuel_command: float) -> float:
        """Limit the fuel command to the configured actuator range."""

        return max(
            self.parameters.minimum_fuel_command,
            min(fuel_command, self.parameters.maximum_fuel_command),
        )
