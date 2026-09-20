# AprilTag + FSR scalpel input

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
| `deadband` | 0.02 | FSR noise below this is ignored |
| `touchPressure` | 0.03 | Pressure at which the tip reaches the skin (a light touch registers contact) |
| `pressurePoints` / `depthMm` | see below | Pressure to tip depth, one slice per layer |
| `swapAxes` | off | Tick if the cut corridor runs along your table's other axis |

`pressurePoints` = 0.03, 0.25, 0.45, 0.55, 0.75, 0.80, 1.00 and `depthMm` = 0, 2.8, 9.5, 15.3, 22, 25.3, 31.5:
skin 0 to 2.8 mm, fat to 9.5, muscle 15.3 to 22, pleura 25.3 to 31.5. The tip rests inside the layer being worked.

In the bridge window, press **m** while pressing as hard as you will ever press to set the full-press value.

Bridge options: `--span` (fraction of the camera frame that covers the full field), `--fsr-max` (raw ADC value at
your hardest press), `--family` (`36h11` default).

New to the rig? Follow the guided practice in [`docs/CHEST_TUBE_PRACTICE_TUTORIAL.md`](../docs/CHEST_TUBE_PRACTICE_TUTORIAL.md).
