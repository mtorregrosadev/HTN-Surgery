from __future__ import annotations

import math
import time

from fastapi import HTTPException, status

from .models import (
    Calibration,
    CalibrationCreate,
    Session,
    SessionCreate,
    SessionMetrics,
    SessionResult,
    SessionStatus,
    SimulationSnapshot,
    ToolSample,
    new_id,
    utc_now,
)
from .simulation import Simulator
from .store import Store


class TrainingService:
    def __init__(self, store: Store, simulator: Simulator) -> None:
        self.store = store
        self.simulator = simulator

    async def create_calibration(self, request: CalibrationCreate) -> Calibration:
        calibration = Calibration(
            **request.model_dump(),
            calibration_id=new_id("cal"),
            version=1,
            created_at=utc_now(),
        )
        await self.store.save_calibration(calibration)
        return calibration

    async def create_session(self, request: SessionCreate) -> Session:
        calibration = await self.store.get_calibration(request.calibration_id)
        if calibration is None or not calibration.valid:
            raise HTTPException(status.HTTP_409_CONFLICT, "A valid calibration is required")
        if calibration.device_id != request.device_id:
            raise HTTPException(status.HTTP_409_CONFLICT, "Calibration belongs to another device")
        session = Session(
            **request.model_dump(),
            session_id=new_id("session"),
            status=SessionStatus.active,
            created_at=utc_now(),
        )
        await self.simulator.begin_session(session.session_id)
        await self.store.save_session(session)
        return session

    async def process_sample(self, session_id: str, sample: ToolSample) -> SimulationSnapshot:
        session = await self.require_session(session_id)
        if session.status != SessionStatus.active:
            raise HTTPException(status.HTTP_409_CONFLICT, "Session is not active")
        if sample.session_id != session_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Payload sessionId does not match path")
        if sample.tool_id != session.tool_id or sample.device_id != session.device_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Tool or device does not match session")
        if sample.calibration_id != session.calibration_id:
            raise HTTPException(status.HTTP_409_CONFLICT, "Calibration does not match session")
        if session.last_sequence is not None and sample.sequence <= session.last_sequence:
            raise HTTPException(status.HTTP_409_CONFLICT, "Sample sequence must increase")
        sample.received_at_ms = int(time.time() * 1000)
        snapshot = await self.simulator.step(sample)
        session.last_sequence = sample.sequence
        await self.store.save_sample(sample)
        await self.store.save_snapshot(snapshot)
        await self.store.save_session(session)
        return snapshot

    async def complete_session(self, session_id: str) -> SessionResult:
        session = await self.require_session(session_id)
        if session.status != SessionStatus.active:
            raise HTTPException(status.HTTP_409_CONFLICT, "Session is not active")
        samples = await self.store.list_samples(session_id)
        session.status = SessionStatus.completed
        session.completed_at = utc_now()
        await self.simulator.end_session(session_id)
        await self.store.save_session(session)
        return SessionResult(session=session, metrics=self.calculate_metrics(samples))

    async def replay(self, session_id: str) -> list[SimulationSnapshot]:
        await self.require_session(session_id)
        return await self.store.list_snapshots(session_id)

    async def require_session(self, session_id: str) -> Session:
        session = await self.store.get_session(session_id)
        if session is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
        return session

    @staticmethod
    def calculate_metrics(samples: list[ToolSample]) -> SessionMetrics:
        if not samples:
            return SessionMetrics(
                sample_count=0, duration_ms=0, contact_time_ms=0,
                peak_force_n=0, mean_contact_force_n=0,
                mean_target_offset_mm=0, peak_target_offset_mm=0,
                force_consistency_n=0, controlled_contact_percent=0,
                illustrative_score_percent=0,
            )
        contact_samples = [sample for sample in samples if sample.contact]
        intervals = [
            max(0, current.timestamp_ms - previous.timestamp_ms)
            for previous, current in zip(samples, samples[1:])
            if previous.contact
        ]
        forces = [sample.force_n for sample in contact_samples]
        offsets = [
            math.sqrt(sample.position_mm.x**2 + sample.position_mm.z**2)
            for sample in contact_samples
        ]
        mean_force = sum(forces) / len(forces) if forces else 0
        force_consistency = (
            math.sqrt(sum((force - mean_force) ** 2 for force in forces) / len(forces))
            if forces else 0
        )
        controlled = [force for force in forces if 0.3 <= force <= 1.2]
        controlled_percent = len(controlled) / len(forces) * 100 if forces else 0
        mean_offset = sum(offsets) / len(offsets) if offsets else 0
        targeting_score = max(0.0, 100.0 - mean_offset * 5.0)
        consistency_score = max(0.0, 100.0 - force_consistency * 100.0)
        illustrative_score = (
            targeting_score * 0.5 + controlled_percent * 0.3 + consistency_score * 0.2
            if forces else 0.0
        )
        return SessionMetrics(
            sample_count=len(samples),
            duration_ms=max(0, samples[-1].timestamp_ms - samples[0].timestamp_ms),
            contact_time_ms=sum(intervals),
            peak_force_n=max(forces, default=0),
            mean_contact_force_n=mean_force,
            mean_target_offset_mm=mean_offset,
            peak_target_offset_mm=max(offsets, default=0),
            force_consistency_n=force_consistency,
            controlled_contact_percent=controlled_percent,
            illustrative_score_percent=illustrative_score,
        )
