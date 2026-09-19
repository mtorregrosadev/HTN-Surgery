from typing import Any
import time

from fastapi.testclient import TestClient

from scalpel_controller.app import create_app
from scalpel_controller.hardware import HardwareBridge
from scalpel_controller.tracking import TrackingBridge, compute_quaternion_from_angle


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
                "contractVersion": "1.1",
                "sessionId": body["sessionId"],
                "tick": 100,
                "simulationTimeMs": 1000,
                "tool": {
                    "positionMm": body["positionMm"],
                    "orientation": body.get("orientation", {"qx": 0, "qy": 0, "qz": 0, "qw": 1}),
                    "forceN": body["forceN"],
                    "contact": body["contact"],
                },
                "tissue": {"deformationMm": body["forceN"] * 0.8},
                "deformableMeshes": [],
                "events": ["contact-engaged"] if body["contact"] else [],
            }
        return 201, body


def test_tracking_bridge_pose_update():
    bridge = TrackingBridge()
    assert not bridge.is_active()

    bridge.update_pose(
        x_mm=25.5,
        y_mm=2.0,
        z_mm=-10.0,
        angle_deg=30.0,
        source="camera-aruco",
        marker_id=0,
        confidence=0.98,
    )
    assert bridge.is_active()
    pose = bridge.telemetry
    assert pose.x_mm == 25.5
    assert pose.y_mm == 2.0
    assert pose.z_mm == -10.0
    assert pose.angle_deg == 30.0
    assert pose.source == "camera-aruco"
    assert pose.marker_id == 0
    assert pose.confidence == 0.98
    assert pose.sequence == 1


def test_tracking_bridge_update_from_pixel_dict():
    bridge = TrackingBridge()
    # 480x360 image, center is (240, 180)
    # Point at (320, 90): right of center (+X), above center (-Z)
    bridge.update_from_dict({
        "pixelX": 320,
        "pixelY": 90,
        "width": 480,
        "height": 360,
        "zPercent": 10.0,
        "angleDeg": 45.0,
        "source": "purple-scalpel",
    })
    pose = bridge.telemetry
    assert bridge.is_active()
    assert pose.x_mm == (320 - 240) * (300.0 / 480.0)  # +50.0 mm
    assert pose.z_mm == (90 - 180) * (380.0 / 360.0)   # -95.0 mm
    assert pose.y_mm == 12.0 - (10.0 * 0.25)           # +9.5 mm
    assert pose.source == "purple-scalpel"


def test_tracking_endpoints():
    tracking = TrackingBridge()
    app = create_app(FakeUpstream(), tracking=tracking)
    with TestClient(app) as client:
        # Check initial status
        status = client.get("/v1/tracking/status")
        assert status.status_code == 200
        assert status.json()["active"] is False

        # Post a pose
        post_resp = client.post(
            "/v1/tracking/pose",
            json={
                "positionMm": {"x": 15.0, "y": -1.5, "z": 20.0},
                "source": "camera-aruco",
                "markerId": 0,
            },
        )
        assert post_resp.status_code == 200
        assert post_resp.json()["active"] is True

        # Check updated status
        status2 = client.get("/v1/tracking/status")
        assert status2.status_code == 200
        data = status2.json()
        assert data["active"] is True
        assert data["positionMm"]["x"] == 15.0
        assert data["positionMm"]["y"] == -1.5
        assert data["positionMm"]["z"] == 20.0
        assert data["markerId"] == 0

        # Health includes tracking
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["tracking"]["active"] is True


def test_tracking_stream_websocket():
    tracking = TrackingBridge()
    hardware = HardwareBridge(port="mock")
    hardware.set_mock_telemetry(force_n=1.5, is_contact=True)

    app = create_app(FakeUpstream(), hardware=hardware, tracking=tracking)
    with TestClient(app) as client:
        with client.websocket_connect("/v1/tracking/stream") as ws:
            ws.send_json({
                "type": "pose",
                "positionMm": {"x": -30.0, "y": 5.0, "z": 10.0},
                "angleDeg": 15.0,
                "source": "camera-aruco",
                "markerId": 0,
            })
            ack = ws.receive_json()
            assert ack["type"] == "ack"
            assert ack["trackingActive"] is True
            assert ack["hardware"]["forceN"] == 1.5
            assert ack["hardware"]["contact"] is True

    assert tracking.is_active()
    assert tracking.telemetry.x_mm == -30.0


def test_fusion_camera_position_and_hardware_force():
    tracking = TrackingBridge()
    tracking.update_pose(
        x_mm=42.0,
        y_mm=-2.0,
        z_mm=15.0,
        angle_deg=10.0,
        source="camera-aruco",
        marker_id=0,
    )

    hardware = HardwareBridge(port="mock")
    hardware.set_mock_telemetry(
        force_n=3.5,
        is_contact=True,
        raw_adc=2800,
        port="/dev/cu.usbtest",
        device_id="esp32-scalpel-01",
    )

    app = create_app(FakeUpstream(), hardware=hardware, tracking=tracking)
    with TestClient(app) as client:
        with client.websocket_connect("/v1/sessions/demo/hardware-stream") as stream_ws:
            # Send sample from Unity or client with dummy/default coordinates
            stream_ws.send_json({
                "sessionId": "demo",
                "positionMm": {"x": 0.0, "y": 12.0, "z": 0.0},
                "forceN": 0.0,
                "contact": False,
            })
            snapshot = stream_ws.receive_json()

            # Verify optical tracking position was fused
            tool = snapshot["tool"]
            assert tool["positionMm"]["x"] == 42.0
            assert tool["positionMm"]["y"] == -2.0
            assert tool["positionMm"]["z"] == 15.0

            # Verify physical ESP-32 FSR force was fused
            assert tool["forceN"] == 3.5
            assert tool["contact"] is True
            assert snapshot["tissue"]["deformationMm"] == 3.5 * 0.8
