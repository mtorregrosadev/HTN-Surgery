# Surge Prep Surgical Showcase — Implementation Handoff

This document is the complete specification for rebuilding the upright anatomy
viewer into a polished 90-second chest-tube training showcase. It is binding for
Cursor and teammates unless a newer recorded decision supersedes it.

This is a training prototype, not a medical device. Do not test on people, attach
prototype electronics to real clinical instruments, or present scores as clinical
accuracy.

## Summary

- Premium medical mannequin lying supine on an operating table.
- Modern, believable operating room viewable through a full 360-degree orbit.
- Overhead/oblique procedure camera focused on the lateral chest.
- Draped patient with only the procedural window exposed.
- Intact silicone skin initially; fat, muscle, ribs, and pleural layers appear
  only as the local opening progresses.
- Subtle clinical wound visuals with minimal blood.
- Native SOFA owns collision, deformation, reaction force, layer opening, and
  topology changes.
- Unity owns rendering, camera controls, input, guidance, and interpolation.
- MongoDB records telemetry, authoritative snapshots, events, metrics, and replay.
- Manual Unity controls replace the physical controller only until hardware
  calibration is connected.

## Locked Experience

### Scene and patient

- Rotate the anatomical subject into a genuinely supine position.
- Place the mannequin horizontally on a padded operating table at realistic
  working height.
- Use a neutral premium silicone-simulator appearance instead of attempting an
  uncanny photoreal human.
- Cover the body with blue surgical drapes and expose one rectangular
  lateral-chest window.
- Keep the external surface intact at session start.
- Place the chest-tube target at the mannequin’s lateral intercostal region, not
  on the center/front of the chest.
- Reuse the high-resolution BodyParts3D ribs, cartilage, intercostals, and
  relevant chest structures beneath the exterior; do not use those visual meshes
  as the FEM volume.

### Operating room

Build a complete modern OR around the table:

- Ceiling-mounted surgical lamps aimed at the procedure window.
- Operating table with mattress, base, rails, and controls.
- Instrument trolley containing the available training tools.
- Patient monitor, anesthesia cart, cabinets, stainless work surfaces, wall
  panels, outlets, and restrained environmental props.
- Physically coherent scale, shadows, reflections, and lighting.
- URP materials with silicone skin, woven drapes, brushed metal, rubber, plastic,
  bone, muscle, and wet wound surfaces.
- Reflection probes, soft contact shadows, ambient occlusion, color grading, and
  restrained bloom.
- Remove the oversized debug panels, primitive black room, exposed anatomy
  mannequin, and current OnGUI toolbar from the final showcase.

### Camera and controls

Default to a slightly oblique top-down surgeon view.

- Right mouse drag: unrestricted 360-degree horizontal orbit with safe vertical
  limits.
- Scroll: smooth zoom centered on the procedural window.
- Middle mouse drag: pan.
- `F`: procedure-window close-up.
- `O`: full-room view.
- `C`: restore surgeon view.
- Camera presets must animate rather than snap.
- Camera movement must never rotate or mirror the tool’s coordinate frame.
- Store all SOFA-to-Unity transforms in one coordinate conversion utility.

Manual tool controls while hardware is unavailable:

- `W`/`A`/`S`/`D`: move across the body in screen-relative directions.
- `Q`/`E`: raise/lower the instrument.
- `1`: scalpel.
- `2`: blunt dissector.
- `3`: chest tube.
- `Tab`: show/hide contextual guidance.
- `R`: reset the current attempt after confirmation.
- Remove `Space` as fake contact and `[`/`]` as fake force controls.
- Contact and force must result visibly from SOFA collision and tissue
  resistance.

## Four-commit implementation

### Commit 1 — Document the native SOFA showcase architecture

- Add this handoff document.
- Add an architecture decision recording native SOFA v26.06 on the host Mac,
  Python 3.12/SofaPython3, SofaCarving for bounded topology changes, 100 Hz SOFA
  stepping, 30 Hz network snapshots, Unity render interpolation, pose-only
  manual input now and calibrated hardware input later.
- Update the exercise definition to a draft, instructor-review-required
  chest-tube workflow:
  1. Approach and landmark alignment.
  2. Controlled skin incision.
  3. Blunt soft-tissue dissection.
  4. Controlled pleural-layer entry.
  5. Tube placement.
  6. Completion and scorecard.
- Preserve explicit training-only and no-real-patient safety language.
- Update versioned contracts before changing implementation.

### Commit 2 — Make native SOFA drive layered chest interaction

Replace the small flat-pad behavior with a localized simulation region
registered to the lateral chest.

- Install/use official SOFA v26.06.00 for macOS; its release package has been
  verified as ARM64 and includes SofaPython3 and SofaCarving.
- Do not commit the approximately 185 MB SOFA distribution.
- Add a setup/check script that validates Python 3.12, locates the
  user-installed SOFA directory, configures plugin/library/Python paths,
  confirms Sofa, SofaRuntime, and SofaCarving load, and runs a headless
  deformation-and-carving smoke test.
- Run MongoDB in Docker, but run the API and controller locally for the demo so
  the API can load native SOFA without emulation.
- Add a one-command launcher that starts MongoDB, the native API, and the
  controller in the background with readable logs. Unity must remain focused
  during interaction.
- Native SOFA must be the required showcase backend. If unavailable, display
  `SOFA OFFLINE`; never silently present the memory adapter as real physics.
- Keep the memory adapter only for automated tests and teammate development.

Build an approximately 80 × 80 mm simulation region around the target:

- Separate volumetric skin, subcutaneous tissue, intercostal muscle, and
  pleural layers.
- Use tetrahedral FEM meshes with fixed outer boundaries and finer cells along
  the allowed corridor.
- Register these meshes to the high-resolution visual anatomy.
- Add scalpel blade, dissector tip, and tube collision representations.
- Drive the SOFA rigid tool from normalized pose commands.
- Derive contact, penetration, reaction force, deformation, and topology from
  SOFA—not keyboard flags.
- Use SofaCarving/topology modifiers only inside the instructor-defined local
  corridor.
- Activate layers sequentially so skin opens before subcutaneous tissue and
  muscle.
- Never carve ribs, cartilage, the full body mesh, or arbitrary anatomy.
- Export the updated visible surface for each changed layer using stable object
  IDs and topology revisions.
- Generate events for first contact, excessive force, layer opened, outside
  corridor, stage completed, and session completed.
- Retain the last valid input briefly during packet jitter, then safely freeze
  the tool and mark the session degraded after timeout.

### Commit 3 — Rebuild the showcase as a modern operating room

Replace the current generated scene while keeping it rebuildable through the
Unity editor menu.

- Refactor the builder into clear room, mannequin, anatomy, procedure-window,
  tools, lighting, and UI sections.
- Import only required high-resolution anatomy and generate optimized Unity
  meshes/material assignments.
- Add appropriate normals, bounds, scale, colliders, LODs, and material
  separation.
- Prevent duplicate scene objects when rebuilding.
- Align the mannequin, simulation patch, target corridor, and instrument using
  named registration anchors.
- Correct scalpel orientation so its handle, blade, cutting edge, SOFA
  collision geometry, target line, and contact marker occupy the same
  coordinate frame.
- Display a small contact-point marker and instrument shadow/depth cue so
  contact is visually unambiguous.
- Interpolate incoming authoritative positions and mesh vertices; snap only
  after major divergence.
- Blend the local deformable patch into the silicone chest surface so it does
  not look like a floating rectangle.
- As tissue opens, reveal only the affected local layers and wound channel.
- Use subtle dark-red wound shading and a small controlled blood decal—no gore
  or uncontrolled particle effects.
- Keep underlying ribs visible only through the opened region or optional
  instructor cutaway mode.

### Commit 4 — Polish the guided procedure and demo workflow

Create a restrained contextual interface:

- Current stage and one short instruction.
- SOFA connection indicator.
- Contact/reaction-force indicator.
- Target alignment cue.
- Procedure progress.
- Warning toast for excess force, wrong angle, or outside-target contact.
- Guidance can be hidden with Tab.
- Detailed measurements stay off-screen until completion.

Implement the 90-second judge flow:

1. Launch scene in overhead OR view.
2. Briefly orbit to demonstrate the complete environment.
3. Focus on the draped procedural window.
4. Approach with the scalpel and visibly deform intact skin.
5. Follow the target corridor and produce a real SOFA topology change.
6. Switch to the blunt dissector and open the deeper soft-tissue tract.
7. Show ribs/intercostal anatomy locally through the opening.
8. Place the tube through the simulated tract.
9. Finish with a compact scorecard and replay trace.

The final score must be deterministic and calculated from stored
telemetry/SOFA state:

- Target-path offset.
- Instrument angle.
- Reaction-force control.
- Force consistency.
- Incision length and depth.
- Outside-corridor contacts.
- Layer violations.
- Completion time.
- Tube placement completion.

AI-generated coaching may explain these metrics but must not calculate or
invent them.

Push these four commits to main only after all checks pass.

## Contract and interface changes

Create contract version 1.1 while retaining parsing compatibility with stored
1.0 sessions.

Normalized tool input adds:

- `inputMode`: `pose-only` or `calibrated-hardware`.
- `forceMeasurementValid`.
- `toolId` values for the scalpel, blunt dissector, and tube.
- Existing session, device, calibration, sequence, timestamps, position,
  orientation, quality, and health fields remain available.
- For pose-only, SOFA derives contact and reaction force. Input `contact` /
  `forceN` cannot trigger cutting by themselves.
- For calibrated-hardware, measured force is preserved for comparison and
  safety metrics, while SOFA remains authoritative for world contact.

Simulation snapshots add:

- `simulationBackend`, required to equal `sofa-native` in showcase mode.
- `procedureStage`.
- `tool.contactPointMm`.
- `tool.contactNormal`.
- `tool.reactionForceN`.
- `tool.penetrationDepthMm`.
- `tissue.activeLayer`.
- Per-layer deformation/opening state.
- Existing simulation tick/time, session identity, deformable meshes, topology
  revisions, and events remain.

The route remains:

```text
Unity client <-> Scalpel controller <-> API <-> native SOFA
                                      |
                                      v
                                   MongoDB
```

Unity must not connect directly to SOFA, MongoDB, or eventual hardware.

## Verification and acceptance tests

### Native SOFA

- Startup fails clearly when SofaPython3 or SofaCarving is missing.
- Health reports `simulation: sofa-native`.
- A descending blade visibly deforms skin before topology changes.
- Contact and reaction force come from SOFA with manual input force set to zero.
- Valid blade travel changes topology and increments `topologyRevision`.
- Motion outside the corridor cannot carve tissue.
- Excessive depth cannot pass through protected bone geometry.
- Each tissue layer opens only after its preceding stage.
- Restart/replay produces traceable stored snapshots and metrics.

### Contracts and backend

- Validate all 1.1 samples and snapshots against JSON Schema.
- Reject malformed, stale-calibration, out-of-order, and unhealthy samples.
- Test coordinate conversion, quaternion normalization, stage transitions,
  metrics, MongoDB persistence, and replay.
- Verify controller tests prove that all client and manual input still passes
  through the controller.
- Verify API and Unity remain compatible with stored 1.0 replay records.

### Unity

- `W` moves visually upward, `S` downward, `A` left, and `D` right from the
  default surgeon camera.
- The blade tip and SOFA contact point remain aligned throughout orbit and zoom.
- The instrument visibly touches and indents the chest.
- No floating tissue patch, inverted tool, upright patient, clipping anatomy,
  duplicate objects, or mirrored input.
- Full-room, surgeon, and close-up views work at common Game-window aspect
  ratios.
- Scene maintains a stable interactive frame rate on the current Apple Silicon
  Mac.
- Stopping SOFA visibly freezes interaction and reports the failure instead of
  continuing canned animation.

### Final demo gate

The build is accepted only when a fresh teammate can:

1. Run the setup check.
2. Start the stack with one command.
3. Open the generated Unity showcase scene.
4. Complete the workflow without touching the terminal.
5. See real deformation and topology changes.
6. Finish the session and retrieve the same metrics through MongoDB/replay.
7. Confirm the scene still works without VR hardware and is ready for later
   OpenXR/controller mapping.

## Assumptions

- Target machine is the current Apple Silicon Mac with Unity 6.6.
- Premium mannequin, clinical-subtle wound visuals, and minimal contextual
  guidance are final choices.
- Physical controller calibration is intentionally deferred; no other part of
  the controller/API boundary is bypassed.
- The simulation is a polished training prototype, not clinically validated and
  not advertised with microscopic or medical-device accuracy.
- Arbitrary destructive full-body cutting is out of scope; the localized
  procedure region still uses real SOFA collision, FEM deformation, and
  topology modification.

## Tool frame

Instrument origin is the working tip. `+Y` is along the handle away from the
tip, `+X` is along the cutting edge, and `+Z` is the blade-face normal. The same
frame is used for Unity visuals, SOFA collision geometry, the target corridor,
and the contact marker. Camera orbit must not remap this frame.

## Coordinate conversion

The API/SOFA frame is right-handed millimetres: `+X` right, `+Y` up, `+Z` away
from the default learner. Unity is left-handed metres. All conversions live in
`CoordinateFrame` on the client. The simulation patch is registered to the
lateral-chest anchor; visual BodyParts3D meshes are never used as FEM volumes.
