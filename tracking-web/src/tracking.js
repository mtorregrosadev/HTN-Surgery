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
  // Reject blown-out white glare, extreme darkness, or non-dominant blue
  if (b < 55 || b > 238) return false;
  // Lilac plastic: Blue is the dominant channel, Red is secondary, Green is lowest
  if (b < r + 4 || b < g + 10 || r < g - 2) return false;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const delta = max - min;
  if (delta < 12) return false;
  const sat = delta / max;
  if (sat < 0.12 || sat > 0.85) return false;

  // Hue calculation (where max === b)
  let h = ((r - g) / delta + 4) * 60;
  if (h < 0) h += 360;
  return h >= 245 && h <= 292;
}

export function detectPurpleScalpel(imageData, options = {}) {
  if (!imageData || !imageData.data) return null;
  const { width, height, data } = imageData;
  const step = options.step ?? 2;
  const minPixels = options.minPixels ?? 30;

  // 1. Scan and collect lilac pixels
  const pts = [];
  for (let y = 0; y < height; y += step) {
    const rowOffset = y * width * 4;
    for (let x = 0; x < width; x += step) {
      const idx = rowOffset + x * 4;
      if (isPurpleColor(data[idx], data[idx + 1], data[idx + 2])) {
        pts.push({ x, y });
      }
    }
  }

  if (pts.length < minPixels) return null;

  // 2. Spatial clustering: grid-based connected components to reject scattered noise/reflections
  const cellSize = 16;
  const cols = Math.ceil(width / cellSize);
  const rows = Math.ceil(height / cellSize);
  const grid = new Int32Array(cols * rows);

  for (let i = 0; i < pts.length; i += 1) {
    const c = Math.floor(pts[i].x / cellSize);
    const r = Math.floor(pts[i].y / cellSize);
    grid[r * cols + c] += 1;
  }

  const labels = new Int32Array(cols * rows);
  let currentLabel = 1;
  const components = [];

  for (let r = 0; r < rows; r += 1) {
    for (let c = 0; c < cols; c += 1) {
      const idx = r * cols + c;
      if (grid[idx] >= 2 && labels[idx] === 0) {
        const queue = [{ r, c }];
        labels[idx] = currentLabel;
        let count = grid[idx];
        let minC = c;
        let maxC = c;
        let minR = r;
        let maxR = r;

        while (queue.length > 0) {
          const curr = queue.pop();
          const neighbors = [
            { r: curr.r - 1, c: curr.c },
            { r: curr.r + 1, c: curr.c },
            { r: curr.r, c: curr.c - 1 },
            { r: curr.r, c: curr.c + 1 },
            { r: curr.r - 1, c: curr.c - 1 },
            { r: curr.r - 1, c: curr.c + 1 },
            { r: curr.r + 1, c: curr.c - 1 },
            { r: curr.r + 1, c: curr.c + 1 },
          ];
          for (let n = 0; n < neighbors.length; n += 1) {
            const nr = neighbors[n].r;
            const nc = neighbors[n].c;
            if (nr >= 0 && nr < rows && nc >= 0 && nc < cols) {
              const nIdx = nr * cols + nc;
              if (grid[nIdx] >= 2 && labels[nIdx] === 0) {
                labels[nIdx] = currentLabel;
                queue.push({ r: nr, c: nc });
                count += grid[nIdx];
                if (nc < minC) minC = nc;
                if (nc > maxC) maxC = nc;
                if (nr < minR) minR = nr;
                if (nr > maxR) maxR = nr;
              }
            }
          }
        }

        const compW = (maxC - minC + 1) * cellSize;
        const compH = (maxR - minR + 1) * cellSize;
        const major = Math.max(compW, compH);
        const minor = Math.max(1, Math.min(compW, compH));
        const aspect = major / minor;

        // Scalpel tool must be elongated and of reasonable size (rejects round faces / squares)
        if (count >= minPixels && major >= 28 && aspect >= 1.5) {
          components.push({
            label: currentLabel,
            count,
            minX: minC * cellSize,
            maxX: (maxC + 1) * cellSize,
            minY: minR * cellSize,
            maxY: (maxR + 1) * cellSize,
            aspect,
          });
        }
        currentLabel += 1;
      }
    }
  }

  if (components.length === 0) return null;

  // Pick the most scalpel-like elongated component
  components.sort((a, b) => (b.count * b.aspect) - (a.count * a.aspect));
  const bestComp = components[0];

  // Collect points belonging to best component
  const compPts = [];
  let sumX = 0;
  let sumY = 0;
  let minX = width;
  let maxX = 0;
  let minY = height;
  let maxY = 0;
  for (let i = 0; i < pts.length; i += 1) {
    const c = Math.floor(pts[i].x / cellSize);
    const r = Math.floor(pts[i].y / cellSize);
    if (labels[r * cols + c] === bestComp.label) {
      compPts.push(pts[i]);
      sumX += pts[i].x;
      sumY += pts[i].y;
      if (pts[i].x < minX) minX = pts[i].x;
      if (pts[i].x > maxX) maxX = pts[i].x;
      if (pts[i].y < minY) minY = pts[i].y;
      if (pts[i].y > maxY) maxY = pts[i].y;
    }
  }

  if (compPts.length < minPixels) return null;

  const cx = sumX / compPts.length;
  const cy = sumY / compPts.length;

  // Compute principal axis using 2nd central moments
  let mu20 = 0;
  let mu02 = 0;
  let mu11 = 0;
  for (let i = 0; i < compPts.length; i += 1) {
    const dx = compPts[i].x - cx;
    const dy = compPts[i].y - cy;
    mu20 += dx * dx;
    mu02 += dy * dy;
    mu11 += dx * dy;
  }

  const theta = 0.5 * Math.atan2(2 * mu11, mu20 - mu02);
  const cosTheta = Math.cos(theta);
  const sinTheta = Math.sin(theta);

  // Project points along principal axis
  let minProj = Infinity;
  let maxProj = -Infinity;
  let endA = { x: cx, y: cy };
  let endB = { x: cx, y: cy };

  for (let i = 0; i < compPts.length; i += 1) {
    const proj = (compPts[i].x - cx) * cosTheta + (compPts[i].y - cy) * sinTheta;
    if (proj < minProj) {
      minProj = proj;
      endA = compPts[i];
    }
    if (proj > maxProj) {
      maxProj = proj;
      endB = compPts[i];
    }
  }

  const projRange = maxProj - minProj;
  if (projRange < 18) return null;

  // Measure thickness (perp spread) near End A vs End B to identify the cutting TIP
  let perpSumSqA = 0;
  let countA = 0;
  let perpSumSqB = 0;
  let countB = 0;

  for (let i = 0; i < compPts.length; i += 1) {
    const proj = (compPts[i].x - cx) * cosTheta + (compPts[i].y - cy) * sinTheta;
    const perp = -(compPts[i].x - cx) * sinTheta + (compPts[i].y - cy) * cosTheta;
    if (proj < minProj + 0.22 * projRange) {
      perpSumSqA += perp * perp;
      countA += 1;
    }
    if (proj > maxProj - 0.22 * projRange) {
      perpSumSqB += perp * perp;
      countB += 1;
    }
  }

  const thickA = countA > 0 ? Math.sqrt(perpSumSqA / countA) : 999;
  const thickB = countB > 0 ? Math.sqrt(perpSumSqB / countB) : 999;

  // The tip ("el final") is the narrower / tapered end
  const isEndATip = thickA <= thickB;
  const tip = isEndATip ? endA : endB;
  const base = isEndATip ? endB : endA;

  return {
    x: tip.x,
    y: tip.y,
    tipX: tip.x,
    tipY: tip.y,
    baseX: base.x,
    baseY: base.y,
    centroidX: cx,
    centroidY: cy,
    angleDeg: (theta * 180) / Math.PI,
    length: projRange,
    tipThickness: Math.min(thickA, thickB),
    pixelCount: compPts.length * step * step,
    minX,
    maxX,
    minY,
    maxY,
    aspect: bestComp.aspect,
    confidence: Math.min(1, compPts.length / 50),
  };
}
