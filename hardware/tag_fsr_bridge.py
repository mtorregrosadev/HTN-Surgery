"""Scalpel hardware bridge: AprilTag position + ESP32 FSR pressure -> Unity (UDP).

The webcam tracks AprilTags 1, 2 and 3 on the scalpel handle (their centroid is the
scalpel's x/y position over the training surface). The ESP32-C3 FSR reports how hard
the scalpel is pressed; Unity turns that into cut depth.

Install:  pip install opencv-python numpy pyserial
Run:      python hardware/tag_fsr_bridge.py --port COM3
No HW:    python hardware/tag_fsr_bridge.py --simulate   (mouse = position, hold left button = press)
Keys:     q quit, z set the current tag position as the origin (0,0), c re-zero the FSR

UDP packet (JSON, ~30 Hz, default 127.0.0.1:5005), read by TagFsrInput.cs:
    {"x": 0..1, "y": 0..1, "force": 0..1, "tags": 0..3, "t": unix_seconds}
x/y are camera-frame coordinates re-centred on the origin (0.5, 0.5 = origin), where the
frame fraction given by --span maps to the full 0..1 range. y grows downward.
"""
import argparse
import json
import socket
import threading
import time

import cv2
import numpy as np

FAMILIES = {
    "16h5": cv2.aruco.DICT_APRILTAG_16h5,
    "25h9": cv2.aruco.DICT_APRILTAG_25h9,
    "36h10": cv2.aruco.DICT_APRILTAG_36h10,
    "36h11": cv2.aruco.DICT_APRILTAG_36h11,
}
TAG_IDS = (1, 2, 3)


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--family", default="36h11", choices=FAMILIES)
    ap.add_argument("--port", help="ESP32 serial port, e.g. COM3")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--fsr-max", type=int, default=3000, help="raw ADC value at hardest press")
    ap.add_argument("--span", type=float, default=0.5,
                    help="fraction of the camera frame that maps to the full 0..1 range")
    ap.add_argument("--udp", default="127.0.0.1:5005")
    ap.add_argument("--simulate", action="store_true", help="mouse instead of camera + FSR")
    args = ap.parse_args()

    host, port = args.udp.split(":")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dest = (host, int(port))

    forcer = ForceReader(args.port, args.baud, args.fsr_max) if args.port else None
    if forcer:
        forcer.recalibrate()

    cap = detector = None
    if not args.simulate:
        params = cv2.aruco.DetectorParameters()
        params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        detector = cv2.aruco.ArucoDetector(
            cv2.aruco.getPredefinedDictionary(FAMILIES[args.family]), params)
        backend = cv2.CAP_DSHOW if hasattr(cv2, "CAP_DSHOW") else cv2.CAP_ANY
        cap = cv2.VideoCapture(args.camera, backend)
        if not cap.isOpened():
            raise SystemExit(f"Cannot open camera {args.camera}")

    mouse = {"x": 0.5, "y": 0.5, "down": False, "force": 0.0}
    if args.simulate:
        def on_mouse(ev, mx, my, flags, _):
            mouse["x"], mouse["y"] = mx / 400, my / 400
            if ev == cv2.EVENT_LBUTTONDOWN:
                mouse["down"] = True
            elif ev == cv2.EVENT_LBUTTONUP:
                mouse["down"] = False
        cv2.namedWindow("Bridge")
        cv2.setMouseCallback("Bridge", on_mouse)

    raw_pos = np.array([0.5, 0.5])      # tag centroid, normalised frame coordinates
    origin = np.array([0.5, 0.5])
    pos = np.array([0.5, 0.5])
    force_smooth = 0.0
    tags = 0
    last = time.time()

    while True:
        now = time.time()
        dt, last = now - last, now
        view = np.zeros((400, 400, 3), np.uint8)

        if args.simulate:
            mouse["force"] = min(1.0, mouse["force"] + dt * 0.4) if mouse["down"] else 0.0
            raw_pos = np.array([mouse["x"], mouse["y"]])
            force, tags = mouse["force"], 3
        else:
            ok, frame = cap.read()
            if not ok:
                break
            h, w = frame.shape[:2]
            corners, ids, _ = detector.detectMarkers(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
            centers = []
            if ids is not None:
                for c, i in zip(corners, ids.flatten()):
                    if int(i) in TAG_IDS:
                        p = c.reshape(4, 2)
                        centers.append(p.mean(axis=0))
                        cv2.polylines(frame, [p.astype(int)], True, (0, 255, 0), 2)
                        cv2.putText(frame, f"ID {i}", tuple(p[0].astype(int)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            tags = len(centers)
            if centers:
                c = np.mean(centers, axis=0)
                raw_pos = np.array([c[0] / w, c[1] / h])
            force = forcer.force if forcer else 0.0
            view = frame

        target = 0.5 + (raw_pos - origin) / max(args.span, 1e-3)
        pos = pos + 0.5 * (target - pos)                    # light smoothing
        force_smooth += 0.6 * (force - force_smooth)

        msg = {"x": round(float(np.clip(pos[0], 0, 1)), 4),
               "y": round(float(np.clip(pos[1], 0, 1)), 4),
               "force": round(float(force_smooth), 4), "tags": tags, "t": now}
        sock.sendto(json.dumps(msg).encode(), dest)

        cv2.putText(view, f"tags={tags} force={force_smooth:.2f} pos=({pos[0]:.2f},{pos[1]:.2f})",
                    (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
        cv2.imshow("Bridge", view)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord("z"):
            origin = raw_pos.copy()
        if key == ord("c") and forcer:
            forcer.recalibrate()

    if cap:
        cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
