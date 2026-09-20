"""Track an object carrying 3 AprilTags with a webcam.

Install:  pip install opencv-python numpy
Run:      python new.py [--camera 0] [--family 36h11] [--csv log.csv]
Keys:     q / Esc = quit, c = clear trails
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
MAX_WARMUP_FRAMES = 15
MAX_CONSECUTIVE_DROPS = 30


def open_camera(preferred_index=0):
    """Open a camera using a platform-appropriate backend with warmup and auto-fallback."""
    candidates = [preferred_index] + [i for i in range(5) if i != preferred_index]
    backends = [cv2.CAP_DSHOW, cv2.CAP_ANY] if sys.platform.startswith("win") else [cv2.CAP_ANY]

    for idx in candidates:
        for backend in backends:
            try:
                cap = cv2.VideoCapture(idx, backend) if backend != cv2.CAP_ANY else cv2.VideoCapture(idx)
            except Exception:
                continue

            if not cap.isOpened():
                cap.release()
                continue

            # Warmup: some cameras (e.g. macOS AVFoundation/Continuity) need several frames to produce data
            ready = False
            for _ in range(MAX_WARMUP_FRAMES):
                ok, test_frame = cap.read()
                if ok and test_frame is not None and test_frame.size > 0:
                    ready = True
                    break
                time.sleep(0.05)

            if ready:
                if idx != preferred_index:
                    print(f"[Camera] Preferred camera {preferred_index} was unavailable; using working camera index {idx}.")
                else:
                    print(f"[Camera] Successfully opened camera index {idx}.")
                return cap, idx

            cap.release()

    return None, None


def main():
    ap = argparse.ArgumentParser(description="Track AprilTags in real time using webcam")
    ap.add_argument("--camera", type=int, default=0, help="Camera device index (default: 0 with auto-fallback)")
    ap.add_argument("--family", choices=FAMILIES, default="36h11", help="AprilTag dictionary family")
    ap.add_argument("--csv", help="Optional path to log positions")
    args = ap.parse_args()

    dictionary = cv2.aruco.getPredefinedDictionary(FAMILIES[args.family])
    params = cv2.aruco.DetectorParameters()
    if hasattr(cv2.aruco, "CORNER_REFINE_SUBPIX"):
        params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX

    detector = None
    if hasattr(cv2.aruco, "ArucoDetector"):
        detector = cv2.aruco.ArucoDetector(dictionary, params)

    cap, camera_idx = open_camera(args.camera)
    if cap is None:
        raise SystemExit(f"Error: Unable to open camera {args.camera} or find an active video input.")

    trails = defaultdict(lambda: deque(maxlen=TRAIL_LEN))
    obj_trail = deque(maxlen=TRAIL_LEN)
    log = open(args.csv, "w") if args.csv else None
    if log:
        log.write("frame,tag_id,x,y\n")
    frame_no = 0
    consecutive_drops = 0

    print("AprilTag tracker running. Press 'q' or 'Esc' to exit, 'c' to clear trails.")
    window_name = f"AprilTag tracker (Camera {camera_idx})"

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
                    # tag "up" direction (from corner 0->1 edge = tag x-axis)
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
                status = f"Tags: {len(centers)}  Object: ({ox:.0f},{oy:.0f})"
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

            # Draw status overlay
            cv2.rectangle(frame, (8, 8), (480, 36), (0, 0, 0), cv2.FILLED)
            cv2.putText(frame, status, (12, 28), cv2.FONT_HERSHEY_SIMPLEX,
                        0.6, (0, 255, 255), 2)

            cv2.imshow(window_name, frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("c"):
                trails.clear()
                obj_trail.clear()

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
