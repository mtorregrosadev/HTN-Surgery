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

The generated scene registers every high-resolution BodyParts3D OBJ in
`bodyparts3d_highres/` on the operating table. The mannequin skin stays intact;
press `K` for an anatomy cutaway. SOFA tissue sits on the registered field.
SOFA remains authoritative for contact, deformation, force, and
incision progress. As soon as the blade makes sufficient SOFA contact, the API
returns a wound trough (lips, walls, bed) that Unity renders; this visual mesh
never calculates the canonical score. The chest wall is 32 mm thick and is not
hard-stopped at 16 mm. The default camera starts in a room orbit, then settles
on that window. Right-drag orbits 360°
horizontally, scroll zooms, middle mouse pans, `F` close-up, `O` room, `C`
surgeon view.

The scalpel visual uses the supplied Onshape/SolidWorks OBJ from
`Runtime/Models/Scalpel`; its measured blade tip is registered to the unchanged
SOFA collision proxy. Keyboard input holds the instrument at a 40° incision
angle so the blade meets the chest. The procedural scalpel is retained only as
a missing-asset fallback.

Pose-only keyboard fallback (calibrated hardware uses the same 1.1 pose
contract through the controller; disable this client and enable
`ScalpelStreamClient` when that stream is live):

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
