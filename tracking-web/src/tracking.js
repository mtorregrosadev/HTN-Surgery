import arucoPackage from 'js-aruco2';
import 'js-aruco2/src/dictionaries/aruco_4x4_1000.js';

const { AR } = arucoPackage;

export const DICTIONARIES = {
  SURGE_PREP: 'ARUCO_MIP_36h12',
  OPENCV_4X4_50: 'OPENCV_4X4_50',
};
export const DEFAULT_DICTIONARY = DICTIONARIES.SURGE_PREP;
export const TARGET_MARKER_ID = 0;
export const MAX_PATH_POINTS = 180;

AR.DICTIONARIES[DICTIONARIES.OPENCV_4X4_50] = {
  ...AR.DICTIONARIES.ARUCO_4X4_1000,
  codeList: AR.DICTIONARIES.ARUCO_4X4_1000.codeList.slice(0, 50),
};

export function createDetector(dictionaryName = DEFAULT_DICTIONARY) {
  if (!Object.values(DICTIONARIES).includes(dictionaryName)) throw new Error('Unsupported marker dictionary');
  return new AR.Detector({ dictionaryName });
}

export function markerSvg(dictionaryName = DEFAULT_DICTIONARY) {
  if (!Object.values(DICTIONARIES).includes(dictionaryName)) throw new Error('Unsupported marker dictionary');
  return new AR.Dictionary(dictionaryName).generateSVG(TARGET_MARKER_ID);
}

export function selectMarker(markers, dictionaryName = DEFAULT_DICTIONARY) {
  if (dictionaryName === DICTIONARIES.OPENCV_4X4_50) {
    return markers.reduce((largest, marker) => {
      const size = marker.corners.reduce((sum, corner, index) => {
        const next = marker.corners[(index + 1) % 4];
        return sum + Math.hypot(next.x - corner.x, next.y - corner.y);
      }, 0);
      return !largest || size > largest.size ? { marker, size } : largest;
    }, null)?.marker ?? null;
  }
  return markers.find((marker) => marker.id === TARGET_MARKER_ID) ?? null;
}

export function markerPose2d(marker, timestampMs) {
  if (!marker || marker.corners?.length !== 4) return null;
  const { corners } = marker;
  const x = corners.reduce((sum, corner) => sum + corner.x, 0) / 4;
  const y = corners.reduce((sum, corner) => sum + corner.y, 0) / 4;
  const dx = corners[1].x - corners[0].x;
  const dy = corners[1].y - corners[0].y;
  const edgeLengths = corners.map((corner, index) => {
    const next = corners[(index + 1) % 4];
    return Math.hypot(next.x - corner.x, next.y - corner.y);
  });
  return {
    markerId: marker.id,
    x,
    y,
    angleDeg: Math.atan2(dy, dx) * 180 / Math.PI,
    sizePx: edgeLengths.reduce((sum, length) => sum + length, 0) / 4,
    corners,
    timestampMs,
  };
}

export function estimatedDepthMm(reference, markerSizePx) {
  if (!reference || !Number.isFinite(markerSizePx) || markerSizePx <= 0) return null;
  const { distanceMm, sizePx } = reference;
  if (!Number.isFinite(distanceMm) || distanceMm <= 0 || !Number.isFinite(sizePx) || sizePx <= 0) return null;
  return distanceMm * sizePx / markerSizePx;
}

export function movementSpeed(previous, current) {
  if (!previous || !current) return null;
  const elapsedSeconds = (current.timestampMs - previous.timestampMs) / 1000;
  if (elapsedSeconds <= 0 || elapsedSeconds > 0.5) return null;
  return Math.hypot(current.x - previous.x, current.y - previous.y) / elapsedSeconds;
}

export function appendPath(path, pose) {
  if (!pose) return path;
  const last = path.at(-1);
  if (last && Math.hypot(pose.x - last.x, pose.y - last.y) < 2) return path;
  return [...path, { x: pose.x, y: pose.y }].slice(-MAX_PATH_POINTS);
}
