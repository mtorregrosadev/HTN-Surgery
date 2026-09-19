from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from surge_prep.models import Quaternion, ToolSample, Vector3
from surge_prep.simulation import SofaSimulator


REPOSITORY = Path(__file__).resolve().parents[2]


def configure_native_sofa() -> None:
    checker_path = REPOSITORY / "scripts" / "check-native-sofa.py"
    spec = importlib.util.spec_from_file_location("check_native_sofa", checker_path)
    if spec is None or spec.loader is None:
        pytest.skip("native SOFA checker is unavailable")
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    try:
        root = checker.find_sofa_root()
    except SystemExit:
        pytest.skip("native SOFA is not installed")
    checker.configure_paths(root)


def sample(
    sequence: int,
    y_mm: float,
    x_mm: float = 0.0,
    tool_id: str = "scalpel",
    z_mm: float = 0.0,
) -> ToolSample:
    return ToolSample(
        session_id="native-test",
        tool_id=tool_id,
        device_id="test-device",
        calibration_id="test-calibration",
        sequence=sequence,
        timestamp_ms=sequence * 10,
        position_mm=Vector3(x=x_mm, y=y_mm, z=z_mm),
        orientation=Quaternion(qx=0.0, qy=0.0, qz=0.0, qw=1.0),
        force_n=0.0,
        contact=False,
    )


@pytest.mark.asyncio
async def test_native_sofa_owns_contact_force_deformation_and_topology() -> None:
    configure_native_sofa()
    simulator = SofaSimulator(str(REPOSITORY / "simulation" / "sofa_scene.py"))
    await simulator.start()
    await simulator.begin_session("native-test")
    try:
        snapshots = []
        for sequence, y_mm in enumerate((5.0, 2.5, 1.0, 0.0, -0.25), start=1):
            snapshots.append(await simulator.step(sample(sequence, y_mm)))
        contact = snapshots[-1]
        assert contact.simulation_backend == "sofa-native"
        assert contact.tool.contact
        assert contact.tool.reaction_force_n > 0.01
        assert contact.tissue.deformation_mm > 0.1
        assert any(mesh.object_id == "layer-skin" for mesh in contact.deformable_meshes)
        assert max(
            vertex.y
            for mesh in contact.deformable_meshes
            for vertex in mesh.vertices_mm
        ) != pytest.approx(0.0)

        before_revision = max(
            mesh.topology_revision for mesh in contact.deformable_meshes
        )
        carved = contact
        topology_changed = False
        sequence = 10
        for y_mm in (5.0, 2.5, 1.0, 0.0, -1.0, -2.0):
            carved = await simulator.step(sample(sequence, y_mm, -15.0))
            topology_changed = topology_changed or "topology-changed" in carved.events
            sequence += 1
        # Move the physical blade edge across the instructor target; SOFA,
        # rather than a progress counter, decides which tetrahedra are removed.
        for x_mm in range(-15, 16):
            carved = await simulator.step(sample(sequence, -2.0, float(x_mm)))
            topology_changed = topology_changed or "topology-changed" in carved.events
            sequence += 1
        assert topology_changed
        assert max(
            mesh.topology_revision for mesh in carved.deformable_meshes
        ) > before_revision
    finally:
        await simulator.end_session("native-test")
        await simulator.close()


@pytest.mark.asyncio
async def test_native_sofa_hard_stops_the_tool_at_protected_ribs() -> None:
    configure_native_sofa()
    simulator = SofaSimulator(str(REPOSITORY / "simulation" / "sofa_scene.py"))
    await simulator.start()
    await simulator.begin_session("native-test")
    try:
        snapshot = await simulator.step(
            sample(1, -16.0, 0.0, "scalpel", z_mm=18.0)
        )
        surface_y = simulator._scene_module.chest_surface_y_mm(0.0, 18.0)
        assert "protected-anatomy" in snapshot.events
        assert snapshot.tool.position_mm.y == pytest.approx(surface_y - 10.0)
        assert all(mesh.topology_revision == 1 for mesh in snapshot.deformable_meshes)
    finally:
        await simulator.end_session("native-test")
        await simulator.close()


@pytest.mark.asyncio
async def test_native_sofa_completes_layered_opening_from_physical_contact() -> None:
    configure_native_sofa()
    simulator = SofaSimulator(str(REPOSITORY / "simulation" / "sofa_scene.py"))
    await simulator.start()
    await simulator.begin_session("native-test")
    sequence = 1
    snapshot = None
    try:
        for y_mm in (5.0, 2.5, 1.0, 0.0, -1.0, -2.0):
            snapshot = await simulator.step(sample(sequence, y_mm, -15.0))
            sequence += 1
        for x_mm in range(-15, 16):
            snapshot = await simulator.step(sample(sequence, -2.0, float(x_mm)))
            sequence += 1
        assert snapshot is not None
        skin = next(
            layer for layer in snapshot.tissue.layers if layer.layer_id == "skin"
        )
        assert skin.opening_progress >= 0.4
        assert skin.opened
        assert snapshot.tissue.active_layer in ("subcutaneous", "none")

        for y_mm in (0.0, -1.0, -2.0, -3.0):
            snapshot = await simulator.step(
                sample(sequence, y_mm, 15.0, "blunt-dissector")
            )
            sequence += 1
        for x_mm in range(15, -16, -1):
            snapshot = await simulator.step(
                sample(sequence, -3.0, float(x_mm), "blunt-dissector")
            )
            sequence += 1
        subcutaneous = next(
            layer
            for layer in snapshot.tissue.layers
            if layer.layer_id == "subcutaneous"
        )
        assert subcutaneous.opened

        for y_mm in (-4.0, -5.0, -6.0, -7.0, -8.0):
            snapshot = await simulator.step(
                sample(sequence, y_mm, -15.0, "blunt-dissector")
            )
            sequence += 1
        for x_mm in range(-15, 16):
            snapshot = await simulator.step(
                sample(sequence, -8.0, float(x_mm), "blunt-dissector")
            )
            sequence += 1
        muscle = next(
            layer
            for layer in snapshot.tissue.layers
            if layer.layer_id == "intercostal-muscle"
        )
        assert muscle.opened

        for y_mm in (-9.0, -10.0, -11.0, -12.0, -13.0):
            snapshot = await simulator.step(
                sample(sequence, y_mm, 15.0, "scalpel")
            )
            sequence += 1
        for x_mm in range(15, -16, -1):
            snapshot = await simulator.step(
                sample(sequence, -13.0, float(x_mm), "scalpel")
            )
            sequence += 1
        pleura = next(
            layer for layer in snapshot.tissue.layers if layer.layer_id == "pleura"
        )
        if not pleura.opened:
            for x_mm in range(-18, 19):
                snapshot = await simulator.step(
                    sample(sequence, -15.0, float(x_mm), "scalpel")
                )
                sequence += 1
            pleura = next(
                layer
                for layer in snapshot.tissue.layers
                if layer.layer_id == "pleura"
            )
        assert pleura.opened

        for y_mm in (-9.0, -10.0, -11.0):
            snapshot = await simulator.step(
                sample(sequence, y_mm, -15.0, "chest-tube")
            )
            sequence += 1
            if snapshot.procedure_stage == "complete":
                break
        assert snapshot.procedure_stage == "complete"
        assert "session-completed" in snapshot.events
    finally:
        await simulator.end_session("native-test")
        await simulator.close()
