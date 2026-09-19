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
    assert snapshot.deformable_meshes[0].object_id == "training-membrane"
    assert min(vertex.y for vertex in snapshot.deformable_meshes[0].vertices_mm) < 11.5
    assert max(vertex.y for vertex in snapshot.deformable_meshes[0].vertices_mm) <= 14.0
    assert snapshot.events == ["excessive-force"]
    result = await service.complete_session(session.session_id)
    assert result.metrics.sample_count == 3
    assert result.metrics.peak_force_n == 2.0
    assert result.metrics.mean_target_offset_mm == pytest.approx(3.16227766)
    assert result.metrics.controlled_contact_percent == 50.0
    assert result.metrics.illustrative_score_percent == pytest.approx(67.09430585)
    assert len(await service.replay(session.session_id)) == 3


def test_no_contact_receives_no_illustrative_score():
    sample = ToolSample.model_validate(
        {
            "sessionId": "session-1",
            "toolId": "stylus-1",
            "deviceId": "esp32-1",
            "calibrationId": "cal-1",
            "sequence": 0,
            "timestampMs": 0,
            "positionMm": {"x": 0, "y": 10, "z": 0},
            "orientation": {"qx": 0, "qy": 0, "qz": 0, "qw": 1},
            "forceN": 0,
            "contact": False,
        }
    )

    metrics = TrainingService.calculate_metrics([sample])

    assert metrics.illustrative_score_percent == 0


@pytest.mark.asyncio
async def test_controlled_motion_opens_an_incision_and_records_metrics():
    service = TrainingService(MemoryStore(), MemorySimulator())
    calibration = await service.create_calibration(
        CalibrationCreate(device_id="demo", transform=IDENTITY, rms_error_mm=0.1)
    )
    session = await service.create_session(
        SessionCreate(
            exercise_id="chest-tube-access-demo",
            calibration_id=calibration.calibration_id,
            tool_id="blunt-training-blade",
            device_id="demo",
        )
    )

    latest = None
    for sequence in range(61):
        x_mm = -15.0 + sequence * 0.5
        latest = await service.process_sample(
            session.session_id,
            ToolSample.model_validate(
                {
                    "sessionId": session.session_id,
                    "toolId": "blunt-training-blade",
                    "deviceId": "demo",
                    "calibrationId": calibration.calibration_id,
                    "sequence": sequence,
                    "timestampMs": sequence * 33,
                    "positionMm": {"x": x_mm, "y": 14.5, "z": 0},
                    "orientation": {"qx": 0, "qy": 0, "qz": 0, "qw": 1},
                    "forceN": 0.75,
                    "contact": True,
                }
            ),
        )

    assert latest is not None
    assert latest.tissue.interaction_mode == "cutting"
    assert latest.tissue.incision_length_mm >= 24
    assert latest.tissue.incision_depth_mm >= 0.65
    assert latest.deformable_meshes[0].topology_revision > 1
    assert latest.deformable_meshes[1].object_id == "incision-channel"
    assert latest.deformable_meshes[1].triangle_indices

    result = await service.complete_session(session.session_id)
    assert result.metrics.incision_length_mm == latest.tissue.incision_length_mm
    assert result.metrics.max_incision_depth_mm == latest.tissue.incision_depth_mm
    assert result.metrics.incision_progress_percent > 60
