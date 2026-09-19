"""Synthetic hardware stream for visual client development."""

import argparse
import asyncio
import json
import math
import time

import httpx
from websockets.asyncio.client import connect


IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


async def run(controller_url: str, sample_limit: int) -> None:
    async with httpx.AsyncClient(base_url=controller_url, timeout=5.0) as client:
        calibration_response = await client.post(
            "/v1/calibrations",
            json={
                "deviceId": "synthetic-hardware",
                "transform": IDENTITY,
                "rmsErrorMm": 0.1,
            },
        )
        calibration_response.raise_for_status()
        calibration = calibration_response.json()
        session_response = await client.post(
            "/v1/sessions",
            json={
                "exerciseId": "chest-tube-access-demo",
                "calibrationId": calibration["calibrationId"],
                "toolId": "blunt-stylus-1",
                "deviceId": "synthetic-hardware",
            },
        )
        session_response.raise_for_status()
        session = session_response.json()

    session_id = session["sessionId"]
    print(f"Session ID: {session_id}", flush=True)
    print("Enter this session ID in the Unity ScalpelStreamClient.", flush=True)
    websocket_base = controller_url.replace("http://", "ws://").replace("https://", "wss://")
    stream_url = f"{websocket_base}/v1/sessions/{session_id}/hardware-stream"
    started = time.monotonic()
    sequence = 0
    try:
        async with connect(stream_url, max_size=1024 * 1024) as socket:
            while sample_limit == 0 or sequence < sample_limit:
                elapsed = time.monotonic() - started
                phase = elapsed % 20.0
                if phase < 5.0:
                    approach = 1.0 - phase / 5.0
                    radius_mm = 30.0 * approach
                    force_n = 0.0
                else:
                    radius_mm = 2.0 + math.sin(elapsed * 1.7) * 1.2
                    force_n = round(0.75 + math.sin(elapsed * 2.3) * 0.16, 3)
                sample = {
                    "contractVersion": "1.0",
                    "sessionId": session_id,
                    "toolId": "blunt-stylus-1",
                    "deviceId": "synthetic-hardware",
                    "calibrationId": calibration["calibrationId"],
                    "sequence": sequence,
                    "timestampMs": int(elapsed * 1000),
                    "positionMm": {
                        "x": math.sin(elapsed * 0.8) * radius_mm,
                        "y": 16.0 - force_n * 2.0,
                        "z": math.cos(elapsed * 0.8) * radius_mm,
                    },
                    "orientation": {"qx": 0, "qy": 0, "qz": 0, "qw": 1},
                    "forceN": force_n,
                    "contact": force_n > 0.08,
                    "quality": 1.0,
                    "sourceHealthy": True,
                }
                await socket.send(json.dumps(sample))
                await socket.recv()
                sequence += 1
                await asyncio.sleep(1 / 30)
    finally:
        async with httpx.AsyncClient(base_url=controller_url, timeout=5.0) as client:
            response = await client.post(f"/v1/sessions/{session_id}/complete")
            if response.is_success:
                print(json.dumps(response.json()["metrics"], indent=2), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controller-url", default="http://localhost:8100")
    parser.add_argument(
        "--samples", type=int, default=0,
        help="Stop after this many samples; zero streams until interrupted.",
    )
    arguments = parser.parse_args()
    try:
        asyncio.run(run(arguments.controller_url.rstrip("/"), arguments.samples))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
