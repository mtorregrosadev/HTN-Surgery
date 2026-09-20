"""The visual incision: tapered, symmetric, smooth, retracting and never self-intersecting."""
from __future__ import annotations

import math

import pytest

from surge_prep.layered_chest import (
    CELL_WIDTH_MM,
    CORRIDOR_MIN_X_MM,
    LAYER_ORDER,
    LAYER_TOPS_MM,
    MAX_GAPE_MM,
    MESH_SUBDIVISIONS,
    LayeredChestState,
    cell_count,
)
from surge_prep.models import Quaternion, ToolSample, Vector3


def tool_sample(x=0.0, y=10.0, z=0.0) -> ToolSample:
    return ToolSample(
        session_id="s", tool_id="scalpel", device_id="d", calibration_id="c", sequence=0, timestamp_ms=0,
        position_mm=Vector3(x=x, y=y, z=z), orientation=Quaternion(qx=0, qy=0, qz=0, qw=1),
        force_n=0, contact=False,
    )


def chest_with(layer="skin", cells=range(2, 10), depth=2.0, deeper=()):
    chest = LayeredChestState()
    for name in [layer, *deeper]:
        for cell in cells:
            chest.layers[name].cut_cells.add(cell)
            chest.layers[name].depths_mm[cell] = depth
    return chest


def mesh_of(chest, layer="skin"):
    return chest._layer_mesh(layer, tool_sample(), 0.0, False)


COLUMNS = cell_count() * MESH_SUBDIVISIONS + 1
ROWS = 10


def grid(mesh):
    """vertices as [row][column]"""
    v = mesh.vertices_mm
    return [[v[r * COLUMNS + c] for c in range(COLUMNS)] for r in range(ROWS)]


# ---------------------------------------------------------------- structure


def test_uncut_mesh_is_flat_and_closed():
    chest = LayeredChestState()
    mesh = mesh_of(chest)
    assert mesh.topology_revision == 1
    assert len(mesh.vertices_mm) == ROWS * COLUMNS
    g = grid(mesh)
    assert all(abs(vertex.y - LAYER_TOPS_MM["skin"]) < 1e-9 for row in g for vertex in row)
    # no slit is cut into intact skin: every quad in the seam band is present
    assert len(mesh.triangle_indices) == (ROWS - 1) * (COLUMNS - 1) * 6


@pytest.mark.parametrize("layer", LAYER_ORDER)
def test_every_layer_mesh_is_valid(layer):
    mesh = mesh_of(chest_with(layer), layer)
    assert mesh.object_id == f"layer-{layer}"
    assert len(mesh.triangle_indices) % 3 == 0
    assert max(mesh.triangle_indices) < len(mesh.vertices_mm)
    assert all(math.isfinite(c) for v in mesh.vertices_mm for c in (v.x, v.y, v.z))


def test_topology_revision_grows_with_cuts():
    assert mesh_of(chest_with(cells=range(0, 4))).topology_revision == 5
    assert mesh_of(chest_with(cells=range(0, 8))).topology_revision == 9


def test_cut_removes_the_quads_across_the_seam():
    intact = mesh_of(LayeredChestState())
    cut = mesh_of(chest_with())
    assert len(cut.triangle_indices) < len(intact.triangle_indices)


# ---------------------------------------------------------------- the opening


def test_edges_part_symmetrically():
    g = grid(mesh_of(chest_with()))
    for column in range(COLUMNS):
        assert g[4][column].z == pytest.approx(-g[5][column].z)


def test_opening_is_widest_in_the_middle_and_pointed_at_the_ends():
    g = grid(mesh_of(chest_with(cells=range(2, 10), depth=2.5)))
    widths = [g[5][c].z - g[4][c].z for c in range(COLUMNS)]
    peak = max(widths)
    assert widths.index(peak) in range(COLUMNS // 4, 3 * COLUMNS // 4)
    first = next(c for c, w in enumerate(widths) if w > 0.31)
    last = max(c for c, w in enumerate(widths) if w > 0.31)
    assert widths[first] < 0.6 * peak and widths[last] < 0.6 * peak       # tapers toward both ends
    assert widths[0] == pytest.approx(0.3) and widths[-1] == pytest.approx(0.3)   # untouched skin stays closed


def test_opening_has_no_staircase():
    """The old mesh jumped by the full gape at each 3 mm cell edge; the new one changes gently."""
    g = grid(mesh_of(chest_with(cells=range(2, 10), depth=4.0)))
    widths = [g[5][c].z - g[4][c].z for c in range(COLUMNS)]
    biggest_step = max(abs(a - b) for a, b in zip(widths, widths[1:]))
    assert biggest_step < 0.45 * max(widths)


def test_deeper_cut_opens_wider():
    shallow = grid(mesh_of(chest_with(depth=0.6)))
    deep = grid(mesh_of(chest_with(depth=3.0)))
    middle = COLUMNS // 2
    assert deep[5][middle].z > shallow[5][middle].z


def test_opening_never_exceeds_the_cap():
    g = grid(mesh_of(chest_with(depth=50.0, deeper=("subcutaneous", "intercostal-muscle", "pleura"))))
    assert max(g[5][c].z for c in range(COLUMNS)) <= MAX_GAPE_MM + 1e-9


def test_upper_layer_is_retracted_when_the_layers_below_are_open():
    alone = grid(mesh_of(chest_with(depth=2.0)))
    retracted = grid(mesh_of(chest_with(depth=2.0, deeper=("subcutaneous", "intercostal-muscle"))))
    middle = COLUMNS // 2
    assert retracted[5][middle].z > alone[5][middle].z


def test_cut_edge_has_a_raised_lip_and_surrounding_skin_curls_up():
    g = grid(mesh_of(chest_with(depth=3.0)))
    top = LAYER_TOPS_MM["skin"]
    middle = COLUMNS // 2
    assert g[4][middle].y > top and g[5][middle].y > top
    assert g[3][middle].y > top and g[3][middle].y < g[4][middle].y          # curl is gentler than the lip
    assert g[0][middle].y == pytest.approx(top)                               # far skin is untouched


def test_surrounding_skin_is_drawn_outward():
    intact = grid(mesh_of(LayeredChestState()))
    cut = grid(mesh_of(chest_with(depth=3.0)))
    middle = COLUMNS // 2
    assert cut[6][middle].z > intact[6][middle].z
    assert cut[3][middle].z < intact[3][middle].z


def test_rows_never_cross_so_the_mesh_cannot_fold():
    for depth in (0.6, 2.0, 6.0, 50.0):
        g = grid(mesh_of(chest_with(depth=depth, deeper=("subcutaneous", "intercostal-muscle", "pleura"))))
        for column in range(COLUMNS):
            zs = [g[r][column].z for r in range(ROWS)]
            assert all(a < b for a, b in zip(zs, zs[1:])), (depth, column, zs)


def test_columns_are_evenly_spaced_across_the_corridor():
    g = grid(mesh_of(LayeredChestState()))
    xs = [v.x for v in g[0]]
    assert xs[0] == pytest.approx(CORRIDOR_MIN_X_MM)
    assert all(b - a == pytest.approx(CELL_WIDTH_MM / MESH_SUBDIVISIONS) for a, b in zip(xs, xs[1:]))


def test_single_cell_cut_is_a_small_pointed_opening():
    g = grid(mesh_of(chest_with(cells=[6], depth=1.0)))
    widths = [g[5][c].z - g[4][c].z for c in range(COLUMNS)]
    assert max(widths) > 0.31
    assert sum(1 for w in widths if w > 0.31) <= 7      # about 10 mm, never the whole corridor


def test_tool_contact_dents_the_skin_under_the_tool():
    chest = LayeredChestState()
    dented = chest._layer_mesh("skin", tool_sample(x=0.0, y=-1.0, z=0.0), 2.0, True)
    g = grid(dented)
    assert min(v.y for row in g for v in row) < LAYER_TOPS_MM["skin"] - 0.5


# ---------------------------------------------------------------- the wound channel


def wound(chest):
    return chest.wound_mesh()


def test_wound_channel_is_empty_without_a_cut():
    assert wound(LayeredChestState()).vertices_mm == []


def test_wound_channel_closes_to_a_point_at_both_ends():
    chest = LayeredChestState()
    for i in range(0, 60):
        chest.blade_path.append((-15.0 + i * 0.5, 0.0, 2.0, 0.0))
    mesh = wound(chest)
    widths = {}
    for vertex in mesh.vertices_mm:
        widths.setdefault(round(vertex.x, 3), []).append(abs(vertex.z))
    xs = sorted(widths)
    end_width = max(widths[xs[0]])
    middle_width = max(widths[xs[len(xs) // 2]])
    assert end_width < 0.5 * middle_width


def test_wound_channel_gets_deeper_with_pressure():
    def deepest(depth):
        chest = LayeredChestState()
        for i in range(30):
            chest.blade_path.append((-10.0 + i * 0.5, 0.0, depth, 0.0))
        return min(v.y for v in wound(chest).vertices_mm)

    assert deepest(6.0) < deepest(1.5)


def test_wound_from_cut_cells_when_there_is_no_blade_path():
    chest = chest_with(cells=range(3, 8), depth=2.0)
    mesh = wound(chest)
    assert len(mesh.vertices_mm) >= 8 and min(v.y for v in mesh.vertices_mm) < -0.8
