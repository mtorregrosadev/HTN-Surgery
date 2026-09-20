"""Track an object carrying AprilTags with a webcam.

Install:  pip install opencv-python numpy
Run:      python new.py [--camera 1] [--family 36h11] [--csv log.csv]
Keys:     q / Esc = quit, s = switch camera, c = clear trails
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
COLORS = [(0, 0, 255), (0, 200, 0), (255, 100, 0), (0, 200, 255), (255, 0, 255)]
TRAIL_LEN = 60
MAX_WARMUP_FRAMES = 12
MAX_CONSECUTIVE_DROPS = 30


def check_stream_active(cap, attempts=MAX_WARMUP_FRAMES):
    """Read a few frames to warm up sensor and check if the feed contains actual image data."""
    for _ in range(attempts):
        ok, frame = cap.read()
        if ok and frame is not None and frame.size > 0:
            # Check whether image has non-trivial contrast (not a blank/black continuity dummy stream)
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

        # Store the first camera that at least opened (even if black) as a fallback
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


def main():
    ap = argparse.ArgumentParser(description="Track AprilTags in real time using webcam")
    ap.add_argument("--camera", type=int, default=None, help="Camera device index (default: auto-detect active camera)")
    ap.add_argument("--family", choices=FAMILIES, default="36h11", help="AprilTag dictionary family")
    ap.add_argument("--csv", help="Optional path to log positions")
    args = ap.parse_args()

    dictionary = cv2.aruco.getPredefinedDictionary(FAMILIES[args.family])
    params = cv2.aruco.DetectorParameters()
    if hasattr(cv2.aruco, "CORNER_REFINE_APRILTAG"):
        params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_APRILTAG
    elif hasattr(cv2.aruco, "CORNER_REFINE_SUBPIX"):
        params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX

    detector = None
    if hasattr(cv2.aruco, "ArucoDetector"):
        detector = cv2.aruco.ArucoDetector(dictionary, params)

    cap, camera_idx = select_best_camera(args.camera)
    if cap is None:
        raise SystemExit("Error: Unable to open any video capture device.")

    trails = defaultdict(lambda: deque(maxlen=TRAIL_LEN))
    obj_trail = deque(maxlen=TRAIL_LEN)
    log = open(args.csv, "w") if args.csv else None
    if log:
        log.write("frame,tag_id,x,y\n")
    frame_no = 0
    consecutive_drops = 0

    print("AprilTag tracker running.", flush=True)
    print("Controls: 'q' or Esc = Quit | 's' = Switch camera | 'c' = Clear trails", flush=True)
    window_name = "AprilTag tracker"

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                consecutive_drops += 1
                if consecutive_drops >= MAX_CONSECUTIVE_DROPS:
                    print(f"Warning: Stream lost after {MAX_CONSECUTIVE_DROPS} consecutive failed reads. Exiting.")
                    break
                time.sleep(0.02)
                continue
            consecutive_drops = 0

            frame_no += 1
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            if detector is not None:
                corners, ids, _ = detector.detectMarkers(gray)
            else:
                corners, ids, _ = cv2.aruco.detectMarkers(gray, dictionary, parameters=params)

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
            cv2.rectangle(frame, (8, 8), (min(w - 8, 620), 62), (20, 20, 20), cv2.FILLED)
            cv2.putText(frame, status, (14, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 255, 255), 2)
            controls_hint = f"Camera {camera_idx} ({w}x{h}) | [s] Switch Cam | [c] Clear | [q] Quit"
            cv2.putText(frame, controls_hint, (14, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (200, 200, 200), 1)

            cv2.imshow(window_name, frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("c"):
                trails.clear()
                obj_trail.clear()
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
