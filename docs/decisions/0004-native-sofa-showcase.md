# ADR 0004: Native SOFA v26.06 showcase backend

## Status

Accepted for the chest-tube surgical showcase.

## Decision

Run official SOFA **v26.06.00** natively on the host Apple Silicon Mac. The API
process loads SofaPython3 in-process and owns the bidirectional simulation
bridge. Showcase physics must not run inside Docker emulation.

Recorded runtime choices:

- Python **3.12** with SofaPython3 from the official macOS SOFA package.
- **SofaCarving** and dynamic topology on four independent curved tissue
  layers inside an anatomy-shaped 80 × 72 mm lateral-chest field. The visual
  field is not rendered as a patch or rectangle.
- Broad non-carvable torso contact is an invisible, simulation-friendly point
  shell downsampled from the registered BodyParts3D skin. Protected rib bands
  are separate SOFA collision geometry and hard-stop deeper tool motion.
- SOFA steps at **100 Hz** (`dt = 0.01 s`). The controller/Unity network path
  publishes snapshots at **30 Hz**. Unity interpolates for display and
  reconciles to the latest authoritative snapshot.
- Manual Unity input is **pose-only**. Contact, penetration, reaction force,
  deformation, and topology come from SOFA collision and tissue resistance.
  Calibrated hardware force arrives later as `inputMode: calibrated-hardware`
  for comparison and safety metrics; SOFA remains authoritative for world
  contact.

The memory adapter remains for automated tests and teammates without SOFA. The
showcase must report `SOFA OFFLINE` when the health payload is not
`sofa-native`. It must never present the memory adapter as real physics.

The SOFA distribution (~185 MB) is a local install and is not committed.

## Why

The upright viewer and flat-pad memory incision were enough to prove transport,
but the 90-second demo needs visible layered deformation and bounded topology
change. Native SOFA v26.06 on macOS already ships ARM64 binaries, SofaPython3,
and SofaCarving, which is the shortest path that preserves
client → controller → API → SOFA.

## Consequences

- MongoDB still runs in Docker; the API and controller run on the host for the
  demo so they can load native libraries.
- `SURGE_PREP_SIMULATION_BACKEND=sofa` is required for the showcase.
- Startup of the native backend fails clearly if SofaPython3 or SofaCarving
  cannot be imported.
- Contract 1.1 adds pose-only metadata and per-layer snapshot fields while
  remaining able to parse stored 1.0 sessions.
- Hardware calibration stays deferred; the Scalpel controller boundary is not
  bypassed.
- The high-resolution OBJ is visualization/registration source only. It is
  never used directly as the deformable FEM volume.
