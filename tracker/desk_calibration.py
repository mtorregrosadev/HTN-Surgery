"""3D Desk Space Registration & Spatial Coordinate Transformation.

Calibrates the physical tabletop workspace coordinate frame relative to the webcam
using either:
1. The rotating/pivoting system of the scalpel (pivot calibration around a stationary tip)
2. A reference fiducial AprilTag laid flat on the desk
3. 3-point probe touching
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import ClassVar, List, Optional, Tuple

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
    calibration_method: str = "pivot"  # "pivot", "tag", "probe", "user-drawn-area"
    rms_error_mm: float = 0.0
    timestamp: float = 0.0
    extent_x_mm: float = 160.0  # Half-width of workspace rectangle (mm)
    extent_z_mm: float = 110.0  # Half-depth of workspace rectangle (mm)

    # These methods produce a frame from observations rather than from the
    # nominal controller geometry.  Keep this allow-list narrow: a valid
    # rotation matrix alone only proves that a frame is mathematically usable,
    # not that it was measured against the physical workspace.
    MEASURED_METHODS: ClassVar[frozenset[str]] = frozenset(("pivot", "tag", "probe"))
    MAX_MEASURED_RMS_ERROR_MM: ClassVar[float] = 3.0
    DEMO_METHOD: ClassVar[str] = "one-click-demo"
    DEMO_RMS_ERROR_MM: ClassVar[float] = 15.0

    def to_dict(self) -> dict:
        return asdict(self)

    def camera_to_desk_transform(self) -> list[float]:
        """Return the measured camera-to-desk transform as row-major 4x4 data.

        ``point_cam_to_desk`` applies ``R @ (p_cam - origin_cam)``.  The
        equivalent homogeneous transform is therefore ``[R, -R @ origin]``;
        keeping this conversion next to the calibration prevents callers from
        accidentally registering an identity transform for a calibrated desk.
        """
        if not self.is_valid():
            raise ValueError("cannot export an invalid desk calibration")
        rotation = np.asarray(self.r_cam_to_desk, dtype=np.float64)
        origin = np.asarray(self.origin_cam, dtype=np.float64)
        transform = np.eye(4, dtype=np.float64)
        transform[:3, :3] = rotation
        transform[:3, 3] = -(rotation @ origin)
        return transform.reshape(-1).tolist()

    @classmethod
    def from_dict(cls, data: dict) -> DeskCalibration:
        import dataclasses
        valid_fields = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)

    def is_valid(self) -> bool:
        """Verify the calibration represents a physically plausible desk in front of the camera."""
        if not self.origin_cam or len(self.origin_cam) != 3:
            return False
        if self.r_cam_to_desk is None:
            return False
        rotation = np.asarray(self.r_cam_to_desk, dtype=np.float64)
        if rotation.shape != (3, 3) or not np.all(np.isfinite(rotation)):
            return False
        if not np.allclose(rotation @ rotation.T, np.eye(3), atol=2e-2):
            return False
        if np.linalg.det(rotation) <= 0.0:
            return False
        origin = np.asarray(self.origin_cam, dtype=np.float64)
        if not np.all(np.isfinite(origin)):
            return False
        z = self.origin_cam[2]
        if z < 150.0 or z > 1500.0:
            return False
        if not self.normal_cam or len(self.normal_cam) != 3:
            return False
        normal = np.asarray(self.normal_cam, dtype=np.float64)
        if not np.all(np.isfinite(normal)) or not 0.9 <= np.linalg.norm(normal) <= 1.1:
            return False
        # Desk normal in camera coordinates must point upwards (negative Y in OpenCV frame)
        if self.normal_cam[1] > -0.2:
            return False
        # Desk should not be tilted crazy sideways (nx within reasonable range)
        if abs(self.normal_cam[0]) > 0.65:
            return False
        try:
            rms_error_mm = float(self.rms_error_mm)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(rms_error_mm) or rms_error_mm < 0.0:
            return False
        return True

    def is_measured(self) -> bool:
        """Return whether this frame is measured and good enough for a session.

        ``is_valid`` intentionally only checks geometric safety so the camera
        preview can still use a nominal frame.  A tare/recenter copies nominal
        tilt and reports zero error; it must never be promoted to a measured
        session calibration by that geometric check alone.
        """
        if not self.is_valid() or self.calibration_method not in self.MEASURED_METHODS:
            return False
        return float(self.rms_error_mm) <= self.MAX_MEASURED_RMS_ERROR_MM

    def is_demo_registration(self) -> bool:
        return (
            self.is_valid()
            and self.calibration_method == self.DEMO_METHOD
            and float(self.rms_error_mm) == self.DEMO_RMS_ERROR_MM
        )

    def is_session_usable(self) -> bool:
        """Allow measured frames and the explicit, visibly degraded demo frame."""
        return self.is_measured() or self.is_demo_registration()

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

    def __init__(self, min_samples: int = 40, max_rms_error_mm: float = 3.0):
        self.min_samples = min_samples
        self.max_rms_error_mm = max_rms_error_mm
        self.rotations: List[np.ndarray] = []
        self.translations: List[np.ndarray] = []
        self.last_failure_reason: Optional[str] = None

    def reset(self):
        self.rotations.clear()
        self.translations.clear()
        self.last_failure_reason = None

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

    @property
    def handle_rotation_span_deg(self) -> float:
        """Largest handle-axis change observed during the pivot capture."""
        if len(self.rotations) < 2:
            return 0.0
        axes = np.asarray([rotation[:, 1] for rotation in self.rotations], dtype=np.float64)
        axes /= np.linalg.norm(axes, axis=1, keepdims=True)
        dots = np.clip(axes @ axes.T, -1.0, 1.0)
        return float(np.degrees(np.arccos(np.min(dots))))

    def solve(self) -> Optional[Tuple[DeskCalibration, np.ndarray]]:
        """Solve least squares system [R_i, -I] * [v_tip, P_contact]^T = -t_i."""
        if not self.is_ready:
            self.last_failure_reason = f"Need {self.min_samples - len(self.rotations)} more camera views."
            return None

        A = []
        b = []
        for R, t in zip(self.rotations, self.translations):
            block = np.hstack([R, -np.eye(3)])
            A.append(block)
            b.append(-t)

        A_mat = np.vstack(A)
        b_vec = np.concatenate(b)

        x, _, rank, _ = np.linalg.lstsq(A_mat, b_vec, rcond=None)
        if rank < 6:
            # A stationary or nearly one-axis motion cannot identify both the
            # tip offset and the contact point.  Do not manufacture a nominal
            # calibration for an under-constrained solve.
            self.last_failure_reason = "Not enough 3D handle angles. Tilt left/right and toward/away from the camera."
            return None
        tip_offset = x[:3]
        contact_point = x[3:]

        # Calculate residual RMS error
        predicted_t = []
        for R in self.rotations:
            predicted_t.append(contact_point - R @ tip_offset)
        errs = np.asarray(
            [np.linalg.norm(p - a) for p, a in zip(predicted_t, self.translations)],
            dtype=np.float64,
        )
        rms_err = float(np.sqrt(np.mean(errs**2))) if errs.size else float("inf")

        # Reject poor or physically impossible solves.  Returning ``None`` is
        # safer than replacing measured data with nominal geometry.
        if not np.isfinite(rms_err):
            self.last_failure_reason = "Camera pose data is not finite. Keep ID 1 fully visible and retry."
            return None
        if rms_err > self.max_rms_error_mm:
            self.last_failure_reason = (
                f"The tip moved about {rms_err:.1f} mm; keep it fixed within {self.max_rms_error_mm:.0f} mm and retry."
            )
            return None
        if contact_point[2] < 150.0 or contact_point[2] > 1500.0:
            self.last_failure_reason = "The camera depth estimate is outside its usable range. Move the desk 15–150 cm from the camera."
            return None
        if not np.all(np.isfinite(tip_offset)) or not np.all(np.isfinite(contact_point)):
            self.last_failure_reason = "The camera pose estimate is invalid. Keep the whole tag in view and retry."
            return None
        if not 20.0 <= np.linalg.norm(tip_offset) <= 150.0:
            self.last_failure_reason = "The estimated tag-to-tip distance is implausible. Check the printed tag size and keep it flat on the handle."
            return None

        # Desk normal is estimated from the symmetry axis of the rotation cone
        # Average tool handle axis (column 1 / Y) across all pivot samples
        handle_axes = [R[:, 1] for R in self.rotations]
        mean_axis = np.mean(handle_axes, axis=0)
        norm_val = np.linalg.norm(mean_axis)
        if norm_val < 1e-4:
            self.last_failure_reason = "The handle angles cancel out. Restart and use a smaller, varied cone of motion."
            return None
        mean_axis = mean_axis / norm_val

        # Desk normal points upward toward camera (opposite to gravity / looking up)
        normal_cam = mean_axis
        if normal_cam[1] > 0.0:
            normal_cam = -normal_cam

        # A sideways normal means the pivot motion did not provide a useful
        # desk orientation.  Do not silently substitute a nominal plane.
        if normal_cam[1] > -0.35:
            self.last_failure_reason = "The captured motion cannot identify the desk plane. Tilt the handle toward and away from the camera."
            return None

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
            rms_error_mm=round(rms_err, 3),
            timestamp=time.time(),
            extent_x_mm=160.0,
            extent_z_mm=110.0
        )
        self.last_failure_reason = None
        return calib, tip_offset


def get_default_desk_calibration(
    contact_z_mm: float = 450.0,
    tilt_deg: float = 28.0,
    origin_cam: Optional[np.ndarray] = None,
    extent_x_mm: float = 160.0,
    extent_z_mm: float = 110.0
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
    else:
        origin_cam = np.asarray(origin_cam, dtype=np.float64)

    return DeskCalibration(
        origin_cam=origin_cam.tolist(),
        r_cam_to_desk=r_cam_to_desk.tolist(),
        normal_cam=u_y.tolist(),
        # The nominal desk frame has no measured tag-to-tip offset.  The pose
        # solver uses its explicit configured fallback until pivot calibration
        # supplies this value.
        calibrated_tip_offset_mm=None,
        calibration_method="nominal-controller",
        rms_error_mm=0.0,
        extent_x_mm=extent_x_mm,
        extent_z_mm=extent_z_mm
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
    """Load desk calibration from a JSON file if present and physically valid."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
            calib = DeskCalibration.from_dict(data)
            if calib.is_valid():
                return calib
            print(f"[Desk] Warning: Stored calibration in {path} failed physical validation. Reverting to nominal.", flush=True)
            return None
    except Exception:
        return None


def desk_pixel_to_3d(
    u: float,
    v: float,
    calib: DeskCalibration,
    camera_matrix: np.ndarray,
) -> Optional[np.ndarray]:
    """Raycast an image pixel (u, v) onto the 3D calibrated desk plane.

    Returns 3D point in camera coordinates (mm), or None if ray does not intersect desk plane.
    """
    fx = camera_matrix[0, 0]
    fy = camera_matrix[1, 1]
    cx = camera_matrix[0, 2]
    cy = camera_matrix[1, 2]

    ray = np.array([(u - cx) / fx, (v - cy) / fy, 1.0], dtype=np.float64)
    n = np.asarray(calib.normal_cam, dtype=np.float64)
    p0 = np.asarray(calib.origin_cam, dtype=np.float64)

    denom = np.dot(n, ray)
    if denom >= -1e-4:
        return None

    t = np.dot(n, p0) / denom
    if t < 120.0 or t > 2000.0:
        return None

    return t * ray


def desk_rect_from_pixels(
    u0: float, v0: float,
    u1: float, v1: float,
    calib: DeskCalibration,
    camera_matrix: np.ndarray,
) -> Optional[DeskCalibration]:
    """Fit an updated DeskCalibration centered on a 2D user-drawn rectangle.

    The center of the rectangle becomes origin_cam (0, 0, 0) on the desk,
    and the extents define the physical boundary area on the desk.
    """
    min_u, max_u = min(u0, u1), max(u0, u1)
    min_v, max_v = min(v0, v1), max(v0, v1)

    c_tl = desk_pixel_to_3d(min_u, min_v, calib, camera_matrix)
    c_tr = desk_pixel_to_3d(max_u, min_v, calib, camera_matrix)
    c_br = desk_pixel_to_3d(max_u, max_v, calib, camera_matrix)
    c_bl = desk_pixel_to_3d(min_u, max_v, calib, camera_matrix)

    if c_tl is None or c_tr is None or c_br is None or c_bl is None:
        return None

    p_center = (c_tl + c_tr + c_br + c_bl) * 0.25

    r_cam_to_desk = np.asarray(calib.r_cam_to_desk, dtype=np.float64)
    d_tr = r_cam_to_desk @ (c_tr - p_center)
    d_tl = r_cam_to_desk @ (c_tl - p_center)
    d_br = r_cam_to_desk @ (c_br - p_center)
    d_bl = r_cam_to_desk @ (c_bl - p_center)

    ext_x = max(abs(d_tr[0]), abs(d_tl[0]), abs(d_br[0]), abs(d_bl[0]))
    ext_z = max(abs(d_tr[2]), abs(d_tl[2]), abs(d_br[2]), abs(d_bl[2]))

    ext_x = float(np.clip(ext_x, 40.0, 450.0))
    ext_z = float(np.clip(ext_z, 30.0, 350.0))

    return DeskCalibration(
        origin_cam=p_center.tolist(),
        r_cam_to_desk=calib.r_cam_to_desk,
        normal_cam=calib.normal_cam,
        calibrated_tip_offset_mm=calib.calibrated_tip_offset_mm,
        # Preserve measured provenance when the rectangle is drawn on a
        # measured desk.  A rectangle drawn over nominal geometry remains a
        # preview-only frame and keeps this derived method name.
        calibration_method=(
            calib.calibration_method
            if calib.is_measured()
            else "user-drawn-area"
        ),
        rms_error_mm=(calib.rms_error_mm if calib.is_measured() else 0.0),
        extent_x_mm=round(ext_x, 1),
        extent_z_mm=round(ext_z, 1)
    )


def draw_desk_plane_grid(
    frame: np.ndarray,
    calib: DeskCalibration,
    camera_matrix: np.ndarray,
    dist_coeffs: np.ndarray,
    extent_x_mm: Optional[float] = None,
    extent_z_mm: Optional[float] = None,
    step_mm: float = 25.0,
    scalpel_tip_desk: Optional[np.ndarray] = None,
    show_grid: bool = False,
) -> None:
    """Render an augmented-reality 3D boundary rectangle and shaded area on the desk."""
    if not calib.is_valid():
        return

    ext_x = extent_x_mm if extent_x_mm is not None else getattr(calib, "extent_x_mm", 160.0)
    ext_z = extent_z_mm if extent_z_mm is not None else getattr(calib, "extent_z_mm", 110.0)

    r_cam_to_desk = np.asarray(calib.r_cam_to_desk, dtype=np.float64)
    r_desk_to_cam = r_cam_to_desk.T
    tvec = np.asarray(calib.origin_cam, dtype=np.float64)

    fx = camera_matrix[0, 0]
    fy = camera_matrix[1, 1]
    cx = camera_matrix[0, 2]
    cy = camera_matrix[1, 2]

    def project_safe(p_desk: list[float] | np.ndarray) -> Optional[Tuple[int, int]]:
        p_c = (r_desk_to_cam @ np.asarray(p_desk, dtype=np.float64)) + tvec
        if p_c[2] < 120.0:
            return None
        u = int(round(fx * p_c[0] / p_c[2] + cx))
        v = int(round(fy * p_c[1] / p_c[2] + cy))
        h, w = frame.shape[:2]
        if -400 <= u <= w + 400 and -400 <= v <= h + 400:
            return (u, v)
        return None

    def draw_segment(p1_desk, p2_desk, color, thickness=1):
        c1 = (r_desk_to_cam @ np.asarray(p1_desk, dtype=np.float64)) + tvec
        c2 = (r_desk_to_cam @ np.asarray(p2_desk, dtype=np.float64)) + tvec
        near_z = 120.0
        if c1[2] < near_z and c2[2] < near_z:
            return
        if c1[2] < near_z:
            t = (near_z - c1[2]) / (c2[2] - c1[2])
            c1 = c1 + t * (c2 - c1)
        elif c2[2] < near_z:
            t = (near_z - c2[2]) / (c1[2] - c2[2])
            c2 = c2 + t * (c1 - c2)

        u1 = int(round(fx * c1[0] / c1[2] + cx))
        v1 = int(round(fy * c1[1] / c1[2] + cy))
        u2 = int(round(fx * c2[0] / c2[2] + cx))
        v2 = int(round(fy * c2[1] / c2[2] + cy))
        cv2.line(frame, (u1, v1), (u2, v2), color, thickness, cv2.LINE_AA)

    # 1. Workspace Area Rectangle 4 corners
    corners_desk = [
        [-ext_x, 0.0, -ext_z],
        [ ext_x, 0.0, -ext_z],
        [ ext_x, 0.0,  ext_z],
        [-ext_x, 0.0,  ext_z],
    ]
    corners_2d = [project_safe(c) for c in corners_desk]

    if all(p is not None for p in corners_2d):
        poly = np.array(corners_2d, dtype=np.int32)
        # Soft translucent shaded surgical field overlay
        overlay = frame.copy()
        cv2.fillPoly(overlay, [poly], (35, 75, 25))
        cv2.addWeighted(overlay, 0.35, frame, 0.65, 0, frame)

        # Crisp border
        cv2.polylines(frame, [poly], True, (0, 255, 200), 2, cv2.LINE_AA)

        # Corner markers
        for pt in corners_2d:
            cv2.circle(frame, pt, 4, (0, 255, 255), -1, cv2.LINE_AA)

        # Dimension label
        top_u = (corners_2d[0][0] + corners_2d[1][0]) // 2
        top_v = (corners_2d[0][1] + corners_2d[1][1]) // 2 - 8
        label = f"Surgical Area: {int(ext_x*2)}x{int(ext_z*2)} mm"
        cv2.putText(frame, label, (top_u - 75, top_v),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.44, (0, 255, 200), 1, cv2.LINE_AA)

    # 2. Internal Grid Lines (optional, default off to keep view clean)
    if show_grid:
        for x in np.arange(-ext_x + step_mm, ext_x, step_mm):
            draw_segment([x, 0.0, -ext_z], [x, 0.0, ext_z], (60, 110, 60), 1)
        for z in np.arange(-ext_z + step_mm, ext_z, step_mm):
            draw_segment([-ext_x, 0.0, z], [ext_x, 0.0, z], (60, 110, 60), 1)

    # 3. Desk Origin Triad at (0, 0, 0)
    p_orig = project_safe([0.0, 0.0, 0.0])
    if p_orig:
        draw_segment([0.0, 0.0, 0.0], [35.0, 0.0, 0.0], (0, 0, 255), 2)    # X Red
        draw_segment([0.0, 0.0, 0.0], [0.0, 30.0, 0.0], (0, 255, 0), 2)    # Y Green Up
        draw_segment([0.0, 0.0, 0.0], [0.0, 0.0, 35.0], (255, 120, 0), 2)  # Z Blue
        cv2.circle(frame, p_orig, 3, (255, 255, 255), -1)
        cv2.putText(frame, "(0,0,0)", (p_orig[0] + 6, p_orig[1] - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 255, 255), 1, cv2.LINE_AA)

    # 4. Scalpel Shadow / Touchpoint on the desk
    if scalpel_tip_desk is not None:
        sx, sy, sz = scalpel_tip_desk[0], scalpel_tip_desk[1], scalpel_tip_desk[2]
        p_shadow = project_safe([sx, 0.0, sz])
        p_tip = project_safe([sx, sy, sz])
        if p_shadow is not None:
            in_area = abs(sx) <= ext_x and abs(sz) <= ext_z
            ring_col = (0, 255, 0) if in_area else (0, 165, 255)
            if sy <= 2.0:
                cv2.circle(frame, p_shadow, 8, (0, 0, 255), 2, cv2.LINE_AA)
                cv2.circle(frame, p_shadow, 3, (0, 0, 255), -1, cv2.LINE_AA)
            else:
                cv2.circle(frame, p_shadow, 6, ring_col, 1, cv2.LINE_AA)
                if p_tip is not None:
                    cv2.line(frame, p_shadow, p_tip, (0, 200, 255), 1, cv2.LINE_AA)
