# ADR 0003: Predefined incision physics for the chest-tube exercise

## Status

Accepted for the hackathon prototype.

## Context

The chest-tube showcase needs visible, measurable tissue interaction before the
physical controller is available. General-purpose anatomical cutting would add
substantial topology, collision, validation, and performance risk. The detailed
anatomy OBJ surfaces are also unsuitable as the finite-element mesh.

## Decision

Use a localized simulation surface around the instructor-approved access region.
The simulation owns a 36 mm incision corridor divided into 3 mm topology cells.
Contact alone deforms the surface. A cell opens only when the tool moves through
the corridor while contact is engaged and force is inside the illustrative
0.3–1.2 N training band. Continued controlled travel deepens and extends the
incision up to a 6 mm prototype limit.

The authoritative snapshot carries incision progress, length, depth, interaction
mode, topology revision, the deforming surface, and a wound-channel mesh. Unity
only renders that returned state. The memory adapter implements the same state
machine for development. With the native backend selected, SOFA supplies the FEM
deformation and the bridge removes cut surface faces from the returned topology.

Keyboard input and tomorrow's physical controller both submit the same normalized
tool sample. Replacing keyboard input therefore does not replace incision logic.

## Consequences

- The demo has obvious deformation, pressure feedback, progressive opening, and
  deterministic incision metrics without arbitrary full-body mesh cutting.
- The force band and geometric dimensions are illustrative prototype values, not
  validated tissue properties or medical-device accuracy claims.
- A later validation pass must replace these values with an instructor-approved
  rubric and measured controller calibration.
- Native SOFA still requires a separate host installation with SofaPython3; the
  default Compose stack remains the deterministic development adapter.
