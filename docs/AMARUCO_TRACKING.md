# AmarUco tracking (ARUCO_MIP_36h12)

Status: implemented and tested, 2026-09-19. The printed demo sheet the team
photographed ("AmarUco") is the **ARUCO_MIP_36h12** dictionary printed in the
tracking-web generator style: a black marker square with **white cells for
`1` bits** and a wide white paper margin. This is now a first-class, native
detection path on both the browser and controller sides.

## What was verified

- `js-aruco2` (tracking-web) and OpenCV 5 `DICT_ARUCO_MIP_36h12` are **bit-exact
  identical** dictionaries; the printed sheet decodes in both.
- OpenCV 5 detects the white-cells-on-black printed polarity natively, all
  rotations, with subpixel corner refinement.
- The controller detector's calibrated PnP pose lands within a few percent of
  ground-truth depth on synthetic fixtures (see `controller/tests/test_amaruco.py`).

## Components

| Piece | Location | Role |
| --- | --- | --- |
| Native detector | `controller/src/scalpel_controller/amaruco.py` | Multi-dictionary detection, subpixel corners, PnP pose (mm), quality flags |
| Detection service | `controller/src/scalpel_controller/amaruco_service.py` | Owns the camera loop, calibration state, publishing into `TrackingBridge` |
| Controller endpoints | `controller/src/scalpel_controller/app.py` | REST status/start/stop/calibration/workspace + pushed-frame WebSocket |
| Sheet generator | `scripts/generate_amaruco_sheet.py` | Prints exact-style sheets at true physical size, self-verifies before saving |
| Photo identifier | `scripts/identify_amaruco.py` | Decodes any printed sheet photo against every known dictionary |
| ArUco Nano (optional) | `third_party/aruco_nano/` | MIT-licensed header-only engine by the original ArUco authors (up to 6.5x faster, higher F1); cross-check when built |

Architecture boundary is preserved: detection is **controller-owned**; the
browser never talks to the API, SOFA, or MongoDB. Pose flows
tracking source -> controller -> API -> SOFA -> controller -> Unity/XR.

## Controller API

- `GET  /v1/tracking/amaruco/status` — engine, dictionaries, calibration IDs, FPS, last detections
- `POST /v1/tracking/amaruco/start`  — `{ "cameraIndex": 0, "dictionaries": ["ARUCO_MIP_36h12"] }`
- `POST /v1/tracking/amaruco/stop`
- `POST /v1/tracking/amaruco/calibration` — camera intrinsics (see below)
- `POST /v1/tracking/amaruco/workspace`   — camera->exercise transform; **requires** camera calibration first
- `WS   /v1/tracking/amaruco/stream` — push `{ "type": "frame", "dataBase64": "<jpeg/png>" , "timestampMs": 123 }`,
  receive `{ "type": "detections", ... }`

### Camera calibration payload

```json
{
  "calibrationId": "cam-cal-3",
  "cameraMatrix": [[fx, 0, cx], [0, fy, cy], [0, 0, 1]],
  "distCoeffs": [k1, k2, p1, p2, k3],
  "imageWidth": 1280,
  "imageHeight": 720,
  "markerSizeMm": 48.0
}
```

Produce it with `cv2.calibrateCamera` from a ChArUco/checkerboard session, or
any standard camera-calibration tool for your capture resolution. Camera
intrinsics are session-bound; moving the camera or changing resolution
invalidates them.

### Pose honesty rules

- Without camera intrinsics, detections carry `uncalibrated` and **no metric
  pose** is fabricated; the payload stays image-relative.
- With intrinsics but no workspace transform, metric PnP pose (OpenCV camera
  frame, mm, +X right / +Y down / +Z away from lens) is returned but flagged
  `calibrated: false` for the exercise frame.
- Calibrated pose publishes into `TrackingBridge` with source
  `camera-amaruco`, marker ID, confidence, and timestamp, then follows the
  normal controller -> API -> SOFA path.
- Small (<35 px) or degenerate detections are flagged and never silently used.

## Usage

```bash
# Print an exact-style sheet (48 mm markers, IDs 0,1,2 at 100% scale)
python3 scripts/generate_amaruco_sheet.py /tmp/sheet --ids 0,1,2 --cell-mm 6

# Identify an unknown printed sheet from a photo
python3 scripts/identify_amaruco.py photo.jpg

# Start services
cd backend && python -m uvicorn surge_prep.app:app --port 8000
cd controller && python -m uvicorn scalpel_controller.app:app --app-dir src --port 8100
cd tracking-web && npm run dev   # http://localhost:5173

# Arm controller-side detection
curl -X POST localhost:8100/v1/tracking/amaruco/start \
  -H 'content-type: application/json' -d '{"cameraIndex": 0}'
```

## Tests

```bash
cd controller && python3 -m pytest -q          # 32 tests incl. 18 AmarUco tests
cd tracking-web && npm test && npm run build   # 21 tests incl. printed-style test
```

## Limits

- Monocular PnP depth is only as good as the intrinsics and marker size;
  calibrate at the actual capture resolution before trusting millimetres.
- A flat marker cannot be seen from behind or edge-on; multi-face tool mounts
  remain the plan in `docs/ARUCO_WORKSPACE_PLAN.md`.
- The optional ArUco Nano C++ cross-check needs `cmake` + OpenCV dev headers
  to build; without it the detector runs OpenCV-only with no loss of
  correctness, only of the second engine's confirmation.
- Synthetic tests cannot substitute the physical acceptance run (mm/deg
  error, jitter, latency) on the real camera and headset.
