# Surge Prep API

This service is the boundary used by the Scalpel controller. Client, VR, and
embedded code should consume the versioned JSON contracts in `../contracts/v1`
and must not connect directly to this service, MongoDB, or SOFA.

## Run the API with MongoDB

From the repository root:

```bash
docker compose up --build
```

OpenAPI documentation is then available at `http://localhost:8000/docs`.
The container defaults to the deterministic memory simulator so teammates can
integrate without a native SOFA installation; MongoDB remains real and stores
calibrations, sessions, normalized samples, and simulation snapshots.

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

The bundled scene uses a small hexahedral training pad for responsive physics.
It deliberately does not use the high-resolution anatomy surfaces as an FEM
mesh. Replace the pad with a procedure-specific volumetric mesh later while
keeping the API contracts unchanged.

## Controller flow

1. `POST /v1/calibrations`
2. `POST /v1/sessions`
3. Connect to `WS /v1/sessions/{sessionId}/stream`
4. Send one normalized tool sample and receive one authoritative simulation
   snapshot per message
5. `POST /v1/sessions/{sessionId}/complete`
6. `GET /v1/sessions/{sessionId}/replay`

REST `POST /v1/sessions/{sessionId}/samples` is also available for diagnostics.
