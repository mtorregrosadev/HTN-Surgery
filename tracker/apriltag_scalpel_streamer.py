"""AprilTag Scalpel Tracker & Scalpel Controller Streamer.

Tracks the physical scalpel in 3D desk space and streams normalized ToolSampleDto
packets to the Surge Prep Scalpel Controller WebSocket endpoint.
Supports 3D Desk Registration using:
- The rotating system of the scalpel (Pivot Calibration around stationary tip) [Press 'p']
- Reference desk fiducial AprilTag [Press 'c']
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import math
import sys
import threading
import time
from collections import defaultdict, deque
from typing import Dict, Optional

import cv2
import numpy as np
import websockets

from .desk_calibration import (
    DeskCalibration,
    PivotCalibrator,
    desk_rect_from_pixels,
    draw_desk_plane_grid,
    estimate_desk_from_tag,
    get_default_camera_matrix,
    get_default_desk_calibration,
    load_desk_calibration,
    save_desk_calibration,
)
from .tool_pose_solver import ScalpelPoseSolver, ToolPose6DOF

FAMILIES = {
    "16h5": cv2.aruco.DICT_APRILTAG_16h5,
    "25h9": cv2.aruco.DICT_APRILTAG_25h9,
    "36h10": cv2.aruco.DICT_APRILTAG_36h10,
    "36h11": cv2.aruco.DICT_APRILTAG_36h11,
}
REFINE_METHODS = {
    "subpix": getattr(cv2.aruco, "CORNER_REFINE_SUBPIX", 1),
    "none": getattr(cv2.aruco, "CORNER_REFINE_NONE", 0),
    "apriltag": getattr(cv2.aruco, "CORNER_REFINE_APRILTAG", 3),
}
COLORS = [(0, 0, 255), (0, 200, 0), (255, 100, 0), (0, 200, 255), (255, 0, 255)]
TRACKER_DEVICE_ID = "apriltag-scalpel-tracker"
TRACKER_TOOL_ID = "scalpel"
TRACKER_EXERCISE_ID = "chest-tube-access-demo"


def _is_measured_calibration(calibration: Optional[DeskCalibration]) -> bool:
    """Return whether a desk frame is safe to bind to a live session."""
    return bool(
        calibration is not None
        and calibration.is_valid()
        and calibration.calibration_method != "nominal-controller"
    )


def _calibration_transform_matches(
    calibration_record: object, desk_calib: DeskCalibration
) -> bool:
    """Check a controller calibration record against the local measured frame."""
    if not isinstance(calibration_record, dict):
        return False
    transform = calibration_record.get("transform")
    if not isinstance(transform, (list, tuple)) or len(transform) != 16:
        return False
    try:
        expected = np.asarray(desk_calib.camera_to_desk_transform(), dtype=np.float64)
        actual = np.asarray(transform, dtype=np.float64)
    except (TypeError, ValueError):
        return False
    return bool(np.all(np.isfinite(actual)) and np.allclose(actual, expected, atol=1e-3, rtol=1e-6))


def _session_matches_tracker(data: dict, desk_calib: DeskCalibration) -> bool:
    """Validate all locally knowable session and calibration ownership fields."""
    if data.get("status") not in (None, "active"):
        return False
    if data.get("toolId") != TRACKER_TOOL_ID or data.get("deviceId") != TRACKER_DEVICE_ID:
        return False
    calibration_id = data.get("calibrationId")
    if not calibration_id:
        return False

    # The current API does not expose a calibration GET route, but newer
    # controller responses may include the record inline.  If the transform is
    # unavailable, reuse is unsafe: create a fresh session below instead.
    calibration_record = data.get("calibration")
    if calibration_record is None and "transform" in data:
        calibration_record = data
    return _calibration_transform_matches(calibration_record, desk_calib)


class ControllerBridge:
    """Streams physical scalpel poses to the Scalpel Controller over WebSockets."""

    def __init__(
        self,
        controller_url: str,
        session_id: str,
        calibration_id: str,
        initial_sequence: int = 0,
        motion_scale: float = 1.0,
    ):
        self.controller_url = controller_url.rstrip("/")
        self.session_id = session_id
        self.calibration_id = calibration_id
        if motion_scale <= 0.0:
            raise ValueError("motion_scale must be positive")
        self.motion_scale = motion_scale
        self.connected = False
        self.latest_snapshot: Optional[dict] = None
        self.sofa_backend = "unknown"
        self._sample_queue: deque = deque(maxlen=2)
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._sequence = initial_sequence
        self.start_time = time.monotonic()
        self._last_sample: Optional[dict] = None
        self._last_loss_report_ms: Optional[int] = None
        self.tracking_lost = False

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.0)

    def queue_sample(self, pose: ToolPose6DOF):
        now_ms = int(time.monotonic_ns() // 1_000_000)
        self._sequence += 1

        # Keep physical desk-space millimetres by default.  An explicit
        # motion_scale remains available for experiments, but the normal live
        # path is one-to-one and does not clamp or reshape penetration.
        scaled_x = pose.x_mm * self.motion_scale
        scaled_y = pose.y_mm * self.motion_scale
        scaled_z = pose.z_mm * self.motion_scale

        sample = {
            "contractVersion": "1.1",
            "sessionId": self.session_id,
            "toolId": "scalpel",
            "deviceId": "apriltag-scalpel-tracker",
            "calibrationId": self.calibration_id,
            "sequence": self._sequence,
            "timestampMs": now_ms,
            "positionMm": {
                "x": round(scaled_x, 3),
                "y": round(scaled_y, 3),
                "z": round(scaled_z, 3),
            },
            "orientation": {
                "qx": round(pose.qx, 5),
                "qy": round(pose.qy, 5),
                "qz": round(pose.qz, 5),
                "qw": round(pose.qw, 5),
            },
            "forceN": round(max(0.0, -pose.y_mm * 0.18), 2) if pose.y_mm <= 0.0 else 0.0,
            "contact": pose.y_mm <= 0.0,
            "quality": round(pose.confidence, 2),
            "sourceHealthy": True,
            "inputMode": "calibrated-hardware",
            "forceMeasurementValid": False,
        }
        self._last_sample = sample
        self._last_loss_report_ms = None
        self.tracking_lost = False
        self._sample_queue.append(sample)

    def queue_unhealthy(self) -> bool:
        """Queue an explicit loss-of-tracking sample using the last pose.

        A missing tag cannot provide a new pose, so reusing the last pose is
        intentional and marked unhealthy.  The API can then freeze the last
        valid simulation state and surface the degraded session to clients.
        """
        if self._last_sample is None:
            return False
        now_ms = int(time.monotonic_ns() // 1_000_000)
        # Avoid flooding the queue faster than the camera can report a useful
        # state while still emitting a visible health transition promptly.
        if self._last_loss_report_ms is not None and now_ms - self._last_loss_report_ms < 50:
            return False
        sample = copy.deepcopy(self._last_sample)
        self._sequence += 1
        sample.update(
            sequence=self._sequence,
            timestampMs=now_ms,
            quality=0.0,
            sourceHealthy=False,
            contact=False,
            forceN=0.0,
            forceMeasurementValid=False,
        )
        self._last_loss_report_ms = now_ms
        self.tracking_lost = True
        self._sample_queue.append(sample)
        return True

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.start_time) * 1000.0)

    def _run_loop(self):
        asyncio.run(self._worker())

    async def _worker(self):
        ws_url = f"{self.controller_url}/v1/sessions/{self.session_id}/hardware-stream"
        ws_url = ws_url.replace("http://", "ws://").replace("https://", "wss://")
        while not self._stop_event.is_set():
            try:
                async with websockets.connect(ws_url, close_timeout=1.0) as ws:
                    self.connected = True
                    print(f"[ControllerBridge] Connected to {ws_url}", flush=True)
                    while not self._stop_event.is_set():
                        if self._sample_queue:
                            sample = self._sample_queue.popleft()
                            await ws.send(json.dumps(sample))
                            try:
                                resp_raw = await asyncio.wait_for(ws.recv(), timeout=0.08)
                                resp = json.loads(resp_raw)
                                if resp.get("type") == "error":
                                    if resp.get("status") == 409:
                                        self._sequence += 1000
                                else:
                                    self.latest_snapshot = resp
                                    if "simulationBackend" in resp:
                                        self.sofa_backend = resp["simulationBackend"]
                            except asyncio.TimeoutError:
                                pass
                        else:
                            await asyncio.sleep(0.01)
            except Exception:
                self.connected = False
                self.sofa_backend = "offline"
                await asyncio.sleep(1.0)


def open_camera_auto(preferred_index: Optional[int] = None) -> Tuple[Optional[cv2.VideoCapture], int]:
    """Auto-detect and open an active, non-blank camera stream."""
    if preferred_index is not None:
        candidates = [preferred_index]
    elif sys.platform == "darwin":
        candidates = [1, 0, 2, 3]
    else:
        candidates = [0, 1, 2, 3]
    candidates += [i for i in range(5) if i not in candidates]
    backend = cv2.CAP_DSHOW if sys.platform.startswith("win") else cv2.CAP_ANY

    for idx in candidates:
        try:
            cap = cv2.VideoCapture(idx, backend) if backend != cv2.CAP_ANY else cv2.VideoCapture(idx)
        except Exception:
            continue
        if not cap.isOpened():
            cap.release()
            continue

        for _ in range(10):
            ok, frame = cap.read()
            if ok and frame is not None and np.mean(frame) > 3.0 and np.std(frame) > 3.0:
                print(f"[Camera] Active stream found on index {idx} ({frame.shape[1]}x{frame.shape[0]}).", flush=True)
                return cap, idx
            time.sleep(0.03)
        cap.release()

    return None, 0


def resolve_or_create_session(
    controller_url: str,
    session_id: str,
    force_new: bool = False,
    desk_calib: Optional[DeskCalibration] = None,
) -> tuple[str, str, int]:
    """Resolve a real session or create one from the measured desk transform."""
    import urllib.request
    ctrl = controller_url.rstrip("/")

    def read_json(request: urllib.request.Request) -> dict:
        try:
            with urllib.request.urlopen(request, timeout=3.0) as response:
                if response.status >= 400:
                    raise RuntimeError(f"controller returned HTTP {response.status}")
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise RuntimeError(f"controller request failed: {exc}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("controller returned a non-object response")
        return payload

    if not force_new and session_id and session_id not in ("auto", "demo-session-1"):
        data = read_json(urllib.request.Request(f"{ctrl}/v1/sessions/{session_id}"))
        calibration_id = data.get("calibrationId")
        if not calibration_id or data.get("status") not in (None, "active"):
            raise RuntimeError(f"session {session_id!r} is missing an active calibration")
        return session_id, str(calibration_id), int(data.get("lastSequence") or 0)

    # 1. Check for active session on controller if not forcing new
    if not force_new:
        try:
            data = read_json(urllib.request.Request(f"{ctrl}/v1/sessions/active"))
            active_id = data.get("sessionId")
            calibration_id = data.get("calibrationId")
            if active_id and calibration_id and data.get("status") in (None, "active"):
                last_seq = data.get("lastSequence", 0) or 0
                print(f"[Session] Auto-attached to active controller session: {active_id} (lastSequence: {last_seq})", flush=True)
                return str(active_id), str(calibration_id), int(last_seq)
        except RuntimeError:
            pass

    if desk_calib is None or not desk_calib.is_valid():
        raise RuntimeError("a valid measured desk calibration is required before creating a session")

    calib_data = json.dumps({
        "deviceId": "apriltag-scalpel-tracker",
        "coordinateFrame": "right-handed-x-right-y-up-z-away",
        "transform": desk_calib.camera_to_desk_transform(),
        "rmsErrorMm": float(desk_calib.rms_error_mm),
        "valid": True,
        "calibrationMethod": desk_calib.calibration_method,
    }).encode("utf-8")
    calib = read_json(urllib.request.Request(
        f"{ctrl}/v1/calibrations",
        data=calib_data,
        headers={"Content-Type": "application/json"}
    ))
    calibration_id = calib.get("calibrationId")
    if not calibration_id:
        raise RuntimeError("controller calibration response did not include calibrationId")

    sess_data = json.dumps({
        "exerciseId": "chest-tube-access-demo",
        "calibrationId": calibration_id,
        "toolId": "scalpel",
        "deviceId": "apriltag-scalpel-tracker"
    }).encode("utf-8")
    session = read_json(urllib.request.Request(
        f"{ctrl}/v1/sessions",
        data=sess_data,
        headers={"Content-Type": "application/json"}
    ))
    new_id = session.get("sessionId")
    if not new_id:
        raise RuntimeError("controller session response did not include sessionId")
    print(f"[Session] Created active surgical training session: {new_id}", flush=True)
    return str(new_id), str(calibration_id), 0


def main():
    ap = argparse.ArgumentParser(description="Track AprilTag scalpel in 3D desk space & stream to controller")
    ap.add_argument("--camera", type=int, default=None, help="Camera index (default: auto-detect)")
    ap.add_argument("--family", choices=FAMILIES, default="36h11", help="AprilTag family")
    ap.add_argument("--scale", type=float, default=1.0, help="Detection scale (1.0 for full space reach, 0.5 for fast)")
    ap.add_argument("--desk-tag", type=int, default=0, help="Fiducial AprilTag ID for desk registration")
    ap.add_argument("--desk-tag-size", type=float, default=50.0, help="Desk tag physical size in mm")
    ap.add_argument("--tool-tag-size", type=float, default=24.0, help="Tool tags physical size in mm")
    ap.add_argument("--tip-offset", type=float, default=65.0, help="Blade tip offset along handle in mm")
    ap.add_argument("--motion-scale", type=float, default=1.0, help="Optional physical-to-virtual scale (default: 1.0, one-to-one)")
    ap.add_argument("--controller", default="http://localhost:8100", help="Scalpel controller URL")
    ap.add_argument("--session", default="auto", help="Controller session ID or 'auto' to attach to active session")
    ap.add_argument("--new-session", action="store_true", help="Force creating a new active session instead of attaching")
    ap.add_argument("--csv", help="Optional CSV logging path")
    args = ap.parse_args()

    cap, camera_idx = open_camera_auto(args.camera)
    if cap is None:
        raise SystemExit("Error: Unable to open any active video camera.")

    ok, test_frame = cap.read()
    h, w = test_frame.shape[:2]
    camera_matrix, dist_coeffs = get_default_camera_matrix(w, h)

    dictionary = cv2.aruco.getPredefinedDictionary(FAMILIES[args.family])
    params = cv2.aruco.DetectorParameters()
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    detector = cv2.aruco.ArucoDetector(dictionary, params)

    pose_solver = ScalpelPoseSolver(
        camera_matrix=camera_matrix,
        dist_coeffs=dist_coeffs,
        tag_size_mm=args.tool_tag_size,
        tip_offset_along_handle_mm=args.tip_offset,
        tool_tag_ids=(1, 2, 3),
    )

    desk_calib = load_desk_calibration()
    # Check if existing calibration is healthy (positive depth > 100mm, valid matrix)
    if desk_calib and (desk_calib.origin_cam[2] < 100.0 or desk_calib.r_cam_to_desk[0][0] < 0.3):
        print("[Desk] Detected degenerate calibration file. Re-initializing to robust 6-DOF controller space.", flush=True)
        desk_calib = None

    if desk_calib is None:
        desk_calib = get_default_desk_calibration()
        save_desk_calibration(desk_calib)
        print("[Desk] 6-DOF Controller Tracking active. (Hold scalpel at start position and press Space to Tare/Recenter).", flush=True)
    else:
        print(f"[Desk] Loaded existing desk calibration ({desk_calib.calibration_method}).", flush=True)

    pivot_calibrator = PivotCalibrator(min_samples=45)
    pivot_mode = False
    status_toast = ""
    toast_until = 0.0

    bridge: Optional[ControllerBridge] = None
    # A nominal desk frame is useful for displaying the camera feed while the
    # user places the tool, but it is not a session calibration.  The bridge is
    # started only after the initial tare creates a real, session-bound frame.
    if desk_calib.calibration_method != "nominal-controller":
        session_id, calib_id, last_seq = resolve_or_create_session(
            args.controller,
            args.session,
            force_new=args.new_session,
            desk_calib=desk_calib,
        )
        bridge = ControllerBridge(
            controller_url=args.controller,
            session_id=session_id,
            calibration_id=calib_id,
            initial_sequence=last_seq,
            motion_scale=args.motion_scale,
        )
        bridge.start()
    else:
        print("[Session] Waiting for the first measured tare before creating a session.", flush=True)

    log_file = open(args.csv, "w") if args.csv else None
    if log_file:
        log_file.write("frame,timestamp_ms,x,y,z,qx,qy,qz,qw,contact\n")

    current_scale = args.scale
    frame_no = 0
    fps = 0.0
    tracker_start_time = time.monotonic()
    prev_time = time.monotonic()
    trail = deque(maxlen=60)
    show_grid = False
    window_name = "Surge Prep - 3D Desk & Scalpel Tracker"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 1280, 720)

    tilt_deg = 28.0
    mouse_state = {
        "dragging": False,
        "start": (0, 0),
        "current": (0, 0),
        "drawn_rect": None,
    }

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            mouse_state["dragging"] = True
            mouse_state["start"] = (x, y)
            mouse_state["current"] = (x, y)
        elif event == cv2.EVENT_MOUSEMOVE and mouse_state["dragging"]:
            mouse_state["current"] = (x, y)
        elif event == cv2.EVENT_LBUTTONUP and mouse_state["dragging"]:
            mouse_state["dragging"] = False
            p0 = mouse_state["start"]
            p1 = (x, y)
            if abs(p1[0] - p0[0]) > 20 and abs(p1[1] - p0[1]) > 20:
                mouse_state["drawn_rect"] = (
                    min(p0[0], p1[0]), min(p0[1], p1[1]),
                    max(p0[0], p1[0]), max(p0[1], p1[1])
                )

    cv2.setMouseCallback(window_name, on_mouse)

    print("\nSurge Prep Physical Scalpel Tracker Live.")
    print("Controls:")
    print("  [Drag Mouse] Draw Rectangle Area directly on the table to lock workspace")
    print("  's' / 'c': Snap Desk Plane to Scalpel resting on desk")
    print("  'd': Default generous surgical area (320x220 mm)")
    print("  '[' / ']': Adjust Desk Tilt Angle (+/- 1.5 deg)")
    print("  '+' / '-': Raise/Lower Desk Height (+/- 5 mm)")
    print("  Space / 't': Tare / Recenter (0,0,0) to current scalpel tip")
    print("  'p': Pivot Calibrate")
    print("  'q'/Esc: Quit\n", flush=True)

    initial_tumbado_locked = False
    settle_counter = 0

    def start_session_bridge(calibration: DeskCalibration) -> ControllerBridge:
        """Create a stream only after the calibration frame is finalized."""
        session_id, calib_id, last_seq = resolve_or_create_session(
            args.controller,
            args.session,
            force_new=args.new_session,
            desk_calib=calibration,
        )
        result = ControllerBridge(
            controller_url=args.controller,
            session_id=session_id,
            calibration_id=calib_id,
            initial_sequence=last_seq,
            motion_scale=args.motion_scale,
        )
        result.start()
        return result

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.02)
                continue

            now = time.monotonic()
            dt = now - prev_time
            prev_time = now
            if dt > 0:
                current_fps = 1.0 / dt
                fps = (0.85 * fps + 0.15 * current_fps) if fps > 0 else current_fps

            frame_no += 1
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            if current_scale < 0.99:
                gray_detect = cv2.resize(gray, (0, 0), fx=current_scale, fy=current_scale)
            else:
                gray_detect = gray

            corners, ids, _ = detector.detectMarkers(gray_detect)

            detected_tags: Dict[int, np.ndarray] = {}
            if ids is not None:
                inv_scale = 1.0 / current_scale if current_scale < 0.99 else 1.0
                for c, tag_id in zip(corners, ids.flatten()):
                    pts = c.reshape(4, 2) * inv_scale
                    detected_tags[int(tag_id)] = pts
                    col = COLORS[int(tag_id) % len(COLORS)]
                    cv2.polylines(frame, [pts.astype(np.int32)], True, col, 2)
                    cx, cy = pts.mean(axis=0)
                    cv2.putText(frame, f"ID {tag_id}", (int(pts[0][0]), int(pts[0][1]) - 6),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 1, cv2.LINE_AA)

            # 1. Check if user drew a rectangle on the video feed
            if bridge is None and mouse_state["drawn_rect"] is not None:
                u0, v0, u1, v1 = mouse_state["drawn_rect"]
                mouse_state["drawn_rect"] = None
                if desk_calib is None or not desk_calib.is_valid():
                    desk_calib = get_default_desk_calibration(tilt_deg=tilt_deg)
                new_calib = desk_rect_from_pixels(u0, v0, u1, v1, desk_calib, camera_matrix)
                if new_calib is not None and new_calib.is_valid():
                    desk_calib = new_calib
                    save_desk_calibration(desk_calib)
                    status_toast = f"LOCKED AREA: {int(desk_calib.extent_x_mm*2)}x{int(desk_calib.extent_z_mm*2)} mm surgical field!"
                    toast_until = now + 4.0
                    print(f"[Area] {status_toast}", flush=True)
                else:
                    status_toast = "Could not project area: drag rectangle on table in lower half of screen"
                    toast_until = now + 2.5

            # 2. Pivot Calibration Mode
            if bridge is None and pivot_mode:
                primary_tag = pose_solver.primary_tag_visible(detected_tags)
                if primary_tag is not None:
                    res = pose_solver.solve_reference_tag_pose(primary_tag, detected_tags[primary_tag])
                    if res is not None:
                        r_mat, t_vec = res
                        pivot_calibrator.add_sample(r_mat, t_vec)

                progress = pivot_calibrator.progress
                cv2.rectangle(frame, (w // 4, h - 85), (3 * w // 4, h - 25), (0, 0, 0), cv2.FILLED)
                cv2.rectangle(frame, (w // 4, h - 85), (3 * w // 4, h - 25), (0, 255, 255), 2)
                cv2.putText(frame, "PIVOT CALIBRATION: Keep tip on desk, rotate handle in cone",
                            (w // 4 + 10, h - 60), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (0, 255, 255), 1, cv2.LINE_AA)
                bar_w = int((w // 2 - 20) * progress)
                cv2.rectangle(frame, (w // 4 + 10, h - 45), (w // 4 + 10 + bar_w, h - 35), (0, 255, 0), cv2.FILLED)

                if pivot_calibrator.is_ready:
                    res_calib = pivot_calibrator.solve()
                    if res_calib is not None:
                        desk_calib, solved_tip = res_calib
                        save_desk_calibration(desk_calib)
                        pivot_mode = False
                        status_toast = f"LOCKED Desk via Scalpel Pivot! Tip offset: {np.round(solved_tip, 1)} mm"
                        toast_until = now + 4.0
                        print(f"[Pivot Calibration] {status_toast} (RMS: {desk_calib.rms_error_mm} mm)", flush=True)

            # 3. Solve 6-DOF Tool Pose
            current_pose: Optional[ToolPose6DOF] = None
            if desk_calib is not None and detected_tags and not pivot_mode:
                current_pose = pose_solver.solve_tool_pose(detected_tags, desk_calib, now)

            # 4. Render AR 3D Desk Grid & Area
            if desk_calib is not None:
                tip_pos_desk = np.array([current_pose.x_mm, current_pose.y_mm, current_pose.z_mm]) if current_pose else None
                draw_desk_plane_grid(frame, desk_calib, camera_matrix, dist_coeffs, scalpel_tip_desk=tip_pos_desk, show_grid=show_grid)

            # 5. Render live mouse dragging rectangle
            if mouse_state["dragging"]:
                p0 = mouse_state["start"]
                p1 = mouse_state["current"]
                cv2.rectangle(frame, p0, p1, (0, 255, 255), 2)
                cv2.putText(frame, "Drawing Workspace Area (Release to Lock)...",
                            (min(p0[0], p1[0]), max(20, min(p0[1], p1[1]) - 8)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.44, (0, 255, 255), 1, cv2.LINE_AA)

            if current_pose is not None:
                session_just_started = False
                # Auto-calibrate initial resting Tumbado position if uncalibrated
                if bridge is None and not initial_tumbado_locked and desk_calib and desk_calib.calibration_method == "nominal-controller":
                    settle_counter += 1
                    if settle_counter >= 6:
                        tip_cam = np.array(current_pose.cam_pos_mm, dtype=np.float64)
                        ext_x = getattr(desk_calib, "extent_x_mm", 160.0) if desk_calib else 160.0
                        ext_z = getattr(desk_calib, "extent_z_mm", 110.0) if desk_calib else 110.0
                        desk_calib = get_default_desk_calibration(origin_cam=tip_cam, tilt_deg=tilt_deg, extent_x_mm=ext_x, extent_z_mm=ext_z)
                        desk_calib.calibration_method = "start-tumbado"
                        save_desk_calibration(desk_calib)
                        initial_tumbado_locked = True
                        pose_solver.reset_tracking()
                        bridge = start_session_bridge(desk_calib)
                        # The pose above was solved in the nominal frame.  Do
                        # not send it under the newly-created calibration; the
                        # next camera sample will be the first session sample.
                        session_just_started = True
                        status_toast = "TUMBADO (RESTING ON TABLE): (0, 0, 0) LOCKED -> 1:1 Unity Live!"
                        toast_until = now + 4.0
                        print(f"[Tumbado] {status_toast}", flush=True)

                # Tare, tag, drawn-area, and successful pivot calibration all
                # finalize a real frame before the first session sample.
                if bridge is None and desk_calib and desk_calib.calibration_method != "nominal-controller":
                    pose_solver.reset_tracking()
                    bridge = start_session_bridge(desk_calib)
                    session_just_started = True

                if bridge is not None and not session_just_started:
                    bridge.queue_sample(current_pose)
                pose_solver.draw_tool_3d(frame, current_pose, desk_calib)

                tip_cam = np.array(current_pose.cam_pos_mm, dtype=np.float64).reshape(1, 3)
                proj_tip, _ = cv2.projectPoints(tip_cam, np.zeros((3, 1)), np.zeros((3, 1)), camera_matrix, dist_coeffs)
                tx, ty = proj_tip[0].ravel().astype(int)
                trail.append((tx, ty))

                if log_file:
                    now_ms = (
                        bridge.elapsed_ms()
                        if bridge is not None
                        else int((now - tracker_start_time) * 1000)
                    )
                    log_file.write(
                        f"{frame_no},{now_ms},{current_pose.x_mm:.2f},{current_pose.y_mm:.2f},"
                        f"{current_pose.z_mm:.2f},{current_pose.qx:.4f},{current_pose.qy:.4f},"
                        f"{current_pose.qz:.4f},{current_pose.qw:.4f},{int(current_pose.y_mm <= 0.0)}\n"
                    )
            else:
                pose_solver.reset_tracking()
                if bridge is not None:
                    bridge.queue_unhealthy()
                trail.append(None)

            trail_pts = list(trail)
            for a, b in zip(trail_pts, trail_pts[1:]):
                if a is not None and b is not None and math.hypot(a[0] - b[0], a[1] - b[1]) < 35:
                    cv2.line(frame, a, b, (0, 255, 255), 2, cv2.LINE_AA)

            # 6. Render HUD Overlay
            cv2.rectangle(frame, (8, 8), (min(w - 8, 860), 78), (20, 20, 20), cv2.FILLED)
            if desk_calib and desk_calib.is_valid():
                method_name = desk_calib.calibration_method.upper()
                ext_w = int(getattr(desk_calib, "extent_x_mm", 160.0) * 2)
                ext_d = int(getattr(desk_calib, "extent_z_mm", 110.0) * 2)
                desk_str = f"LOCKED ({ext_w}x{ext_d}mm {method_name})"
            else:
                desk_str = "UNSET (Place flat & press 't')"
            stream_str = f"LIVE ({bridge.sofa_backend})" if bridge is not None and bridge.connected else "OFFLINE"
            line1 = f"FPS: {fps:4.1f} | Table: {desk_str} | Stream: {stream_str}"
            cv2.putText(frame, line1, (14, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 255, 255), 1, cv2.LINE_AA)

            if now < toast_until:
                cv2.putText(frame, status_toast, (14, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (50, 255, 50), 1, cv2.LINE_AA)
            elif current_pose is not None:
                is_tumbado = abs(current_pose.y_mm) <= 6.0
                if is_tumbado:
                    mode_str = "TUMBADO (ON DESK)"
                    txt_col = (50, 255, 50)
                elif current_pose.y_mm < 0:
                    mode_str = f"INCISING ({current_pose.y_mm:.1f}mm)"
                    txt_col = (0, 140, 255)
                else:
                    mode_str = f"HOVER (+{current_pose.y_mm:.1f}mm)"
                    txt_col = (50, 220, 255)
                ext_x = getattr(desk_calib, "extent_x_mm", 160.0)
                ext_z = getattr(desk_calib, "extent_z_mm", 110.0)
                in_area = abs(current_pose.x_mm) <= ext_x and abs(current_pose.z_mm) <= ext_z
                area_tag = "IN ZONE" if in_area else "OUT OF ZONE"
                line2 = f"Scalpel: ({current_pose.x_mm:4.0f}, {current_pose.y_mm:4.0f}, {current_pose.z_mm:4.0f} mm) | [{mode_str}] [{area_tag}] -> Unity 1:1"
                cv2.putText(frame, line2, (14, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.44, txt_col, 1, cv2.LINE_AA)
            else:
                lost_text = (
                    "TRACKING LOST: unhealthy state sent to controller"
                    if bridge is not None and bridge.tracking_lost
                    else "Scalpel: Searching for Tag 1 on tool handle..."
                )
                lost_color = (0, 80, 255) if bridge is not None and bridge.tracking_lost else (200, 200, 200)
                cv2.putText(frame, lost_text, (14, 50),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.44, lost_color, 1, cv2.LINE_AA)

            line3 = "[t] Start Tumbado / Zero | [Drag Mouse] Draw Area | [g] Grid | [s] Snap Desk | [d] Default | [[ / ]] Tilt | [q] Quit"
            cv2.putText(frame, line3, (14, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (170, 170, 170), 1, cv2.LINE_AA)

            cv2.imshow(window_name, frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if bridge is None and key in (ord("t"), ord(" "), ord("z")):
                if current_pose is not None:
                    tip_cam = np.array(current_pose.cam_pos_mm, dtype=np.float64)
                    ext_x = getattr(desk_calib, "extent_x_mm", 160.0) if desk_calib else 160.0
                    ext_z = getattr(desk_calib, "extent_z_mm", 110.0) if desk_calib else 110.0
                    desk_calib = get_default_desk_calibration(origin_cam=tip_cam, tilt_deg=tilt_deg, extent_x_mm=ext_x, extent_z_mm=ext_z)
                    desk_calib.calibration_method = "start-tumbado"
                    save_desk_calibration(desk_calib)
                    status_toast = "TUMBADO CALIBRATED: Scalpel flat on desk (Z=0). 1:1 Linked to Unity!"
                    toast_until = now + 4.0
                    print(f"[Tumbado] {status_toast}", flush=True)
                else:
                    status_toast = "Cannot Tare: Place scalpel flat in view of camera"
                    toast_until = now + 2.0
            if bridge is None and key in (ord("s"), ord("c")):
                if current_pose is not None:
                    tip_cam = np.array(current_pose.cam_pos_mm, dtype=np.float64)
                    ext_x = getattr(desk_calib, "extent_x_mm", 160.0) if desk_calib else 160.0
                    ext_z = getattr(desk_calib, "extent_z_mm", 110.0) if desk_calib else 110.0
                    desk_calib = get_default_desk_calibration(origin_cam=tip_cam, tilt_deg=tilt_deg, extent_x_mm=ext_x, extent_z_mm=ext_z)
                    desk_calib.calibration_method = "scalpel-surface"
                    save_desk_calibration(desk_calib)
                    status_toast = "LOCKED DESK to scalpel position on table!"
                    toast_until = now + 3.5
                    print(f"[Desk] {status_toast}", flush=True)
                elif args.desk_tag in detected_tags:
                    new_calib = estimate_desk_from_tag(
                        corners_2d=detected_tags[args.desk_tag],
                        tag_size_mm=args.desk_tag_size,
                        camera_matrix=camera_matrix,
                        dist_coeffs=dist_coeffs,
                        tag_id=args.desk_tag
                    )
                    if new_calib:
                        desk_calib = new_calib
                        save_desk_calibration(desk_calib)
                        status_toast = "Desk calibration locked & saved using Tag 0."
                        toast_until = now + 3.0
                        print(f"[Desk] {status_toast}", flush=True)
                else:
                    status_toast = "Place scalpel on desk and press 's', or drag rectangle with mouse"
                    toast_until = now + 2.5
            if bridge is None and key == ord("d"):
                desk_calib = get_default_desk_calibration(tilt_deg=tilt_deg, extent_x_mm=160.0, extent_z_mm=110.0)
                save_desk_calibration(desk_calib)
                status_toast = "RESET AREA: Default 320x220 mm workspace"
                toast_until = now + 3.0
                print(f"[Area] {status_toast}", flush=True)
            if bridge is None and key == ord("r"):
                desk_calib = get_default_desk_calibration(tilt_deg=tilt_deg)
                save_desk_calibration(desk_calib)
                status_toast = "RESET: Restored default 6-DOF controller space"
                toast_until = now + 3.0
                print(f"[Reset] {status_toast}", flush=True)
            if bridge is None and key == ord("["):
                tilt_deg = max(12.0, tilt_deg - 1.5)
                orig = np.array(desk_calib.origin_cam) if desk_calib else None
                ext_x = getattr(desk_calib, "extent_x_mm", 160.0) if desk_calib else 160.0
                ext_z = getattr(desk_calib, "extent_z_mm", 110.0) if desk_calib else 110.0
                desk_calib = get_default_desk_calibration(origin_cam=orig, tilt_deg=tilt_deg, extent_x_mm=ext_x, extent_z_mm=ext_z)
                save_desk_calibration(desk_calib)
                status_toast = f"Desk Tilt Adjusted: {tilt_deg:.1f} deg"
                toast_until = now + 2.0
            elif bridge is None and key == ord("]"):
                tilt_deg = min(48.0, tilt_deg + 1.5)
                orig = np.array(desk_calib.origin_cam) if desk_calib else None
                ext_x = getattr(desk_calib, "extent_x_mm", 160.0) if desk_calib else 160.0
                ext_z = getattr(desk_calib, "extent_z_mm", 110.0) if desk_calib else 110.0
                desk_calib = get_default_desk_calibration(origin_cam=orig, tilt_deg=tilt_deg, extent_x_mm=ext_x, extent_z_mm=ext_z)
                save_desk_calibration(desk_calib)
                status_toast = f"Desk Tilt Adjusted: {tilt_deg:.1f} deg"
                toast_until = now + 2.0
            if bridge is None and key in (ord("+"), ord("=")):
                if desk_calib:
                    orig = np.array(desk_calib.origin_cam)
                    orig[1] -= 5.0
                    desk_calib.origin_cam = orig.tolist()
                    save_desk_calibration(desk_calib)
                    status_toast = "Raised Desk Plane (+5mm)"
                    toast_until = now + 1.5
            elif bridge is None and key in (ord("-"), ord("_")):
                if desk_calib:
                    orig = np.array(desk_calib.origin_cam)
                    orig[1] += 5.0
                    desk_calib.origin_cam = orig.tolist()
                    save_desk_calibration(desk_calib)
                    status_toast = "Lowered Desk Plane (-5mm)"
                    toast_until = now + 1.5
            if bridge is None and key == ord("p"):
                pivot_mode = not pivot_mode
                pivot_calibrator.reset()
                status_toast = "Pivot Calibration Started: keep tip on desk and rotate handle"
                toast_until = now + 3.0
                print(f"[Pivot] {status_toast}", flush=True)
            if key == ord("g"):
                show_grid = not show_grid
                status_toast = f"Grid lines: {'ON' if show_grid else 'OFF'}"
                toast_until = now + 1.5
                print(f"[HUD] {status_toast}", flush=True)
            if key == ord("f"):
                current_scale = 1.0 if current_scale < 0.99 else 0.5
                print(f"[Performance] Switched detection scale to {current_scale}x.", flush=True)

            if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        if bridge is not None:
            bridge.stop()
        cap.release()
        cv2.destroyAllWindows()
        for _ in range(5):
            cv2.waitKey(1)
        if log_file:
            log_file.close()


if __name__ == "__main__":
    main()
