from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from collections import defaultdict
import importlib.util
import math
from pathlib import Path
from types import ModuleType
from typing import Any

from .models import (
    DeformableMeshState,
    SimulationSnapshot,
    TissueState,
    ToolSample,
    ToolState,
    Vector3,
)


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

    async def begin_session(self, session_id: str) -> None:
        self.ticks[session_id] = 0
        self.contacts[session_id] = False

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
            tissue=TissueState(deformation_mm=deformation),
            deformable_meshes=[self._training_pad_mesh(deformation)],
            events=events,
        )

    async def end_session(self, session_id: str) -> None:
        self.ticks.pop(session_id, None)
        self.contacts.pop(session_id, None)

    @staticmethod
    def _training_pad_mesh(deformation_mm: float) -> DeformableMeshState:
        segments = 32
        radius_mm = 21.0
        vertices = [Vector3(x=0.0, y=-deformation_mm, z=0.0)]
        vertices.extend(
            Vector3(
                x=math.cos(index * math.tau / segments) * radius_mm,
                y=0.0,
                z=math.sin(index * math.tau / segments) * radius_mm,
            )
            for index in range(segments)
        )
        triangles = [
            vertex
            for index in range(segments)
            for vertex in (0, index + 1, (index + 1) % segments + 1)
        ]
        return DeformableMeshState(
            object_id="training-membrane",
            topology_revision=1,
            vertices_mm=vertices,
            triangle_indices=triangles,
        )


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
            surface = self._surface_mesh(root)
            events: list[str] = []
            if sample.contact and not previous_contact:
                events.append("contact-start")
            elif previous_contact and not sample.contact:
                events.append("contact-end")
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
                tissue=TissueState(deformation_mm=deformation),
                deformable_meshes=[surface],
                events=events,
            )

    async def end_session(self, session_id: str) -> None:
        async with self._lock:
            state = self._sessions.pop(session_id, None)
            if state is not None:
                self._simulation.unload(state[0])

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
    def _surface_mesh(root: Any) -> DeformableMeshState:
        positions = root.tissue.surface.dofs.position.value
        quads = root.tissue.surface.topology.quads.value
        triangles: list[int] = []
        for quad in quads:
            a, b, c, d = (int(index) for index in quad)
            triangles.extend([a, b, c, a, c, d])
        return DeformableMeshState(
            object_id="training-pad",
            topology_revision=1,
            vertices_mm=[
                Vector3(x=float(point[0]), y=float(point[1]), z=float(point[2]))
                for point in positions
            ],
            triangle_indices=triangles,
        )
