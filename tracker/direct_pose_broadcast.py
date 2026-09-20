"""Fire-and-forget UDP broadcast of the raw desk-frame tool pose.

The controller/API/SOFA path is authoritative for the simulation, but it
rewrites Y by the chest surface height and runs at the solver's step rate.
For rendering the instrument, Unity only needs the pose, so this sends it
straight to the renderer on localhost.

UDP is deliberate: a dropped packet is always superseded by a newer pose, so
there is no value in retransmission, and no handshake or backpressure can
stall the camera loop.
"""
from __future__ import annotations

import json
import socket
from typing import Optional

DEFAULT_PORT = 8301


class DirectPoseBroadcaster:
    """Sends the tool pose to a local renderer; never raises into the loop."""

    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> None:
        self.address = (host, port)
        self.sent = 0
        self._warned = False
        self._socket: Optional[socket.socket] = None
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.setblocking(False)
        except OSError as exc:
            print(f"[DirectPose] Disabled, could not open socket: {exc}", flush=True)

    def send(self, pose) -> None:
        """Broadcast one pose. A failure here must never stop tracking."""
        if self._socket is None:
            return
        payload = json.dumps(
            {
                "x": round(float(pose.x_mm), 3),
                "y": round(float(pose.y_mm), 3),
                "z": round(float(pose.z_mm), 3),
                "qx": round(float(pose.qx), 5),
                "qy": round(float(pose.qy), 5),
                "qz": round(float(pose.qz), 5),
                "qw": round(float(pose.qw), 5),
            }
        ).encode("utf-8")
        try:
            self._socket.sendto(payload, self.address)
            self.sent += 1
        except OSError as exc:
            # A full send buffer is expected under load and is safe to drop.
            if not self._warned:
                print(f"[DirectPose] Dropping packets: {exc}", flush=True)
                self._warned = True

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None
