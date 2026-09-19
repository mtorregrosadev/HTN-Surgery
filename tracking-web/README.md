# ArUco motion tracking experiment

This is a standalone browser experiment for tracking a **blunt training tool** with an attached ArUco marker. It is deliberately separate from the Surge Prep controller, API, SOFA scene, and XR client. It provides a visible first step toward AR without claiming to know the tool tip's 3D position.

## Run

```bash
cd tracking-web
npm ci
npm run dev
```

Open `http://127.0.0.1:5173/`, download marker **#0**, print it without cropping its white margin, and attach it rigidly to a blunt tool. Start the camera and keep the entire marker in view. Camera access requires the browser's permission and a secure context; localhost works for local development. Do not use the setup on people or with a clinical instrument.

If the browser reports **No camera found**, connect a webcam, open the page on a device with a camera, or choose **Open video file** to analyze a local recording. **Try synthetic demo** generates a moving marker in the browser so the tracker can be checked without hardware. Neither source is uploaded.

The page uses the `ARUCO_MIP_36h12` dictionary from `js-aruco2`. The download button generates the exact marker the detector expects. Other dictionaries, including OpenCV's common `DICT_4X4_50`, are **not** interchangeable with this marker.

## What the page measures

- Marker center `x` and `y` in pixels of the processed camera image, origin at top left, +X right and +Y down.
- Rotation of the marker's top edge in screen degrees, clockwise positive because image Y points down.
- Approximate center speed in pixels per second and a recent 2D path.
- Approximate Z distance in millimetres **only after** entering a measured camera-to-marker reference distance and clicking **Set reference** while the marker is visible. The estimate is `reference distance × reference marker size in pixels ÷ current marker size in pixels`.
- Detection loss, shown visibly; stale positions and speed are cleared.

Processing is limited to 640 pixels wide to keep the browser responsive. The Z estimate assumes the marker keeps the same orientation toward the camera; tilt, lens distortion, and measurement error change the result. It is **not** calibrated 3D pose, and X/Y remain image pixels. This experiment performs no camera-intrinsic calibration, tip-offset correction, force/contact sensing, or anatomy registration. It does not record or transmit video frames. The detector runs locally in the browser.

## Integration path

Keep the tracking and presentation modules separate when joining this work to the main system:

```text
Camera + ArUco + calibrated tip offset
          ↓
Scalpel controller → versioned tool-pose observation → API → SOFA
          ↑                                         ↓
Web/XR client ← controller ← authoritative simulation state
```

1. Move camera acquisition and ArUco detection into the **Scalpel controller** for the integrated system. The current browser detector is a replaceable proof of concept, not a new production client-to-camera boundary.
2. Calibrate camera intrinsics and distortion, physical marker size, the fixed marker-to-tip transform, and camera-to-training-surface transform. Use fixed workspace markers or a calibrated board so tool pose and anatomy share one coordinate frame. Validate error and freshness before sending a pose.
3. Extend or map a versioned controller observation to `contracts/v1/tool-sample.schema.json`, retaining device ID, sequence, source timestamp, receive time, calibration ID, quality flags, and units. Fuse the camera pose with the embedded contact/pressure path in the controller/API according to the accepted boundaries. A missing or stale marker must degrade tracking rather than reuse an old pose.
4. The API sends normalized tool actions to SOFA and returns simulation ticks/snapshots through the controller. The XR client anchors anatomy to the calibrated surface and reconciles its rendering to SOFA's authoritative state. Only then can an anatomy overlay honestly align with the real workspace.

The OAK-D S2 remains the intended hardware direction in the project brief. A regular browser camera is enough for this motion study; camera selection and depth fusion remain open integration decisions.

## Checks

```bash
npm test
npm run build
```
