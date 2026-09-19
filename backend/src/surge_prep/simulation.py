from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from collections import defaultdict
import importlib.util
import math
from pathlib import Path
from types import ModuleType
from typing import Any
from dataclasses import dataclass, field

from .models import (
    DeformableMeshState,
    SimulationSnapshot,
    TissueState,
    ToolSample,
    ToolState,
    Vector3,
)


@dataclass
class IncisionState:
    """Stable, predefined incision corridor shared by development and SOFA adapters."""

    minimum_x_mm: float = -18.0
    maximum_x_mm: float = 18.0
    cell_width_mm: float = 3.0
    corridor_half_width_mm: float = 6.0
    minimum_force_n: float = 0.3
    maximum_force_n: float = 1.2
    maximum_depth_mm: float = 6.0
    cut_threshold_mm: float = 0.65
    depths_mm: dict[int, float] = field(default_factory=dict)
    cut_cells: set[int] = field(default_factory=set)
    previous_x_mm: float | None = None

    @property
    def cell_count(self) -> int:
        return round((self.maximum_x_mm - self.minimum_x_mm) / self.cell_width_mm)

    @property
    def topology_revision(self) -> int:
        return 1 + len(self.cut_cells)

    @property
    def length_mm(self) -> float:
        return len(self.cut_cells) * self.cell_width_mm

    @property
    def depth_mm(self) -> float:
        return max(self.depths_mm.values(), default=0.0)

    @property
    def progress(self) -> float:
        return len(self.cut_cells) / self.cell_count

    def update(self, sample: ToolSample) -> tuple[str, list[str]]:
        if not sample.contact:
            self.previous_x_mm = None
            return "approach", []
        if sample.force_n < self.minimum_force_n:
            self.previous_x_mm = None
            return "low-force", []
        if sample.force_n > self.maximum_force_n:
            self.previous_x_mm = None
            return "excessive-force", ["excessive-force"]
        if (
            abs(sample.position_mm.z) > self.corridor_half_width_mm
            or sample.position_mm.x < self.minimum_x_mm
            or sample.position_mm.x > self.maximum_x_mm
        ):
            self.previous_x_mm = None
            return "outside-target", ["outside-target"]

        previous_cut_cells = len(self.cut_cells)
        start_x = sample.position_mm.x if self.previous_x_mm is None else self.previous_x_mm
        start_cell = self._cell(start_x)
        end_cell = self._cell(sample.position_mm.x)
        crossed_cells = list(range(min(start_cell, end_cell), max(start_cell, end_cell) + 1))
        travel_mm = (
            0.0 if self.previous_x_mm is None
            else abs(sample.position_mm.x - self.previous_x_mm)
        )
        depth_increment = (
            max(0.0, sample.force_n - 0.2) * 0.4 * travel_mm / len(crossed_cells)
        )
        for cell in crossed_cells:
            depth = self.depths_mm.get(cell, 0.0)
            depth += depth_increment
            self.depths_mm[cell] = min(depth, self.maximum_depth_mm)
            if self.depths_mm[cell] >= self.cut_threshold_mm:
                self.cut_cells.add(cell)
        self.previous_x_mm = sample.position_mm.x

        events: list[str] = []
        if len(self.cut_cells) > previous_cut_cells:
            events.append("incision-start" if previous_cut_cells == 0 else "incision-extended")
        return ("cutting" if self.cut_cells else "contact"), events

    def surface_mesh(
        self, sample: ToolSample, deformation_mm: float, surface_y_mm: float = 14.0
    ) -> DeformableMeshState:
        x_columns = self.cell_count + 1
        z_rows = [-18.0, -12.0, -6.0, -0.15, 0.15, 6.0, 12.0, 18.0]
        vertices: list[Vector3] = []
        for row, original_z in enumerate(z_rows):
            for column in range(x_columns):
                x = self.minimum_x_mm + column * self.cell_width_mm
                z = original_z
                bordering = [index for index in (column - 1, column) if index in self.cut_cells]
                local_depth = max((self.depths_mm.get(index, 0.0) for index in bordering), default=0.0)
                if row in (3, 4) and bordering:
                    opening = min(4.5, 0.5 + local_depth * 0.7)
                    z = (-1 if row == 3 else 1) * opening
                distance_squared = (
                    (x - sample.position_mm.x) ** 2 + (original_z - sample.position_mm.z) ** 2
                )
                contact_deformation = (
                    -deformation_mm * math.exp(-distance_squared / 80.0) if sample.contact else 0.0
                )
                seam_drop = -local_depth * 0.55 if row in (3, 4) else 0.0
                vertices.append(
                    Vector3(x=x, y=surface_y_mm + contact_deformation + seam_drop, z=z)
                )

        triangles: list[int] = []
        for row in range(len(z_rows) - 1):
            for column in range(self.cell_count):
                if row == 3 and column in self.cut_cells:
                    continue
                a = row * x_columns + column
                b = a + 1
                c = (row + 1) * x_columns + column + 1
                d = c - 1
                triangles.extend([a, b, c, a, c, d])
        return DeformableMeshState(
            object_id="training-membrane",
            topology_revision=self.topology_revision,
            vertices_mm=vertices,
            triangle_indices=triangles,
        )

    def wound_mesh(self, surface_y_mm: float = 0.0) -> DeformableMeshState:
        vertices: list[Vector3] = []
        triangles: list[int] = []
        for cell in sorted(self.cut_cells):
            x0 = self.minimum_x_mm + cell * self.cell_width_mm
            x1 = x0 + self.cell_width_mm
            depth = self.depths_mm.get(cell, self.cut_threshold_mm)
            half_width = min(4.2, 0.45 + depth * 0.65)
            base = len(vertices)
            vertices.extend([
                Vector3(x=x0, y=surface_y_mm - depth * 0.6 - 0.2, z=-half_width),
                Vector3(x=x1, y=surface_y_mm - depth * 0.6 - 0.2, z=-half_width),
                Vector3(x=x1, y=surface_y_mm - depth * 0.6 - 0.2, z=half_width),
                Vector3(x=x0, y=surface_y_mm - depth * 0.6 - 0.2, z=half_width),
            ])
            triangles.extend([base, base + 1, base + 2, base, base + 2, base + 3])
        return DeformableMeshState(
            object_id="incision-channel",
            topology_revision=self.topology_revision,
            vertices_mm=vertices,
            triangle_indices=triangles,
        )

    def tissue_state(self, deformation_mm: float, mode: str) -> TissueState:
        return TissueState(
            deformation_mm=deformation_mm,
            incision_progress=self.progress,
            incision_length_mm=self.length_mm,
            incision_depth_mm=self.depth_mm,
            interaction_mode=mode,
        )

    def _cell(self, x_mm: float) -> int:
        value = int((x_mm - self.minimum_x_mm) / self.cell_width_mm)
        return max(0, min(self.cell_count - 1, value))


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


class MemorySimulator(Simulator):
    """Deterministic development adapter matching the SOFA bridge contract."""

    name = "memory-development-only"

    def __init__(self, step_ms: int = 10) -> None:
        self.step_ms = step_ms
        self.ticks: dict[str, int] = defaultdict(int)
        self.contacts: dict[str, bool] = defaultdict(bool)
        self.incisions: dict[str, IncisionState] = {}

    async def begin_session(self, session_id: str) -> None:
        self.ticks[session_id] = 0
        self.contacts[session_id] = False
        self.incisions[session_id] = IncisionState()

    async def step(self, sample: ToolSample) -> SimulationSnapshot:
        self.ticks[sample.session_id] += 1
        tick = self.ticks[sample.session_id]
        deformation = min(sample.force_n * 1.5, 12.0) if sample.contact else 0.0
        previous_contact = self.contacts[sample.session_id]
        events: list[str] = []
        if sample.contact and not previous_contact:
            events.append("contact-start")
        elif previous_contact and not sample.contact:
            events.append("contact-end")
        self.contacts[sample.session_id] = sample.contact
        incision = self.incisions[sample.session_id]
        mode, incision_events = incision.update(sample)
        events.extend(incision_events)
        return SimulationSnapshot(
            session_id=sample.session_id,
            tick=tick,
            simulation_time_ms=tick * self.step_ms,
            tool=ToolState(
                position_mm=sample.position_mm,
                orientation=sample.orientation,
                force_n=sample.force_n,
                contact=sample.contact,
            ),
            tissue=incision.tissue_state(deformation, mode),
            deformable_meshes=[
                incision.surface_mesh(sample, deformation),
                incision.wound_mesh(surface_y_mm=13.8),
            ],
            events=events,
        )

    async def end_session(self, session_id: str) -> None:
        self.ticks.pop(session_id, None)
        self.contacts.pop(session_id, None)
        self.incisions.pop(session_id, None)


class SofaSimulator(Simulator):
    """In-process bridge to a SOFA Python scene.

    SOFA is imported lazily so API and contract development can run without the
    native simulator installed. A lock serializes access because SOFA scene
    mutation is not thread-safe.
    """

    name = "sofa"

    def __init__(self, scene_path: str, step_ms: int = 10) -> None:
        self.scene_path = Path(scene_path).resolve()
        self.step_ms = step_ms
        self._lock = asyncio.Lock()
        self._sofa: Any = None
        self._simulation: Any = None
        self._scene_module: ModuleType | None = None
        self._sessions: dict[str, tuple[Any, int, bool]] = {}
        self._incisions: dict[str, IncisionState] = {}

    async def start(self) -> None:
        try:
            import Sofa
            import Sofa.Simulation
        except ImportError as error:
            raise RuntimeError(
                "SOFA backend selected but SofaPython3 is unavailable; run with "
                "SURGE_PREP_SIMULATION_BACKEND=memory for API-only development"
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
            for root, _, _ in self._sessions.values():
                self._simulation.unload(root)
            self._sessions.clear()

    async def begin_session(self, session_id: str) -> None:
        if self._scene_module is None:
            raise RuntimeError("SOFA simulator has not been started")
        async with self._lock:
            root = self._sofa.Core.Node(f"session_{session_id}")
            self._scene_module.createScene(root)
            self._simulation.init(root)
            self._sessions[session_id] = (root, 0, False)
            self._incisions[session_id] = IncisionState()

    async def step(self, sample: ToolSample) -> SimulationSnapshot:
        async with self._lock:
            state = self._sessions.get(sample.session_id)
            if state is None:
                raise RuntimeError("SOFA session has not been initialized")
            root, tick, previous_contact = state
            tool_pose = [[
                sample.position_mm.x, sample.position_mm.y, sample.position_mm.z,
                sample.orientation.qx, sample.orientation.qy,
                sample.orientation.qz, sample.orientation.qw,
            ]]
            root.tool.dofs.position.value = tool_pose
            self._simulation.animate(root, self.step_ms / 1000)
            tick += 1
            deformation = self._maximum_deformation_mm(root)
            incision = self._incisions[sample.session_id]
            mode, incision_events = incision.update(sample)
            surface = self._surface_mesh(root, incision)
            events: list[str] = []
            if sample.contact and not previous_contact:
                events.append("contact-start")
            elif previous_contact and not sample.contact:
                events.append("contact-end")
            events.extend(incision_events)
            self._sessions[sample.session_id] = (root, tick, sample.contact)
            return SimulationSnapshot(
                session_id=sample.session_id,
                tick=tick,
                simulation_time_ms=tick * self.step_ms,
                tool=ToolState(
                    position_mm=sample.position_mm,
                    orientation=sample.orientation,
                    force_n=sample.force_n,
                    contact=sample.contact,
                ),
                tissue=incision.tissue_state(deformation, mode),
                deformable_meshes=[surface, incision.wound_mesh(surface_y_mm=11.7)],
                events=events,
            )

    async def end_session(self, session_id: str) -> None:
        async with self._lock:
            state = self._sessions.pop(session_id, None)
            if state is not None:
                self._simulation.unload(state[0])
            self._incisions.pop(session_id, None)

    @staticmethod
    def _maximum_deformation_mm(root: Any) -> float:
        current = root.tissue.dofs.position.value
        resting = root.tissue.dofs.rest_position.value
        maximum_squared = 0.0
        for point, rest in zip(current, resting):
            squared = sum((float(point[index]) - float(rest[index])) ** 2 for index in range(3))
            maximum_squared = max(maximum_squared, squared)
        return maximum_squared**0.5

    @staticmethod
    def _surface_mesh(root: Any, incision: IncisionState) -> DeformableMeshState:
        positions = root.tissue.surface.dofs.position.value
        quads = root.tissue.surface.topology.quads.value
        triangles: list[int] = []
        for quad in quads:
            a, b, c, d = (int(index) for index in quad)
            quad_positions = [positions[index] for index in (a, b, c, d)]
            center_x = sum(float(point[0]) for point in quad_positions) / 4
            minimum_z = min(float(point[2]) for point in quad_positions)
            maximum_z = max(float(point[2]) for point in quad_positions)
            cell = incision._cell(center_x)
            if minimum_z <= 0 <= maximum_z and cell in incision.cut_cells:
                continue
            triangles.extend([a, b, c, a, c, d])
        return DeformableMeshState(
            object_id="training-pad",
            topology_revision=incision.topology_revision,
            vertices_mm=[
                Vector3(x=float(point[0]), y=float(point[1]), z=float(point[2]))
                for point in positions
            ],
            triangle_indices=triangles,
        )
