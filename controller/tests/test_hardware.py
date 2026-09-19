from typing import Any
import time

from fastapi.testclient import TestClient

from scalpel_controller.app import create_app
from scalpel_controller.hardware import HardwareBridge, HardwareTelemetry


class FakeUpstream:
    def __init__(self) -> None:
        self.sample_bodies: list[dict[str, Any]] = []

    async def start(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def request(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        if path == "/health":
            return 200, {"status": "ok"}
        if path.endswith("/samples"):
            self.sample_bodies.append(dict(body))
            return 200, {
                "contractVersion": "1.1",
                "sessionId": body["sessionId"],
                "tick": 42,
                "simulationTimeMs": 420,
                "tool": {
                    "positionMm": body["positionMm"],
                    "orientation": {"qx": 0, "qy": 0, "qz": 0, "qw": 1},
                    "forceN": body["forceN"],
                    "contact": body["contact"],
                },
                "tissue": {"deformationMm": body["forceN"] * 0.8},
                "deformableMeshes": [],
                "events": ["contact-engaged"] if body["contact"] else [],
            }
        return 201, body


def test_hardware_telemetry_parsing():
    bridge = HardwareBridge()
    # Test JSON telemetry parsing
    line = '{"type":"pressure","forceN":2.45,"contact":true,"raw":2340,"timestampMs":12345,"seq":10}'
    bridge._parse_line(line)
    telemetry = bridge.telemetry
    assert telemetry.force_n == 2.45
    assert telemetry.is_contact is True
    assert telemetry.raw_adc == 2340
    assert telemetry.timestamp_ms == 12345

    # Test FSR text parsing fallback
    line2 = "[FSR]  1.80 N  [====------]  (raw: 1980 | delta: +120)"
    bridge._parse_line(line2)
    telemetry2 = bridge.telemetry
    assert telemetry2.force_n == 1.80
    assert telemetry2.is_contact is True
    assert telemetry2.raw_adc == 1980


def test_hardware_endpoints():
    bridge = HardwareBridge(port="mock")
    bridge.set_mock_telemetry(force_n=3.21, is_contact=True, raw_adc=2650, port="/dev/cu.usbtest")

    app = create_app(FakeUpstream(), bridge)
    with TestClient(app) as client:
        status = client.get("/v1/hardware/status")
        assert status.status_code == 200
        data = status.json()
        assert data["connected"] is True
        assert data["port"] == "/dev/cu.usbtest"
        assert data["forceN"] == 3.21
        assert data["contact"] is True
        assert data["rawAdc"] == 2650

        # Health includes hardware
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["hardware"]["connected"] is True


def test_physical_scalpel_stream_merges_hardware_force():
    bridge = HardwareBridge(port="mock")
    bridge.set_mock_telemetry(
        force_n=2.75,
        is_contact=True,
        raw_adc=2450,
        port="/dev/cu.usbtest",
        device_id="esp32-scalpel-01",
    )

    app = create_app(FakeUpstream(), bridge)
    with TestClient(app) as client:
        with client.websocket_connect("/v1/sessions/demo/hardware-stream") as hardware_ws:
            # Send sample with 0 force from software
            hardware_ws.send_json(
                {
                    "sessionId": "demo",
                    "positionMm": {"x": 0, "y": 0, "z": 0},
                    "forceN": 0.0,
                    "contact": False,
                }
            )
            response = hardware_ws.receive_json()
            # Verify the physical hardware force was merged
            assert response["tool"]["forceN"] == 2.75
            assert response["tool"]["contact"] is True
            assert response["tissue"]["deformationMm"] == 2.75 * 0.8


def test_physical_scalpel_stream_preserves_session_device_id():
    bridge = HardwareBridge(port="mock")
    bridge.set_mock_telemetry(
        force_n=2.75,
        is_contact=True,
        raw_adc=2450,
        port="/dev/cu.usbtest",
        device_id="esp32-scalpel-01",
    )
    upstream = FakeUpstream()

    app = create_app(upstream, bridge)
    with TestClient(app) as client:
        with client.websocket_connect("/v1/sessions/demo/hardware-stream") as hardware_ws:
            hardware_ws.send_json(
                {
                    "sessionId": "demo",
                    "deviceId": "unity-manual-demo",
                    "positionMm": {"x": 0, "y": 0, "z": 0},
                    "forceN": 0.0,
                    "contact": False,
                }
            )
            hardware_ws.receive_json()

    forwarded_sample = upstream.sample_bodies[-1]
    assert forwarded_sample["deviceId"] == "unity-manual-demo"
    assert forwarded_sample["forceN"] == 2.75
