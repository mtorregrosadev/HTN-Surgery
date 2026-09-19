from surge_prep.layered_chest import (
    LayeredChestState,
    hits_protected_rib,
    in_carvable_field,
    in_patch,
)
from surge_prep.models import Quaternion, ToolSample, Vector3


def test_active_field_matches_the_elliptical_sofa_mesh() -> None:
    assert in_patch(0.0, 0.0)
    assert in_patch(39.0, 0.0)
    assert not in_patch(40.0, 36.0)
    assert not in_patch(0.0, 37.0)
    assert in_carvable_field(18.0, 6.0)
    assert not in_carvable_field(0.0, 30.0)


def test_ribs_only_block_deep_tool_motion_over_their_bands() -> None:
    assert hits_protected_rib(0.0, -19.0, 18.0)
    assert not hits_protected_rib(0.0, -17.0, 18.0)
    assert not hits_protected_rib(0.0, -19.0, 0.0)


def test_blade_contact_builds_a_visible_wound_trough() -> None:
    chest = LayeredChestState()
    sample = ToolSample(
        session_id="wound-test",
        tool_id="scalpel",
        device_id="test",
        calibration_id="test",
        sequence=1,
        timestamp_ms=10,
        position_mm=Vector3(x=0.0, y=-1.2, z=0.0),
        orientation=Quaternion(qx=0.0, qy=0.0, qz=0.0, qw=1.0),
        force_n=0.0,
        contact=False,
    )
    chest.track_blade_path(sample, 1.2, 0.0)
    mesh = chest.wound_mesh()
    assert mesh.object_id == "wound-channel"
    assert len(mesh.vertices_mm) >= 8
    assert len(mesh.triangle_indices) >= 12
    assert min(vertex.y for vertex in mesh.vertices_mm) < -0.8
