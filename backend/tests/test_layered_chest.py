from surge_prep.layered_chest import hits_protected_rib, in_patch


def test_active_field_matches_the_elliptical_sofa_mesh() -> None:
    assert in_patch(0.0, 0.0)
    assert in_patch(39.0, 0.0)
    assert not in_patch(40.0, 36.0)
    assert not in_patch(0.0, 37.0)


def test_ribs_only_block_deep_tool_motion_over_their_bands() -> None:
    assert hits_protected_rib(0.0, -11.0, 18.0)
    assert not hits_protected_rib(0.0, -9.0, 18.0)
    assert not hits_protected_rib(0.0, -11.0, 0.0)
