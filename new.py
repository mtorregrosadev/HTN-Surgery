"""Track an object carrying 3 AprilTags with a webcam.

Install:  pip install opencv-python numpy
Run:      python apriltag_tracker.py [--camera 0] [--family 36h11]
Keys:     q = quit, c = clear trails
"""
import argparse
import math
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--family", choices=FAMILIES, default="36h11")
    ap.add_argument("--csv", help="optional path to log positions")
    args = ap.parse_args()

    params = cv2.aruco.DetectorParameters()
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    detector = cv2.aruco.ArucoDetector(
        cv2.aruco.getPredefinedDictionary(FAMILIES[args.family]), params
    )

    cap = cv2.VideoCapture(args.camera, cv2.CAP_DSHOW)
    if not cap.isOpened():
        raise SystemExit(f"Cannot open camera {args.camera}")

    trails = defaultdict(lambda: deque(maxlen=TRAIL_LEN))
    obj_trail = deque(maxlen=TRAIL_LEN)
    log = open(args.csv, "w") if args.csv else None
    if log:
        log.write("frame,tag_id,x,y\n")
    frame_no = 0

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame_no += 1
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = detector.detectMarkers(gray)

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
                cv2.polylines(frame, [pts.astype(int)], True, col, 2)
                # tag "up" direction (from corner 0->1 edge = tag x-axis)
                cv2.putText(frame, f"ID {tag_id} ({cx:.0f},{cy:.0f})",
                            (int(pts[0][0]), int(pts[0][1]) - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 2)

        for tag_id, trail in trails.items():
            col = COLORS[tag_id % len(COLORS)]
            for a, b in zip(trail, list(trail)[1:]):
                cv2.line(frame, a, b, col, 1)

        # Object position = centroid of all visible tags (works even if
        # one or two are occluded). Heading uses first two visible tags.
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
        for a, b in zip(obj_trail, list(obj_trail)[1:]):
            cv2.line(frame, a, b, (255, 255, 255), 2)

        cv2.putText(frame, status, (10, 25), cv2.FONT_HERSHEY_SIMPLEX,
                    0.65, (0, 255, 255), 2)
        cv2.imshow("AprilTag tracker", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord("c"):
            trails.clear()
            obj_trail.clear()

    cap.release()
    cv2.destroyAllWindows()
    if log:
        log.close()


if __name__ == "__main__":
    main()
