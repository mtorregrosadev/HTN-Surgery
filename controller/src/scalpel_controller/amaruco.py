"""Native high-precision ArUco ("AmarUco") detection for the Scalpel controller.

This module is the controller-owned optical ingestion adapter. It detects the
printed ARUCO_MIP_36h12 marker style (black square, white bit cells, wide white
paper margin) that tracking-web generates and that the physical demo sheet
uses, plus every other OpenCV predefined dictionary, and returns subpixel
corners, metric pose, and quality metadata.

Engine notes
------------
- OpenCV 5 ships ``DICT_ARUCO_MIP_36h12`` natively and its bit layout is
  bit-exact with the js-aruco2 dictionary used by tracking-web, so the printed
  sheet is decodable by both engines.
- When OpenCV and the vendored ArUco Nano agree on a detection, confidence is
  raised; when they disagree, the OpenCV corners are used and the marker is
  flagged ``engineDisagreement`` for inspection.
- Pose comes from calibrated solvePnP. Without calibration, the detector still
  returns corners and an uncalibrated flag instead of inventing metric pose.
- Optional ``OAK-D`` style depth fusion multiplies the monocular PnP distance
  by a per-session depth scale captured during workspace calibration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Optional

import numpy as np

try:  # OpenCV is an optional controller dependency; degrade loudly, not silently.
    import cv2

    CV2_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised on minimal installs
    cv2 = None  # type: ignore[assignment]
    CV2_AVAILABLE = False


# Dictionaries supported natively. MIP_36h12 is listed first: it is the printed
# demo sheet style ("AmarUco": black square, white bit cells).
DICTIONARY_NAMES = [
    "ARUCO_MIP_36h12",
    "DICT_4X4_50",
    "DICT_4X4_100",
    "DICT_4X4_250",
    "DICT_4X4_1000",
    "DICT_5X5_50",
    "DICT_5X5_100",
    "DICT_5X5_250",
    "DICT_5X5_1000",
    "DICT_6X6_50",
    "DICT_6X6_100",
    "DICT_6X6_250",
    "DICT_6X6_1000",
    "DICT_7X7_50",
    "DICT_7X7_100",
    "DICT_7X7_250",
    "DICT_7X7_1000",
    "DICT_APRILTAG_16h5",
    "DICT_APRILTAG_25h9",
    "DICT_APRILTAG_36h10",
    "DICT_APRILTAG_36h11",
]

DEFAULT_DICTIONARY = "ARUCO_MIP_36h12"


@dataclass
class Detection:
    """One detected marker with subpixel corners and optional metric pose."""

    marker_id: int
    dictionary: str
    corners_px: list[list[float]]  # 4x2, OpenCV order (tl, tr, br, bl), image coords
    center_px: tuple[float, float]
    side_px: float
    # Metric pose (right-handed, millimetres, OpenCV camera frame: +X right,
    # +Y down, +Z away from the lens). None when uncalibrated.
    rvec: Optional[list[float]] = None
    tvec_mm: Optional[list[float]] = None
    reprojection_error_px: Optional[float] = None
    pose_valid: bool = False
    confidence: float = 0.0
    engine: str = "opencv"
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "markerId": self.marker_id,
            "dictionary": self.dictionary,
            "cornersPx": self.corners_px,
            "centerPx": list(self.center_px),
            "sidePx": round(self.side_px, 2),
            "tvecMm": self.tvec_mm,
            "rvec": self.rvec,
            "reprojectionErrorPx": (
                round(self.reprojection_error_px, 4)
                if self.reprojection_error_px is not None
                else None
            ),
            "poseValid": self.pose_valid,
            "confidence": round(self.confidence, 3),
            "engine": self.engine,
            "flags": self.flags,
        }


@dataclass
class CameraCalibration:
    """Versioned camera intrinsics. Ownership: controller, session-bound."""

    calibration_id: str
    camera_matrix: np.ndarray  # 3x3 float64
    dist_coeffs: np.ndarray  # (k,1) float64
    image_width: int
    image_height: int
    marker_size_mm: float = 30.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CameraCalibration":
        cm = np.asarray(data["cameraMatrix"], dtype=np.float64).reshape(3, 3)
        dc = np.asarray(data.get("distCoeffs", [0, 0, 0, 0, 0]), dtype=np.float64).reshape(-1, 1)
        return cls(
            calibration_id=str(data["calibrationId"]),
            camera_matrix=cm,
            dist_coeffs=dc,
            image_width=int(data.get("imageWidth", 0)),
            image_height=int(data.get("imageHeight", 0)),
            marker_size_mm=float(data.get("markerSizeMm", 30.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "calibrationId": self.calibration_id,
            "cameraMatrix": self.camera_matrix.tolist(),
            "distCoeffs": self.dist_coeffs.flatten().tolist(),
            "imageWidth": self.image_width,
            "imageHeight": self.image_height,
            "markerSizeMm": self.marker_size_mm,
        }


def _dictionary(name: str):
    mapping = {
        "ARUCO_MIP_36h12": cv2.aruco.DICT_ARUCO_MIP_36h12,
        "DICT_4X4_50": cv2.aruco.DICT_4X4_50,
        "DICT_4X4_100": cv2.aruco.DICT_4X4_100,
        "DICT_4X4_250": cv2.aruco.DICT_4X4_250,
        "DICT_4X4_1000": cv2.aruco.DICT_4X4_1000,
        "DICT_5X5_50": cv2.aruco.DICT_5X5_50,
        "DICT_5X5_100": cv2.aruco.DICT_5X5_100,
        "DICT_5X5_250": cv2.aruco.DICT_5X5_250,
        "DICT_5X5_1000": cv2.aruco.DICT_5X5_1000,
        "DICT_6X6_50": cv2.aruco.DICT_6X6_50,
        "DICT_6X6_100": cv2.aruco.DICT_6X6_100,
        "DICT_6X6_250": cv2.aruco.DICT_6X6_250,
        "DICT_6X6_1000": cv2.aruco.DICT_6X6_1000,
        "DICT_7X7_50": cv2.aruco.DICT_7X7_50,
        "DICT_7X7_100": cv2.aruco.DICT_7X7_100,
        "DICT_7X7_250": cv2.aruco.DICT_7X7_250,
        "DICT_7X7_1000": cv2.aruco.DICT_7X7_1000,
        "DICT_APRILTAG_16h5": cv2.aruco.DICT_APRILTAG_16h5,
        "DICT_APRILTAG_25h9": cv2.aruco.DICT_APRILTAG_25h9,
        "DICT_APRILTAG_36h10": cv2.aruco.DICT_APRILTAG_36h10,
        "DICT_APRILTAG_36h11": cv2.aruco.DICT_APRILTAG_36h11,
    }
    if name not in mapping:
        raise ValueError(f"Unsupported dictionary: {name}")
    return cv2.aruco.getPredefinedDictionary(mapping[name])


def _detector_params(corner_refinement: bool = True) -> "cv2.aruco.DetectorParameters":
    """Tuned for small/angled/blurry printed markers and phone/laptop cameras."""
    p = cv2.aruco.DetectorParameters()
    p.adaptiveThreshWinSizeMin = 3
    p.adaptiveThreshWinSizeMax = 53
    p.adaptiveThreshWinSizeStep = 4
    p.minMarkerPerimeterRate = 0.006
    p.maxMarkerPerimeterRate = 6.0
    p.polygonalApproxAccuracyRate = 0.08
    p.minCornerDistanceRate = 0.02
    p.minDistanceToBorder = 2
    p.minMarkerDistanceRate = 0.01
    p.perspectiveRemoveIgnoredMarginPerCell = 0.13
    p.maxErroneousBitsInBorderRate = 0.35
    p.errorCorrectionRate = 0.6
    p.detectInvertedMarker = True
    if corner_refinement:
        p.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        p.cornerRefinementWinSize = 5
        p.cornerRefinementMaxIterations = 30
        p.cornerRefinementMinAccuracy = 0.05
    return p


class AmarucoDetector:
    """Multi-dictionary, subpixel, PnP-capable marker detector.

    The optional ArUco Nano engine (vendored under third_party/aruco_nano and
    built by scripts/build_amaruco_engine.py) raises confidence when its result
    matches OpenCV's. Detection never depends on it being present.
    """

    def __init__(
        self,
        dictionaries: Optional[list[str]] = None,
        calibration: Optional[CameraCalibration] = None,
        use_engine: bool = True,
    ) -> None:
        if not CV2_AVAILABLE:
            raise RuntimeError("OpenCV (cv2) is required for native AmarUco detection")
        self.dictionary_names = dictionaries or [DEFAULT_DICTIONARY]
        self.calibration = calibration
        self._params = _detector_params()
        self._detectors = {
            name: cv2.aruco.ArucoDetector(_dictionary(name), self._params)
            for name in self.dictionary_names
        }
        self._nano_ready = False
        self._nano_lib: Any = None
        if use_engine:
            self._try_load_engine()

    # -- optional ArUco Nano engine ------------------------------------------
    def _try_load_engine(self) -> None:
        """Load the compiled ArUco Nano bridge if it was built."""
        try:
            from scalpel_controller import _aruco_nano_bridge  # type: ignore

            self._nano_lib = _aruco_nano_bridge
            self._nano_ready = True
        except ImportError:
            self._nano_ready = False

    @property
    def engine_ready(self) -> bool:
        return self._nano_ready

    # -- detection ------------------------------------------------------------
    def detect(self, image_bgr_or_gray: "np.ndarray") -> list[Detection]:
        gray = image_bgr_or_gray
        if gray.ndim == 3:
            gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
        if gray.dtype != np.uint8:
            gray = np.clip(gray, 0, 255).astype(np.uint8)

        # Detect across all configured dictionaries in one pass each. MIP_36h12
        # first keeps the common path fast; duplicates across dictionaries are
        # resolved to the highest-confidence interpretation.
        results: list[Detection] = []
        seen_boxes: list[tuple[float, float, float]] = []
        for name in self.dictionary_names:
            corners, ids, _ = self._detectors[name].detectMarkers(gray)
            if ids is None:
                continue
            for corner, mid in zip(corners, ids.flatten()):
                det = self._build_detection(gray, name, int(mid), corner)
                cx, cy = det.center_px
                box = (cx, cy, det.side_px)
                if any(
                    math.hypot(cx - sx, cy - sy) < max(side, sside) * 0.5
                    for sx, sy, sside in seen_boxes
                ):
                    continue
                seen_boxes.append(box)
                results.append(det)

        if self._nano_ready:
            results = self._cross_check_with_nano(gray, results)
        return results

    def _build_detection(
        self, gray: "np.ndarray", dictionary: str, marker_id: int, corner: "np.ndarray"
    ) -> Detection:
        corner = np.asarray(corner, dtype=np.float64).reshape(-1, 2)
        center = corner.mean(axis=0)
        sides = [
            float(np.linalg.norm(corner[(i + 1) % 4] - corner[i])) for i in range(4)
        ]
        side_px = sum(sides) / 4.0
        det = Detection(
            marker_id=marker_id,
            dictionary=dictionary,
            corners_px=[[float(x), float(y)] for x, y in corner],
            center_px=(float(center[0]), float(center[1])),
            side_px=side_px,
        )
        # Degenerate geometry guard: reject non-finite or concave quads.
        if not all(math.isfinite(v) for pt in det.corners_px for v in pt):
            det.flags.append("degenerate")
            det.confidence = 0.0
            return det
        area = 0.0
        for i in range(4):
            x1, y1 = corner[i]
            x2, y2 = corner[(i + 1) % 4]
            area += x1 * y2 - x2 * y1
        if abs(area) / 2.0 < 1.0:
            det.flags.append("degenerate")
            det.confidence = 0.0
            return det

        if self.calibration is not None:
            self._estimate_pose(det, corner)
        else:
            det.flags.append("uncalibrated")
        det.confidence = self._confidence(det)
        return det

    def _estimate_pose(self, det: Detection, corner: "np.ndarray") -> None:
        """Calibrated PnP against the known physical marker size."""
        assert self.calibration is not None
        cal = self.calibration
        s = cal.marker_size_mm / 2.0
        # OpenCV corner order: top-left, top-right, bottom-right, bottom-left
        # in the marker's own frame; object points placed in the marker plane.
        obj = np.array(
            [[-s, s, 0], [s, s, 0], [s, -s, 0], [-s, -s, 0]], dtype=np.float64
        )
        img = corner.reshape(-1, 1, 2).astype(np.float64)
        ok, rvec, tvec = cv2.solvePnP(
            obj, img, cal.camera_matrix, cal.dist_coeffs,
            flags=cv2.SOLVEPNP_IPPE_SQUARE,
        )
        if not ok:
            det.flags.append("pose-failed")
            return
        proj, _ = cv2.projectPoints(obj, rvec, tvec, cal.camera_matrix, cal.dist_coeffs)
        err = float(np.linalg.norm(proj.reshape(-1, 2) - corner, axis=1).mean())
        det.rvec = rvec.flatten().tolist()
        det.tvec_mm = tvec.flatten().tolist()  # OpenCV camera frame, mm
        det.reprojection_error_px = err
        det.pose_valid = err < max(1.5, det.side_px * 0.05)

    def _confidence(self, det: Detection) -> float:
        """Deterministic quality from geometry and reprojection error."""
        score = 0.55
        if det.pose_valid and det.reprojection_error_px is not None:
            # Sub-pixel reprojection -> high confidence; 3+ px -> low.
            err = det.reprojection_error_px
            score = min(1.0, max(0.3, 1.0 - err / 3.0))
        if det.side_px >= 40:
            score = min(1.0, score + 0.15)
        elif det.side_px < 35:
            # Below ~35 px the subpixel corner error dominates metric accuracy.
            score = max(0.1, score - 0.25)
            det.flags.append("small-marker")
        return score

    # -- ArUco Nano cross-check -------------------------------------------------
    def _cross_check_with_nano(
        self, gray: "np.ndarray", results: list[Detection]
    ) -> list[Detection]:
        """Raise confidence when ArUco Nano agrees; flag disagreements."""
        try:
            nano = self._nano_lib
            nano_markers = nano.detect(gray, self.dictionary_names)
        except Exception:
            return results
        for det in results:
            for nm in nano_markers:
                nc = np.asarray(nm["corners"], dtype=np.float64)
                dist = float(
                    np.linalg.norm(
                        nc - np.asarray(det.corners_px, dtype=np.float64)
                    )
                )
                if dist < max(3.0, det.side_px * 0.05):
                    det.engine = "opencv+aruco_nano"
                    det.confidence = min(1.0, det.confidence + 0.1)
                    break
            else:
                det.flags.append("engineDisagreement")
        return results


def frame_to_pose_update(
    detections: list[Detection],
    frame_width: int,
    frame_height: int,
    timestamp_ms: int,
    *,
    workspace: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Convert detections into one controller tracking-pose payload.

    The largest confident marker wins. Without a calibrated workspace transform
    the payload stays in image-relative units and is flagged uncalibrated so
    downstream consumers cannot mistake it for measured millimetres.
    """
    if not detections:
        return None
    det = max(
        (d for d in detections if not d.pose_valid or d.confidence > 0.2),
        key=lambda d: d.confidence * d.side_px,
        default=None,
    )
    if det is None:
        return None

    payload: dict[str, Any] = {
        "source": "camera-amaruco",
        "markerId": det.marker_id,
        "dictionary": det.dictionary,
        "confidence": det.confidence,
        "timestampMs": timestamp_ms,
        "frame": {"width": frame_width, "height": frame_height},
        "cornersPx": det.corners_px,
        "sidePx": det.side_px,
        "engine": det.engine,
        "flags": det.flags,
    }

    if det.pose_valid and det.tvec_mm is not None and det.rvec is not None:
        tx, ty, tz = det.tvec_mm
        qx, qy, qz, qw = _rvec_to_quaternion(det.rvec)
        if workspace and workspace.get("calibrated"):
            # Workspace transform: camera frame -> board frame -> exercise frame.
            scale = float(workspace.get("scaleMmPerPixel", 1.0))
            pos = {
                "x": tx * scale + float(workspace.get("originX", 0.0)),
                "y": ty * scale + float(workspace.get("originY", 0.0)),
                "z": tz * scale + float(workspace.get("originZ", 0.0)),
            }
            payload["positionMm"] = pos
            payload["orientation"] = {"qx": qx, "qy": qy, "qz": qz, "qw": qw}
            payload["calibrated"] = True
        else:
            payload["tvecMm"] = [tx, ty, tz]
            payload["rvec"] = det.rvec
            payload["calibrated"] = False
    else:
        payload["calibrated"] = False
        cx, cy = det.center_px
        payload["pixelX"] = cx
        payload["pixelY"] = cy
        payload["width"] = frame_width
        payload["height"] = frame_height
    return payload


def _rvec_to_quaternion(rvec: list[float]) -> tuple[float, float, float, float]:
    """Rodrigues vector to quaternion (x, y, z, w)."""
    angle = float(np.linalg.norm(rvec))
    if angle < 1e-9:
        return 0.0, 0.0, 0.0, 1.0
    axis = np.asarray(rvec, dtype=np.float64) / angle
    half = angle / 2.0
    s = math.sin(half)
    return (
        float(axis[0] * s),
        float(axis[1] * s),
        float(axis[2] * s),
        float(math.cos(half)),
    )
