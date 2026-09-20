from __future__ import annotations

from dataclasses import dataclass, field
import math

from .models import (
    DeformableMeshState,
    TissueLayerState,
    TissueState,
    ToolSample,
    ToolState,
    Vector3,
)

SURFACE_Y_MM = 0.0
PATCH_RADIUS_X_MM = 40.0
PATCH_RADIUS_Z_MM = 36.0
CARVABLE_RADIUS_X_MM = 30.0
CARVABLE_RADIUS_Z_MM = 22.0
CORRIDOR_MIN_X_MM = -18.0
CORRIDOR_MAX_X_MM = 18.0
CELL_WIDTH_MM = 3.0
CORRIDOR_HALF_WIDTH_MM = 6.0
# Calibrated against the native constraint response from the localized FEM
# scene. Physical hardware force thresholds remain a separate calibration.
# Native blade-edge contact distributes constraint force across a line rather
# than concentrating it at the old sphere. Treat any stable solver force above
# numerical noise as contact; hardware coaching thresholds remain separate.
MINIMUM_REACTION_N = 0.001
MAXIMUM_REACTION_N = 3.0
CUT_THRESHOLD_MM = 0.5
REACTION_PER_MM = 0.38
CONTACT_THRESHOLD_MM = 0.15
PUNCTURE_DEPTH_MM = 0.4
RIB_HALF_WIDTH_MM = 4.0
RIB_CENTRES_MM = (-18.0, 18.0)
RIB_TOP_Y_MM = -18.0
# Keyboard fallback only. Calibrated hardware must not reuse this bound.
WORKSPACE_MIN_Y_MM = -80.0
WORKSPACE_MAX_Y_MM = 40.0
JITTER_HOLD_MS = 180
# Visual opening of an incision (mesh only; scoring cells stay 3 mm wide)
FINE_STEP_MM = 0.75                                  # resolution of the recorded incision
FINE_BINS = int(round((36.0) / FINE_STEP_MM)) + 1
FINE_CUT_THRESHOLD_MM = 0.2                          # a column counts as cut once the blade went 0.2 mm deep
MESH_SUBDIVISIONS = int(round(3.0 / FINE_STEP_MM))
MAX_GAPE_MM = 5.0
GAPE_BASE_MM = 0.6
END_TAPER_MM = 3.5                                   # a blade enters and leaves at an angle: the cut runs out to a point
GAPE_PER_MM_DEPTH = 0.95
MAX_CENTRE_SHIFT_MM = 3.0
SEAM_OFFSET_MM = 0.15
# Rows across the layer, dense near the cut so the edge can roll over smoothly
MESH_ROW_Z = [-32.0, -18.0, -12.0, -7.0, -4.0, -2.2, -0.9, -0.15,
              0.15, 0.9, 2.2, 4.0, 7.0, 12.0, 18.0, 32.0]
SEAM_ROW = 7
DEGRADE_TIMEOUT_MS = 500

LAYER_ORDER = ("skin", "subcutaneous", "intercostal-muscle", "pleura")
LAYER_TOOLS = {
    "skin": "scalpel",
    "subcutaneous": "blunt-dissector",
    "intercostal-muscle": "blunt-dissector",
    "pleura": "scalpel",
}
LAYER_BOTTOMS_MM = {
    "skin": -3.0,
    "subcutaneous": -15.0,
    "intercostal-muscle": -25.0,
    "pleura": -32.0,
}
LAYER_TOPS_MM = {
    "skin": 0.0,
    "subcutaneous": -3.0,
    "intercostal-muscle": -15.0,
    "pleura": -25.0,
}
LAYER_STAGES = {
    "skin": "skin-incision",
    "subcutaneous": "blunt-dissection",
    "intercostal-muscle": "blunt-dissection",
    "pleura": "pleural-entry",
}


def fine_bin(x_mm: float) -> int:
    """Index of the 0.75 mm column nearest to x, clamped to the corridor."""
    return max(0, min(FINE_BINS - 1, int(round((x_mm - CORRIDOR_MIN_X_MM) / FINE_STEP_MM))))


def cell_count() -> int:
    return round((CORRIDOR_MAX_X_MM - CORRIDOR_MIN_X_MM) / CELL_WIDTH_MM)


def corridor_cell(x_mm: float) -> int:
    value = int((x_mm - CORRIDOR_MIN_X_MM) / CELL_WIDTH_MM)
    return max(0, min(cell_count() - 1, value))


def in_patch(x_mm: float, z_mm: float) -> bool:
    return (
        (x_mm / PATCH_RADIUS_X_MM) ** 2
        + (z_mm / PATCH_RADIUS_Z_MM) ** 2
        <= 1.0
    )


def in_carvable_field(x_mm: float, z_mm: float) -> bool:
    """Keep topology changes away from the field's fixed FEM boundary."""
    return (
        (x_mm / CARVABLE_RADIUS_X_MM) ** 2
        + (z_mm / CARVABLE_RADIUS_Z_MM) ** 2
        <= 1.0
    )


def in_corridor(x_mm: float, z_mm: float) -> bool:
    return (
        CORRIDOR_MIN_X_MM <= x_mm <= CORRIDOR_MAX_X_MM
        and abs(z_mm) <= CORRIDOR_HALF_WIDTH_MM
    )


def hits_protected_rib(x_mm: float, y_mm: float, z_mm: float) -> bool:
    if y_mm > RIB_TOP_Y_MM:
        return False
    return any(abs(z_mm - centre) <= RIB_HALF_WIDTH_MM for centre in RIB_CENTRES_MM)


def exposed_surface_y_mm(chest: "LayeredChestState", x_mm: float, z_mm: float) -> float:
    if not in_corridor(x_mm, z_mm):
        return SURFACE_Y_MM
    cell = corridor_cell(x_mm)
    for name in LAYER_ORDER:
        if cell not in chest.layers[name].cut_cells:
            return LAYER_TOPS_MM[name]
    return LAYER_BOTTOMS_MM["pleura"]


def pose_contact(
    sample: ToolSample, surface_y_mm: float = SURFACE_Y_MM
) -> tuple[bool, float, float, Vector3]:
    """Derive contact from tool pose. Keyboard contact/force are ignored in pose-only."""
    x_mm = sample.position_mm.x
    y_mm = sample.position_mm.y
    z_mm = sample.position_mm.z
    if hits_protected_rib(x_mm, y_mm, z_mm):
        y_mm = RIB_TOP_Y_MM
    if not in_patch(x_mm, z_mm) or y_mm >= surface_y_mm:
        return False, 0.0, 0.0, Vector3(x=x_mm, y=y_mm, z=z_mm)
    penetration = surface_y_mm - y_mm
    if penetration < CONTACT_THRESHOLD_MM:
        return False, 0.0, 0.0, Vector3(x=x_mm, y=y_mm, z=z_mm)
    reaction = min(8.0, penetration * REACTION_PER_MM)
    return True, penetration, reaction, Vector3(x=x_mm, y=y_mm, z=z_mm)


def instrument_angle_deg(sample: ToolSample) -> float:
    qw = sample.orientation.qw
    qx = sample.orientation.qx
    qy = sample.orientation.qy
    qz = sample.orientation.qz
    handle_y = qw * qw - qx * qx - qy * qy + qz * qz
    return abs(math.degrees(math.acos(max(-1.0, min(1.0, handle_y)))) - 90.0)


@dataclass
class LayerOpening:
    depths_mm: dict[int, float] = field(default_factory=dict)
    cut_cells: set[int] = field(default_factory=set)
    previous_x_mm: float | None = None
    previous_fine: tuple[float, float, float] | None = None       # last tracked (x, z, depth)
    # Sub-cell record of the incision (0.75 mm columns): how deep the blade went and where it was sideways
    fine_depth: dict[int, float] = field(default_factory=dict)
    fine_z: dict[int, float] = field(default_factory=dict)
    fine_cells: set[int] = field(default_factory=set)

    def bin_depth(self, column: int) -> float:
        """Cut depth at a 0.75 mm column, 0 if the blade has not opened it."""
        cell = min(cell_count() - 1, int(column * FINE_STEP_MM / CELL_WIDTH_MM))
        if cell in self.fine_cells:
            d = self.fine_depth.get(column, 0.0)
            return d if d >= FINE_CUT_THRESHOLD_MM else 0.0
        if cell in self.cut_cells:                    # only recorded per 3 mm cell (e.g. by native SOFA)
            return self.depths_mm.get(cell, 0.0)
        return 0.0

    @property
    def length_mm(self) -> float:
        return len(self.cut_cells) * CELL_WIDTH_MM

    @property
    def depth_mm(self) -> float:
        return max(self.depths_mm.values(), default=0.0)

    @property
    def progress(self) -> float:
        return len(self.cut_cells) / cell_count()

    @property
    def opened(self) -> bool:
        # Four adjacent scoring cells represent a continuous 12 mm tract in
        # the current coarse native mesh. This is a prototype progression
        # threshold, not a clinically validated incision prescription.
        return len(self.cut_cells) >= 4


@dataclass
class LayeredChestState:
    layers: dict[str, LayerOpening] = field(
        default_factory=lambda: {name: LayerOpening() for name in LAYER_ORDER}
    )
    tube_placed: bool = False
    layer_violations: int = 0
    outside_corridor_contacts: int = 0
    blade_path: list[tuple[float, float, float, float]] = field(default_factory=list)

    @property
    def topology_revision(self) -> int:
        return 1 + sum(len(layer.cut_cells) for layer in self.layers.values())

    def current_layer(self) -> str:
        for name in LAYER_ORDER:
            if not self.layers[name].opened:
                return name
        return "pleura"

    def procedure_stage(self, contact: bool) -> str:
        if self.tube_placed:
            return "complete"
        current = self.current_layer()
        if not contact:
            if current == "skin" and not self.layers["skin"].cut_cells:
                return "approach"
            if current == "skin":
                return "landmark-alignment"
        if current == "skin":
            return "skin-incision" if contact else "landmark-alignment"
        if current in ("subcutaneous", "intercostal-muscle"):
            return "blunt-dissection"
        if self.layers["pleura"].opened:
            return "tube-placement"
        return "pleural-entry"

    def update(
        self,
        sample: ToolSample,
        contact: bool,
        penetration_mm: float,
        reaction_n: float,
        advance_opening: bool = True,
    ) -> tuple[str, list[str], bool]:
        events: list[str] = []
        self._track_fine(sample, contact, reaction_n)
        blocked_by_rib = hits_protected_rib(
            sample.position_mm.x, sample.position_mm.y, sample.position_mm.z
        )
        if (
            sample.tool_id == "chest-tube"
            and self.layers["pleura"].opened
            and in_corridor(sample.position_mm.x, sample.position_mm.z)
            and sample.position_mm.y <= LAYER_BOTTOMS_MM["intercostal-muscle"]
        ):
            if not self.tube_placed:
                self.tube_placed = True
                events.extend(["stage-completed", "session-completed"])
            return "tube-placement", events, blocked_by_rib
        if not contact:
            for layer in self.layers.values():
                layer.previous_x_mm = None
            return "approach", events, blocked_by_rib
        if not in_corridor(sample.position_mm.x, sample.position_mm.z):
            self.outside_corridor_contacts += 1
            return "outside-target", ["outside-corridor"], blocked_by_rib
        if reaction_n > MAXIMUM_REACTION_N:
            return "excessive-force", ["excessive-force"], blocked_by_rib
        if reaction_n < MINIMUM_REACTION_N:
            return "low-force", events, blocked_by_rib

        # The layer being worked is the one the tip is physically inside. Measuring depth from the
        # exposed surface (penetration) would call muscle 'skin' again once the skin above it is open.
        active = self.layer_at_height(sample.position_mm.y)
        required = LAYER_TOOLS[active]
        if sample.tool_id != required:
            self.layer_violations += 1
            events.append("layer-violation")
            return "contact", events, blocked_by_rib

        if not self._predecessors_open(active):
            self.layer_violations += 1
            events.append("layer-violation")
            return "contact", events, blocked_by_rib

        if not advance_opening:
            return "contact", events, blocked_by_rib

        opening = self.layers[active]
        previous_cuts = len(opening.cut_cells)
        start_x = sample.position_mm.x if opening.previous_x_mm is None else opening.previous_x_mm
        start_cell = corridor_cell(start_x)
        end_cell = corridor_cell(sample.position_mm.x)
        crossed = list(range(min(start_cell, end_cell), max(start_cell, end_cell) + 1))
        travel_mm = 0.0 if opening.previous_x_mm is None else abs(
            sample.position_mm.x - opening.previous_x_mm
        )
        layer_thickness = LAYER_TOPS_MM[active] - LAYER_BOTTOMS_MM[active]
        depth_increment = max(0.15, reaction_n - 0.15) * 1.4 * travel_mm / max(1, len(crossed))
        max_depth = min(layer_thickness, 6.0)
        for cell in crossed:
            depth = opening.depths_mm.get(cell, 0.0) + depth_increment
            opening.depths_mm[cell] = min(depth, max_depth)
            if opening.depths_mm[cell] >= CUT_THRESHOLD_MM:
                opening.cut_cells.add(cell)
        opening.previous_x_mm = sample.position_mm.x
        if len(opening.cut_cells) > previous_cuts:
            events.append("layer-opened" if previous_cuts == 0 else "incision-extended")
            if opening.opened:
                events.append("stage-completed")
        mode = "cutting" if opening.cut_cells else "contact"
        return mode, events, blocked_by_rib

    def _track_fine(self, sample: ToolSample, contact: bool, reaction_n: float) -> None:
        """Record the incision at 0.75 mm: the deepest the tip went at each column, and where it was sideways.

        This follows the tip itself rather than the 3 mm scoring cells, so the cut starts where the blade first
        entered the layer, ends where it left, keeps going while the tip is inside a layer whose cell is already
        counted as open, and follows sideways drift. The scoring cells are untouched.
        """
        x, y, z = sample.position_mm.x, sample.position_mm.y, sample.position_mm.z
        layer = self.layer_at_height(y)
        opening = self.layers[layer]
        for other in self.layers.values():
            if other is not opening:
                other.previous_fine = None                     # only the layer the tip is inside is tracked
        top, bottom = LAYER_TOPS_MM[layer], LAYER_BOTTOMS_MM[layer]
        depth = top - y
        column = fine_bin(x)
        upper_open = all(
            self.layers[name].bin_depth(column) > 0 for name in LAYER_ORDER[:LAYER_ORDER.index(layer)]
        )
        valid = (
            depth > 0.0
            and in_corridor(x, z)
            and sample.tool_id == LAYER_TOOLS[layer]
            and self._predecessors_open(layer)
            and upper_open
            and not (contact and reaction_n > MAXIMUM_REACTION_N)
        )
        if not valid:
            opening.previous_fine = None
            return
        depth = min(depth, top - bottom, 6.0)
        previous = opening.previous_fine
        if previous is None:
            spans = [(column, z, depth)]
        else:
            prev_x, prev_z, prev_depth = previous
            first, last = fine_bin(prev_x), fine_bin(x)
            step = 1 if last >= first else -1
            spans = []
            for b in range(first, last + step, step):
                t = 1.0 if last == first else (b - first) / (last - first)
                spans.append((b, prev_z + (z - prev_z) * t, prev_depth + (depth - prev_depth) * t))
        for b, bz, bd in spans:
            opening.fine_depth[b] = max(opening.fine_depth.get(b, 0.0), bd)
            opening.fine_z[b] = bz
            opening.fine_cells.add(min(cell_count() - 1, int(b * FINE_STEP_MM / CELL_WIDTH_MM)))
        opening.previous_fine = (x, z, depth)

    def record_sofa_cut(
        self, layer_id: str, sample: ToolSample, penetration_mm: float
    ) -> list[str]:
        """Observe an authoritative SOFA topology change for metrics/staging.

        This state object no longer grants permission for native carving. It
        records what SOFA actually removed so replay and scoring remain
        deterministic without pretending a Python counter is tissue physics.
        """
        if layer_id not in self.layers:
            return []
        if not in_corridor(sample.position_mm.x, sample.position_mm.z):
            self.outside_corridor_contacts += 1
            return ["outside-corridor-cut"]
        opening = self.layers[layer_id]
        previous = len(opening.cut_cells)
        # The native tetrahedral field uses approximately 5 mm surface cells.
        # Record every scoring cell overlapped by the actually removed SOFA
        # element, instead of pretending each network sample made a cut.
        affected_cells = [
            cell
            for cell in range(cell_count())
            if abs(
                CORRIDOR_MIN_X_MM + (cell + 0.5) * CELL_WIDTH_MM
                - sample.position_mm.x
            ) <= 4.0
        ]
        if not affected_cells:
            affected_cells = [corridor_cell(sample.position_mm.x)]
        for cell in affected_cells:
            opening.cut_cells.add(cell)
            opening.depths_mm[cell] = max(
                opening.depths_mm.get(cell, 0.0), penetration_mm
            )
        events = ["layer-opened" if previous == 0 else "incision-extended"]
        if opening.opened and previous / cell_count() < 0.4:
            events.append("stage-completed")
        return events

    def track_blade_path(
        self, sample: ToolSample, penetration_mm: float, surface_y: float
    ) -> None:
        """Record the visible incision trough from SOFA contact, not Unity."""
        if penetration_mm < PUNCTURE_DEPTH_MM:
            return
        if not in_carvable_field(sample.position_mm.x, sample.position_mm.z):
            return
        point = (
            float(sample.position_mm.x),
            float(sample.position_mm.z),
            float(penetration_mm),
            float(surface_y),
        )
        if self.blade_path:
            last = self.blade_path[-1]
            if abs(last[0] - point[0]) < 0.45 and abs(last[1] - point[1]) < 0.45:
                if point[2] > last[2]:
                    self.blade_path[-1] = point
                return
        self.blade_path.append(point)

    @staticmethod
    def layer_at_height(y_mm: float) -> str:
        """The tissue layer that contains an absolute tip height (0 = skin surface, negative = deeper)."""
        for name in LAYER_ORDER:
            if y_mm >= LAYER_BOTTOMS_MM[name]:
                return name
        return "pleura"

    def active_layer_for_depth(self, penetration_mm: float) -> str:
        y_mm = SURFACE_Y_MM - penetration_mm
        for name in LAYER_ORDER:
            if y_mm >= LAYER_BOTTOMS_MM[name]:
                return name
        return "pleura"

    def _predecessors_open(self, layer_id: str) -> bool:
        for name in LAYER_ORDER:
            if name == layer_id:
                return True
            if not self.layers[name].opened:
                return False
        return True

    def tissue_state(self, deformation_mm: float, mode: str) -> TissueState:
        active = self.current_layer() if mode != "approach" else (
            self.current_layer() if any(layer.cut_cells for layer in self.layers.values()) else "none"
        )
        if mode in ("contact", "cutting", "low-force", "excessive-force"):
            active = self.current_layer()
        skin = self.layers["skin"]
        return TissueState(
            deformation_mm=deformation_mm,
            incision_progress=skin.progress,
            incision_length_mm=skin.length_mm,
            incision_depth_mm=max(
                max(layer.depth_mm for layer in self.layers.values()),
                max((point[2] for point in self.blade_path), default=0.0),
            ),
            interaction_mode=mode,
            active_layer=active if active in LAYER_ORDER else "none",
            layers=[
                TissueLayerState(
                    layer_id=name,
                    opened=self.layers[name].opened,
                    opening_progress=self.layers[name].progress,
                    deformation_mm=deformation_mm if name == self.current_layer() else 0.0,
                )
                for name in LAYER_ORDER
            ],
        )

    def meshes(self, sample: ToolSample, deformation_mm: float, contact: bool) -> list[DeformableMeshState]:
        meshes = [
            self._layer_mesh(name, sample, deformation_mm if name == self.current_layer() else 0.0, contact)
            for name in LAYER_ORDER
        ]
        meshes.append(self.wound_mesh())
        return meshes

    def _gape_profile(
        self, layer_id: str, columns: int
    ) -> tuple[list[float], list[float], list[float]]:
        """Opening half-width, depth and centre-line offset (mm) at every 0.75 mm column of the layer.

        Built from the blade's recorded path (sub-cell accurate, follows sideways drift), falling back to the 3 mm
        scoring cells when only those exist (for example a cut reported by native SOFA). Layers above an opened layer
        are drawn further apart, as if the wound edges were retracted.
        """
        opening = self.layers[layer_id]
        deeper = LAYER_ORDER[LAYER_ORDER.index(layer_id) + 1:]
        gape, depth, centre = [], [], []
        for column in range(columns):
            d = opening.bin_depth(column)
            if d > 0:
                retract = 1.0 + 0.3 * sum(1 for name in deeper if self.layers[name].bin_depth(column) > 0)
                gape.append(min(MAX_GAPE_MM, (GAPE_BASE_MM + GAPE_PER_MM_DEPTH * d) * retract))
            else:
                gape.append(0.0)
            depth.append(d)
            centre.append(opening.fine_z.get(column, 0.0) if d > 0 else 0.0)
        # Taper every unbroken run of cut columns toward both of its ends
        column = 0
        while column < columns:
            if gape[column] <= 0.0:
                column += 1
                continue
            end = column
            while end + 1 < columns and gape[end + 1] > 0.0:
                end += 1
            for i in range(column, end + 1):
                distance = min(i - column + 1, end - i + 1) * FINE_STEP_MM
                t = min(1.0, distance / END_TAPER_MM)
                gape[i] *= 0.12 + 0.88 * t * t * (3.0 - 2.0 * t)
            column = end + 1
        for _ in range(3):                                             # light smoothing keeps the ends pointed
            gape = [0.25 * gape[max(0, i - 1)] + 0.5 * gape[i] + 0.25 * gape[min(columns - 1, i + 1)]
                    for i in range(columns)]
            centre = [0.25 * centre[max(0, i - 1)] + 0.5 * centre[i] + 0.25 * centre[min(columns - 1, i + 1)]
                      for i in range(columns)]
        return gape, depth, centre

    def _layer_mesh(
        self, layer_id: str, sample: ToolSample, deformation_mm: float, contact: bool
    ) -> DeformableMeshState:
        opening = self.layers[layer_id]
        y_mm = LAYER_TOPS_MM[layer_id]
        x_columns = FINE_BINS
        gape, _, centre = self._gape_profile(layer_id, x_columns)
        vertices: list[Vector3] = []
        for original_z in MESH_ROW_Z:
            sign = -1.0 if original_z < 0 else 1.0
            r0 = abs(original_z)
            for column in range(x_columns):
                x = CORRIDOR_MIN_X_MM + column * FINE_STEP_MM
                g = gape[column]
                g_norm = g / MAX_GAPE_MM
                z = original_z
                lift = 0.0
                if r0 < 32.0 and g > 0.0:
                    c = max(-MAX_CENTRE_SHIFT_MM, min(MAX_CENTRE_SHIFT_MM, centre[column]))
                    spread = math.exp(-max(0.0, r0 - SEAM_OFFSET_MM) / (3.0 + g))
                    z = c * math.exp(-r0 / 12.0) + sign * (r0 + g * spread)   # the skin beside the cut is drawn outward
                    lift = 0.45 * g_norm * math.exp(-(r0 - SEAM_OFFSET_MM) / 1.4)   # raised lip, easing off outward
                distance_squared = (x - sample.position_mm.x) ** 2 + (original_z - sample.position_mm.z) ** 2
                contact_deformation = (
                    -deformation_mm * math.exp(-distance_squared / 80.0) if contact else 0.0
                )
                vertices.append(Vector3(x=x, y=y_mm + contact_deformation + lift, z=z))

        triangles: list[int] = []
        rows = len(MESH_ROW_Z)
        for row in range(rows - 1):
            for column in range(x_columns - 1):
                if row == SEAM_ROW and (gape[column] + gape[column + 1]) / 2 > 0.12:
                    continue                                              # open wound: no skin across the cut
                a = row * x_columns + column
                b = a + 1
                c = (row + 1) * x_columns + column + 1
                d = c - 1
                triangles.extend([a, c, b, a, d, c])
        return DeformableMeshState(
            object_id=f"layer-{layer_id}",
            topology_revision=1 + len(opening.cut_cells),
            vertices_mm=vertices,
            triangle_indices=triangles,
        )

    def _bed_height(self, column: int) -> float:
        """Height of the wound floor at a column: the bottom of the deepest opened layer's cut."""
        bed = 0.0
        for name in LAYER_ORDER:
            d = self.layers[name].bin_depth(column)
            if d <= 0:
                break
            thickness = LAYER_TOPS_MM[name] - LAYER_BOTTOMS_MM[name]
            bed = LAYER_TOPS_MM[name] - min(d, thickness)
        return bed

    def _wound_detailed(self) -> DeformableMeshState:
        """The wound channel from the recorded incision: a rounded, stepped profile that follows the blade."""
        gape, _, centre = self._gape_profile("skin", FINE_BINS)
        skin = self.layers["skin"]
        # every column where the skin actually parts, including the smoothed run-out at both ends, so the
        # channel always sits under the gap and the fat below never shows through the tips
        columns = [b for b in range(FINE_BINS) if gape[b] > 0.005]
        vertices: list[Vector3] = []
        triangles: list[int] = []
        rings: dict[int, list[int]] = {}
        for b in columns:
            x = CORRIDOR_MIN_X_MM + b * FINE_STEP_MM
            width = max(0.4, gape[b] + SEAM_OFFSET_MM)
            c = max(-MAX_CENTRE_SHIFT_MM, min(MAX_CENTRE_SHIFT_MM, centre[b]))
            bed = self._bed_height(b) * min(1.0, 0.35 + gape[b] / 2.0)       # ends run out shallow
            bed = min(bed, -0.3)
            profile = [
                (-width, 0.25), (-width * 0.94, bed * 0.3), (-width * 0.66, bed * 0.78),
                (0.0, bed), (width * 0.66, bed * 0.78), (width * 0.94, bed * 0.3), (width, 0.25),
            ]
            rings[b] = []
            for dz, y in profile:
                rings[b].append(len(vertices))
                vertices.append(Vector3(x=x, y=y, z=c + dz))
        for b in columns:
            if b + 1 not in rings:
                continue
            for k in range(6):
                a, bb = rings[b][k], rings[b][k + 1]
                c2, d2 = rings[b + 1][k + 1], rings[b + 1][k]
                triangles.extend([a, bb, c2, a, c2, d2, a, c2, bb, a, d2, c2])   # both faces are visible
        return DeformableMeshState(
            object_id="wound-channel",
            topology_revision=max(1, len(columns)),
            vertices_mm=vertices,
            triangle_indices=triangles,
        )

    def wound_mesh(self, surface_y_fn=None) -> DeformableMeshState:
        skin = self.layers["skin"]
        if surface_y_fn is None and skin.fine_cells and any(skin.bin_depth(b) > 0 for b in range(FINE_BINS)):
            return self._wound_detailed()
        return self._wound_from_path(surface_y_fn)

    def _wound_from_path(self, surface_y_fn=None) -> DeformableMeshState:
        def height(x_mm: float, z_mm: float) -> float:
            if surface_y_fn is None:
                return SURFACE_Y_MM
            return float(surface_y_fn(x_mm, z_mm))

        points = list(self.blade_path)
        if not points:
            skin = self.layers["skin"]
            for cell in sorted(skin.cut_cells):
                x_mm = CORRIDOR_MIN_X_MM + (cell + 0.5) * CELL_WIDTH_MM
                depth = max(
                    layer.depths_mm.get(cell, 0.0) for layer in self.layers.values()
                )
                points.append((x_mm, 0.0, depth, height(x_mm, 0.0)))
        if not points:
            return DeformableMeshState(
                object_id="wound-channel",
                topology_revision=1,
                vertices_mm=[],
                triangle_indices=[],
            )
        points = sorted(points, key=lambda item: item[0])
        if len(points) == 1:
            x_mm, z_mm, depth, surface = points[0]
            points = [
                (x_mm - 1.6, z_mm, depth, surface),
                (x_mm + 1.6, z_mm, depth, surface),
            ]

        first_x, last_x = points[0][0], points[-1][0]

        def taper(x_mm: float) -> float:
            """1 in the middle of the wound, easing to 0.3 at both ends so it closes to a point."""
            edge = min(x_mm - first_x, last_x - x_mm)
            t = max(0.0, min(1.0, edge / 4.0))
            return 0.3 + 0.7 * t * t * (3 - 2 * t)

        vertices: list[Vector3] = []
        triangles: list[int] = []

        def add_quad(a: Vector3, b: Vector3, c: Vector3, d: Vector3) -> None:
            base = len(vertices)
            vertices.extend([a, b, c, d])
            triangles.extend(
                [base, base + 2, base + 1, base, base + 3, base + 2]
            )
            triangles.extend(
                [base, base + 1, base + 2, base, base + 2, base + 3]
            )

        for index in range(len(points) - 1):
            x0, z0, depth0, surface0 = points[index]
            x1, z1, depth1, surface1 = points[index + 1]
            depth0 = max(0.9, depth0)
            depth1 = max(0.9, depth1)
            half0 = min(5.8, 0.7 + depth0 * 0.32) * taper(x0)
            half1 = min(5.8, 0.7 + depth1 * 0.32) * taper(x1)
            left0 = Vector3(x=x0, y=surface0 + 0.2, z=z0 - half0)
            left1 = Vector3(x=x1, y=surface1 + 0.2, z=z1 - half1)
            right0 = Vector3(x=x0, y=surface0 + 0.2, z=z0 + half0)
            right1 = Vector3(x=x1, y=surface1 + 0.2, z=z1 + half1)
            bed0 = Vector3(x=x0, y=surface0 - depth0, z=z0)
            bed1 = Vector3(x=x1, y=surface1 - depth1, z=z1)
            add_quad(left0, left1, bed1, bed0)
            add_quad(right0, bed0, bed1, right1)

        return DeformableMeshState(
            object_id="wound-channel",
            topology_revision=max(1, len(points)),
            vertices_mm=vertices,
            triangle_indices=triangles,
        )


def tool_state_from_pose(
    sample: ToolSample, contact: bool, penetration_mm: float, reaction_n: float, contact_point: Vector3
) -> ToolState:
    return ToolState(
        tool_id=sample.tool_id,
        position_mm=sample.position_mm,
        orientation=sample.orientation,
        force_n=reaction_n,
        contact=contact,
        contact_point_mm=contact_point if contact else None,
        contact_normal=Vector3(x=0, y=1, z=0) if contact else None,
        reaction_force_n=reaction_n,
        penetration_depth_mm=penetration_mm,
    )
