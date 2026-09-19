"""Hardware bridge for physical ESP32 scalpel.

Reads real-time FSR pressure and contact telemetry over USB serial from the ESP32 firmware,
maintains connection health, and provides normalized physical telemetry to the controller.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import serial
import serial.tools.list_ports

logger = logging.getLogger("scalpel_controller.hardware")


@dataclass
class HardwareTelemetry:
    connected: bool = False
    port: str = ""
    device_id: str = "esp32-scalpel-01"
    force_n: float = 0.0
    is_contact: bool = False
    raw_adc: int = 0
    sequence: int = 0
    timestamp_ms: int = 0
    sample_rate_hz: float = 0.0
    last_seen_time: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "port": self.port,
            "deviceId": self.device_id,
            "forceN": round(self.force_n, 3),
            "contact": self.is_contact,
            "rawAdc": self.raw_adc,
            "sequence": self.sequence,
            "timestampMs": self.timestamp_ms,
            "sampleRateHz": round(self.sample_rate_hz, 1),
            "lastSeenSecondsAgo": round(time.monotonic() - self.last_seen_time, 2)
            if self.last_seen_time > 0
            else None,
        }


def find_scalpel_port() -> Optional[str]:
    """Scans system serial ports for an attached ESP32 or USB-serial device."""
    preferred = os.getenv("SCALPEL_SERIAL_PORT")
    if preferred and os.path.exists(preferred):
        return preferred

    ports = serial.tools.list_ports.comports()
    for port_info in ports:
        device = port_info.device
        # Skip Bluetooth incoming ports
        if "Bluetooth" in device or "incoming" in device.lower():
            continue
        # Check standard USB serial identifiers across macOS and Linux
        if any(
            pattern in device
            for pattern in (
                "usbmodem",
                "usbserial",
                "wchusbserial",
                "SLAB_USB",
                "ttyACM",
                "ttyUSB",
            )
        ):
            return device
    return None


class HardwareBridge:
    def __init__(
        self,
        port: Optional[str] = None,
        baud_rate: int = 115200,
        auto_reconnect: bool = True,
        auto_scan: bool = True,
    ) -> None:
        self.preferred_port = port or os.getenv("SCALPEL_SERIAL_PORT")
        self.baud_rate = baud_rate
        self.auto_reconnect = auto_reconnect
        self.auto_scan = auto_scan

        self._telemetry = HardwareTelemetry()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._serial: Optional[serial.Serial] = None

        # Sample rate calculation
        self._packet_count = 0
        self._rate_window_start = time.monotonic()

    @property
    def telemetry(self) -> HardwareTelemetry:
        with self._lock:
            # Return a copy of the dataclass
            return HardwareTelemetry(**self._telemetry.__dict__)

    def set_mock_telemetry(
        self,
        force_n: float,
        is_contact: bool = True,
        raw_adc: int = 2000,
        port: str = "/dev/cu.usbtest",
        device_id: str = "esp32-scalpel-01",
    ) -> None:
        """Sets mock telemetry for testing without physical hardware."""
        with self._lock:
            self._telemetry.connected = True
            self._telemetry.port = port
            self._telemetry.device_id = device_id
            self._telemetry.force_n = force_n
            self._telemetry.is_contact = is_contact
            self._telemetry.raw_adc = raw_adc
            self._telemetry.last_seen_time = time.monotonic()

    def is_active(self, max_stale_seconds: float = 1.5) -> bool:
        """Returns True if the physical hardware is currently connected and actively streaming."""
        with self._lock:
            if not self._telemetry.connected:
                return False
            return (time.monotonic() - self._telemetry.last_seen_time) <= max_stale_seconds

    def start(self) -> None:
        if not self.auto_scan and not self.preferred_port:
            return
        if self.preferred_port == "mock":
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="HardwareBridgeThread", daemon=True)
        self._thread.start()
        logger.info("Physical scalpel hardware bridge thread started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        logger.info("Physical scalpel hardware bridge thread stopped")

    def send_command(self, cmd: str) -> bool:
        """Sends a single character command to the ESP32 firmware."""
        if self._serial is None or not self._serial.is_open:
            return False
        try:
            self._serial.write(cmd.encode("utf-8"))
            self._serial.flush()
            return True
        except Exception as err:
            logger.warning("Failed to send command '%s' to scalpel: %s", cmd, err)
            return False

    def tare(self) -> bool:
        """Sends tare zero calibration command ('c') to ESP32."""
        return self.send_command("c")

    def set_display_mode(self, mode: int) -> bool:
        """Changes OLED display mode ('0'..'5') on ESP32."""
        if 0 <= mode <= 5:
            return self.send_command(str(mode))
        return False

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            target_port = self.preferred_port or find_scalpel_port()
            if not target_port:
                with self._lock:
                    self._telemetry.connected = False
                    self._telemetry.port = ""
                time.sleep(1.0)
                continue

            try:
                logger.info("Connecting to physical scalpel on %s (%d baud)...", target_port, self.baud_rate)
                ser = serial.Serial(target_port, self.baud_rate, timeout=0.1)
                try:
                    ser.dtr = True
                    ser.rts = True
                except Exception:
                    pass
                self._serial = ser

                # Wait for USB CDC line setup
                time.sleep(0.3)
                # Send 'j' (JSON format) and 't' (stream enable)
                try:
                    ser.write(b"j\nt\n")
                    ser.flush()
                except Exception:
                    pass

                with self._lock:
                    self._telemetry.connected = True
                    self._telemetry.port = target_port
                    self._telemetry.last_seen_time = time.monotonic()

                logger.info("Physical scalpel connected on %s", target_port)

                buffer = bytearray()
                while not self._stop_event.is_set():
                    raw_bytes = ser.read(128)
                    if raw_bytes:
                        buffer.extend(raw_bytes)
                        while b"\n" in buffer:
                            line_bytes, _, buffer = buffer.partition(b"\n")
                            line = line_bytes.decode("utf-8", errors="ignore").strip()
                            if line:
                                self._parse_line(line)
                    else:
                        time.sleep(0.005)

            except (serial.SerialException, OSError) as err:
                logger.debug("Serial connection error on %s: %s", target_port, err)
            finally:
                if self._serial is not None:
                    try:
                        self._serial.close()
                    except Exception:
                        pass
                    self._serial = None
                with self._lock:
                    self._telemetry.connected = False
                    self._telemetry.port = ""

            if not self.auto_reconnect:
                break
            time.sleep(1.5)

    def _parse_line(self, line: str) -> None:
        now = time.monotonic()
        # Fast path: JSON telemetry packet
        if line.startswith("{") and line.endswith("}"):
            try:
                data = json.loads(line)
                force_n = float(data.get("forceN", data.get("force_n", 0.0)))
                contact = bool(data.get("contact", data.get("isContact", False)))
                raw_adc = int(data.get("raw", data.get("rawValue", 0)))
                timestamp_ms = int(data.get("timestampMs", data.get("timestamp_ms", int(now * 1000))))
                seq = int(data.get("seq", data.get("sequence", self._telemetry.sequence + 1)))

                # If event was contact_start or contact_end
                event = data.get("event")
                if event == "contact_start":
                    contact = True
                elif event == "contact_end":
                    contact = False

                self._update_telemetry(force_n, contact, raw_adc, timestamp_ms, seq, now)
                return
            except (ValueError, KeyError):
                pass

        # Text format fallback 1: e.g. "[FSR]  1.45 N  [====------]  (raw: 2150 | delta: +150)"
        if "[FSR]" in line:
            try:
                parts = line.split()
                if len(parts) >= 3 and parts[2].upper() == "N":
                    force_n = float(parts[1])
                    contact = force_n > 0.05
                    raw_val = 0
                    if "raw:" in line:
                        raw_str = line.split("raw:")[1].split()[0]
                        raw_val = int(raw_str)
                    self._update_telemetry(
                        force_n, contact, raw_val, int(now * 1000), self._telemetry.sequence + 1, now
                    )
                    return
            except Exception:
                pass

        # Text format fallback 2: e.g. "[PRESSURE] pin=1 (ADC1) | state=CONTACT | raw=2150 | force=1.45N | t=123ms"
        if "[PRESSURE]" in line or "[Pressure Reading]" in line:
            try:
                force_n = 0.0
                if "force=" in line:
                    force_str = line.split("force=")[1].split("N")[0].strip()
                    force_n = float(force_str)
                elif "Force=" in line:
                    force_str = line.split("Force=")[1].split("N")[0].strip()
                    force_n = float(force_str)
                contact = "CONTACT" in line.upper() or "YES" in line or force_n > 0.05
                raw_val = 0
                if "raw=" in line:
                    raw_val = int(line.split("raw=")[1].split()[0].strip())
                elif "Raw=" in line:
                    raw_val = int(line.split("Raw=")[1].split(",")[0].strip())
                self._update_telemetry(
                    force_n, contact, raw_val, int(now * 1000), self._telemetry.sequence + 1, now
                )
                return
            except Exception:
                pass

        # Text format fallback 3: e.g. ">>> [TOUCH] Engaged (Force: 1.25 N | raw: 2150 | delta: +150)"
        if "[TOUCH]" in line or "[RELEASE]" in line:
            try:
                contact = "[TOUCH]" in line
                force_n = 0.0
                if "Force:" in line:
                    force_str = line.split("Force:")[1].split("N")[0].strip()
                    force_n = float(force_str)
                raw_val = 0
                if "raw:" in line:
                    raw_val = int(line.split("raw:")[1].split()[0].strip())
                self._update_telemetry(
                    force_n, contact, raw_val, int(now * 1000), self._telemetry.sequence + 1, now
                )
                return
            except Exception:
                pass

    def _update_telemetry(
        self, force_n: float, contact: bool, raw_adc: int, timestamp_ms: int, seq: int, now: float
    ) -> None:
        with self._lock:
            self._telemetry.force_n = force_n
            self._telemetry.is_contact = contact
            self._telemetry.raw_adc = raw_adc
            self._telemetry.timestamp_ms = timestamp_ms
            self._telemetry.sequence = seq
            self._telemetry.last_seen_time = now

            self._packet_count += 1
            dt = now - self._rate_window_start
            if dt >= 1.0:
                self._telemetry.sample_rate_hz = self._packet_count / dt
                self._packet_count = 0
                self._rate_window_start = now
