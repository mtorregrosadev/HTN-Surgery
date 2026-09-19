#!/usr/bin/env python3
"""Exercise the REST vertical slice using only the Python standard library."""

import json
import sys
from urllib.request import Request, urlopen


BASE_URL = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:8000"
IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def request(method: str, path: str, body: dict | None = None):
    encoded = json.dumps(body).encode() if body is not None else None
    call = Request(
        f"{BASE_URL}{path}", data=encoded, method=method,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(call) as response:
        return json.load(response)


calibration = request(
    "POST", "/v1/calibrations",
    {"deviceId": "demo-device", "transform": IDENTITY, "rmsErrorMm": 0.5},
)
session = request(
    "POST", "/v1/sessions",
    {
        "exerciseId": "training-pad-demo",
        "calibrationId": calibration["calibrationId"],
        "toolId": "blunt-stylus-1",
        "deviceId": "demo-device",
    },
)
for sequence, force in enumerate((0.0, 0.6, 1.2, 0.4, 0.0)):
    snapshot = request(
        "POST", f"/v1/sessions/{session['sessionId']}/samples",
        {
            "sessionId": session["sessionId"],
            "toolId": "blunt-stylus-1",
            "deviceId": "demo-device",
            "calibrationId": calibration["calibrationId"],
            "sequence": sequence,
            "timestampMs": sequence * 10,
            "positionMm": {"x": 0, "y": 15 - sequence, "z": 0},
            "orientation": {"qx": 0, "qy": 0, "qz": 0, "qw": 1},
            "forceN": force,
            "contact": force > 0,
        },
    )
    print(json.dumps(snapshot))

result = request("POST", f"/v1/sessions/{session['sessionId']}/complete")
print(json.dumps(result, indent=2))
