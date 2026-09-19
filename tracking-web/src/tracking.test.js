import test from 'node:test';
import assert from 'node:assert/strict';
import { appendPath, createDetector, estimatedDepthMm, markerPose2d, markerSvg, movementSpeed, selectMarker } from './tracking.js';

test('generated marker #0 is detected by the configured dictionary', () => {
  const detector = createDetector();
  const size = 320;
  const data = new Uint8ClampedArray(size * size * 4);
  const bits = detector.dictionary.codeList[0];
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const markerX = Math.floor((x - 80) / 20);
      const markerY = Math.floor((y - 80) / 20);
      const inside = markerX >= 0 && markerX < 8 && markerY >= 0 && markerY < 8;
      const inner = markerX > 0 && markerX < 7 && markerY > 0 && markerY < 7;
      const white = !inside || (inner && bits[(markerY - 1) * 6 + markerX - 1] === '1');
      const index = (y * size + x) * 4;
      data[index] = data[index + 1] = data[index + 2] = white ? 255 : 0;
      data[index + 3] = 255;
    }
  }
  const marker = selectMarker(detector.detect({ width: size, height: size, data }));
  assert.equal(marker?.id, 0);
  assert.match(markerSvg(), /^<svg/);
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
