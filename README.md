# Surge Prep

Surge Prep is a physical-digital surgical-skills trainer for safe, repeatable practice outside a specialized simulation lab. A learner uses a blunt training tool on a reusable synthetic surface while the system tracks motion, orientation, contact, and pressure. The virtual scene follows the physical tool, gives live spatial guidance, and produces a replayable score with plain-language coaching.

This is a training prototype, not a medical device. It does not replace qualified instructors, supervised simulation, clinical observation, or clinical judgment. Never attach prototype electronics to a real clinical instrument or use the system on a person.

## Hackathon goal

Build one convincing end-to-end exercise:

1. Select an exercise.
2. Calibrate the physical workspace to the virtual scene.
3. Perform a guided interaction with a blunt training tool.
4. Detect contact and stream tool pose and force into the simulation.
5. Show live XR/VR feedback without obscuring the learner's real workspace.
6. Save the attempt, calculate objective metrics, and replay it.
7. Generate an AI-assisted explanation grounded in an instructor-approved rubric.

The demo should optimize for a complete, reliable loop rather than broad anatomical coverage or high-fidelity tissue cutting.

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
simulation adapter. Shared payload schemas live under `contracts/v1/`; embedded,
controller, and VR work should generate or validate DTOs against those contracts
instead of copying backend-internal models.

The runnable Scalpel relay under `controller/` separates hardware ingestion
from client subscriptions. The embedded Unity package under `client/unity/`
consumes those subscriptions, interpolates the authoritative tool pose and
deformable simulation surface, and is ready to host inside an OpenXR/XREAL
project. Its `Surge Prep > Build Chest-Tube Showcase` editor command creates a
computer- and XR-ready layered chest scene from the curated anatomy source set,
with a live target/force HUD and blunt-tool rehearsal flow.

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
