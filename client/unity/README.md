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

The procedure window includes a workstation setup panel. Adjust width, depth,
and height in millimetres, press **Validate area**, and use the outlined
rectangle on the table as the physical workspace preview. Validation currently
checks only the minimum configured size; camera, board, and tool-tip calibration
remain the next setup step. `Tab` hides or shows the setup panel.

The generated workstation also starts a Unity camera preview automatically and
shows its permission/device status. Press `V` to hide or show the preview. This
is only the physical camera image; it does not yet detect ArUco markers or move
the tool. ArUco pose detection must be added to the Scalpel controller, then
the normalized pose will travel through the API/SOFA loop to Unity.

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

Rejected tracking samples are reported through the controller to both the
hardware sender and subscribed clients. The Unity clients latch the failure
instead of interpreting the error as a simulation snapshot. For the manual
showcase, leave and re-enter Play Mode to start a fresh session after a tracking
failure; `R` only resets the tool pose during a healthy attempt. A physical
tracker must revalidate its source/calibration before starting a new attempt.

This is a training prototype. Do not use it on people or with real clinical
instruments.
