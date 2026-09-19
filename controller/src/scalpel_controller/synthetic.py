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
        self.y_mm = 12.0
        self.z_mm = 0.0
        self.tool_id = "scalpel"

    def apply(self, key: str) -> bool:
        if key == "q":
            self.y_mm = min(24.0, self.y_mm + 1.0)
            return True
        if key == "e":
            self.y_mm = max(-16.0, self.y_mm - 1.0)
            return True
        if key == "a":
            self.x_mm += 2.0
        elif key == "d":
            self.x_mm -= 2.0
        elif key == "w":
            self.z_mm += 2.0
        elif key == "s":
            self.z_mm -= 2.0
        elif key == "1":
            self.tool_id = "scalpel"
        elif key == "2":
            self.tool_id = "blunt-dissector"
        elif key == "3":
            self.tool_id = "chest-tube"
        elif key == "r":
            self.x_mm = 0.0
            self.y_mm = 12.0
            self.z_mm = 0.0
        elif key == "x":
            return False
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
                "toolId": "scalpel",
                "deviceId": "synthetic-hardware",
            },
        )
        session_response.raise_for_status()
        session = session_response.json()

    session_id = session["sessionId"]
    print(f"Session ID: {session_id}", flush=True)
    if manual:
        print(
            "Controls: W/A/S/D move, Q/E raise/lower, 1 scalpel, 2 dissector, 3 tube, "
            "R resets, X finishes. Contact comes from SOFA, not Space.",
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
                        y_mm = manual_state.y_mm
                        z_mm = manual_state.z_mm
                        tool_id = manual_state.tool_id
                    else:
                        phase = elapsed % 20.0
                        tool_id = "scalpel"
                        if phase < 5.0:
                            y_mm = 12.0 - phase
                            x_mm = math.sin(elapsed * 0.8) * 8.0
                            z_mm = math.cos(elapsed * 0.8) * 4.0
                        else:
                            y_mm = -1.2
                            x_mm = math.sin(elapsed * 0.4) * 12.0
                            z_mm = 0.0
                    sample = {
                        "contractVersion": "1.1",
                        "sessionId": session_id,
                        "toolId": tool_id,
                        "deviceId": "synthetic-hardware",
                        "calibrationId": calibration["calibrationId"],
                        "sequence": sequence,
                        "timestampMs": int(elapsed * 1000),
                        "positionMm": {"x": x_mm, "y": y_mm, "z": z_mm},
                        "orientation": {"qx": 0.0, "qy": 0.0, "qz": 0.0, "qw": 1.0},
                        "forceN": 0.0,
                        "contact": False,
                        "quality": 1.0,
                        "sourceHealthy": True,
                        "inputMode": "pose-only",
                        "forceMeasurementValid": False,
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
