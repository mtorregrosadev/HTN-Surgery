# Surge Prep API

This service is the boundary used by the Scalpel controller. Client, VR, and
embedded code should consume the versioned JSON contracts in `../contracts/v1`
and must not connect directly to this service, MongoDB, or SOFA.

## Run the API with MongoDB

From the repository root:

```bash
docker compose --profile memory-dev up --build
```

OpenAPI documentation is then available at `http://localhost:8000/docs`.
The container defaults to the deterministic memory simulator so teammates can
integrate without a native SOFA installation; MongoDB remains real and stores
calibrations, sessions, normalized samples, and simulation snapshots. Do not
present that memory path as SOFA physics. The showcase uses host SOFA:

```bash
docker compose up -d mongodb
scripts/check-native-sofa.py
scripts/start-showcase.sh
```

## Run locally without infrastructure

```bash
cd backend
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
uvicorn surge_prep.app:app --reload
```

With no MongoDB URI, data is kept in memory. Run tests with `pytest`.

## Use SOFA

Run the API inside an environment containing SOFA and SofaPython3:

```bash
export SURGE_PREP_SIMULATION_BACKEND=sofa
export SURGE_PREP_SOFA_SCENE=../simulation/sofa_scene.py
uvicorn surge_prep.app:app
```

The showcase scene uses a localized ~80 × 80 mm chest-wall volume 32 mm thick.
Visual BodyParts3D meshes are never used as the FEM volume. Native SOFA v26.06 on the
host Mac is required for the demo; see `docs/SHOWCASE_IMPLEMENTATION_HANDOFF.md`.
The physical region is a mapped tetrahedral continuum with constraint contact,
solver-derived reaction force, and a dynamically updated collision boundary.
The collision pipeline follows SOFA's documented `MinProximityIntersection`
pattern. Because that pipeline uses discrete rather than continuous collision
detection, a surface-coupled proxy prevents tracked poses from tunnelling
through the tissue between updates. SofaCarving can puncture on first
sufficient blade contact; Unity renders the returned wound-channel mesh rather
than hiding it.

Verify both the native scene and the complete running transport:

```bash
.venv-sofa/bin/python scripts/check-native-sofa.py
scripts/start-showcase.sh
.venv-sofa/bin/python scripts/check-live-physics.py
```

## Controller flow

1. `POST /v1/calibrations`
2. `POST /v1/sessions`
3. Connect to `WS /v1/sessions/{sessionId}/stream`
4. Send one normalized tool sample and receive one authoritative simulation
   snapshot per message
5. `POST /v1/sessions/{sessionId}/complete`
6. `GET /v1/sessions/{sessionId}/replay`

REST `POST /v1/sessions/{sessionId}/samples` is also available for diagnostics.
Samples with an unhealthy source, zero tracking quality, a revoked calibration,
an old sequence, or a timestamp earlier than the last accepted sample are
rejected before simulation and storage. The WebSocket closes with code 1008 and
a reason for rejected samples (1007 for malformed payloads); the controller
should surface that reason and reconnect only after the source is valid. The
development simulator emits `contact-start` and `contact-end` when contact
changes, including after initial hover. It is only a contract-compatible
fallback, not an authoritative SOFA physics demo.


Snapshots include the authoritative tool pose plus deformable surface vertices
and triangle topology for immersive rendering. The controller broadcasts these
snapshots to Unity; clients must not open this API WebSocket directly.

The chest-tube scene uses a localized, predefined incision corridor. Tool contact
deforms the tetrahedral volume; controlled force plus travel removes native
tetrahedra and streams the mapped boundary back as skin, subcutaneous, muscle,
and pleural render surfaces. Incision length, depth, and completion are stored
with simulation snapshots and returned in completed-session metrics. Material
values are tuned for a visually credible synthetic training pad, not validated
human tissue or medical-device accuracy.

Completing a session returns deterministic force, contact-time, target-offset,
and force-consistency metrics plus an illustrative composite score. The draft
weights and force range are recorded in
`../models/exercises/chest-tube-access-demo.json`; they require qualified
instructor review and are not clinical thresholds.
