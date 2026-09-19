from fastapi.testclient import TestClient

from surge_prep.app import create_app
from surge_prep.simulation import MemorySimulator
from surge_prep.store import MemoryStore


IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def test_controller_websocket_receives_simulation_snapshot():
    app = create_app(MemoryStore(), MemorySimulator())
    with TestClient(app) as client:
        calibration = client.post(
            "/v1/calibrations",
            json={"deviceId": "esp32-1", "transform": IDENTITY, "rmsErrorMm": 0.5},
        ).json()
        session = client.post(
            "/v1/sessions",
            json={
                "exerciseId": "demo",
                "calibrationId": calibration["calibrationId"],
                "toolId": "stylus-1",
                "deviceId": "esp32-1",
            },
        ).json()
        with client.websocket_connect(f"/v1/sessions/{session['sessionId']}/stream") as socket:
            socket.send_json(
                {
                    "sessionId": session["sessionId"],
                    "toolId": "stylus-1",
                    "deviceId": "esp32-1",
                    "calibrationId": calibration["calibrationId"],
                    "sequence": 1,
                    "timestampMs": 10,
                    "positionMm": {"x": 0, "y": 10, "z": 0},
                    "orientation": {"qx": 0, "qy": 0, "qz": 0, "qw": 1},
                    "forceN": 1.2,
                    "contact": True,
                }
            )
            snapshot = socket.receive_json()

        assert snapshot["sessionId"] == session["sessionId"]
        assert snapshot["tick"] == 1
        assert snapshot["tool"]["forceN"] == 1.2

