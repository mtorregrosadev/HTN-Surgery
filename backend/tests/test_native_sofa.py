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


def sample(sequence: int, y_mm: float, x_mm: float = 0.0) -> ToolSample:
    return ToolSample(
        session_id="native-test",
        tool_id="scalpel",
        device_id="test-device",
        calibration_id="test-calibration",
        sequence=sequence,
        timestamp_ms=sequence * 10,
        position_mm=Vector3(x=x_mm, y=y_mm, z=0.0),
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
        for sequence, y_mm in enumerate((5.0, 2.5, 1.8, 1.0, 0.0), start=1):
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
        for y_mm in (1.8, 1.0, 0.0, -1.0):
            carved = await simulator.step(sample(sequence, y_mm, -10.0))
            topology_changed = topology_changed or "topology-changed" in carved.events
            sequence += 1
        for x_mm in range(-8, 11, 2):
            carved = await simulator.step(sample(sequence, -1.0, float(x_mm)))
            topology_changed = topology_changed or "topology-changed" in carved.events
            sequence += 1
        assert topology_changed
        assert max(
            mesh.topology_revision for mesh in carved.deformable_meshes
        ) > before_revision
    finally:
        await simulator.end_session("native-test")
        await simulator.close()
