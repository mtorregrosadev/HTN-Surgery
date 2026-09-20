# AprilTag + FSR scalpel input

## One existing 36h11 tag: 6-DoF stylus

`single_tag_stylus_bridge.py` tracks one existing AprilTag `36h11`, including
3D position and complete quaternion rotation. It automatically locks onto the
first visible tag, so its ID does not need to be known. No FSR is required:
physical tip depth drives the pose while SOFA remains responsible for contact,
reaction, deformation, and cutting.

1. Measure the tag's outer black-square width. If it is 50 mm, use `50` below.
2. Mount it flat on the back of a blunt training stylus, with the printed
   bottom edge pointing toward the tip. Measure tag-centre to tip distance.
3. Leave Play Mode and run **Surge Prep > Build Chest-Tube Showcase**.
4. Select `RegistrationAnchor_SimulationPatch`, find `Tag Fsr Input`, and set
   `Tag To Tip Metres`. A 140 mm centre-to-tip distance is `X 0, Y -0.14, Z 0`.
5. Start the stack, then open a second terminal:

   ```bash
   .venv-sofa/bin/python -m pip install opencv-python
   .venv-sofa/bin/python hardware/single_tag_stylus_bridge.py --tag-size-mm 50
   ```

   The camera window must outline the tag in green and report `6-DoF`.
6. Enter Play Mode. Put the physical tip at the chosen centre of the training
   surface, hold the desired starting angle, click the Unity Game view, and
   press **Space** once. The HUD changes to `LIVE — one 36h11 tag, 6-DoF stylus`.
7. Cover the tag or stop the bridge to test fallback. Click the Game view and
   use `W/A/S/D`, `Q/E`, and `1/2/3`. Losing the tag never removes keyboard
   controls.

If the wrong camera opens, add `--camera 1`. If physical motion is scaled
incorrectly, verify `--tag-size-mm`; optionally tune webcam scale with
`--fov-deg`. For calibrated lens intrinsics, run `camera_calibration.py` and
pass its file using `--camera-calib hardware/camera_calib.npz`.

This is a one-camera prototype, not a precision measurement claim. Motion
blur, glare, shallow viewing angles, lens distortion, and marker occlusion
introduce error. Keep the camera fixed and the complete tag large in frame.

The older multi-tag + FSR option remains available:

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
