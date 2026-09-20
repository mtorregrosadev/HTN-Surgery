"""Track one existing AprilTag 36h11 as a six-DoF training stylus.

The bridge owns the webcam and sends camera-space tag poses to Unity over UDP.
Unity performs the one-pose workspace registration and then routes normalized
samples through the Scalpel controller -> API -> SOFA path.

Run:
    python hardware/single_tag_stylus_bridge.py --tag-size-mm 50

The first visible 36h11 tag is selected automatically. Use --tag-id only when
several tags can appear in the camera image.
"""
from __future__ import annotations

import argparse
import json
import math
import socket
import time

import cv2
import numpy as np


CAMERA_TO_UNITY = np.diag([1.0, -1.0, 1.0])
TAG_TO_UNITY = np.diag([1.0, 1.0, -1.0])


def camera_matrix(width: int, height: int, horizontal_fov_deg: float) -> np.ndarray:
    focal = width / (2.0 * math.tan(math.radians(horizontal_fov_deg) / 2.0))
    return np.array(
        [[focal, 0.0, width / 2.0], [0.0, focal, height / 2.0], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )


def tag_object_points(tag_size_metres: float) -> np.ndarray:
    half = tag_size_metres / 2.0
    # Required ordering for SOLVEPNP_IPPE_SQUARE: TL, TR, BR, BL.
    return np.array(
        [[-half, half, 0.0], [half, half, 0.0],
         [half, -half, 0.0], [-half, -half, 0.0]],
        dtype=np.float64,
    )


def rotation_matrix_to_quaternion(matrix: np.ndarray) -> np.ndarray:
    """Return normalized x,y,z,w quaternion for a proper 3x3 rotation."""
    m = np.asarray(matrix, dtype=np.float64)
    trace = float(np.trace(m))
    if trace > 0.0:
        scale = math.sqrt(trace + 1.0) * 2.0
        q = np.array(
            [(m[2, 1] - m[1, 2]) / scale,
             (m[0, 2] - m[2, 0]) / scale,
             (m[1, 0] - m[0, 1]) / scale,
             0.25 * scale]
        )
    else:
        axis = int(np.argmax(np.diag(m)))
        if axis == 0:
            scale = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2.0
            q = np.array([0.25 * scale, (m[0, 1] + m[1, 0]) / scale,
                          (m[0, 2] + m[2, 0]) / scale,
                          (m[2, 1] - m[1, 2]) / scale])
        elif axis == 1:
            scale = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2.0
            q = np.array([(m[0, 1] + m[1, 0]) / scale, 0.25 * scale,
                          (m[1, 2] + m[2, 1]) / scale,
                          (m[0, 2] - m[2, 0]) / scale])
        else:
            scale = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2.0
            q = np.array([(m[0, 2] + m[2, 0]) / scale,
                          (m[1, 2] + m[2, 1]) / scale, 0.25 * scale,
                          (m[1, 0] - m[0, 1]) / scale])
    norm = float(np.linalg.norm(q))
    if norm <= 1e-12:
        raise ValueError("pose produced an invalid rotation")
    return q / norm


def estimate_pose(
    corners: np.ndarray,
    tag_size_metres: float,
    intrinsics: np.ndarray,
    distortion: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, float] | None:
    points = tag_object_points(tag_size_metres)
    image_points = np.asarray(corners, dtype=np.float64).reshape(4, 2)
    success, rvec, tvec = cv2.solvePnP(
        points, image_points, intrinsics, distortion,
        flags=cv2.SOLVEPNP_IPPE_SQUARE,
    )
    if not success or float(tvec.reshape(3)[2]) <= 0.0:
        return None

    rotation_cv, _ = cv2.Rodrigues(rvec)
    rotation_unity = CAMERA_TO_UNITY @ rotation_cv @ TAG_TO_UNITY
    position_unity = CAMERA_TO_UNITY @ tvec.reshape(3)
    quaternion = rotation_matrix_to_quaternion(rotation_unity)

    projected, _ = cv2.projectPoints(points, rvec, tvec, intrinsics, distortion)
    residual = projected.reshape(4, 2) - image_points
    rms_px = float(np.sqrt(np.mean(np.sum(residual * residual, axis=1))))
    return position_unity, quaternion, rms_px


def open_camera(index: int, width: int, height: int, fps: int):
    backend = cv2.CAP_AVFOUNDATION if hasattr(cv2, "CAP_AVFOUNDATION") else cv2.CAP_ANY
    capture = cv2.VideoCapture(index, backend)
    if not capture.isOpened():
        raise SystemExit(
            f"Cannot open camera {index}. On macOS, allow camera access for Terminal."
        )
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    capture.set(cv2.CAP_PROP_FPS, fps)
    return capture


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--tag-id", type=int, help="default: lock onto first visible tag")
    parser.add_argument("--tag-size-mm", type=float, default=50.0)
    parser.add_argument("--fov-deg", type=float, default=60.0, help="horizontal webcam FOV")
    parser.add_argument("--camera-calib", help="optional .npz produced by camera_calibration.py")
    parser.add_argument("--udp", default="127.0.0.1:5005")
    args = parser.parse_args()

    if args.tag_size_mm <= 0:
        raise SystemExit("--tag-size-mm must be the measured black-square width")

    host, port_text = args.udp.rsplit(":", 1)
    destination = (host, int(port_text))
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    capture = open_camera(args.camera, args.width, args.height, args.fps)

    parameters = cv2.aruco.DetectorParameters()
    parameters.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    detector = cv2.aruco.ArucoDetector(
        cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11),
        parameters,
    )
    calibration = np.load(args.camera_calib) if args.camera_calib else None
    locked_id = args.tag_id
    print("Looking for AprilTag 36h11" +
          (f" ID {locked_id}" if locked_id is not None else " (first visible ID)"))
    print("Press q in the camera window to stop.")

    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                raise SystemExit("Camera stopped returning frames")
            height, width = frame.shape[:2]
            intrinsics = calibration["K"] if calibration is not None else camera_matrix(
                width, height, args.fov_deg
            )
            distortion = calibration["dist"] if calibration is not None else np.zeros(5)
            corners, ids, _ = detector.detectMarkers(
                cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            )

            chosen = None
            visible_ids = [] if ids is None else [int(value) for value in ids.flatten()]
            if locked_id is None and visible_ids:
                areas = [abs(cv2.contourArea(item.reshape(4, 2))) for item in corners]
                locked_id = visible_ids[int(np.argmax(areas))]
                print(f"Locked onto AprilTag 36h11 ID {locked_id}")
            if locked_id is not None and locked_id in visible_ids:
                chosen = corners[visible_ids.index(locked_id)].reshape(4, 2)

            packet = {
                "mode": "pose6d",
                "family": "36h11",
                "tagId": locked_id if locked_id is not None else -1,
                "tagSizeMm": args.tag_size_mm,
                "tags": 0,
                "t": time.time(),
            }
            status = "NO TAG"
            if chosen is not None:
                pose = estimate_pose(
                    chosen, args.tag_size_mm / 1000.0, intrinsics, distortion
                )
                if pose is not None:
                    position, quaternion, rms_px = pose
                    quality = max(0.0, min(1.0, 1.0 - rms_px / 8.0))
                    packet.update({
                        "tags": 1,
                        "px": round(float(position[0]), 6),
                        "py": round(float(position[1]), 6),
                        "pz": round(float(position[2]), 6),
                        "qx": round(float(quaternion[0]), 7),
                        "qy": round(float(quaternion[1]), 7),
                        "qz": round(float(quaternion[2]), 7),
                        "qw": round(float(quaternion[3]), 7),
                        "quality": round(quality, 3),
                        "rmsPx": round(rms_px, 3),
                    })
                    status = f"ID {locked_id}  6-DoF  rms={rms_px:.2f}px"
                    cv2.polylines(frame, [chosen.astype(int)], True, (0, 255, 0), 2)
            sender.sendto(json.dumps(packet).encode("utf-8"), destination)

            cv2.putText(
                frame, status, (12, 28), cv2.FONT_HERSHEY_SIMPLEX,
                0.7, (0, 255, 0) if chosen is not None else (0, 0, 255), 2,
            )
            cv2.imshow("Surge Prep — one 36h11 stylus", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        capture.release()
        sender.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
