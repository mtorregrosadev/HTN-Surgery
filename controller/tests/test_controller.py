import asyncio
import time
from typing import Any

from fastapi.testclient import TestClient

from scalpel_controller.app import SessionHub, create_app


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
                        "sequence": 0,
                        "timestampMs": 0,
                        "positionMm": {"x": 1, "y": 2, "z": 3},
                        "forceN": 1.0,
                        "contact": True,
                    }
                )
                assert hardware.receive_json()["tick"] == 1
                snapshot = vr.receive_json()
                assert snapshot["sessionId"] == "demo"
                assert snapshot["events"] == ["contact-start"]


def test_hardware_reconnect_rejects_stale_sequence_without_relabeling():
    posted_sequences = []

    class SequenceRecordingUpstream(FakeUpstream):
        async def request(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
            if path == "/v1/sessions/demo":
                return 200, {"lastSequence": 49}
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

            # Hardware reconnects and sends an old sample. The controller must
            # surface the ordering error instead of changing it to sequence 51.
            with client.websocket_connect("/v1/sessions/demo/hardware-stream") as hardware:
                hardware.send_json({"sessionId": "demo", "sequence": 1, "positionMm": {"x": 1, "y": 1, "z": 1}})
                error = hardware.receive_json()

    assert error["type"] == "error"
    assert error["status"] == 409
    assert "lastSequence=50" in error["detail"]
    assert posted_sequences == [50]


def test_http_sample_route_forwards_and_broadcasts_through_controller():
    sample = {
        "sessionId": "demo",
        "sequence": 0,
        "timestampMs": 0,
        "positionMm": {"x": 1, "y": 2, "z": 3},
        "forceN": 0.0,
        "contact": False,
    }

    with TestClient(create_app(FakeUpstream())) as client:
        with client.websocket_connect("/v1/sessions/demo/client-stream") as vr:
            response = client.post("/v1/sessions/demo/samples", json=sample)
            assert response.status_code == 200
            assert response.json()["sessionId"] == "demo"
            assert vr.receive_json()["sessionId"] == "demo"


def test_client_stream_accepts_sample_actions():
    sample = {
        "sessionId": "demo",
        "sequence": 0,
        "timestampMs": 0,
        "positionMm": {"x": 1, "y": 2, "z": 3},
        "forceN": 0.0,
        "contact": False,
    }

    with TestClient(create_app(FakeUpstream())) as client:
        with client.websocket_connect("/v1/sessions/demo/client-stream") as vr:
            vr.send_json({"type": "sample", "sample": sample})
            snapshot = vr.receive_json()
            assert snapshot["sessionId"] == "demo"


def test_broadcast_drops_slow_client_without_delaying_healthy_client():
    class FakeClient:
        def __init__(self, delay_s: float) -> None:
            self.delay_s = delay_s
            self.payloads: list[str] = []

        async def send_text(self, payload: str) -> None:
            await asyncio.sleep(self.delay_s)
            self.payloads.append(payload)

    fast = FakeClient(0)
    slow = FakeClient(0.1)
    hub = SessionHub(FakeUpstream(), client_send_timeout_s=0.01)
    hub.clients["demo"].update({fast, slow})

    started = time.monotonic()
    asyncio.run(hub.broadcast("demo", {"tick": 1}))
    elapsed = time.monotonic() - started

    assert elapsed < 0.08
    assert fast.payloads == ['{"tick": 1}']
    assert slow not in hub.clients["demo"]
