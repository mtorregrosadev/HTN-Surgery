# ArUco tracking and physical workspace plan

Status: proposed implementation plan, 2026-09-19. This is not a claim that
calibrated hardware tracking or all-angle coverage is already implemented.
Use only a blunt training prop and a reusable synthetic surface.

## Current implementation and findings

- `tracking-web/src/tracking.js` detects ArUco marker corners and the purple
  tool body, producing image-pixel positions and a screen angle. Marker size
  provides relative Z as a size ratio, not measured depth: rotating a marker
  can look like moving it away. Purple-only tracking has no depth estimate.
  The demo has no camera intrinsics, distortion correction, physical size, or
  tip calibration.
- The browser camera demo sends image-derived poses to the Scalpel controller's
  tracking stream. The controller merges them into Unity's session samples and
  returns simulation snapshots to Unity; the browser does not connect to Unity
  or the API directly. This is an uncalibrated demo input, not a validated
  physical tracking interface.
- `UnityManualDemoClient.CreateSession` submits an identity calibration and a
  synthetic `rmsErrorMm = 0.1`. `NextSample` sends keyboard-controlled millimetres
  and a fixed incision-hold quaternion through the controller's `hardware-stream`.
  The controller replaces that pose when browser optical tracking is active.
  These are demo assumptions, not measurements or physical calibration validation.
- `controller/src/scalpel_controller/app.py` forwards samples to the API and
  broadcasts returned snapshots. `ScalpelStreamClient` receives its
  `client-stream`; `SimulationSceneRenderer.SetTarget` renders the returned tool
  and deformable meshes. The showcase uses the manual client's returned stream.
- `CoordinateFrame` converts API positions to Unity as `(x, y, -z) * 0.001` and
  quaternions as `(-qx, -qy, qz, qw)`. The renderer interpolates toward the latest
  target and snaps above 50 mm divergence; it does not yet buffer by simulation
  time or reject stale/session-mismatched snapshots.
- The existing tool renderer assumes its origin is the working tip. Preserve
  the documented tool basis: +Y along the handle away from the tip, +X along
  the cutting edge, and +Z normal to the blade face.
- The API stores a calibration transform but does not apply it to incoming
  positions. Hardware observations need a defined frame and explicit API-owned
  normalization before they can replace the existing normalized demo samples.

## Tracking from different sides

A flat marker cannot be detected from its back or when edge-on/occluded. More
smoothing or a larger error-correction allowance cannot restore that missing
information. The target is measured coverage of the intended hand movements,
with visible loss whenever the tool is not observable.

Use a rigid, lightweight multi-face mount on the blunt tool, with distinct marker
IDs and measured corner coordinates in one tool frame. Keep white margins clear
of the grip. Reserve different IDs for the fixed workspace board. Do not simply
switch between marker centers: each face must resolve to the same tool origin
and tip. The number and placement of faces must be tested against the intended
grip; a second synchronized/calibrated camera is a later option if one camera
cannot cover required motions.

Calibrate the camera at the actual capture resolution, including distortion and
focus settings. Estimate the rigid tool pose from visible, identified corners
with calibrated PnP; refine corners and reject high reprojection error, tiny or
edge-on detections, impossible motion, and ambiguous planar poses. Use temporal
consistency only to choose between plausible observations, never to label an
unobserved prediction as a measurement. Retain raw observations alongside any
filtered presentation pose. Establish filter settings from measured jitter and
latency, not visual smoothness alone.

OpenCV supports a known multi-marker board and calibrated pose estimation using
[`Board.matchImagePoints` and `solvePnP`](https://docs.opencv.org/4.7.0/db/da9/tutorial_aruco_board_detection.html).
A [ChArUco board](https://docs.opencv.org/4.10.0/df/d4a/tutorial_charuco_detection.html)
is a candidate for the fixed calibration target. These are proposed replacements
for the browser's 2D estimation, not APIs already used in this repository.

## User procedure: choose the real area and align the virtual tool

1. **Prepare.** Fix the camera and reference board beside the synthetic surface.
   Select the saved camera/tool profiles. Show live visibility, camera health,
   and marker identity through the controller. No valid profile means no start.
2. **Locate the surface.** Observe the known board to establish a metric plane.
   Display a board-aligned grid and the workspace axes in the setup view.
   Use physical reference dimensions; four arbitrary image clicks alone do not
   recover general 3D position or height above a plane.
3. **Choose the active area.** Let the learner select ordered corners on the
   calibrated plane, or touch those corners using the calibrated blunt tip.
   For image selection, intersect undistorted camera rays with the known plane.
   Reject crossed, tiny, outside-board, or poorly observed regions. Show the
   measured width/depth in millimetres and an adjustable height limit. MVP scope
   is one planar region; do not pretend this registers a curved mannequin.
4. **Calibrate the tip.** Use a measured rigid tip offset or pivot calibration:
   hold the tip in a fixed jig while rotating the handle through varied poses.
   Also define the tool's local axes/blade orientation; a tip offset alone does
   not calibrate blade orientation. Store residuals and tool-mount identity.
5. **Align the exercise.** Place and rotate a virtual workspace root so the
   selected physical origin/axes correspond to the exercise frame. Default to
   one-to-one physical scale. If the region is too small, request a larger region
   instead of silently stretching it. Preview a ghost tip and boundary grid.
6. **Validate.** Touch independent check points near the center, corners, and
   known heights; rotate the tool with its tip held in the jig. Show measured
   positional residuals, tip drift across face transitions, coverage, and age.
   Start only after the configured exercise tolerances pass. Fit residuals alone
   are insufficient validation. An instructor must approve exercise tolerances.
7. **Practice.** Physical motion inside the area drives the normalized tip pose;
   SOFA advances and Unity renders returned state. Outside the area, show an
   explicit boundary warning and pause interaction. Do not clamp positions and
   disguise the physical/virtual mismatch. Allow setup adjustment between
   attempts; moving camera, board, tool mount, or area invalidates the calibration
   and requires a new version and validation before the next attempt.

## Frame and ownership contract

Keep the required path: hardware -> Scalpel controller -> API -> SOFA, with
simulation state returning API -> controller -> Unity/XR. MongoDB remains
API-only. The controller owns camera/device connections and calibration command
routing; the API owns the canonical frame conversion, validation, and storage.

Define `T_A_B` to map coordinates from frame B to frame A, using column vectors
and millimetres. With camera C, fixed board B, rigid tool M, and exercise E:

```text
T_B_M = inverse(T_C_B) * T_C_M
p_E_tip = T_E_B * T_B_M * p_M_tip
R_E_tip = R_E_B * R_B_M * R_M_tip
```

The camera convention must be recorded explicitly (for example OpenCV's +X
right, +Y down, +Z forward). Define a right-handed exercise basis from the board,
with +Y the surface normal and X/Z in the plane, and document the chosen axis
directions with physical arrows. Do not copy camera coordinates directly into
the exercise or infer handedness from ambiguous labels such as "away". Keep
Unity's existing reflection/unit conversion at presentation only and test it
with axis and rotation fixtures. Specify matrix serialization order separately
from these mathematical conventions in the versioned schema.

Before transport implementation, define versioned observation/calibration
contracts containing camera intrinsics/distortion and resolution, camera/board/
tool identities, known marker geometry and dictionary, tool-tip transform,
workspace polygon and height bounds, frame transforms, calibration version and
validity, validation residuals, source clock identity/time, receive time,
sequence, session identity, observed IDs, reprojection error, and quality/loss
reasons. Preserve raw force/contact timestamps for API alignment; missing force
must remain explicitly unmeasured. Store derived telemetry by default; raw
camera/depth recording remains a separate unresolved decision.

## Sequenced implementation and verification

1. **Browser correctness.** Fix marker switching, perspective-center bias, and
   invented dropout paths. Test rotations and projected geometry. This improves
   the diagnostic view but does not supply calibrated physical 3D pose.
2. **Contracts and calibration math.** Add the observation/calibration schemas
   and API normalization tests: transform composition/inverse, units, quaternion
   basis changes, tip invariance during rotation, region validation, expired or
   mismatched calibration, out-of-order samples, and clock alignment.
3. **Controller camera adapter.** Add calibrated board/tool detection and replay
   of synthetic corner observations. Validate multi-face transitions, distractor
   IDs, blur, occlusion, camera reconnect, frame age, and calibration changes.
   Do not send browser pixel coordinates as `positionMm`.
4. **Unity setup flow.** Add setup UI and a workspace-root component, with all
   commands through the controller. Add an explicit hardware/manual source mode
   so the manual demo cannot simultaneously drive the tool. Preserve the
   existing renderer and shared DTO generation/compatibility checks.
5. **Live failure handling.** Add an idle watchdog independent of new samples,
   transport health events, and API simulation pause semantics. Holding the last
   contact pose must not keep advancing an incision during tracking loss. Unity
   must visibly mark stale state, reject old ticks/wrong sessions, and require
   validated recovery. Keep prediction/interpolation separate from scored data.
6. **Physical acceptance run.** At center and edges of the selected area, test
   known translations/heights and full intended roll/pitch/yaw ranges, including
   face transitions and deliberate occlusion. Report error in mm/degrees,
   stationary jitter, valid-frame coverage, recovery time, and input-to-render
   latency/jitter. Repeat the actual grip on a synthetic surface. Then confirm a
   native SOFA response, stored attempt, replay, and matching deterministic
   metrics. Synthetic tests cannot establish real camera accuracy.

Before calling hardware integration complete, record approved numerical limits
for spatial/angular error, calibration age, dropout timeout, latency, and update
rates. These remain open until measured on the actual camera/headset; do not
reuse illustrative README or manual-demo values as acceptance thresholds.

## Coordination with ongoing main work

The initial merge uses local `main` at `4c5cc50`; remote fetch was blocked by
GitHub authentication. Merge commit `203de03` preserves main's renderer and
layered simulation plus this branch's validation safeguards. The tracking fixes
and this plan are separate follow-up work. Keep future tracking work in its own
adapter and setup components; coordinate changes to shared schemas/Unity input
with the main-branch owner. Fetch and merge newer main changes once access is
restored, then rerun both sides of affected contracts. No remote branch was
overwritten or pushed by this work.

## Verification limits for this review

The resolved merge passed all 18 backend/controller tests, including schema
compatibility and hover/contact transitions. These use the development
simulator. The native SOFA check could not locate an installation, and the
standard Unity Editor installation directory was absent. No physical camera,
marker mount, headset, or Unity Play Mode accuracy test was performed here.
The later tracking/failure-feedback changes have their own regression checks;
none substitutes for the physical acceptance run above.
