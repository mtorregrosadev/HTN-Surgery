# API features for the Hack the North prize tracks

Surge Prep now uses several sponsor APIs. Every one is **optional**: with no keys set, the whole system still works
(a built-in rubric coach replaces the AI, and audio is simply unavailable). Keys are read from environment variables
and are never stored, logged or put in prompts.

| Prize track (from the Devpost listing) | What Surge Prep does with it | Turn it on |
| --- | --- | --- |
| **MLH: Best Use of MongoDB Atlas** | Every sample and physics frame is stored in Atlas; finished attempts also store a **scorecard** in a `results` collection, which powers **progress across attempts** (`GET /v1/progress`) | `SURGE_PREP_MONGODB_URI=mongodb+srv://...` |
| **OpenAI: API Prizes** | After a run, the OpenAI API turns the scorecard into personal coaching (summary, strengths, what to improve, next drill) | `OPENAI_API_KEY` |
| **MLH: Best Use of Gemini API** | The same coaching through Google Gemini, as an alternative provider | `GEMINI_API_KEY` |
| **MLH: Best Use of ElevenLabs** | The coaching is **spoken** in a natural voice | `ELEVENLABS_API_KEY` |
| **Sentry: Best Use of Sentry** | Tracing, profiling and logs on the API (needs at least two products beyond error monitoring) | `SENTRY_DSN` and `pip install "./backend[observability]"` |

Only enter the tracks you can honestly explain. Read the rules for each on Devpost; some ask for things this repository
does not do (for example, the OpenAI track asks you to show how **Codex** helped you build; only say that if it is true).

## How the coaching stays honest

The AI never invents numbers. The flow is:

1. The API computes one **finding per scorecard component** from the stored data, using the same formulas and weights as
   the scorecard (`backend/src/surge_prep/coaching.py`). A test checks the weighted findings add up to the real score.
2. Those findings and the raw metrics go to the model with an instruction to only use the numbers provided and never
   give medical or clinical advice.
3. The model returns wording only. The API **keeps its own scores and its own "focus area"** and takes just the
   phrasing (`summary`, `strengths`, `improvements`, `next_drill`, `spoken`) from the model.
4. If the call fails for any reason (no key, timeout, HTTP error, invalid JSON) the built-in coach answers instead and the
   response says so (`provider: "offline-fallback"`, plus a `note`).

## New endpoints

| Method and path | What it returns |
| --- | --- |
| `GET /v1/sessions?limit=20` | Recent sessions, newest first |
| `GET /v1/sessions/{id}/result` | The stored scorecard for a finished session |
| `GET /v1/progress?deviceId=&limit=50` | Attempts, latest, best, average, improvement, weakest area, per-component averages and a score trend |
| `POST /v1/sessions/{id}/coaching` | The coaching report (JSON) |
| `POST /v1/sessions/{id}/coaching/audio` | The spoken coaching as `audio/mpeg` (503 if no ElevenLabs key) |

MongoDB collections added: `results` (unique on `sessionId`, indexed on `deviceId` + `completedAt`). Sessions get a
`createdAt` index for the newest-first list.

## Try it

```bash
# 1. put your keys in backend/.env (never commit it) and start the API as usual
# 2. do a practice run in Unity, then leave Play mode so the session completes
python scripts/coach.py --latest              # prints the coaching
python scripts/coach.py --latest --speak      # also saves and plays the audio
python scripts/coach.py --progress            # scores across attempts (from MongoDB)
```

## Demo talking points

- "Every run is stored in **MongoDB Atlas**: samples, physics frames, and a scorecard, so we can chart progress."
- "**OpenAI** (or **Gemini**) writes the coaching, but only from the stored numbers. It cannot change the score."
- "**ElevenLabs** reads it back, so a learner keeps their eyes on the task."
- "If any API is down, the built-in coach takes over, so the demo never breaks."

## Tests

```bash
python -m pytest backend/tests hardware tools controller/tests
```

The provider calls are tested with mocked HTTP (`httpx.MockTransport`), so the suite needs no keys and no network. That
also means the real OpenAI, Gemini and ElevenLabs endpoints have **not** been called from this repository's tests. Before
the demo, run `scripts/coach.py --latest --speak` once with real keys to confirm each provider accepts the request
(model names change over time; set `SURGE_PREP_OPENAI_MODEL` / `SURGE_PREP_GEMINI_MODEL` if needed).
