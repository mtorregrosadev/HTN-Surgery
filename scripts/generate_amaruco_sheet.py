"""Generate printable AmarUco (ARUCO_MIP_36h12) sheets in the exact printed style.

Renders the physical demo style: black marker square, white cells for '1'
bits, wide white quiet margin around each marker, laid out in a row at true
physical size for the chosen DPI. The rendered sheet is re-detected with
OpenCV before saving so a broken sheet can never ship silently.

Usage:
  python3 scripts/generate_amaruco_sheet.py OUT_DIR [--ids 0,1,2]
      [--cell-mm 6] [--dpi 300] [--marker-mm 48]
"""
from __future__ import annotations

import argparse
import pathlib

import cv2
import numpy as np

GRID = 8  # MIP_36h12: 6 data cells + 1-cell black border on each side


def render_marker(dictionary, marker_id: int, cell_px: int) -> np.ndarray:
    """One marker square: black background, white cells for '1' bits."""
    side = GRID * cell_px
    base = cv2.aruco.generateImageMarker(dictionary, marker_id, side)
    cells = base.reshape(GRID, cell_px, GRID, cell_px).mean(axis=(1, 3))
    cell01 = (cells > 127).astype(np.uint8)
    interior = np.kron(
        cell01[1:-1, 1:-1] * 255, np.ones((cell_px, cell_px), dtype=np.uint8)
    )
    square = np.zeros((side, side), dtype=np.uint8)
    square[cell_px:side - cell_px, cell_px:side - cell_px] = interior
    return square


def build_sheet(dictionary, ids: list[int], cell_px: int, quiet_px: int) -> np.ndarray:
    markers = [render_marker(dictionary, mid, cell_px) for mid in ids]
    marker_px = markers[0].shape[0]
    height = marker_px + 2 * quiet_px
    width = sum(marker_px + 2 * quiet_px for _ in markers)
    sheet = np.full((height, width), 255, dtype=np.uint8)
    x = 0
    for marker in markers:
        sheet[quiet_px:quiet_px + marker_px, x + quiet_px:x + quiet_px + marker_px] = marker
        x += marker_px + 2 * quiet_px
    return sheet


def verify_sheet(sheet: np.ndarray, ids: list[int]) -> list[int]:
    detector = cv2.aruco.ArucoDetector(
        cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_ARUCO_MIP_36h12),
        cv2.aruco.DetectorParameters(),
    )
    corners, found_ids, _ = detector.detectMarkers(sheet)
    found = sorted(int(i) for i in found_ids.flatten()) if found_ids is not None else []
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out_dir", type=pathlib.Path)
    parser.add_argument("--ids", default="0,1,2", help="comma-separated marker IDs")
    parser.add_argument("--cell-mm", type=float, default=6.0, help="printed size of one cell")
    parser.add_argument("--dpi", type=int, default=300)
    args = parser.parse_args()

    ids = [int(x) for x in args.ids.split(",") if x != ""]
    cell_px = max(8, round(args.cell_mm / 25.4 * args.dpi))
    quiet_px = cell_px * 2  # generous white margin, as printed on the demo sheet

    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_ARUCO_MIP_36h12)
    sheet = build_sheet(dictionary, ids, cell_px, quiet_px)

    found = verify_sheet(sheet, ids)
    if found != sorted(ids):
        raise SystemExit(f"self-verification failed: rendered {ids}, detected {found}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    name = "amaruco-mip36h12-" + "-".join(str(i) for i in ids) + ".png"
    out_path = args.out_dir / name
    cv2.imencode(".png", sheet)[1].tofile(str(out_path))

    marker_mm = GRID * args.cell_mm
    print(f"sheet: {out_path}")
    print(f"marker size when printed at {args.dpi} DPI: {marker_mm:.0f} mm square "
          f"({args.cell_mm:.0f} mm cells); set the print dialog to 100% scale / no fit")


if __name__ == "__main__":
    main()
