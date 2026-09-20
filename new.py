"""Track an object carrying AprilTags with a webcam.

Install:  pip install opencv-python numpy
Run:      python new.py [--camera 1] [--family 36h11] [--scale 0.5] [--refine subpix] [--csv log.csv]
Keys:     q / Esc = quit, s = switch camera, f = toggle fast mode, c = clear trails
"""
import argparse
import math
import sys
import time
from collections import defaultdict, deque

import cv2
import numpy as np

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
TRAIL_LEN = 60
MAX_WARMUP_FRAMES = 12
MAX_CONSECUTIVE_DROPS = 30


def check_stream_active(cap, attempts=MAX_WARMUP_FRAMES):
    """Read a few frames to warm up sensor and check if the feed contains actual image data."""
    for _ in range(attempts):
        ok, frame = cap.read()
        if ok and frame is not None and frame.size > 0:
            if np.mean(frame) > 2.5 and np.std(frame) > 2.5:
                return True, frame
        time.sleep(0.04)
    return False, None


def open_camera_device(index):
    """Open a VideoCapture instance with appropriate backend for the OS."""
    backend = cv2.CAP_DSHOW if sys.platform.startswith("win") else cv2.CAP_ANY
    try:
        cap = cv2.VideoCapture(index, backend) if backend != cv2.CAP_ANY else cv2.VideoCapture(index)
        if cap.isOpened():
            return cap
    except Exception:
        pass
    return None


def select_best_camera(preferred_index=None):
    """Find and return an active camera, prioritizing live non-black feeds."""
    candidates = []
    if preferred_index is not None:
        candidates.append(preferred_index)
    for i in range(5):
        if i not in candidates:
            candidates.append(i)

    fallback_cap = None
    fallback_idx = None

    for idx in candidates:
        cap = open_camera_device(idx)
        if cap is None:
            continue

        is_active, frame = check_stream_active(cap)
        if is_active:
            print(f"[Camera] Active video feed detected on camera index {idx} ({frame.shape[1]}x{frame.shape[0]}).", flush=True)
            if preferred_index is not None and idx != preferred_index:
                print(f"[Camera] Note: Requested camera {preferred_index} was blank/inactive; automatically switched to camera {idx}.", flush=True)
            return cap, idx

        if fallback_cap is None:
            fallback_cap = cap
            fallback_idx = idx
        else:
            cap.release()

    if fallback_cap is not None:
        print(f"[Camera] Warning: No active non-black stream detected among candidate cameras. Using camera {fallback_idx}.", flush=True)
        return fallback_cap, fallback_idx

    return None, None


def switch_camera(current_idx):
    """Cycle to the next available camera."""
    for offset in range(1, 5):
        next_idx = (current_idx + offset) % 5
        cap = open_camera_device(next_idx)
        if cap is not None:
            is_active, _ = check_stream_active(cap, attempts=5)
            if is_active:
                print(f"[Camera] Switched to camera {next_idx}.", flush=True)
                return cap, next_idx
            cap.release()
    print(f"[Camera] No other active camera found; remaining on camera {current_idx}.", flush=True)
    return open_camera_device(current_idx), current_idx


def build_detector(family_name, refine_name):
    """Construct an optimized AprilTag detector."""
    dictionary = cv2.aruco.getPredefinedDictionary(FAMILIES[family_name])
    params = cv2.aruco.DetectorParameters()
    refine_val = REFINE_METHODS.get(refine_name, cv2.aruco.CORNER_REFINE_SUBPIX)
    params.cornerRefinementMethod = refine_val
    params.adaptiveThreshWinSizeStep = 10

    detector = None
    if hasattr(cv2.aruco, "ArucoDetector"):
        detector = cv2.aruco.ArucoDetector(dictionary, params)
    return detector, dictionary, params


def main():
    ap = argparse.ArgumentParser(description="Track AprilTags in real time using webcam")
    ap.add_argument("--camera", type=int, default=None, help="Camera device index (default: auto-detect active camera)")
    ap.add_argument("--family", choices=FAMILIES, default="36h11", help="AprilTag dictionary family")
    ap.add_argument("--scale", type=float, default=0.5, help="Detection scale factor (0.5 for high-speed ~100FPS detection, 1.0 for full res)")
    ap.add_argument("--refine", choices=REFINE_METHODS, default="subpix", help="Corner refinement method: subpix (fast & accurate), none (fastest), apriltag (slow)")
    ap.add_argument("--csv", help="Optional path to log positions")
    args = ap.parse_args()

    detector, dictionary, params = build_detector(args.family, args.refine)

    cap, camera_idx = select_best_camera(args.camera)
    if cap is None:
        raise SystemExit("Error: Unable to open any video capture device.")

    current_scale = args.scale
    trails = defaultdict(lambda: deque(maxlen=TRAIL_LEN))
    obj_trail = deque(maxlen=TRAIL_LEN)
    log = open(args.csv, "w") if args.csv else None
    if log:
        log.write("frame,tag_id,x,y\n")
    frame_no = 0
    consecutive_drops = 0

    fps = 0.0
    prev_time = time.perf_counter()

    print("AprilTag tracker running.", flush=True)
    print("Controls: 'q' or Esc = Quit | 's' = Switch camera | 'f' = Toggle Fast Mode | 'c' = Clear trails", flush=True)
    window_name = "AprilTag tracker"

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                consecutive_drops += 1
                if consecutive_drops >= MAX_CONSECUTIVE_DROPS:
                    print(f"Warning: Stream lost after {MAX_CONSECUTIVE_DROPS} consecutive failed reads. Exiting.", flush=True)
                    break
                time.sleep(0.02)
                continue
            consecutive_drops = 0

            # Calculate live FPS (exponential moving average)
            now = time.perf_counter()
            dt = now - prev_time
            prev_time = now
            if dt > 0:
                current_fps = 1.0 / dt
                fps = (0.85 * fps + 0.15 * current_fps) if fps > 0 else current_fps

            frame_no += 1
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # High-speed scaled detection
            if current_scale < 0.99:
                gray_detect = cv2.resize(gray, (0, 0), fx=current_scale, fy=current_scale)
            else:
                gray_detect = gray

            if detector is not None:
                corners, ids, _ = detector.detectMarkers(gray_detect)
            else:
                corners, ids, _ = cv2.aruco.detectMarkers(gray_detect, dictionary, parameters=params)

            # Scale corner points back to full-resolution coordinates if downscaled
            if ids is not None and current_scale < 0.99:
                inv_scale = 1.0 / current_scale
                corners = [c * inv_scale for c in corners]

            centers = {}
            if ids is not None:
                for c, tag_id in zip(corners, ids.flatten()):
                    pts = c.reshape(4, 2)
                    cx, cy = pts.mean(axis=0)
                    centers[int(tag_id)] = (float(cx), float(cy))
                    trails[int(tag_id)].append((int(cx), int(cy)))
                    if log:
                        log.write(f"{frame_no},{tag_id},{cx:.1f},{cy:.1f}\n")

                    col = COLORS[int(tag_id) % len(COLORS)]
                    cv2.polylines(frame, [pts.astype(np.int32)], True, col, 2)
                    # Tag label
                    cv2.putText(frame, f"ID {tag_id} ({cx:.0f},{cy:.0f})",
                                (int(pts[0][0]), int(pts[0][1]) - 8),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 2)

            for tag_id, trail in trails.items():
                col = COLORS[tag_id % len(COLORS)]
                trail_pts = list(trail)
                for a, b in zip(trail_pts, trail_pts[1:]):
                    cv2.line(frame, a, b, col, 1)

            # Object position = centroid of all visible tags
            if centers:
                pts = np.array(list(centers.values()))
                ox, oy = pts.mean(axis=0)
                obj_trail.append((int(ox), int(oy)))
                cv2.drawMarker(frame, (int(ox), int(oy)), (255, 255, 255),
                               cv2.MARKER_CROSS, 25, 2)
                status = f"Tags: {len(centers)}/3  Object: ({ox:.0f},{oy:.0f})"
                if len(centers) >= 2:
                    ids_sorted = sorted(centers)
                    (x1, y1), (x2, y2) = centers[ids_sorted[0]], centers[ids_sorted[1]]
                    ang = math.degrees(math.atan2(y2 - y1, x2 - x1))
                    status += f"  Angle: {ang:.0f} deg"
            else:
                status = "No tags detected"

            obj_trail_pts = list(obj_trail)
            for a, b in zip(obj_trail_pts, obj_trail_pts[1:]):
                cv2.line(frame, a, b, (255, 255, 255), 2)

            # Draw status HUD overlay
            h, w = frame.shape[:2]
            cv2.rectangle(frame, (8, 8), (min(w - 8, 640), 64), (20, 20, 20), cv2.FILLED)
            mode_str = f"Fast ({current_scale:.1f}x)" if current_scale < 0.99 else "Full (1.0x)"
            hud_line1 = f"FPS: {fps:4.1f} | {status}"
            cv2.putText(frame, hud_line1, (14, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
            controls_hint = f"Cam {camera_idx} ({w}x{h}) | {mode_str} [f] | [s] Switch Cam | [c] Clear | [q] Quit"
            cv2.putText(frame, controls_hint, (14, 54), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (200, 200, 200), 1)

            cv2.imshow(window_name, frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("c"):
                trails.clear()
                obj_trail.clear()
            if key == ord("f"):
                current_scale = 1.0 if current_scale < 0.99 else 0.5
                print(f"[Performance] Switched detection scale to {current_scale}x.", flush=True)
            if key == ord("s"):
                cap.release()
                new_cap, new_idx = switch_camera(camera_idx)
                if new_cap is not None:
                    cap = new_cap
                    camera_idx = new_idx

            # Check if user closed the window
            if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
        for _ in range(5):
            cv2.waitKey(1)
        if log:
            log.close()


if __name__ == "__main__":
    main()
