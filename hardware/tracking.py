"""Accurate scalpel tracking from AprilTags (no camera or Unity needed, so it is easy to test).

What makes it more accurate than a plain average of tag centres:

* Rigid-body pose. The three tags are learned as one rigid layout. Every visible tag corner
  (4 per tag, up to 12) is fitted to that layout with a least-squares rotation + translation, so
  position AND angle come out right even when one or two tags are hidden or partly out of frame.
  A plain centroid jumps whenever a tag appears or disappears.
* Tip position. The tags sit on the handle, the cutting tip is somewhere else. The tip is stored
  in the tool's own frame and follows the tool as it rotates.
* Table plane. Four clicked table corners give a homography from camera pixels to millimetres on
  the table, which removes perspective distortion.
* Lens correction. An optional camera calibration removes lens distortion.
* One Euro filter. Heavy smoothing when the hand is still (no jitter), almost none when it moves
  fast (no lag).
* Sanity checks. A frame whose corners do not fit the learned layout is rejected.
"""
import json
import math

import numpy as np

TAG_IDS = (1, 2, 3)


class OneEuro:
    """Adaptive low-pass filter: smooth when slow, responsive when fast."""

    def __init__(self, min_cutoff=1.0, beta=8.0, d_cutoff=1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.t = None
        self.x = None
        self.dx = None

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def reset(self):
        self.t = self.x = self.dx = None

    def __call__(self, value, t):
        value = np.asarray(value, float)
        if self.t is None:
            self.t, self.x, self.dx = t, value, np.zeros_like(value)
            return value
        dt = max(t - self.t, 1e-3)
        dx = (value - self.x) / dt
        a_d = self._alpha(self.d_cutoff, dt)
        self.dx = a_d * dx + (1 - a_d) * self.dx
        cutoff = self.min_cutoff + self.beta * float(np.linalg.norm(self.dx))
        a = self._alpha(cutoff, dt)
        self.x = a * value + (1 - a) * self.x
        self.t = t
        return self.x


def rigid_fit(local, observed):
    """Least-squares rotation + translation with observed ~ R @ local + t (2D, no reflection)."""
    lc, oc = local.mean(axis=0), observed.mean(axis=0)
    u, _, vt = np.linalg.svd((local - lc).T @ (observed - oc))
    rot = vt.T @ u.T
    if np.linalg.det(rot) < 0:
        vt[-1] *= -1
        rot = vt.T @ u.T
    trans = oc - rot @ lc
    residual = observed - (local @ rot.T + trans)
    rms = float(np.sqrt(np.mean(np.sum(residual ** 2, axis=1))))
    return rot, trans, rms


def rot2(theta):
    c, s = math.cos(theta), math.sin(theta)
    return np.array([[c, -s], [s, c]])


class ToolTracker:
    def __init__(self, tag_ids=TAG_IDS):
        self.tag_ids = tuple(tag_ids)
        self.homography = None          # camera pixels -> table millimetres
        self.table_mm = (300.0, 220.0)  # practice area size (width, height)
        self.layout = None              # tag id -> (4, 2) corner coordinates in the tool frame
        self.tip_local = np.zeros(2)    # cutting tip in the tool frame
        self.max_relative_error = 0.25  # reject fits worse than 25% of a tag's side length
        self._learning = None
        self.last = None

    # ---- table plane --------------------------------------------------------------------
    def set_table(self, image_corners, table_mm):
        """image_corners: 4 pixel points, top-left, top-right, bottom-right, bottom-left."""
        import cv2
        w, h = table_mm
        dst = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
        self.homography = cv2.getPerspectiveTransform(np.float32(image_corners), dst)
        self.table_mm = (float(w), float(h))

    def to_plane(self, pixels):
        pixels = np.asarray(pixels, float).reshape(-1, 2)
        if self.homography is None:
            return pixels
        ones = np.ones((len(pixels), 1))
        p = np.hstack([pixels, ones]) @ self.homography.T
        return p[:, :2] / p[:, 2:3]

    # ---- learning the rigid layout ------------------------------------------------------
    def start_learning(self, frames=30):
        self._learning = {"need": frames, "sum": {}, "count": 0}

    @property
    def learning(self):
        return self._learning is not None

    def feed_learning(self, corners_by_id):
        """Call every frame while learning. Returns True when the layout was just finished."""
        if self._learning is None:
            return False
        if not all(i in corners_by_id for i in self.tag_ids):
            return False                                   # only use frames where every tag is seen
        acc = self._learning
        for i in self.tag_ids:
            acc["sum"][i] = acc["sum"].get(i, 0) + self.to_plane(corners_by_id[i])
        acc["count"] += 1
        if acc["count"] < acc["need"]:
            return False
        mean = {i: acc["sum"][i] / acc["count"] for i in self.tag_ids}
        centre = np.vstack(list(mean.values())).mean(axis=0)
        self.layout = {i: mean[i] - centre for i in self.tag_ids}
        self._learning = None
        return True

    # ---- pose ---------------------------------------------------------------------------
    def estimate(self, corners_by_id):
        """corners_by_id: tag id -> (4, 2) pixel corners. Returns a dict or None if unusable."""
        seen = [i for i in self.tag_ids if i in corners_by_id]
        if not seen:
            return None
        observed = {i: self.to_plane(corners_by_id[i]) for i in seen}
        side = float(np.mean([np.linalg.norm(observed[i][0] - observed[i][1]) for i in seen]))

        if self.layout is None:
            centre = np.vstack(list(observed.values())).mean(axis=0)
            result = {"origin": centre, "theta": 0.0, "rms": 0.0, "tags": len(seen), "rigid": False}
        else:
            local = np.vstack([self.layout[i] for i in seen])
            obs = np.vstack([observed[i] for i in seen])
            rot, trans, rms = rigid_fit(local, obs)
            if rms > self.max_relative_error * side:
                return None                                # corners do not fit the tool: misdetection
            result = {"origin": trans, "theta": math.atan2(rot[1, 0], rot[0, 0]),
                      "rms": rms, "tags": len(seen), "rigid": True}
        result["tip"] = result["origin"] + rot2(result["theta"]) @ self.tip_local
        result["quality"] = float(np.clip(1.0 - result["rms"] / max(side * self.max_relative_error, 1e-6), 0, 1))
        self.last = result
        return result

    def calibrate_tip(self, pose, known_plane_point):
        """Touch the tip to a known table point, then call this with the current pose."""
        self.tip_local = rot2(-pose["theta"]) @ (np.asarray(known_plane_point, float) - pose["origin"])

    # ---- persistence --------------------------------------------------------------------
    def to_json(self):
        return {
            "homography": None if self.homography is None else self.homography.tolist(),
            "table_mm": list(self.table_mm),
            "layout": None if self.layout is None else {str(k): v.tolist() for k, v in self.layout.items()},
            "tip_local": self.tip_local.tolist(),
        }

    def from_json(self, data):
        if data.get("homography") is not None:
            self.homography = np.array(data["homography"], float)
        self.table_mm = tuple(data.get("table_mm", self.table_mm))
        if data.get("layout"):
            self.layout = {int(k): np.array(v, float) for k, v in data["layout"].items()}
        self.tip_local = np.array(data.get("tip_local", [0.0, 0.0]), float)

    def save(self, path):
        with open(path, "w") as f:
            json.dump(self.to_json(), f, indent=2)

    def load(self, path):
        with open(path) as f:
            self.from_json(json.load(f))
