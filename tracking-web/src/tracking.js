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

export class SignalSmoother {
  constructor({ minAlpha = 0.35, maxAlpha = 0.85, speedThreshold = 80, maxJumpPx = 65 } = {}) {
    this.x = null;
    this.y = null;
    this.angle = null;
    this.minAlpha = minAlpha;
    this.maxAlpha = maxAlpha;
    this.speedThreshold = speedThreshold;
    this.maxJumpPx = maxJumpPx;
    this.lastTimestampMs = 0;
  }

  filter(rawX, rawY, rawAngle, timestampMs = 0) {
    if (this.x === null || this.lastTimestampMs === 0) {
      this.x = rawX;
      this.y = rawY;
      this.angle = rawAngle;
      this.lastTimestampMs = timestampMs;
      return { x: rawX, y: rawY, angle: rawAngle, jumped: false };
    }

    const dt = Math.max(1, Math.min(300, timestampMs - this.lastTimestampMs || 33));
    this.lastTimestampMs = timestampMs;

    const rawDist = Math.hypot(rawX - this.x, rawY - this.y);
    let targetX = rawX;
    let targetY = rawY;
    let jumped = false;

    // Suppress sudden teleportations across frames (e.g. 180-deg flip or stray reflection)
    if (rawDist > this.maxJumpPx) {
      const ratio = this.maxJumpPx / rawDist;
      targetX = this.x + (rawX - this.x) * ratio;
      targetY = this.y + (rawY - this.y) * ratio;
      jumped = true;
    }

    // Dynamic alpha: stationary / slow motion -> high stability; rapid sweeps -> low latency
    const speed = rawDist / (dt / 1000);
    const t = Math.min(1, speed / (this.speedThreshold * 8));
    const alpha = this.minAlpha + (this.maxAlpha - this.minAlpha) * t;

    this.x = this.x + alpha * (targetX - this.x);
    this.y = this.y + alpha * (targetY - this.y);

    // Angle smoothing with 360-degree wrap-around
    if (this.angle !== null && rawAngle !== undefined && !Number.isNaN(rawAngle)) {
      let diff = (rawAngle - this.angle) % 360;
      if (diff > 180) diff -= 360;
      if (diff < -180) diff += 360;
      this.angle = (this.angle + alpha * diff) % 360;
    } else {
      this.angle = rawAngle;
    }

    return { x: this.x, y: this.y, angle: this.angle, jumped };
  }

  reset() {
    this.x = null;
    this.y = null;
    this.angle = null;
    this.lastTimestampMs = 0;
  }
}

export function isPurpleColor(r, g, b) {
  // Reject pure white glare, deep shadow/black, or extreme lightness
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  if (max < 45 || max > 250) return false;

  const delta = max - min;
  if (delta < 18) return false; // Reject greys / neutrals

  const sat = delta / max;
  if (sat < 0.15) return false; // Reject washed-out low-saturation tones

  // In purple/violet/magenta/lilac, Green is suppressed compared to Red and Blue
  if (g >= r - 6 && g >= b - 6) return false;
  if (g > (r + b) * 0.46) return false;

  // Standard HSV Hue calculation (0 to 360 degrees)
  let h = 0;
  if (max === r) {
    h = ((g - b) / delta + (g < b ? 6 : 0)) * 60;
  } else if (max === g) {
    return false; // Green cannot be dominant for purple
  } else {
    h = ((r - g) / delta + 4) * 60;
  }

  // Full purple / violet / magenta / lilac spectrum: 240° to 345°
  return h >= 240 && h <= 345;
}

export function detectPurpleScalpel(imageData, options = {}) {
  if (!imageData || !imageData.data) return null;
  const { width, height, data } = imageData;
  const step = options.step ?? 2;
  const minPixels = options.minPixels ?? 20;

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

  // 2. Spatial clustering: grid-based connected components with finger-gap bridging
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
          // Search up to 2 cells away (Chebyshev dist <= 2) to bridge finger occlusion gaps (~32px)
          for (let dr = -2; dr <= 2; dr += 1) {
            for (let dc = -2; dc <= 2; dc += 1) {
              if (dr === 0 && dc === 0) continue;
              const nr = curr.r + dr;
              const nc = curr.c + dc;
              if (nr >= 0 && nr < rows && nc >= 0 && nc < cols) {
                const nIdx = nr * cols + nc;
                const req = Math.max(Math.abs(dr), Math.abs(dc)) === 1 ? 2 : 3;
                if (grid[nIdx] >= req && labels[nIdx] === 0) {
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
        }

        const compW = (maxC - minC + 1) * cellSize;
        const compH = (maxR - minR + 1) * cellSize;
        const major = Math.max(compW, compH);
        const minor = Math.max(1, Math.min(compW, compH));
        const aspect = major / minor;

        // Scalpel tool must be elongated and of reasonable size
        if (count >= minPixels && major >= 18 && aspect >= 1.2) {
          components.push({
            label: currentLabel,
            count,
            aspect,
            major,
            cx: (minC + maxC + 1) * cellSize / 2,
            cy: (minR + maxR + 1) * cellSize / 2,
          });
        }
        currentLabel += 1;
      }
    }
  }

  if (components.length === 0) return null;

  // Pick the primary scalpel body (elongated stick)
  components.sort((a, b) => (b.major * b.aspect) - (a.major * a.aspect));
  const bestComp = components[0];
  const activeLabels = new Set([bestComp.label]);

  // Collinear tool merging across hand occlusion: unite blade tip with handle
  for (let i = 1; i < components.length; i += 1) {
    const comp = components[i];
    const dx = comp.cx - bestComp.cx;
    const dy = comp.cy - bestComp.cy;
    const centerDist = Math.hypot(dx, dy);
    if (centerDist < 140) {
      activeLabels.add(comp.label);
    }
  }

  // Collect points belonging to active scalpel component(s)
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
    if (activeLabels.has(labels[r * cols + c])) {
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

  // Measure thickness (perp spread) near End A vs End B
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

  // SELECT THE WORKING SURGICAL TIP ("el final, no tot"):
  // Prioritize continuity if previously tracked, then downward surface orientation, then taper
  let isEndATip;
  const previousTip = options.previousTip;

  if (previousTip && typeof previousTip.x === 'number' && typeof previousTip.y === 'number') {
    const distA = Math.hypot(endA.x - previousTip.x, endA.y - previousTip.y);
    const distB = Math.hypot(endB.x - previousTip.x, endB.y - previousTip.y);
    if (Math.abs(distA - distB) >= 20) {
      // Firm lock: tip cannot flip 180° to the other end of the stick
      isEndATip = distA < distB;
    } else {
      const deltaY = endA.y - endB.y;
      isEndATip = Math.abs(deltaY) >= 12 ? deltaY > 0 : thickA <= thickB;
    }
  } else {
    // Initial detection: Tabletop surgical tool blade points downwards towards the surface
    const deltaY = endA.y - endB.y;
    if (Math.abs(deltaY) >= 14) {
      isEndATip = deltaY > 0;
    } else {
      isEndATip = thickA <= thickB;
    }
  }

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
