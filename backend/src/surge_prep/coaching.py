"""Rubric-grounded coaching and voice feedback.

Every coach starts from the same deterministic findings (one per scorecard component, using the exact
formulas and weights of `TrainingService.calculate_metrics`), so an LLM can only *phrase* what the data
already says. Providers:

* OpenAI (chat completions)       set OPENAI_API_KEY
* Google Gemini (generateContent) set GEMINI_API_KEY
* offline                         always available; also the fallback whenever a provider call fails

ElevenLabs turns the spoken summary into audio (ELEVENLABS_API_KEY).
Nothing here is medical advice: it is training feedback about the scorecard.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from pydantic import Field

from .models import ApiModel, SessionMetrics

# (id, label, weight, drill that trains it). Weights mirror the illustrative rubric.
COMPONENTS: list[tuple[str, str, float, str]] = [
    ("targeting", "Targeting", 0.22, "Stage 1: hover over the target window and check before you descend"),
    ("controlled_force", "Controlled force", 0.16, "Drill B: hit and hold each depth for two seconds"),
    ("incision", "Incision progress", 0.12, "Drill C: one straight, even line along the corridor"),
    ("instrument_angle", "Instrument angle", 0.10, "Hold the scalpel at a steady, shallow angle"),
    ("force_consistency", "Force consistency", 0.10, "Drill B, then Drill C at constant pressure"),
    ("corridor", "Staying in the corridor", 0.10, "Drill C: follow the highlighted corridor slowly"),
    ("layer_discipline", "Layer discipline", 0.10, "Repeat blunt dissection one layer at a time"),
    ("time", "Completion time", 0.05, "Only after accuracy is steady: repeat the same quality faster"),
    ("tube", "Tube placement", 0.05, "Finish the procedure: switch to the chest tube and pass it through the tract"),
]
GOOD, OK = 80.0, 55.0


class Finding(ApiModel):
    component: str
    label: str
    score: float = Field(ge=0, le=100)
    weight: float
    level: str                      # strong | fair | weak
    note: str
    drill: str


class CoachReport(ApiModel):
    session_id: str | None = None
    provider: str
    score_percent: float
    summary: str
    strengths: list[str]
    improvements: list[str]
    next_drill: str
    focus_component: str
    spoken: str
    findings: list[Finding]
    disclaimer: str = (
        "Training feedback only. Not a clinical assessment, and not a substitute for an instructor."
    )
    note: str | None = None         # e.g. why an AI provider was skipped



def component_scores(m: SessionMetrics) -> dict[str, float]:
    """Same formulas as TrainingService.calculate_metrics, exposed per component (0-100)."""
    return {
        "targeting": max(0.0, 100.0 - m.mean_target_offset_mm * 5.0),
        "controlled_force": m.controlled_contact_percent,
        "incision": min(100.0, m.incision_progress_percent),
        "instrument_angle": max(0.0, 100.0 - m.mean_instrument_angle_deg),
        "force_consistency": max(0.0, 100.0 - m.force_consistency_n * 100.0),
        "corridor": max(0.0, 100.0 - m.outside_corridor_contacts * 8.0),
        "layer_discipline": max(0.0, 100.0 - m.layer_violations * 12.0),
        "time": max(0.0, 100.0 - max(0, m.duration_ms - 90_000) / 1000.0),
        "tube": 100.0 if m.tube_placement_complete else 0.0,
    }


def _note(component: str, score: float, m: SessionMetrics) -> str:
    if component == "targeting":
        return f"Average distance from the target was {m.mean_target_offset_mm:.1f} mm."
    if component == "controlled_force":
        return f"{m.controlled_contact_percent:.0f}% of contact time was in the 0.3 to 1.2 N range (peak {m.peak_force_n:.1f} N)."
    if component == "incision":
        return f"The incision reached {m.incision_progress_percent:.0f}% of the planned corridor ({m.incision_length_mm:.0f} mm long)."
    if component == "instrument_angle":
        return f"Average instrument angle was {m.mean_instrument_angle_deg:.0f} degrees from ideal."
    if component == "force_consistency":
        return f"Force varied by {m.force_consistency_n:.2f} N around its average."
    if component == "corridor":
        return f"{m.outside_corridor_contacts} contact(s) landed outside the marked corridor."
    if component == "layer_discipline":
        return f"{m.layer_violations} layer violation(s) were recorded."
    if component == "time":
        return f"The attempt took {m.duration_ms / 1000:.0f} s."
    return "The chest tube was placed." if m.tube_placement_complete else "The chest tube was not placed."


def build_findings(m: SessionMetrics) -> list[Finding]:
    scores = component_scores(m)
    findings = []
    for component, label, weight, drill in COMPONENTS:
        score = scores[component]
        level = "strong" if score >= GOOD else "fair" if score >= OK else "weak"
        findings.append(Finding(component=component, label=label, score=round(score, 1), weight=weight,
                                level=level, note=_note(component, score, m), drill=drill))
    return findings


def focus_of(findings: list[Finding]) -> Finding:
    """The component where the most rubric points are being lost (weight x shortfall)."""
    return max(findings, key=lambda f: f.weight * (100.0 - f.score))


class Coach(Protocol):
    name: str

    async def coach(self, session_id: str | None, metrics: SessionMetrics) -> CoachReport: ...


def _base_report(session_id: str | None, metrics: SessionMetrics, provider: str) -> CoachReport:
    findings = build_findings(metrics)
    focus = focus_of(findings)
    strengths = [f"{f.label}: {f.note}" for f in findings if f.level == "strong"][:3]
    improvements = [f"{f.label}: {f.note}" for f in sorted(findings, key=lambda f: -f.weight * (100 - f.score))
                    if f.level != "strong"][:3]
    score = round(metrics.illustrative_score_percent, 1)
    if not strengths:
        strengths = ["You completed an attempt. Every run gives the system data to coach from."]
    if not improvements:
        improvements = ["Nothing stands out as weak. Repeat the run and aim for the same quality faster."]
    summary = (
        f"Training score {score:.0f}%. Your strongest area was {max(findings, key=lambda f: f.score).label.lower()}; "
        f"the biggest gain is in {focus.label.lower()}."
    )
    next_drill = focus.drill
    spoken = f"{summary} Next, {next_drill[0].lower() + next_drill[1:]}."
    return CoachReport(
        session_id=session_id, provider=provider, score_percent=score, summary=summary,
        strengths=strengths, improvements=improvements, next_drill=next_drill,
        focus_component=focus.component, spoken=spoken, findings=findings,
    )


class OfflineCoach:
    name = "offline"

    async def coach(self, session_id: str | None, metrics: SessionMetrics) -> CoachReport:
        return _base_report(session_id, metrics, self.name)


SYSTEM_PROMPT = (
    "You are a supportive surgical-skills training coach for a SIMULATED chest-tube practice tool. "
    "You are given a scorecard as JSON. Only use the numbers provided; never invent measurements. "
    "Give training feedback, never medical or clinical advice. Be specific, kind and brief. "
    'Reply with a JSON object with keys: "summary" (string, max 2 sentences), "strengths" (array of up to 3 short strings), '
    '"improvements" (array of up to 3 short strings), "next_drill" (string, one concrete drill), '
    '"spoken" (string, 2 to 3 sentences to be read aloud, no lists).'
)


def _prompt_payload(session_id: str | None, metrics: SessionMetrics, base: CoachReport) -> dict[str, Any]:
    return {
        "score_percent": base.score_percent,
        "focus_component": base.focus_component,
        "metrics": metrics.model_dump(by_alias=True, mode="json"),
        "findings": [f.model_dump(mode="json") for f in base.findings],
        "known_drills": [c[3] for c in COMPONENTS],
    }


def _merge(base: CoachReport, data: dict[str, Any], provider: str) -> CoachReport:
    """Take the model's wording but keep every number and the focus from the deterministic findings."""
    def strings(key: str, fallback: list[str]) -> list[str]:
        value = data.get(key)
        if isinstance(value, list) and value and all(isinstance(v, str) and v.strip() for v in value):
            return [v.strip() for v in value][:3]
        return fallback

    def text(key: str, fallback: str) -> str:
        value = data.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else fallback

    return base.model_copy(update={
        "provider": provider,
        "summary": text("summary", base.summary),
        "strengths": strings("strengths", base.strengths),
        "improvements": strings("improvements", base.improvements),
        "next_drill": text("next_drill", base.next_drill),
        "spoken": text("spoken", base.spoken),
    })


def _parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.index("{"):] if "{" in text else text
    return json.loads(text)


@dataclass
class OpenAICoach:
    api_key: str
    model: str = "gpt-4o-mini"
    base_url: str = "https://api.openai.com"
    http: httpx.AsyncClient | None = None
    name: str = "openai"

    async def coach(self, session_id: str | None, metrics: SessionMetrics) -> CoachReport:
        base = _base_report(session_id, metrics, "offline")
        body = {
            "model": self.model,
            "temperature": 0.4,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(_prompt_payload(session_id, metrics, base))},
            ],
        }
        try:
            client = self.http or httpx.AsyncClient(timeout=20.0)
            try:
                response = await client.post(
                    f"{self.base_url}/v1/chat/completions", json=body,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
            finally:
                if self.http is None:
                    await client.aclose()
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return _merge(base, _parse_json(content), self.name)
        except Exception as error:               # any failure falls back to the deterministic coach
            return base.model_copy(update={"provider": "offline-fallback",
                                           "note": f"OpenAI coaching unavailable ({type(error).__name__})"})


@dataclass
class GeminiCoach:
    api_key: str
    model: str = "gemini-2.0-flash"
    base_url: str = "https://generativelanguage.googleapis.com"
    http: httpx.AsyncClient | None = None
    name: str = "gemini"

    async def coach(self, session_id: str | None, metrics: SessionMetrics) -> CoachReport:
        base = _base_report(session_id, metrics, "offline")
        body = {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": json.dumps(_prompt_payload(session_id, metrics, base))}]}],
            "generationConfig": {"temperature": 0.4, "responseMimeType": "application/json"},
        }
        try:
            client = self.http or httpx.AsyncClient(timeout=20.0)
            try:
                response = await client.post(
                    f"{self.base_url}/v1beta/models/{self.model}:generateContent", json=body,
                    headers={"x-goog-api-key": self.api_key},
                )
            finally:
                if self.http is None:
                    await client.aclose()
            response.raise_for_status()
            content = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            return _merge(base, _parse_json(content), self.name)
        except Exception as error:
            return base.model_copy(update={"provider": "offline-fallback",
                                           "note": f"Gemini coaching unavailable ({type(error).__name__})"})


class VoiceUnavailable(Exception):
    pass


@dataclass
class ElevenLabsVoice:
    api_key: str | None
    voice_id: str = "21m00Tcm4TlvDq8ikWAM"
    model_id: str = "eleven_multilingual_v2"
    base_url: str = "https://api.elevenlabs.io"
    http: httpx.AsyncClient | None = None

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    async def synthesize(self, text: str) -> bytes:
        if not self.api_key:
            raise VoiceUnavailable("Set ELEVENLABS_API_KEY to enable spoken coaching")
        text = text.strip()
        if not text:
            raise VoiceUnavailable("Nothing to speak")
        client = self.http or httpx.AsyncClient(timeout=30.0)
        try:
            response = await client.post(
                f"{self.base_url}/v1/text-to-speech/{self.voice_id}",
                json={"text": text[:2500], "model_id": self.model_id},
                headers={"xi-api-key": self.api_key, "accept": "audio/mpeg"},
            )
        finally:
            if self.http is None:
                await client.aclose()
        if response.status_code >= 400:
            raise VoiceUnavailable(f"ElevenLabs returned {response.status_code}")
        return response.content


def build_coach(provider: str, openai_key: str | None, gemini_key: str | None,
                openai_model: str, gemini_model: str) -> Coach:
    """provider: auto | openai | gemini | offline. 'auto' picks the first provider that has a key."""
    provider = (provider or "auto").lower()
    if provider in ("auto", "openai") and openai_key:
        return OpenAICoach(openai_key, openai_model)
    if provider in ("auto", "gemini") and gemini_key:
        return GeminiCoach(gemini_key, gemini_model)
    return OfflineCoach()
