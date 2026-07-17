"""Exhaust-gas-temperature protection for the Mini-FADEC simulation."""

from dataclasses import dataclass

from simulation.core.types import ActuatorCommand, SensorData


@dataclass(frozen=True)
class ExhaustTemperatureLimiterParameters:
    """Configuration parameters of the exhaust-temperature limiter."""

    intervention_exhaust_temperature_c: float = 650.0
    maximum_exhaust_temperature_c: float = 680.0
    fuel_reduction_at_maximum_temperature: float = 0.6
    overtemperature_fuel_reduction_per_degree_c: float = 0.04
    minimum_fuel_command: float = 0.0
    maximum_fuel_command: float = 1.0


class ExhaustTemperatureLimiter:
    """Reduce requested fuel when exhaust temperature exceeds its limit."""

    def __init__(
        self,
        parameters: ExhaustTemperatureLimiterParameters | None = None,
    ) -> None:
        self.parameters = parameters or ExhaustTemperatureLimiterParameters()

    def apply(
        self,
        requested_command: ActuatorCommand,
        sensor_data: SensorData,
        time_step_s: float,
    ) -> ActuatorCommand:
        """Return a fuel command protected by the exhaust-temperature limit."""

        if time_step_s <= 0.0:
            raise ValueError("time_step_s must be greater than zero")

        fuel_reduction = self._calculate_fuel_reduction(
            sensor_data.exhaust_temperature_c
        )
        protected_fuel_command = requested_command.fuel_command - fuel_reduction
        protected_fuel_command = self._clamp(
            protected_fuel_command,
            minimum=self.parameters.minimum_fuel_command,
            maximum=self.parameters.maximum_fuel_command,
        )

        return ActuatorCommand(fuel_command=protected_fuel_command)

    def _calculate_fuel_reduction(self, exhaust_temperature_c: float) -> float:
        """Calculate progressive fuel reduction for the measured EGT."""

        if exhaust_temperature_c <= (
            self.parameters.intervention_exhaust_temperature_c
        ):
            return 0.0

        intervention_range_c = (
            self.parameters.maximum_exhaust_temperature_c
            - self.parameters.intervention_exhaust_temperature_c
        )
        temperature_above_intervention_c = (
            exhaust_temperature_c
            - self.parameters.intervention_exhaust_temperature_c
        )
        intervention_fraction = self._clamp(
            temperature_above_intervention_c / intervention_range_c,
            minimum=0.0,
            maximum=1.0,
        )
        fuel_reduction = (
            self.parameters.fuel_reduction_at_maximum_temperature
            * intervention_fraction
        )

        if exhaust_temperature_c > self.parameters.maximum_exhaust_temperature_c:
            overtemperature_c = (
                exhaust_temperature_c
                - self.parameters.maximum_exhaust_temperature_c
            )
            fuel_reduction += (
                self.parameters.overtemperature_fuel_reduction_per_degree_c
                * overtemperature_c
            )

        return fuel_reduction

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        """Limit a value to a closed interval."""

        return max(minimum, min(value, maximum))
