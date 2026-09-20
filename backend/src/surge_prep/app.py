from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Response, WebSocket, WebSocketDisconnect

from .coaching import CoachReport, ElevenLabsVoice, VoiceUnavailable, build_coach
from .config import Settings
from .models import (
    Calibration,
    CalibrationCreate,
    Health,
    ProgressSummary,
    ResultRecord,
    Session,
    SessionCreate,
    SessionResult,
    SimulationSnapshot,
    ToolSample,
)
from .service import TrainingService
from .simulation import MemorySimulator, Simulator, SofaSimulator
from .store import MemoryStore, MongoStore, Store


def build_store(settings: Settings) -> Store:
    if settings.mongodb_uri:
        return MongoStore(settings.mongodb_uri, settings.mongodb_database)
    return MemoryStore()


def build_simulator(settings: Settings) -> Simulator:
    if settings.simulation_backend == "memory":
        return MemorySimulator()
    if settings.simulation_backend == "sofa":
        return SofaSimulator(settings.sofa_scene_path, allow_fallback=True)
    raise RuntimeError(f"Unsupported simulation backend: {settings.simulation_backend}")


def init_sentry(settings: Settings) -> bool:
    """Optional observability: tracing and profiling, only when SENTRY_DSN is set and sentry-sdk is installed."""
    if not settings.sentry_dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        return False
    sentry_sdk.init(
        dsn=settings.sentry_dsn, traces_sample_rate=1.0, profiles_sample_rate=1.0,
        send_default_pii=False, enable_logs=True,
    )
    return True


def create_app(
    store: Store | None = None,
    simulator: Simulator | None = None,
    coach=None,
    voice: ElevenLabsVoice | None = None,
) -> FastAPI:
    settings = Settings.from_environment()
    init_sentry(settings)
    selected_store = store or build_store(settings)
    selected_simulator = simulator or build_simulator(settings)
    service = TrainingService(selected_store, selected_simulator)
    selected_coach = coach or build_coach(
        settings.coach_provider, settings.openai_api_key, settings.gemini_api_key,
        settings.openai_model, settings.gemini_model,
    )
    selected_voice = voice or ElevenLabsVoice(settings.elevenlabs_api_key, settings.elevenlabs_voice_id)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await selected_store.start()
        await selected_simulator.start()
        yield
        await selected_simulator.close()
        await selected_store.close()

    app = FastAPI(title="Surge Prep API", version="1.0.0", lifespan=lifespan)
    app.state.service = service

    @app.get("/health", response_model=Health)
    async def health() -> Health:
        return Health(status="ok", persistence=selected_store.name, simulation=selected_simulator.name)

    @app.post("/v1/calibrations", response_model=Calibration, status_code=201)
    async def create_calibration(request: CalibrationCreate) -> Calibration:
        return await service.create_calibration(request)

    @app.get("/v1/sessions", response_model=list[Session])
    async def list_sessions(limit: int = Query(20, ge=1, le=200)) -> list[Session]:
        return await service.list_sessions(limit)

    @app.post("/v1/sessions", response_model=Session, status_code=201)
    async def create_session(request: SessionCreate) -> Session:
        return await service.create_session(request)

    @app.get("/v1/sessions/active", response_model=Session)
    async def get_active_session() -> Session:
        return await service.get_active_session()

    @app.get("/v1/sessions/{session_id}", response_model=Session)
    async def get_session(session_id: str) -> Session:
        return await service.require_session(session_id)

    @app.post("/v1/sessions/{session_id}/samples", response_model=SimulationSnapshot)
    async def process_sample(session_id: str, sample: ToolSample) -> SimulationSnapshot:
        return await service.process_sample(session_id, sample)

    @app.post("/v1/sessions/{session_id}/complete", response_model=SessionResult)
    async def complete_session(session_id: str) -> SessionResult:
        return await service.complete_session(session_id)

    @app.get("/v1/sessions/{session_id}/result", response_model=ResultRecord)
    async def session_result(session_id: str) -> ResultRecord:
        return await service.get_result(session_id)

    @app.get("/v1/progress", response_model=ProgressSummary)
    async def progress(
        device_id: str | None = Query(None, alias="deviceId"), limit: int = Query(50, ge=1, le=500)
    ) -> ProgressSummary:
        return await service.progress(device_id, limit)

    @app.post("/v1/sessions/{session_id}/coaching", response_model=CoachReport)
    async def coaching(session_id: str) -> CoachReport:
        record = await service.get_result(session_id)
        return await selected_coach.coach(session_id, record.metrics)

    @app.post("/v1/sessions/{session_id}/coaching/audio")
    async def coaching_audio(session_id: str) -> Response:
        if not selected_voice.available:
            raise HTTPException(503, "Spoken coaching needs ELEVENLABS_API_KEY")
        record = await service.get_result(session_id)
        report = await selected_coach.coach(session_id, record.metrics)
        try:
            audio = await selected_voice.synthesize(report.spoken)
        except VoiceUnavailable as error:
            raise HTTPException(502, str(error)) from error
        return Response(content=audio, media_type="audio/mpeg")

    @app.get("/v1/sessions/{session_id}/replay", response_model=list[SimulationSnapshot])
    async def replay(session_id: str) -> list[SimulationSnapshot]:
        return await service.replay(session_id)

    @app.websocket("/v1/sessions/{session_id}/stream")
    async def simulation_stream(websocket: WebSocket, session_id: str) -> None:
        await websocket.accept()
        try:
            while True:
                sample = ToolSample.model_validate(await websocket.receive_json())
                snapshot = await service.process_sample(session_id, sample)
                await websocket.send_json(snapshot.model_dump(by_alias=True, mode="json"))
        except WebSocketDisconnect:
            return

    return app


app = create_app()
