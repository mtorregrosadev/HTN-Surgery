import pytest

from surge_prep.models import CalibrationCreate, SessionCreate, ToolSample
from surge_prep.service import TrainingService
from surge_prep.simulation import MemorySimulator
from surge_prep.store import MemoryStore


IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


@pytest.mark.asyncio
async def test_session_round_trip_and_metrics():
    service = TrainingService(MemoryStore(), MemorySimulator())
    calibration = await service.create_calibration(
        CalibrationCreate(device_id="esp32-1", transform=IDENTITY, rms_error_mm=0.8)
    )
    session = await service.create_session(
        SessionCreate(
            exercise_id="demo", calibration_id=calibration.calibration_id,
            tool_id="stylus-1", device_id="esp32-1",
        )
    )

    for sequence, force in enumerate((0.0, 1.0, 2.0)):
        snapshot = await service.process_sample(
            session.session_id,
            ToolSample.model_validate(
                {
                    "sessionId": session.session_id,
                    "toolId": "stylus-1",
                    "deviceId": "esp32-1",
                    "calibrationId": calibration.calibration_id,
                    "sequence": sequence,
                    "timestampMs": sequence * 10,
                    "positionMm": {"x": 1, "y": 2, "z": 3},
                    "orientation": {"qx": 0, "qy": 0, "qz": 0, "qw": 1},
                    "forceN": force,
                    "contact": force > 0,
                }
            ),
        )

    assert snapshot.tick == 3
    assert snapshot.tissue.deformation_mm == 3.0
    assert snapshot.deformable_meshes[0].vertices_mm[4].y == -3.0
    assert snapshot.events == []
    result = await service.complete_session(session.session_id)
    assert result.metrics.sample_count == 3
    assert result.metrics.peak_force_n == 2.0
    assert result.metrics.mean_target_offset_mm == pytest.approx(3.16227766)
    assert result.metrics.controlled_contact_percent == 50.0
    assert result.metrics.illustrative_score_percent == pytest.approx(67.09430585)
    assert len(await service.replay(session.session_id)) == 3
