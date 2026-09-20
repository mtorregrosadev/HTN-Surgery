# Surge Prep

Surge Prep is a physical-digital surgical-skills trainer for safe, repeatable practice outside a specialized simulation lab. A learner uses a blunt training tool on a reusable synthetic surface while the system tracks motion, orientation, contact, and pressure. The virtual scene follows the physical tool, gives live spatial guidance, and produces a replayable score with plain-language coaching.

This is a training prototype, not a medical device. It does not replace qualified instructors, supervised simulation, clinical observation, or clinical judgment. Never attach prototype electronics to a real clinical instrument or use the system on a person.

## Start here: reproduce the showcase on another Mac

The repository contains the API, controller, SOFA scene, contracts, anatomy,
and a reusable Unity package. The generated Unity project is deliberately not
committed. Each developer creates a small Unity project and links the package
from this checkout, so package changes remain shared without committing
machine-specific Unity files.

The known-good development environment is:

| Dependency | Tested version | Why it is needed |
| --- | --- | --- |
| macOS on Apple Silicon | Current demo machine | Runs Unity, SOFA, and Xcode |
| Git | Current | Clones the repository and lets Unity resolve packages |
| Docker Desktop + Compose | Current | Runs MongoDB |
| Python | 3.12 | Runs the API/controller and matches the project SOFA environment |
| [SOFA](https://github.com/sofa-framework/sofa/releases/tag/v26.06.00) | 26.06.00 macOS | Authoritative contact, deformation, force, and carving |
| Unity Hub + Unity Editor | 6000.6.2f1, Apple Silicon | Renders the desktop/XR client |
| Unity template | Universal 3D | Known-good render pipeline for the generated scene |
| Xcode + Unity iOS Build Support | Optional | Only required for an iPhone build |

Later patch releases may work, but use these versions first when reproducing
the demo under time pressure.

### 1. Clone the repository

```bash
git clone https://github.com/mtorregrosadev/HTN-Surgery.git surgery-htn
cd surgery-htn
git switch main
```

Confirm that the curated anatomy exists. The scene builder expects these files
to remain inside the checkout:

```bash
test -f bodyparts3d_highres/FJ2810_BP22617_FMA7163_Skin.obj && echo "anatomy ready"
```

### 2. Create the shared Python environment

Install Python 3.12 first if it is unavailable. With Homebrew:

```bash
brew install python@3.12
```

Then create one environment for the native demo and install both services:

```bash
python3.12 -m venv .venv-sofa
.venv-sofa/bin/python -m pip install --upgrade pip
.venv-sofa/bin/python -m pip install numpy scipy
.venv-sofa/bin/python -m pip install -e './backend[dev]' -e './controller[dev]'
```

Do not commit `.venv-sofa`; it is intentionally ignored.

### 3. Install and validate native SOFA

Download the official macOS archive for SOFA 26.06.00, extract it, and keep it
at the default location below:

```text
~/SOFA/SOFA_v26.06.00_MacOS/
```

The distribution must include `SofaPython3` and `SofaCarving`. If SOFA lives
somewhere else, set its absolute path before running any project scripts:

```bash
export SURGE_PREP_SOFA_ROOT=/absolute/path/to/SOFA_v26.06.00_MacOS
```

Run the full native smoke test:

```bash
.venv-sofa/bin/python scripts/check-native-sofa.py
```

Success ends with a contact/deformation/carving message. Do not continue with
the showcase if this check fails: the in-memory simulator is useful for API
development but is not the physics shown in the pitch.

### 4. Create and link the Unity project

1. In Unity Hub, install Unity `6000.6.2f1` for Apple Silicon. Desktop preview
   needs the Mac build module; also select **iOS Build Support** if this machine
   will build for an iPhone.
2. Create a new **Universal 3D** project. It may live anywhere outside the
   repository; `~/SurgePrepXR` is a simple choice.
3. Open **Window > Package Management > Package Manager**.
4. Select **+ > Install package from disk**.
5. Choose this file from the cloned repository:

   ```text
   client/unity/Packages/com.surgeprep.runtime/package.json
   ```

6. Wait for Unity to finish compiling. The top menu should now contain
   **Surge Prep**.
7. Leave Play Mode and select **Surge Prep > Build Chest-Tube Showcase**.
8. Wait for the anatomy import to finish. Unity creates and opens:

   ```text
   Assets/SurgePrepShowcase/Scenes/ChestTubeShowcase.unity
   ```

The package must stay linked to the repository. Copying only `package.json`
will fail because the builder resolves `bodyparts3d_highres/` relative to the
linked package.

### 5. Start the native showcase stack

Open a terminal at the repository root and make sure Docker Desktop is running:

```bash
docker compose version
./scripts/start-showcase.sh
```

That single script:

1. starts MongoDB in Docker;
2. verifies native SOFA and SofaCarving;
3. starts the API at `http://127.0.0.1:8000`;
4. starts the Scalpel controller at `http://127.0.0.1:8100`; and
5. refuses to start if the API does not report `sofa-native`.

Verify the two service boundaries before opening the demo:

```bash
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8100/health
```

Both responses should be healthy and mention `sofa-native`. Logs are written
to `.logs/api.log` and `.logs/controller.log`.

### 6. Run the desktop demonstration

Return to Unity, open the generated `ChestTubeShowcase` scene, press **Play**,
and click once inside the **Game** view. The current keyboard client creates
its own calibration and session, so there is no session ID to paste.

| Input | Action |
| --- | --- |
| `W A S D` | Move the tool across the chest in screen space |
| `Q / E` | Raise or lower the tool |
| `1 / 2 / 3` | Scalpel / blunt dissector / chest tube |
| Mouse drag | Orbit around the room |
| Mouse wheel | Zoom |
| Middle-mouse drag | Pan |
| `F / C / O` | Procedure close-up / surgeon view / room view |
| `K` | Toggle the anatomy cutaway |
| `Tab` | Hide or show guidance |
| `V` | Desktop-only side-by-side phone-view preview |
| `R` twice | Reset the attempt |

Contact and force are calculated by SOFA. `Space` registers the optional
physical tracker; it is not a keyboard force control. Lower the selected tool
until the blade or tip reaches the tissue, then move along the highlighted
corridor.

### Optional: single-tag 6-DoF stylus

The `test` branch tracks one existing `36h11` marker through
`hardware/single_tag_stylus_bridge.py`. It auto-selects the first visible tag
and sends translation plus quaternion rotation through the normal
client/controller/API/SOFA loop; it never writes directly to SOFA or MongoDB.
Setup, mount measurement, and Space-to-register instructions are in
[`hardware/README.md`](hardware/README.md).

This mode derives contact from tracked tip depth and therefore does not provide
measured hand force. The existing AprilTag + ESP32 FSR mode remains available
when physical force telemetry is required.

To verify that live transport and physics are still working:

```bash
.venv-sofa/bin/python scripts/check-live-physics.py
```

To measure the native solver without MongoDB, HTTP, or Unity in the result:

```bash
.venv-sofa/bin/python scripts/benchmark-sofa-pipeline.py
```

The benchmark prints the tetrahedral element count, median and p95 solve plus
mesh-export time, authoritative snapshot rate, payload size, deformation,
reaction force, and topology changes. Record its output whenever changing mesh
density, collision, solver, or carving settings; visual smoothness alone is not
evidence that the physical model improved.

### Current physics fidelity boundary

Native mode uses SOFA for contact constraints, reaction force, deformation, and
tetrahedral topology removal. Unity no longer receives the old procedural
`wound-channel` mesh in native mode: a visible opening must be present in the
boundary topology exported by SOFA. The active field currently contains 2,856
vertices and 7,584 tetrahedra across four material layers and uses SOFA's fast
corotational tetrahedral force field. These are illustrative training material
parameters, not validated human-tissue properties.

This is not yet equivalent to InfinyTech3D's liver-resection showcase. That
showcase uses its dedicated native C++ SofaUnity integration, and its fine
incision/refinement path depends on a separate `MeshRefinement` plugin. The
official macOS SOFA 26.06 package includes InfinyToolkit but does not include
that dependency, and the linked upstream repository is not publicly available.
Do not claim sub-element incision accuracy from basic SofaCarving, which removes
whole intersected tetrahedra. Reaching the reference quality requires either a
licensed/supported refinement stack or a separately engineered, tested adaptive
remeshing implementation. The controller integration does not need to change
for either route.

### 7. Stop cleanly

Exit Unity Play Mode and run:

```bash
./scripts/stop-showcase.sh
docker compose down
```

The first command stops the host API and controller. The second stops MongoDB;
omit it when the team wants MongoDB to remain warm between demo runs.

### Optional: API-only development without native SOFA

Teammates working on contracts, persistence, or controller integration can run
the containerized memory adapter:

```bash
docker compose --profile memory-dev up --build
```

OpenAPI is available at `http://localhost:8000/docs`. This mode uses real
MongoDB but does **not** use native SOFA and must never be presented as the
physics demo.

### Optional: iPhone/Cardboard direction

The checked-in `PhoneVrRig` provides a desktop side-by-side preview when `V` is
pressed. It is not yet a packaged iOS VR build. For real iPhone head tracking
and lens distortion, install the official
[Google Cardboard XR Plugin for Unity](https://developers.google.com/cardboard/develop/unity/quickstart),
enable its iOS loader through XR Plug-in Management, build in landscape through
Xcode, and retain the same client -> controller -> API -> SOFA boundary.

An iPhone cannot use `ws://localhost:8100` to reach the Mac. A phone build must
use the Mac's LAN address, and the controller must be intentionally bound to a
LAN interface. Keep the desktop path as the reliable fallback until that
network and iOS signing path has been tested on the actual phone.

### Common setup problems

| Symptom | Fix |
| --- | --- |
| **Surge Prep** menu is missing | Confirm the local package appears in Package Manager and let compilation finish. Check Unity's Console for the first compiler error. |
| Builder says anatomy is missing | Reinstall the package from this checkout; do not copy the package into an unrelated directory. Confirm `bodyparts3d_highres/` exists. |
| `SofaPython3 did not import` | Use `.venv-sofa/bin/python`, Python 3.12, and the matching macOS SOFA archive. Set `SURGE_PREP_SOFA_ROOT` explicitly. |
| `SofaCarving plugin was not found` | Reinstall the full SOFA 26.06 distribution and rerun `check-native-sofa.py`. |
| MongoDB repeatedly prints connection messages | Normal connection logging is noisy. Check `docker compose ps`; do not follow `docker compose logs -f` during the pitch. |
| Unity shows **SOFA OFFLINE** | Stop Play Mode, run `./scripts/start-showcase.sh`, verify both health endpoints, and enter Play Mode again. |
| Unity scene looks stale after pulling changes | Leave Play Mode and rerun **Surge Prep > Build Chest-Tube Showcase**. |
| Port 8000, 8100, or 27017 is busy | Run `./scripts/stop-showcase.sh`, then inspect the port owner with `lsof -nP -iTCP:<port> -sTCP:LISTEN`. |
| Tool moves but the tissue does not respond | Verify the HUD says **SOFA NATIVE**, lower with `E`, and check `.logs/api.log` for a finite-solver or connection error. |

Run backend and controller tests after changing contracts or transport:

```bash
.venv-sofa/bin/python -m pytest backend/tests controller/tests
```

## Hackathon goal

Build one convincing end-to-end exercise:

1. Select an exercise.
2. Calibrate the physical workspace to the virtual scene.
3. Perform a guided interaction with a blunt training tool.
4. Detect contact and stream tool pose and force into the simulation.
5. Show live XR/VR feedback without obscuring the learner's real workspace.
6. Save the attempt, calculate objective metrics, and replay it.
7. Generate an AI-assisted explanation grounded in an instructor-approved rubric.

The demo should optimize for a complete, reliable loop. Layered tissue opening is bounded to one instructor-defined chest-tube corridor; it is not general-purpose anatomical cutting.

## Canonical architecture

The following topology is the project's primary design constraint. Implementations should preserve these boundaries and data directions even when individual technologies evolve.

<img width="930" height="340" alt="image" src="https://github.com/user-attachments/assets/4ed2a014-6c05-4ae8-8a1d-461ee421dbb3" />


### Non-negotiable boundaries

- **VR/XR is a full, live simulation experience.** The headset and client send tool/user actions into the system and continuously receive the updated 3D world, contact response, deformation, and guidance generated from SOFA state. It is not a static model viewer.
- **The client drives VR/XR presentation.** It owns immersive rendering, exercise UI, headset input/output, and interpolation of received simulation state. VR does not connect directly to MongoDB or embedded devices; its simulation connection follows client -> controller -> API -> SOFA and returns along the same path.
- **Every live client interaction crosses the Scalpel controller.** The client must not bypass it to communicate directly with hardware or the API.
- **The Scalpel controller is the coordination boundary.** It routes client intent, manages the live hardware connection, and forwards readings/events to the API. It does not own persistence or SOFA physics.
- **The embedded/hardware subsystem owns the physical calibration path.** It exchanges calibration and sensor data with the controller, preferably through a reliable wired connection. Calibration state must also be identifiable by the API so recorded samples can be interpreted correctly.
- **The Go/Python API owns sensor normalization, session tracking, scoring inputs, persistence orchestration, and the bidirectional SOFA connection.** Raw device formats stop at this boundary; downstream records use normalized contracts.
- **SOFA is the authoritative dynamic 3D simulation.** It owns the evolving physical state of the training environment: tool contact, collision response, forces, deformation, and other exercise physics. Neither the client nor embedded firmware reimplements these physics.
- **The SOFA loop is bidirectional.** The API sends normalized tool/contact state to SOFA and returns simulation snapshots/events to the client through the controller. A static `.glb` alone is not the experience.
- **MongoDB is the session store for this architecture.** The API is the only component that reads or writes it; clients, controllers, and embedded devices never access MongoDB directly.

These rules take precedence over the older project-design document. In particular, PostgreSQL and a browser-first React/Three.js architecture are not the current plan.

### Expected data flow

1. The client starts an exercise through the Scalpel controller.
2. The controller establishes the wired embedded/hardware link and coordinates calibration with the API.
3. The embedded sensors produce tool/contact readings; the controller forwards them with device, sequence, timestamp, and calibration context.
4. The Go/Python API validates and normalizes the readings, associates them with the active session, and sends interaction state to SOFA.
5. SOFA advances the dynamic 3D environment, including collisions, contact forces, deformation, and exercise-specific physical state.
6. Simulation snapshots/events and live guidance return through SOFA -> API -> controller -> client.
7. The client synchronizes and renders the evolving environment as a full VR/XR experience and returns headset/user actions through the same chain.
8. The API stores normalized telemetry, relevant simulation state/events, calibration versions, and derived session data in MongoDB.
9. The learner reviews a replay, score, and rubric-grounded explanation through the client.

An illustrative normalized sample (the exact contract is still to be finalized):

```json
{
  "sessionId": "demo-18",
  "toolId": "blunt-stylus-1",
  "sequence": 1842,
  "timestampMs": 29138,
  "positionMm": { "x": 124.3, "y": 76.8, "z": 4.2 },
  "orientation": { "qx": 0, "qy": 0, "qz": 0, "qw": 1 },
  "forceN": 0.7,
  "contact": true,
  "calibrationId": "calibration-7"
}
```

## Components

### Current backend implementation

The runnable Python service under `backend/` exposes the controller-facing
versioned REST and WebSocket API, owns session validation and deterministic
metrics, persists through a MongoDB adapter, and drives SOFA through an isolated
simulation adapter. Shared payload schemas live under `contracts/v1/` (stored
1.0 sessions) and `contracts/v1.1/` (showcase). Embedded, controller, and VR
work should generate or validate DTOs against those contracts instead of
copying backend-internal models. See `docs/SHOWCASE_IMPLEMENTATION_HANDOFF.md`.

The runnable Scalpel relay under `controller/` separates hardware ingestion
from client subscriptions. The embedded Unity package under `client/unity/`
consumes those subscriptions, interpolates the authoritative tool pose and
deformable simulation surface, and is ready to host inside an OpenXR/XREAL
project. Its `Surge Prep > Build Chest-Tube Showcase` editor command creates a
computer- and XR-ready layered chest scene from the curated anatomy source set,
with a live target/force HUD and blunt-tool rehearsal flow. Native SOFA derives
broad torso contact from a downsampled version of the same registered
BodyParts3D skin, while four stacked curved FEM layers provide a 32 mm
localized chest wall (skin, fat, intercostal muscle, pleura) with through-thickness
elements, rib hard-stops, and a visible wound trough driven by SOFA contact.
The surgical field is elliptical; Unity shows the high-resolution BodyParts3D
layers through a procedure window rather than hiding them. Registered
non-carvable rib bands stop unsafe deep motion. WASD remains a pose-only
fallback; calibrated hardware uses the same 1.1 tool-sample contract. The
material parameters and progression thresholds are
illustrative prototype values, not clinically validated tissue properties.
The memory adapter is for tests and teammates without SOFA and must be labelled
SOFA OFFLINE in the showcase.

For API-only development, the default in-memory simulator preserves the same
request/response shape. The demo must switch to the `sofa` backend so SOFA is
authoritative. See `backend/README.md` for setup and controller flow.

### Physical setup

- Blunt plastic training stylus or spatula
- Reusable synthetic/foam/cardboard training surface
- 3D-printed training prop and fixed calibration markers
- Luxonis OAK-D S2 depth camera for tool pose tracking
- ESP32 plus a load cell or force-sensitive resistor for contact and pressure
- Load-cell amplifier such as HX711 when a load cell is used
- USB/wired links and low-voltage power
- Emergency-disable control if the physical prototype supports one

### Controller / hardware bridge

- Sit between the client, embedded/hardware subsystem, and API for all live interactions.
- Own hardware connections, command routing, device health, and stream transport.
- Preserve timestamps, sequences, device identity, and calibration identity while forwarding readings.
- Coordinate calibration without becoming the persistence or simulation layer.
- Stop or visibly degrade the live interaction when hardware, calibration, or API connectivity is invalid.
- Never write MongoDB or call SOFA directly.

### Unity + XR/VR client

- Render the complete evolving 3D exercise: anatomy/training geometry, tool, collisions, deformation, target path, and live corrections.
- Integrate XREAL One through Beam Pro for the intended demo hardware.
- Keep the learner's hands and physical workspace visible.
- Communicate with the system through the Scalpel controller, not directly with the API or embedded hardware.
- Send headset/tool/user actions toward SOFA and consume time-stamped simulation snapshots/events on the return path.
- Interpolate or predict between simulation updates for comfortable rendering, but reconcile to authoritative SOFA state.
- Do not substitute canned animation or a static model for the simulation. Scope physical behavior to one polished exercise if needed, but make that exercise genuinely interactive.

### API, simulation, and storage

- A Go/Python API validates and normalizes sensor data, manages sessions and metrics, and orchestrates persistence.
- The API is the sole bidirectional bridge to SOFA, which creates and advances the dynamic 3D training environment.
- Define a real-time simulation contract for inputs (tool pose, contact, pressure, user actions) and outputs (object transforms, deformation/state updates, collisions, forces, and exercise events).
- Track simulation tick/time and session identity so the client can synchronize, interpolate, record, and replay the experience.
- The API is the sole owner of MongoDB access.
- MongoDB stores normalized samples for replay, calibration versions, session state, and derived metrics.
- Go vs. Python responsibilities can be refined, but they must remain behind this single API boundary.

### Scoring and coaching

Start with deterministic metrics:

- Path deviation from the intended trajectory
- Tool-angle deviation
- Pressure range, peaks, and consistency
- Time to completion and time in contact
- Missed/incorrect regions or order of steps

The AI coach explains these recorded measurements against an instructor-approved rubric. It must not invent observations, diagnose patients, or present itself as a clinical authority.

## MVP boundaries

In scope:

- One polished exercise and one prepared training region
- Calibration plus a quick pre-session validation
- Live tool tracking, pressure/contact detection, and XR feedback
- A dynamic SOFA scene whose state visibly responds to the learner's actions in VR/XR
- Session persistence, scoring, replay, and an AI-assisted explanation
- Safe blunt tools and reusable materials

Out of scope for the hackathon:

- Use on people or with real clinical instruments
- Clinical validation, certification, or claims of medical-device accuracy
- Replacing instructors or supervised training
- Many exercises or a general-purpose anatomy platform
- General-purpose anatomical cutting across arbitrary models; the one demo exercise must still have meaningful dynamic SOFA physics
- Autonomous assessment not grounded in a reviewed rubric

## Open decisions

The architecture above settles component topology and MongoDB usage. These lower-level details still need resolution:

- **Backend language split:** Go, Python, or both behind the API boundary; define which process owns normalization, SOFA integration, APIs, and metrics.
- **Client implementation:** exact engine/framework and VR/XR transport while retaining the client-to-controller boundary.
- **Simulation streaming:** SOFA tick rate, client snapshot rate, state-delta format, interpolation strategy, and latency budget.
- **Controller deployment:** which machine/device runs it and how it connects to the OAK-D, ESP32, API, and headset.
- **Wire protocols:** serial format from ESP32 and transport between controller, Unity, and API.
- **Calibration:** exact reference points, coordinate frames, acceptable error, and invalidation rules.
- **Exercise:** anatomy/skill, intended trajectory, scoring weights, and instructor-approved rubric.
- **Privacy:** whether recordings contain video/depth imagery or only derived tool telemetry, plus retention rules.

## Suggested repository layout

```text
firmware/       ESP32 sensor firmware
controller/     camera/sensor ingestion, calibration, normalized stream
backend/        API, sessions, metrics, persistence, AI-coach orchestration
simulation/     SOFA scenes, models, and integration code
client/         Unity/XREAL experience
dashboard/      optional browser replay/instructor UI
models/         prepared 3D assets and exercise metadata
contracts/      event/API schemas shared across components
docs/           architecture, calibration, safety, and demo runbook
```

The repository may begin with fewer directories. Add a component only when it has runnable code or a clear owner.

## Definition of done for the demo

- A new participant can complete calibration with visible success/failure feedback.
- Moving the physical blunt tool moves the virtual tool with tolerable latency and error.
- Hover and contact are distinguishable; pressure changes are reflected in the experience.
- The SOFA scene responds dynamically to interaction, and the resulting state is visible in VR/XR rather than being a canned or static visualization.
- A round trip from physical input to SOFA update to headset rendering remains stable enough for the intended exercise.
- One exercise can be completed from start to finish without manually editing data.
- The session can be replayed and its metrics can be traced back to recorded samples.
- Coaching statements cite measured metrics and rubric criteria.
- The system fails safely when a sensor disconnects or calibration becomes invalid.

## Source precedence

This README reconciles three planning artifacts. When they conflict, use this order until the team explicitly records a new decision:

1. The latest architecture sketch supplied with this repository brief; its topology and MongoDB choice are authoritative
2. `Ideas for Hack the North.pdf` (product vision and newer hardware direction)
3. `Project design.pdf` (useful implementation detail, but explicitly considered potentially stale)

The older document's articulated two-link encoder arm, PostgreSQL choice, and React/Three.js-first client are not the current default. They must not override the canonical architecture even if reused as fallback implementation ideas.
