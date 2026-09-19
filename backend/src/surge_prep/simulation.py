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
    LayeredChestState,
    exposed_surface_y_mm,
    in_corridor,
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
    initial_tetrahedra: int
    previous_tetrahedra: int


class SofaSimulator(Simulator):
    """In-process bridge to a native SOFA Python scene."""

    name = "sofa-native"
    # Two 10 ms implicit steps let contact settle while keeping the local loop
    # interactive at showcase input rates.
    network_substeps = 2

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
            tetrahedra = len(root.tissue.topology.tetrahedra.value)
            self._sessions[session_id] = SofaSessionState(
                root=root,
                tick=0,
                previous_contact=False,
                initial_tetrahedra=tetrahedra,
                previous_tetrahedra=tetrahedra,
            )
            self._chests[session_id] = LayeredChestState()

    async def step(self, sample: ToolSample) -> SimulationSnapshot:
        async with self._lock:
            state = self._sessions.get(sample.session_id)
            if state is None:
                raise RuntimeError("SOFA session has not been initialized")
            root = state.root
            chest = self._chests[sample.session_id]
            tool_pose = [[
                sample.position_mm.x, sample.position_mm.y, sample.position_mm.z,
                sample.orientation.qx, sample.orientation.qy,
                sample.orientation.qz, sample.orientation.qw,
            ]]
            self._apply_tool(root, sample, tool_pose)
            root.carvingManager.active.value = False
            for _ in range(self.network_substeps - 1):
                self._simulation.animate(root, 0.01)
            preliminary_reaction = self._reaction_force_n(root)
            preliminary_contact = self._has_contact(root, preliminary_reaction)
            root.carvingManager.active.value = self._should_carve(
                sample, chest, preliminary_contact, preliminary_reaction
            )
            self._simulation.animate(root, 0.01)
            root.carvingManager.active.value = False
            state.tick += self.network_substeps
            reaction = self._reaction_force_n(root)
            if not math.isfinite(reaction):
                raise RuntimeError(
                    "SOFA contact solver became non-finite; stop the session and reset the tool."
                )
            contact = self._has_contact(root, reaction)
            deformation = self._maximum_deformation_mm(root)
            contact_point = self._nearest_surface_point(root, sample)
            penetration = (
                max(0.0, self._tool_radius_mm(sample.tool_id) - sample.position_mm.y)
                if contact
                else 0.0
            )
            events: list[str] = []
            if contact and not state.previous_contact:
                events.append("first-contact")
                events.append("contact-start")
            elif state.previous_contact and not contact:
                events.append("contact-end")
            mode, chest_events, blocked = chest.update(sample, contact, penetration, reaction)
            events.extend(chest_events)
            if blocked:
                events.append("protected-anatomy")
            tetrahedra = len(root.tissue.topology.tetrahedra.value)
            if tetrahedra < state.previous_tetrahedra:
                events.append("topology-changed")
            state.previous_tetrahedra = tetrahedra
            state.previous_contact = contact
            return _snapshot(
                sample, state.tick, self.step_ms, self.name, chest, events,
                contact, penetration, reaction, contact_point, deformation, mode,
                deformable_meshes=self._deformable_meshes(state),
            )

    async def end_session(self, session_id: str) -> None:
        async with self._lock:
            state = self._sessions.pop(session_id, None)
            if state is not None:
                self._simulation.unload(state.root)
            self._chests.pop(session_id, None)

    def _apply_tool(self, root: Any, sample: ToolSample, tool_pose: list) -> None:
        root.tool.dofs.position.value = tool_pose
        root.tool.collision.sphere.radius.value = self._tool_radius_mm(sample.tool_id)

    @staticmethod
    def _tool_radius_mm(tool_id: str) -> float:
        return {
            "scalpel": 1.6,
            "blunt-dissector": 2.4,
            "chest-tube": 3.2,
        }.get(tool_id, 2.0)

    @staticmethod
    def _reaction_force_n(root: Any) -> float:
        nodal_contact = root.tissue.dofs.getData("lambda").value
        components = [
            sum(float(force[axis]) for force in nodal_contact)
            for axis in range(3)
        ]
        return math.sqrt(sum(component * component for component in components))

    @staticmethod
    def _has_contact(root: Any, reaction_n: float) -> bool:
        return (
            reaction_n > 1e-4
            and len(root.contactSolver.constraintForces.value) > 0
        )

    @staticmethod
    def _should_carve(
        sample: ToolSample,
        chest: LayeredChestState,
        contact: bool,
        reaction_n: float,
    ) -> bool:
        layer_tool = {
            "skin": "scalpel",
            "subcutaneous": "blunt-dissector",
            "intercostal-muscle": "blunt-dissector",
            "pleura": "scalpel",
        }
        return (
            contact
            and sample.tool_id == layer_tool[chest.current_layer()]
            and in_corridor(sample.position_mm.x, sample.position_mm.z)
            and 0.12 <= reaction_n <= 1.5
        )

    @staticmethod
    def _maximum_deformation_mm(root: Any) -> float:
        current = root.tissue.dofs.position.value
        resting = root.tissue.dofs.rest_position.value
        maximum_squared = 0.0
        for point, rest in zip(current, resting):
            squared = sum((float(point[index]) - float(rest[index])) ** 2 for index in range(3))
            maximum_squared = max(maximum_squared, squared)
        return maximum_squared ** 0.5

    @staticmethod
    def _nearest_surface_point(root: Any, sample: ToolSample) -> Vector3:
        current = root.tissue.dofs.position.value
        resting = root.tissue.dofs.rest_position.value
        top_indices = [
            index for index, point in enumerate(resting)
            if float(point[1]) > -0.01
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
    def _deformable_meshes(state: SofaSessionState) -> list[DeformableMeshState]:
        root = state.root
        vertices = [
            Vector3(x=float(point[0]), y=float(point[1]), z=float(point[2]))
            for point in root.tissue.dofs.position.value
        ]
        layers: dict[str, list[int]] = {
            "skin": [],
            "subcutaneous": [],
            "intercostal-muscle": [],
            "pleura": [],
        }
        resting = root.tissue.dofs.rest_position.value
        for triangle in root.tissue.surface.topology.triangles.value:
            indices = [int(index) for index in triangle]
            rest_points = [resting[index] for index in indices]
            on_external_wall = any(
                all(
                    abs(abs(float(point[axis])) - 40.0) < 1e-4
                    for point in rest_points
                )
                for axis in (0, 2)
            ) or all(float(point[1]) < -15.9 for point in rest_points)
            if on_external_wall:
                continue
            mean_y = sum(float(resting[index][1]) for index in indices) / 3.0
            if mean_y >= -3.0:
                layer = "skin"
            elif mean_y >= -8.0:
                layer = "subcutaneous"
            elif mean_y >= -13.0:
                layer = "intercostal-muscle"
            else:
                layer = "pleura"
            layers[layer].extend(indices)
        revision = 1 + state.initial_tetrahedra - state.previous_tetrahedra
        meshes: list[DeformableMeshState] = []
        for layer, triangles in layers.items():
            used_indices = sorted(set(triangles))
            remap = {
                original: compact
                for compact, original in enumerate(used_indices)
            }
            meshes.append(
                DeformableMeshState(
                    object_id=f"layer-{layer}",
                    topology_revision=revision,
                    vertices_mm=[vertices[index] for index in used_indices],
                    triangle_indices=[remap[index] for index in triangles],
                )
            )
        return meshes


CONTACT_THRESHOLD_FROM_FEM = 0.12
