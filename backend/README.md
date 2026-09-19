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

The showcase scene uses a localized ~80 × 80 mm layered chest region. Visual
BodyParts3D meshes are never used as the FEM volume. Native SOFA v26.06 on the
host Mac is required for the demo; see `docs/SHOWCASE_IMPLEMENTATION_HANDOFF.md`.

## Controller flow

1. `POST /v1/calibrations`
2. `POST /v1/sessions`
3. Connect to `WS /v1/sessions/{sessionId}/stream`
4. Send one normalized tool sample and receive one authoritative simulation
   snapshot per message
5. `POST /v1/sessions/{sessionId}/complete`
6. `GET /v1/sessions/{sessionId}/replay`

REST `POST /v1/sessions/{sessionId}/samples` is also available for diagnostics.

Snapshots include the authoritative tool pose plus deformable surface vertices
and triangle topology for immersive rendering. The controller broadcasts these
snapshots to Unity; clients must not open this API WebSocket directly.

The chest-tube scene uses a localized, predefined incision corridor. Tool contact
produces deformation; controlled force plus travel progressively changes the
returned surface topology and wound-channel mesh. Incision length, depth, and
completion are stored with simulation snapshots and returned in completed-session
metrics. This is a prototype interaction model, not validated tissue or
medical-device accuracy.

Completing a session returns deterministic force, contact-time, target-offset,
and force-consistency metrics plus an illustrative composite score. The draft
weights and force range are recorded in
`../models/exercises/chest-tube-access-demo.json`; they require qualified
instructor review and are not clinical thresholds.
