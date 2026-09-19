from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .config import Settings
from .models import (
    Calibration,
    CalibrationCreate,
    Health,
    Session,
    SessionCreate,
    SessionResult,
    SimulationSnapshot,
    ToolSample,
)
from .service import TrainingService
from .simulation import MemorySimulator, Simulator
from .store import MemoryStore, MongoStore, Store


def build_store(settings: Settings) -> Store:
    if settings.mongodb_uri:
        return MongoStore(settings.mongodb_uri, settings.mongodb_database)
    return MemoryStore()


def build_simulator(settings: Settings) -> Simulator:
    if settings.simulation_backend != "memory":
        raise RuntimeError(f"Unsupported simulation backend: {settings.simulation_backend}")
    return MemorySimulator()


def create_app(store: Store | None = None, simulator: Simulator | None = None) -> FastAPI:
    settings = Settings.from_environment()
    selected_store = store or build_store(settings)
    selected_simulator = simulator or build_simulator(settings)
    service = TrainingService(selected_store, selected_simulator)

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

    @app.post("/v1/sessions", response_model=Session, status_code=201)
    async def create_session(request: SessionCreate) -> Session:
        return await service.create_session(request)

    @app.get("/v1/sessions/{session_id}", response_model=Session)
    async def get_session(session_id: str) -> Session:
        return await service.require_session(session_id)

    @app.post("/v1/sessions/{session_id}/samples", response_model=SimulationSnapshot)
    async def process_sample(session_id: str, sample: ToolSample) -> SimulationSnapshot:
        return await service.process_sample(session_id, sample)

    @app.post("/v1/sessions/{session_id}/complete", response_model=SessionResult)
    async def complete_session(session_id: str) -> SessionResult:
        return await service.complete_session(session_id)

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

