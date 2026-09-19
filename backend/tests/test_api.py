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
                "toolId": "scalpel",
                "deviceId": "esp32-1",
            },
        ).json()
        with client.websocket_connect(f"/v1/sessions/{session['sessionId']}/stream") as socket:
            socket.send_json(
                {
                    "contractVersion": "1.1",
                    "sessionId": session["sessionId"],
                    "toolId": "scalpel",
                    "deviceId": "esp32-1",
                    "calibrationId": calibration["calibrationId"],
                    "sequence": 1,
                    "timestampMs": 10,
                    "positionMm": {"x": 0, "y": -1.2, "z": 0},
                    "orientation": {"qx": 0, "qy": 0, "qz": 0, "qw": 1},
                    "forceN": 0,
                    "contact": False,
                    "inputMode": "pose-only",
                    "forceMeasurementValid": False,
                }
            )
            snapshot = socket.receive_json()

        assert snapshot["sessionId"] == session["sessionId"]
        assert snapshot["tick"] == 1
        assert snapshot["simulationBackend"] == "memory-development-only"
        assert snapshot["tool"]["contact"] is True
        assert snapshot["tool"]["reactionForceN"] > 0
        assert snapshot["events"][0] == "first-contact"
        assert snapshot["deformableMeshes"][0]["objectId"] == "layer-skin"
        assert snapshot["tissue"]["activeLayer"] == "skin"


def test_health_names_memory_adapter_explicitly():
    app = create_app(MemoryStore(), MemorySimulator())
    with TestClient(app) as client:
        health = client.get("/health").json()
        assert health["simulation"] == "memory-development-only"
