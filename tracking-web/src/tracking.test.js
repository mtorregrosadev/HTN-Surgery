import test from 'node:test';
import assert from 'node:assert/strict';
import { advanceDepthCalibration, appendPath, CALIBRATION_FRAMES, createDetector, DICTIONARIES, estimatedDepthMm, markerPose2d, markerSvg, movementSpeed, selectMarker } from './tracking.js';

function makeMarkerImage(detector, markerId) {
  const size = 320;
  const data = new Uint8ClampedArray(size * size * 4);
  const bits = detector.dictionary.codeList[markerId];
  const markerSize = detector.dictionary.markSize;
  const innerSize = markerSize - 2;
  const cellSize = 20;
  const offset = Math.floor((size - markerSize * cellSize) / 2);
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const markerX = Math.floor((x - offset) / cellSize);
      const markerY = Math.floor((y - offset) / cellSize);
      const inside = markerX >= 0 && markerX < markerSize && markerY >= 0 && markerY < markerSize;
      const inner = markerX > 0 && markerX < markerSize - 1 && markerY > 0 && markerY < markerSize - 1;
      const white = !inside || (inner && bits[(markerY - 1) * innerSize + markerX - 1] === '1');
      const index = (y * size + x) * 4;
      data[index] = data[index + 1] = data[index + 2] = white ? 255 : 0;
      data[index + 3] = 255;
    }
  }
  return { width: size, height: size, data };
}

function rasterizeMarkerSvg(svg) {
  const size = 320;
  const pixels = new Uint8ClampedArray(size * size * 4);
  for (let index = 0; index < pixels.length; index += 4) pixels.set([255, 255, 255, 255], index);
  const unit = 20;
  const offset = 50;
  for (const [element] of svg.matchAll(/<rect[^>]+>/g)) {
    const attribute = (name) => element.match(new RegExp(`${name}="([^"]+)"`))?.[1];
    const x0 = offset + Number(attribute('x')) * unit;
    const y0 = offset + Number(attribute('y')) * unit;
    const x1 = x0 + Number(attribute('width')) * unit;
    const y1 = y0 + Number(attribute('height')) * unit;
    const color = attribute('fill') === 'black' ? 0 : 255;
    for (let y = y0; y < y1; y += 1) {
      for (let x = x0; x < x1; x += 1) {
        const index = (y * size + x) * 4;
        pixels[index] = pixels[index + 1] = pixels[index + 2] = color;
      }
    }
  }
  return { width: size, height: size, data: pixels };
}

test('generated Surge Prep marker #0 is detected', () => {
  const detector = createDetector(DICTIONARIES.SURGE_PREP);
  const marker = selectMarker(detector.detect(makeMarkerImage(detector, 0)), DICTIONARIES.SURGE_PREP);
  assert.equal(marker?.id, 0);
  assert.match(markerSvg(DICTIONARIES.SURGE_PREP), /^<svg/);
});

test('OpenCV 4x4 marker family decodes a nonzero ID', () => {
  const detector = createDetector(DICTIONARIES.OPENCV_4X4_50);
  const marker = selectMarker(detector.detect(makeMarkerImage(detector, 23)), DICTIONARIES.OPENCV_4X4_50);
  assert.equal(marker?.id, 23);
  assert.match(markerSvg(DICTIONARIES.OPENCV_4X4_50), /^<svg/);
});

test('OpenCV 5x5 marker family decodes marker #0 and ignores unreliable matches', () => {
  const family = DICTIONARIES.OPENCV_5X5_250;
  const detector = createDetector(family);
  const marker = selectMarker(detector.detect(makeMarkerImage(detector, 0)), family);
  assert.equal(marker?.id, 0);
  assert.equal(marker.hammingDistance, 0);
  assert.equal(selectMarker([{ ...marker, hammingDistance: 3 }], family), null);
  assert.equal(selectMarker([{ ...marker, hammingDistance: 2 }], family)?.id, 0);
});

test('the marker preview SVG is detectable in every supported family', () => {
  for (const family of Object.values(DICTIONARIES)) {
    const detector = createDetector(family);
    const marker = selectMarker(detector.detect(rasterizeMarkerSvg(markerSvg(family))), family);
    assert.equal(marker?.id, 0, family);
  }
});

test('pose and speed use image coordinates and elapsed time', () => {
  const marker = { id: 0, corners: [{ x: 10, y: 20 }, { x: 30, y: 20 }, { x: 30, y: 40 }, { x: 10, y: 40 }] };
  const pose = markerPose2d(marker, 1000);
  assert.equal(pose.x, 20);
  assert.equal(pose.y, 30);
  assert.equal(pose.angleDeg, 0);
  assert.equal(pose.sizePx, 20);
  assert.equal(movementSpeed(pose, { ...pose, x: 30, timestampMs: 1100 }), 100);
  assert.equal(movementSpeed(pose, { ...pose, timestampMs: 2000 }), null);
  assert.equal(appendPath([], pose).length, 1);
  assert.equal(appendPath([{ x: 20, y: 30 }], pose).length, 1);
});

test('Z estimate uses a measured reference and rejects invalid measurements', () => {
  const reference = { distanceMm: 300, sizePx: 120 };
  assert.equal(estimatedDepthMm(reference, 120), 300);
  assert.equal(estimatedDepthMm(reference, 60), 600);
  assert.equal(estimatedDepthMm(null, 120), null);
  assert.equal(estimatedDepthMm(reference, 0), null);
});

test('depth calibration waits for stable frames and resets after motion or marker loss', () => {
  const pose = { markerId: 0, x: 100, y: 100, sizePx: 80 };
  let samples = [];
  for (let index = 0; index < CALIBRATION_FRAMES - 1; index += 1) {
    const next = advanceDepthCalibration(samples, { ...pose, sizePx: 80 + index * 0.2 }, 300);
    samples = next.samples;
    assert.equal(next.reference, null);
  }
  const stable = advanceDepthCalibration(samples, pose, 300);
  assert.equal(stable.reference.distanceMm, 300);
  assert.equal(stable.reference.markerId, 0);
  assert.ok(Math.abs(estimatedDepthMm(stable.reference, 40) - 600) < 5);
  assert.equal(advanceDepthCalibration(samples, { ...pose, x: 130 }, 300).samples.length, 1);
  assert.equal(advanceDepthCalibration(samples, { ...pose, markerId: 1 }, 300).samples.length, 1);
  assert.equal(advanceDepthCalibration(samples, null, 300).samples.length, 0);
  assert.equal(advanceDepthCalibration(samples, pose, 0).reference, null);
});
