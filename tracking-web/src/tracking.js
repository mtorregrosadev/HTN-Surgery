import arucoPackage from 'js-aruco2';
import 'js-aruco2/src/dictionaries/aruco_4x4_1000.js';
import 'js-aruco2/src/dictionaries/aruco_5x5_1000.js';

const { AR } = arucoPackage;

export const DICTIONARIES = {
  SURGE_PREP: 'ARUCO_MIP_36h12',
  OPENCV_4X4_50: 'OPENCV_4X4_50',
  OPENCV_5X5_250: 'OPENCV_5X5_250',
};
export const DEFAULT_DICTIONARY = DICTIONARIES.OPENCV_5X5_250;
export const TARGET_MARKER_ID = 0;
export const MAX_PATH_POINTS = 180;
export const CALIBRATION_FRAMES = 8;

AR.DICTIONARIES[DICTIONARIES.OPENCV_4X4_50] = {
  ...AR.DICTIONARIES.ARUCO_4X4_1000,
  codeList: AR.DICTIONARIES.ARUCO_4X4_1000.codeList.slice(0, 50),
};
AR.DICTIONARIES[DICTIONARIES.OPENCV_5X5_250] = {
  ...AR.DICTIONARIES.ARUCO_5X5_1000,
  codeList: AR.DICTIONARIES.ARUCO_5X5_1000.codeList.slice(0, 250),
};

const MAX_CORRECTION_BITS = {
  [DICTIONARIES.SURGE_PREP]: 5,
  [DICTIONARIES.OPENCV_4X4_50]: 1,
  [DICTIONARIES.OPENCV_5X5_250]: 2,
};

const GEOMETRY_EPSILON = 1e-8;

export function createDetector(dictionaryName = DEFAULT_DICTIONARY) {
  if (!Object.values(DICTIONARIES).includes(dictionaryName)) throw new Error('Unsupported marker dictionary');
  return new AR.Detector({ dictionaryName });
}

export function markerSvg(dictionaryName = DEFAULT_DICTIONARY) {
  if (!Object.values(DICTIONARIES).includes(dictionaryName)) throw new Error('Unsupported marker dictionary');
  return new AR.Dictionary(dictionaryName).generateSVG(TARGET_MARKER_ID);
}

function cross(ax, ay, bx, by) {
  return ax * by - ay * bx;
}

function crossPoints(a, b, c) {
  return cross(b.x - a.x, b.y - a.y, c.x - a.x, c.y - a.y);
}

function finitePoint(point) {
  return point && Number.isFinite(point.x) && Number.isFinite(point.y);
}

/**
 * Return the intersection of two finite line segments, or null when they are
 * parallel/degenerate. The marker diagonals are segments, not infinite lines,
 * so checking the parameters also rejects crossed or malformed corner lists.
 */
function segmentIntersection(startA, endA, startB, endB) {
  const directionA = { x: endA.x - startA.x, y: endA.y - startA.y };
  const directionB = { x: endB.x - startB.x, y: endB.y - startB.y };
  const denominator = cross(directionA.x, directionA.y, directionB.x, directionB.y);
  const offset = { x: startB.x - startA.x, y: startB.y - startA.y };
  const scale = Math.max(
    Math.hypot(directionA.x, directionA.y),
    Math.hypot(directionB.x, directionB.y),
    1,
  );
  if (!Number.isFinite(denominator) || Math.abs(denominator) <= GEOMETRY_EPSILON * scale * scale) return null;
  const parameterA = cross(offset.x, offset.y, directionB.x, directionB.y) / denominator;
  const parameterB = cross(offset.x, offset.y, directionA.x, directionA.y) / denominator;
  if (
    parameterA < -GEOMETRY_EPSILON || parameterA > 1 + GEOMETRY_EPSILON ||
    parameterB < -GEOMETRY_EPSILON || parameterB > 1 + GEOMETRY_EPSILON
  ) return null;
  return {
    x: startA.x + parameterA * directionA.x,
    y: startA.y + parameterA * directionA.y,
  };
}

/**
 * ArUco returns corners in perimeter order. A valid marker must be a finite,
 * non-self-intersecting convex quadrilateral; otherwise a false center can
 * contaminate the path and depth estimate. The diagonal intersection is the
 * projective image of the square's center and remains correct under oblique
 * views where the mean of four image corners is biased.
 */
export function projectiveMarkerCenter(corners) {
  if (!Array.isArray(corners) || corners.length !== 4 || corners.some((corner) => !finitePoint(corner))) return null;
  const edgeLengths = corners.map((corner, index) => {
    const next = corners[(index + 1) % corners.length];
    return Math.hypot(next.x - corner.x, next.y - corner.y);
  });
  const scale = Math.max(...edgeLengths);
  if (!Number.isFinite(scale) || scale <= GEOMETRY_EPSILON || edgeLengths.some((length) => length <= GEOMETRY_EPSILON)) return null;

  const signedCorners = corners.map((corner, index) => crossPoints(corner, corners[(index + 1) % 4], corners[(index + 2) % 4]));
  const orientation = Math.sign(signedCorners[0]);
  const areaTolerance = GEOMETRY_EPSILON * scale * scale;
  if (
    !orientation ||
    signedCorners.some((turn) => Math.abs(turn) <= areaTolerance || Math.sign(turn) !== orientation)
  ) return null;

  return segmentIntersection(corners[0], corners[2], corners[1], corners[3]);
}

function markerGeometryValid(marker) {
  return Boolean(projectiveMarkerCenter(marker?.corners));
}

function markerSize(corners) {
  return corners.reduce((sum, corner, index) => {
    const next = corners[(index + 1) % corners.length];
    return sum + Math.hypot(next.x - corner.x, next.y - corner.y);
  }, 0) / corners.length;
}

/**
 * Select one decoded marker. Pass the previously selected ID to keep the
 * target stable through frames; a missing locked ID returns null instead of
 * silently switching to another square. Pass null/undefined only for an
 * explicit selection reset (source restart or dictionary change in the UI).
 */
export function selectMarker(markers, dictionaryName = DEFAULT_DICTIONARY, lockedMarkerId = null) {
  if (!Array.isArray(markers)) return null;
  const maxCorrectionBits = MAX_CORRECTION_BITS[dictionaryName];
  const validMarkers = markers.filter((marker) => (
    marker &&
    Number.isFinite(marker.hammingDistance) &&
    marker.hammingDistance <= maxCorrectionBits &&
    markerGeometryValid(marker)
  ));
  if (lockedMarkerId !== null && lockedMarkerId !== undefined) {
    return validMarkers.find((marker) => marker.id === lockedMarkerId) ?? null;
  }
  if (dictionaryName === DICTIONARIES.SURGE_PREP) {
    return validMarkers.find((marker) => marker.id === TARGET_MARKER_ID) ?? null;
  }
  return validMarkers.reduce((largest, marker) => {
    const size = markerSize(marker.corners);
    return !largest || size > largest.size ? { marker, size } : largest;
  }, null)?.marker ?? null;
}

export function markerPose2d(marker, timestampMs) {
  if (!marker || !Array.isArray(marker.corners) || marker.corners.length !== 4) return null;
  const { corners } = marker;
  const center = projectiveMarkerCenter(corners);
  if (!center) return null;
  const dx = corners[1].x - corners[0].x;
  const dy = corners[1].y - corners[0].y;
  return {
    markerId: marker.id,
    x: center.x,
    y: center.y,
    angleDeg: Math.atan2(dy, dx) * 180 / Math.PI,
    sizePx: markerSize(corners),
    corners,
    timestampMs,
  };
}

export function relativeDepthPercent(reference, markerSizePx) {
  if (!reference || !Number.isFinite(markerSizePx) || markerSizePx <= 0) return null;
  const { sizePx } = reference;
  if (!Number.isFinite(sizePx) || sizePx <= 0) return null;
  return 100 * (sizePx / markerSizePx - 1);
}

export function demoMarkerState(frame) {
  return {
    x: 320 + Math.sin(frame / 24) * 100,
    y: 240 + Math.sin(frame / 37) * 60,
    sidePx: 150 / (1 + 0.3 * Math.sin(frame / 25)),
    angleRad: Math.sin(frame / 39) * 0.15,
  };
}

export function advanceDepthCalibration(samples, pose) {
  if (!pose || !Number.isFinite(pose.sizePx) || pose.sizePx <= 0) {
    return { samples: [], reference: null };
  }
  const first = samples[0];
  if (first && (
    pose.markerId !== first.markerId ||
    Math.hypot(pose.x - first.x, pose.y - first.y) > 12 ||
    Math.abs(pose.sizePx - first.sizePx) > first.sizePx * 0.05
  )) {
    samples = [];
  }
  const next = [...samples, pose].slice(-CALIBRATION_FRAMES);
  if (next.length < CALIBRATION_FRAMES) return { samples: next, reference: null };
  const sizes = next.map((item) => item.sizePx).sort((a, b) => a - b);
  const sizePx = (sizes[3] + sizes[4]) / 2;
  return { samples: next, reference: { sizePx, markerId: pose.markerId } };
}

export function movementSpeed(previous, current) {
  if (!previous || !current) return null;
  const elapsedSeconds = (current.timestampMs - previous.timestampMs) / 1000;
  if (elapsedSeconds <= 0 || elapsedSeconds > 0.5) return null;
  return Math.hypot(current.x - previous.x, current.y - previous.y) / elapsedSeconds;
}

export function appendPath(path, pose, isContinuous = true) {
  if (!pose) return path;
  const last = path.at(-1);
  if (last && isContinuous && Math.hypot(pose.x - last.x, pose.y - last.y) < 2) return path;
  return [...path, { x: pose.x, y: pose.y, continuous: isContinuous }].slice(-MAX_PATH_POINTS);
}

export function isPurpleColor(r, g, b) {
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const delta = max - min;
  if (max < 38 || delta < 22) return false;
  if (delta / max < 0.20) return false;
  if (g > r * 0.90 || g > b * 0.90) return false;
  let h = 0;
  if (max === r) h = ((g - b) / delta) % 6;
  else if (max === g) return false;
  else h = (r - g) / delta + 4;
  h = Math.round(h * 60);
  if (h < 0) h += 360;
  return h >= 245 && h <= 345;
}

export function detectPurpleScalpel(imageData, options = {}) {
  if (!imageData || !imageData.data) return null;
  const { width, height, data } = imageData;
  const step = options.step ?? 2;
  const minPixels = options.minPixels ?? 15;

  let count = 0;
  let sumX = 0;
  let sumY = 0;
  let minX = width;
  let minY = height;
  let maxX = 0;
  let maxY = 0;

  for (let y = 0; y < height; y += step) {
    const rowOffset = y * width * 4;
    for (let x = 0; x < width; x += step) {
      const idx = rowOffset + x * 4;
      if (isPurpleColor(data[idx], data[idx + 1], data[idx + 2])) {
        count += 1;
        sumX += x;
        sumY += y;
        if (x < minX) minX = x;
        if (x > maxX) maxX = x;
        if (y < minY) minY = y;
        if (y > maxY) maxY = y;
      }
    }
  }

  if (count < minPixels) return null;

  const cx = sumX / count;
  const cy = sumY / count;
  let mu20 = 0;
  let mu02 = 0;
  let mu11 = 0;
  let maxDistSq = 0;
  let tipX = cx;
  let tipY = cy;

  for (let y = minY; y <= maxY; y += step) {
    const rowOffset = y * width * 4;
    for (let x = minX; x <= maxX; x += step) {
      const idx = rowOffset + x * 4;
      if (isPurpleColor(data[idx], data[idx + 1], data[idx + 2])) {
        const dx = x - cx;
        const dy = y - cy;
        mu20 += dx * dx;
        mu02 += dy * dy;
        mu11 += dx * dy;
        const distSq = dx * dx + dy * dy;
        if (distSq > maxDistSq) {
          maxDistSq = distSq;
          tipX = x;
          tipY = y;
        }
      }
    }
  }

  const angleRad = 0.5 * Math.atan2(2 * mu11, mu20 - mu02);
  const angleDeg = (angleRad * 180) / Math.PI;

  return {
    x: cx,
    y: cy,
    tipX,
    tipY,
    minX,
    minY,
    maxX,
    maxY,
    width: maxX - minX,
    height: maxY - minY,
    pixelCount: count * step * step,
    angleDeg,
    confidence: Math.min(1, count / 60),
  };
}
