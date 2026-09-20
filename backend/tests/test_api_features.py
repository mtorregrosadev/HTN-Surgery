"""HTTP-level tests for results, progress, coaching, spoken coaching and the optional Sentry hook."""
from __future__ import annotations

import json
import sys
import types

import httpx
import pytest
from fastapi.testclient import TestClient

from helpers import IDENTITY, make_metrics
from surge_prep.app import create_app, init_sentry
from surge_prep.coaching import ElevenLabsVoice, OfflineCoach, OpenAICoach, VoiceUnavailable
from surge_prep.config import Settings
from surge_prep.simulation import MemorySimulator
from surge_prep.store import MemoryStore


def sample_payload(session_id, calibration_id, sequence, y, force, contact):
    return {
        "contractVersion": "1.1", "sessionId": session_id, "toolId": "scalpel", "deviceId": "esp32-1",
        "calibrationId": calibration_id, "sequence": sequence, "timestampMs": sequence * 33,
        "positionMm": {"x": sequence * 0.4, "y": y, "z": 0},
        "orientation": {"qx": 0, "qy": 0, "qz": 0, "qw": 1},
        "forceN": force, "contact": contact, "inputMode": "calibrated-hardware", "forceMeasurementValid": True,
    }


def start_session(client):
    cal = client.post("/v1/calibrations", json={"deviceId": "esp32-1", "transform": IDENTITY, "rmsErrorMm": 0.5}).json()
    session = client.post("/v1/sessions", json={
        "exerciseId": "chest-tube-access-demo", "calibrationId": cal["calibrationId"],
        "toolId": "scalpel", "deviceId": "esp32-1"}).json()
    return session["sessionId"], cal["calibrationId"]


def finish_session(client, samples=10):
    session_id, cal_id = start_session(client)
    for i in range(samples):
        pressed = i >= 3
        response = client.post(f"/v1/sessions/{session_id}/samples", json=sample_payload(
            session_id, cal_id, i, -2.0 if pressed else 6.0, 0.8 if pressed else 0.0, pressed))
        assert response.status_code == 200
    complete = client.post(f"/v1/sessions/{session_id}/complete")
    assert complete.status_code == 200
    return session_id, complete.json()


class StubVoice(ElevenLabsVoice):
    def __init__(self, audio=b"MP3DATA", fail=None):
        super().__init__("key")
        self.audio, self.fail, self.spoken = audio, fail, []

    async def synthesize(self, text):
        self.spoken.append(text)
        if self.fail:
            raise VoiceUnavailable(self.fail)
        return self.audio


@pytest.fixture
def client():
    with TestClient(create_app(MemoryStore(), MemorySimulator(), coach=OfflineCoach(), voice=ElevenLabsVoice(None))) as c:
        yield c


# ---------------------------------------------------------------- results and listing


def test_result_endpoint_returns_the_scorecard(client):
    session_id, completed = finish_session(client)
    body = client.get(f"/v1/sessions/{session_id}/result").json()
    assert body["sessionId"] == session_id
    assert body["metrics"] == completed["metrics"]
    assert {"completedAt", "deviceId", "exerciseId"} <= set(body)


def test_result_for_unknown_session_is_404(client):
    assert client.get("/v1/sessions/missing/result").status_code == 404


def test_result_for_active_session_is_409(client):
    session_id, _ = start_session(client)
    assert client.get(f"/v1/sessions/{session_id}/result").status_code == 409


def test_sessions_list_newest_first_and_validates_limit(client):
    ids = [start_session(client)[0] for _ in range(3)]
    listed = client.get("/v1/sessions", params={"limit": 2}).json()
    assert [s["sessionId"] for s in listed] == [ids[2], ids[1]]
    assert client.get("/v1/sessions", params={"limit": 0}).status_code == 422
    assert client.get("/v1/sessions", params={"limit": 999}).status_code == 422


def test_progress_endpoint_across_attempts(client):
    for _ in range(3):
        finish_session(client)
    body = client.get("/v1/progress").json()
    assert body["attempts"] == 3
    assert len(body["trend"]) == 3
    assert body["weakestComponent"]
    assert client.get("/v1/progress", params={"deviceId": "esp32-1"}).json()["attempts"] == 3
    assert client.get("/v1/progress", params={"deviceId": "someone-else"}).json()["attempts"] == 0
    assert client.get("/v1/progress", params={"limit": 0}).status_code == 422


def test_progress_with_no_attempts(client):
    assert client.get("/v1/progress").json()["attempts"] == 0


# ---------------------------------------------------------------- coaching


def test_coaching_after_a_completed_session(client):
    session_id, completed = finish_session(client)
    response = client.post(f"/v1/sessions/{session_id}/coaching")
    assert response.status_code == 200
    body = response.json()
    assert body["sessionId"] == session_id
    assert body["provider"] == "offline"
    assert body["scorePercent"] == pytest.approx(completed["metrics"]["illustrativeScorePercent"], abs=0.1)
    assert len(body["findings"]) == 9
    assert body["nextDrill"] and body["spoken"]


def test_coaching_before_completion_is_409(client):
    session_id, _ = start_session(client)
    assert client.post(f"/v1/sessions/{session_id}/coaching").status_code == 409


def test_coaching_unknown_session_is_404(client):
    assert client.post("/v1/sessions/nope/coaching").status_code == 404


def test_coaching_uses_the_configured_provider():
    seen = {}

    def handler(request):
        seen["called"] = True
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(
            {"summary": "Custom voice from the model.", "spoken": "Custom voice from the model."})}}]})

    coach = OpenAICoach("k", http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with TestClient(create_app(MemoryStore(), MemorySimulator(), coach=coach)) as c:
        session_id, _ = finish_session(c)
        body = c.post(f"/v1/sessions/{session_id}/coaching").json()
    assert seen["called"] and body["provider"] == "openai"
    assert body["summary"] == "Custom voice from the model."


def test_coaching_falls_back_when_the_provider_is_down():
    def handler(request):
        return httpx.Response(503, text="down")

    coach = OpenAICoach("k", http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with TestClient(create_app(MemoryStore(), MemorySimulator(), coach=coach)) as c:
        session_id, _ = finish_session(c)
        response = c.post(f"/v1/sessions/{session_id}/coaching")
    assert response.status_code == 200
    assert response.json()["provider"] == "offline-fallback"


# ---------------------------------------------------------------- spoken coaching


def test_audio_needs_a_voice_key(client):
    session_id, _ = finish_session(client)
    response = client.post(f"/v1/sessions/{session_id}/coaching/audio")
    assert response.status_code == 503
    assert "ELEVENLABS_API_KEY" in response.json()["detail"]


def test_audio_success_returns_mpeg_of_the_spoken_text():
    voice = StubVoice(audio=b"\xff\xfbAUDIO")
    with TestClient(create_app(MemoryStore(), MemorySimulator(), coach=OfflineCoach(), voice=voice)) as c:
        session_id, _ = finish_session(c)
        response = c.post(f"/v1/sessions/{session_id}/coaching/audio")
        report = c.post(f"/v1/sessions/{session_id}/coaching").json()
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.content == b"\xff\xfbAUDIO"
    assert voice.spoken == [report["spoken"]]


def test_audio_upstream_failure_is_502():
    voice = StubVoice(fail="ElevenLabs returned 429")
    with TestClient(create_app(MemoryStore(), MemorySimulator(), coach=OfflineCoach(), voice=voice)) as c:
        session_id, _ = finish_session(c)
        response = c.post(f"/v1/sessions/{session_id}/coaching/audio")
    assert response.status_code == 502
    assert "429" in response.json()["detail"]


def test_audio_before_completion_is_409():
    with TestClient(create_app(MemoryStore(), MemorySimulator(), coach=OfflineCoach(), voice=StubVoice())) as c:
        session_id, _ = start_session(c)
        assert c.post(f"/v1/sessions/{session_id}/coaching/audio").status_code == 409


# ---------------------------------------------------------------- existing behaviour still intact


def test_health_reports_persistence_and_simulation(client):
    assert client.get("/health").json() == {
        "status": "ok", "persistence": "memory", "simulation": "memory-development-only"}


def test_complete_response_shape_is_unchanged(client):
    _, completed = finish_session(client)
    assert set(completed) == {"session", "metrics"}
    assert completed["session"]["status"] == "completed"


# ---------------------------------------------------------------- settings


def test_settings_defaults_have_no_keys(monkeypatch):
    for name in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "ELEVENLABS_API_KEY", "SENTRY_DSN",
                 "SURGE_PREP_COACH_PROVIDER", "SURGE_PREP_OPENAI_MODEL"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings.from_environment()
    assert settings.openai_api_key is None and settings.gemini_api_key is None
    assert settings.elevenlabs_api_key is None and settings.sentry_dsn is None
    assert settings.coach_provider == "auto"


def test_settings_read_the_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-1")
    monkeypatch.setenv("GOOGLE_API_KEY", "g-1")
    monkeypatch.setenv("SURGE_PREP_OPENAI_MODEL", "my-model")
    monkeypatch.setenv("SURGE_PREP_COACH_PROVIDER", "gemini")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-1")
    monkeypatch.setenv("SURGE_PREP_ELEVENLABS_VOICE_ID", "voice-9")
    settings = Settings.from_environment()
    assert (settings.openai_api_key, settings.gemini_api_key) == ("sk-1", "g-1")
    assert settings.openai_model == "my-model" and settings.coach_provider == "gemini"
    assert (settings.elevenlabs_api_key, settings.elevenlabs_voice_id) == ("el-1", "voice-9")


def test_blank_keys_count_as_unset(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    assert Settings.from_environment().openai_api_key is None


def test_create_app_builds_the_coach_from_settings(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-live")
    monkeypatch.setenv("SURGE_PREP_COACH_PROVIDER", "auto")
    app = create_app(MemoryStore(), MemorySimulator())
    with TestClient(app) as c:
        assert c.get("/health").status_code == 200        # app boots with a key present (no calls made)


# ---------------------------------------------------------------- sentry hook


def sentry_settings(dsn):
    return Settings(mongodb_uri=None, mongodb_database="d", simulation_backend="memory",
                    sofa_scene_path="x", sentry_dsn=dsn)


def test_sentry_is_off_without_a_dsn():
    assert init_sentry(sentry_settings(None)) is False


def test_sentry_is_skipped_when_the_sdk_is_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "sentry_sdk", None)      # makes `import sentry_sdk` raise ImportError
    assert init_sentry(sentry_settings("https://k@o0.ingest.sentry.io/1")) is False


def test_sentry_initialises_tracing_and_profiling_without_pii(monkeypatch):
    calls = {}
    fake = types.SimpleNamespace(init=lambda **kwargs: calls.update(kwargs))
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)
    assert init_sentry(sentry_settings("https://k@o0.ingest.sentry.io/1")) is True
    assert calls["dsn"] == "https://k@o0.ingest.sentry.io/1"
    assert calls["traces_sample_rate"] == 1.0 and calls["profiles_sample_rate"] == 1.0
    assert calls["send_default_pii"] is False and calls["enable_logs"] is True


def test_metrics_helper_defaults_are_valid():
    assert make_metrics().sample_count == 200
