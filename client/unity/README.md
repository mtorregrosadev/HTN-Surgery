# Unity XR integration

The `com.surgeprep.runtime` package renders authoritative simulation snapshots
received from the Scalpel controller. It has no MongoDB, SOFA, or hardware
dependency and can be added to an existing Unity/XREAL project as an embedded
package.

## Build the chest showcase

1. Leave Play Mode, then choose `Surge Prep > Build Chest-Tube Showcase`.
2. Wait while Unity copies and imports the curated chest anatomy.
3. On the host Mac, run `scripts/check-native-sofa.py` then
   `scripts/start-showcase.sh`. MongoDB stays in Docker; the API loads native
   SOFA. If SOFA is missing, the HUD shows **SOFA OFFLINE**.
4. Enter Play Mode and click the Game view. No session ID paste is required.

The generated scene registers the supplied high-resolution BodyParts3D skin and
internal chest anatomy in a supine pose on an operating table. A fitted cloth
drape exposes the right anterolateral simulation patch. The default camera
starts in a room orbit, then settles on that window. Right-drag orbits 360°
horizontally, scroll zooms, middle mouse pans, `F` close-up, `O` room, `C`
surgeon view.

Pose-only tool control (hardware later):

- `W/A/S/D` screen-relative movement
- `Q/E` raise/lower
- `1` scalpel, `2` blunt dissector, `3` chest tube
- `Tab` hide guidance
- `R` twice to reset
- Contact and force come from SOFA, not Space or `[` `]`

The rendered patch is the mapped native SOFA boundary. Indentation, layer
surfaces, openings, and topology revisions therefore reconcile to the server
state; Unity only interpolates between received snapshots.

This is a training prototype. Do not use it on people or with real clinical
instruments.
