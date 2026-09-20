"""End-to-end bridge test: synthetic camera frames -> tag_fsr_bridge.main() -> UDP packets.

OpenCV's camera and window functions are replaced by fakes; detection, tracking, calibration keys and the
UDP sender are the real code.
"""
import json
import math
import os
import socket
import sys
import threading

import cv2
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tag_fsr_bridge as bridge  # noqa: E402
import test_tracking as synth  # noqa: E402


def free_udp_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def run_bridge(monkeypatch, tmp_path, frames, keys, extra_args=(), preexisting_config=None):
    """Feed `frames` to the bridge, press `keys` ({frame index: char}), return (packets, config path)."""
    port = free_udp_port()
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", port))
    rx.settimeout(0.2)
    packets, stop = [], threading.Event()

    def listen():
        while not stop.is_set():
            try:
                packets.append(json.loads(rx.recv(1000)))
            except socket.timeout:
                pass

    class FakeCap:
        def __init__(self, *a, **k):
            self.i = 0

        def isOpened(self):
            return True

        def set(self, *a):
            return True

        def read(self):
            frame = frames[min(self.i, len(frames) - 1)]
            self.i += 1
            return True, frame.copy()

        def release(self):
            pass

    counter = {"n": 0}

    def fake_waitkey(_):
        n = counter["n"]
        counter["n"] += 1
        if n >= len(frames) - 1:
            return ord("q")
        return ord(keys[n]) if n in keys else 255

    monkeypatch.setattr(cv2, "VideoCapture", FakeCap)
    monkeypatch.setattr(cv2, "imshow", lambda *a, **k: None)
    monkeypatch.setattr(cv2, "namedWindow", lambda *a, **k: None)
    monkeypatch.setattr(cv2, "setMouseCallback", lambda *a, **k: None)
    monkeypatch.setattr(cv2, "waitKey", fake_waitkey)
    monkeypatch.setattr(cv2, "destroyAllWindows", lambda: None)

    cfg = str(tmp_path / "cfg.json")
    if preexisting_config is not None:
        with open(cfg, "w") as f:
            json.dump(preexisting_config, f)
    monkeypatch.setattr(sys, "argv", ["bridge", "--config", cfg, "--udp", f"127.0.0.1:{port}",
                                      "--min-cutoff", "1000000", "--beta", "0", *extra_args])
    thread = threading.Thread(target=listen, daemon=True)
    thread.start()
    try:
        bridge.main()
    finally:
        stop.set()
        thread.join(1)
        rx.close()
    return packets, cfg


def to_bgr(gray):
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def scene(theta, offset, hidden=()):
    gray, _, _ = synth.render(theta, np.array(offset, float), hidden)
    return to_bgr(gray)


def expected_xy(centre_px, frame_w=1280, frame_h=720, span=0.5):
    """Bridge output when no table is calibrated: 0.5 + (tip/frame - origin) / span with origin (0.5, 0.5)."""
    return (0.5 + (centre_px[0] / frame_w - 0.5) / span, 0.5 + (centre_px[1] / frame_h - 0.5) / span)


def test_learns_calibrates_and_tracks_within_two_pixels(monkeypatch, tmp_path):
    still = [scene(0.0, (640, 360))] * 40
    moving = [scene(0.6 * math.sin(k / 7), (480 + k * 7, 300 + 40 * math.sin(k / 5))) for k in range(60)]
    frames = still + moving
    packets, cfg = run_bridge(monkeypatch, tmp_path, frames, {2: "l", 36: "t"})
    saved = json.load(open(cfg))
    assert saved["layout"] is not None and any(abs(v) > 1 for v in saved["tip_local"])

    errors = []
    for k in range(60):
        n = 40 + k
        p = packets[n]
        truth = (480 + k * 7, 300 + 40 * math.sin(k / 5))
        ex, ey = expected_xy(truth)
        if p["tags"] > 0 and 0 <= ex <= 1 and 0 <= ey <= 1:
            errors.append((abs(p["x"] - ex) * 640, abs(p["y"] - ey) * 360))
    assert len(errors) > 40
    assert np.mean(errors) < 2.0 and np.max(errors) < 6.0


def test_hidden_tags_do_not_move_the_position(monkeypatch, tmp_path):
    base = [scene(0.0, (640, 360))] * 40
    steady = [scene(0.3, (700, 380))] * 10
    partial = [scene(0.3, (700, 380), hidden=(2,))] * 10 + [scene(0.3, (700, 380), hidden=(1, 3))] * 10
    packets, _ = run_bridge(monkeypatch, tmp_path, base + steady + partial, {2: "l", 36: "t"})
    reference = packets[45]
    for p in packets[52:70]:
        assert p["tags"] >= 1
        assert abs(p["x"] - reference["x"]) * 640 < 3 and abs(p["y"] - reference["y"]) * 360 < 3


def test_no_tags_reports_zero_tags_and_holds_position(monkeypatch, tmp_path):
    blank = to_bgr(np.full((720, 1280), 255, np.uint8))
    frames = [scene(0.0, (640, 360))] * 40 + [scene(0.2, (800, 400))] * 8 + [blank] * 12
    packets, _ = run_bridge(monkeypatch, tmp_path, frames, {5: "l"})
    last_seen = packets[47]
    for p in packets[50:59]:
        assert p["tags"] == 0 and p["quality"] == 0
        assert (p["x"], p["y"]) == (last_seen["x"], last_seen["y"])


def test_packet_has_the_fields_unity_expects(monkeypatch, tmp_path):
    packets, _ = run_bridge(monkeypatch, tmp_path, [scene(0.0, (640, 360))] * 12, {})
    p = packets[-1]
    assert {"x", "y", "force", "tags", "t", "angle", "quality"} <= set(p)
    assert 0 <= p["x"] <= 1 and 0 <= p["y"] <= 1 and p["force"] == 0.0


def test_saved_calibration_is_loaded_on_the_next_run(monkeypatch, tmp_path):
    frames = [scene(0.0, (640, 360))] * 40
    _, cfg = run_bridge(monkeypatch, tmp_path, frames, {2: "l", 34: "t"})
    saved = json.load(open(cfg))
    packets, _ = run_bridge(monkeypatch, tmp_path, [scene(0.4, (500, 300))] * 12, {}, preexisting_config=saved)
    ex, ey = expected_xy((500, 300))
    p = packets[-1]
    assert p["tags"] == 3 and p["quality"] > 0.9
    assert abs(p["x"] - ex) * 640 < 2.5 and abs(p["y"] - ey) * 360 < 2.5
    assert p["angle"] == pytest.approx(math.degrees(0.4), abs=0.5)


def test_angle_is_reported_in_degrees(monkeypatch, tmp_path):
    frames = [scene(0.0, (640, 360))] * 35 + [scene(math.radians(30), (640, 360))] * 10
    packets, _ = run_bridge(monkeypatch, tmp_path, frames, {2: "l"})
    assert packets[-1]["angle"] == pytest.approx(30.0, abs=0.5)
