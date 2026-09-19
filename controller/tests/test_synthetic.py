from scalpel_controller.synthetic import ManualToolState


def test_manual_tool_controls_move_press_and_reset():
    state = ManualToolState()

    for key in ("d", "d", "w", " ", "]"):
        assert state.apply(key)

    assert state.x_mm == 4.0
    assert state.z_mm == 2.0
    assert state.force_n == 0.85

    assert state.apply("r")
    assert (state.x_mm, state.z_mm, state.force_n) == (0.0, 0.0, 0.0)
    assert not state.apply("q")
