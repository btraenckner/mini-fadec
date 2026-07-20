"""Conservative FADEC response policy for validated sensor health."""

from dataclasses import dataclass
from enum import Enum

from simulation.operation.engine_state import EngineOperatingState
from simulation.validation.sensor_validation import (
    ChannelHealth,
    SensorValidationResult,
)


class SensorFaultResponseReason(Enum):
    """Reason selected by the critical sensor fault-response policy."""

    NONE = "none"
    ROTOR_SPEED_INVALID = "rotor-speed sensor invalid"
    EGT_INVALID = "EGT sensor invalid"
    EGT_SUSPECT = "EGT sensor suspect"


@dataclass(frozen=True)
class SensorFaultResponse:
    """Explicit response request produced from validation health."""

    automatic_fault_requested: bool
    fuel_cutoff_required: bool
    warning_active: bool
    reason: SensorFaultResponseReason


class SensorFaultResponsePolicy:
    """Map sensor health to safe state-machine and actuator requests."""

    def evaluate(
        self,
        operating_state: EngineOperatingState,
        validation_result: SensorValidationResult,
    ) -> SensorFaultResponse:
        """Return the configured response without changing operating state."""

        rotor_critical_states = {
            EngineOperatingState.CRANKING,
            EngineOperatingState.IGNITION,
            EngineOperatingState.IDLE,
            EngineOperatingState.RUNNING,
        }
        egt_critical_states = {
            EngineOperatingState.IGNITION,
            EngineOperatingState.IDLE,
            EngineOperatingState.RUNNING,
        }

        if (
            validation_result.rotor_speed.health is ChannelHealth.INVALID
            and operating_state in rotor_critical_states
        ):
            return SensorFaultResponse(
                automatic_fault_requested=True,
                fuel_cutoff_required=True,
                warning_active=True,
                reason=SensorFaultResponseReason.ROTOR_SPEED_INVALID,
            )

        if (
            validation_result.exhaust_temperature.health
            is ChannelHealth.INVALID
            and operating_state in egt_critical_states
        ):
            return SensorFaultResponse(
                automatic_fault_requested=True,
                fuel_cutoff_required=True,
                warning_active=True,
                reason=SensorFaultResponseReason.EGT_INVALID,
            )

        if (
            validation_result.exhaust_temperature.health
            is ChannelHealth.SUSPECT
        ):
            return SensorFaultResponse(
                automatic_fault_requested=False,
                fuel_cutoff_required=False,
                warning_active=True,
                reason=SensorFaultResponseReason.EGT_SUSPECT,
            )

        return SensorFaultResponse(
            automatic_fault_requested=False,
            fuel_cutoff_required=False,
            warning_active=(
                validation_result.aggregate_health is not ChannelHealth.VALID
            ),
            reason=SensorFaultResponseReason.NONE,
        )
