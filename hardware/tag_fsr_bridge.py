"""Scalpel hardware bridge: AprilTag pose + ESP32 FSR pressure -> Unity (UDP).

The webcam tracks AprilTags 1, 2 and 3 on the scalpel handle. hardware/tracking.py fits them as one
rigid tool (position + angle, even with a tag hidden) and follows the cutting tip. The ESP32-C3 FSR
reports how hard the scalpel is pressed; Unity turns that into cut depth.

Install:  pip install opencv-python numpy pyserial
Run:      python hardware/tag_fsr_bridge.py --port COM3
No HW:    python hardware/tag_fsr_bridge.py --simulate   (mouse = position, hold left button = press)

ONE-TIME CALIBRATION (each takes a few seconds; results are saved in hardware/tracking_config.json)
  k   click the 4 corners of the practice area in the camera window: top-left, top-right,
      bottom-right, bottom-left. This removes perspective distortion. (Do this first.)
  l   hold the scalpel still with all 3 tags visible; it learns how the tags sit on the handle.
  t   touch the scalpel TIP to the centre of the practice area, then press t. This teaches the
      bridge where the cutting tip is relative to the tags.
Other keys: c zero the FSR (no pressure), z set the origin (only when no table is calibrated), q quit.

UDP packet (JSON, ~30+ Hz, default 127.0.0.1:5005), read by TagFsrInput.cs:
    {"x": 0..1, "y": 0..1, "force": 0..1, "tags": 0..3, "t": unix_seconds,
     "angle": degrees, "quality": 0..1}
x/y are the scalpel TIP position across the practice area (0,0 = top-left, y grows downward).
"""
import argparse
import json
import math
import os
import socket
import threading
import time

import cv2
import numpy as np

from tracking import OneEuro, ToolTracker

FAMILIES = {
    "16h5": cv2.aruco.DICT_APRILTAG_16h5,
    "25h9": cv2.aruco.DICT_APRILTAG_25h9,
    "36h10": cv2.aruco.DICT_APRILTAG_36h10,
    "36h11": cv2.aruco.DICT_APRILTAG_36h11,
}
HERE = os.path.dirname(os.path.abspath(__file__))


class ForceReader:
    """Reads 'F,<raw>' lines from the ESP32 and returns normalised force 0..1."""

    def __init__(self, port, baud, raw_max):
        import serial
        self.ser = serial.Serial(port, baud, timeout=0.1)
        self.raw_max = raw_max
        self.raw = 0
        self.zero = 0.0
        self._calib = []
        threading.Thread(target=self._run, daemon=True).start()

    def recalibrate(self):
        self._calib = []          # the next 30 samples define the no-touch baseline

    def _run(self):
        while True:
            try:
                line = self.ser.readline().decode(errors="ignore").strip()
                if line.startswith("F,"):
                    self.raw = int(line[2:])
                    if len(self._calib) < 30:
                        self._calib.append(self.raw)
                        self.zero = float(np.mean(self._calib))
            except (ValueError, OSError):
                pass

    @property
    def force(self):
        span = max(1.0, self.raw_max - self.zero)
        return float(np.clip((self.raw - self.zero) / span, 0, 1))


def open_camera(index, width, height):
    backend = cv2.CAP_DSHOW if hasattr(cv2, "CAP_DSHOW") else cv2.CAP_ANY
    cap = cv2.VideoCapture(index, backend)
    if not cap.isOpened():
        raise SystemExit(f"Cannot open camera {index}")
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))   # full frame rate at 720p
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    return cap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--family", default="36h11", choices=FAMILIES)
    ap.add_argument("--port", help="ESP32 serial port, e.g. COM3")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--fsr-max", type=int, default=3000, help="raw ADC value at hardest press")
    ap.add_argument("--table-mm", default="300x220", help="practice area size in mm, WIDTHxHEIGHT")
    ap.add_argument("--config", default=os.path.join(HERE, "tracking_config.json"))
    ap.add_argument("--camera-calib", help="optional .npz from hardware/camera_calibration.py")
    ap.add_argument("--min-cutoff", type=float, default=1.0, help="smoothing when still (lower = smoother)")
    ap.add_argument("--beta", type=float, default=8.0, help="responsiveness when moving (higher = less lag)")
    ap.add_argument("--span", type=float, default=0.5,
                    help="only without a table calibration: frame fraction that covers the full 0..1 range")
    ap.add_argument("--udp", default="127.0.0.1:5005")
    ap.add_argument("--simulate", action="store_true", help="mouse instead of camera + FSR")
    args = ap.parse_args()

    host, port = args.udp.split(":")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dest = (host, int(port))

    forcer = ForceReader(args.port, args.baud, args.fsr_max) if args.port else None
    if forcer:
        forcer.recalibrate()

    tracker = ToolTracker()
    tracker.table_mm = tuple(float(v) for v in args.table_mm.lower().split("x"))
    if os.path.exists(args.config):
        tracker.load(args.config)
        print(f"Loaded calibration from {args.config}")
    lens = np.load(args.camera_calib) if args.camera_calib else None

    cap = detector = None
    if not args.simulate:
        params = cv2.aruco.DetectorParameters()
        params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        detector = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(FAMILIES[args.family]), params)
        cap = open_camera(args.camera, args.width, args.height)

    state = {"picking": [], "mouse": [0.5, 0.5], "down": False, "force": 0.0, "note": ""}

    def on_mouse(ev, mx, my, flags, _):
        if args.simulate:
            state["mouse"] = [mx / 400, my / 400]
            if ev == cv2.EVENT_LBUTTONDOWN:
                state["down"] = True
            elif ev == cv2.EVENT_LBUTTONUP:
                state["down"] = False
        elif ev == cv2.EVENT_LBUTTONDOWN and state["pick_active"]:
            state["picking"].append((mx, my))
    state["pick_active"] = False
    cv2.namedWindow("Bridge")
    cv2.setMouseCallback("Bridge", on_mouse)

    tip_filter = OneEuro(args.min_cutoff, args.beta)
    origin = np.array([0.5, 0.5])          # only used when no table calibration exists
    norm = np.array([0.5, 0.5])
    pos = np.array([0.5, 0.5])
    angle_deg, quality, tags = 0.0, 0.0, 0
    force_smooth = 0.0
    jump_streak = 0
    last = time.time()

    while True:
        now = time.time()
        dt, last = now - last, now
        view = np.zeros((400, 400, 3), np.uint8)

        if args.simulate:
            state["force"] = min(1.0, state["force"] + dt * 0.4) if state["down"] else 0.0
            target, force, tags, quality = np.array(state["mouse"]), state["force"], 3, 1.0
        else:
            ok, frame = cap.read()
            if not ok:
                break
            fh, fw = frame.shape[:2]
            corners, ids, _ = detector.detectMarkers(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
            dets = {}
            if ids is not None:
                for c, i in zip(corners, ids.flatten()):
                    if int(i) in tracker.tag_ids:
                        pts = c.reshape(4, 2)
                        cv2.polylines(frame, [pts.astype(int)], True, (0, 255, 0), 2)
                        cv2.putText(frame, f"ID {i}", tuple(pts[0].astype(int)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                        if lens is not None:                        # remove lens distortion
                            pts = cv2.undistortPoints(pts.reshape(-1, 1, 2), lens["K"], lens["dist"],
                                                      P=lens["K"]).reshape(4, 2)
                        dets[int(i)] = pts

            # ---- calibration steps
            if tracker.learning and tracker.feed_learning(dets):
                tracker.save(args.config)
                state["note"] = "Layout learned. Now touch the TIP to the table centre and press t."
            if len(state["picking"]) == 4:
                tracker.set_table(state["picking"], tracker.table_mm)
                tracker.layout, tracker.tip_local = None, np.zeros(2)     # plane changed, relearn
                tracker.save(args.config)
                state["picking"], state["pick_active"] = [], False
                state["note"] = "Table set. Hold the scalpel still and press l to learn the tag layout."

            pose = tracker.estimate(dets)
            tags = pose["tags"] if pose else 0
            if pose:
                quality, angle_deg = pose["quality"], math.degrees(pose["theta"])
                tip = pose["tip"]
                if tracker.homography is not None:
                    target = tip / np.array(tracker.table_mm)
                else:
                    target = 0.5 + (tip / np.array([fw, fh]) - origin) / max(args.span, 1e-3)
                norm = tip / np.array([fw, fh])
                if tracker.homography is None:
                    cv2.drawMarker(frame, tuple(tip.astype(int)), (0, 255, 255), cv2.MARKER_CROSS, 28, 2)
            else:
                target, quality = pos, 0.0
            force = forcer.force if forcer else 0.0

            # table outline + status
            if tracker.homography is not None:
                inv = np.linalg.inv(tracker.homography)
                w, h = tracker.table_mm
                box = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
                box_px = cv2.perspectiveTransform(box.reshape(-1, 1, 2), inv).reshape(4, 2)
                cv2.polylines(frame, [box_px.astype(int)], True, (255, 200, 0), 2)
                if pose:
                    tip_px = cv2.perspectiveTransform(np.float32([pose["tip"]]).reshape(1, 1, 2), inv).reshape(2)
                    cv2.drawMarker(frame, tuple(tip_px.astype(int)), (0, 255, 255), cv2.MARKER_CROSS, 28, 2)
            for p in state["picking"]:
                cv2.circle(frame, p, 6, (0, 0, 255), -1)
            steps = [("table", tracker.homography is not None), ("layout", tracker.layout is not None),
                     ("tip", bool(np.any(tracker.tip_local)))]
            cv2.putText(frame, "calibrated: " + "  ".join(f"{n}:{'OK' if v else 'no'}" for n, v in steps),
                        (8, fh - 40), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
            if state["picking"] or state["pick_active"]:
                cv2.putText(frame, f"click table corners TL, TR, BR, BL ({len(state['picking'])}/4)",
                            (8, fh - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2)
            elif tracker.learning:
                cv2.putText(frame, "learning layout - hold still, all 3 tags visible",
                            (8, fh - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2)
            elif state["note"]:
                cv2.putText(frame, state["note"], (8, fh - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 200, 255), 2)
            view = frame

        # ---- filtering and outlier gate
        if np.linalg.norm(target - pos) > 0.4 and jump_streak < 3 and not args.simulate:
            jump_streak += 1                                  # ignore a lone, implausible jump
        else:
            jump_streak = 0
            pos = tip_filter(target, now) if tags > 0 or args.simulate else pos
        force_smooth += 0.6 * (force - force_smooth)

        msg = {"x": round(float(np.clip(pos[0], 0, 1)), 4), "y": round(float(np.clip(pos[1], 0, 1)), 4),
               "force": round(float(force_smooth), 4), "tags": tags, "t": now,
               "angle": round(angle_deg, 1), "quality": round(float(quality), 3)}
        sock.sendto(json.dumps(msg).encode(), dest)

        cv2.putText(view, f"tags={tags} q={quality:.2f} force={force_smooth:.2f} pos=({pos[0]:.3f},{pos[1]:.3f})",
                    (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
        cv2.imshow("Bridge", view)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord("k") and not args.simulate:
            state["picking"], state["pick_active"] = [], True
            state["note"] = ""
        if key == ord("l") and not args.simulate:
            tracker.start_learning(30)
        if key == ord("t") and not args.simulate and tracker.last:
            if tracker.layout is None:
                state["note"] = "Learn the layout first (l)."
            else:
                centre = np.array(tracker.table_mm) / 2 if tracker.homography is not None \
                    else np.array([frame.shape[1], frame.shape[0]]) / 2
                tracker.calibrate_tip(tracker.last, centre)
                tracker.save(args.config)
                state["note"] = "Tip calibrated and saved."
        if key == ord("z") and not args.simulate:
            origin = norm.copy()
        if key == ord("c") and forcer:
            forcer.recalibrate()

    if cap:
        cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
