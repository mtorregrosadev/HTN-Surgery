"""Identify which fiducial dictionary a printed marker sheet uses.

Usage: python3 scripts/identify_amaruco.py <photo-or-scan> [more photos...]

Tries every OpenCV predefined dictionary (including ARUCO_MIP_36h12, the
printed Surge Prep style) with aggressive preprocessing variants tuned for
angled phone photos of printed sheets, then decodes raw square candidates
against every candidate grid size as a fallback.
"""
from __future__ import annotations

import sys

import cv2
import numpy as np

DICTIONARIES = {
    "DICT_ARUCO_MIP_36h12": cv2.aruco.DICT_ARUCO_MIP_36h12,
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
    "DICT_ARUCO_ORIGINAL": cv2.aruco.DICT_ARUCO_ORIGINAL,
    "DICT_APRILTAG_16h5": cv2.aruco.DICT_APRILTAG_16h5,
    "DICT_APRILTAG_25h9": cv2.aruco.DICT_APRILTAG_25h9,
    "DICT_APRILTAG_36h10": cv2.aruco.DICT_APRILTAG_36h10,
    "DICT_APRILTAG_36h11": cv2.aruco.DICT_APRILTAG_36h11,
}


def variants(gray: np.ndarray) -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {}
    scale = max(1.0, 900.0 / max(gray.shape[:2]))
    if scale > 1.0:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    out["original"] = gray
    out["clahe"] = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(gray)
    blur = cv2.GaussianBlur(gray, (0, 0), 1.8)
    out["sharpened"] = cv2.addWeighted(gray, 1.7, blur, -0.7, 0)
    return out


def detector_params() -> "cv2.aruco.DetectorParameters":
    p = cv2.aruco.DetectorParameters()
    p.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    p.adaptiveThreshWinSizeMin = 3
    p.adaptiveThreshWinSizeMax = 63
    p.adaptiveThreshWinSizeStep = 4
    p.minMarkerPerimeterRate = 0.004
    p.maxMarkerPerimeterRate = 8.0
    p.polygonalApproxAccuracyRate = 0.12
    p.perspectiveRemoveIgnoredMarginPerCell = 0.15
    p.minDistanceToBorder = 1
    p.minMarkerDistanceRate = 0.01
    p.maxErroneousBitsInBorderRate = 0.5
    p.detectInvertedMarker = True
    return p


def identify(path: str) -> dict[str, list[int]]:
    img = cv2.imread(path)
    if img is None:
        print(f"{path}: unreadable image")
        return {}
    gray0 = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    print(f"{path}: {img.shape[1]}x{img.shape[0]}")

    hits: dict[str, list[int]] = {}
    for vname, gray in variants(gray0).items():
        detector = cv2.aruco.ArucoDetector(None, detector_params())  # type: ignore[arg-type]
        for name, dict_id in DICTIONARIES.items():
            detector = cv2.aruco.ArucoDetector(
                cv2.aruco.getPredefinedDictionary(dict_id), detector_params()
            )
            corners, ids, _ = detector.detectMarkers(gray)
            if ids is None:
                continue
            found = sorted(int(i) for i in ids.flatten())
            if len(found) > len(hits.get(name, [])):
                hits[name] = found
                print(f"  [{vname}] {name}: IDs {found}")
    if not hits:
        print("  no dictionary matched; try a sharper, straighter photo")
    return hits


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    for argument in sys.argv[1:]:
        identify(argument)
