from __future__ import annotations

from collections import defaultdict
from contextlib import asynccontextmanager
import json
import os
from typing import Any, Protocol

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
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
        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=10.0)

    async def close(self) -> None:
        if self.client is not None:
            await self.client.aclose()

    async def request(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        if self.client is None:
            raise RuntimeError("API connection has not started")
        response = await self.client.request(method, path, json=body)
        return response.status_code, response.json()


from scalpel_controller.hardware import HardwareBridge
from scalpel_controller.tracking import TrackingBridge


class SessionHub:
    def __init__(
        self,
        upstream: Upstream,
        hardware: HardwareBridge | None = None,
        tracking: TrackingBridge | None = None,
    ) -> None:
        self.upstream = upstream
        self.hardware = hardware
        self.tracking = tracking
        self.clients: dict[str, set[WebSocket]] = defaultdict(set)

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
        optical_tracking_seen = False
        try:
            while True:
                sample = await socket.receive_json()

                # Manual/keyboard streams are valid until optical tracking has
                # actually taken over. Once it has, do not silently fall back to
                # the last client pose when the tracker goes stale.
                tracking_pose = self.tracking.telemetry if self.tracking else None
                tracking_active = bool(tracking_pose and tracking_pose.is_active())
                if tracking_active:
                    optical_tracking_seen = True
                elif optical_tracking_seen:
                    await self._send_stream_error(
                        socket,
                        session_id,
                        409,
                        {"detail": "Optical tracking is stale; waiting for a fresh pose"},
                    )
                    continue

                # 1. If physical scalpel hardware is actively streaming, merge real FSR pressure
                hardware_active = bool(self.hardware and self.hardware.is_active())
                if hardware_active:
                    hw = self.hardware.telemetry
                    sample["forceN"] = hw.force_n
                    sample["contact"] = hw.is_contact
                    sample["forceMeasurementValid"] = True
                    sample["inputMode"] = "calibrated-hardware"
                    if not sample.get("deviceId"):
                        sample["deviceId"] = hw.device_id

                # 2. If optical camera tracking is active, merge tracked position & orientation
                if tracking_active and tracking_pose is not None:
                    tr = tracking_pose
                    sample["positionMm"] = {
                        "x": tr.x_mm,
                        "y": tr.y_mm,
                        "z": tr.z_mm,
                    }
                    sample["orientation"] = {
                        "qx": tr.qx,
                        "qy": tr.qy,
                        "qz": tr.qz,
                        "qw": tr.qw,
                    }
                    sample["quality"] = max(0.5, tr.confidence)
                    sample["sourceHealthy"] = True
                    # If hardware FSR is not connected, use optical surface depth for contact
                    if not hardware_active:
                        if tr.y_mm <= 0.0:
                            sample["contact"] = True
                            sample["forceN"] = min(8.0, abs(tr.y_mm) * 0.8 + 0.5)
                            sample["forceMeasurementValid"] = True

                try:
                    status_code, snapshot = await self.upstream.request(
                        "POST", f"/v1/sessions/{session_id}/samples", sample
                    )
                except Exception:
                    await self._send_stream_error(
                        socket,
                        session_id,
                        503,
                        {"detail": "Controller could not reach the simulation API"},
                    )
                    continue

                if status_code >= 400:
                    await self._send_stream_error(socket, session_id, status_code, snapshot)
                    continue
                await socket.send_json(snapshot)
                await self.broadcast(session_id, snapshot)
        except WebSocketDisconnect:
            return

    async def _send_stream_error(
        self,
        socket: WebSocket,
        session_id: str,
        status_code: int,
        detail: Any,
    ) -> None:
        error = {
            "type": "error",
            "sessionId": session_id,
            "status": status_code,
            "detail": detail,
        }
        await socket.send_json(error)
        await self.broadcast(session_id, error)

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


def create_app(
    upstream: Upstream | None = None,
    hardware: HardwareBridge | None = None,
    tracking: TrackingBridge | None = None,
) -> FastAPI:
    selected_upstream = upstream or ApiUpstream(
        os.getenv("SURGE_PREP_API_URL", "http://localhost:8000")
    )
    hardware_bridge = hardware or HardwareBridge()
    tracking_bridge = tracking or TrackingBridge()
    hub = SessionHub(selected_upstream, hardware_bridge, tracking_bridge)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await selected_upstream.start()
        hardware_bridge.start()
        yield
        hardware_bridge.stop()
        await selected_upstream.close()

    app = FastAPI(title="Surge Prep Scalpel Controller", version="1.0.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    async def proxy(method: str, path: str, body: Any = None) -> JSONResponse:
        status_code, payload = await selected_upstream.request(method, path, body)
        return JSONResponse(payload, status_code=status_code)

    @app.get("/health")
    async def health() -> JSONResponse:
        status_code, api_health = await selected_upstream.request("GET", "/health")
        hw_dict = hardware_bridge.telemetry.to_dict()
        tr_dict = tracking_bridge.to_dict()
        return JSONResponse(
            {
                "status": "ok" if status_code < 400 else "degraded",
                "api": api_health,
                "hardware": hw_dict,
                "tracking": tr_dict,
            },
            status_code=200 if status_code < 400 else 503,
        )

    @app.get("/v1/hardware/status")
    async def hardware_status() -> JSONResponse:
        return JSONResponse(hardware_bridge.telemetry.to_dict())

    @app.post("/v1/hardware/tare")
    async def hardware_tare() -> JSONResponse:
        success = hardware_bridge.tare()
        return JSONResponse({"status": "ok" if success else "failed", "action": "tare"})

    @app.post("/v1/hardware/display")
    async def hardware_display(body: dict[str, Any]) -> JSONResponse:
        mode = int(body.get("mode", 0))
        success = hardware_bridge.set_display_mode(mode)
        return JSONResponse({"status": "ok" if success else "failed", "mode": mode})

    @app.get("/v1/tracking/status")
    async def tracking_status() -> JSONResponse:
        return JSONResponse(tracking_bridge.to_dict())

    @app.post("/v1/tracking/pose")
    async def tracking_pose(body: dict[str, Any]) -> JSONResponse:
        tracking_bridge.update_from_dict(body)
        return JSONResponse({"status": "ok", "active": tracking_bridge.is_active()})

    @app.websocket("/v1/tracking/stream")
    async def tracking_stream(socket: WebSocket) -> None:
        await socket.accept()
        try:
            while True:
                message = await socket.receive_json()
                msg_type = message.get("type", "pose")
                if msg_type in ("pose", "frame") or "positionMm" in message or "pixelX" in message or "x" in message:
                    tracking_bridge.update_from_dict(message)
                    hw_dict = hardware_bridge.telemetry.to_dict() if hardware_bridge else {}
                    await socket.send_json({
                        "type": "ack",
                        "trackingActive": True,
                        "hardware": hw_dict,
                        "sequence": tracking_bridge.telemetry.sequence,
                    })
                elif msg_type == "ping":
                    await socket.send_json({"type": "pong"})
        except WebSocketDisconnect:
            pass

    @app.post("/v1/calibrations")
    async def create_calibration(body: dict[str, Any]) -> JSONResponse:
        return await proxy("POST", "/v1/calibrations", body)

    @app.post("/v1/sessions")
    async def create_session(body: dict[str, Any]) -> JSONResponse:
        return await proxy("POST", "/v1/sessions", body)

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

