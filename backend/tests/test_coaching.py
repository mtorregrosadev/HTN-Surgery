"""Coaching: deterministic findings, the OpenAI / Gemini / offline coaches and ElevenLabs voice.

No test here touches the network: providers are exercised through httpx.MockTransport.
"""
from __future__ import annotations

import json

import httpx
import pytest

from helpers import completed_session, fresh_service, make_metrics, run
from surge_prep.coaching import (
    COMPONENTS,
    CoachReport,
    ElevenLabsVoice,
    GeminiCoach,
    OfflineCoach,
    OpenAICoach,
    VoiceUnavailable,
    build_coach,
    build_findings,
    component_scores,
    focus_of,
)

GOOD_REPLY = {
    "summary": "Nice steady run.",
    "strengths": ["Steady force", "Good angle"],
    "improvements": ["Stay in the corridor"],
    "next_drill": "Drill C: one straight line",
    "spoken": "Nice steady run. Try Drill C next.",
}


def mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------- findings


def test_component_weights_sum_to_one():
    assert sum(weight for _, _, weight, _ in COMPONENTS) == pytest.approx(1.0)


def test_component_scores_match_the_real_scorecard():
    """The per-component formulas must stay in sync with TrainingService.calculate_metrics."""
    _, result = run(_complete())
    metrics = result.metrics
    scores = component_scores(metrics)
    weights = {name: weight for name, _, weight, _ in COMPONENTS}
    weighted = sum(scores[name] * weights[name] for name in scores)
    assert weighted == pytest.approx(metrics.illustrative_score_percent, abs=0.01)


async def _complete():
    return await completed_session(fresh_service())


def test_findings_levels_follow_thresholds():
    metrics = make_metrics(controlled_contact_percent=90, outside_corridor_contacts=4, layer_violations=6)
    levels = {f.component: f.level for f in build_findings(metrics)}
    assert levels["controlled_force"] == "strong"
    assert levels["corridor"] == "fair"              # 100 - 4 * 8 = 68
    assert levels["layer_discipline"] == "weak"      # 100 - 6 * 12 = 28


def test_corridor_score_boundaries():
    assert component_scores(make_metrics(outside_corridor_contacts=0))["corridor"] == 100
    assert component_scores(make_metrics(outside_corridor_contacts=4))["corridor"] == pytest.approx(68)
    assert component_scores(make_metrics(outside_corridor_contacts=50))["corridor"] == 0


@pytest.mark.parametrize("field,value,component,expected", [
    ("mean_target_offset_mm", 0.0, "targeting", 100),
    ("mean_target_offset_mm", 10.0, "targeting", 50),
    ("mean_target_offset_mm", 100.0, "targeting", 0),
    ("mean_instrument_angle_deg", 25.0, "instrument_angle", 75),
    ("force_consistency_n", 0.2, "force_consistency", 80),
    ("force_consistency_n", 5.0, "force_consistency", 0),
    ("layer_violations", 2, "layer_discipline", 76),
    ("incision_progress_percent", 150.0, "incision", 100),
    ("duration_ms", 60_000, "time", 100),
    ("duration_ms", 130_000, "time", 60),
    ("duration_ms", 900_000, "time", 0),
    ("tube_placement_complete", False, "tube", 0),
    ("tube_placement_complete", True, "tube", 100),
])
def test_component_score_formulas(field, value, component, expected):
    assert component_scores(make_metrics(**{field: value}))[component] == pytest.approx(expected)


def test_focus_is_the_biggest_weighted_shortfall():
    # targeting is worth 22 points; tube only 5, so equal shortfalls should point at targeting
    metrics = make_metrics(mean_target_offset_mm=12.0, tube_placement_complete=False)   # 40 vs 0
    focus = focus_of(build_findings(metrics))
    # targeting: 0.22 * 60 = 13.2 points lost; tube: 0.05 * 100 = 5 points lost
    assert focus.component == "targeting"


def test_findings_note_uses_real_numbers():
    metrics = make_metrics(mean_target_offset_mm=3.4, outside_corridor_contacts=7)
    notes = {f.component: f.note for f in build_findings(metrics)}
    assert "3.4 mm" in notes["targeting"]
    assert "7 contact" in notes["corridor"]


def test_perfect_run_has_no_weak_areas_and_a_friendly_fallback():
    metrics = make_metrics(
        mean_target_offset_mm=0, controlled_contact_percent=100, incision_progress_percent=100,
        mean_instrument_angle_deg=0, force_consistency_n=0, outside_corridor_contacts=0,
        layer_violations=0, duration_ms=30_000, tube_placement_complete=True, illustrative_score_percent=100,
    )
    report = run(OfflineCoach().coach("s1", metrics))
    assert all(f.level == "strong" for f in report.findings)
    assert "Nothing stands out" in report.improvements[0]


def test_empty_run_still_produces_a_report():
    metrics = make_metrics(
        sample_count=0, duration_ms=0, contact_time_ms=0, peak_force_n=0, mean_contact_force_n=0,
        controlled_contact_percent=0, incision_progress_percent=0, tube_placement_complete=False,
        illustrative_score_percent=0, mean_instrument_angle_deg=0, mean_target_offset_mm=0,
    )
    report = run(OfflineCoach().coach(None, metrics))
    assert report.score_percent == 0
    assert report.session_id is None
    assert report.focus_component in {c[0] for c in COMPONENTS}


# ---------------------------------------------------------------- offline coach


def test_offline_report_shape_and_camel_case():
    report = run(OfflineCoach().coach("s1", make_metrics()))
    data = report.model_dump(by_alias=True, mode="json")
    assert data["provider"] == "offline"
    assert {"sessionId", "scorePercent", "nextDrill", "focusComponent", "findings", "disclaimer"} <= set(data)
    assert len(report.findings) == len(COMPONENTS)
    assert len(report.strengths) <= 3 and len(report.improvements) <= 3
    assert "Not a clinical assessment" in report.disclaimer


def test_offline_report_is_deterministic():
    metrics = make_metrics(layer_violations=3)
    a = run(OfflineCoach().coach("s1", metrics)).model_dump()
    b = run(OfflineCoach().coach("s1", metrics)).model_dump()
    assert a == b


def test_spoken_text_is_plain_sentences():
    report = run(OfflineCoach().coach("s1", make_metrics(layer_violations=5)))
    assert "\n" not in report.spoken and "*" not in report.spoken
    assert report.spoken.startswith("Training score")


# ---------------------------------------------------------------- OpenAI


def openai_reply(payload):
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})


def test_openai_success_merges_wording_but_keeps_numbers_and_focus():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return openai_reply(GOOD_REPLY)

    metrics = make_metrics(outside_corridor_contacts=6)
    coach = OpenAICoach("sk-test", "test-model", http=mock_client(handler))
    report = run(coach.coach("s1", metrics))

    assert seen["url"] == "https://api.openai.com/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-test"
    assert seen["body"]["model"] == "test-model"
    assert seen["body"]["response_format"] == {"type": "json_object"}
    system, user = seen["body"]["messages"]
    assert "never medical or clinical advice" in system["content"].lower() or "never" in system["content"].lower()
    payload = json.loads(user["content"])
    assert payload["metrics"]["outsideCorridorContacts"] == 6
    assert "sk-test" not in json.dumps(seen["body"])            # the key never goes in the prompt

    assert report.provider == "openai"
    assert report.summary == "Nice steady run."
    assert report.strengths == ["Steady force", "Good angle"]
    base = run(OfflineCoach().coach("s1", metrics))
    assert report.findings == base.findings                      # numbers come from the data, not the model
    assert report.focus_component == base.focus_component
    assert report.score_percent == base.score_percent


def test_openai_accepts_fenced_json():
    def handler(request):
        content = "```json\n" + json.dumps(GOOD_REPLY) + "\n```"
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    report = run(OpenAICoach("k", http=mock_client(handler)).coach("s1", make_metrics()))
    assert report.provider == "openai"
    assert report.next_drill == "Drill C: one straight line"


def test_openai_partial_reply_keeps_fallback_for_missing_keys():
    def handler(request):
        return openai_reply({"summary": "Only a summary."})

    metrics = make_metrics(layer_violations=4)
    report = run(OpenAICoach("k", http=mock_client(handler)).coach("s1", metrics))
    base = run(OfflineCoach().coach("s1", metrics))
    assert report.summary == "Only a summary."
    assert report.improvements == base.improvements
    assert report.next_drill == base.next_drill


@pytest.mark.parametrize("bad", [
    lambda r: httpx.Response(500, text="boom"),
    lambda r: httpx.Response(401, json={"error": "bad key"}),
    lambda r: httpx.Response(200, text="not json"),
    lambda r: httpx.Response(200, json={"unexpected": True}),
    lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "not json at all"}}]}),
])
def test_openai_failures_fall_back_to_offline(bad):
    report = run(OpenAICoach("k", http=mock_client(bad)).coach("s1", make_metrics()))
    assert report.provider == "offline-fallback"
    assert report.note and "OpenAI coaching unavailable" in report.note
    assert len(report.findings) == len(COMPONENTS)


def test_openai_network_error_falls_back():
    def handler(request):
        raise httpx.ConnectError("no route")

    report = run(OpenAICoach("k", http=mock_client(handler)).coach("s1", make_metrics()))
    assert report.provider == "offline-fallback"
    assert "ConnectError" in report.note


def test_openai_ignores_wrong_types_in_reply():
    def handler(request):
        return openai_reply({"summary": 12, "strengths": "not a list", "improvements": [1, 2], "spoken": ""})

    metrics = make_metrics()
    report = run(OpenAICoach("k", http=mock_client(handler)).coach("s1", metrics))
    base = run(OfflineCoach().coach("s1", metrics))
    assert report.provider == "openai"
    assert report.summary == base.summary
    assert report.strengths == base.strengths
    assert report.spoken == base.spoken


def test_openai_truncates_long_lists():
    def handler(request):
        return openai_reply({"strengths": ["a", "b", "c", "d", "e"]})

    report = run(OpenAICoach("k", http=mock_client(handler)).coach("s1", make_metrics()))
    assert report.strengths == ["a", "b", "c"]


# ---------------------------------------------------------------- Gemini


def gemini_reply(payload):
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]})


def test_gemini_success():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["key"] = request.headers["x-goog-api-key"]
        seen["body"] = json.loads(request.content)
        return gemini_reply(GOOD_REPLY)

    report = run(GeminiCoach("g-key", "gem-model", http=mock_client(handler)).coach("s1", make_metrics()))
    assert seen["url"].endswith("/v1beta/models/gem-model:generateContent")
    assert seen["key"] == "g-key"
    assert "key=" not in seen["url"]                              # the key is a header, not in the URL
    assert seen["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert report.provider == "gemini"
    assert report.spoken == GOOD_REPLY["spoken"]


def test_gemini_failure_falls_back():
    report = run(GeminiCoach("k", http=mock_client(lambda r: httpx.Response(429, text="slow down")))
                 .coach("s1", make_metrics()))
    assert report.provider == "offline-fallback"
    assert "Gemini coaching unavailable" in report.note


def test_gemini_empty_candidates_falls_back():
    report = run(GeminiCoach("k", http=mock_client(lambda r: httpx.Response(200, json={"candidates": []})))
                 .coach("s1", make_metrics()))
    assert report.provider == "offline-fallback"


# ---------------------------------------------------------------- provider selection


@pytest.mark.parametrize("provider,openai,gemini,expected", [
    ("auto", "o", "g", "openai"),
    ("auto", None, "g", "gemini"),
    ("auto", None, None, "offline"),
    ("openai", "o", "g", "openai"),
    ("openai", None, "g", "offline"),          # explicit provider without its key does not silently switch
    ("gemini", "o", "g", "gemini"),
    ("gemini", "o", None, "offline"),
    ("offline", "o", "g", "offline"),
    ("AUTO", "o", None, "openai"),
    ("", None, "g", "gemini"),
])
def test_build_coach_selection(provider, openai, gemini, expected):
    assert build_coach(provider, openai, gemini, "m1", "m2").name == expected


def test_build_coach_passes_models_through():
    coach = build_coach("openai", "k", None, "my-openai-model", "x")
    assert coach.model == "my-openai-model"
    assert build_coach("gemini", None, "k", "x", "my-gemini-model").model == "my-gemini-model"


# ---------------------------------------------------------------- ElevenLabs voice


def test_voice_success_sends_expected_request():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["key"] = request.headers["xi-api-key"]
        seen["accept"] = request.headers["accept"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=b"ID3fake-mp3")

    voice = ElevenLabsVoice("el-key", "voice-1", "model-x", http=mock_client(handler))
    audio = run(voice.synthesize("  Well done.  "))
    assert audio == b"ID3fake-mp3"
    assert seen["url"] == "https://api.elevenlabs.io/v1/text-to-speech/voice-1"
    assert seen["key"] == "el-key" and seen["accept"] == "audio/mpeg"
    assert seen["body"] == {"text": "Well done.", "model_id": "model-x"}


def test_voice_without_key_is_unavailable():
    voice = ElevenLabsVoice(None)
    assert not voice.available
    with pytest.raises(VoiceUnavailable, match="ELEVENLABS_API_KEY"):
        run(voice.synthesize("hello"))


def test_voice_rejects_empty_text():
    with pytest.raises(VoiceUnavailable, match="Nothing to speak"):
        run(ElevenLabsVoice("k", http=mock_client(lambda r: httpx.Response(200, content=b"x"))).synthesize("   "))


def test_voice_http_error_is_reported_without_leaking_the_key():
    voice = ElevenLabsVoice("secret-key", http=mock_client(lambda r: httpx.Response(401, json={"detail": "bad"})))
    with pytest.raises(VoiceUnavailable) as error:
        run(voice.synthesize("hello"))
    assert "401" in str(error.value)
    assert "secret-key" not in str(error.value)


def test_voice_truncates_very_long_text():
    seen = {}

    def handler(request):
        seen["len"] = len(json.loads(request.content)["text"])
        return httpx.Response(200, content=b"x")

    run(ElevenLabsVoice("k", http=mock_client(handler)).synthesize("a" * 9000))
    assert seen["len"] == 2500


def test_report_model_round_trips():
    report = run(OfflineCoach().coach("s1", make_metrics()))
    again = CoachReport.model_validate(report.model_dump(by_alias=True, mode="json"))
    assert again == report
