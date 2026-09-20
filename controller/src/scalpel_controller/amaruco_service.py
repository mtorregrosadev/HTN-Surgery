"""Camera service that owns the native AmarUco detection loop for the controller.

Responsibilities (controller boundary):
- Own the OpenCV VideoCapture device connection.
- Run detection per frame with the native AmarucoDetector.
- Hold session-bound camera calibration (intrinsics + workspace scale).
- Publish pose updates into the TrackingBridge using calibrated metric pose
  when available, image-relative pose otherwise, with honest flags.

It never touches MongoDB, the API database, or SOFA directly; pose flows into
the existing tracking bridge and follows the normal controller -> API path.
"""
from __future__ import annotations

import math
import threading
import time
from typing import Any, Optional

import numpy as np

from scalpel_controller.amaruco import (
    CV2_AVAILABLE,
    CameraCalibration,
    Detection,
    AmarucoDetector,
    frame_to_pose_update,
)

# Pixels below which a detection cannot drive calibrated pose.
MIN_CALIBRATED_SIDE_PX = 35.0


class AmarucoService:
    """Controller-owned detection service with a background camera loop."""

    def __init__(self, tracking_bridge: Any = None) -> None:
        self._tracking = tracking_bridge
        self._lock = threading.Lock()
        self._detector: Optional[AmarucoDetector] = None
        self._calibration: Optional[CameraCalibration] = None
        self._workspace: dict[str, Any] = {}
        self._capture: Any = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._running = False
        self._camera_index = 0
        self._last_detections: list[dict[str, Any]] = []
        self._last_frame_ts = 0.0
        self._fps = 0.0
        self._error: Optional[str] = None

    # -- lifecycle -------------------------------------------------------------
    def start(self, camera_index: int = 0, dictionaries: Optional[list[str]] = None) -> dict[str, Any]:
        if not CV2_AVAILABLE:
            return {"started": False, "error": "OpenCV (cv2) not installed"}
        with self._lock:
            if self._running:
                return {"started": True, "alreadyRunning": True}
            self._stop.clear()
            self._camera_index = camera_index
            try:
                self._capture = cv2.VideoCapture(camera_index)
                if not self._capture.isOpened():
                    self._capture.release()
                    self._capture = None
                    return {"started": False, "error": f"camera {camera_index} unavailable"}
            except Exception as exc:  # pragma: no cover - device dependent
                self._capture = None
                return {"started": False, "error": f"camera open failed: {exc}"}
            self._detector = AmarucoDetector(dictionaries=dictionaries)
            self._running = True
            self._thread = threading.Thread(target=self._loop, daemon=True, name="amaruco-loop")
            self._thread.start()
            return {"started": True, "cameraIndex": camera_index}

    def stop(self) -> None:
        with self._lock:
            self._running = False
            self._stop.set()
            if self._thread is not None:
                self._thread.join(timeout=2.0)
                self._thread = None
            if self._capture is not None:
                self._capture.release()
                self._capture = None

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    # -- calibration -------------------------------------------------------------
    def set_camera_calibration(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            cal = CameraCalibration.from_dict(payload)
        except (KeyError, TypeError, ValueError) as exc:
            return {"accepted": False, "error": f"invalid calibration payload: {exc}"}
        with self._lock:
            self._calibration = cal
            if self._detector is not None:
                self._detector.calibration = cal
        return {"accepted": True, "calibrationId": cal.calibration_id}

    def set_workspace(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Register the camera->exercise workspace transform.

        Required fields: calibrated flag and per-axis mm scale from the
        calibrated PnP frame to the exercise frame. Rejected when no camera
        calibration exists yet, mirroring the plan's validation gates.
        """
        with self._lock:
            if self._calibration is None:
                return {"accepted": False, "error": "set camera intrinsics first"}
        if not isinstance(payload.get("calibrated"), bool):
            return {"accepted": False, "error": "calibrated flag required"}
        for key in ("scaleMmPerPixel", "originX", "originY", "originZ"):
            if key in payload and not isinstance(payload[key], (int, float)):
                return {"accepted": False, "error": f"{key} must be numeric"}
        with self._lock:
            self._workspace = dict(payload)
        return {"accepted": True}

    def clear_calibration(self) -> None:
        with self._lock:
            self._calibration = None
            self._workspace = {}
            if self._detector is not None:
                self._detector.calibration = None

    # -- single-frame ingest (no camera: frames pushed from clients/tools) -----
    def process_frame(self, image: "np.ndarray", timestamp_ms: Optional[int] = None) -> dict[str, Any]:
        """Detect on one pushed frame; returns the pose payload sent to tracking."""
        with self._lock:
            detector = self._detector
            calibration = self._calibration
            workspace = dict(self._workspace)
        if detector is None:
            detector = AmarucoDetector(calibration=calibration)
            with self._lock:
                self._detector = detector
        ts = timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)
        detections = detector.detect(image)
        det_dicts = [d.to_dict() for d in detections]
        pose = frame_to_pose_update(detections, image.shape[1], image.shape[0], ts, workspace=workspace)
        with self._lock:
            self._last_detections = det_dicts
            self._last_frame_ts = time.monotonic()
        if pose is not None and self._tracking is not None:
            self._publish(pose)
        return {"detections": det_dicts, "pose": pose, "timestampMs": ts}

    # -- background loop ----------------------------------------------------------
    def _loop(self) -> None:  # pragma: no cover - requires camera hardware
        frame_count = 0
        window_start = time.monotonic()
        while not self._stop.is_set():
            with self._lock:
                capture = self._capture
            if capture is None:
                break
            ok, frame = capture.read()
            if not ok:
                with self._lock:
                    self._error = "camera frame grab failed"
                time.sleep(0.05)
                continue
            with self._lock:
                self._error = None
            try:
                self.process_frame(frame)
            except Exception as exc:
                with self._lock:
                    self._error = f"detection error: {exc}"
            frame_count += 1
            now = time.monotonic()
            if now - window_start >= 1.0:
                with self._lock:
                    self._fps = frame_count / (now - window_start)
                frame_count = 0
                window_start = now

    # -- publishing ------------------------------------------------------------
    def _publish(self, pose: dict[str, Any]) -> None:
        """Push one detection payload into the TrackingBridge."""
        if self._tracking is None:
            return
        if pose.get("calibrated") and "positionMm" in pose:
            ori = pose.get("orientation", {})
            self._tracking.update_pose(
                x_mm=pose["positionMm"]["x"],
                y_mm=pose["positionMm"]["y"],
                z_mm=pose["positionMm"]["z"],
                qx=ori.get("qx"),
                qy=ori.get("qy"),
                qz=ori.get("qz"),
                qw=ori.get("qw"),
                angle_deg=0.0,
                source="camera-amaruco",
                marker_id=pose.get("markerId"),
                confidence=float(pose.get("confidence", 0.0)),
                timestamp_ms=pose.get("timestampMs"),
            )
            return
        # Uncalibrated: keep the existing image-relative conversion path.
        self._tracking.update_from_dict(pose)

    # -- status -------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self._running,
                "engine": "opencv" if self._detector is None or not self._detector.engine_ready else "opencv+aruco_nano",
                "dictionaries": list(self._detector.dictionary_names) if self._detector else [],
                "cameraCalibrationId": self._calibration.calibration_id if self._calibration else None,
                "workspaceCalibrated": bool(self._workspace.get("calibrated")),
                "fps": round(self._fps, 1),
                "error": self._error,
                "lastDetections": self._last_detections[-8:],
            }
