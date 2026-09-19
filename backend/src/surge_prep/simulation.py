from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict

from .models import SimulationSnapshot, TissueState, ToolSample, ToolState


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

    async def begin_session(self, session_id: str) -> None:
        self.ticks[session_id] = 0

    async def step(self, sample: ToolSample) -> SimulationSnapshot:
        self.ticks[sample.session_id] += 1
        tick = self.ticks[sample.session_id]
        deformation = min(sample.force_n * 1.5, 12.0) if sample.contact else 0.0
        events = ["contact-start"] if sample.contact and tick == 1 else []
        return SimulationSnapshot(
            session_id=sample.session_id,
            tick=tick,
            simulation_time_ms=tick * self.step_ms,
            tool=ToolState(
                position_mm=sample.position_mm,
                force_n=sample.force_n,
                contact=sample.contact,
            ),
            tissue=TissueState(deformation_mm=deformation),
            events=events,
        )

    async def end_session(self, session_id: str) -> None:
        self.ticks.pop(session_id, None)

