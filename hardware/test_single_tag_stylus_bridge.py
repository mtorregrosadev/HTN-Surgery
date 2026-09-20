import cv2
import numpy as np
import pytest

from single_tag_stylus_bridge import (
    camera_matrix,
    estimate_pose,
    rotation_matrix_to_quaternion,
    tag_object_points,
)


def quaternion_matrix(quaternion):
    x, y, z, w = quaternion
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def test_rotation_quaternion_round_trip():
    rvec = np.array([0.35, -0.2, 0.6], dtype=np.float64)
    rotation, _ = cv2.Rodrigues(rvec)
    quaternion = rotation_matrix_to_quaternion(rotation)
    assert np.linalg.norm(quaternion) == pytest.approx(1.0)
    assert quaternion_matrix(quaternion) == pytest.approx(rotation, abs=1e-8)


def test_synthetic_tag_recovers_position_and_a_proper_rotation():
    intrinsics = camera_matrix(1280, 720, 60.0)
    distortion = np.zeros(5)
    rvec = np.array([0.22, -0.31, 0.12], dtype=np.float64)
    tvec = np.array([0.08, -0.04, 0.72], dtype=np.float64)
    points = tag_object_points(0.05)
    pixels, _ = cv2.projectPoints(points, rvec, tvec, intrinsics, distortion)

    position, quaternion, rms_px = estimate_pose(
        pixels.reshape(4, 2), 0.05, intrinsics, distortion
    )
    assert position == pytest.approx([0.08, 0.04, 0.72], abs=1e-5)
    assert np.linalg.norm(quaternion) == pytest.approx(1.0, abs=1e-7)
    assert np.linalg.det(quaternion_matrix(quaternion)) == pytest.approx(1.0, abs=1e-7)
    assert rms_px < 1e-4


def test_tag_size_controls_metric_depth_scale():
    intrinsics = camera_matrix(1280, 720, 60.0)
    distortion = np.zeros(5)
    points = tag_object_points(0.04)
    pixels, _ = cv2.projectPoints(
        points, np.zeros(3), np.array([0.0, 0.0, 0.6]), intrinsics, distortion
    )
    correct, _, _ = estimate_pose(pixels.reshape(4, 2), 0.04, intrinsics, distortion)
    oversized, _, _ = estimate_pose(pixels.reshape(4, 2), 0.08, intrinsics, distortion)
    assert correct[2] == pytest.approx(0.6, rel=1e-4)
    assert oversized[2] == pytest.approx(1.2, rel=1e-4)
