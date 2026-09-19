from typing import Any

from fastapi.testclient import TestClient

from scalpel_controller.app import create_app


class FakeUpstream:
    async def start(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def request(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        if path == "/health":
            return 200, {"status": "ok"}
        if path.endswith("/samples"):
            return 200, {
                "contractVersion": "1.0",
                "sessionId": body["sessionId"],
                "tick": 1,
                "simulationTimeMs": 10,
                "tool": {
                    "positionMm": body["positionMm"],
                    "orientation": {"qx": 0, "qy": 0, "qz": 0, "qw": 1},
                    "forceN": body["forceN"],
                    "contact": body["contact"],
                },
                "tissue": {"deformationMm": 1.5},
                "deformableMeshes": [],
                "events": ["contact-start"],
            }
        return 201, body


class RejectingUpstream(FakeUpstream):
    async def request(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        if path.endswith("/samples"):
            return 409, {"detail": "Tool source is unhealthy or tracking is invalid"}
        return await super().request(method, path, body)


def test_hardware_snapshot_reaches_vr_client():
    with TestClient(create_app(FakeUpstream())) as client:
        with client.websocket_connect("/v1/sessions/demo/client-stream") as vr:
            with client.websocket_connect("/v1/sessions/demo/hardware-stream") as hardware:
                hardware.send_json(
                    {
                        "sessionId": "demo",
                        "positionMm": {"x": 1, "y": 2, "z": 3},
                        "forceN": 1.0,
                        "contact": True,
                    }
                )
                assert hardware.receive_json()["tick"] == 1
                snapshot = vr.receive_json()
                assert snapshot["sessionId"] == "demo"
                assert snapshot["events"] == ["contact-start"]


def test_hardware_rejection_reaches_hardware_and_vr_without_snapshot():
    with TestClient(create_app(RejectingUpstream())) as client:
        with client.websocket_connect("/v1/sessions/demo/client-stream") as vr:
            with client.websocket_connect("/v1/sessions/demo/hardware-stream") as hardware:
                hardware.send_json(
                    {
                        "sessionId": "demo",
                        "positionMm": {"x": 1, "y": 2, "z": 3},
                        "forceN": 1.0,
                        "contact": True,
                        "sourceHealthy": False,
                    }
                )
                hardware_error = hardware.receive_json()
                vr_error = vr.receive_json()

    assert hardware_error == vr_error
    assert hardware_error["type"] == "error"
    assert hardware_error["sessionId"] == "demo"
    assert hardware_error["status"] == 409
    assert hardware_error["detail"]["detail"] == (
        "Tool source is unhealthy or tracking is invalid"
    )
    assert "tick" not in vr_error
