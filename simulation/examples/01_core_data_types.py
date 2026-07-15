"""Simple executable check for the core Mini-FADEC data types."""

from simulation.core.types import (
    ActuatorCommand,
    AmbientConditions,
    ControlRequest,
    EngineOutputs,
    EngineState,
    SensorData,
)


def main() -> None:
    ambient_conditions = AmbientConditions()

    engine_state = EngineState(
        rotor_speed_rpm=39_000.0,
        exhaust_temperature_c=450.0,
    )

    sensor_data = SensorData(
        rotor_speed_rpm=engine_state.rotor_speed_rpm,
        exhaust_temperature_c=engine_state.exhaust_temperature_c,
    )

    control_request = ControlRequest(throttle_command=0.5)
    actuator_command = ActuatorCommand(fuel_command=0.3)

    engine_outputs = EngineOutputs(
        estimated_thrust_n=6.0,
        estimated_fuel_flow_ml_min=120.0,
    )

    print("Ambient conditions:", ambient_conditions)
    print("Engine state:", engine_state)
    print("Sensor data:", sensor_data)
    print("Control request:", control_request)
    print("Actuator command:", actuator_command)
    print("Engine outputs:", engine_outputs)


if __name__ == "__main__":
    main()
