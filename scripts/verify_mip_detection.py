"""Verify OpenCV 5 detects the printed AmarUco style: ARUCO_MIP_36h12 markers
with white bit cells on a black square background (js-aruco2 generateSVG style)."""
import cv2
import numpy as np

DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_ARUCO_MIP_36h12)


def render_mip_style(marker_id, size=420):
    """Render like js-aruco2 generateSVG: white bg, black square, white '1' bits."""
    n = 6
    side = (n + 2) * 50
    base = cv2.aruco.generateImageMarker(DICT, marker_id, side)
    _, bw = cv2.threshold(base, 127, 255, cv2.THRESH_BINARY)
    # standard: white border ring, black field, black=0 bits, white=1 bits
    inv = 255 - bw  # black border ring, white field, white 0-bits, black 1-bits... no
    # js-aruco2 style is: outer margin white (2 cells), 1-cell black border,
    # inside: bits '1' -> white, '0' -> black
    cells = bw.reshape(n + 2, 50, n + 2, 50).mean(axis=(1, 3))
    cell01 = (cells > 127).astype(np.uint8)  # standard: white cell == 1
    inner = cell01[1:-1, 1:-1]  # the 6x6 data bits (white==1 in standard render)
    # js-aruco2 style: whole square black; data bit '1' -> white cell
    canvas = np.zeros((side, side), dtype=np.uint8)
    inner_px = np.kron(255 - inner * 255, np.ones((50, 50), dtype=np.uint8))
    canvas[50:side - 50, 50:side - 50] = inner_px  # black bg, white '1' bits
    canvas[0:50, :] = 0
    canvas[-50:, :] = 0
    canvas[:, 0:50] = 0
    canvas[:, -50:] = 0
    out = np.full((size, size), 255, dtype=np.uint8)  # white paper margin
    off = (size - side) // 2
    out[off:off + side, off:off + side] = canvas
    return out


def render_standard(marker_id, size=420):
    side = (6 + 2) * 50
    base = cv2.aruco.generateImageMarker(DICT, marker_id, side)
    out = np.full((size, size), 255, dtype=np.uint8)
    off = (size - side) // 2
    out[off:off + side, off:off + side] = base
    return out


def rotated(gray, quarter):
    return np.rot90(gray, quarter) if quarter else gray


params = cv2.aruco.DetectorParameters()
params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX

for style, render in (("jsaruco2-white-on-black", render_mip_style), ("standard", render_standard)):
    print(f"--- {style} ---")
    for mid in (0, 1, 2, 7, 123, 249):
        for rot in range(4):
            g = rotated(render(mid), rot)
            det = cv2.aruco.ArucoDetector(DICT, params)
            corners, ids, _ = det.detectMarkers(g)
            got = [int(i) for i in ids.flatten()] if ids is not None else []
            ok = mid in got
            if not ok:
                print(f"  id={mid} rot={rot}: MISS (got {got})")
    print("  done")

# inverted detection check
params2 = cv2.aruco.DetectorParameters()
params2.detectInvertedMarker = True
params2.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
det2 = cv2.aruco.ArucoDetector(DICT, params2)
g = render_mip_style(0)
corners, ids, _ = det2.detectMarkers(g)
print("inverted-mode detection of white-on-black id 0:", [int(i) for i in ids.flatten()] if ids is not None else "NONE")
