"""Shared helpers for the coaching/results tests."""
from __future__ import annotations

import asyncio

from surge_prep.models import CalibrationCreate, SessionCreate, SessionMetrics, ToolSample
from surge_prep.service import TrainingService
from surge_prep.simulation import MemorySimulator
from surge_prep.store import MemoryStore

IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def run(coro):
    return asyncio.run(coro)


def make_metrics(**overrides) -> SessionMetrics:
    """A SessionMetrics with sensible 'good run' defaults; override any field."""
    values = dict(
        sample_count=200, duration_ms=60_000, contact_time_ms=30_000, peak_force_n=1.0,
        mean_contact_force_n=0.7, mean_target_offset_mm=2.0, peak_target_offset_mm=5.0,
        force_consistency_n=0.1, controlled_contact_percent=90.0, illustrative_score_percent=80.0,
        incision_length_mm=30.0, max_incision_depth_mm=6.0, incision_progress_percent=90.0,
        mean_instrument_angle_deg=10.0, mean_reaction_force_n=0.7, outside_corridor_contacts=0,
        layer_violations=0, tube_placement_complete=True,
    )
    values.update(overrides)
    return SessionMetrics(**values)


def sample(session, calibration, sequence, x, y, z, *, force=0.0, contact=False, tool="scalpel",
           hardware=True):
    return ToolSample.model_validate({
        "contractVersion": "1.1", "sessionId": session.session_id, "toolId": tool, "deviceId": "demo",
        "calibrationId": calibration.calibration_id, "sequence": sequence, "timestampMs": sequence * 33,
        "positionMm": {"x": x, "y": y, "z": z},
        "orientation": {"qx": 0, "qy": 0, "qz": 0, "qw": 1},
        "forceN": force, "contact": contact,
        "inputMode": "calibrated-hardware" if hardware else "pose-only",
        "forceMeasurementValid": hardware,
    })


async def completed_session(service: TrainingService, device="demo", samples=12, force=0.8):
    """Create a session, stream some pressing samples through the simulator and complete it."""
    calibration = await service.create_calibration(
        CalibrationCreate(device_id=device, transform=IDENTITY, rms_error_mm=0.1)
    )
    session = await service.create_session(SessionCreate(
        exercise_id="chest-tube-access-demo", calibration_id=calibration.calibration_id,
        tool_id="scalpel", device_id=device,
    ))
    for i in range(samples):
        pressed = i >= 3
        await service.process_sample(session.session_id, sample(
            session, calibration, i, i * 0.5, -2.0 if pressed else 6.0, 0.0,
            force=force if pressed else 0.0, contact=pressed,
        ))
    return session, await service.complete_session(session.session_id)


def fresh_service() -> TrainingService:
    return TrainingService(MemoryStore(), MemorySimulator())
