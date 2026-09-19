#!/usr/bin/env python3
"""Verify the running controller -> API -> SOFA -> controller physics loop."""

from __future__ import annotations

import asyncio
import json
import time

import httpx
import websockets


CONTROLLER = "http://127.0.0.1:8100"


async def main() -> None:
    async with httpx.AsyncClient(base_url=CONTROLLER, timeout=10.0) as client:
        calibration_response = await client.post(
            "/v1/calibrations",
            json={
                "deviceId": "live-physics-check",
                "transform": [
                    1, 0, 0, 0,
                    0, 1, 0, 0,
                    0, 0, 1, 0,
                    0, 0, 0, 1,
                ],
                "rmsErrorMm": 0.1,
            },
        )
        calibration_response.raise_for_status()
        calibration_id = calibration_response.json()["calibrationId"]
        session_response = await client.post(
            "/v1/sessions",
            json={
                "exerciseId": "chest-tube-access-demo",
                "calibrationId": calibration_id,
                "toolId": "scalpel",
                "deviceId": "live-physics-check",
            },
        )
        session_response.raise_for_status()
        session_id = session_response.json()["sessionId"]

        sequence = 0
        started = time.monotonic()
        contact_seen = False
        maximum_force = 0.0
        maximum_deformation = 0.0
        first_revision = None
        maximum_revision = 0
        maximum_payload_bytes = 0
        uri = f"ws://127.0.0.1:8100/v1/sessions/{session_id}/hardware-stream"
        trajectory = [
            (-15.0, 5.0),
            (-15.0, 2.5),
            (-15.0, 1.8),
            (-15.0, 1.0),
            (-15.0, 0.0),
            (-15.0, -1.0),
            *[(float(x), -1.0) for x in range(-15, 16, 2)],
        ]
        async with websockets.connect(uri, max_size=1_048_576) as socket:
            for x_mm, y_mm in trajectory:
                payload = {
                    "contractVersion": "1.1",
                    "sessionId": session_id,
                    "toolId": "scalpel",
                    "deviceId": "live-physics-check",
                    "calibrationId": calibration_id,
                    "sequence": sequence,
                    "timestampMs": sequence * 33,
                    "positionMm": {"x": x_mm, "y": y_mm, "z": 0.0},
                    "orientation": {"qx": 0, "qy": 0, "qz": 0, "qw": 1},
                    "forceN": 0.0,
                    "contact": False,
                    "inputMode": "pose-only",
                    "forceMeasurementValid": False,
                }
                await socket.send(json.dumps(payload))
                raw = await socket.recv()
                maximum_payload_bytes = max(maximum_payload_bytes, len(raw))
                snapshot = json.loads(raw)
                if snapshot["simulationBackend"] != "sofa-native":
                    raise RuntimeError("Live response did not come from native SOFA")
                tool = snapshot["tool"]
                tissue = snapshot["tissue"]
                contact_seen = contact_seen or tool["contact"]
                maximum_force = max(maximum_force, tool["reactionForceN"])
                maximum_deformation = max(
                    maximum_deformation, tissue["deformationMm"]
                )
                revision = max(
                    mesh["topologyRevision"]
                    for mesh in snapshot["deformableMeshes"]
                )
                if first_revision is None:
                    first_revision = revision
                maximum_revision = max(maximum_revision, revision)
                sequence += 1

        await client.post(f"/v1/sessions/{session_id}/complete")

    if not contact_seen:
        raise RuntimeError("Live SOFA loop did not report contact")
    if maximum_force <= 0.01:
        raise RuntimeError("Live SOFA loop did not report reaction force")
    if maximum_deformation <= 0.1:
        raise RuntimeError("Live SOFA loop did not report deformation")
    if maximum_revision <= (first_revision or 0):
        raise RuntimeError("Live SOFA loop did not stream a topology change")
    if maximum_payload_bytes >= 1_048_576:
        raise RuntimeError("Live simulation snapshot exceeded Unity's 1 MiB limit")
    elapsed = time.monotonic() - started
    print(
        "LIVE PHYSICS CHECK PASSED: "
        f"{sequence} snapshots in {elapsed:.2f}s, "
        f"peak force {maximum_force:.3f} N, "
        f"deformation {maximum_deformation:.3f} mm, "
        f"topology revision {maximum_revision}, "
        f"largest payload {maximum_payload_bytes / 1024:.1f} KiB."
    )


if __name__ == "__main__":
    asyncio.run(main())
