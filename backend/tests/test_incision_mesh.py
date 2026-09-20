"""The visual incision: recorded at 0.75 mm along the blade's real path, tapered, smooth and never folded."""
from __future__ import annotations

import math
import random

import pytest

from surge_prep.layered_chest import (
    CORRIDOR_MIN_X_MM,
    FINE_BINS,
    FINE_CUT_THRESHOLD_MM,
    FINE_STEP_MM,
    LAYER_ORDER,
    LAYER_TOPS_MM,
    MAX_GAPE_MM,
    MESH_ROW_Z,
    SEAM_ROW,
    LayeredChestState,
    exposed_surface_y_mm,
    fine_bin,
    pose_contact,
)
from surge_prep.models import Quaternion, ToolSample, Vector3

COLUMNS = FINE_BINS
ROWS = len(MESH_ROW_Z)
UPPER, LOWER = SEAM_ROW, SEAM_ROW + 1


def tool_sample(x=0.0, y=10.0, z=0.0, tool="scalpel") -> ToolSample:
    return ToolSample(
        session_id="s", tool_id=tool, device_id="d", calibration_id="c", sequence=0, timestamp_ms=0,
        position_mm=Vector3(x=x, y=y, z=z), orientation=Quaternion(qx=0, qy=0, qz=0, qw=1),
        force_n=0, contact=False,
    )


def stroke(chest, x0, x1, z0=0.0, z1=0.0, y=-1.2, steps=80, tool="scalpel"):
    """Draw the tool from (x0, z0) to (x1, z1) at tip height y through the real contact + cutting logic."""
    for i in range(steps):
        t = i / (steps - 1)
        s = tool_sample(x0 + (x1 - x0) * t, y, z0 + (z1 - z0) * t, tool)
        surface = exposed_surface_y_mm(chest, s.position_mm.x, s.position_mm.z)
        contact, penetration, reaction, _ = pose_contact(s, surface)
        chest.update(s, contact, penetration, reaction)


def lift(chest):
    chest.update(tool_sample(y=10.0), False, 0.0, 0.0)


def chest_with_cells(layer="skin", cells=range(2, 10), depth=2.0, deeper=()):
    """Only 3 mm scoring cells (the way native SOFA reports a cut): the mesh falls back to them."""
    chest = LayeredChestState()
    for name in [layer, *deeper]:
        for cell in cells:
            chest.layers[name].cut_cells.add(cell)
            chest.layers[name].depths_mm[cell] = depth
    return chest


def mesh_of(chest, layer="skin"):
    return chest._layer_mesh(layer, tool_sample(), 0.0, False)


def grid(mesh):
    v = mesh.vertices_mm
    return [[v[r * COLUMNS + c] for c in range(COLUMNS)] for r in range(ROWS)]


def widths_of(g):
    return [g[LOWER][c].z - g[UPPER][c].z for c in range(COLUMNS)]


def centres_of(g):
    return [(g[LOWER][c].z + g[UPPER][c].z) / 2 for c in range(COLUMNS)]


def x_of(column):
    return CORRIDOR_MIN_X_MM + column * FINE_STEP_MM


def open_columns(chest, layer="skin"):
    return [c for c in range(COLUMNS) if chest.layers[layer].bin_depth(c) > 0]


# ---------------------------------------------------------------- structure


def test_uncut_mesh_is_flat_and_closed():
    mesh = mesh_of(LayeredChestState())
    assert mesh.topology_revision == 1
    assert len(mesh.vertices_mm) == ROWS * COLUMNS
    g = grid(mesh)
    assert all(abs(v.y - LAYER_TOPS_MM["skin"]) < 1e-9 for row in g for v in row)
    assert [row[0].z for row in g] == pytest.approx(MESH_ROW_Z)               # rows sit exactly where they were
    assert len(mesh.triangle_indices) == (ROWS - 1) * (COLUMNS - 1) * 6       # no slit in intact skin


def test_columns_are_evenly_spaced_across_the_corridor():
    xs = [v.x for v in grid(mesh_of(LayeredChestState()))[0]]
    assert xs[0] == pytest.approx(CORRIDOR_MIN_X_MM)
    assert xs[-1] == pytest.approx(-CORRIDOR_MIN_X_MM)
    assert all(b - a == pytest.approx(FINE_STEP_MM) for a, b in zip(xs, xs[1:]))


@pytest.mark.parametrize("layer", LAYER_ORDER)
def test_every_layer_mesh_is_valid(layer):
    chest = LayeredChestState()
    stroke(chest, -8, 8, y=-1.2)
    mesh = mesh_of(chest, layer)
    assert mesh.object_id == f"layer-{layer}"
    assert len(mesh.triangle_indices) % 3 == 0 and max(mesh.triangle_indices) < len(mesh.vertices_mm)
    assert all(math.isfinite(c) for v in mesh.vertices_mm for c in (v.x, v.y, v.z))


def test_topology_revision_grows_with_cuts():
    chest = LayeredChestState()
    before = mesh_of(chest).topology_revision
    stroke(chest, -10, 10)
    assert mesh_of(chest).topology_revision > before


def test_fine_bin_clamps_to_the_corridor():
    assert fine_bin(-99) == 0 and fine_bin(99) == FINE_BINS - 1
    assert fine_bin(CORRIDOR_MIN_X_MM) == 0
    assert fine_bin(0.0) == FINE_BINS // 2


# ---------------------------------------------------------------- the blade's real path


def test_incision_starts_and_ends_where_the_blade_did():
    chest = LayeredChestState()
    stroke(chest, 0.7, 10.3)
    columns = open_columns(chest)
    assert abs(x_of(columns[0]) - 0.7) <= 1.0
    assert abs(x_of(columns[-1]) - 10.3) <= 1.0
    assert columns == list(range(columns[0], columns[-1] + 1))               # one unbroken cut


def test_incision_is_sharper_than_the_3mm_scoring_cells():
    chest = LayeredChestState()
    stroke(chest, 0.7, 10.3)
    cells = sorted(chest.layers["skin"].cut_cells)
    cell_start = CORRIDOR_MIN_X_MM + cells[0] * 3.0
    fine_start = x_of(open_columns(chest)[0])
    assert abs(fine_start - 0.7) < abs(cell_start - 0.7) + 1e-9 or abs(fine_start - 0.7) <= 0.75


def test_cutting_starts_almost_immediately_at_first_contact():
    chest = LayeredChestState()
    stroke(chest, 0.0, 2.0, steps=40)
    assert open_columns(chest), "a 2 mm stroke should already have opened the skin"


def test_a_harder_press_cuts_deeper_columns():
    shallow, deep = LayeredChestState(), LayeredChestState()
    stroke(shallow, -8, 8, y=-0.5)
    stroke(deep, -8, 8, y=-2.6)
    mid = COLUMNS // 2
    assert deep.layers["skin"].bin_depth(mid) > shallow.layers["skin"].bin_depth(mid)


def test_lifting_the_blade_leaves_uncut_skin_between_two_cuts():
    chest = LayeredChestState()
    stroke(chest, -12, -4)
    lift(chest)
    stroke(chest, 4, 12)
    g = grid(mesh_of(chest))
    mid = COLUMNS // 2
    assert widths_of(g)[mid] < 0.31                                          # untouched between the two cuts
    assert widths_of(g)[fine_bin(-8)] > 0.8 and widths_of(g)[fine_bin(8)] > 0.8


def test_hovering_or_lifting_never_extends_the_cut():
    chest = LayeredChestState()
    stroke(chest, -6, 6)
    before = open_columns(chest)
    stroke(chest, 6, 16, y=6.0)                                              # tip above the skin
    assert open_columns(chest) == before


def test_opening_follows_the_blade_sideways():
    chest = LayeredChestState()
    stroke(chest, -10, 10, z0=0.0, z1=4.0)
    centres = centres_of(grid(mesh_of(chest)))
    assert centres[fine_bin(8)] > centres[fine_bin(-8)] + 1.0
    assert centres[fine_bin(8)] > 1.5


def test_an_off_centre_cut_opens_where_it_was_made():
    chest = LayeredChestState()
    stroke(chest, -8, 8, z0=3.0, z1=3.0)
    centres = centres_of(grid(mesh_of(chest)))
    assert centres[COLUMNS // 2] == pytest.approx(3.0, abs=0.35)


def test_a_cut_on_the_other_side_opens_on_the_other_side():
    chest = LayeredChestState()
    stroke(chest, -8, 8, z0=-3.0, z1=-3.0)
    assert centres_of(grid(mesh_of(chest)))[COLUMNS // 2] == pytest.approx(-3.0, abs=0.35)


def test_deeper_layers_are_recorded_at_the_same_fine_resolution():
    chest = LayeredChestState()
    stroke(chest, -10, 10, y=-1.2)                                           # skin
    stroke(chest, -8, 8, y=-6.0, tool="blunt-dissector")                     # fat
    fat = open_columns(chest, "subcutaneous")
    assert fat and abs(x_of(fat[0]) - (-8)) <= 1.0 and abs(x_of(fat[-1]) - 8) <= 1.0


# ---------------------------------------------------------------- the opening


def test_edges_part_symmetrically_about_the_centre_line():
    chest = LayeredChestState()
    stroke(chest, -10, 10)
    g = grid(mesh_of(chest))
    for c in open_columns(chest):
        assert (g[UPPER][c].z + g[LOWER][c].z) / 2 == pytest.approx(0.0, abs=1e-6)


def test_opening_is_widest_in_the_middle_and_pointed_at_the_ends():
    chest = LayeredChestState()
    stroke(chest, -10, 10, y=-2.0)
    widths = widths_of(grid(mesh_of(chest)))
    peak = max(widths)
    assert widths.index(peak) in range(COLUMNS // 4, 3 * COLUMNS // 4)
    cut = [c for c, w in enumerate(widths) if w > 0.31]
    assert widths[cut[0]] < 0.6 * peak and widths[cut[-1]] < 0.6 * peak
    assert widths[0] == pytest.approx(0.3) and widths[-1] == pytest.approx(0.3)


def test_opening_has_no_staircase():
    chest = LayeredChestState()
    stroke(chest, -10, 10, y=-2.4)
    widths = widths_of(grid(mesh_of(chest)))
    assert max(abs(a - b) for a, b in zip(widths, widths[1:])) < 0.3 * max(widths)


def test_deeper_cut_opens_wider():
    shallow, deep = LayeredChestState(), LayeredChestState()
    stroke(shallow, -8, 8, y=-0.5)
    stroke(deep, -8, 8, y=-2.6)
    mid = COLUMNS // 2
    assert widths_of(grid(mesh_of(deep)))[mid] > widths_of(grid(mesh_of(shallow)))[mid]


def test_opening_never_exceeds_the_cap():
    chest = chest_with_cells(depth=50.0, deeper=("subcutaneous", "intercostal-muscle", "pleura"))
    g = grid(mesh_of(chest))
    assert max(widths_of(g)) / 2 <= MAX_GAPE_MM + 0.15 + 1e-9


def test_upper_layer_is_retracted_when_the_layers_below_are_open():
    alone = widths_of(grid(mesh_of(chest_with_cells(depth=2.0))))
    retracted = widths_of(grid(mesh_of(chest_with_cells(depth=2.0, deeper=("subcutaneous", "intercostal-muscle")))))
    mid = COLUMNS // 2
    assert retracted[mid] > alone[mid]


def test_cut_edge_has_a_raised_lip_that_eases_off_outward():
    chest = LayeredChestState()
    stroke(chest, -10, 10, y=-2.4)
    g = grid(mesh_of(chest))
    top, mid = LAYER_TOPS_MM["skin"], COLUMNS // 2
    lip = g[UPPER][mid].y - top
    assert lip > 0.1
    heights = [g[r][mid].y - top for r in range(UPPER, -1, -1)]              # from the cut edge outward
    assert all(a >= b - 1e-9 for a, b in zip(heights, heights[1:]))
    assert g[0][mid].y == pytest.approx(top)                                 # far skin is untouched


def test_surrounding_skin_is_drawn_outward():
    chest = LayeredChestState()
    stroke(chest, -10, 10, y=-2.4)
    cut, intact = grid(mesh_of(chest)), grid(mesh_of(LayeredChestState()))
    mid = COLUMNS // 2
    assert cut[UPPER - 1][mid].z < intact[UPPER - 1][mid].z
    assert cut[LOWER + 1][mid].z > intact[LOWER + 1][mid].z


def test_patch_boundary_never_moves():
    chest = LayeredChestState()
    stroke(chest, -14, 14, z0=-4, z1=4, y=-2.6)
    g = grid(mesh_of(chest))
    for c in range(COLUMNS):
        assert g[0][c].z == pytest.approx(-32.0) and g[-1][c].z == pytest.approx(32.0)


def test_rows_never_cross_so_the_mesh_cannot_fold():
    """Property test: random strokes, depths and drift must never fold the surface over itself."""
    rng = random.Random(4)
    for _ in range(25):
        chest = LayeredChestState()
        for _ in range(rng.randint(1, 3)):
            x0 = rng.uniform(-16, 8)
            stroke(chest, x0, x0 + rng.uniform(2, 14), rng.uniform(-5, 5), rng.uniform(-5, 5), y=rng.uniform(-0.3, -2.9),
                   steps=50)
            lift(chest)
        for layer in LAYER_ORDER:
            g = grid(mesh_of(chest, layer))
            for c in range(COLUMNS):
                zs = [g[r][c].z for r in range(ROWS)]
                assert all(a < b for a, b in zip(zs, zs[1:])), (layer, c, zs)


def test_cells_only_cut_still_draws_a_tapered_opening():
    """Native SOFA reports cuts per 3 mm cell; the mesh must still look right from that alone."""
    widths = widths_of(grid(mesh_of(chest_with_cells(cells=range(2, 10), depth=2.5))))
    peak = max(widths)
    cut = [c for c, w in enumerate(widths) if w > 0.31]
    assert cut and widths[cut[0]] < 0.6 * peak and widths[cut[-1]] < 0.6 * peak


def test_tool_contact_dents_the_skin_under_the_tool():
    dented = LayeredChestState()._layer_mesh("skin", tool_sample(x=0.0, y=-1.0, z=0.0), 2.0, True)
    assert min(v.y for row in grid(dented) for v in row) < LAYER_TOPS_MM["skin"] - 0.5


# ---------------------------------------------------------------- the wound channel


def test_wound_channel_is_empty_without_a_cut():
    assert LayeredChestState().wound_mesh().vertices_mm == []


def test_wound_channel_is_a_multi_point_profile_that_follows_the_cut():
    chest = LayeredChestState()
    stroke(chest, -8, 8, y=-2.0)
    mesh = chest.wound_mesh()
    assert mesh.object_id == "wound-channel" and mesh.triangle_indices
    xs = [v.x for v in mesh.vertices_mm]
    cut = open_columns(chest)
    assert min(xs) <= x_of(cut[0]) and max(xs) >= x_of(cut[-1])            # covers the whole cut
    assert min(xs) >= x_of(cut[0]) - 4 * FINE_STEP_MM and max(xs) <= x_of(cut[-1]) + 4 * FINE_STEP_MM
    assert len(mesh.vertices_mm) % 7 == 0                                    # lip, wall, toe, bed, toe, wall, lip


def test_wound_channel_is_narrow_at_the_ends_and_wide_in_the_middle():
    chest = LayeredChestState()
    stroke(chest, -10, 10, y=-2.4)
    spans = {}
    for v in chest.wound_mesh().vertices_mm:
        low, high = spans.get(round(v.x, 3), (99, -99))
        spans[round(v.x, 3)] = (min(low, v.z), max(high, v.z))
    xs = sorted(spans)
    width = lambda x: spans[x][1] - spans[x][0]
    assert width(xs[0]) < 0.5 * width(xs[len(xs) // 2]) and width(xs[-1]) < 0.5 * width(xs[len(xs) // 2])


def test_wound_bed_gets_deeper_with_pressure_and_with_each_opened_layer():
    def deepest(chest):
        return min(v.y for v in chest.wound_mesh().vertices_mm)

    shallow, deep = LayeredChestState(), LayeredChestState()
    stroke(shallow, -8, 8, y=-0.5)
    stroke(deep, -8, 8, y=-2.6)
    assert deepest(deep) < deepest(shallow)
    stroke(deep, -6, 6, y=-6.0, tool="blunt-dissector")
    assert deepest(deep) < -3.0                                              # the fat is now part of the wound


def test_wound_channel_follows_sideways_drift():
    chest = LayeredChestState()
    stroke(chest, -10, 10, z0=-3.0, z1=3.0)
    mesh = chest.wound_mesh()
    def mean_z(lo, hi):
        zs = [v.z for v in mesh.vertices_mm if lo <= v.x <= hi]
        return sum(zs) / len(zs)
    assert mean_z(6, 10) > mean_z(-10, -6) + 1.5


def test_wound_from_cell_only_cuts_falls_back_to_the_path_builder():
    chest = chest_with_cells(cells=range(3, 8), depth=2.0)
    mesh = chest.wound_mesh()
    assert len(mesh.vertices_mm) >= 8 and min(v.y for v in mesh.vertices_mm) < -0.8


def test_wound_from_blade_path_only_still_works():
    chest = LayeredChestState()
    for i in range(30):
        chest.blade_path.append((-10.0 + i * 0.5, 0.0, 2.0, 0.0))
    assert chest.wound_mesh().vertices_mm


def test_fine_threshold_is_small_enough_to_cut_immediately():
    assert 0 < FINE_CUT_THRESHOLD_MM <= 0.3 and FINE_STEP_MM <= 1.0


def test_wound_channel_sits_under_every_column_where_the_skin_parts():
    """Regression: the fat below showed through the tips because the channel was shorter than the gap."""
    chest = LayeredChestState()
    stroke(chest, -8, 8, y=-2.0)
    gap = grid(mesh_of(chest))
    parted = {round(gap[UPPER][c].x, 3) for c in range(COLUMNS) if gap[LOWER][c].z - gap[UPPER][c].z > 0.31}
    covered = {round(v.x, 3) for v in chest.wound_mesh().vertices_mm}
    assert parted <= covered
