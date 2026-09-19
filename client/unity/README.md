# Unity XR integration

The `com.surgeprep.runtime` package renders authoritative simulation snapshots
received from the Scalpel controller. It has no MongoDB, SOFA, or hardware
dependency and can be added to an existing Unity/XREAL project as an embedded
package.

## Scene setup

1. Use Unity 2021.3 or newer and enable the XR provider for the eventual headset.
2. Add an empty `SurgePrep Simulation` object.
3. Add `SimulationSceneRenderer` and `ScalpelStreamClient` to it.
4. Assign a transparent or tissue-like material to the renderer.
5. Set the controller URL to the computer running Scalpel, using its LAN address
   from a headset (for example `ws://192.168.1.20:8100`, not `localhost`).
6. Set the active session ID before connecting.

The client consumes `client-stream`; physical/synthetic tool telemetry enters
the controller's separate `hardware-stream`. The renderer converts API
millimetres to Unity metres, reflects the right-handed Z axis into Unity's
left-handed coordinates, interpolates tool transforms and mesh vertices, and
reconciles every frame to SOFA state.

## XREAL

Do not add an old NRSDK dependency to this package. XREAL SDK 3.x integrates
under Unity XR Plugin Management and supports Unity 2021.3+. Import the XREAL
SDK into the containing Unity application, configure its loader and XR Origin,
and keep these transport/rendering scripts unchanged. Hardware validation must
wait until the exact glasses, Beam Pro firmware, and tracking mode are known.
