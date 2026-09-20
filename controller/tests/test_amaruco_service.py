"""Tests for the AmarucoService and its controller endpoints."""
import base64

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from fastapi.testclient import TestClient  # noqa: E402

from scalpel_controller.amaruco_service import AmarucoService  # noqa: E402
from scalpel_controller.app import create_app  # noqa: E402


class FakeTrackingBridge:
    """Records update calls without threading or timing dependencies."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def update_pose(self, **kwargs) -> None:
        self.calls.append({"kind": "update_pose", **kwargs})

    def update_from_dict(self, data) -> None:
        self.calls.append({"kind": "update_from_dict", "data": data})


DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_ARUCO_MIP_36h12)


def render_frame(marker_id: int = 0, cell: int = 20) -> np.ndarray:
    side = 8 * cell
    base = cv2.aruco.generateImageMarker(DICT, marker_id, side)
    cells = base.reshape(8, cell, 8, cell).mean(axis=(1, 3))
    cell01 = (cells > 127).astype(np.uint8)
    interior = np.kron(cell01[1:-1, 1:-1] * 255, np.ones((cell, cell), dtype=np.uint8))
    square = np.zeros((side, side), dtype=np.uint8)
    square[cell:side - cell, cell:side - cell] = interior
    frame = np.full((side + 160, side + 160), 255, dtype=np.uint8)
    frame[80:80 + side, 80:80 + side] = square
    return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)


def make_service() -> AmarucoService:
    return AmarucoService(FakeTrackingBridge())


def test_process_frame_publishes_uncalibrated_pose() -> None:
    svc = make_service()
    frame = render_frame(0)
    result = svc.process_frame(frame, timestamp_ms=99)
    assert result["detections"], "printed-style marker not detected"
    assert result["detections"][0]["markerId"] == 0
    assert result["pose"]["calibrated"] is False
    kinds = [c["kind"] for c in svc._tracking.calls]
    assert "update_from_dict" in kinds


def test_calibrated_publish_uses_update_pose() -> None:
    svc = make_service()
    frame = render_frame(0, cell=10)
    h, w = frame.shape[:2]
    cal = {
        "calibrationId": "cal-1",
        "cameraMatrix": [[800.0, 0, w / 2], [0, 800.0, h / 2], [0, 0, 1]],
        "distCoeffs": [0, 0, 0, 0, 0],
        "imageWidth": w,
        "imageHeight": h,
        "markerSizeMm": 30.0,
    }
    assert svc.set_camera_calibration(cal)["accepted"] is True
    assert svc.set_workspace({
        "calibrated": True, "scaleMmPerPixel": 1.0,
        "originX": 0.0, "originY": 0.0, "originZ": 0.0,
    })["accepted"] is True
    result = svc.process_frame(frame, timestamp_ms=7)
    assert result["pose"]["calibrated"] is True
    call = [c for c in svc._tracking.calls if c["kind"] == "update_pose"][-1]
    assert call["source"] == "camera-amaruco"
    assert abs(call["z_mm"]) < 400  # plausible metric depth from the fixture


def test_workspace_requires_camera_calibration_first() -> None:
    svc = make_service()
    result = svc.set_workspace({"calibrated": True})
    assert result["accepted"] is False
    assert "intrinsics" in result["error"]


def test_bad_calibration_rejected() -> None:
    svc = make_service()
    assert svc.set_camera_calibration({"calibrationId": "x"})["accepted"] is False
    assert svc.set_camera_calibration({
        "calibrationId": "x",
        "cameraMatrix": [[800, 0, 320], [0, 800, 240], [0, 0, 1]],
        "distCoeffs": [0, 0, 0, 0, 0],
    })["accepted"] is True


def test_status_reports_idle_service() -> None:
    svc = make_service()
    status = svc.status()
    assert status["running"] is False
    assert status["cameraCalibrationId"] is None
    assert status["workspaceCalibrated"] is False


def test_frame_stream_websocket_roundtrip() -> None:
    app = create_app(amaruco=make_service())
    frame = render_frame(0)
    ok, buf = cv2.imencode(".jpg", frame)
    assert ok
    payload = base64.b64encode(buf.tobytes()).decode("ascii")
    with TestClient(app) as client:
        with client.websocket_connect("/v1/tracking/amaruco/stream") as ws:
            ws.send_json({"type": "frame", "dataBase64": payload, "timestampMs": 5})
            reply = ws.receive_json()
            assert reply["type"] == "detections"
            assert reply["detections"][0]["markerId"] == 0
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}


def test_amaruco_status_endpoint() -> None:
    app = create_app(amaruco=make_service())
    with TestClient(app) as client:
        response = client.get("/v1/tracking/amaruco/status")
        assert response.status_code == 200
        body = response.json()
        assert body["running"] is False
        assert "dictionaries" in body
