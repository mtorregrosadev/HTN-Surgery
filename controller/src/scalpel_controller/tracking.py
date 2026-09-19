"""Optical tracking bridge for Surge Prep scalpel controller.

Ingests real-time tool pose (positionMm, orientation quaternion, markerId, source)
from optical camera trackers (tracking-web, external CV pipelines), validates timestamps,
and provides fused 3D spatial pose to the live simulation loop.
"""

from __future__ import annotations

from copy import copy
from dataclasses import dataclass
import math
import threading
import time
from typing import Any, Optional


# Base surgical incision orientation (40 degree pitch about +X)
DEFAULT_QX = 0.34202014
DEFAULT_QY = 0.0
DEFAULT_QZ = 0.0
DEFAULT_QW = 0.93969262


@dataclass
class TrackingPose:
    x_mm: float = 0.0
    y_mm: float = 12.0
    z_mm: float = 0.0
    qx: float = DEFAULT_QX
    qy: float = DEFAULT_QY
    qz: float = DEFAULT_QZ
    qw: float = DEFAULT_QW
    angle_deg: float = 0.0
    source: str = "camera-aruco"
    marker_id: Optional[int] = None
    confidence: float = 1.0
    sequence: int = 0
    timestamp_ms: int = 0
    last_seen_time: float = 0.0

    def is_active(self, max_stale_seconds: float = 1.5) -> bool:
        """Returns True if a tracking update was received within max_stale_seconds."""
        return self.last_seen_time > 0 and (time.monotonic() - self.last_seen_time) <= max_stale_seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": self.is_active(),
            "positionMm": {
                "x": round(self.x_mm, 2),
                "y": round(self.y_mm, 2),
                "z": round(self.z_mm, 2),
            },
            "orientation": {
                "qx": round(self.qx, 4),
                "qy": round(self.qy, 4),
                "qz": round(self.qz, 4),
                "qw": round(self.qw, 4),
            },
            "angleDeg": round(self.angle_deg, 1),
            "source": self.source,
            "markerId": self.marker_id,
            "confidence": round(self.confidence, 2),
            "sequence": self.sequence,
            "timestampMs": self.timestamp_ms,
            "lastSeenSecondsAgo": round(time.monotonic() - self.last_seen_time, 2)
            if self.last_seen_time > 0
            else None,
        }


def compute_quaternion_from_angle(
    angle_deg: float,
    base_qx: float = DEFAULT_QX,
    base_qw: float = DEFAULT_QW,
) -> tuple[float, float, float, float]:
    """Combines a 40 degree incision pitch with tool yaw on screen."""
    rad = math.radians(angle_deg)
    half_yaw = rad / 2.0
    sy = math.sin(half_yaw)
    cy = math.cos(half_yaw)

    # Base pitch q_pitch = (base_qx, 0, 0, base_qw)
    # Yaw q_yaw = (0, sy, 0, cy)
    # Multiplied:
    # qx = q_pitch.x * cy + q_pitch.w * 0 ... = base_qx * cy
    # qy = base_qw * sy
    # qz = -base_qx * sy
    # qw = base_qw * cy
    qx = base_qx * cy
    qy = base_qw * sy
    qz = -base_qx * sy
    qw = base_qw * cy
    norm = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
    if norm > 1e-6:
        return qx / norm, qy / norm, qz / norm, qw / norm
    return DEFAULT_QX, DEFAULT_QY, DEFAULT_QZ, DEFAULT_QW


class TrackingBridge:
    def __init__(self) -> None:
        self._pose = TrackingPose()
        self._lock = threading.Lock()
        self._packet_count = 0
        self._rate_window_start = time.monotonic()
        self._sample_rate_hz = 0.0

    @property
    def telemetry(self) -> TrackingPose:
        with self._lock:
            return copy(self._pose)

    @property
    def sample_rate_hz(self) -> float:
        with self._lock:
            return self._sample_rate_hz

    def is_active(self, max_stale_seconds: float = 1.5) -> bool:
        with self._lock:
            return self._pose.is_active(max_stale_seconds)

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            data = self._pose.to_dict()
            data["sampleRateHz"] = round(self._sample_rate_hz, 1)
            return data

    def update_pose(
        self,
        x_mm: float,
        y_mm: float,
        z_mm: float,
        qx: Optional[float] = None,
        qy: Optional[float] = None,
        qz: Optional[float] = None,
        qw: Optional[float] = None,
        angle_deg: float = 0.0,
        source: str = "camera-aruco",
        marker_id: Optional[int] = None,
        confidence: float = 1.0,
        timestamp_ms: Optional[int] = None,
    ) -> None:
        now = time.monotonic()
        # Clamp coordinates to surgical safety bounds
        clamped_x = max(-150.0, min(150.0, float(x_mm)))
        clamped_y = max(-80.0, min(50.0, float(y_mm)))
        clamped_z = max(-260.0, min(260.0, float(z_mm)))

        if qx is None or qw is None:
            calc_qx, calc_qy, calc_qz, calc_qw = compute_quaternion_from_angle(angle_deg)
        else:
            calc_qx, calc_qy, calc_qz, calc_qw = float(qx), float(qy or 0.0), float(qz or 0.0), float(qw)

        with self._lock:
            self._pose.x_mm = clamped_x
            self._pose.y_mm = clamped_y
            self._pose.z_mm = clamped_z
            self._pose.qx = calc_qx
            self._pose.qy = calc_qy
            self._pose.qz = calc_qz
            self._pose.qw = calc_qw
            self._pose.angle_deg = float(angle_deg)
            self._pose.source = source
            self._pose.marker_id = marker_id
            self._pose.confidence = max(0.0, min(1.0, float(confidence)))
            self._pose.sequence += 1
            self._pose.timestamp_ms = int(timestamp_ms) if timestamp_ms is not None else int(now * 1000)
            self._pose.last_seen_time = now

            self._packet_count += 1
            dt = now - self._rate_window_start
            if dt >= 1.0:
                self._sample_rate_hz = self._packet_count / dt
                self._packet_count = 0
                self._rate_window_start = now

    def update_from_dict(self, data: dict[str, Any]) -> None:
        """Parses a tracking payload in either millimeter or camera pixel formats."""
        timestamp_ms = data.get("timestampMs", data.get("timestamp_ms"))
        source = str(data.get("source", "camera-aruco"))
        marker_id = data.get("markerId", data.get("marker_id"))
        if marker_id is not None:
            try:
                marker_id = int(marker_id)
            except (ValueError, TypeError):
                marker_id = None
        confidence = float(data.get("confidence", data.get("quality", 1.0)))
        angle_deg = float(data.get("angleDeg", data.get("angle", 0.0)))

        # Format 1: Direct millimetres
        if "positionMm" in data or "xMm" in data:
            pos = data.get("positionMm", {})
            x = float(pos.get("x", data.get("xMm", 0.0)))
            y = float(pos.get("y", data.get("yMm", 12.0)))
            z = float(pos.get("z", data.get("zMm", 0.0)))

            ori = data.get("orientation")
            if ori and isinstance(ori, dict) and "qx" in ori and "qw" in ori:
                self.update_pose(
                    x_mm=x,
                    y_mm=y,
                    z_mm=z,
                    qx=ori.get("qx"),
                    qy=ori.get("qy", 0.0),
                    qz=ori.get("qz", 0.0),
                    qw=ori.get("qw"),
                    angle_deg=angle_deg,
                    source=source,
                    marker_id=marker_id,
                    confidence=confidence,
                    timestamp_ms=timestamp_ms,
                )
                return

            self.update_pose(
                x_mm=x,
                y_mm=y,
                z_mm=z,
                angle_deg=angle_deg,
                source=source,
                marker_id=marker_id,
                confidence=confidence,
                timestamp_ms=timestamp_ms,
            )
            return

        # Format 2: Camera image pixels (pixelX, pixelY, width, height, zPercent)
        if "pixelX" in data or "x" in data:
            px_x = float(data.get("pixelX", data.get("x", 240.0)))
            px_y = float(data.get("pixelY", data.get("y", 180.0)))
            width = float(data.get("width", 480.0))
            height = float(data.get("height", 360.0))
            z_percent = float(data.get("zPercent", data.get("z", 0.0)))

            # Lateral X: center is 0, span ±150 mm
            x_mm = (px_x - width / 2.0) * (300.0 / max(1.0, width))
            # Body axis Z: center is 0, span ±220 mm
            z_mm = (px_y - height / 2.0) * (380.0 / max(1.0, height))
            # Height Y: default 12 mm hover, adjusted by relative Z
            y_mm = 12.0 - (z_percent * 0.25)

            self.update_pose(
                x_mm=x_mm,
                y_mm=y_mm,
                z_mm=z_mm,
                angle_deg=angle_deg,
                source=source,
                marker_id=marker_id,
                confidence=confidence,
                timestamp_ms=timestamp_ms,
            )
