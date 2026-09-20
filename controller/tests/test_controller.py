from typing import Any

import httpx
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


class RecoveringUpstream(FakeUpstream):
    def __init__(self) -> None:
        self.failed = False

    async def request(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        if path.endswith("/samples") and not self.failed:
            self.failed = True
            raise httpx.ReadTimeout("native solver was busy")
        return await super().request(method, path, body)


def test_hardware_stream_survives_a_temporary_sofa_timeout():
    with TestClient(create_app(RecoveringUpstream())) as client:
        with client.websocket_connect("/v1/sessions/demo/hardware-stream") as hardware:
            sample = {
                "sessionId": "demo",
                "positionMm": {"x": 1, "y": 2, "z": 3},
                "forceN": 0.0,
                "contact": False,
            }
            hardware.send_json(sample)
            error = hardware.receive_json()
            assert error["status"] == 503
            assert error["message"] == "SOFA API temporarily unavailable"

            hardware.send_json(sample)
            assert hardware.receive_json()["tick"] == 1
