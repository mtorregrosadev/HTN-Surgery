"""Receive the Unity simulator's rendered view as JPEG frames over UDP.

The tracker window is where the operator is already looking while cutting, so
the simulator view is composited into it as a corner inset. Unity sends one
complete JPEG per datagram: a lost or reordered packet therefore costs exactly
one frame instead of corrupting a stream, and no reassembly state is needed.

Entirely optional. If Unity is not running, the socket simply never receives
anything and the tracker renders as it always did.
"""
import socket
import threading
from typing import Optional, Tuple

import cv2
import numpy as np

DEFAULT_PORT = 8302

# IPv4's maximum datagram payload; the sender stays well under this.
MAX_DATAGRAM_BYTES = 65535


class SimulatorViewReceiver:
    """Background UDP listener exposing only the newest simulator frame.

    Mirrors ``LatestFrameCamera``: decoding on a dedicated thread and keeping
    just the latest image means a slow or stalled simulator can never add
    latency to the tracking loop, it only makes the inset go stale.
    """

    def __init__(self, port: int = DEFAULT_PORT, bind_host: str = "127.0.0.1") -> None:
        self.port = port
        self._lock = threading.Lock()
        self._frame: Optional[np.ndarray] = None
        self._count = 0
        self._stop = threading.Event()
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # A timeout keeps the loop responsive to close() instead of
            # blocking forever in recvfrom on a silent socket.
            sock.settimeout(0.5)
            sock.bind((bind_host, port))
        except OSError as exc:
            print(f"[SimView] Could not bind udp://{bind_host}:{port}: {exc}", flush=True)
            return

        self._sock = sock
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        print(f"[SimView] Listening for the simulator view on udp://{bind_host}:{port}", flush=True)

    @property
    def available(self) -> bool:
        """True when the socket bound; False means the port was already taken."""
        return self._sock is not None

    @property
    def frame_count(self) -> int:
        with self._lock:
            return self._count

    def _run(self) -> None:
        buffer = bytearray(MAX_DATAGRAM_BYTES)
        while not self._stop.is_set():
            try:
                size, _ = self._sock.recvfrom_into(buffer)
            except socket.timeout:
                continue
            except OSError:
                return
            if size <= 0:
                continue

            image = cv2.imdecode(
                np.frombuffer(bytes(buffer[:size]), dtype=np.uint8), cv2.IMREAD_COLOR
            )
            if image is None:
                # A truncated datagram decodes to None; drop it silently
                # rather than logging every frame on a lossy link.
                continue
            with self._lock:
                self._frame = image
                self._count += 1

    def read(self) -> Tuple[Optional[np.ndarray], int]:
        """Return (newest frame or None, total frames received)."""
        with self._lock:
            return self._frame, self._count

    def close(self) -> None:
        self._stop.set()
        if self._sock is not None:
            self._sock.close()
        if self._thread is not None:
            self._thread.join(timeout=1.0)


def draw_simulator_inset(
    frame: np.ndarray,
    sim_frame: Optional[np.ndarray],
    connected: bool,
    width_fraction: float = 0.3,
    margin: int = 14,
) -> None:
    """Composite the simulator view into the bottom-right of ``frame``.

    Drawn in place. When no frame has arrived yet a labelled placeholder is
    shown instead, so a silent Unity is visibly distinguishable from a feature
    that simply is not running.
    """
    h, w = frame.shape[:2]
    inset_w = max(160, int(w * width_fraction))
    inset_h = int(inset_w * 9 / 16)

    x1 = w - inset_w - margin
    y1 = h - inset_h - margin
    x2, y2 = x1 + inset_w, y1 + inset_h
    if x1 < 0 or y1 < 0:
        return

    if sim_frame is not None:
        resized = cv2.resize(sim_frame, (inset_w, inset_h), interpolation=cv2.INTER_AREA)
        frame[y1:y2, x1:x2] = resized
        border = (0, 255, 255) if connected else (60, 160, 200)
        label = "SIMULATOR VIEW" if connected else "SIMULATOR VIEW (stalled)"
    else:
        cv2.rectangle(frame, (x1, y1), (x2, y2), (28, 28, 28), cv2.FILLED)
        border = (90, 90, 90)
        label = "SIMULATOR VIEW: waiting for Unity"
        cv2.putText(
            frame, "no frames on udp:8302", (x1 + 10, y1 + inset_h // 2),
            cv2.FONT_HERSHEY_SIMPLEX, 0.42, (150, 150, 150), 1, cv2.LINE_AA
        )

    cv2.rectangle(frame, (x1, y1), (x2, y2), border, 2)
    cv2.rectangle(frame, (x1, y1 - 20), (x2, y1), (20, 20, 20), cv2.FILLED)
    cv2.putText(
        frame, label, (x1 + 8, y1 - 6),
        cv2.FONT_HERSHEY_SIMPLEX, 0.42, border, 1, cv2.LINE_AA
    )
