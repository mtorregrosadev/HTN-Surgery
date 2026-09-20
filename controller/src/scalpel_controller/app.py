from __future__ import annotations

from collections import defaultdict
from contextlib import asynccontextmanager
import json
import os
from typing import Any, Protocol

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse


class Upstream(Protocol):
    async def start(self) -> None: ...
    async def close(self) -> None: ...
    async def request(self, method: str, path: str, body: Any = None) -> tuple[int, Any]: ...


class ApiUpstream:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=5.0)

    async def close(self) -> None:
        if self.client is not None:
            await self.client.aclose()

    async def request(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        if self.client is None:
            raise RuntimeError("API connection has not started")
        response = await self.client.request(method, path, json=body)
        return response.status_code, response.json()


class SessionHub:
    def __init__(self, upstream: Upstream) -> None:
        self.upstream = upstream
        self.clients: dict[str, set[WebSocket]] = defaultdict(set)
        self.session_sequences: dict[str, int] = {}

    async def client_stream(self, socket: WebSocket, session_id: str) -> None:
        await socket.accept()
        self.clients[session_id].add(socket)
        try:
            while True:
                message = await socket.receive_json()
                if message.get("type") == "ping":
                    await socket.send_json({"type": "pong"})
                else:
                    await socket.send_json(
                        {"type": "error", "message": "Unsupported client action"}
                    )
        except WebSocketDisconnect:
            pass
        finally:
            self.clients[session_id].discard(socket)

    async def hardware_stream(self, socket: WebSocket, session_id: str) -> None:
        await socket.accept()
        try:
            while True:
                sample = await socket.receive_json()
                seq = sample.get("sequence", 0)
                last_seq = self.session_sequences.get(session_id)
                if last_seq is None:
                    s_code, s_info = await self.upstream.request("GET", f"/v1/sessions/{session_id}")
                    if s_code < 400 and isinstance(s_info, dict):
                        last_seq = s_info.get("lastSequence") or 0
                    else:
                        last_seq = 0
                    self.session_sequences[session_id] = last_seq

                if seq <= self.session_sequences[session_id]:
                    self.session_sequences[session_id] += 1
                    sample["sequence"] = self.session_sequences[session_id]
                else:
                    self.session_sequences[session_id] = seq

                status_code, snapshot = await self.upstream.request(
                    "POST", f"/v1/sessions/{session_id}/samples", sample
                )
                if status_code == 409 and "sequence" in str(snapshot).lower():
                    s_code, s_info = await self.upstream.request("GET", f"/v1/sessions/{session_id}")
                    if s_code < 400 and isinstance(s_info, dict):
                        self.session_sequences[session_id] = (s_info.get("lastSequence") or 0) + 1
                        sample["sequence"] = self.session_sequences[session_id]
                        status_code, snapshot = await self.upstream.request(
                            "POST", f"/v1/sessions/{session_id}/samples", sample
                        )

                if status_code >= 400:
                    await socket.send_json(
                        {"type": "error", "status": status_code, "detail": snapshot}
                    )
                    continue
                await socket.send_json(snapshot)
                await self.broadcast(session_id, snapshot)
        except WebSocketDisconnect:
            return

    async def broadcast(self, session_id: str, snapshot: Any) -> None:
        disconnected: list[WebSocket] = []
        payload = json.dumps(snapshot)
        for socket in tuple(self.clients[session_id]):
            try:
                await socket.send_text(payload)
            except (RuntimeError, WebSocketDisconnect):
                disconnected.append(socket)
        for socket in disconnected:
            self.clients[session_id].discard(socket)


def create_app(upstream: Upstream | None = None) -> FastAPI:
    selected_upstream = upstream or ApiUpstream(
        os.getenv("SURGE_PREP_API_URL", "http://localhost:8000")
    )
    hub = SessionHub(selected_upstream)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await selected_upstream.start()
        yield
        await selected_upstream.close()

    app = FastAPI(title="Surge Prep Scalpel Controller", version="1.0.0", lifespan=lifespan)

    async def proxy(method: str, path: str, body: Any = None) -> JSONResponse:
        status_code, payload = await selected_upstream.request(method, path, body)
        return JSONResponse(payload, status_code=status_code)

    @app.get("/health")
    async def health() -> JSONResponse:
        status_code, api_health = await selected_upstream.request("GET", "/health")
        return JSONResponse(
            {"status": "ok" if status_code < 400 else "degraded", "api": api_health},
            status_code=200 if status_code < 400 else 503,
        )

    @app.post("/v1/calibrations")
    async def create_calibration(body: dict[str, Any]) -> JSONResponse:
        return await proxy("POST", "/v1/calibrations", body)

    @app.post("/v1/sessions")
    async def create_session(body: dict[str, Any]) -> JSONResponse:
        return await proxy("POST", "/v1/sessions", body)

    @app.get("/v1/sessions")
    async def list_sessions() -> JSONResponse:
        return await proxy("GET", "/v1/sessions")

    @app.get("/v1/sessions/active")
    async def get_active_session() -> JSONResponse:
        return await proxy("GET", "/v1/sessions/active")

    @app.get("/v1/sessions/{session_id}")
    async def get_session(session_id: str) -> JSONResponse:
        return await proxy("GET", f"/v1/sessions/{session_id}")

    @app.post("/v1/sessions/{session_id}/complete")
    async def complete_session(session_id: str) -> JSONResponse:
        return await proxy("POST", f"/v1/sessions/{session_id}/complete")

    @app.get("/v1/sessions/{session_id}/replay")
    async def replay(session_id: str) -> JSONResponse:
        return await proxy("GET", f"/v1/sessions/{session_id}/replay")

    @app.websocket("/v1/sessions/{session_id}/client-stream")
    async def client_stream(socket: WebSocket, session_id: str) -> None:
        await hub.client_stream(socket, session_id)

    @app.websocket("/v1/sessions/{session_id}/hardware-stream")
    async def hardware_stream(socket: WebSocket, session_id: str) -> None:
        await hub.hardware_stream(socket, session_id)

    return app


app = create_app()

