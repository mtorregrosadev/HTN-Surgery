from scalpel_controller.synthetic import ManualToolState


def test_manual_tool_controls_move_raise_and_reset():
    state = ManualToolState()

    for key in ("d", "d", "w", "e"):
        assert state.apply(key)

    assert state.x_mm == -4.0
    assert state.z_mm == 2.0
    assert state.y_mm == 11.0
    assert state.tool_id == "scalpel"

    assert state.apply("2")
    assert state.tool_id == "blunt-dissector"
    assert state.apply("r")
    assert (state.x_mm, state.y_mm, state.z_mm) == (0.0, 12.0, 0.0)
    assert not state.apply("x")
