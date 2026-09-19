import test from 'node:test';
import assert from 'node:assert/strict';
import { advanceDepthCalibration, appendPath, CALIBRATION_FRAMES, createDetector, demoMarkerState, detectPurpleScalpel, DICTIONARIES, isPurpleColor, projectiveMarkerCenter, relativeDepthPercent, markerPose2d, markerSvg, movementSpeed, selectMarker } from './tracking.js';

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

function rotateImage(image, quarterTurns) {
  const turns = ((quarterTurns % 4) + 4) % 4;
  if (turns === 0) return image;
  const { width, height, data } = image;
  const rotated = new Uint8ClampedArray(data.length);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const [rotatedX, rotatedY] = turns === 1
        ? [height - 1 - y, x]
        : turns === 2
          ? [width - 1 - x, height - 1 - y]
          : [y, width - 1 - x];
      const sourceIndex = (y * width + x) * 4;
      const targetIndex = (rotatedY * width + rotatedX) * 4;
      rotated[targetIndex] = data[sourceIndex];
      rotated[targetIndex + 1] = data[sourceIndex + 1];
      rotated[targetIndex + 2] = data[sourceIndex + 2];
      rotated[targetIndex + 3] = data[sourceIndex + 3];
    }
  }
  return { width, height, data: rotated };
}

function syntheticMarker(id, corners, hammingDistance = 0) {
  return { id, corners, hammingDistance };
}

function squareCorners(centerX, centerY, sidePx, angleDeg = 0) {
  const angle = angleDeg * Math.PI / 180;
  const half = sidePx / 2;
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  return [[-half, -half], [half, -half], [half, half], [-half, half]].map(([x, y]) => ({
    x: centerX + x * cos - y * sin,
    y: centerY + x * sin + y * cos,
  }));
}

function angleDifference(actual, expected) {
  return Math.abs(((actual - expected + 180) % 360 + 360) % 360 - 180);
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

test('each supported dictionary detects its generated marker at quarter-turn rotations', () => {
  for (const family of Object.values(DICTIONARIES)) {
    const detector = createDetector(family);
    const image = makeMarkerImage(detector, 0);
    for (const quarterTurns of [1, 2, 3]) {
      const marker = selectMarker(detector.detect(rotateImage(image, quarterTurns)), family);
      assert.equal(marker?.id, 0, `${family} at ${quarterTurns * 90}°`);
    }
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

test('projective center uses diagonal intersection for an oblique marker', () => {
  const corners = [{ x: 0, y: 0 }, { x: 4, y: 0 }, { x: 3, y: 3 }, { x: 0, y: 2 }];
  const center = projectiveMarkerCenter(corners);
  assert.ok(center);
  assert.ok(Math.abs(center.x - 4 / 3) < 1e-10);
  assert.ok(Math.abs(center.y - 4 / 3) < 1e-10);
  const pose = markerPose2d(syntheticMarker(0, corners), 1000);
  assert.ok(pose);
  assert.ok(Math.abs(pose.x - 4 / 3) < 1e-10);
  assert.ok(Math.abs(pose.y - 4 / 3) < 1e-10);
  assert.notDeepEqual({ x: pose.x, y: pose.y }, { x: 1.75, y: 1.25 });
});

test('marker angle remains correct through full in-plane rotations', () => {
  for (const angleDeg of [-179, -135, -90, -45, 0, 45, 90, 135, 179]) {
    const pose = markerPose2d(syntheticMarker(0, squareCorners(160, 120, 80, angleDeg)), 1000);
    assert.ok(pose, `rotation ${angleDeg}° should be valid`);
    assert.ok(angleDifference(pose.angleDeg, angleDeg) < 1e-8, `rotation ${angleDeg}° measured as ${pose.angleDeg}°`);
    assert.ok(Math.abs(pose.x - 160) < 1e-8);
    assert.ok(Math.abs(pose.y - 120) < 1e-8);
  }
});

test('invalid marker corners are rejected before producing measurements', () => {
  const invalid = [
    null,
    [{ x: 0, y: 0 }, { x: 2, y: 0 }, { x: 2, y: 0 }, { x: 0, y: 2 }],
    [{ x: 0, y: 0 }, { x: 2, y: 2 }, { x: 0, y: 2 }, { x: 2, y: 0 }],
    [{ x: 0, y: 0 }, { x: 2, y: 0 }, { x: 4, y: 0 }, { x: 0, y: 2 }],
    [{ x: 0, y: 0 }, { x: Number.NaN, y: 1 }, { x: 2, y: 2 }, { x: 0, y: 2 }],
  ];
  for (const corners of invalid) {
    assert.equal(projectiveMarkerCenter(corners), null);
    assert.equal(markerPose2d(syntheticMarker(0, corners), 1000), null);
  }
});

test('selected marker ID stays locked through a competing marker and loss', () => {
  const small = syntheticMarker(7, squareCorners(80, 80, 40));
  const large = syntheticMarker(23, squareCorners(240, 160, 120));
  const selected = selectMarker([small, large], DICTIONARIES.OPENCV_5X5_250);
  assert.equal(selected?.id, 23);
  assert.equal(selectMarker([small, large], DICTIONARIES.OPENCV_5X5_250, selected.id)?.id, 23);
  assert.equal(selectMarker([small], DICTIONARIES.OPENCV_5X5_250, selected.id), null);
  assert.equal(selectMarker([small, large], DICTIONARIES.OPENCV_5X5_250, selected.id)?.id, 23);
  assert.equal(selectMarker([small], DICTIONARIES.OPENCV_5X5_250)?.id, 7);
});

test('path records a visible break instead of fabricating a dropout bridge', () => {
  const first = { x: 20, y: 30 };
  const afterLoss = appendPath(appendPath([], first), { x: 100, y: 130 }, false);
  assert.equal(afterLoss.length, 2);
  assert.equal(afterLoss[1].continuous, false);
  const resumed = appendPath(afterLoss, { x: 110, y: 140 }, true);
  assert.equal(resumed.length, 3);
  assert.equal(resumed[2].continuous, true);
});

test('path preserves a break even when reacquisition is near the last point', () => {
  const beforeLoss = appendPath([], { x: 20, y: 30 });
  const reacquired = appendPath(beforeLoss, { x: 20.5, y: 30.5 }, false);
  assert.equal(reacquired.length, 2);
  assert.equal(reacquired[1].continuous, false);
});

test('relative Z starts at zero and follows apparent marker size', () => {
  const reference = { sizePx: 120 };
  assert.equal(relativeDepthPercent(reference, 120), 0);
  assert.equal(relativeDepthPercent(reference, 60), 100);
  assert.equal(relativeDepthPercent(reference, 240), -50);
  assert.equal(relativeDepthPercent(null, 120), null);
  assert.equal(relativeDepthPercent(reference, 0), null);
});

test('depth calibration waits for stable frames and resets after motion or marker loss', () => {
  const pose = { markerId: 0, x: 100, y: 100, sizePx: 80 };
  let samples = [];
  for (let index = 0; index < CALIBRATION_FRAMES - 1; index += 1) {
    const next = advanceDepthCalibration(samples, { ...pose, sizePx: 80 + index * 0.2 });
    samples = next.samples;
    assert.equal(next.reference, null);
  }
  const stable = advanceDepthCalibration(samples, pose);
  assert.equal(stable.reference.markerId, 0);
  assert.ok(Math.abs(relativeDepthPercent(stable.reference, 40) - 100) < 2);
  assert.equal(advanceDepthCalibration(samples, { ...pose, x: 130 }).samples.length, 1);
  assert.equal(advanceDepthCalibration(samples, { ...pose, markerId: 1 }).samples.length, 1);
  assert.equal(advanceDepthCalibration(samples, null).samples.length, 0);
  assert.equal(advanceDepthCalibration(samples, { ...pose, sizePx: 0 }).reference, null);
});

test('synthetic demo holds the calibration size then moves in both Z directions', () => {
  const startingSize = demoMarkerState(0).sidePx;
  assert.equal(startingSize, 150);
  assert.ok(relativeDepthPercent({ sizePx: startingSize }, demoMarkerState(25).sidePx) > 20);
  assert.ok(relativeDepthPercent({ sizePx: startingSize }, demoMarkerState(125).sidePx) < -20);
});

test('isPurpleColor distinguishes purple hues from other colors and neutrals', () => {
  // Purples
  assert.equal(isPurpleColor(160, 50, 200), true);
  assert.equal(isPurpleColor(120, 30, 170), true);
  assert.equal(isPurpleColor(200, 100, 220), true);
  assert.equal(isPurpleColor(80, 20, 95), true);
  // Non-purples
  assert.equal(isPurpleColor(30, 80, 220), false); // Blue
  assert.equal(isPurpleColor(220, 50, 40), false); // Red
  assert.equal(isPurpleColor(50, 190, 60), false); // Green
  assert.equal(isPurpleColor(210, 160, 130), false); // Skin
  assert.equal(isPurpleColor(240, 240, 240), false); // White
  assert.equal(isPurpleColor(20, 20, 20), false); // Black
});

test('detectPurpleScalpel locates centroid, bounding box, tip, and angle', () => {
  const width = 200;
  const height = 150;
  const data = new Uint8ClampedArray(width * height * 4);
  data.fill(220); // light background
  // Draw a purple horizontal scalpel at x: 60..140, y: 40..60
  for (let y = 40; y <= 60; y += 1) {
    for (let x = 60; x <= 140; x += 1) {
      const idx = (y * width + x) * 4;
      data[idx] = 160;     // R
      data[idx + 1] = 40;  // G
      data[idx + 2] = 190; // B
      data[idx + 3] = 255;
    }
  }
  const scalpel = detectPurpleScalpel({ width, height, data }, { step: 2, minPixels: 10 });
  assert.ok(scalpel);
  assert.equal(Math.round(scalpel.centroidX), 100);
  assert.equal(Math.round(scalpel.centroidY), 50);
  assert.ok(scalpel.tipX <= 65 || scalpel.tipX >= 135);
  assert.equal(scalpel.minX, 60);
  assert.equal(scalpel.maxX, 140);
  assert.equal(scalpel.minY, 40);
  assert.equal(scalpel.maxY, 60);
  assert.ok(scalpel.pixelCount > 0);
  assert.ok(Math.abs(scalpel.angleDeg) < 5); // horizontal
});

