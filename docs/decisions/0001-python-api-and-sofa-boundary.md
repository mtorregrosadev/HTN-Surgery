# ADR 0001: Python API with replaceable SOFA and MongoDB adapters

## Status

Accepted for the hackathon MVP.

## Decision

Use one Python service for the public API, session lifecycle, normalization,
MongoDB persistence, and the bidirectional SOFA bridge. The public boundary is
versioned HTTP/WebSocket JSON under `/v1`. Persistence and simulation are
interfaces: production adapters use MongoDB and SOFA, while in-memory adapters
keep local development and contract tests independent of those runtimes.

The normalized coordinate frame is right-handed: +X right, +Y up, and +Z away
from the learner. Positions use millimetres, forces use newtons, device times use
milliseconds, and orientation is an `(x, y, z, w)` unit quaternion.

## Why

SOFA's Python bindings make a Python-owned simulation bridge the shortest path
to a working vertical slice. Keeping the contracts and adapters explicit lets a
Go gateway or separate simulator process be introduced later without changing
controller or client payloads.

## Consequences

- The Scalpel controller is the only intended live API consumer.
- The API remains the only component with MongoDB credentials or SOFA access.
- The in-memory simulator is a development fallback, not a substitute for the
  SOFA-authoritative demo configuration.
- Raw camera imagery is not persisted; only normalized telemetry and derived
  simulation state are stored.
