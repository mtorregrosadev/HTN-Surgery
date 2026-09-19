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
4. Start the stack and synthetic stream using the commands below.
5. Paste the printed session ID into **Scalpel Stream Client > Session Id** in
   the Inspector, then enter Play Mode.

The scene includes a dark surgical training lab, console, floor guides, layered
skin/ribs/cartilage/muscle/diaphragm, an illustrative target guide, the
authoritative simulation surface, a blunt virtual tool, and live force/target
guidance. It renders in the normal Unity Game view on a computer. Press `V`
while playing to preview side-by-side phone-VR eye views.

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

## Phone VR fallback

The phone is a display/client, not a replacement for the controller or API. For
a real phone viewer, add a supported Cardboard/XR provider to the containing
Unity application, enable its Android loader under **Project Settings → XR
Plug-in Management**, and build the showcase scene to Android. Set
`ScalpelStreamClient → Controller Url` to the Mac's LAN address, for example
`ws://192.168.1.20:8100`; `localhost` would point back to the phone. The phone
and Mac must be on the same network. The `PhoneVrRig` keeps the same scene and
transport; an XR loader owns head tracking and stereo rendering on-device.

Until an Android build is ready, `V` provides a side-by-side stereo preview in
the desktop Game view for a simple phone viewer/cardboard shell.

## Develop without hardware

Start the Docker stack, then run a continuous synthetic hardware source:

```bash
docker compose up --build -d
docker compose exec controller \
  python -m scalpel_controller.synthetic --controller-url http://localhost:8100
```

Copy the printed session ID into `ScalpelStreamClient`. Enter Play Mode and the
tool plus interactive tissue will move from live controller snapshots. Stop the
synthetic stream with Ctrl+C; it will complete the session and print metrics.

For a hands-on laptop demo, add `--manual` to that command and keep the Terminal
window focused while Unity remains visible. Use `W/A/S/D` to move over the
target, Space to make or release contact, `[` and `]` to change force, `R` to
reset, and `Q` to complete the attempt. This is explicitly a synthetic input
fallback; the physical demo replaces it with controller-routed OAK-D and ESP32
readings.

The default Compose stack uses the deterministic memory simulation adapter so
the whole team can run the presentation without a native SOFA install. It
exercises the real API, controller, MongoDB, Unity transport, mesh streaming,
metrics, and replay paths, but it is not a substitute for the native SOFA demo.
For native SOFA setup, follow `backend/README.md` and set the simulation backend
to `sofa` before presenting the physics as SOFA-driven.
