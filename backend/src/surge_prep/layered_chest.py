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
PATCH_HALF_MM = 40.0
CORRIDOR_MIN_X_MM = -18.0
CORRIDOR_MAX_X_MM = 18.0
CELL_WIDTH_MM = 3.0
CORRIDOR_HALF_WIDTH_MM = 6.0
MINIMUM_REACTION_N = 0.3
MAXIMUM_REACTION_N = 1.2
CUT_THRESHOLD_MM = 0.65
REACTION_PER_MM = 0.38
CONTACT_THRESHOLD_MM = 0.15
RIB_HALF_WIDTH_MM = 4.0
RIB_CENTRES_MM = (-18.0, 18.0)
RIB_TOP_Y_MM = -10.0
JITTER_HOLD_MS = 180
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
    "subcutaneous": -8.0,
    "intercostal-muscle": -13.0,
    "pleura": -16.0,
}
LAYER_TOPS_MM = {
    "skin": 0.0,
    "subcutaneous": -3.0,
    "intercostal-muscle": -8.0,
    "pleura": -13.0,
}
LAYER_STAGES = {
    "skin": "skin-incision",
    "subcutaneous": "blunt-dissection",
    "intercostal-muscle": "blunt-dissection",
    "pleura": "pleural-entry",
}


def cell_count() -> int:
    return round((CORRIDOR_MAX_X_MM - CORRIDOR_MIN_X_MM) / CELL_WIDTH_MM)


def corridor_cell(x_mm: float) -> int:
    value = int((x_mm - CORRIDOR_MIN_X_MM) / CELL_WIDTH_MM)
    return max(0, min(cell_count() - 1, value))


def in_patch(x_mm: float, z_mm: float) -> bool:
    return abs(x_mm) <= PATCH_HALF_MM and abs(z_mm) <= PATCH_HALF_MM


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
        # Five 3 mm cells form a sufficient localized tract while preserving
        # intact tissue at both corridor ends.
        return self.progress >= 0.4


@dataclass
class LayeredChestState:
    layers: dict[str, LayerOpening] = field(
        default_factory=lambda: {name: LayerOpening() for name in LAYER_ORDER}
    )
    tube_placed: bool = False
    layer_violations: int = 0
    outside_corridor_contacts: int = 0

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
        self, sample: ToolSample, contact: bool, penetration_mm: float, reaction_n: float
    ) -> tuple[str, list[str], bool]:
        events: list[str] = []
        blocked_by_rib = hits_protected_rib(
            sample.position_mm.x, sample.position_mm.y, sample.position_mm.z
        )
        if (
            sample.tool_id == "chest-tube"
            and self.layers["pleura"].opened
            and in_corridor(sample.position_mm.x, sample.position_mm.z)
            and sample.position_mm.y <= -10.0
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

        active = self._active_layer_for_depth(penetration_mm)
        required = LAYER_TOOLS[active]
        if sample.tool_id != required:
            self.layer_violations += 1
            events.append("layer-violation")
            return "contact", events, blocked_by_rib

        if not self._predecessors_open(active):
            self.layer_violations += 1
            events.append("layer-violation")
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

    def _active_layer_for_depth(self, penetration_mm: float) -> str:
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
            incision_depth_mm=max(layer.depth_mm for layer in self.layers.values()),
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
        meshes.append(self._wound_mesh())
        return meshes

    def _layer_mesh(
        self, layer_id: str, sample: ToolSample, deformation_mm: float, contact: bool
    ) -> DeformableMeshState:
        opening = self.layers[layer_id]
        y_mm = LAYER_TOPS_MM[layer_id]
        x_columns = cell_count() + 1
        z_rows = [-32.0, -18.0, -12.0, -6.0, -0.15, 0.15, 6.0, 12.0, 18.0, 32.0]
        vertices: list[Vector3] = []
        for row, original_z in enumerate(z_rows):
            for column in range(x_columns):
                x = CORRIDOR_MIN_X_MM + column * CELL_WIDTH_MM
                z = original_z
                bordering = [index for index in (column - 1, column) if index in opening.cut_cells]
                local_depth = max((opening.depths_mm.get(index, 0.0) for index in bordering), default=0.0)
                if row in (4, 5) and bordering:
                    opening_width = min(6.0, 1.5 + local_depth * 0.8)
                    z = (-1 if row == 4 else 1) * opening_width
                distance_squared = (x - sample.position_mm.x) ** 2 + (original_z - sample.position_mm.z) ** 2
                contact_deformation = (
                    -deformation_mm * math.exp(-distance_squared / 80.0) if contact else 0.0
                )
                seam_drop = -local_depth * 0.55 if row in (4, 5) else 0.0
                vertices.append(Vector3(x=x, y=y_mm + contact_deformation + seam_drop, z=z))

        triangles: list[int] = []
        for row in range(len(z_rows) - 1):
            for column in range(cell_count()):
                if row == 4 and column in opening.cut_cells:
                    continue
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

    def _wound_mesh(self) -> DeformableMeshState:
        vertices: list[Vector3] = []
        triangles: list[int] = []
        skin = self.layers["skin"]
        for cell in sorted(skin.cut_cells):
            x0 = CORRIDOR_MIN_X_MM + cell * CELL_WIDTH_MM
            x1 = x0 + CELL_WIDTH_MM
            depth = max(layer.depths_mm.get(cell, 0.0) for layer in self.layers.values())
            half_width = min(5.8, 1.35 + depth * 0.75)
            base = len(vertices)
            y_mm = SURFACE_Y_MM - depth * 0.8 - 0.2
            vertices.extend([
                Vector3(x=x0, y=y_mm, z=-half_width),
                Vector3(x=x1, y=y_mm, z=-half_width),
                Vector3(x=x1, y=y_mm, z=half_width),
                Vector3(x=x0, y=y_mm, z=half_width),
            ])
            triangles.extend([base, base + 2, base + 1, base, base + 3, base + 2])
        return DeformableMeshState(
            object_id="wound-channel",
            topology_revision=self.topology_revision,
            vertices_mm=vertices,
            triangle_indices=triangles,
        )


def tool_state_from_pose(
    sample: ToolSample, contact: bool, penetration_mm: float, reaction_n: float, contact_point: Vector3
) -> ToolState:
    return ToolState(
        position_mm=sample.position_mm,
        orientation=sample.orientation,
        force_n=reaction_n,
        contact=contact,
        contact_point_mm=contact_point if contact else None,
        contact_normal=Vector3(x=0, y=1, z=0) if contact else None,
        reaction_force_n=reaction_n,
        penetration_depth_mm=penetration_mm,
    )
