"""Synthetic hardware stream for visual client development."""

import argparse
import asyncio
from contextlib import contextmanager
import json
import math
import os
import select
import sys
import termios
import time
import tty

import httpx
from websockets.asyncio.client import connect


IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


class ManualToolState:
    def __init__(self) -> None:
        self.x_mm = 0.0
        self.z_mm = 0.0
        self.force_n = 0.0

    def apply(self, key: str) -> bool:
        if key == "q":
            return False
        if key == "a":
            self.x_mm += 2.0
        elif key == "d":
            self.x_mm -= 2.0
        elif key == "w":
            self.z_mm += 2.0
        elif key == "s":
            self.z_mm -= 2.0
        elif key == " ":
            self.force_n = 0.0 if self.force_n > 0.0 else 0.75
        elif key == "[":
            self.force_n = max(0.0, self.force_n - 0.1)
        elif key == "]":
            self.force_n = min(1.5, self.force_n + 0.1)
        elif key == "r":
            self.x_mm = 0.0
            self.z_mm = 0.0
            self.force_n = 0.0
        return True


@contextmanager
def terminal_input(enabled: bool):
    if not enabled:
        yield None
        return
    if not sys.stdin.isatty():
        raise RuntimeError("Manual control requires an interactive terminal")
    descriptor = sys.stdin.fileno()
    previous = termios.tcgetattr(descriptor)
    tty.setcbreak(descriptor)
    try:
        yield descriptor
    finally:
        termios.tcsetattr(descriptor, termios.TCSADRAIN, previous)


def read_keys(descriptor: int | None) -> list[str]:
    if descriptor is None:
        return []
    keys: list[str] = []
    while select.select([descriptor], [], [], 0)[0]:
        keys.append(os.read(descriptor, 1).decode(errors="ignore").lower())
    return keys


async def run(controller_url: str, sample_limit: int, manual: bool = False) -> None:
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
    if manual:
        print(
            "Controls: W/A/S/D move, Space contacts/releases, [ and ] change force, "
            "R resets, Q finishes.",
            flush=True,
        )
    websocket_base = controller_url.replace("http://", "ws://").replace("https://", "wss://")
    stream_url = f"{websocket_base}/v1/sessions/{session_id}/hardware-stream"
    started = time.monotonic()
    sequence = 0
    manual_state = ManualToolState()
    keep_running = True
    try:
        with terminal_input(manual) as input_descriptor:
            async with connect(stream_url, max_size=1024 * 1024) as socket:
                while keep_running and (sample_limit == 0 or sequence < sample_limit):
                    elapsed = time.monotonic() - started
                    for key in read_keys(input_descriptor):
                        keep_running = manual_state.apply(key) and keep_running
                    if not keep_running:
                        break
                    if manual:
                        x_mm = manual_state.x_mm
                        z_mm = manual_state.z_mm
                        force_n = manual_state.force_n
                    else:
                        phase = elapsed % 20.0
                        if phase < 5.0:
                            approach = 1.0 - phase / 5.0
                            radius_mm = 30.0 * approach
                            force_n = 0.0
                        else:
                            radius_mm = 2.0 + math.sin(elapsed * 1.7) * 1.2
                            force_n = round(0.75 + math.sin(elapsed * 2.3) * 0.16, 3)
                        x_mm = math.sin(elapsed * 0.8) * radius_mm
                        z_mm = math.cos(elapsed * 0.8) * radius_mm
                    sample = {
                        "contractVersion": "1.0",
                        "sessionId": session_id,
                        "toolId": "blunt-stylus-1",
                        "deviceId": "synthetic-hardware",
                        "calibrationId": calibration["calibrationId"],
                        "sequence": sequence,
                        "timestampMs": int(elapsed * 1000),
                        "positionMm": {
                            "x": x_mm,
                            "y": 16.0 - force_n * 2.0,
                            "z": z_mm,
                        },
                        "orientation": {
                            "qx": 0.173648,
                            "qy": 0,
                            "qz": 0,
                            "qw": 0.984808,
                        },
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
    parser.add_argument(
        "--manual", action="store_true",
        help="Control the synthetic tool with keys in this terminal.",
    )
    arguments = parser.parse_args()
    try:
        asyncio.run(
            run(arguments.controller_url.rstrip("/"), arguments.samples, arguments.manual)
        )
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
