import pytest
from fastapi import HTTPException

from surge_prep.models import CalibrationCreate, SessionCreate, ToolSample
from surge_prep.service import TrainingService
from surge_prep.simulation import MemorySimulator
from surge_prep.store import MemoryStore

IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def _sample(session, calibration, sequence, x, y, z, tool_id="scalpel", **extra):
    payload = {
        "contractVersion": "1.1",
        "sessionId": session.session_id,
        "toolId": tool_id,
        "deviceId": "demo",
        "calibrationId": calibration.calibration_id,
        "sequence": sequence,
        "timestampMs": sequence * 33,
        "positionMm": {"x": x, "y": y, "z": z},
        "orientation": {"qx": 0, "qy": 0, "qz": 0, "qw": 1},
        "forceN": 0,
        "contact": False,
        "inputMode": "pose-only",
        "forceMeasurementValid": False,
    }
    payload.update(extra)
    return ToolSample.model_validate(payload)


async def _session(tool_id="scalpel"):
    service = TrainingService(MemoryStore(), MemorySimulator())
    calibration = await service.create_calibration(
        CalibrationCreate(device_id="demo", transform=IDENTITY, rms_error_mm=0.1)
    )
    session = await service.create_session(
        SessionCreate(
            exercise_id="chest-tube-access-demo",
            calibration_id=calibration.calibration_id,
            tool_id=tool_id,
            device_id="demo",
        )
    )
    return service, calibration, session


@pytest.mark.asyncio
async def test_session_round_trip_and_metrics():
    service, calibration, session = await _session()
    latest = None
    for sequence, y_mm in enumerate((8.0, -1.0, -4.5)):
        latest = await service.process_sample(
            session.session_id,
            _sample(session, calibration, sequence, 1, y_mm, 3),
        )
    assert latest.tick == 3
    assert latest.simulation_backend == "memory-development-only"
    assert latest.tool.reaction_force_n > 0
    assert latest.deformable_meshes[0].object_id == "layer-skin"
    result = await service.complete_session(session.session_id)
    assert result.metrics.sample_count == 3
    assert result.metrics.peak_force_n == latest.tool.reaction_force_n
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
            "positionMm": {"x": 1, "y": -1 if contact else 2, "z": 3},
            "orientation": {"qx": 0, "qy": 0, "qz": 0, "qw": 1},
            "forceN": 1 if contact else 0, "contact": contact,
        })
        snapshot = await service.process_sample(session.session_id, sample)
        events.append([event for event in snapshot.events if event in ("contact-start", "contact-end")])
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


def test_no_contact_receives_no_illustrative_score():
    sample = ToolSample.model_validate(
        {
            "sessionId": "session-1",
            "toolId": "scalpel",
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
async def test_pose_only_force_cannot_cut_without_penetration():
    service, calibration, session = await _session()
    snapshot = await service.process_sample(
        session.session_id,
        _sample(session, calibration, 0, 0, 12, 0, forceN=4, contact=True),
    )
    assert snapshot.tool.contact is False
    assert snapshot.tissue.incision_length_mm == 0
    assert snapshot.deformable_meshes[0].topology_revision == 1


@pytest.mark.asyncio
async def test_controlled_motion_opens_skin_from_pose():
    service, calibration, session = await _session()
    latest = None
    for sequence in range(61):
        x_mm = -15.0 + sequence * 0.5
        latest = await service.process_sample(
            session.session_id,
            _sample(session, calibration, sequence, x_mm, -1.2, 0),
        )
    assert latest is not None
    assert latest.tool.contact is True
    assert latest.tool.reaction_force_n >= 0.3
    assert latest.tissue.interaction_mode == "cutting"
    assert latest.tissue.incision_length_mm >= 24
    assert latest.deformable_meshes[0].topology_revision > 1
    assert latest.deformable_meshes[0].object_id == "layer-skin"
    result = await service.complete_session(session.session_id)
    assert result.metrics.incision_length_mm == latest.tissue.incision_length_mm
    assert result.metrics.incision_progress_percent > 60


@pytest.mark.asyncio
async def test_outside_corridor_does_not_carve():
    service, calibration, session = await _session()
    latest = None
    for sequence in range(20):
        latest = await service.process_sample(
            session.session_id,
            _sample(session, calibration, sequence, -15 + sequence, -1.2, 20),
        )
    assert latest.tissue.incision_length_mm == 0
    assert "outside-corridor" in latest.events
    assert latest.deformable_meshes[0].topology_revision == 1


@pytest.mark.asyncio
async def test_muscle_does_not_open_before_skin():
    service, calibration, session = await _session("blunt-dissector")
    snapshot = await service.process_sample(
        session.session_id,
        _sample(session, calibration, 0, 0, -1.2, 0, tool_id="blunt-dissector"),
    )
    assert snapshot.tissue.layers[2].opening_progress == 0
    assert "layer-violation" in snapshot.events


@pytest.mark.asyncio
async def test_showcase_tools_can_be_switched():
    service, calibration, session = await _session("scalpel")
    snapshot = await service.process_sample(
        session.session_id,
        _sample(session, calibration, 0, 0, 10, 0, tool_id="blunt-dissector"),
    )
    assert snapshot.tick == 1
