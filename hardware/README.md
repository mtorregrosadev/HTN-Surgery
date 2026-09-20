# AprilTag + FSR scalpel input

## One-tag 6-DoF stylus trial in Unity

For the quickest orientation test, the Unity client can use a single rigidly
mounted tag through Keijiro's `jp.keijiro.apriltag` package. This mode tracks
the stylus position and complete quaternion rotation from the webcam. It does
not need the Python bridge or an FSR: moving the physical tip down supplies the
depth, while SOFA remains responsible for collision, reaction force,
deformation, and cutting.

1. In Unity, select **Surge Prep > Install AprilTag Stylus Tracking** and wait
   for scripts to compile.
2. Leave Play Mode and select **Surge Prep > Build Chest-Tube Showcase** again.
3. Print `tagStandard41h12` ID `0` from the official
   [AprilTag image repository](https://github.com/AprilRobotics/apriltag-imgs/tree/master/tagStandard41h12).
   Scale it to a measured size, keep its white border, and mount it flat and
   rigidly on the back of a blunt training stylus.
4. Select `RegistrationAnchor_SimulationPatch` and configure its
   `April Tag Stylus Input` component:
   - `Tag Size Metres`: measured outer black-square edge length.
   - `Camera Field Of View Degrees`: the webcam field of view used for pose
     estimation. An incorrect value makes depth scale incorrectly.
   - `Tag To Tip Metres`: measured vector from the tag centre to the stylus
     tip in tag-local axes. The default assumes the tip is 140 mm down the
     tag's local Y axis; adjust it for the actual mount.
5. Start the showcase stack, enter Play Mode, and allow camera access.
6. Hold the physical tip at the centre of the highlighted procedure target,
   with the stylus at the angle the virtual tool should copy. Press **Space**
   once. Translation and rotation now stream through client -> Scalpel
   controller -> API -> SOFA. Cover the tag to verify that the HUD reports the
   loss and keyboard fallback resumes safely.

This is a one-camera prototype, not a precision measurement claim. A correctly
measured tag and fixed camera can look close to one-to-one, but motion blur,
glare, shallow viewing angles, lens distortion, and marker occlusion introduce
jitter and pose error. Keep the tag large in frame and the camera fixed. The
package only accepts `tagStandard41h12`; the older three-tag bridge below uses
`36h11`, so those printed markers are not interchangeable.

The Keijiro package is pinned to `1.0.3`. The integration is optional: without
it, the Surge Prep Unity package still compiles and retains WASD plus the
existing tag/FSR path.

Drives the Unity scalpel from real hardware:

- **AprilTags 1, 2, 3** on the scalpel handle, seen by a webcam, set the scalpel's position over the skin (x/z).
- **FSR sensor** on an ESP32-C3 Mini sets how deep the cut is: no pressure hovers just above the skin, and harder pressure lowers the blade through skin, fat and muscle.

```text
webcam + AprilTags ─┐
                    ├─ hardware/tag_fsr_bridge.py ──UDP :5005──> TagFsrInput.cs
ESP32-C3 + FSR ─────┘                                                 │
                                        UnityManualDemoClient (calibrated-hardware sample)
                                                                       │
                                        controller -> API -> SOFA (contact + carving)
```

SOFA remains authoritative: Unity only sends a pose (`y` below the skin surface = penetration depth) plus the
measured `forceN`. WASD stays as the fallback whenever the bridge is not sending.

## Accurate tracking (calibrate once)

The bridge does not just average the tag centres. `tracking.py` fits the three tags as **one rigid tool**
(all 12 tag corners, least squares), so position and angle stay right when a tag is hidden or partly out of frame,
follows the **cutting tip** rather than the handle, corrects **perspective** with a table calibration, and smooths
with a **One Euro filter** (steady when still, no lag when moving fast).

Calibrate once in the bridge's camera window (saved to `hardware/tracking_config.json`):

1. **`k`** then click the four corners of the practice area: top-left, top-right, bottom-right, bottom-left.
   Set the real size with `--table-mm 300x220` (width x height).
2. **`l`** with the scalpel held still and all three tags visible: learns how the tags sit on the handle.
3. **`t`** with the scalpel **tip touching the centre of the practice area**: teaches the bridge where the tip is.

Recalibrate with `k` if the camera or table moves (it clears the layout and tip, so repeat `l` and `t`).
Optional lens correction: `python hardware/camera_calibration.py`, then run the bridge with
`--camera-calib hardware/camera_calib.npz`.

Check the maths without any hardware: `python hardware/test_tracking.py` renders a tool at random poses and
compares a plain centroid with the rigid-body tracker. On synthetic frames the tracker stayed within about
0.3 to 1.6 px (95th percentile up to 3.5 px with two tags hidden), while a plain centroid drifted by tens of pixels
as soon as a tag was hidden. Real cameras add noise and lens error, so expect worse than that.

Tuning: `--min-cutoff` (lower = steadier when still) and `--beta` (higher = less lag when moving).

## Run

1. Flash `esp32c3_fsr/esp32c3_fsr.ino` (Arduino IDE, board "ESP32C3 Dev Module", **USB CDC On Boot: Enabled**).
   Wire 3V3 - FSR - GPIO3 - 10k - GND.
2. Start the showcase as usual (`scripts/start-showcase.sh`) and press Play in Unity. Rebuild the scene once
   (`Surge Prep -> Build Chest-Tube Showcase`) so the `TagFsrInput` component is added.
3. Start the bridge:

   ```bash
   pip install opencv-python numpy pyserial
   python hardware/tag_fsr_bridge.py --port COM3        # your ESP32's port
   python hardware/tag_fsr_bridge.py --simulate         # no hardware: mouse + hold left button
   ```

   Keys: `z` sets the scalpel's current position as the origin, `c` re-zeroes the FSR, `q` quits.

## Tuning (TagFsrInput inspector)

| Setting | Default | Meaning |
| --- | --- | --- |
| `xRangeMm` / `zRangeMm` | 30 / 22 | Half-size of the field the tag movement covers (matches the carvable field) |
| `invertX` / `invertZ` | off | Flip an axis if the scalpel moves the wrong way |
| `hoverMm` | 6 | Height above skin with no pressure |
| `maxDepthMm` | 32 | Depth at full pressure (skin to 3, fat to 15, muscle to 25, pleura to 32) |
| `deadband` | 0.08 | FSR noise below this is ignored |

Bridge options: `--span` (fraction of the camera frame that covers the full field), `--fsr-max` (raw ADC value at
your hardest press), `--family` (`36h11` default).

New to the rig? Follow the guided practice in [`docs/CHEST_TUBE_PRACTICE_TUTORIAL.md`](../docs/CHEST_TUBE_PRACTICE_TUTORIAL.md).
