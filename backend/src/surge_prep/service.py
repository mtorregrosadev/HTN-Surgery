from __future__ import annotations

import math
import time

from fastapi import HTTPException, status

from .layered_chest import DEGRADE_TIMEOUT_MS, instrument_angle_deg
from .models import (
    SHOWCASE_TOOL_IDS,
    Calibration,
    CalibrationCreate,
    ProgressSummary,
    ResultRecord,
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
from .progress import summarize_progress
from .simulation import Simulator
from .store import Store


class TrainingService:
    def __init__(self, store: Store, simulator: Simulator) -> None:
        self.store = store
        self.simulator = simulator
        self._last_valid: dict[str, ToolSample] = {}
        self._frozen: dict[str, bool] = {}

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

    def _tool_allowed(self, session: Session, sample: ToolSample) -> bool:
        if sample.tool_id == session.tool_id:
            return True
        return session.tool_id in SHOWCASE_TOOL_IDS and sample.tool_id in SHOWCASE_TOOL_IDS

    async def process_sample(self, session_id: str, sample: ToolSample) -> SimulationSnapshot:
        session = await self.require_session(session_id)
        if session.status != SessionStatus.active:
            raise HTTPException(status.HTTP_409_CONFLICT, "Session is not active")
        if sample.session_id != session_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Payload sessionId does not match path")
        if sample.device_id != session.device_id or not self._tool_allowed(session, sample):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Tool or device does not match session")
        if sample.calibration_id != session.calibration_id:
            raise HTTPException(status.HTTP_409_CONFLICT, "Calibration does not match session")
        if session.last_sequence is not None and sample.sequence <= session.last_sequence:
            raise HTTPException(status.HTTP_409_CONFLICT, "Sample sequence must increase")

        last = self._last_valid.get(session_id)
        unhealthy = not sample.source_healthy or sample.quality < 0.2
        degraded = False
        recovered = False
        was_frozen = self._frozen.get(session_id, False)
        gap = 0
        if last is not None:
            gap = sample.timestamp_ms - last.timestamp_ms
            if gap > DEGRADE_TIMEOUT_MS:
                degraded = True
                self._frozen[session_id] = True
        if unhealthy and last is not None and not self._frozen.get(session_id):
            sample = last.model_copy(update={"sequence": sample.sequence, "timestamp_ms": sample.timestamp_ms})
        elif self._frozen.get(session_id) and last is not None:
            if was_frozen and not unhealthy and gap <= DEGRADE_TIMEOUT_MS:
                self._frozen[session_id] = False
                degraded = False
                recovered = True
            else:
                sample = last.model_copy(update={"sequence": sample.sequence, "timestamp_ms": sample.timestamp_ms})
                degraded = True

        sample.received_at_ms = int(time.time() * 1000)
        snapshot = await self.simulator.step(sample)
        if degraded:
            snapshot.session_degraded = True
            snapshot.procedure_stage = "degraded"
            if "session-degraded" not in snapshot.events:
                snapshot.events = [*snapshot.events, "session-degraded"]
        elif recovered:
            snapshot.events = [*snapshot.events, "session-recovered"]
        if not unhealthy:
            self._last_valid[session_id] = sample
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
        snapshots = await self.store.list_snapshots(session_id)
        session.status = SessionStatus.completed
        session.completed_at = utc_now()
        await self.simulator.end_session(session_id)
        self._last_valid.pop(session_id, None)
        self._frozen.pop(session_id, None)
        await self.store.save_session(session)
        metrics = self.calculate_metrics(samples, snapshots)
        await self.store.save_result(ResultRecord(
            session_id=session.session_id, exercise_id=session.exercise_id, device_id=session.device_id,
            tool_id=session.tool_id, completed_at=session.completed_at, metrics=metrics,
        ))
        return SessionResult(session=session, metrics=metrics)

    async def get_result(self, session_id: str) -> ResultRecord:
        """The stored scorecard. Older sessions completed before results were stored are re-scored from their data."""
        session = await self.require_session(session_id)
        record = await self.store.get_result(session_id)
        if record is not None:
            return record
        if session.status != SessionStatus.completed:
            raise HTTPException(status.HTTP_409_CONFLICT, "Session is not completed yet")
        samples = await self.store.list_samples(session_id)
        snapshots = await self.store.list_snapshots(session_id)
        record = ResultRecord(
            session_id=session.session_id, exercise_id=session.exercise_id, device_id=session.device_id,
            tool_id=session.tool_id, completed_at=session.completed_at or utc_now(),
            metrics=self.calculate_metrics(samples, snapshots),
        )
        await self.store.save_result(record)
        return record

    async def progress(self, device_id: str | None = None, limit: int = 50) -> ProgressSummary:
        return summarize_progress(await self.store.list_results(device_id, limit))

    async def list_sessions(self, limit: int = 20) -> list[Session]:
        return await self.store.list_sessions(limit)

    async def replay(self, session_id: str) -> list[SimulationSnapshot]:
        await self.require_session(session_id)
        return await self.store.list_snapshots(session_id)

    async def require_session(self, session_id: str) -> Session:
        session = await self.store.get_session(session_id)
        if session is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
        return session

    @staticmethod
    def calculate_metrics(
        samples: list[ToolSample], snapshots: list[SimulationSnapshot] | None = None
    ) -> SessionMetrics:
        snapshots = snapshots or []
        incision_length = max(
            (snapshot.tissue.incision_length_mm for snapshot in snapshots), default=0.0
        )
        incision_depth = max(
            (snapshot.tissue.incision_depth_mm for snapshot in snapshots), default=0.0
        )
        incision_progress = max(
            (snapshot.tissue.incision_progress for snapshot in snapshots), default=0.0
        )
        outside_corridor = sum(
            1 for snapshot in snapshots if "outside-corridor" in snapshot.events
        )
        layer_violations = sum(
            1 for snapshot in snapshots if "layer-violation" in snapshot.events
        )
        tube_complete = any(
            snapshot.procedure_stage == "complete" or "session-completed" in snapshot.events
            for snapshot in snapshots
        )
        contact_snapshots = [snapshot for snapshot in snapshots if snapshot.tool.contact]
        reactions = [snapshot.tool.reaction_force_n for snapshot in contact_snapshots]
        if not reactions:
            reactions = [
                sample.force_n for sample in samples
                if sample.contact or sample.force_measurement_valid
            ]
        angles = [instrument_angle_deg(sample) for sample in samples] if samples else []
        empty = SessionMetrics(
            sample_count=len(samples), duration_ms=0, contact_time_ms=0,
            peak_force_n=0, mean_contact_force_n=0,
            mean_target_offset_mm=0, peak_target_offset_mm=0,
            force_consistency_n=0, controlled_contact_percent=0,
            illustrative_score_percent=0,
            incision_length_mm=incision_length,
            max_incision_depth_mm=incision_depth,
            incision_progress_percent=incision_progress * 100,
            mean_instrument_angle_deg=sum(angles) / len(angles) if angles else 0,
            mean_reaction_force_n=sum(reactions) / len(reactions) if reactions else 0,
            outside_corridor_contacts=outside_corridor,
            layer_violations=layer_violations,
            tube_placement_complete=tube_complete,
        )
        if not samples:
            return empty

        pose_only = all(sample.input_mode == "pose-only" for sample in samples)
        if pose_only:
            positions = [snapshot.tool.position_mm for snapshot in contact_snapshots]
        else:
            positions = [sample.position_mm for sample in samples if sample.contact]
        contact_time_ms = 0
        if snapshots:
            for previous, current in zip(snapshots, snapshots[1:]):
                if previous.tool.contact:
                    contact_time_ms += max(0, current.simulation_time_ms - previous.simulation_time_ms)
        else:
            for previous, current in zip(samples, samples[1:]):
                if previous.contact:
                    contact_time_ms += max(0, current.timestamp_ms - previous.timestamp_ms)

        offsets = [math.sqrt(position.x ** 2 + position.z ** 2) for position in positions]
        mean_force = sum(reactions) / len(reactions) if reactions else 0
        force_consistency = (
            math.sqrt(sum((force - mean_force) ** 2 for force in reactions) / len(reactions))
            if reactions else 0
        )
        controlled = [force for force in reactions if 0.3 <= force <= 1.2]
        controlled_percent = len(controlled) / len(reactions) * 100 if reactions else 0
        mean_offset = sum(offsets) / len(offsets) if offsets else 0
        mean_angle = sum(angles) / len(angles) if angles else 0
        targeting_score = max(0.0, 100.0 - mean_offset * 5.0)
        angle_score = max(0.0, 100.0 - mean_angle)
        consistency_score = max(0.0, 100.0 - force_consistency * 100.0)
        incision_score = min(100.0, incision_progress * 100.0)
        corridor_score = max(0.0, 100.0 - outside_corridor * 8.0)
        layer_score = max(0.0, 100.0 - layer_violations * 12.0)
        duration_ms = max(0, samples[-1].timestamp_ms - samples[0].timestamp_ms)
        time_score = max(0.0, 100.0 - max(0, duration_ms - 90_000) / 1000.0)
        tube_score = 100.0 if tube_complete else 0.0
        scored = bool(reactions or incision_progress > 0)
        illustrative_score = (
            targeting_score * 0.22
            + angle_score * 0.10
            + controlled_percent * 0.16
            + consistency_score * 0.10
            + incision_score * 0.12
            + corridor_score * 0.10
            + layer_score * 0.10
            + time_score * 0.05
            + tube_score * 0.05
            if scored else 0.0
        )
        return SessionMetrics(
            sample_count=len(samples),
            duration_ms=duration_ms,
            contact_time_ms=contact_time_ms,
            peak_force_n=max(reactions, default=0),
            mean_contact_force_n=mean_force,
            mean_target_offset_mm=mean_offset,
            peak_target_offset_mm=max(offsets, default=0),
            force_consistency_n=force_consistency,
            controlled_contact_percent=controlled_percent,
            illustrative_score_percent=illustrative_score,
            incision_length_mm=incision_length,
            max_incision_depth_mm=incision_depth,
            incision_progress_percent=incision_progress * 100,
            mean_instrument_angle_deg=mean_angle,
            mean_reaction_force_n=mean_force,
            outside_corridor_contacts=outside_corridor,
            layer_violations=layer_violations,
            tube_placement_complete=tube_complete,
        )
