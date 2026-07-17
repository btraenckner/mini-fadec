"""Engine operating states used by the Mini-FADEC simulation."""

from enum import Enum


class EngineOperatingState(Enum):
    """Discrete operating states of the engine."""

    OFF = "OFF"
    CRANKING = "CRANKING"
    IGNITION = "IGNITION"
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    SHUTDOWN = "SHUTDOWN"
    FAULT = "FAULT"
