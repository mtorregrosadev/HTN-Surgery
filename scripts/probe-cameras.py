#!/usr/bin/env python3
"""Enumerate every camera index OpenCV can reach and report why each one passed
or failed the tracker's "is this a usable stream" test.

The tracker rejects a camera that opens but only yields dark, flat frames.  That
check is deliberately strict, and a camera that simply needs a longer warm-up
looks identical to a dead one.  This script separates those two cases by
probing each index for a full second and printing the brightness statistics.

Run from Terminal.app (macOS grants camera permission per-app):

    python3 scripts/probe-cameras.py
"""
import sys
import time

import cv2
import numpy as np

SCAN_LIMIT = 8
WARMUP_SECONDS = 1.5

# Same thresholds the tracker uses to decide a stream is real.
MEAN_MIN = 3.0
STD_MIN = 3.0


def probe(idx: int) -> None:
    cap = cv2.VideoCapture(idx)
    if not cap.isOpened():
        print(f"  [{idx}] not openable")
        cap.release()
        return

    backend = cap.getBackendName()
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    print(f"  [{idx}] OPENED  backend={backend}  {width}x{height} @ {fps:.0f}fps")

    deadline = time.monotonic() + WARMUP_SECONDS
    frames = 0
    first_pass_at = None
    best_mean = 0.0
    best_std = 0.0

    while time.monotonic() < deadline:
        ok, frame = cap.read()
        if not ok or frame is None:
            time.sleep(0.01)
            continue
        frames += 1
        mean = float(np.mean(frame))
        std = float(np.std(frame))
        best_mean = max(best_mean, mean)
        best_std = max(best_std, std)
        if mean > MEAN_MIN and std > STD_MIN and first_pass_at is None:
            first_pass_at = frames

    if frames == 0:
        print(f"       -> NO FRAMES at all in {WARMUP_SECONDS}s (device busy or blocked)")
    elif first_pass_at is None:
        print(f"       -> {frames} frames, but all too dark/flat "
              f"(best mean={best_mean:.1f} need>{MEAN_MIN}, "
              f"best std={best_std:.1f} need>{STD_MIN})")
        print( "          lens covered, or this is a virtual/placeholder device")
    else:
        print(f"       -> USABLE: passed on frame {first_pass_at} of {frames} "
              f"(mean={best_mean:.1f}, std={best_std:.1f})")
        if first_pass_at > 10:
            print(f"          NOTE: needed {first_pass_at} frames, more than the "
                  f"tracker's 10-frame budget -> tracker would REJECT this camera")

    cap.release()


def main() -> int:
    print(f"OpenCV {cv2.__version__} on {sys.platform}")
    print(f"Probing indices 0..{SCAN_LIMIT - 1}, {WARMUP_SECONDS}s each.\n")
    for idx in range(SCAN_LIMIT):
        probe(idx)
    print("\nDone. Report the index whose picture is the Logitech.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
