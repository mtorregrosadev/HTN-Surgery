"""Unit tests for 3D Desk Space Registration and Scalpel Pose Solver."""
import numpy as np
import pytest

from tracker.desk_calibration import (
    DeskCalibration,
    PivotCalibrator,
    estimate_desk_from_3_points,
)
from tracker.tool_pose_solver import OneEuroFilter, rotation_matrix_to_quaternion


def test_desk_coordinate_roundtrip():
    """Verify points and vectors transform accurately between camera and desk frames."""
    # Desk at Z=600mm, tilted by 30 deg around X
    theta = np.deg2rad(30.0)
    R_cam_to_desk = np.array([
        [1.0, 0.0, 0.0],
        [0.0, np.cos(theta), -np.sin(theta)],
        [0.0, np.sin(theta),  np.cos(theta)]
    ])
    origin_cam = [10.0, 20.0, 600.0]
    normal_cam = R_cam_to_desk.T[:, 1].tolist()

    calib = DeskCalibration(
        origin_cam=origin_cam,
        r_cam_to_desk=R_cam_to_desk.tolist(),
        normal_cam=normal_cam,
        calibration_method="test"
    )

    # Point on the desk surface (Y=0 in desk space)
    pt_desk_orig = np.array([50.0, 0.0, -30.0])
    # Transform to camera space
    pt_cam = calib.point_desk_to_cam(pt_desk_orig)
    # Transform back to desk space
    pt_desk_recovered = calib.point_cam_to_desk(pt_cam)

    np.testing.assert_allclose(pt_desk_orig, pt_desk_recovered, atol=1e-5)


def test_desk_surface_height_mapping():
    """Verify Y_desk represents vertical height above the desk surface."""
    R_identity = np.eye(3)
    origin_cam = [0.0, 0.0, 500.0]
    calib = DeskCalibration(
        origin_cam=origin_cam,
        r_cam_to_desk=R_identity.tolist(),
        normal_cam=[0.0, 1.0, 0.0],
        calibration_method="test"
    )

    # Point 25mm above desk origin
    pt_cam_hover = np.array([0.0, 25.0, 500.0])
    pt_desk = calib.point_cam_to_desk(pt_cam_hover)
    assert pytest.approx(pt_desk[1], 1e-4) == 25.0

    # Map to SOFA (synthetic pad at surface)
    pt_sofa = calib.point_desk_to_sofa(pt_desk, surface_height_mm=0.0)
    assert pytest.approx(pt_sofa[1], 1e-4) == 25.0


def test_scalpel_pivot_calibration():
    """Verify PivotCalibrator solves the true blade tip offset and desk contact point."""
    true_tip_offset = np.array([0.5, 62.0, 1.2])
    true_contact = np.array([15.0, -5.0, 480.0])

    calibrator = PivotCalibrator(min_samples=30)
    np.random.seed(123)

    for _ in range(35):
        # Generate pivot angles
        angles = np.random.uniform(-0.35, 0.35, size=3)
        Rx = np.array([[1, 0, 0], [0, np.cos(angles[0]), -np.sin(angles[0])], [0, np.sin(angles[0]), np.cos(angles[0])]])
        Ry = np.array([[np.cos(angles[1]), 0, np.sin(angles[1])], [0, 1, 0], [-np.sin(angles[1]), 0, np.cos(angles[1])]])
        Rz = np.array([[np.cos(angles[2]), -np.sin(angles[2]), 0], [np.sin(angles[2]), np.cos(angles[2]), 0], [0, 0, 1]])
        R = Rz @ Ry @ Rx

        # Tag position from stationary contact point
        t_cam = true_contact - R @ true_tip_offset
        calibrator.add_sample(R, t_cam)

    assert calibrator.is_ready
    calib, est_tip_offset = calibrator.solve()

    # Tip offset error should be sub-millimetre
    error_tip = np.linalg.norm(est_tip_offset - true_tip_offset)
    assert error_tip < 0.05, f"Tip offset error too high: {error_tip} mm"

    # Contact point error should be sub-millimetre
    error_contact = np.linalg.norm(np.array(calib.origin_cam) - true_contact)
    assert error_contact < 0.05, f"Contact error too high: {error_contact} mm"


def test_one_euro_filter():
    """Verify OneEuroFilter suppresses noise while responding quickly to steps."""
    euro = OneEuroFilter(min_cutoff=1.0, beta=0.01)
    stationary_val = np.array([10.0, 20.0, 30.0])

    filtered_vals = []
    for i in range(20):
        noisy = stationary_val + np.random.normal(0, 0.5, size=3)
        filtered = euro.filter(noisy, t=i * 0.033)
        filtered_vals.append(filtered)

    # Variance of filtered samples should be lower than noise
    std_filtered = np.std(filtered_vals[5:], axis=0)
    assert np.all(std_filtered < 0.4)


def test_quaternion_conversion():
    """Verify rotation matrix converts to valid normalized quaternion."""
    theta = np.deg2rad(45.0)
    R = np.array([
        [np.cos(theta), 0, np.sin(theta)],
        [0, 1, 0],
        [-np.sin(theta), 0, np.cos(theta)]
    ])
    q = rotation_matrix_to_quaternion(R)
    norm_q = np.linalg.norm(q)
    assert pytest.approx(norm_q, 1e-5) == 1.0
    # For Y-axis 45 deg rotation: qy = sin(22.5 deg) approx 0.38268, qw = cos(22.5 deg) approx 0.92388
    assert pytest.approx(q[1], 1e-4) == np.sin(theta / 2.0)
    assert pytest.approx(q[3], 1e-4) == np.cos(theta / 2.0)


def test_scalpel_pose_solver_6dof():
    """Verify ScalpelPoseSolver computes 6-DOF blade tip in desk coordinates."""
    import cv2
    from tracker.desk_calibration import get_default_desk_calibration
    from tracker.tool_pose_solver import ScalpelPoseSolver

    calib = get_default_desk_calibration(origin_cam=np.array([0.0, 50.0, 500.0]))
    K = np.array([[800.0, 0.0, 640.0], [0.0, 800.0, 360.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    dist = np.zeros(5, dtype=np.float64)
    solver = ScalpelPoseSolver(camera_matrix=K, dist_coeffs=dist, tag_size_mm=24.0, tip_offset_along_handle_mm=65.0)

    # Synthetic tag 1 corners in front of camera
    half = 12.0
    obj_pts = np.array([
        [-half, -half, 0.0],
        [ half, -half, 0.0],
        [ half,  half, 0.0],
        [-half,  half, 0.0]
    ], dtype=np.float64)
    tag_pos = np.array([0.0, 30.0, 480.0], dtype=np.float64)
    pts_cam = obj_pts + tag_pos

    img_pts, _ = cv2.projectPoints(pts_cam, np.zeros((3, 1)), np.zeros((3, 1)), K, dist)
    detected = {1: img_pts.reshape(4, 2)}

    pose = solver.solve_tool_pose(detected, calib, timestamp=0.0)
    assert pose is not None
    assert pose.confidence > 0.0
    assert len(pose.visible_tags) == 1
    assert -500.0 < pose.x_mm < 500.0
    assert -500.0 < pose.y_mm < 500.0
    assert -500.0 < pose.z_mm < 500.0


def test_desk_validation():
    """Verify DeskCalibration detects degenerate planes (Z < 150mm or inverted normal)."""
    from tracker.desk_calibration import get_default_desk_calibration, DeskCalibration

    valid = get_default_desk_calibration()
    assert valid.is_valid() is True

    # Behind camera
    bad_z = DeskCalibration(
        origin_cam=[0.0, 50.0, -25.0],
        r_cam_to_desk=valid.r_cam_to_desk,
        normal_cam=valid.normal_cam
    )
    assert bad_z.is_valid() is False

    # Normal pointing down or sideways
    bad_n = DeskCalibration(
        origin_cam=[0.0, 50.0, 450.0],
        r_cam_to_desk=valid.r_cam_to_desk,
        normal_cam=[0.0, 0.8, 0.0]
    )
    assert bad_n.is_valid() is False


def test_desk_user_drawn_rectangle():
    """Verify drawing a 2D bounding box on the camera feed projects to a valid 3D desk area."""
    from tracker.desk_calibration import (
        get_default_desk_calibration,
        get_default_camera_matrix,
        desk_pixel_to_3d,
        desk_rect_from_pixels
    )

    K, _ = get_default_camera_matrix(1280, 720)
    calib = get_default_desk_calibration(contact_z_mm=450.0, tilt_deg=28.0)

    # Pixel in lower center of image (on desk)
    p3d = desk_pixel_to_3d(640, 550, calib, K)
    assert p3d is not None
    assert p3d[2] > 200.0  # Safe positive depth in front of camera

    # User draws a rectangle in the lower screen (desk region)
    updated = desk_rect_from_pixels(400, 450, 880, 650, calib, K)
    assert updated is not None
    assert updated.is_valid() is True
    assert updated.calibration_method == "user-drawn-area"
    assert updated.extent_x_mm > 50.0
    assert updated.extent_z_mm > 50.0


