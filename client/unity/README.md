# Unity XR integration

The `com.surgeprep.runtime` package renders authoritative simulation snapshots
received from the Scalpel controller. It has no MongoDB, SOFA, or hardware
dependency and can be added to an existing Unity/XREAL project as an embedded
package.

## Build the chest showcase

The fastest demo path is the package's one-click editor builder. With the local
package added to a Unity project:

1. Leave Play Mode, then choose `Surge Prep > Build Chest-Tube Showcase`.
2. Wait while Unity copies and imports the curated chest anatomy into the
   containing project. The source OBJ files remain unchanged in this repository.
3. The builder opens
   `Assets/SurgePrepShowcase/Scenes/ChestTubeShowcase.unity` and selects the
   `Surge Prep Simulation` object.
4. Start the Docker stack with `docker compose up --build -d`.
5. Enter Play Mode and click once inside the **Game** view. The showcase creates
   its own demo session; no Terminal stream or pasted session ID is required.

The scene presents a cropped high-resolution torso at an interactive surgical
workstation inside a dark training lab. Use the **CHEST** and **ROOM** buttons
for camera presets, right-drag to orbit, and scroll to zoom. The layer controls
toggle skin, muscle, and bone; keys `1`, `2`, and `3` do the same. Press `Tab`
to hide or restore the live guidance panel.

While the Game view is focused, use `W/A/S/D` or the arrow keys to move the
training tool, Space to make or release contact, `[` and `]` to change pressure,
and `R` to reset. Right-drag and scroll remain available for camera orbit and
zoom. Because input and rendering now live in the same Unity window, the
Terminal can remain hidden after Docker starts.

The builder writes generated Unity assets only into the containing Unity
project. Re-running it refreshes the scene without committing those generated
copies to this repository.

## Manual scene setup

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

## Develop without hardware

The generated showcase includes `UnityManualDemoClient`, an explicitly
synthetic input fallback. It creates a calibrated session and submits keyboard
samples through the Scalpel controller, API, and simulation adapter, then
renders the authoritative returned snapshots. It does not locally animate the
tool or bypass the service boundary.

Start the Docker stack:

```bash
docker compose up --build -d
```

Then enter Play Mode and keep the Game view focused. Unity completes the session
when Play Mode stops. The older command-line synthetic source remains available
for API-only development, but it should not run at the same time as the Unity
manual demo.

For physical hardware, disable `UnityManualDemoClient`, enable
`ScalpelStreamClient`, and set its active session ID. The physical demo replaces
only the synthetic input source with controller-routed OAK-D and ESP32 readings;
the authoritative API/simulation return path stays the same.

The default Compose stack uses the deterministic memory simulation adapter so
the whole team can run the presentation without a native SOFA install. It
exercises the real API, controller, MongoDB, Unity transport, mesh streaming,
metrics, and replay paths, but it is not a substitute for the native SOFA demo.
For native SOFA setup, follow `backend/README.md` and set the simulation backend
to `sofa` before presenting the physics as SOFA-driven.
