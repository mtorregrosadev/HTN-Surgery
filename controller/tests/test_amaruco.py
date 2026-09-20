"""Tests for the native AmarUco (ARUCO_MIP_36h12) controller detector.

Synthetic fixtures render the exact printed sheet style: black square, white
bit cells, wide white margin, mild perspective and blur, matching the physical
demo sheet and the tracking-web generator output.
"""
import math

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from scalpel_controller.amaruco import (  # noqa: E402
    CameraCalibration,
    DEFAULT_DICTIONARY,
    Detection,
    AmarucoDetector,
    _rvec_to_quaternion,
    frame_to_pose_update,
)


DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_ARUCO_MIP_36h12)


def render_printed_style(
    marker_id: int,
    cell: int = 40,
    perspective: float = 0.0,
    blur_sigma: float = 0.0,
    margin: int = 120,
) -> np.ndarray:
    """Render one marker as printed on the demo sheet (white cells on black)."""
    side = 8 * cell
    base = cv2.aruco.generateImageMarker(DICT, marker_id, side)
    cells = base.reshape(8, cell, 8, cell).mean(axis=(1, 3))
    cell01 = (cells > 127).astype(np.uint8)
    interior = np.kron(cell01[1:-1, 1:-1] * 255, np.ones((cell, cell), dtype=np.uint8))
    square = np.zeros((side, side), dtype=np.uint8)
    square[cell:side - cell, cell:side - cell] = interior

    size = side + 2 * margin
    canvas = np.full((size, size), 255, dtype=np.uint8)
    canvas[margin:margin + side, margin:margin + side] = square

    if perspective > 0.0:
        h, w = canvas.shape
        src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
        dst = np.float32([
            [perspective * w, perspective * h],
            [w * (1 - perspective * 0.6), 0],
            [w, h * (1 - perspective * 0.4)],
            [0, h * (1 - perspective)],
        ])
        canvas = cv2.warpPerspective(
            canvas,
            cv2.getPerspectiveTransform(src, dst),
            (w, h),
            borderValue=255,
        )
    if blur_sigma > 0.0:
        canvas = cv2.GaussianBlur(canvas, (0, 0), blur_sigma)
    return canvas


def calibration_for(image: np.ndarray, focal_px: float = 800.0) -> CameraCalibration:
    h, w = image.shape[:2]
    return CameraCalibration(
        calibration_id="test-cam-cal",
        camera_matrix=np.array([
            [focal_px, 0, w / 2],
            [0, focal_px, h / 2],
            [0, 0, 1],
        ]),
        dist_coeffs=np.zeros((5, 1)),
        image_width=w,
        image_height=h,
        marker_size_mm=30.0,
    )


def test_detects_printed_style_all_rotations_and_ids() -> None:
    det = AmarucoDetector(use_engine=False)
    for mid in (0, 1, 2, 7, 123, 249):
        for rot in range(4):
            img = np.rot90(render_printed_style(mid), rot)
            found = det.detect(img)
            assert any(d.marker_id == mid for d in found), f"id={mid} rot={rot}"


def test_detects_with_perspective_and_blur() -> None:
    det = AmarucoDetector(use_engine=False)
    img = render_printed_style(3, perspective=0.12, blur_sigma=2.2)
    found = det.detect(img)
    assert found, "printed-style marker lost under mild perspective/blur"
    assert found[0].marker_id == 3
    assert found[0].flags.count("degenerate") == 0


def test_uncalibrated_pose_is_flagged_not_invented() -> None:
    det = AmarucoDetector(use_engine=False)
    found = det.detect(render_printed_style(0))
    assert found
    assert found[0].tvec_mm is None
    assert "uncalibrated" in found[0].flags
    assert not found[0].pose_valid


def test_calibrated_pose_distance_accuracy() -> None:
    # The 30 mm marker outline renders 80 px wide at a 800 px-focal camera,
    # so metric depth must land near focal * size / pixels = 800*30/80 = 300 mm.
    cell = 10
    img = render_printed_style(0, cell=cell, margin=40)
    det = AmarucoDetector(calibration=calibration_for(img), use_engine=False)
    found = det.detect(img)
    assert found and found[0].pose_valid, "calibrated pose failed on clean render"
    tvec = found[0].tvec_mm
    assert tvec is not None
    depth = abs(tvec[2])
    assert 270.0 < depth < 330.0, f"depth {depth:.1f} mm out of expected band"
    assert found[0].reprojection_error_px < 1.0


def test_confidence_reflects_quality() -> None:
    det = AmarucoDetector(use_engine=False)
    clean = det.detect(render_printed_style(1))[0]
    rough = det.detect(render_printed_style(1, perspective=0.12, blur_sigma=2.2))[0]
    small = det.detect(render_printed_style(1, cell=4, margin=12))[0]
    assert clean.confidence >= rough.confidence >= 0.0
    assert "small-marker" in small.flags


def test_frame_to_pose_payload_uncalibrated() -> None:
    img = render_printed_style(2)
    det = AmarucoDetector(use_engine=False)
    found = det.detect(img)
    payload = frame_to_pose_update(found, img.shape[1], img.shape[0], 1234)
    assert payload is not None
    assert payload["source"] == "camera-amaruco"
    assert payload["markerId"] == 2
    assert payload["dictionary"] == DEFAULT_DICTIONARY
    assert payload["calibrated"] is False
    assert "positionMm" not in payload
    assert payload["pixelX"] > 0 and payload["pixelY"] > 0


def test_frame_to_pose_payload_calibrated() -> None:
    img = render_printed_style(2, cell=10, margin=40)
    det = AmarucoDetector(calibration=calibration_for(img), use_engine=False)
    found = det.detect(img)
    assert found[0].pose_valid
    payload = frame_to_pose_update(
        found,
        img.shape[1],
        img.shape[0],
        42,
        workspace={"calibrated": True, "scaleMmPerPixel": 1.0,
                   "originX": 10.0, "originY": 20.0, "originZ": 30.0},
    )
    assert payload is not None
    assert payload["calibrated"] is True
    assert "positionMm" in payload and "orientation" in payload
    qx, qy, qz, qw = (payload["orientation"][k] for k in ("qx", "qy", "qz", "qw"))
    norm = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
    assert abs(norm - 1.0) < 1e-6


def test_quaternion_helper_identity_and_rotation() -> None:
    assert _rvec_to_quaternion([0, 0, 0]) == (0.0, 0.0, 0.0, 1.0)
    qx, qy, qz, qw = _rvec_to_quaternion([math.pi, 0, 0])
    assert abs(qx - 1.0) < 1e-9 and abs(qw) < 1e-9


def test_empty_frame_returns_none_payload() -> None:
    blank = np.full((480, 640), 255, dtype=np.uint8)
    det = AmarucoDetector(use_engine=False)
    assert det.detect(blank) == []
    assert frame_to_pose_update([], 640, 480, 1) is None


def test_dictionary_rejects_unknown_name() -> None:
    with pytest.raises(Exception):
        AmarucoDetector(dictionaries=["NOT_A_DICT"], use_engine=False)


def test_detection_dict_shape() -> None:
    det = AmarucoDetector(use_engine=False)
    d = det.detect(render_printed_style(5))[0]
    raw = d.to_dict()
    assert set(raw) == {
        "markerId", "dictionary", "cornersPx", "centerPx", "sidePx",
        "tvecMm", "rvec", "reprojectionErrorPx", "poseValid",
        "confidence", "engine", "flags",
    }
    assert len(raw["cornersPx"]) == 4
    assert all(len(p) == 2 for p in raw["cornersPx"])
    assert isinstance(raw["markerId"], int)
    assert Detection is not None  # import sanity for type users
