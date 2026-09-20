"""Unit tests for hardware/tracking.py (pure maths: no camera, no OpenCV detection)."""
import json
import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tracking import OneEuro, ToolTracker, rigid_fit, rot2  # noqa: E402

rng = np.random.default_rng(11)

# three tags laid out in the tool frame (millimetres), each a 20 mm square
TAG_CENTRES = {1: (-30.0, -10.0), 2: (30.0, -10.0), 3: (0.0, 35.0)}
SQUARE = np.array([[-10, -10], [10, -10], [10, 10], [-10, 10]], float)     # marker corner order


def corners_at(pose_theta, pose_t, ids=(1, 2, 3), noise=0.0):
    """Tag corners as the camera would see them for a tool at (theta, t)."""
    rot = rot2(pose_theta)
    out = {}
    for i in ids:
        local = SQUARE + np.array(TAG_CENTRES[i])
        pts = local @ rot.T + pose_t
        out[i] = pts + rng.normal(0, noise, pts.shape) if noise else pts
    return out


def trained_tracker():
    tracker = ToolTracker()
    tracker.start_learning(frames=5)
    for _ in range(5):
        tracker.feed_learning(corners_at(0.0, np.array([100.0, 100.0])))
    return tracker


# ---------------------------------------------------------------- rigid_fit


@pytest.mark.parametrize("theta", [-3.0, -1.2, 0.0, 0.4, 1.57, 3.1])
def test_rigid_fit_recovers_rotation_and_translation(theta):
    local = rng.uniform(-50, 50, (12, 2))
    trans = rng.uniform(-200, 200, 2)
    observed = local @ rot2(theta).T + trans
    rot, t, rms = rigid_fit(local, observed)
    assert math.atan2(rot[1, 0], rot[0, 0]) == pytest.approx(theta, abs=1e-9)
    assert t == pytest.approx(trans, abs=1e-9)
    assert rms < 1e-9


def test_rigid_fit_never_returns_a_reflection():
    local = rng.uniform(-50, 50, (8, 2))
    mirrored = local * np.array([-1, 1])                      # a mirror image cannot be matched by a rotation
    rot, _, rms = rigid_fit(local, mirrored)
    assert np.linalg.det(rot) == pytest.approx(1.0)
    assert rms > 1.0                                          # and the poor fit is visible in the error


def test_rigid_fit_with_noise_is_close():
    local = rng.uniform(-50, 50, (12, 2))
    observed = local @ rot2(0.7).T + np.array([10.0, -5.0]) + rng.normal(0, 0.2, (12, 2))
    rot, t, rms = rigid_fit(local, observed)
    assert math.atan2(rot[1, 0], rot[0, 0]) == pytest.approx(0.7, abs=0.01)
    assert t == pytest.approx([10.0, -5.0], abs=0.3)
    assert 0.05 < rms < 0.6


def test_rigid_fit_single_tag_of_four_points_is_enough():
    local = SQUARE + np.array([30.0, -10.0])
    observed = local @ rot2(1.0).T + np.array([5.0, 6.0])
    rot, t, rms = rigid_fit(local, observed)
    assert math.atan2(rot[1, 0], rot[0, 0]) == pytest.approx(1.0, abs=1e-9)
    assert rms < 1e-9


# ---------------------------------------------------------------- One Euro filter


def test_one_euro_first_value_passes_through():
    assert OneEuro()(np.array([0.3, 0.7]), 0.0) == pytest.approx([0.3, 0.7])


def test_one_euro_converges_to_a_constant_input():
    f = OneEuro()
    value = None
    for i in range(300):
        value = f(np.array([0.5, 0.5]), i * 0.01)
    assert value == pytest.approx([0.5, 0.5], abs=1e-6)


def test_one_euro_smooths_jitter_when_still():
    f = OneEuro(min_cutoff=1.0, beta=8.0)
    noisy = [0.5 + rng.normal(0, 0.005) for _ in range(400)]
    out = [float(f(np.array([v]), i * 0.01)[0]) for i, v in enumerate(noisy)]
    assert np.std(out[100:]) < 0.5 * np.std(noisy[100:])


def test_one_euro_follows_fast_motion_closely():
    f = OneEuro(min_cutoff=1.0, beta=8.0)
    lag = []
    for i in range(200):
        t = i * 0.01
        x = 0.3 * t                                            # steady 0.3 units/s ramp
        out = float(f(np.array([x]), t)[0])
        if i > 100:
            lag.append(x - out)
    assert max(lag) < 0.05


def test_higher_beta_means_less_lag():
    def final_lag(beta):
        f = OneEuro(min_cutoff=1.0, beta=beta)
        lag = 0
        for i in range(120):
            t = i * 0.01
            lag = 0.5 * t - float(f(np.array([0.5 * t]), t)[0])
        return lag

    assert final_lag(20.0) < final_lag(0.0)


def test_one_euro_reset_forgets_history():
    f = OneEuro()
    f(np.array([0.0]), 0.0)
    f(np.array([1.0]), 0.01)
    f.reset()
    assert f(np.array([5.0]), 1.0) == pytest.approx([5.0])


def test_one_euro_survives_zero_and_repeated_timestamps():
    f = OneEuro()
    f(np.array([0.2]), 1.0)
    out = f(np.array([0.4]), 1.0)                              # dt = 0 must not divide by zero
    assert np.isfinite(out).all()


# ---------------------------------------------------------------- layout learning


def test_learning_waits_for_all_tags_and_enough_frames():
    tracker = ToolTracker()
    tracker.start_learning(frames=3)
    assert tracker.feed_learning(corners_at(0, np.zeros(2), ids=(1, 2))) is False     # tag 3 missing: frame ignored
    assert tracker.learning
    results = [tracker.feed_learning(corners_at(0, np.zeros(2))) for _ in range(3)]
    assert results == [False, False, True]
    assert not tracker.learning and tracker.layout is not None


def test_learned_layout_is_centred_and_matches_the_geometry():
    tracker = trained_tracker()
    everything = np.vstack(list(tracker.layout.values()))
    assert everything.mean(axis=0) == pytest.approx([0, 0], abs=1e-9)
    truth = np.mean([np.array(TAG_CENTRES[i]) for i in TAG_CENTRES], axis=0)
    expected_tag1 = (SQUARE + np.array(TAG_CENTRES[1])) - (np.vstack(
        [SQUARE + np.array(TAG_CENTRES[i]) for i in TAG_CENTRES]).mean(axis=0))
    assert tracker.layout[1] == pytest.approx(expected_tag1, abs=1e-9)
    assert truth is not None


def test_learning_averages_out_noise():
    tracker = ToolTracker()
    tracker.start_learning(frames=60)
    for _ in range(60):
        tracker.feed_learning(corners_at(0.0, np.zeros(2), noise=0.5))
    clean = trained_tracker()
    error = np.abs(tracker.layout[2] - clean.layout[2]).max()
    assert error < 0.4


def test_feed_learning_when_not_learning_is_a_noop():
    assert ToolTracker().feed_learning(corners_at(0, np.zeros(2))) is False


# ---------------------------------------------------------------- pose estimation


@pytest.mark.parametrize("ids", [(1, 2, 3), (1, 2), (2, 3), (1, 3), (1,), (2,), (3,)])
def test_pose_is_exact_for_any_visible_subset(ids):
    tracker = trained_tracker()
    theta, t = 0.83, np.array([310.0, 205.0])
    pose = tracker.estimate(corners_at(theta, t, ids=ids))
    assert pose["tags"] == len(ids)
    assert pose["theta"] == pytest.approx(theta, abs=1e-9)
    assert pose["rms"] < 1e-9 and pose["quality"] == pytest.approx(1.0)


def test_origin_is_the_centre_of_all_three_tags():
    tracker = trained_tracker()
    t = np.array([50.0, 60.0])
    pose = tracker.estimate(corners_at(0.0, t))
    centre = np.mean([np.array(TAG_CENTRES[i]) for i in TAG_CENTRES], axis=0)
    assert pose["origin"] == pytest.approx(t + centre, abs=1e-9)


def test_no_tags_gives_no_pose():
    assert trained_tracker().estimate({}) is None
    assert ToolTracker().estimate({}) is None


def test_unknown_tag_ids_are_ignored():
    tracker = trained_tracker()
    detections = corners_at(0.2, np.array([10.0, 10.0]))
    detections[99] = detections[1] + 500                        # a stray tag elsewhere in the scene
    pose = tracker.estimate(detections)
    assert pose["tags"] == 3 and pose["rms"] < 1e-9


def test_a_misdetected_tag_is_rejected():
    tracker = trained_tracker()
    detections = corners_at(0.0, np.array([100.0, 100.0]))
    detections[2] = detections[2] + np.array([60.0, -40.0])     # tag 2 reported in the wrong place
    assert tracker.estimate(detections) is None


def test_small_noise_is_accepted_and_reduces_quality():
    tracker = trained_tracker()
    pose = tracker.estimate(corners_at(0.5, np.array([200.0, 100.0]), noise=0.3))
    assert pose is not None and 0.5 < pose["quality"] < 1.0


def test_without_a_layout_it_falls_back_to_the_average_of_the_tags():
    tracker = ToolTracker()
    detections = corners_at(0.0, np.array([10.0, 10.0]))
    pose = tracker.estimate(detections)
    assert pose["rigid"] is False
    assert pose["origin"] == pytest.approx(np.vstack(list(detections.values())).mean(axis=0))


def test_many_random_poses_stay_exact():
    tracker = trained_tracker()
    for _ in range(200):
        theta = rng.uniform(-math.pi, math.pi)
        t = rng.uniform(-500, 500, 2)
        ids = tuple(sorted(rng.choice([1, 2, 3], size=rng.integers(1, 4), replace=False)))
        pose = tracker.estimate(corners_at(theta, t, ids=ids))
        assert pose is not None
        assert math.remainder(pose["theta"] - theta, 2 * math.pi) == pytest.approx(0, abs=1e-8)


# ---------------------------------------------------------------- tip


def test_tip_follows_rotation():
    tracker = trained_tracker()
    reference = tracker.estimate(corners_at(0.0, np.array([100.0, 100.0])))
    tip_truth_local = np.array([0.0, 80.0])                     # a tip 80 mm along the tool's +y from its origin
    known = reference["origin"] + tip_truth_local
    tracker.calibrate_tip(reference, known)
    for theta in (0.0, 0.7, math.pi / 2, -2.0):
        t = np.array([220.0, -40.0])
        pose = tracker.estimate(corners_at(theta, t))
        assert pose["tip"] == pytest.approx(pose["origin"] + rot2(theta) @ tip_truth_local, abs=1e-8)


def test_tip_calibration_is_independent_of_the_reference_pose():
    tracker = trained_tracker()
    theta0, t0 = 1.1, np.array([300.0, 50.0])
    pose = tracker.estimate(corners_at(theta0, t0))
    tip_local = np.array([-12.0, 60.0])
    tracker.calibrate_tip(pose, pose["origin"] + rot2(theta0) @ tip_local)
    assert tracker.tip_local == pytest.approx(tip_local, abs=1e-9)


def test_default_tip_is_the_tool_origin():
    tracker = trained_tracker()
    pose = tracker.estimate(corners_at(0.3, np.array([5.0, 5.0])))
    assert pose["tip"] == pytest.approx(pose["origin"])


# ---------------------------------------------------------------- table homography


def test_homography_maps_table_corners_to_millimetres():
    tracker = ToolTracker()
    pixels = [(100, 80), (900, 120), (860, 640), (140, 600)]     # a skewed quad in the image
    tracker.set_table(pixels, (300.0, 220.0))
    plane = tracker.to_plane(pixels)
    assert plane == pytest.approx(np.array([[0, 0], [300, 0], [300, 220], [0, 220]], float), abs=1e-6)


def test_homography_maps_the_middle_correctly():
    tracker = ToolTracker()
    tracker.set_table([(0, 0), (1000, 0), (1000, 500), (0, 500)], (200.0, 100.0))
    assert tracker.to_plane([(500, 250)])[0] == pytest.approx([100, 50])


def test_without_a_homography_the_plane_is_the_image():
    assert ToolTracker().to_plane([(12, 34)])[0] == pytest.approx([12, 34])


def test_pose_in_millimetres_after_table_calibration():
    tracker = ToolTracker()
    tracker.set_table([(0, 0), (1000, 0), (1000, 500), (0, 500)], (200.0, 100.0))     # 5 px per mm
    tracker.start_learning(frames=2)
    px_corners = {i: (SQUARE * 5 + np.array(TAG_CENTRES[i]) * 5 + [500, 250]) for i in TAG_CENTRES}
    for _ in range(2):
        tracker.feed_learning(px_corners)
    moved = {i: c + np.array([100.0, 50.0]) for i, c in px_corners.items()}           # shift by 20 mm, 10 mm
    a = tracker.estimate(px_corners)["origin"]
    b = tracker.estimate(moved)["origin"]
    assert (b - a) == pytest.approx([20.0, 10.0], abs=1e-6)


def test_perspective_is_corrected():
    """Equal distances on the table must give equal plane distances even when the image is skewed."""
    tracker = ToolTracker()
    quad = [(200, 100), (800, 100), (1000, 600), (0, 600)]      # trapezoid: far edge is narrower
    tracker.set_table(quad, (300.0, 200.0))
    far = tracker.to_plane([(200, 100), (800, 100)])
    near = tracker.to_plane([(0, 600), (1000, 600)])
    assert np.linalg.norm(far[1] - far[0]) == pytest.approx(300.0)
    assert np.linalg.norm(near[1] - near[0]) == pytest.approx(300.0)


# ---------------------------------------------------------------- persistence


def test_save_and_load_round_trip(tmp_path):
    tracker = trained_tracker()
    tracker.set_table([(0, 0), (800, 0), (800, 600), (0, 600)], (240.0, 180.0))
    tracker.tip_local = np.array([3.0, 70.0])
    path = tmp_path / "cfg.json"
    tracker.save(str(path))

    loaded = ToolTracker()
    loaded.load(str(path))
    assert loaded.table_mm == (240.0, 180.0)
    assert loaded.homography == pytest.approx(tracker.homography)
    assert loaded.tip_local == pytest.approx([3.0, 70.0])
    for i in tracker.layout:
        assert loaded.layout[i] == pytest.approx(tracker.layout[i])
    assert json.loads(path.read_text())["layout"].keys() == {"1", "2", "3"}


def test_loading_an_empty_config_keeps_defaults(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text("{}")
    tracker = ToolTracker()
    tracker.load(str(path))
    assert tracker.homography is None and tracker.layout is None
    assert tracker.tip_local == pytest.approx([0, 0])


def test_loaded_tracker_estimates_like_the_original(tmp_path):
    tracker = trained_tracker()
    tracker.tip_local = np.array([0.0, 50.0])
    path = tmp_path / "cfg.json"
    tracker.save(str(path))
    loaded = ToolTracker()
    loaded.load(str(path))
    detections = corners_at(0.9, np.array([123.0, 45.0]), ids=(2, 3))
    assert loaded.estimate(detections)["tip"] == pytest.approx(tracker.estimate(detections)["tip"])
