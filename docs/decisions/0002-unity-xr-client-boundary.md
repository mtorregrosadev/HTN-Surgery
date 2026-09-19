# ADR 0002: Unity XR client behind the Scalpel controller

## Status

Accepted as a hardware-ready boundary; headset-specific validation is pending.

## Decision

Use Unity for the immersive client and isolate headset SDK code from Surge
Prep's transport and simulation rendering. The shared runtime consumes versioned
simulation snapshots only from the Scalpel controller. It converts API units
and coordinates, interpolates display frames, and continually reconciles tool
and deformable-mesh state to the authoritative SOFA snapshots.

The controller exposes separate client and hardware streams. Hardware telemetry
is forwarded to the API/SOFA loop, while returned snapshots are broadcast to
immersive clients. This preserves the required topology and allows synthetic
hardware and Unity Editor testing before devices arrive.

The containing Unity application will use the current XREAL SDK through Unity
XR Plugin Management when XREAL hardware is confirmed. As of this decision,
XREAL SDK 3.1 documents Unity 2021.3+ support and integration with Unity's XR
subsystems. No XREAL package is committed until the exact glasses, Beam Pro
firmware, target Android version, and tracking mode are available for testing.

## Consequences

- Unity never connects directly to the API, MongoDB, SOFA, or embedded device.
- SOFA snapshots include renderable deformable surface vertices and topology.
- The Unity runtime stays portable across Editor, OpenXR, and XREAL loaders.
- A synthetic controller stream can drive the entire visual path without unsafe
  physical testing.
- Native SOFA, Unity, and headset builds remain separate runtime dependencies;
  passing memory-simulator tests does not certify the native stack.
