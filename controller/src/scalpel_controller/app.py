from __future__ import annotations

import asyncio
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
    def __init__(self, upstream: Upstream, client_send_timeout_s: float = 0.25) -> None:
        self.upstream = upstream
        self.clients: dict[str, set[WebSocket]] = defaultdict(set)
        self.session_sequences: dict[str, int] = {}
        self._sequence_locks: dict[str, asyncio.Lock] = {}
        self.client_send_timeout_s = client_send_timeout_s

    def _sequence_lock(self, session_id: str) -> asyncio.Lock:
        lock = self._sequence_locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._sequence_locks[session_id] = lock
        return lock

    async def _load_last_sequence(self, session_id: str) -> int:
        status_code, session_info = await self.upstream.request(
            "GET", f"/v1/sessions/{session_id}"
        )
        if status_code >= 400 or not isinstance(session_info, dict):
            return -1
        last_sequence = session_info.get("lastSequence")
        if isinstance(last_sequence, int) and not isinstance(last_sequence, bool):
            return last_sequence
        return -1

    @staticmethod
    def _sample_error(status_code: int, detail: Any) -> dict[str, Any]:
        return {"type": "error", "status": status_code, "detail": detail}

    @classmethod
    def _websocket_error(cls, status_code: int, payload: Any) -> Any:
        if isinstance(payload, dict) and payload.get("type") == "error":
            return payload
        return cls._sample_error(status_code, payload)

    async def submit_sample(self, session_id: str, sample: Any) -> tuple[int, Any]:
        """Forward one sample while preserving the upstream sequence contract."""
        if not isinstance(sample, dict):
            return 422, self._sample_error(422, "Sample payload must be a JSON object")

        sequence = sample.get("sequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
            return 422, self._sample_error(
                422, "Sample sequence must be a non-negative integer"
            )

        async with self._sequence_lock(session_id):
            last_sequence = self.session_sequences.get(session_id)
            if last_sequence is None:
                last_sequence = await self._load_last_sequence(session_id)
                self.session_sequences[session_id] = last_sequence

            if sequence <= last_sequence:
                return 409, self._sample_error(
                    409,
                    f"Sample sequence must increase (lastSequence={last_sequence})",
                )

            status_code, snapshot = await self.upstream.request(
                "POST", f"/v1/sessions/{session_id}/samples", sample
            )
            if status_code == 409 and "sequence" in str(snapshot).lower():
                # Another controller instance may have advanced the API. Refresh
                # our guard for the next sample, but never rewrite this sample.
                self.session_sequences[session_id] = await self._load_last_sequence(session_id)
            elif status_code < 400:
                self.session_sequences[session_id] = sequence

            if status_code < 400:
                await self.broadcast(session_id, snapshot)
            return status_code, snapshot

    async def client_stream(self, socket: WebSocket, session_id: str) -> None:
        await socket.accept()
        self.clients[session_id].add(socket)
        try:
            while True:
                message = await socket.receive_json()
                if not isinstance(message, dict):
                    await socket.send_json(
                        self._sample_error(422, "Client action must be a JSON object")
                    )
                elif message.get("type") == "ping":
                    await socket.send_json({"type": "pong"})
                elif message.get("type") in {"sample", "tool-sample"}:
                    sample = message.get("sample", message.get("payload"))
                    status_code, payload = await self.submit_sample(session_id, sample)
                    if status_code >= 400:
                        await socket.send_json(self._websocket_error(status_code, payload))
                elif "sequence" in message:
                    status_code, payload = await self.submit_sample(session_id, message)
                    if status_code >= 400:
                        await socket.send_json(self._websocket_error(status_code, payload))
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
                status_code, snapshot = await self.submit_sample(session_id, sample)
                if status_code >= 400:
                    await socket.send_json(self._websocket_error(status_code, snapshot))
                    continue
                await socket.send_json(snapshot)
        except WebSocketDisconnect:
            return

    async def broadcast(self, session_id: str, snapshot: Any) -> None:
        payload = json.dumps(snapshot)

        async def send(socket: WebSocket) -> WebSocket | None:
            try:
                await asyncio.wait_for(
                    socket.send_text(payload), timeout=self.client_send_timeout_s
                )
            except Exception:
                return socket
            return None

        results = await asyncio.gather(
            *(send(socket) for socket in tuple(self.clients[session_id])),
            return_exceptions=True,
        )
        for result in results:
            if result is not None:
                self.clients[session_id].discard(result)


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

    @app.post("/v1/sessions/{session_id}/samples")
    async def process_sample(session_id: str, body: dict[str, Any]) -> JSONResponse:
        status_code, payload = await hub.submit_sample(session_id, body)
        return JSONResponse(payload, status_code=status_code)

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
