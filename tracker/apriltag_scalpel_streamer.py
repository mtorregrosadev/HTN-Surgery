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


class ControllerBridge:
    """Async background bridge to the Scalpel Controller WebSocket."""

    def __init__(self, controller_url: str, session_id: str, calibration_id: str = "desk-calib-1"):
        self.controller_url = controller_url.rstrip("/")
        self.session_id = session_id
        self.calibration_id = calibration_id
        self.connected = False
        self.latest_snapshot: Optional[dict] = None
        self.sofa_backend = "unknown"
        self._sample_queue: deque = deque(maxlen=2)
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._sequence = 0
        self.start_time = time.perf_counter()

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.0)

    def queue_sample(self, pose: ToolPose6DOF):
        now_ms = int((time.perf_counter() - self.start_time) * 1000)
        self._sequence += 1
        sample = {
            "contractVersion": "1.1",
            "sessionId": self.session_id,
            "toolId": "scalpel",
            "deviceId": "apriltag-scalpel-tracker",
            "calibrationId": self.calibration_id,
            "sequence": self._sequence,
            "timestampMs": now_ms,
            "positionMm": {
                "x": round(pose.x_mm, 2),
                "y": round(pose.y_mm, 2),
                "z": round(pose.z_mm, 2),
            },
            "orientation": {
                "qx": round(pose.qx, 5),
                "qy": round(pose.qy, 5),
                "qz": round(pose.qz, 5),
                "qw": round(pose.qw, 5),
            },
            "forceN": 0.0,
            "contact": pose.y_mm <= 0.0,
            "quality": round(pose.confidence, 2),
            "sourceHealthy": True,
            "inputMode": "calibrated-hardware",
            "forceMeasurementValid": False,
        }
        self._sample_queue.append(sample)

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


def resolve_or_create_session(controller_url: str, session_id: str) -> tuple[str, str]:
    """Resolve an active session from the controller or create a new calibrated session."""
    import urllib.request
    ctrl = controller_url.rstrip("/")
    if session_id and session_id not in ("auto", "demo-session-1"):
        return session_id, "calib-demo-default"

    # 1. Check for active session on controller
    try:
        req = urllib.request.Request(f"{ctrl}/v1/sessions/active")
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                active_id = data.get("sessionId")
                if active_id:
                    print(f"[Session] Auto-attached to active controller session: {active_id}", flush=True)
                    return active_id, data.get("calibrationId", "calib-demo-default")
    except Exception:
        pass

    # 2. Create new session with demo calibration if none exists
    try:
        calib_data = json.dumps({
            "deviceId": "apriltag-scalpel-tracker",
            "transform": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
            "rmsErrorMm": 0.05
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{ctrl}/v1/calibrations",
            data=calib_data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            calib = json.loads(resp.read().decode("utf-8"))
            calib_id = calib.get("calibrationId", "calib-demo-default")

        sess_data = json.dumps({
            "exerciseId": "chest-tube-access-demo",
            "calibrationId": calib_id,
            "toolId": "scalpel",
            "deviceId": "apriltag-scalpel-tracker"
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{ctrl}/v1/sessions",
            data=sess_data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            sess = json.loads(resp.read().decode("utf-8"))
            new_id = sess.get("sessionId", "demo-session-live")
            print(f"[Session] Created active surgical training session: {new_id}", flush=True)
            return new_id, calib_id
    except Exception as e:
        print(f"[Session] Note: Controller session creation ({e}); using default session ID.", flush=True)
        return "demo-session-live", "calib-demo-default"


def main():
    ap = argparse.ArgumentParser(description="Track AprilTag scalpel in 3D desk space & stream to controller")
    ap.add_argument("--camera", type=int, default=None, help="Camera index (default: auto-detect)")
    ap.add_argument("--family", choices=FAMILIES, default="36h11", help="AprilTag family")
    ap.add_argument("--scale", type=float, default=1.0, help="Detection scale (1.0 for full space reach, 0.5 for fast)")
    ap.add_argument("--desk-tag", type=int, default=0, help="Fiducial AprilTag ID for desk registration")
    ap.add_argument("--desk-tag-size", type=float, default=50.0, help="Desk tag physical size in mm")
    ap.add_argument("--tool-tag-size", type=float, default=24.0, help="Tool tags physical size in mm")
    ap.add_argument("--tip-offset", type=float, default=65.0, help="Blade tip offset along handle in mm")
    ap.add_argument("--controller", default="http://localhost:8100", help="Scalpel controller URL")
    ap.add_argument("--session", default="auto", help="Controller session ID or 'auto' to attach to active session")
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

    session_id, calib_id = resolve_or_create_session(args.controller, args.session)
    bridge = ControllerBridge(controller_url=args.controller, session_id=session_id, calibration_id=calib_id)
    bridge.start()

    log_file = open(args.csv, "w") if args.csv else None
    if log_file:
        log_file.write("frame,timestamp_ms,x,y,z,qx,qy,qz,qw,contact\n")

    current_scale = args.scale
    frame_no = 0
    fps = 0.0
    prev_time = time.perf_counter()
    trail = deque(maxlen=60)
    window_name = "Surge Prep - 3D Desk & Scalpel Tracker"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 1280, 720)

    print("\nSurge Prep Physical Scalpel Tracker Live.")
    print("Controls:")
    print("  'p': Pivot Calibrate (Rotate scalpel around stationary tip on desk for high precision)")
    print("  'c': Fiducial Calibrate (Lock desk using visible Tag 0)")
    print("  'f': Toggle Fast Detection (0.5x vs 1.0x)")
    print("  'q'/Esc: Quit\n", flush=True)

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.02)
                continue

            now = time.perf_counter()
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

            # 1. Pivot Calibration Mode (Rotating System of Scalpel)
            if pivot_mode:
                # Check for tool tags
                tool_visible = [tid for tid in detected_tags if tid in pose_solver.tool_tag_ids]
                if tool_visible:
                    tag_pts = [detected_tags[tid] for tid in tool_visible]
                    # Solve single tag pose
                    res = pose_solver.solve_tag_pose(tag_pts[0])
                    if res is not None:
                        r_mat, t_vec = res
                        pivot_calibrator.add_sample(r_mat, t_vec)

                progress = pivot_calibrator.progress
                # Draw pivot calibration HUD
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

            # 2. Fiducial Tag-based calibration (if tag 0 visible and not in pivot mode)
            elif args.desk_tag in detected_tags and desk_calib is None:
                new_calib = estimate_desk_from_tag(
                    corners_2d=detected_tags[args.desk_tag],
                    tag_size_mm=args.desk_tag_size,
                    camera_matrix=camera_matrix,
                    dist_coeffs=dist_coeffs,
                    tag_id=args.desk_tag
                )
                if new_calib is not None:
                    desk_calib = new_calib
                    save_desk_calibration(desk_calib)

            # 3. Render AR 3D Desk Grid if calibrated
            if desk_calib is not None:
                draw_desk_plane_grid(frame, desk_calib, camera_matrix, dist_coeffs)

            # 4. Solve 6-DOF Tool Pose
            current_pose: Optional[ToolPose6DOF] = None
            if desk_calib is not None and detected_tags and not pivot_mode:
                current_pose = pose_solver.solve_tool_pose(detected_tags, desk_calib, now)

            if current_pose is not None:
                bridge.queue_sample(current_pose)
                pose_solver.draw_tool_3d(frame, current_pose, desk_calib)

                tip_cam = np.array(current_pose.cam_pos_mm, dtype=np.float64).reshape(1, 3)
                proj_tip, _ = cv2.projectPoints(tip_cam, np.zeros((3, 1)), np.zeros((3, 1)), camera_matrix, dist_coeffs)
                tx, ty = proj_tip[0].ravel().astype(int)
                trail.append((tx, ty))

                if log_file:
                    now_ms = int((now - bridge.start_time) * 1000)
                    log_file.write(
                        f"{frame_no},{now_ms},{current_pose.x_mm:.2f},{current_pose.y_mm:.2f},"
                        f"{current_pose.z_mm:.2f},{current_pose.qx:.4f},{current_pose.qy:.4f},"
                        f"{current_pose.qz:.4f},{current_pose.qw:.4f},{int(current_pose.y_mm <= 0.0)}\n"
                    )

            trail_pts = list(trail)
            for a, b in zip(trail_pts, trail_pts[1:]):
                cv2.line(frame, a, b, (0, 255, 255), 2, cv2.LINE_AA)

            # 5. Render HUD Overlay
            cv2.rectangle(frame, (8, 8), (min(w - 8, 720), 72), (20, 20, 20), cv2.FILLED)
            if desk_calib:
                method_name = desk_calib.calibration_method.upper()
                desk_str = f"LOCKED ({method_name})"
            else:
                desk_str = "UNSET (Press 'p' to Pivot or place Tag 0)"
            stream_str = f"LIVE ({bridge.sofa_backend})" if bridge.connected else "OFFLINE"
            line1 = f"FPS: {fps:4.1f} | Desk Space: {desk_str} | Stream: {stream_str}"
            cv2.putText(frame, line1, (14, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 255, 255), 2, cv2.LINE_AA)

            if now < toast_until:
                cv2.putText(frame, status_toast, (14, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (50, 255, 50), 1, cv2.LINE_AA)
            elif current_pose is not None:
                contact_str = "CONTACT [YES]" if current_pose.y_mm <= 0 else f"Hover (+{current_pose.y_mm:.1f}mm)"
                line2 = f"Scalpel: ({current_pose.x_mm:4.0f}, {current_pose.y_mm:4.0f}, {current_pose.z_mm:4.0f} mm) | {contact_str}"
                cv2.putText(frame, line2, (14, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (220, 220, 220), 1, cv2.LINE_AA)
            else:
                cv2.putText(frame, "Scalpel: Searching for Tags 1, 2, 3 on tool handle...", (14, 48),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.44, (200, 200, 200), 1, cv2.LINE_AA)

            mode_str = f"Fast ({current_scale:.1f}x)" if current_scale < 0.99 else "Full (1.0x)"
            line3 = f"[Space/t] Tare Recenter | [p] Pivot Calib | [c] Tag Calib | [r] Reset Space | [f] Speed | [q] Quit"
            cv2.putText(frame, line3, (14, 66), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (170, 170, 170), 1, cv2.LINE_AA)

            cv2.imshow(window_name, frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key in (ord("t"), ord(" "), ord("z")):
                if current_pose is not None:
                    desk_calib.origin_cam = list(current_pose.cam_pos_mm)
                    save_desk_calibration(desk_calib)
                    status_toast = "RECENTERED CONTROLLER: (0, 0, 0) set to current scalpel tip!"
                    toast_until = now + 3.0
                    print(f"[Tare] {status_toast}", flush=True)
                else:
                    status_toast = "Cannot Tare: Hold scalpel in view of camera"
                    toast_until = now + 2.0
            if key == ord("r"):
                desk_calib = get_default_desk_calibration()
                save_desk_calibration(desk_calib)
                status_toast = "RESET: Restored default 6-DOF controller space"
                toast_until = now + 3.0
                print(f"[Reset] {status_toast}", flush=True)
            if key == ord("p"):
                pivot_mode = not pivot_mode
                pivot_calibrator.reset()
                status_toast = "Pivot Calibration Started: keep tip on desk and rotate handle"
                toast_until = now + 3.0
                print(f"[Pivot] {status_toast}", flush=True)
            if key == ord("c"):
                if args.desk_tag in detected_tags:
                    desk_calib = estimate_desk_from_tag(
                        corners_2d=detected_tags[args.desk_tag],
                        tag_size_mm=args.desk_tag_size,
                        camera_matrix=camera_matrix,
                        dist_coeffs=dist_coeffs,
                        tag_id=args.desk_tag
                    )
                    if desk_calib:
                        save_desk_calibration(desk_calib)
                        status_toast = "Desk calibration locked & saved using Tag 0."
                        toast_until = now + 3.0
                        print(f"[Desk] {status_toast}", flush=True)
                else:
                    status_toast = f"Desk Tag {args.desk_tag} not visible."
                    toast_until = now + 2.5
            if key == ord("f"):
                current_scale = 1.0 if current_scale < 0.99 else 0.5
                print(f"[Performance] Switched detection scale to {current_scale}x.", flush=True)

            if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        bridge.stop()
        cap.release()
        cv2.destroyAllWindows()
        for _ in range(5):
            cv2.waitKey(1)
        if log_file:
            log_file.close()


if __name__ == "__main__":
    main()
