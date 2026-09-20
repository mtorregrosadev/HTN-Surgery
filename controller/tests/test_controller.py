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


def test_hardware_reconnect_monotonic_sequence():
    posted_sequences = []

    class SequenceRecordingUpstream(FakeUpstream):
        async def request(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
            if path.endswith("/samples"):
                posted_sequences.append(body.get("sequence"))
                return 200, {
                    "contractVersion": "1.0",
                    "sessionId": body["sessionId"],
                    "tick": len(posted_sequences),
                    "tool": {
                        "positionMm": body["positionMm"],
                        "forceN": 0.0,
                        "contact": False,
                    },
                }
            return await super().request(method, path, body)

    with TestClient(create_app(SequenceRecordingUpstream())) as client:
        with client.websocket_connect("/v1/sessions/demo/client-stream") as vr:
            with client.websocket_connect("/v1/sessions/demo/hardware-stream") as hardware:
                hardware.send_json({"sessionId": "demo", "sequence": 50, "positionMm": {"x": 0, "y": 0, "z": 0}})
                _ = hardware.receive_json()
                _ = vr.receive_json()

            # Hardware reconnects and resets sequence counter to 1
            with client.websocket_connect("/v1/sessions/demo/hardware-stream") as hardware:
                hardware.send_json({"sessionId": "demo", "sequence": 1, "positionMm": {"x": 1, "y": 1, "z": 1}})
                _ = hardware.receive_json()
                _ = vr.receive_json()

    # The controller must have advanced sequence monotonically from 50 to 51
    assert posted_sequences == [50, 51]

