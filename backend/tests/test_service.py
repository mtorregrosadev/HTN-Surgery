import pytest
from fastapi import HTTPException

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
    result = await service.complete_session(session.session_id)
    assert result.metrics.sample_count == 3
    assert result.metrics.peak_force_n == 2.0
    assert len(await service.replay(session.session_id)) == 3


@pytest.mark.asyncio
async def test_contact_events_follow_transitions_after_hover():
    service = TrainingService(MemoryStore(), MemorySimulator())
    calibration = await service.create_calibration(
        CalibrationCreate(device_id="esp32-1", transform=IDENTITY, rms_error_mm=0.8)
    )
    session = await service.create_session(
        SessionCreate(exercise_id="demo", calibration_id=calibration.calibration_id,
                      tool_id="stylus-1", device_id="esp32-1")
    )
    events = []
    for sequence, contact in enumerate((False, True, True, False)):
        sample = ToolSample.model_validate({
            "sessionId": session.session_id, "toolId": "stylus-1",
            "deviceId": "esp32-1", "calibrationId": calibration.calibration_id,
            "sequence": sequence, "timestampMs": sequence * 10,
            "positionMm": {"x": 1, "y": 2, "z": 3},
            "orientation": {"qx": 0, "qy": 0, "qz": 0, "qw": 1},
            "forceN": 1 if contact else 0, "contact": contact,
        })
        events.append((await service.process_sample(session.session_id, sample)).events)
    assert events == [[], ["contact-start"], [], ["contact-end"]]


@pytest.mark.asyncio
async def test_invalid_source_time_and_calibration_do_not_advance_simulation():
    store = MemoryStore()
    service = TrainingService(store, MemorySimulator())
    calibration = await service.create_calibration(
        CalibrationCreate(device_id="esp32-1", transform=IDENTITY, rms_error_mm=0.8)
    )
    session = await service.create_session(
        SessionCreate(exercise_id="demo", calibration_id=calibration.calibration_id,
                      tool_id="stylus-1", device_id="esp32-1")
    )
    base = {
        "sessionId": session.session_id, "toolId": "stylus-1",
        "deviceId": "esp32-1", "calibrationId": calibration.calibration_id,
        "sequence": 1, "timestampMs": 100,
        "positionMm": {"x": 1, "y": 2, "z": 3},
        "orientation": {"qx": 0, "qy": 0, "qz": 0, "qw": 1},
        "forceN": 0, "contact": False,
    }
    await service.process_sample(session.session_id, ToolSample.model_validate(base))
    for changes in (
        {"sequence": 1},
        {"sequence": 2, "timestampMs": 99},
        {"sequence": 2, "sourceHealthy": False},
        {"sequence": 2, "quality": 0},
    ):
        with pytest.raises(HTTPException) as error:
            await service.process_sample(
                session.session_id, ToolSample.model_validate({**base, **changes})
            )
        assert error.value.status_code == 409
    store.calibrations[calibration.calibration_id].valid = False
    with pytest.raises(HTTPException) as error:
        await service.process_sample(
            session.session_id, ToolSample.model_validate({**base, "sequence": 2})
        )
    assert error.value.status_code == 409
    assert len(await service.replay(session.session_id)) == 1
