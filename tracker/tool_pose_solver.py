"""6-DOF Scalpel Pose Solver with AprilTag Tracking and One-Euro Jitter Filtering.

Calculates the 3D position and orientation of the physical scalpel blade tip
relative to the calibrated desk workspace and the Surge Prep simulation space.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from .desk_calibration import DeskCalibration


class OneEuroFilter:
    """Adaptive low-pass filter to eliminate tracking jitter with zero latency penalty."""

    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.007, d_cutoff: float = 1.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self.x_prev: Optional[np.ndarray] = None
        self.dx_prev: Optional[np.ndarray] = None
        self.t_prev: Optional[float] = None

    def alpha(self, rate: float, cutoff: float) -> float:
        tau = 1.0 / (2.0 * math.pi * cutoff)
        te = 1.0 / rate if rate > 0 else 0.033
        return 1.0 / (1.0 + tau / te)

    def filter(self, x: np.ndarray, t: Optional[float] = None) -> np.ndarray:
        if t is None:
            t = time.perf_counter()
        if self.x_prev is None:
            self.x_prev = x.copy().astype(np.float64)
            self.dx_prev = np.zeros_like(self.x_prev)
            self.t_prev = t
            return self.x_prev

        dt = t - self.t_prev
        rate = 1.0 / dt if dt > 1e-4 else 30.0
        self.t_prev = t

        dx = (x - self.x_prev) * rate
        a_d = self.alpha(rate, self.d_cutoff)
        dx_hat = a_d * dx + (1.0 - a_d) * self.dx_prev
        self.dx_prev = dx_hat

        cutoff = self.min_cutoff + self.beta * np.linalg.norm(dx_hat)
        a = self.alpha(rate, cutoff)
        x_hat = a * x + (1.0 - a) * self.x_prev
        self.x_prev = x_hat
        return x_hat

    def reset(self):
        self.x_prev = None
        self.dx_prev = None
        self.t_prev = None


@dataclass
class ToolPose6DOF:
    """Represents the 6-DOF pose of the scalpel blade tip."""
    # Coordinates in Desk Frame (mm)
    x_mm: float
    y_mm: float  # Height above desk surface (0 = touching desk)
    z_mm: float
    # Orientation Quaternion in Desk Frame [qx, qy, qz, qw]
    qx: float
    qy: float
    qz: float
    qw: float
    # Coordinates in Camera Frame (mm)
    cam_pos_mm: Tuple[float, float, float]
    # Tracking quality & visible tags
    visible_tags: List[int]
    confidence: float


class ScalpelPoseSolver:
    """Solves 6-DOF physical scalpel tip pose using AprilTags on the handle."""

    # Outlier-jump budget: a generous ceiling on genuine hand speed (mm/s),
    # scaled by actual elapsed time, plus floor/ceiling clamps so a very
    # short or very long dt still produces a sane per-sample threshold.
    MAX_TIP_SPEED_MM_S: float = 1800.0
    MIN_JUMP_THRESHOLD_MM: float = 25.0
    MAX_JUMP_THRESHOLD_MM: float = 250.0

    def __init__(
        self,
        camera_matrix: np.ndarray,
        dist_coeffs: np.ndarray,
        tag_size_mm: float = 24.0,
        tip_offset_along_handle_mm: float = 65.0,
        tool_tag_ids: Tuple[int, ...] = (1, 2, 3),
        tag_to_tool_transforms: Optional[Dict[int, np.ndarray]] = None,
    ):
        self.camera_matrix = camera_matrix
        self.dist_coeffs = dist_coeffs
        self.tag_size_mm = tag_size_mm
        self.tip_offset_along_handle_mm = tip_offset_along_handle_mm
        self.tool_tag_ids = set(tool_tag_ids)
        self.primary_tag_id = min(self.tool_tag_ids) if self.tool_tag_ids else None
        # A tag-to-tool transform is only available after a physical marker
        # mount calibration.  Without one, using multiple tag frames as if
        # they shared an origin makes the calculated tip jump as visibility
        # changes, so the primary tag is used exclusively.
        self.tag_to_tool_transforms = {
            int(tag_id): np.asarray(transform, dtype=np.float64)
            for tag_id, transform in (tag_to_tool_transforms or {}).items()
        }

        self.pos_filter = OneEuroFilter(min_cutoff=0.8, beta=0.01)
        self.rot_filter = OneEuroFilter(min_cutoff=1.0, beta=0.015)
        self._last_valid_tip_cam: Optional[np.ndarray] = None
        self._jump_reject_count: int = 0
        self._last_quaternion: Optional[np.ndarray] = None
        self._last_sample_time: Optional[float] = None
        # Whichever tool tag is currently being used as the tracking
        # reference.  Sticking with it while it stays visible avoids
        # tag-swap jitter; falling back to another visible tag (rather than
        # dropping tracking) is what keeps the pose alive as the handle
        # rotates and different tags come into view.
        self._active_reference_tag: Optional[int] = None

    def reset_tracking(self) -> None:
        """Forget filtered state after a tracking gap."""
        self.pos_filter.reset()
        self.rot_filter.reset()
        self._last_valid_tip_cam = None
        self._jump_reject_count = 0
        self._last_quaternion = None
        self._last_sample_time = None
        self._active_reference_tag = None

    def primary_tag_visible(self, detected_tags: Dict[int, np.ndarray]) -> Optional[int]:
        """Return the reference tag to use for this frame.

        All configured tool tags share the same tip-offset convention (see
        ``solve_tool_pose``), so any one of them is an equally valid
        tracking reference.  Restricting this to a single fixed tag ID
        meant tracking dropped out completely whenever that specific tag
        rotated out of view, even though another tool tag was visible.
        """
        if self.tag_to_tool_transforms:
            candidates = sorted(tid for tid in detected_tags if tid in self.tool_tag_ids)
            return candidates[0] if candidates else None
        visible_tool_tags = sorted(tid for tid in detected_tags if tid in self.tool_tag_ids)
        if not visible_tool_tags:
            self._active_reference_tag = None
            return None
        if self._active_reference_tag in visible_tool_tags:
            return self._active_reference_tag
        self._active_reference_tag = visible_tool_tags[0]
        return self._active_reference_tag

    def _tag_pose_to_tool(
        self, tag_id: int, rotation_cam: np.ndarray, position_cam: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Express a detected tag pose in the configured tool reference frame."""
        transform = self.tag_to_tool_transforms.get(tag_id)
        if transform is None:
            return rotation_cam, position_cam
        if transform.shape != (4, 4) or not np.all(np.isfinite(transform)):
            raise ValueError(f"invalid tag-to-tool transform for tag {tag_id}")
        tag_to_tool = transform.copy()
        tag_to_tool[3, :] = [0.0, 0.0, 0.0, 1.0]
        cam_from_tag = np.eye(4, dtype=np.float64)
        cam_from_tag[:3, :3] = rotation_cam
        cam_from_tag[:3, 3] = position_cam
        cam_from_tool = cam_from_tag @ tag_to_tool
        return cam_from_tool[:3, :3], cam_from_tool[:3, 3]

    def solve_reference_tag_pose(
        self, tag_id: int, corners: np.ndarray
    ) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        """Solve the selected tag and convert it to the tool reference frame."""
        result = self.solve_tag_pose(corners)
        if result is None:
            return None
        rotation_cam, position_cam = result
        return self._tag_pose_to_tool(tag_id, rotation_cam, position_cam)

    def solve_tag_pose(self, corners: np.ndarray) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        """Solve 3D pose of a single tag in camera coordinates with reprojection validation."""
        half = self.tag_size_mm / 2.0
        obj_pts = np.array([
            [-half, -half, 0.0],
            [ half, -half, 0.0],
            [ half,  half, 0.0],
            [-half,  half, 0.0]
        ], dtype=np.float64)

        img_pts = corners.reshape(4, 2).astype(np.float64)
        ok, rvec, tvec = cv2.solvePnP(
            obj_pts, img_pts, self.camera_matrix, self.dist_coeffs,
            flags=cv2.SOLVEPNP_IPPE_SQUARE
        )
        if ok:
            proj_pts, _ = cv2.projectPoints(obj_pts, rvec, tvec, self.camera_matrix, self.dist_coeffs)
            reproj_err = float(np.mean(np.linalg.norm(img_pts - proj_pts.reshape(4, 2), axis=1)))
        else:
            reproj_err = 999.0

        # Fallback to standard iterative Levenberg-Marquardt solver if IPPE failed or reprojection error is poor
        if not ok or reproj_err > 4.5:
            ok, rvec, tvec = cv2.solvePnP(
                obj_pts, img_pts, self.camera_matrix, self.dist_coeffs,
                flags=cv2.SOLVEPNP_ITERATIVE
            )
            if ok:
                proj_pts, _ = cv2.projectPoints(obj_pts, rvec, tvec, self.camera_matrix, self.dist_coeffs)
                reproj_err = float(np.mean(np.linalg.norm(img_pts - proj_pts.reshape(4, 2), axis=1)))
            else:
                return None

        # Guard against severely distorted or occluded corner detections
        if not ok or reproj_err > 5.5:
            return None

        r_mat, _ = cv2.Rodrigues(rvec)
        return r_mat, tvec.flatten()

    def solve_tool_pose(
        self,
        detected_tags: Dict[int, np.ndarray],
        desk_calib: DeskCalibration,
        timestamp: Optional[float] = None
    ) -> Optional[ToolPose6DOF]:
        """Compute the physical blade tip pose in desk coordinates from detected tags."""
        visible_tag = self.primary_tag_visible(detected_tags)
        if visible_tag is None:
            return None

        # Only combine tags when all observed tags have measured extrinsics.
        # The default path intentionally uses one stable reference tag.
        if self.tag_to_tool_transforms:
            selected_ids = sorted(
                tid
                for tid in detected_tags
                if tid in self.tool_tag_ids and tid in self.tag_to_tool_transforms
            )
            if not selected_ids:
                return None
        else:
            selected_ids = [visible_tag]

        tag_positions_cam: list[np.ndarray] = []
        tag_rotations_cam: list[np.ndarray] = []
        visible: list[int] = []
        for tid in selected_ids:
            res = self.solve_reference_tag_pose(tid, detected_tags[tid])
            if res is not None:
                r_mat, t_cam = res
                tag_positions_cam.append(t_cam)
                tag_rotations_cam.append(r_mat)
                visible.append(tid)

        if not tag_positions_cam or visible_tag not in visible and not self.tag_to_tool_transforms:
            return None

        # Mean tool-reference position.  Orientation uses the first calibrated
        # reference; uncalibrated tag rotations cannot be averaged safely.
        mean_tag_pos_cam = np.mean(tag_positions_cam, axis=0)
        mean_rot_cam = tag_rotations_cam[0]  # Primary orientation reference

        # Use exact tip offset vector from pivot calibration if available and physically valid
        tip_offset_valid = (
            desk_calib.calibrated_tip_offset_mm is not None
            and 20.0 <= np.linalg.norm(desk_calib.calibrated_tip_offset_mm) <= 130.0
            and abs(desk_calib.calibrated_tip_offset_mm[0]) < 30.0  # Should not stick wildly to the side
        )
        if tip_offset_valid:
            tip_vec = np.asarray(desk_calib.calibrated_tip_offset_mm, dtype=np.float64)
            blade_tip_cam = mean_tag_pos_cam + (mean_rot_cam @ tip_vec)
        else:
            # Fallback to nominal handle axis offset (+Y is down the handle toward tip)
            tool_handle_axis_cam = mean_rot_cam[:, 1]
            blade_tip_cam = mean_tag_pos_cam + (tool_handle_axis_cam * self.tip_offset_along_handle_mm)

        # Outlier Jump Check (guard against planar ambiguity or sudden occlusion
        # jumps).  The allowed jump scales with the real elapsed time between
        # samples instead of a fixed per-frame distance: a fixed threshold
        # misclassifies genuine fast motion as an outlier whenever the camera
        # frame rate dips, freezing the displayed tip and then snapping it
        # forward once the freeze budget runs out.
        now_t = timestamp if timestamp is not None else time.perf_counter()
        if self._last_valid_tip_cam is not None:
            jump_mm = float(np.linalg.norm(blade_tip_cam - self._last_valid_tip_cam))
            dt = (now_t - self._last_sample_time) if self._last_sample_time is not None else None
            if dt is None or dt <= 0.0 or dt > 0.5:
                dt = 1.0 / 30.0
            jump_threshold_mm = float(np.clip(self.MAX_TIP_SPEED_MM_S * dt, self.MIN_JUMP_THRESHOLD_MM, self.MAX_JUMP_THRESHOLD_MM))
            if jump_mm > jump_threshold_mm:
                self._jump_reject_count += 1
                if self._jump_reject_count <= 3:
                    blade_tip_cam = self._last_valid_tip_cam.copy()
                else:
                    self._jump_reject_count = 0
            else:
                self._jump_reject_count = 0
        self._last_sample_time = now_t

        # Apply One-Euro filter in camera frame before desk projection
        filtered_tip_cam = self.pos_filter.filter(blade_tip_cam, timestamp)
        self._last_valid_tip_cam = filtered_tip_cam.copy()

        # Transform blade tip into Desk Coordinates
        tip_desk = desk_calib.point_cam_to_desk(filtered_tip_cam)

        # Transform rotation into Desk Coordinates
        rot_desk = desk_calib.rotation_cam_to_desk(mean_rot_cam)

        # Convert 3x3 rotation matrix to Quaternion [qx, qy, qz, qw]
        quat = rotation_matrix_to_quaternion(rot_desk)
        if self._last_quaternion is not None and float(np.dot(quat, self._last_quaternion)) < 0.0:
            # q and -q describe the same rotation.  Align signs before the
            # component-wise filter so equivalent poses cannot cancel out.
            quat = -quat
        filtered_quat = self.rot_filter.filter(quat, timestamp)
        if self._last_quaternion is not None and float(np.dot(filtered_quat, self._last_quaternion)) < 0.0:
            filtered_quat = -filtered_quat
        # Normalize quaternion
        norm_q = np.linalg.norm(filtered_quat)
        if norm_q > 1e-6:
            filtered_quat = filtered_quat / norm_q
        self._last_quaternion = filtered_quat.copy()

        confidence = min(1.0, len(visible) / float(len(self.tool_tag_ids)))

        return ToolPose6DOF(
            x_mm=float(tip_desk[0]),
            y_mm=float(tip_desk[1]),
            z_mm=float(tip_desk[2]),
            qx=float(filtered_quat[0]),
            qy=float(filtered_quat[1]),
            qz=float(filtered_quat[2]),
            qw=float(filtered_quat[3]),
            cam_pos_mm=tuple(filtered_tip_cam.tolist()),
            visible_tags=visible,
            confidence=confidence
        )

    def draw_tool_3d(
        self,
        frame: np.ndarray,
        pose: ToolPose6DOF,
        desk_calib: DeskCalibration
    ) -> None:
        """Draw 3D scalpel axis and blade tip marker on the camera frame."""
        tip_cam = np.array(pose.cam_pos_mm, dtype=np.float64).reshape(1, 3)
        proj_tip, _ = cv2.projectPoints(
            tip_cam, np.zeros((3, 1)), np.zeros((3, 1)),
            self.camera_matrix, self.dist_coeffs
        )
        tx, ty = proj_tip[0].ravel().astype(int)

        # Draw blade tip crosshair
        # Green if elevated, Yellow if near surface (<15mm), Orange/Red if contact (<=0mm)
        if pose.y_mm <= 0.0:
            col = (0, 0, 255)  # Red = In Contact
            status_txt = f"CONTACT! Y={pose.y_mm:.1f}mm"
        elif pose.y_mm < 15.0:
            col = (0, 255, 255)  # Yellow = Near Surface
            status_txt = f"Near: Y={pose.y_mm:.1f}mm"
        else:
            col = (0, 255, 0)  # Green = Elevated
            status_txt = f"Hover: Y={pose.y_mm:.1f}mm"

        cv2.circle(frame, (tx, ty), 6, col, -1, cv2.LINE_AA)
        cv2.circle(frame, (tx, ty), 12, col, 2, cv2.LINE_AA)
        cv2.putText(
            frame, f"Tip: ({pose.x_mm:.0f}, {pose.y_mm:.0f}, {pose.z_mm:.0f})",
            (tx + 14, ty + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 1, cv2.LINE_AA
        )


def rotation_matrix_to_quaternion(R: np.ndarray) -> np.ndarray:
    """Convert a 3x3 rotation matrix to quaternion [qx, qy, qz, qw]."""
    tr = R[0, 0] + R[1, 1] + R[2, 2]
    if tr > 0:
        S = math.sqrt(tr + 1.0) * 2
        qw = 0.25 * S
        qx = (R[2, 1] - R[1, 2]) / S
        qy = (R[0, 2] - R[2, 0]) / S
        qz = (R[1, 0] - R[0, 1]) / S
    elif (R[0, 0] > R[1, 1]) and (R[0, 0] > R[2, 2]):
        S = math.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2
        qw = (R[2, 1] - R[1, 2]) / S
        qx = 0.25 * S
        qy = (R[0, 1] + R[1, 0]) / S
        qz = (R[0, 2] + R[2, 0]) / S
    elif R[1, 1] > R[2, 2]:
        S = math.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2
        qw = (R[0, 2] - R[2, 0]) / S
        qx = (R[0, 1] + R[1, 0]) / S
        qy = 0.25 * S
        qz = (R[1, 2] + R[2, 1]) / S
    else:
        S = math.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2
        qw = (R[1, 0] - R[0, 1]) / S
        qx = (R[0, 2] + R[2, 0]) / S
        qy = (R[1, 2] + R[2, 1]) / S
        qz = 0.25 * S
    return np.array([qx, qy, qz, qw], dtype=np.float64)
