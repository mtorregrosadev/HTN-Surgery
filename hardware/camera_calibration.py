"""Optional lens calibration for the webcam (removes barrel/pincushion distortion).

Print a chessboard (default 9x6 inner corners, any square size) and keep it flat, e.g. taped to a book.

Run:   python hardware/camera_calibration.py --camera 0
Keys:  space = capture a view (aim for 15+, tilt and move the board around, cover the corners of the image)
       c     = calibrate and save,   q = quit
Then:  python hardware/tag_fsr_bridge.py --camera-calib hardware/camera_calib.npz ...

The .npz holds K (camera matrix) and dist (distortion coefficients). The reported RMS reprojection
error should be under about 0.5 px; if it is much higher, retake the views with a flatter board.
"""
import argparse
import os

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--cols", type=int, default=9, help="inner corners across")
    ap.add_argument("--rows", type=int, default=6, help="inner corners down")
    ap.add_argument("--out", default=os.path.join(HERE, "camera_calib.npz"))
    args = ap.parse_args()

    backend = cv2.CAP_DSHOW if hasattr(cv2, "CAP_DSHOW") else cv2.CAP_ANY
    cap = cv2.VideoCapture(args.camera, backend)
    if not cap.isOpened():
        raise SystemExit(f"Cannot open camera {args.camera}")
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)

    pattern = (args.cols, args.rows)
    grid = np.zeros((args.rows * args.cols, 3), np.float32)
    grid[:, :2] = np.mgrid[0:args.cols, 0:args.rows].T.reshape(-1, 2)      # square units; scale is irrelevant here
    object_points, image_points, size = [], [], None
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 0.001)

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        size = gray.shape[::-1]
        found, corners = cv2.findChessboardCorners(gray, pattern)
        shown = frame.copy()
        if found:
            corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
            cv2.drawChessboardCorners(shown, pattern, corners, found)
        cv2.putText(shown, f"views: {len(image_points)}   space=capture  c=calibrate  q=quit",
                    (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        cv2.imshow("Camera calibration", shown)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord(" ") and found:
            object_points.append(grid)
            image_points.append(corners)
        if key == ord("c"):
            if len(image_points) < 8:
                print("Capture at least 8 views first (15+ is better).")
                continue
            rms, k, dist, _, _ = cv2.calibrateCamera(object_points, image_points, size, None, None)
            np.savez(args.out, K=k, dist=dist)
            print(f"Saved {args.out}   RMS reprojection error: {rms:.3f} px")
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
