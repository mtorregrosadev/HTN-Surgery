"""Accuracy check for hardware/tracking.py using synthetic camera frames with known tool poses.

Run:  python hardware/test_tracking.py
It renders a tool with three AprilTags at random positions/angles, detects the tags with OpenCV,
and compares a plain average of the visible tag centres with the rigid-body tracker (tool point and
cutting tip), with all tags visible and with tags hidden.
"""
import math
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tracking import ToolTracker, rot2  # noqa: E402

DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
DETECTOR = cv2.aruco.ArucoDetector(DICT, cv2.aruco.DetectorParameters())
W, H = 1280, 720
TAG_PX = 96
# tool image is 420 x 420; tags at these top-left corners, tip below them
TOOL = 420
TAG_POS = {1: (40, 40), 2: (250, 60), 3: (140, 220)}
TIP = np.array([210.0, 400.0])
CENTRE = np.array([TOOL / 2, TOOL / 2])
rng = np.random.default_rng(3)


def tool_image(hidden=()):
    img = np.full((TOOL, TOOL), 255, np.uint8)
    for i, (x, y) in TAG_POS.items():
        if i in hidden:
            continue
        img[y:y + TAG_PX, x:x + TAG_PX] = cv2.aruco.generateImageMarker(DICT, i, TAG_PX)
    return img


def render(theta, offset, hidden=()):
    """Place the tool at rotation theta with its centre at `offset`. Returns the frame and the true tip."""
    rot = rot2(theta)
    matrix = np.hstack([rot, (offset - rot @ CENTRE).reshape(2, 1)])
    frame = cv2.warpAffine(tool_image(hidden), matrix, (W, H), flags=cv2.INTER_CUBIC, borderValue=255)
    frame = cv2.GaussianBlur(frame, (3, 3), 0.8).astype(np.float32)
    frame += rng.normal(0, 3.0, frame.shape)
    frame = np.clip(frame, 0, 255).astype(np.uint8)
    ref = np.mean([np.array(TAG_POS[i]) + TAG_PX / 2 for i in TAG_POS], axis=0)   # centre of the 3 tags
    return frame, rot @ (TIP - CENTRE) + offset, rot @ (ref - CENTRE) + offset


def detect(frame):
    corners, ids, _ = DETECTOR.detectMarkers(frame)
    if ids is None:
        return {}
    return {int(i): c.reshape(4, 2) for c, i in zip(corners, ids.flatten()) if int(i) in TAG_POS}


def main():
    tracker = ToolTracker()

    # learn the layout at a reference pose, then calibrate the tip by "touching" a known point
    ref_frame, ref_tip, _ = render(0.0, np.array([640.0, 360.0]))
    tracker.start_learning(frames=1)
    detections = detect(ref_frame)
    assert len(detections) == 3, "reference frame must show all three tags"
    tracker.feed_learning(detections)
    pose = tracker.estimate(detections)
    tracker.calibrate_tip(pose, ref_tip)

    results = {}
    for hidden in ((), (2,), (1, 3), (1, 2)):
        naive_err, origin_err, tip_err, rejected = [], [], [], 0
        for _ in range(120):
            theta = rng.uniform(-math.pi, math.pi)
            offset = np.array([rng.uniform(300, 980), rng.uniform(200, 520)])
            frame, true_tip, true_ref = render(theta, offset, hidden)
            det = detect(frame)
            pose = tracker.estimate(det) if det else None
            if pose is None:
                rejected += 1
                continue
            # plain average of the visible tag centres, as the old bridge did
            naive_err.append(np.linalg.norm(np.mean([det[i].mean(axis=0) for i in det], axis=0) - true_ref))
            origin_err.append(np.linalg.norm(pose["origin"] - true_ref))
            tip_err.append(np.linalg.norm(pose["tip"] - true_tip))
        results[hidden] = (naive_err, origin_err, tip_err, rejected)

    print("Error in pixels (lower is better). 'tool point' = centre of the three tags.")
    print(f"{'hidden tags':<13}{'method':<30}{'mean':>7}{'95th':>7}{'max':>7}")
    for hidden, (naive, origin, tip, rejected) in results.items():
        label = ",".join(map(str, hidden)) or "none"
        for name, errs in (("tool point, plain average", naive), ("tool point, rigid-body", origin),
                           ("cutting tip, rigid-body", tip)):
            print(f"{label:<13}{name:<30}{np.mean(errs):>7.2f}{np.percentile(errs, 95):>7.2f}{np.max(errs):>7.2f}")
        if rejected:
            print(f"{'':<13}(rejected/undetected frames: {rejected})")
    all_rigid = [e for _, o, t, _ in results.values() for e in o + t]
    assert np.mean(all_rigid) < 3.0, "rigid tracker should stay within a few pixels"
    print("OK")


if __name__ == "__main__":
    main()


def test_synthetic_accuracy():
    main()
