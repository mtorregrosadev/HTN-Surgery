from typing import Any
import time

from fastapi.testclient import TestClient

from scalpel_controller.app import create_app
from scalpel_controller.hardware import HardwareBridge
from scalpel_controller.tracking import TrackingBridge


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


class FailingOnceUpstream(FakeUpstream):
    def __init__(self) -> None:
        self.sample_calls = 0

    async def request(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        if path.endswith("/samples"):
            self.sample_calls += 1
            if self.sample_calls == 1:
                raise RuntimeError("simulation API unavailable")
        return await super().request(method, path, body)


class RecordingUpstream(FakeUpstream):
    def __init__(self) -> None:
        self.sample_bodies: list[dict[str, Any]] = []

    async def request(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        if path.endswith("/samples") and body is not None:
            self.sample_bodies.append(body)
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


def test_upstream_failure_returns_one_error_and_next_sample_continues():
    upstream = FailingOnceUpstream()
    hardware_bridge = HardwareBridge(port="mock")
    with TestClient(create_app(upstream, hardware=hardware_bridge)) as client:
        with client.websocket_connect("/v1/sessions/demo/client-stream") as vr:
            with client.websocket_connect("/v1/sessions/demo/hardware-stream") as hardware:
                sample = {
                    "sessionId": "demo",
                    "positionMm": {"x": 1, "y": 2, "z": 3},
                    "forceN": 1.0,
                    "contact": True,
                }
                hardware.send_json(sample)
                hardware_error = hardware.receive_json()
                vr_error = vr.receive_json()

                assert hardware_error == vr_error
                assert hardware_error["type"] == "error"
                assert hardware_error["status"] == 503
                assert hardware_error["detail"]["detail"] == (
                    "Controller could not reach the simulation API"
                )

                hardware.send_json(sample)
                snapshot = hardware.receive_json()
                assert snapshot["tick"] == 1
                assert vr.receive_json() == snapshot

    assert upstream.sample_calls == 2


def test_stale_optical_tracking_is_rejected_until_tracking_resumes():
    tracking = TrackingBridge()
    tracking.update_pose(
        x_mm=10.0,
        y_mm=-2.0,
        z_mm=15.0,
        source="camera-aruco",
        marker_id=0,
    )
    upstream = RecordingUpstream()
    hardware_bridge = HardwareBridge(port="mock")

    with TestClient(
        create_app(upstream, hardware=hardware_bridge, tracking=tracking)
    ) as client:
        with client.websocket_connect("/v1/sessions/demo/client-stream") as vr:
            with client.websocket_connect("/v1/sessions/demo/hardware-stream") as hardware:
                sample = {
                    "sessionId": "demo",
                    "positionMm": {"x": 999, "y": 999, "z": 999},
                    "forceN": 0.0,
                    "contact": False,
                }
                hardware.send_json(sample)
                first_snapshot = hardware.receive_json()
                assert first_snapshot["tool"]["positionMm"]["x"] == 10.0
                assert vr.receive_json() == first_snapshot

                with tracking._lock:
                    tracking._pose.last_seen_time = time.monotonic() - 2.0

                hardware.send_json(sample)
                stale_error = hardware.receive_json()
                assert vr.receive_json() == stale_error
                assert stale_error["type"] == "error"
                assert stale_error["status"] == 409
                assert stale_error["detail"]["detail"] == (
                    "Optical tracking is stale; waiting for a fresh pose"
                )
                assert len(upstream.sample_bodies) == 1

                tracking.update_pose(
                    x_mm=20.0,
                    y_mm=-3.0,
                    z_mm=25.0,
                    source="camera-aruco",
                    marker_id=0,
                )
                hardware.send_json(sample)
                resumed_snapshot = hardware.receive_json()
                assert resumed_snapshot["tool"]["positionMm"]["x"] == 20.0
                assert vr.receive_json() == resumed_snapshot

    assert len(upstream.sample_bodies) == 2
    assert upstream.sample_bodies[0]["positionMm"]["x"] == 10.0
    assert upstream.sample_bodies[1]["positionMm"]["x"] == 20.0
