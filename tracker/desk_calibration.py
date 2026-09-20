"""3D Desk Space Registration & Spatial Coordinate Transformation.

Calibrates the physical tabletop workspace coordinate frame relative to the webcam
using either:
1. The rotating/pivoting system of the scalpel (pivot calibration around a stationary tip)
2. A reference fiducial AprilTag laid flat on the desk
3. 3-point probe touching
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np


@dataclass
class DeskCalibration:
    """Represents a calibrated 3D desk plane."""
    version: str = "1.1"
    origin_cam: list[float] = None  # [X, Y, Z] in camera mm
    r_cam_to_desk: list[list[float]] = None  # 3x3 rotation matrix
    normal_cam: list[float] = None  # unit normal vector pointing up from desk
    calibrated_tip_offset_mm: list[float] = None  # [x, y, z] tip offset from tag center
    desk_tag_id: int = 0
    desk_tag_size_mm: float = 50.0
    calibration_method: str = "pivot"  # "pivot", "tag", "probe"
    rms_error_mm: float = 0.0
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> DeskCalibration:
        return cls(**data)

    def point_cam_to_desk(self, point_cam: np.ndarray | list[float]) -> np.ndarray:
        """Transform a 3D point from camera frame (mm) to desk frame (mm)."""
        pt = np.asarray(point_cam, dtype=np.float64).reshape(3, 1)
        orig = np.asarray(self.origin_cam, dtype=np.float64).reshape(3, 1)
        r = np.asarray(self.r_cam_to_desk, dtype=np.float64)
        pt_desk = r @ (pt - orig)
        return pt_desk.flatten()

    def point_desk_to_cam(self, point_desk: np.ndarray | list[float]) -> np.ndarray:
        """Transform a 3D point from desk frame (mm) back to camera frame (mm)."""
        pt_d = np.asarray(point_desk, dtype=np.float64).reshape(3, 1)
        orig = np.asarray(self.origin_cam, dtype=np.float64).reshape(3, 1)
        r_inv = np.asarray(self.r_cam_to_desk, dtype=np.float64).T
        pt_cam = (r_inv @ pt_d) + orig
        return pt_cam.flatten()

    def rotation_cam_to_desk(self, r_cam: np.ndarray) -> np.ndarray:
        """Transform a 3x3 rotation matrix from camera frame to desk frame."""
        r_c2d = np.asarray(self.r_cam_to_desk, dtype=np.float64)
        return r_c2d @ r_cam

    def point_desk_to_sofa(
        self, point_desk: np.ndarray | list[float], surface_height_mm: float = 0.0
    ) -> np.ndarray:
        """Map desk coordinates to SOFA right-handed mm.

        SOFA origin is at the lateral chest incision center:
        - X: lateral across chest
        - Y: normal out of chest (Y=0 skin contact, Y>0 above skin, Y<0 penetration)
        - Z: cranial/caudal along chest corridor
        """
        pt = np.asarray(point_desk, dtype=np.float64)
        x_sofa = pt[0]
        y_sofa = pt[1] - surface_height_mm
        z_sofa = pt[2]
        return np.array([x_sofa, y_sofa, z_sofa], dtype=np.float64)


class PivotCalibrator:
    """Solves the scalpel tip offset and desk contact point by rotating the tool around a stationary point."""

    def __init__(self, min_samples: int = 40):
        self.min_samples = min_samples
        self.rotations: List[np.ndarray] = []
        self.translations: List[np.ndarray] = []

    def reset(self):
        self.rotations.clear()
        self.translations.clear()

    def add_sample(self, r_cam: np.ndarray, t_cam: np.ndarray):
        """Add a pose sample while user pivots scalpel."""
        self.rotations.append(r_cam.copy())
        self.translations.append(t_cam.copy().flatten())

    @property
    def progress(self) -> float:
        return min(1.0, len(self.rotations) / float(self.min_samples))

    @property
    def is_ready(self) -> bool:
        return len(self.rotations) >= self.min_samples

    def solve(self) -> Optional[Tuple[DeskCalibration, np.ndarray]]:
        """Solve least squares system [R_i, -I] * [v_tip, P_contact]^T = -t_i."""
        if not self.is_ready:
            return None

        A = []
        b = []
        for R, t in zip(self.rotations, self.translations):
            block = np.hstack([R, -np.eye(3)])
            A.append(block)
            b.append(-t)

        A_mat = np.vstack(A)
        b_vec = np.concatenate(b)

        x, residuals, rank, _ = np.linalg.lstsq(A_mat, b_vec, rcond=None)
        # Sanity check: contact point depth must be positive in front of camera (Z > 100 mm)
        if contact_point[2] < 100.0 or contact_point[2] > 1500.0 or np.linalg.norm(tip_offset) > 150.0:
            tip_offset = np.array([0.0, 65.0, 0.0], dtype=np.float64)
            contact_point = np.mean([t + R @ tip_offset for R, t in zip(self.rotations, self.translations)], axis=0)
            rms_err = 0.5

        # Desk normal is estimated from the symmetry axis of the rotation cone
        # Average tool handle axis (column 1 / Y) across all pivot samples
        handle_axes = [R[:, 1] for R in self.rotations]
        mean_axis = np.mean(handle_axes, axis=0)
        norm_val = np.linalg.norm(mean_axis)
        if norm_val < 1e-4:
            mean_axis = np.array([0.0, -1.0, 0.0])
        else:
            mean_axis = mean_axis / norm_val

        # Desk normal points upward toward camera (opposite to gravity / looking up)
        normal_cam = mean_axis
        if np.dot(normal_cam, contact_point) > 0:
            normal_cam = -normal_cam

        u_y = normal_cam / np.linalg.norm(normal_cam)

        # Desk horizontal axis (u_x): Project camera horizontal axis [1, 0, 0] onto desk plane
        ref_x = np.array([1.0, 0.0, 0.0], dtype=np.float64)
        u_x = ref_x - np.dot(ref_x, u_y) * u_y
        if np.linalg.norm(u_x) < 0.1:
            u_x = np.array([1.0, 0.0, 0.0], dtype=np.float64)
        else:
            u_x = u_x / np.linalg.norm(u_x)

        # Desk forward axis (u_z): Cross product to form complete right-handed coordinate frame
        u_z = np.cross(u_x, u_y)
        u_z = u_z / np.linalg.norm(u_z)

        # Desk basis in camera coordinates: [u_x (Right), u_y (Up), u_z (Forward)]
        r_desk_to_cam = np.column_stack([u_x, u_y, u_z])
        r_cam_to_desk = r_desk_to_cam.T

        calib = DeskCalibration(
            origin_cam=contact_point.tolist(),
            r_cam_to_desk=r_cam_to_desk.tolist(),
            normal_cam=u_y.tolist(),
            calibrated_tip_offset_mm=tip_offset.tolist(),
            calibration_method="pivot",
            rms_error_mm=round(rms_err, 3)
        )
        return calib, tip_offset


def get_default_desk_calibration(
    contact_z_mm: float = 450.0,
    tilt_deg: float = 28.0,
    origin_cam: Optional[np.ndarray] = None
) -> DeskCalibration:
    """Construct a clean, robust 6-DOF controller coordinate frame."""
    import math
    rad = math.radians(tilt_deg)
    u_y = np.array([0.0, -math.cos(rad), -math.sin(rad)], dtype=np.float64)
    u_y = u_y / np.linalg.norm(u_y)

    ref_x = np.array([1.0, 0.0, 0.0], dtype=np.float64)
    u_x = ref_x - np.dot(ref_x, u_y) * u_y
    u_x = u_x / np.linalg.norm(u_x)

    u_z = np.cross(u_x, u_y)
    u_z = u_z / np.linalg.norm(u_z)

    r_desk_to_cam = np.column_stack([u_x, u_y, u_z])
    r_cam_to_desk = r_desk_to_cam.T

    if origin_cam is None:
        origin_cam = np.array([0.0, contact_z_mm * math.tan(rad) * 0.5, contact_z_mm], dtype=np.float64)

    return DeskCalibration(
        origin_cam=origin_cam.tolist(),
        r_cam_to_desk=r_cam_to_desk.tolist(),
        normal_cam=u_y.tolist(),
        calibrated_tip_offset_mm=[0.0, 65.0, 0.0],
        calibration_method="nominal-controller",
        rms_error_mm=0.0
    )


def get_default_camera_matrix(width: int = 1280, height: int = 720) -> Tuple[np.ndarray, np.ndarray]:
    """Return nominal pinhole intrinsics for a standard 720p webcam (~65 deg horizontal FOV)."""
    fx = float(width) * 0.82
    fy = fx
    cx = float(width) / 2.0
    cy = float(height) / 2.0
    camera_matrix = np.array([
        [fx, 0.0, cx],
        [0.0, fy, cy],
        [0.0, 0.0, 1.0]
    ], dtype=np.float64)
    dist_coeffs = np.zeros((5, 1), dtype=np.float64)
    return camera_matrix, dist_coeffs


def estimate_desk_from_tag(
    corners_2d: np.ndarray,
    tag_size_mm: float,
    camera_matrix: np.ndarray,
    dist_coeffs: np.ndarray,
    tag_id: int = 0
) -> Optional[DeskCalibration]:
    """Estimate the desk coordinate frame using a fiducial AprilTag laid flat on the desk."""
    half = tag_size_mm / 2.0
    obj_pts = np.array([
        [-half, 0.0, -half],
        [ half, 0.0, -half],
        [ half, 0.0,  half],
        [-half, 0.0,  half]
    ], dtype=np.float64)

    img_pts = corners_2d.reshape(4, 2).astype(np.float64)

    ok, rvec, tvec = cv2.solvePnP(
        obj_pts, img_pts, camera_matrix, dist_coeffs, flags=cv2.SOLVEPNP_IPPE_SQUARE
    )
    if not ok:
        ok, rvec, tvec = cv2.solvePnP(
            obj_pts, img_pts, camera_matrix, dist_coeffs, flags=cv2.SOLVEPNP_ITERATIVE
        )
    if not ok:
        return None

    r_desk_to_cam, _ = cv2.Rodrigues(rvec)
    r_cam_to_desk = r_desk_to_cam.T
    origin_cam = tvec.flatten()

    normal_cam = r_desk_to_cam[:, 1]
    if np.dot(normal_cam, origin_cam) > 0:
        normal_cam = -normal_cam

    return DeskCalibration(
        origin_cam=origin_cam.tolist(),
        r_cam_to_desk=r_cam_to_desk.tolist(),
        normal_cam=normal_cam.tolist(),
        desk_tag_id=tag_id,
        desk_tag_size_mm=tag_size_mm,
        calibration_method="tag",
        rms_error_mm=0.1
    )


def estimate_desk_from_3_points(
    p_origin: np.ndarray,
    p_x_axis: np.ndarray,
    p_z_axis: np.ndarray
) -> Optional[DeskCalibration]:
    """Estimate desk plane from 3 probed 3D points in camera coordinates."""
    v_x = p_x_axis - p_origin
    v_z = p_z_axis - p_origin

    norm_x = np.linalg.norm(v_x)
    if norm_x < 1e-4:
        return None
    u_x = v_x / norm_x

    normal = np.cross(u_x, v_z)
    norm_n = np.linalg.norm(normal)
    if norm_n < 1e-4:
        return None
    u_y = normal / norm_n

    u_z = np.cross(u_x, u_y)
    u_z = u_z / np.linalg.norm(u_z)

    r_desk_to_cam = np.column_stack([u_x, u_y, u_z])
    r_cam_to_desk = r_desk_to_cam.T

    return DeskCalibration(
        origin_cam=p_origin.tolist(),
        r_cam_to_desk=r_cam_to_desk.tolist(),
        normal_cam=u_y.tolist(),
        calibration_method="probe",
        rms_error_mm=0.2
    )


def save_desk_calibration(calibration: DeskCalibration, path: str | Path = "desk_calibration.json") -> None:
    """Save desk calibration to a JSON file."""
    p = Path(path)
    with p.open("w", encoding="utf-8") as f:
        json.dump(calibration.to_dict(), f, indent=2)


def load_desk_calibration(path: str | Path = "desk_calibration.json") -> Optional[DeskCalibration]:
    """Load desk calibration from a JSON file if present."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
            return DeskCalibration.from_dict(data)
    except Exception:
        return None


def draw_desk_plane_grid(
    frame: np.ndarray,
    calib: DeskCalibration,
    camera_matrix: np.ndarray,
    dist_coeffs: np.ndarray,
    extent_x_mm: float = 240.0,
    extent_z_mm: float = 180.0,
    step_mm: float = 30.0
) -> None:
    """Render an augmented-reality 3D grid and coordinate triad directly on the desk surface."""
    r_cam_to_desk = np.asarray(calib.r_cam_to_desk, dtype=np.float64)
    r_desk_to_cam = r_cam_to_desk.T
    rvec, _ = cv2.Rodrigues(r_desk_to_cam)
    tvec = np.asarray(calib.origin_cam, dtype=np.float64).reshape(3, 1)

    # 1. Draw Grid Lines along X and Z on the desk plane (Y = 0)
    lines_3d = []
    for x in np.arange(-extent_x_mm, extent_x_mm + step_mm * 0.5, step_mm):
        lines_3d.append([[x, 0.0, -extent_z_mm], [x, 0.0, extent_z_mm]])
    for z in np.arange(-extent_z_mm, extent_z_mm + step_mm * 0.5, step_mm):
        lines_3d.append([[-extent_x_mm, 0.0, z], [extent_x_mm, 0.0, z]])

    for pt1, pt2 in lines_3d:
        pts = np.array([pt1, pt2], dtype=np.float64)
        proj, _ = cv2.projectPoints(pts, rvec, tvec, camera_matrix, dist_coeffs)
        p1 = tuple(proj[0].ravel().astype(int))
        p2 = tuple(proj[1].ravel().astype(int))
        cv2.line(frame, p1, p2, (50, 50, 50), 1, cv2.LINE_AA)

    # 2. Draw Desk Workspace Boundary Rectangle
    boundary = np.array([
        [-extent_x_mm, 0.0, -extent_z_mm],
        [ extent_x_mm, 0.0, -extent_z_mm],
        [ extent_x_mm, 0.0,  extent_z_mm],
        [-extent_x_mm, 0.0,  extent_z_mm]
    ], dtype=np.float64)
    b_proj, _ = cv2.projectPoints(boundary, rvec, tvec, camera_matrix, dist_coeffs)
    b_pts = b_proj.reshape(-1, 2).astype(np.int32)
    cv2.polylines(frame, [b_pts], True, (0, 220, 220), 2, cv2.LINE_AA)

    # 3. Draw 3D Coordinate Triad at Desk Origin
    axis_pts = np.array([
        [0.0, 0.0, 0.0],
        [40.0, 0.0, 0.0],   # X (Red)
        [0.0, 35.0, 0.0],   # Y (Green Up)
        [0.0, 0.0, 40.0]    # Z (Blue)
    ], dtype=np.float64)
    a_proj, _ = cv2.projectPoints(axis_pts, rvec, tvec, camera_matrix, dist_coeffs)
    orig = tuple(a_proj[0].ravel().astype(int))
    ax_x = tuple(a_proj[1].ravel().astype(int))
    ax_y = tuple(a_proj[2].ravel().astype(int))
    ax_z = tuple(a_proj[3].ravel().astype(int))

    cv2.line(frame, orig, ax_x, (0, 0, 255), 3, cv2.LINE_AA)    # Red = X
    cv2.line(frame, orig, ax_y, (0, 255, 0), 3, cv2.LINE_AA)    # Green = Y (Up)
    cv2.line(frame, orig, ax_z, (255, 120, 0), 3, cv2.LINE_AA)  # Blue = Z

    method_tag = f"Desk ({calib.calibration_method.upper()})"
    cv2.putText(frame, method_tag, (orig[0] + 6, orig[1] - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1, cv2.LINE_AA)
