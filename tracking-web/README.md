# Browser optical tracking demo

This browser app tracks a **blunt training tool** from camera frames. It detects
an attached ArUco marker and the tool's purple body, provides a 2D diagnostic
view, and publishes the latest image-derived observation to the Scalpel
controller over `WS /v1/tracking/stream`. It is an integrated camera input
producer, while remaining a proof of concept for pose estimation. It does not
claim calibrated 3D tool-tip position or clinical accuracy.

## Run

```bash
cd tracking-web
npm ci
npm run dev
```

Start the API at `localhost:8000` and the Scalpel controller at
`localhost:8100` before using a live session. The controller's API upstream is
the only backend connection; the browser does not connect directly to the API,
SOFA, MongoDB, or embedded hardware. A Unity showcase client (or another
controller client) must open a session and send samples over the controller's
session stream so the controller can merge the latest optical pose and hardware
telemetry before forwarding the sample to the API. For native SOFA, use
`scripts/start-showcase.sh`; the memory simulator is a development fallback and
must be identified as offline/development in the showcase.

For the memory path, run the API and controller in separate terminals after
installing their local packages:

```bash
# terminal 1: memory-development API
cd backend
python -m uvicorn surge_prep.app:app --reload --port 8000

# terminal 2: Scalpel controller
cd controller
python -m uvicorn scalpel_controller.app:app --app-dir src --port 8100
```

The native showcase script starts both services with native SOFA; do not run
the memory commands alongside it.

Open `http://localhost:5173/`, choose a marker family, and use **Show matching marker #0** to display or download the exact image the detector expects. The app redirects a numeric loopback page to `localhost` for camera permissions, so use the `localhost` URL above. Print the marker or show it on another device with the **entire white margin** visible. Keep the phone display free of dark full-screen backgrounds around the marker, reflections, and UI overlays. Attach the printed marker rigidly to a blunt tool. Start the camera and keep the marker or purple tool in view. Camera access requires the browser's permission and a secure context. Do not use the setup on people or with a clinical instrument.

The guided Z flow requires no measurement: **(1)** start the camera or demo, **(2)** hold one marker still facing the lens until eight stable detections set the starting position, and **(3)** move it toward or away from the lens. **Restart Z calibration** sets a new starting position and is an explicit marker-selection reset. Otherwise the tracker locks onto the first accepted marker ID for the current source, keeps that lock through temporary loss, and will not silently switch to a different square; restarting the source or changing the marker family also selects afresh. Z is a **relative percentage of the starting camera distance**, with positive values farther away and negative values closer. It is not an absolute distance in millimetres; a monocular camera cannot infer that from an unknown marker size on a phone display.

If the browser reports **No camera found**, connect a webcam, open the page on a device with a camera, or choose **Open video file** to analyze a local recording. **Try synthetic demo** first holds a generated marker and purple scalpel still for automatic calibration, then moves them across the image and toward/away from the virtual camera so the browser display can be checked without hardware. Neither source is uploaded. If the controller is unavailable, the page can still display local measurements, but it cannot feed a session.

The default marker family is OpenCV `DICT_5X5_250`, which recognizes IDs 0–249 and matches the common 5×5 marker generator shown in the camera test. The page also supports OpenCV `DICT_4X4_50` (IDs 0–49) and Surge Prep `ARUCO_MIP_36h12` (ID 0). Select the **exact dictionary** shown by your marker generator. The generated preview and downloads always match the selected family. A similarly shaped marker from another generator can have different bits or a different ID; use the image from this page if the family is unknown.

When tracking fails, the page distinguishes a visible square with a code mismatch from a frame with no clean square candidate. It ignores decoded markers beyond each dictionary's error-correction limit so unrelated screen elements do not trigger false tracking, and rejects non-finite, degenerate, concave, or self-intersecting corner geometry. A locked marker ID is not replaced by a larger competing marker. A dark phone interface touching the black marker border can hide that border from the detector. The generated PNG includes a wide white margin to separate it from the surrounding screen.

## What the page measures

- Marker center `x` and `y` in pixels of the processed camera image, origin at top left, +X right and +Y down. The center is the intersection of the two detected corner diagonals, which avoids the corner-average perspective bias on oblique views.
- Rotation of the marker's top edge in screen degrees, clockwise positive because image Y points down.
- Approximate center speed in pixels per second and a recent 2D path.
- Relative Z change **only after** the stable marker starting position is captured. The estimate is `100 × (starting marker size ÷ current marker size − 1)` percent of the starting distance. Purple-scalpel-only tracking does not provide Z.
- Detection loss, shown visibly. The page briefly holds the last path point (up to 450 ms), then clears the readouts and resumes after reacquisition. Short marker gaps may be connected by display-only path interpolation; no new measured pose is inferred from those points.

Processing is limited to 480 pixels wide and at most about 30 new video frames per second to keep the browser responsive. Fast motion can still blur a marker or exceed the camera's own frame rate; a lost marker stops producing new pose observations. The relative Z estimate assumes the marker keeps the same orientation toward the camera; tilt, oblique views, and lens distortion change the apparent size and therefore bias the result.

When a detection is published, the page maps image X/Y into bounded workspace fields and combines the screen angle with a fixed demo orientation before sending a `positionMm` and quaternion payload to the controller. Those fields are an image-coordinate approximation. This app performs no camera-intrinsic calibration, camera-to-workspace registration, marker-to-tip offset correction, calibrated all-side 3D pose estimation, force/contact sensing, or anatomy registration. The controller and API may use the payload for the software demo, but native SOFA authority does not make the browser estimate calibrated. A controller-owned calibrated tracker or physical hardware path must supply that measurement for a calibrated pose workflow. The app does not record or transmit video frames; detection runs locally in the browser.

## Integrated path

The browser sends optical observations to the controller. Unity remains the
session client and presentation path, and the controller merges optical pose
with hardware contact/pressure when available:

```text
Camera + ArUco / purple segmentation
          ↓
tracking-web → WS /v1/tracking/stream → Scalpel controller
                                              ↑
UnityManualDemoClient → session samples ──────┘
                                              ↓
                                      API → memory simulator or SOFA
                                              ↓
                                      controller → Unity/XR snapshots
```

After optical tracking has been used in a session, stale camera input pauses
sample forwarding and the controller reports a recoverable error. Fresh optical
input resumes the stream. A session that has only used keyboard input continues
to work without a camera.

1. For a calibrated production path, move camera acquisition and detection into the **Scalpel controller** or connect a calibrated hardware tracker there. The browser detector remains a replaceable proof of concept, not a calibrated client-to-camera boundary.
2. Calibrate camera intrinsics and distortion, physical marker size, the fixed marker-to-tip transform, and camera-to-training-surface transform. Use fixed workspace markers or a calibrated board so tool pose and anatomy share one coordinate frame. Validate error and freshness before sending a pose.
3. Extend or map a versioned controller observation to `contracts/v1/tool-sample.schema.json`, retaining device ID, sequence, source timestamp, receive time, calibration ID, quality flags, and units. Fuse the camera pose with the embedded contact/pressure path in the controller/API according to the accepted boundaries. A missing or stale marker must degrade tracking rather than reuse an old pose.
4. The API sends normalized tool actions to SOFA and returns simulation ticks/snapshots through the controller. The XR client anchors anatomy to the calibrated surface and reconciles its rendering to SOFA's authoritative state. Only a calibrated pose and workspace transform can support an honest anatomy overlay.

The OAK-D S2 remains the intended hardware direction in the project brief. A regular browser camera is enough for this motion study; camera selection and depth fusion remain open integration decisions.

## Checks

```bash
npm test
npm run build
```
