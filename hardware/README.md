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
