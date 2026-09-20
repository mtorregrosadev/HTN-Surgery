"""Determine bit polarity conventions: OpenCV MIP_36h12 marker image vs
js-aruco2 codeList and its white-on-black SVG style. Then test detection
of the actual printed style with OpenCV and polarity variants."""
import pathlib
import re

import cv2
import numpy as np

DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_ARUCO_MIP_36h12)

# --- OpenCV's own rendering of id 0 ------------------------------------------
side = 8 * 50
m = cv2.aruco.generateImageMarker(DICT, 0, side)
cells = m.reshape(8, 50, 8, 50).mean(axis=(1, 3))
white = (cells > 127).astype(np.uint8)
print("OpenCV generateImageMarker id0: border ring values (should be all 0 or all 1):")
print(white[0, :])
print("OpenCV interior white-bit map (1=white cell):")
print(white[1:-1, 1:-1])

# --- js-aruco2 codeList id 0 ---------------------------------------------------
txt = pathlib.Path("tracking-web/node_modules/js-aruco2/src/dictionaries/aruco_mip_36h12.js").read_text()
mm = re.search(r"codeList:\s*\[([^\]]+)\]", txt, re.S)
codes = [int(x, 16) for x in re.findall(r"0x[0-9a-fA-F]+", mm.group(1))]
code0 = codes[0]
bits_msb = [(code0 >> (35 - b)) & 1 for b in range(36)]
print("\njs-aruco2 codeList[0] bits (MSB first):")
print(np.array(bits_msb, dtype=np.uint8).reshape(6, 6))
print("OpenCV interior flattened (1=white):", white[1:-1, 1:-1].flatten().tolist())
print("js bits:", bits_msb)
print("equal:", bits_msb == white[1:-1, 1:-1].flatten().tolist())
print("equal inverted:", bits_msb == (1 - white[1:-1, 1:-1]).flatten().tolist())

# check bit-order variants too
ocv = white[1:-1, 1:-1]
for name, arr in (("ocv", ocv), ("ocv.T", ocv.T)):
    for pol, a in (("white=1", arr), ("black=1", 1 - arr)):
        flat = a.flatten().tolist()
        for label, jb in (("msb", bits_msb), ("lsb", bits_msb[::-1])):
            if flat == jb:
                print(f"MATCH: js {label} == {name} {pol}")

# --- render js-aruco2 print style (black square, white '1' bits) --------------
def render_js_style(mid, size=480):
    n = 6
    code = codes[mid]
    bits = np.array([(code >> (35 - b)) & 1 for b in range(36)], dtype=np.uint8).reshape(n, n)
    cell = 50
    sq = (n + 2) * cell
    canvas = np.zeros((sq, sq), dtype=np.uint8)  # black square
    interior = np.kron(bits * 255, np.ones((cell, cell), dtype=np.uint8))
    canvas[cell:sq - cell, cell:sq - cell] = interior  # white '1' bits
    out = np.full((size, size), 255, dtype=np.uint8)  # white paper
    off = (size - sq) // 2
    out[off:off + sq, off:off + sq] = canvas
    return out

params = cv2.aruco.DetectorParameters()
params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX

for label, g in (("js-style as printed", render_js_style(0)),
                 ("js-style inverted image", 255 - render_js_style(0))):
    for inv_flag in (False, True):
        p2 = cv2.aruco.DetectorParameters()
        p2.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        p2.detectInvertedMarker = inv_flag
        det = cv2.aruco.ArucoDetector(DICT, p2)
        corners, ids, _ = det.detectMarkers(g)
        got = [int(i) for i in ids.flatten()] if ids is not None else []
        print(f"{label} | detectInvertedMarker={inv_flag} -> {got}")
