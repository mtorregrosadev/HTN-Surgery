from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from collections import defaultdict
from dataclasses import dataclass
import importlib.util
import math
from pathlib import Path
from types import ModuleType
from typing import Any

from .layered_chest import (
    LAYER_TOPS_MM,
    LayeredChestState,
    PUNCTURE_DEPTH_MM,
    RIB_TOP_Y_MM,
    exposed_surface_y_mm,
    hits_protected_rib,
    in_carvable_field,
    in_patch,
    pose_contact,
    tool_state_from_pose,
)
from .models import DeformableMeshState, SimulationSnapshot, ToolSample, Vector3


class Simulator(ABC):
    name: str

    async def start(self) -> None:
        pass

    async def close(self) -> None:
        pass

    @abstractmethod
    async def begin_session(self, session_id: str) -> None: ...

    @abstractmethod
    async def step(self, sample: ToolSample) -> SimulationSnapshot: ...

    async def end_session(self, session_id: str) -> None:
        pass


def _snapshot(
    sample: ToolSample,
    tick: int,
    step_ms: int,
    backend: str,
    chest: LayeredChestState,
    events: list[str],
    contact: bool,
    penetration_mm: float,
    reaction_n: float,
    contact_point,
    deformation_mm: float,
    mode: str,
    degraded: bool = False,
    deformable_meshes: list[DeformableMeshState] | None = None,
) -> SimulationSnapshot:
    stage = "degraded" if degraded else chest.procedure_stage(contact)
    return SimulationSnapshot(
        session_id=sample.session_id,
        tick=tick,
        simulation_time_ms=tick * step_ms,
        simulation_backend=backend,
        procedure_stage=stage,
        session_degraded=degraded,
        tool=tool_state_from_pose(sample, contact, penetration_mm, reaction_n, contact_point),
        tissue=chest.tissue_state(deformation_mm, mode),
        deformable_meshes=(
            deformable_meshes
            if deformable_meshes is not None
            else chest.meshes(sample, deformation_mm, contact)
        ),
        events=events,
    )


class MemorySimulator(Simulator):
    """Deterministic development adapter matching the native SOFA contract."""

    name = "memory-development-only"

    def __init__(self, step_ms: int = 10) -> None:
        self.step_ms = step_ms
        self.ticks: dict[str, int] = defaultdict(int)
        self.contacts: dict[str, bool] = defaultdict(bool)
        self.chests: dict[str, LayeredChestState] = {}

    async def begin_session(self, session_id: str) -> None:
        self.ticks[session_id] = 0
        self.contacts[session_id] = False
        self.chests[session_id] = LayeredChestState()

    async def step(self, sample: ToolSample) -> SimulationSnapshot:
        self.ticks[sample.session_id] += 1
        tick = self.ticks[sample.session_id]
        chest = self.chests[sample.session_id]
        surface = exposed_surface_y_mm(chest, sample.position_mm.x, sample.position_mm.z)
        contact, penetration, reaction, contact_point = pose_contact(sample, surface)
        previous_contact = self.contacts[sample.session_id]
        events: list[str] = []
        if contact and not previous_contact:
            events.append("first-contact")
            events.append("contact-start")
        elif previous_contact and not contact:
            events.append("contact-end")
        self.contacts[sample.session_id] = contact
        if contact:
            chest.track_blade_path(sample, penetration, surface)
        mode, chest_events, blocked = chest.update(sample, contact, penetration, reaction)
        events.extend(chest_events)
        if blocked:
            events.append("protected-anatomy")
        deformation = min(penetration, 12.0) if contact else 0.0
        return _snapshot(
            sample, tick, self.step_ms, self.name, chest, events,
            contact, penetration, reaction, contact_point, deformation, mode,
        )

    async def end_session(self, session_id: str) -> None:
        self.ticks.pop(session_id, None)
        self.contacts.pop(session_id, None)
        self.chests.pop(session_id, None)


@dataclass
class SofaSessionState:
    root: Any
    tick: int
    previous_contact: bool
    initial_tetrahedra: dict[str, int]
    previous_tetrahedra: dict[str, int]
    applied_tool_pose: list[float]
    carving_layer: str | None


class SofaSimulator(Simulator):
    """In-process bridge to a native SOFA Python scene."""

    name = "sofa-native"
    # Two 10 ms implicit steps let contact settle while keeping the local loop
    # interactive at showcase input rates.
    network_substeps = 3
    layer_nodes = {
        "skin": "skin",
        "subcutaneous": "subcutaneous",
        "intercostal-muscle": "muscle",
        "pleura": "pleura",
    }
    carving_managers = {
        "skin": "carveSkin",
        "subcutaneous": "carveSubcutaneous",
        "intercostal-muscle": "carveMuscle",
        "pleura": "carvePleura",
    }

    def __init__(self, scene_path: str, step_ms: int = 10) -> None:
        self.scene_path = Path(scene_path).resolve()
        self.step_ms = step_ms
        self._lock = asyncio.Lock()
        self._sofa: Any = None
        self._simulation: Any = None
        self._scene_module: ModuleType | None = None
        self._sessions: dict[str, SofaSessionState] = {}
        self._chests: dict[str, LayeredChestState] = {}

    async def start(self) -> None:
        try:
            import Sofa
            import Sofa.Simulation
            import SofaRuntime
        except ImportError as error:
            raise RuntimeError(
                "Native SOFA backend selected but SofaPython3 is unavailable. "
                "Install official SOFA v26.06 and run scripts/check-native-sofa.py"
            ) from error
        try:
            if SofaRuntime.importPlugin("SofaCarving") is False:
                raise RuntimeError("SofaCarving plugin was not found")
        except Exception as error:
            raise RuntimeError(
                "SofaCarving is required for the showcase topology path. "
                "Use the official SOFA v26.06 package and re-run scripts/check-native-sofa.py"
            ) from error
        if not self.scene_path.is_file():
            raise RuntimeError(f"SOFA scene not found: {self.scene_path}")
        spec = importlib.util.spec_from_file_location("surge_prep_sofa_scene", self.scene_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load SOFA scene: {self.scene_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self._sofa = Sofa
        self._simulation = Sofa.Simulation
        self._scene_module = module

    async def close(self) -> None:
        async with self._lock:
            for state in self._sessions.values():
                self._simulation.unload(state.root)
            self._sessions.clear()

    async def begin_session(self, session_id: str) -> None:
        if self._scene_module is None:
            raise RuntimeError("SOFA simulator has not been started")
        async with self._lock:
            root = self._sofa.Core.Node(f"session_{session_id}")
            self._scene_module.createScene(root, carving_active=False)
            self._simulation.init(root)
            tetrahedra = {
                layer_id: len(self._layer(root, layer_id).topology.tetrahedra.value)
                for layer_id in self.layer_nodes
            }
            initial_y = self._scene_module.chest_surface_y_mm(0.0, 0.0) + 18.0
            self._sessions[session_id] = SofaSessionState(
                root=root,
                tick=0,
                previous_contact=False,
                initial_tetrahedra=tetrahedra,
                previous_tetrahedra=tetrahedra.copy(),
                applied_tool_pose=[0.0, initial_y, 0.0, 0.0, 0.0, 0.0, 1.0],
                carving_layer=None,
            )
            self._chests[session_id] = LayeredChestState()

    async def step(self, sample: ToolSample) -> SimulationSnapshot:
        async with self._lock:
            state = self._sessions.get(sample.session_id)
            if state is None:
                raise RuntimeError("SOFA session has not been initialized")
            root = state.root
            chest = self._chests[sample.session_id]
            surface_y = self._scene_module.body_surface_y_mm(
                sample.position_mm.x, sample.position_mm.z
            )
            blocked_by_rib = hits_protected_rib(
                sample.position_mm.x, sample.position_mm.y, sample.position_mm.z
            )
            effective_y_mm = (
                max(sample.position_mm.y, RIB_TOP_Y_MM)
                if blocked_by_rib
                else sample.position_mm.y
            )
            target_pose = [
                sample.position_mm.x, effective_y_mm + surface_y, sample.position_mm.z,
                sample.orientation.qx, sample.orientation.qy,
                sample.orientation.qz, sample.orientation.qw,
            ]
            # SOFA's standard pipeline is discrete. Interpolate the complete
            # tracked blade pose over fixed substeps rather than moving a
            # spherical proxy or silently clamping the user's instrument.
            previous_pose = state.applied_tool_pose
            planar_travel_mm = math.hypot(
                target_pose[0] - previous_pose[0], target_pose[2] - previous_pose[2]
            )
            reactions: list[float] = []
            contacts: list[bool] = []
            deformations: list[float] = []
            self._set_carving(root, None)
            for substep in range(self.network_substeps):
                fraction = (substep + 1) / self.network_substeps
                proxy_pose = [
                    previous_pose[index]
                    + (target_pose[index] - previous_pose[index]) * fraction
                    for index in range(3)
                ] + target_pose[3:]
                self._apply_tool(root, sample, [proxy_pose])
                self._simulation.animate(root, 0.01)
                reaction_at_step = self._reaction_force_n(root)
                contact_at_step = self._has_contact(root, reaction_at_step)
                reactions.append(reaction_at_step)
                contacts.append(contact_at_step)
                deformations.append(self._maximum_deformation_mm(root))
            state.applied_tool_pose = target_pose
            reaction = max(reactions, default=0.0)
            if not math.isfinite(reaction):
                reaction = 0.0
            contact = any(contacts) and math.isfinite(reaction)
            deformation = max(
                (value for value in deformations if math.isfinite(value)),
                default=0.0,
            )
            active_layer = chest.current_layer()
            contact_point = self._nearest_surface_point(root, sample, active_layer)
            penetration = max(0.0, -effective_y_mm) if contact else 0.0
            events: list[str] = []
            if contact and not state.previous_contact:
                events.append("first-contact")
                events.append("contact-start")
            elif state.previous_contact and not contact:
                events.append("contact-end")
            mode, chest_events, blocked = chest.update(
                sample, contact, penetration, reaction, advance_opening=False
            )
            events.extend(chest_events)
            if blocked:
                events.append("protected-anatomy")
            carving_step = 0
            if contact and not blocked:
                chest.track_blade_path(sample, penetration, surface_y)
            if self._should_carve(
                sample,
                chest,
                contact,
                reaction,
                planar_travel_mm,
                penetration,
                active_layer,
            ) and not blocked:
                state.carving_layer = active_layer
                layer = self._layer(root, active_layer)
                tetrahedra_before_carving = len(layer.topology.tetrahedra.value)
                self._set_carving(root, active_layer)
                for extra_depth_mm in (0.25, 0.5, 0.75):
                    carving_pose = target_pose.copy()
                    carving_pose[1] -= extra_depth_mm
                    self._apply_tool(root, sample, [carving_pose])
                    self._simulation.animate(root, 0.01)
                self._set_carving(root, None)
                carving_step = 3
                if len(layer.topology.tetrahedra.value) < tetrahedra_before_carving:
                    events.extend(chest.record_sofa_cut(active_layer, sample, penetration))
                    mode = "cutting"
            state.tick += self.network_substeps + carving_step
            for layer_id in self.layer_nodes:
                tetrahedra = len(self._layer(root, layer_id).topology.tetrahedra.value)
                if tetrahedra < state.previous_tetrahedra[layer_id]:
                    events.extend(["topology-changed", f"topology-changed:{layer_id}"])
                state.previous_tetrahedra[layer_id] = tetrahedra
            state.previous_contact = contact
            proxy_sample = sample.model_copy(
                update={
                    "position_mm": Vector3(
                        x=target_pose[0], y=target_pose[1], z=target_pose[2]
                    )
                }
            )
            meshes = self._deformable_meshes(state)
            wound = chest.wound_mesh(self._scene_module.chest_surface_y_mm)
            if wound.triangle_indices:
                meshes.append(wound)
            return _snapshot(
                proxy_sample, state.tick, self.step_ms, self.name, chest, events,
                contact, penetration, reaction, contact_point, deformation, mode,
                deformable_meshes=meshes,
            )

    async def end_session(self, session_id: str) -> None:
        async with self._lock:
            state = self._sessions.pop(session_id, None)
            if state is not None:
                self._simulation.unload(state.root)
            self._chests.pop(session_id, None)

    def _apply_tool(self, root: Any, sample: ToolSample, tool_pose: list) -> None:
        root.tool.dofs.position.value = tool_pose
        local_deformation = in_carvable_field(
            sample.position_mm.x, sample.position_mm.z
        )
        for layer_id in self.layer_nodes:
            surface = self._layer(root, layer_id).surface
            surface.triangles.active.value = local_deformation
            surface.points.active.value = local_deformation
        body_shell = root.getChild("bodyContactShell")
        if body_shell is not None:
            body_shell.skin.active.value = not local_deformation
        scalpel = sample.tool_id == "scalpel"
        blunt = sample.tool_id == "blunt-dissector"
        tube = sample.tool_id == "chest-tube"
        root.tool.blade.edge.active.value = scalpel
        root.tool.blade.thickness.active.value = scalpel
        root.tool.blunt.tips.active.value = blunt
        root.tool.tube.tip.active.value = tube

    @classmethod
    def _layer(cls, root: Any, layer_id: str) -> Any:
        return getattr(root.layers, cls.layer_nodes[layer_id])

    @classmethod
    def _set_carving(cls, root: Any, layer_id: str | None) -> None:
        for candidate, manager_name in cls.carving_managers.items():
            getattr(root, manager_name).active.value = candidate == layer_id

    @staticmethod
    def _reaction_force_n(root: Any) -> float:
        components = [0.0, 0.0, 0.0]
        for layer in SofaSimulator.layer_nodes:
            nodal_contact = SofaSimulator._layer(root, layer).dofs.getData("lambda").value
            for axis in range(3):
                components[axis] += sum(
                    float(force[axis])
                    for force in nodal_contact
                    if math.isfinite(float(force[axis]))
                )
        if root.getChild("bodyContactShell") is not None:
            body_contact = root.bodyContactShell.dofs.getData("lambda").value
            for axis in range(3):
                components[axis] += sum(
                    float(force[axis])
                    for force in body_contact
                    if math.isfinite(float(force[axis]))
                )
        return math.sqrt(sum(component * component for component in components))

    @staticmethod
    def _has_contact(root: Any, reaction_n: float) -> bool:
        return len(root.contactSolver.constraintForces.value) > 0

    @staticmethod
    def _should_carve(
        sample: ToolSample,
        chest: LayeredChestState,
        contact: bool,
        reaction_n: float,
        planar_travel_mm: float,
        penetration_mm: float,
        layer_id: str | None = None,
    ) -> bool:
        puncture = penetration_mm >= PUNCTURE_DEPTH_MM
        stroke = planar_travel_mm >= 0.15
        return (
            contact
            and SofaSimulator._tool_matches_layer(
                sample.tool_id, layer_id or chest.current_layer()
            )
            and in_carvable_field(sample.position_mm.x, sample.position_mm.z)
            and 0.001 <= reaction_n <= 3.0
            and (puncture or stroke)
        )

    @staticmethod
    def _tool_matches_layer(tool_id: str, layer_id: str) -> bool:
        return tool_id == {
            "skin": "scalpel",
            "subcutaneous": "blunt-dissector",
            "intercostal-muscle": "blunt-dissector",
            "pleura": "scalpel",
        }[layer_id]

    @staticmethod
    def _maximum_deformation_mm(root: Any) -> float:
        maximum_squared = 0.0
        for layer_id in SofaSimulator.layer_nodes:
            layer = SofaSimulator._layer(root, layer_id)
            current = layer.dofs.position.value
            resting = layer.dofs.rest_position.value
            for point, rest in zip(current, resting):
                squared = sum(
                    (float(point[index]) - float(rest[index])) ** 2 for index in range(3)
                )
                maximum_squared = max(maximum_squared, squared)
        return maximum_squared ** 0.5

    @classmethod
    def _nearest_surface_point(
        cls, root: Any, sample: ToolSample, layer_id: str
    ) -> Vector3:
        layer = cls._layer(root, layer_id)
        current = layer.dofs.position.value
        resting = layer.dofs.rest_position.value
        top_offset = LAYER_TOPS_MM[layer_id]
        top_indices = [
            index for index, point in enumerate(resting)
            if abs(
                float(point[1])
                - cls._scene_surface_y(root, float(point[0]), float(point[2]))
                - top_offset
            ) < 0.05
        ]
        nearest = min(
            top_indices,
            key=lambda index: (
                (float(current[index][0]) - sample.position_mm.x) ** 2
                + (float(current[index][2]) - sample.position_mm.z) ** 2
            ),
        )
        point = current[nearest]
        if not all(math.isfinite(float(value)) for value in point):
            raise RuntimeError(
                "SOFA tissue state became non-finite; stop the session and reset the scene."
            )
        return Vector3(x=float(point[0]), y=float(point[1]), z=float(point[2]))

    @staticmethod
    def _scene_surface_y(root: Any, x_mm: float, z_mm: float) -> float:
        # The fitted surface function is stored on the scene module, not the
        # graph. Importing it here would duplicate a second source of truth, so
        # recover the top rest height from the skin nodes at the same x/z.
        skin = root.layers.skin.dofs.rest_position.value
        nearest = min(
            skin,
            key=lambda point: (float(point[0]) - x_mm) ** 2 + (float(point[2]) - z_mm) ** 2,
        )
        return max(
            float(point[1])
            for point in skin
            if abs(float(point[0]) - float(nearest[0])) < 1e-4
            and abs(float(point[2]) - float(nearest[2])) < 1e-4
        )

    @classmethod
    def _deformable_meshes(cls, state: SofaSessionState) -> list[DeformableMeshState]:
        root = state.root
        meshes: list[DeformableMeshState] = []
        for layer_id in cls.layer_nodes:
            layer = cls._layer(root, layer_id)
            current = layer.dofs.position.value
            resting = layer.dofs.rest_position.value
            finite_indices = {
                index
                for index, point in enumerate(current)
                if all(math.isfinite(float(point[axis])) for axis in range(3))
            }
            boundary_indices = {
                index
                for index, point in enumerate(resting)
                if (float(point[0]) / 40.0) ** 2 + (float(point[2]) / 36.0) ** 2
                >= 0.90
            }
            surface_triangles = [
                [int(index) for index in triangle]
                for triangle in layer.surface.topology.triangles.value
                if all(int(index) in finite_indices for index in triangle)
                and not all(int(index) in boundary_indices for index in triangle)
            ]
            triangles = [index for triangle in surface_triangles for index in triangle]
            used_indices = sorted(set(triangles))
            vertices = [
                Vector3(
                    x=float(current[index][0]),
                    y=float(current[index][1]),
                    z=float(current[index][2]),
                )
                for index in used_indices
            ]
            remap = {
                original: compact
                for compact, original in enumerate(used_indices)
            }
            meshes.append(
                DeformableMeshState(
                    object_id=f"layer-{layer_id}",
                    topology_revision=(
                        1
                        + state.initial_tetrahedra[layer_id]
                        - state.previous_tetrahedra[layer_id]
                    ),
                    vertices_mm=vertices,
                    triangle_indices=[remap[index] for index in triangles],
                )
            )
        return meshes


CONTACT_THRESHOLD_FROM_FEM = 0.12
