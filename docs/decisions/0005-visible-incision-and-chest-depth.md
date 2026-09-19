# ADR 0005: Visible incision and realistic chest-wall depth

## Status

Accepted for the chest-tube showcase.

## Decision

Unity display is the product acceptance criterion. SOFA remains authoritative
for contact, reaction, deformation, and topology, but the client must actually
render those results.

Recorded choices:

- Import every high-resolution BodyParts3D OBJ present in
  `bodyparts3d_highres/`. The procedure window is cut only in skin and
  pectoralis so intercostals, ribs, and cartilage are visible in the field.
- The FEM chest wall is 32 mm thick (skin 3 mm, fat 12 mm, muscle 10 mm,
  pleura 7 mm). Each layer keeps a stable one-element thickness; only the
  pleural floor is fully fixed. There is no 16 mm input stop. Keyboard
  fallback may travel to 80 mm; calibrated hardware uses the same pose
  contract with no extra client clamp.
- SofaCarving may puncture on first sufficient contact. The backend also
  records the blade path from SOFA contact and returns a wound-channel mesh
  with walls and a bed. Unity renders that mesh; it does not invent the cut.
- WASD/`UnityManualDemoClient` stays as the software fallback.
  `ScalpelStreamClient` is the receive path for calibrated hardware snapshots.

## Why

The previous 16 mm slab, top-surface-only mesh export, and hidden wound mesh
let backend tests pass while the scalpel appeared to hover over a dark hole
with no incision.

## Consequences

- Showcase rebuild (`Surge Prep → Build Chest-Tube Showcase`) is required so
  Unity loads the extra anatomy and stops hiding sub-skin layers.
- Native layered-opening tests use deeper tool trajectories.
- Hardware calibration can replace keyboard pose without changing SOFA or
  scoring; only the sample source changes.
