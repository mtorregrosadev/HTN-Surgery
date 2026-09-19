import './style.css';
import { advanceDepthCalibration, appendPath, CALIBRATION_FRAMES, createDetector, DEFAULT_DICTIONARY, demoMarkerState, detectPurpleScalpel, DICTIONARIES, relativeDepthPercent, markerPose2d, markerSvg, movementSpeed, selectMarker, SignalSmoother, TARGET_MARKER_ID } from './tracking.js';

// Auto-redirect from 127.0.0.1 to localhost for browser camera permissions compliance
if (typeof window !== 'undefined' && window.location.hostname === '127.0.0.1') {
  window.location.hostname = 'localhost';
}

const $ = (id) => document.getElementById(id);
const video = $('camera');
const overlay = $('overlay');
const overlayContext = overlay.getContext('2d');
const processingCanvas = document.createElement('canvas');
const processingContext = processingCanvas.getContext('2d', { willReadFrequently: true });
const preview = $('path-preview');
const previewContext = preview.getContext('2d');
let dictionaryName = DEFAULT_DICTIONARY;
let detector = createDetector(dictionaryName);
$('dictionary').value = dictionaryName;
const familyDetails = {
  [DICTIONARIES.SURGE_PREP]: { description: 'marker #0', label: 'Surge Prep · MIP 36h12', camera: 'LIVE / ARUCO MIP 36h12', filename: 'mip-36h12' },
  [DICTIONARIES.OPENCV_4X4_50]: { description: 'an OpenCV 4×4 marker (IDs 0–49)', label: 'OpenCV · 4×4 50', camera: 'LIVE / OPENCV 4×4 50', filename: 'opencv-4x4-50' },
  [DICTIONARIES.OPENCV_5X5_250]: { description: 'an OpenCV 5×5 marker (IDs 0–249)', label: 'OpenCV · 5×5 250', camera: 'LIVE / OPENCV 5×5 250', filename: 'opencv-5x5-250' },
};

let stream = null;
let fileUrl = null;
let source = null;
let demoTimer = null;
let frameCallbackId = 0;
let frameCallbackKind = null;
let lastProcessedMs = 0;
let previousPose = null;
let path = [];
let frameCount = 0;
let selectedMarkerId = null;
let depthReference = null;
let calibrationSamples = [];
let lastDetectionMs = 0;
let missingFrames = 0;
const scalpelSmoother = new SignalSmoother({ minAlpha: 0.35, maxAlpha: 0.85, speedThreshold: 80, maxJumpPx: 60 });
let lastScalpelTip = null;
const TRACKING_HOLD_MS = 450;

let controllerWs = null;
let latestHardware = null;

function connectController() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.hostname || '127.0.0.1';
  const url = `${protocol}//${host}:8100/v1/tracking/stream`;

  try {
    controllerWs = new WebSocket(url);

    controllerWs.onopen = () => {
      const pill = $('controller-pill');
      if (pill) {
        pill.textContent = 'CONTROLLER: CONNECTED (:8100)';
        pill.className = 'controller-pill connected';
      }
    };

    controllerWs.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.hardware) {
          latestHardware = data.hardware;
          updateHardwareCard(data.hardware);
        }
      } catch (_) {}
    };

    controllerWs.onclose = () => {
      const pill = $('controller-pill');
      if (pill) {
        pill.textContent = 'CONTROLLER: RECONNECTING…';
        pill.className = 'controller-pill disconnected';
      }
      setTimeout(connectController, 2000);
    };

    controllerWs.onerror = () => {
      try { controllerWs.close(); } catch (_) {}
    };
  } catch (err) {
    setTimeout(connectController, 3000);
  }
}

function updateHardwareCard(hw) {
  const badge = $('hardware-status-badge');
  const label = $('hardware-force-label');
  const fill = $('hardware-force-fill');
  if (!badge || !label || !fill) return;

  if (hw && hw.connected) {
    badge.textContent = `${hw.port || 'USB'} · ${hw.sampleRateHz || 0} Hz`;
    badge.style.color = '#c4ffbd';
    const force = hw.forceN || 0;
    const isContact = hw.contact || false;
    label.textContent = `${force.toFixed(2)} N ${isContact ? '(CONTACT)' : '(IDLE)'}`;
    label.className = isContact ? 'contact' : '';
    const pct = Math.min(100, Math.max(0, (force / 8.0) * 100));
    fill.style.width = `${pct}%`;
  } else {
    badge.textContent = 'DISCONNECTED';
    badge.style.color = '#91a3a9';
    label.textContent = '0.00 N (NO SENSOR)';
    label.className = '';
    fill.style.width = '0%';
  }
}

function sendTrackingPose(payload) {
  if (controllerWs && controllerWs.readyState === WebSocket.OPEN) {
    try {
      controllerWs.send(JSON.stringify(payload));
    } catch (_) {}
  }
}

function dispatchTrackingUpdate(targetX, targetY, angleDeg, zPercent, source, markerId, timestampMs) {
  const w = processingCanvas.width || 480;
  const h = processingCanvas.height || 360;

  // Surgical workspace lateral X (-150 to +150 mm)
  const xMm = Math.max(-150, Math.min(150, (targetX - w / 2) * (300 / w)));
  // Surgical workspace Z body axis (-220 to +220 mm)
  const zMm = Math.max(-220, Math.min(220, (targetY - h / 2) * (380 / h)));

  // Surgical height Y (hovering at +12mm down to -10mm penetration)
  let yMm = 12.0;
  if (zPercent != null) {
    yMm = Math.max(-15, Math.min(30, 8.0 - (zPercent * 0.25)));
  }
  if (latestHardware && latestHardware.contact) {
    const f = latestHardware.forceN || 0.5;
    yMm = -Math.min(8.0, Math.max(0.5, f * 0.9));
  }

  // Incision hold orientation combined with tool yaw
  const rad = (angleDeg * Math.PI) / 180;
  const halfYaw = rad / 2;
  const sy = Math.sin(halfYaw);
  const cy = Math.cos(halfYaw);
  const baseQx = 0.34202014;
  const baseQw = 0.93969262;
  const qx = baseQx * cy;
  const qy = baseQw * sy;
  const qz = -baseQx * sy;
  const qw = baseQw * cy;

  sendTrackingPose({
    type: 'pose',
    positionMm: { x: xMm, y: yMm, z: zMm },
    orientation: { qx, qy, qz, qw },
    angleDeg,
    source,
    markerId,
    confidence: 1.0,
    timestampMs: Math.round(timestampMs),
  });

  if ($('position-x-mm')) $('position-x-mm').textContent = `(${xMm >= 0 ? '+' : ''}${Math.round(xMm)} mm)`;
  if ($('position-z-mm')) $('position-z-mm').textContent = `(${zMm >= 0 ? '+' : ''}${Math.round(zMm)} mm)`;
  if ($('surgical-y-val')) $('surgical-y-val').textContent = `${yMm.toFixed(1)}`;
  if ($('stream-substatus')) {
    $('stream-substatus').textContent = 'STREAMING';
    $('stream-substatus').className = 'marker-active';
  }
}

function markerDescription() {
  return familyDetails[dictionaryName].description;
}

function setStatus(label, kind = '') {
  $('status-pill').textContent = label;
  $('status-pill').className = `status-pill ${kind}`;
}

function setTracking(message, hint) {
  $('tracking-state').textContent = message;
  $('tracking-hint').textContent = hint;
}

function clearMeasurements() {
  for (const id of ['position-x', 'position-y', 'position-z', 'marker-size', 'angle', 'speed', 'marker-id']) $(id).textContent = '—';
  if ($('position-x-mm')) $('position-x-mm').textContent = '(0 mm)';
  if ($('position-z-mm')) $('position-z-mm').textContent = '(0 mm)';
  if ($('surgical-y-val')) $('surgical-y-val').textContent = '12.0';
  if ($('stream-substatus')) {
    $('stream-substatus').textContent = 'IDLE';
    $('stream-substatus').className = '';
  }
}

function setCalibrationStatus(label, ready = false) {
  $('calibration-status').textContent = label;
  $('calibration-status').className = `calibration-status${ready ? ' ready' : ''}`;
}

function setCalibrationStep(activeStep) {
  for (let step = 1; step <= 3; step += 1) {
    const item = $(`calibration-step-${step}`);
    item.className = step === activeStep ? 'active' : step < activeStep ? 'complete' : '';
    if (step === activeStep) item.setAttribute('aria-current', 'step');
    else item.removeAttribute('aria-current');
  }
}

function resetDepthCalibration(message) {
  depthReference = null;
  calibrationSamples = [];
  setCalibrationStep(source ? 2 : 1);
  setCalibrationStatus(source ? 'SHOW MARKER' : 'WAITING FOR CAMERA');
  $('depth-hint').textContent = message;
  $('position-z').textContent = '—';
}

function beginDepthCalibration() {
  // This visible reset starts a fresh measurement and explicitly allows a
  // different marker ID to be selected. Keep ordinary detection loss locked.
  resetMarkerSelection();
  previousPose = null;
  if (!source) {
    resetDepthCalibration('Start the camera or demo, then show the marker.');
    return;
  }
  depthReference = null;
  calibrationSamples = [];
  setCalibrationStep(2);
  setCalibrationStatus('SHOW MARKER');
  $('depth-hint').textContent = 'Hold the full marker still and facing the camera lens.';
  $('position-z').textContent = '—';
}

function resetMarkerSelection() {
  selectedMarkerId = null;
}

let isProcessing = false;

function drawPath(context, points, scaleX = 1, scaleY = 1) {
  if (points.length < 2) return;
  context.save();
  context.beginPath();
  context.strokeStyle = '#a7edba';
  context.lineWidth = 2.5;
  context.lineJoin = 'round';
  context.lineCap = 'round';

  let segStart = 0;
  for (let i = 0; i <= points.length; i += 1) {
    const isEnd = i === points.length;
    const isBreak = !isEnd && i > segStart && points[i].continuous === false;

    if (isBreak || isEnd) {
      const segLen = i - segStart;
      if (segLen === 1) {
        const p = points[segStart];
        context.moveTo(p.x * scaleX, p.y * scaleY);
        context.arc(p.x * scaleX, p.y * scaleY, 1.2, 0, Math.PI * 2);
      } else if (segLen === 2) {
        const p0 = points[segStart];
        const p1 = points[segStart + 1];
        context.moveTo(p0.x * scaleX, p0.y * scaleY);
        context.lineTo(p1.x * scaleX, p1.y * scaleY);
      } else if (segLen > 2) {
        const p0 = points[segStart];
        context.moveTo(p0.x * scaleX, p0.y * scaleY);
        for (let j = segStart + 1; j < i - 1; j += 1) {
          const xc = ((points[j].x + points[j + 1].x) / 2) * scaleX;
          const yc = ((points[j].y + points[j + 1].y) / 2) * scaleY;
          context.quadraticCurveTo(points[j].x * scaleX, points[j].y * scaleY, xc, yc);
        }
        const lastP = points[i - 1];
        context.lineTo(lastP.x * scaleX, lastP.y * scaleY);
      }
      segStart = i;
    }
  }
  context.stroke();
  context.restore();
}

function drawPreview() {
  const { width, height } = preview;
  previewContext.clearRect(0, 0, width, height);
  previewContext.strokeStyle = 'rgba(255,255,255,.08)';
  previewContext.lineWidth = 1;
  for (let x = 0; x <= width; x += 40) {
    previewContext.beginPath(); previewContext.moveTo(x, 0); previewContext.lineTo(x, height); previewContext.stroke();
  }
  for (let y = 0; y <= height; y += 27.5) {
    previewContext.beginPath(); previewContext.moveTo(0, y); previewContext.lineTo(width, y); previewContext.stroke();
  }
  if (!processingCanvas.width) return;
  drawPath(previewContext, path, width / processingCanvas.width, height / processingCanvas.height);
  $('path-count').textContent = `${path.length} points`;
}

function drawOverlay(pose, scalpel) {
  overlayContext.clearRect(0, 0, overlay.width, overlay.height);
  drawPath(overlayContext, path, 1, 1);

  // 1. Draw Purple Scalpel TIP (detectar el final, no tot)
  if (scalpel) {
    overlayContext.save();
    const tx = scalpel.tipX;
    const ty = scalpel.tipY;

    // Sleek blade spine line towards base (max 45px to show blade direction)
    const distToBase = Math.hypot(scalpel.baseX - tx, scalpel.baseY - ty);
    if (distToBase > 10) {
      const bladeLen = Math.min(45, distToBase);
      const dirX = (scalpel.baseX - tx) / distToBase;
      const dirY = (scalpel.baseY - ty) / distToBase;

      overlayContext.strokeStyle = 'rgba(217, 102, 255, 0.65)';
      overlayContext.lineWidth = 3;
      overlayContext.lineCap = 'round';
      overlayContext.beginPath();
      overlayContext.moveTo(tx, ty);
      overlayContext.lineTo(tx + dirX * bladeLen, ty + dirY * bladeLen);
      overlayContext.stroke();
    }

    // High-precision surgical tip reticle
    overlayContext.strokeStyle = '#d966ff';
    overlayContext.lineWidth = 2;
    overlayContext.beginPath();
    overlayContext.arc(tx, ty, 9, 0, Math.PI * 2);
    overlayContext.stroke();

    // Crosshairs on the tip
    overlayContext.beginPath();
    overlayContext.moveTo(tx - 14, ty); overlayContext.lineTo(tx - 9, ty);
    overlayContext.moveTo(tx + 9, ty); overlayContext.lineTo(tx + 14, ty);
    overlayContext.moveTo(tx, ty - 14); overlayContext.lineTo(tx, ty - 9);
    overlayContext.moveTo(tx, ty + 9); overlayContext.lineTo(tx, ty + 14);
    overlayContext.stroke();

    // Inner bright tip focal point
    overlayContext.fillStyle = '#ffffff';
    overlayContext.beginPath();
    overlayContext.arc(tx, ty, 3, 0, Math.PI * 2);
    overlayContext.fill();

    // Compact floating tip badge
    const badgeW = 95;
    const badgeH = 18;
    const badgeX = tx + 14 + badgeW > overlay.width ? tx - badgeW - 14 : tx + 14;
    const badgeY = ty - 9 < 15 ? ty + 12 : ty - 9;
    overlayContext.fillStyle = '#220b33';
    overlayContext.fillRect(badgeX, badgeY - 11, badgeW, badgeH);
    overlayContext.strokeStyle = '#d966ff';
    overlayContext.lineWidth = 1;
    overlayContext.strokeRect(badgeX, badgeY - 11, badgeW, badgeH);
    overlayContext.fillStyle = '#f0b3ff';
    overlayContext.font = 'bold 10px monospace';
    overlayContext.fillText('✂ SCALPEL TIP', badgeX + 6, badgeY + 2);

    overlayContext.restore();
  }

  // 2. Draw Marker if detected
  if (pose) {
    const corners = pose.corners;
    overlayContext.beginPath();
    overlayContext.moveTo(corners[0].x, corners[0].y);
    for (const corner of corners.slice(1)) overlayContext.lineTo(corner.x, corner.y);
    overlayContext.closePath();
    overlayContext.strokeStyle = '#c4ffbd';
    overlayContext.lineWidth = 3;
    overlayContext.stroke();
    overlayContext.fillStyle = '#c4ffbd';
    overlayContext.beginPath(); overlayContext.arc(pose.x, pose.y, 5, 0, Math.PI * 2); overlayContext.fill();
    overlayContext.fillStyle = '#101b24';
    overlayContext.fillRect(pose.x + 10, pose.y - 24, 52, 23);
    overlayContext.fillStyle = '#c4ffbd';
    overlayContext.font = 'bold 14px monospace';
    overlayContext.fillText(`#${pose.markerId}`, pose.x + 17, pose.y - 8);
  }

  // 3. Connect Marker and Scalpel if both are visible
  if (pose && scalpel) {
    overlayContext.save();
    overlayContext.setLineDash([4, 4]);
    overlayContext.strokeStyle = 'rgba(217, 102, 255, 0.75)';
    overlayContext.lineWidth = 1.5;
    overlayContext.beginPath();
    overlayContext.moveTo(pose.x, pose.y);
    overlayContext.lineTo(scalpel.x, scalpel.y);
    overlayContext.stroke();
    overlayContext.restore();
  }
}

function processFrame(timestampMs) {
  if (!source || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) return;
  if (isProcessing) return;
  if (timestampMs - lastProcessedMs < 25) return;
  isProcessing = true;
  try {
    lastProcessedMs = timestampMs;
    processingContext.drawImage(video, 0, 0, processingCanvas.width, processingCanvas.height);
    const pixels = processingContext.getImageData(0, 0, processingCanvas.width, processingCanvas.height);
    const markers = detector.detect(pixels);
    const marker = selectMarker(markers, dictionaryName, selectedMarkerId);
    frameCount += 1;
    $('frame-count').textContent = String(frameCount);

    const pose = markerPose2d(marker, timestampMs);
    const rawScalpel = detectPurpleScalpel(pixels, {
      step: 2,
      minPixels: 14,
      previousTip: lastScalpelTip,
    });
    let scalpel = null;
    let smoothedScalpel = null;

    if (rawScalpel) {
      smoothedScalpel = scalpelSmoother.filter(
        rawScalpel.tipX,
        rawScalpel.tipY,
        rawScalpel.angleDeg,
        timestampMs,
      );
      scalpel = {
        ...rawScalpel,
        tipX: smoothedScalpel.x,
        tipY: smoothedScalpel.y,
        x: smoothedScalpel.x,
        y: smoothedScalpel.y,
        angleDeg: smoothedScalpel.angle,
      };
      lastScalpelTip = { x: smoothedScalpel.x, y: smoothedScalpel.y };
    }

    if (pose) {
      lastDetectionMs = timestampMs;
      if (selectedMarkerId === null) selectedMarkerId = pose.markerId;
      if (!depthReference) {
        const result = advanceDepthCalibration(calibrationSamples, pose);
        calibrationSamples = result.samples;
        if (result.reference) {
          depthReference = result.reference;
          setCalibrationStep(3);
          setCalibrationStatus('Z READY', true);
          $('depth-hint').textContent = 'Starting position set. Positive Z means farther away; negative Z means closer.';
        } else {
          setCalibrationStatus(`HOLD STILL ${calibrationSamples.length}/${CALIBRATION_FRAMES}`);
        }
      } else {
        setCalibrationStatus('Z READY', true);
      }

      const speed = movementSpeed(previousPose, pose);

      // Autocomplete motion gaps across brief frame drops
      let isContinuous = true;
      if (previousPose) {
        const dt = timestampMs - previousPose.timestampMs;
        const dist = Math.hypot(pose.x - previousPose.x, pose.y - previousPose.y);
        if (missingFrames > 0) {
          if (dt <= TRACKING_HOLD_MS && dist <= 200) {
            const steps = Math.min(4, Math.max(1, Math.floor(dist / 20)));
            for (let s = 1; s < steps; s += 1) {
              const t = s / steps;
              path = appendPath(path, {
                x: previousPose.x + (pose.x - previousPose.x) * t,
                y: previousPose.y + (pose.y - previousPose.y) * t,
              }, true);
            }
            isContinuous = true;
          } else {
            isContinuous = false;
          }
        }
      } else {
        isContinuous = false;
      }

      path = appendPath(path, pose, isContinuous);
      previousPose = pose;
      missingFrames = 0;

      if (scalpel) {
        setStatus('DUAL: QR + SCALPEL', 'dual');
        setTracking('Dual tracking active', `Marker #${pose.markerId} and purple scalpel tracked simultaneously.`);
        $('marker-substatus').textContent = `#${pose.markerId}`;
        $('marker-substatus').className = 'marker-active';
        $('scalpel-substatus').textContent = 'DETECTED';
        $('scalpel-substatus').className = 'scalpel-active';
        $('scalpel-status').textContent = 'TRACKED';
      } else {
        setStatus('MARKER FOUND', 'detected');
        setTracking('Motion detected', `Marker #${pose.markerId} is visible to the camera.`);
        $('marker-substatus').textContent = `#${pose.markerId}`;
        $('marker-substatus').className = 'marker-active';
        $('scalpel-substatus').textContent = 'SEARCHING';
        $('scalpel-substatus').className = '';
        $('scalpel-status').textContent = '—';
      }

      $('position-x').textContent = Math.round(pose.x);
      $('position-y').textContent = Math.round(pose.y);
      const zPercent = depthReference?.markerId === pose.markerId
        ? relativeDepthPercent(depthReference, pose.sizePx) : null;
      const roundedZ = zPercent == null ? null : Math.round(zPercent);
      $('position-z').textContent = roundedZ == null ? '—' : `${roundedZ > 0 ? '+' : ''}${roundedZ}%`;
      $('marker-size').textContent = Math.round(pose.sizePx);
      $('angle').textContent = `${Math.round(pose.angleDeg)}°`;
      $('speed').textContent = speed == null ? '—' : Math.round(speed);
      $('marker-id').textContent = `#${pose.markerId}`;

      dispatchTrackingUpdate(
        scalpel ? scalpel.tipX : pose.x,
        scalpel ? scalpel.tipY : pose.y,
        scalpel ? scalpel.angleDeg : pose.angleDeg,
        zPercent,
        scalpel ? 'dual' : 'camera-aruco',
        pose.markerId,
        timestampMs,
      );
    } else if (scalpel) {
      // Scalpel tracked without QR marker! Keep tracking alive
      lastDetectionMs = timestampMs;
      const scalpelPose = {
        x: scalpel.tipX,
        y: scalpel.tipY,
        timestampMs,
        angleDeg: scalpel.angleDeg,
      };

      const speed = movementSpeed(previousPose, scalpelPose);

      let isContinuous = true;
      if (previousPose) {
        const dt = timestampMs - previousPose.timestampMs;
        const dist = Math.hypot(scalpelPose.x - previousPose.x, scalpelPose.y - previousPose.y);
        // Only continuous surgical incisions within realistic per-frame displacement
        if (dt <= 160 && dist <= 45 && !smoothedScalpel?.jumped) {
          isContinuous = true;
        } else {
          isContinuous = false;
        }
      } else {
        isContinuous = false;
      }

      path = appendPath(path, scalpelPose, isContinuous);
      previousPose = scalpelPose;
      missingFrames = 0;

      setStatus('SCALPEL TRACKING', 'scalpel');
      setTracking('Tracking Purple Scalpel', 'QR marker occluded; maintaining tool position via purple scalpel.');
      $('marker-substatus').textContent = 'OCCLUDED';
      $('marker-substatus').className = '';
      $('scalpel-substatus').textContent = 'ACTIVE';
      $('scalpel-substatus').className = 'scalpel-active';
      $('scalpel-status').textContent = 'TRACKED';

      $('position-x').textContent = Math.round(scalpelPose.x);
      $('position-y').textContent = Math.round(scalpelPose.y);
      $('angle').textContent = `${Math.round(scalpel.angleDeg)}°`;
      $('speed').textContent = speed == null ? '—' : Math.round(speed);
      if (depthReference) setCalibrationStatus('Z READY', true);

      dispatchTrackingUpdate(
        scalpelPose.x,
        scalpelPose.y,
        scalpelPose.angleDeg,
        null,
        'purple-scalpel',
        null,
        timestampMs,
      );
    } else {
      // Neither detected
      missingFrames += 1;
      const dt = timestampMs - lastDetectionMs;

      if (previousPose && dt <= TRACKING_HOLD_MS) {
        // Holding window: retain state so it doesn't flicker or look broken
        setStatus('TRACKING (HOLD)', 'hold');
        setTracking('Holding tool trajectory', 'Brief motion pause or glare; preserving position.');
        $('marker-substatus').textContent = 'HOLD';
        $('marker-substatus').className = '';
        $('scalpel-substatus').textContent = 'HOLD';
        $('scalpel-substatus').className = '';
      } else {
        // Truly lost after grace period
        previousPose = null;
        scalpelSmoother.reset();
        lastScalpelTip = null;
        if (!depthReference) {
          calibrationSamples = [];
          setCalibrationStatus('SHOW MARKER');
          $('depth-hint').textContent = 'Keep the marker or purple scalpel visible to set the starting position.';
        } else {
          setCalibrationStatus('Z PAUSED');
        }
        setStatus('LOOKING FOR TOOL', 'searching');
        const hint = selectedMarkerId !== null
          ? `Marker #${selectedMarkerId} and purple scalpel are not visible. Keep either in view.`
          : 'Keep the marker or purple scalpel clearly visible to the camera.';
        setTracking('Looking for tool', hint);
        clearMeasurements();
        $('marker-substatus').textContent = '—';
        $('marker-substatus').className = '';
        $('scalpel-substatus').textContent = '—';
        $('scalpel-substatus').className = '';
        $('scalpel-status').textContent = '—';
      }
    }
    drawOverlay(pose, scalpel);
    drawPreview();
  } finally {
    isProcessing = false;
  }
}

function scheduleFrame() {
  if (!source) return;
  if (typeof video.requestVideoFrameCallback === 'function') {
    frameCallbackKind = 'video';
    frameCallbackId = video.requestVideoFrameCallback((now) => {
      processFrame(now);
      scheduleFrame();
    });
  } else {
    frameCallbackKind = 'animation';
    frameCallbackId = requestAnimationFrame((now) => {
      processFrame(now);
      scheduleFrame();
    });
  }
}

function stopSource() {
  if (frameCallbackKind === 'video') video.cancelVideoFrameCallback(frameCallbackId);
  else if (frameCallbackKind === 'animation') cancelAnimationFrame(frameCallbackId);
  frameCallbackId = 0;
  frameCallbackKind = null;
  stream?.getTracks().forEach((track) => track.stop());
  stream = null;
  if (demoTimer) clearInterval(demoTimer);
  demoTimer = null;
  try {
    video.pause();
    video.srcObject = null;
    video.removeAttribute('src');
  } catch (_) {}
  if (fileUrl) URL.revokeObjectURL(fileUrl);
  fileUrl = null;
  source = null;
  $('video-file').value = '';
  resetMarkerSelection();
  previousPose = null;
  missingFrames = 0;
  lastDetectionMs = 0;
  scalpelSmoother.reset();
  lastScalpelTip = null;
  $('marker-substatus').textContent = '—';
  $('marker-substatus').className = '';
  $('scalpel-substatus').textContent = '—';
  $('scalpel-substatus').className = '';
  $('scalpel-status').textContent = '—';
  resetDepthCalibration('Start the camera or demo, then show the marker.');
  path = [];
  frameCount = 0;
  $('frame-count').textContent = '0';
  drawPreview();
  overlayContext.clearRect(0, 0, overlay.width, overlay.height);
  $('empty-state').hidden = false;
  $('camera-button').innerHTML = 'Start camera <span>↗</span>';
  $('camera-button').disabled = false;
  const emptyBtn = $('empty-state-start-btn');
  if (emptyBtn) {
    emptyBtn.innerHTML = 'Start camera <span>↗</span>';
    emptyBtn.disabled = false;
  }
  $('video-button').textContent = 'Open video file';
  $('demo-button').textContent = 'Try synthetic demo';
  setStatus('CAMERA OFF');
  setTracking('Waiting for camera', 'No reading yet.');
  clearMeasurements();
}

async function startDemo() {
  if (!HTMLCanvasElement.prototype.captureStream) {
    $('camera-error').textContent = 'This browser cannot run the synthetic video demo.';
    return;
  }
  stopSource();
  $('camera-error').textContent = '';
  const canvas = document.createElement('canvas');
  canvas.width = 640;
  canvas.height = 480;
  const context = canvas.getContext('2d');
  const markerImage = new Image();
  markerImage.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(markerSvg(dictionaryName))}`;
  try {
    await markerImage.decode();
    let frame = 0;
    const render = () => {
      frame = depthReference ? frame + 1 : 0;
      context.fillStyle = '#dce8e3';
      context.fillRect(0, 0, canvas.width, canvas.height);
      const { x, y, sidePx, angleRad } = demoMarkerState(frame);
      context.save();
      context.translate(x, y);
      context.rotate(angleRad);

      // Render purple scalpel attached to the marker in demo mode
      context.fillStyle = '#9b30d9';
      context.beginPath();
      if (context.roundRect) context.roundRect(sidePx / 2 - 4, -9, 70, 18, 4);
      else context.rect(sidePx / 2 - 4, -9, 70, 18);
      context.fill();

      // Scalpel tip
      context.fillStyle = '#bf4bf6';
      context.beginPath();
      context.moveTo(sidePx / 2 + 66, -9);
      context.lineTo(sidePx / 2 + 96, 0);
      context.lineTo(sidePx / 2 + 66, 9);
      context.closePath();
      context.fill();

      context.drawImage(markerImage, -sidePx / 2, -sidePx / 2, sidePx, sidePx);
      context.restore();
    };
    render();
    demoTimer = setInterval(render, 33);
    stream = canvas.captureStream(30);
    video.srcObject = stream;
    await video.play();
    startProcessing('demo');
  } catch (error) {
    stopSource();
    $('camera-error').textContent = `Could not start the demo: ${error.message}`;
  }
}

async function startVideo() {
  const file = $('video-file').files?.[0];
  if (!file) return;
  stopSource();
  $('camera-error').textContent = '';
  fileUrl = URL.createObjectURL(file);
  video.src = fileUrl;
  video.loop = true;
  try {
    await video.play();
    startProcessing('file');
  } catch (error) {
    stopSource();
    $('camera-error').textContent = `Could not play the video: ${error.message}`;
  }
}

function startProcessing(kind) {
  source = kind;
  resetMarkerSelection();
  const vidW = (video.videoWidth && video.videoWidth > 0) ? video.videoWidth : 640;
  const vidH = (video.videoHeight && video.videoHeight > 0) ? video.videoHeight : 480;
  processingCanvas.width = Math.min(vidW, 480);
  processingCanvas.height = Math.round(processingCanvas.width * vidH / vidW);
  overlay.width = processingCanvas.width;
  overlay.height = processingCanvas.height;
  $('camera-stage').style.aspectRatio = `${vidW} / ${vidH}`;
  $('empty-state').hidden = true;
  $('empty-state-hint').style.display = 'none';
  $('camera-button').innerHTML = kind === 'camera' ? 'Stop camera <span>■</span>' : 'Start camera <span>↗</span>';
  $('video-button').textContent = kind === 'file' ? 'Stop video' : 'Open video file';
  $('demo-button').textContent = kind === 'demo' ? 'Stop demo' : 'Try synthetic demo';
  setStatus('LOOKING FOR MARKER', 'searching');
  setTracking('Looking for marker', kind === 'file' ? `Play a video that shows ${markerDescription()}.` : kind === 'demo' ? 'Detecting a generated moving marker.' : `Show ${markerDescription()} to the camera.`);
  lastProcessedMs = 0;
  beginDepthCalibration();
  scheduleFrame();
}

let selectedCameraId = null;

async function updateCameraList() {
  if (!navigator.mediaDevices?.enumerateDevices) return;
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    const videoDevices = devices.filter((d) => d.kind === 'videoinput');
    const select = $('camera-select');
    if (!select) return;

    if (videoDevices.length > 1) {
      select.innerHTML = '';
      videoDevices.forEach((d, i) => {
        const opt = document.createElement('option');
        opt.value = d.deviceId;
        opt.textContent = d.label || `Camera ${i + 1}`;
        if (d.deviceId === selectedCameraId) opt.selected = true;
        select.appendChild(opt);
      });
      select.style.display = 'inline-block';
    } else {
      select.style.display = 'none';
    }
  } catch (_) {}
}

$('camera-select')?.addEventListener('change', (e) => {
  selectedCameraId = e.target.value;
  if (source === 'camera') {
    startCamera(selectedCameraId);
  }
});

async function startCamera(preferredDeviceId = null) {
  $('camera-error').textContent = '';
  $('empty-state-hint').style.display = 'none';

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    const isIp = window.location.hostname === '127.0.0.1';
    const msg = isIp
      ? 'Per obrir la càmera, ves a http://localhost:5173 (els navegadors bloquegen la càmera a adreces 127.0.0.1).'
      : 'Aquest navegador no té suport per a getUserMedia (requereix localhost o HTTPS).';
    $('camera-error').textContent = msg;
    $('empty-state-hint').textContent = msg;
    $('empty-state-hint').style.display = 'block';
    setStatus('CAMERA OFF');
    setTracking('Càmera no disponible', msg);
    return;
  }

  // Teardown previous active stream/loops cleanly without resetting UI to "CAMERA OFF"
  if (frameCallbackKind === 'video') video.cancelVideoFrameCallback(frameCallbackId);
  else if (frameCallbackKind === 'animation') cancelAnimationFrame(frameCallbackId);
  frameCallbackId = 0;
  frameCallbackKind = null;
  stream?.getTracks().forEach((track) => track.stop());
  stream = null;
  if (demoTimer) clearInterval(demoTimer);
  demoTimer = null;
  try {
    video.pause();
    video.srcObject = null;
    video.removeAttribute('src');
  } catch (_) {}
  if (fileUrl) URL.revokeObjectURL(fileUrl);
  fileUrl = null;
  source = null;

  // Immediate visual feedback so the user knows camera acquisition is in progress
  const camBtn = $('camera-button');
  if (camBtn) {
    camBtn.disabled = true;
    camBtn.innerHTML = 'Starting camera… <span>⏳</span>';
  }
  const emptyBtn = $('empty-state-start-btn');
  if (emptyBtn) {
    emptyBtn.disabled = true;
    emptyBtn.innerHTML = 'Starting camera… <span>⏳</span>';
  }
  setStatus('OPENING CAMERA…', 'searching');
  setTracking('Connecting to camera…', 'Demana permís per utilitzar la càmera. Si et surt un avís al navegador, fes clic a "Permetre".');
  $('empty-state-hint').textContent = 'Demana permís per utilitzar la càmera… Si surt un avís al navegador, fes clic a "Permetre".';
  $('empty-state-hint').style.display = 'block';

  try {
    let mediaStream = null;
    let lastError = null;

    // Strategy 1: Explicit device if selected
    // Strategy 2: Standard HD request without overconstraining facingMode
    // Strategy 3: Basic generic { video: true } fallback
    const targetId = preferredDeviceId || selectedCameraId;
    const constraintOptions = [];
    if (targetId) {
      constraintOptions.push({ video: { deviceId: { exact: targetId } }, audio: false });
      constraintOptions.push({ video: { deviceId: targetId }, audio: false });
    }
    constraintOptions.push({
      video: {
        width: { ideal: 1280, max: 1920 },
        height: { ideal: 720, max: 1080 },
      },
      audio: false,
    });
    constraintOptions.push({ video: true, audio: false });

    for (const constraints of constraintOptions) {
      try {
        mediaStream = await navigator.mediaDevices.getUserMedia(constraints);
        if (mediaStream) break;
      } catch (err) {
        lastError = err;
        // If user explicitly clicked Block/Deny, fail immediately without trying other constraints
        if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
          throw err;
        }
      }
    }

    if (!mediaStream) {
      throw lastError || new Error('No video stream available');
    }

    stream = mediaStream;
    video.srcObject = stream;
    video.playsInline = true;
    video.muted = true;
    video.setAttribute('playsinline', '');
    video.setAttribute('muted', '');
    video.setAttribute('autoplay', '');

    const track = stream.getVideoTracks()?.[0];
    if (track) {
      const settings = track.getSettings?.();
      if (settings?.deviceId) {
        selectedCameraId = settings.deviceId;
      }
      track.addEventListener('ended', stopSource, { once: true });
    }

    // Wait for video element to have valid metadata/dimensions
    await new Promise((resolve) => {
      if (video.videoWidth > 0 && video.readyState >= HTMLMediaElement.HAVE_METADATA) {
        resolve();
      } else {
        const onMeta = () => {
          video.removeEventListener('loadedmetadata', onMeta);
          resolve();
        };
        video.addEventListener('loadedmetadata', onMeta);
        setTimeout(resolve, 1000);
      }
    });

    try {
      await video.play();
    } catch (playErr) {
      console.warn('Initial play() interrupted, retrying:', playErr);
      await new Promise((r) => setTimeout(r, 150));
      await video.play();
    }

    startProcessing('camera');
    await updateCameraList();
  } catch (error) {
    console.error('Camera startup error:', error);
    stream?.getTracks().forEach((t) => t.stop());
    stream = null;
    source = null;

    let msg = `Error al obrir la càmera: ${error.name || ''} - ${error.message}`;
    if (error.name === 'NotAllowedError' || error.name === 'PermissionDeniedError') {
      msg = 'Permís de càmera denegat. Fes clic a la icona del cadenat o de la càmera a l\'esquerra de la URL del navegador per permetre l\'accés.';
    } else if (error.name === 'NotFoundError' || error.name === 'DevicesNotFoundError') {
      msg = 'No s\'ha trobat cap càmera connectada a aquest equip.';
    } else if (error.name === 'NotReadableError' || error.name === 'TrackStartError') {
      msg = 'La càmera està en ús per una altra app (FaceTime, Zoom, Teams, Photo Booth). Tanca-les i torna a provar.';
    } else if (error.name === 'OverconstrainedError') {
      msg = 'La configuració de la càmera no és suportada pel dispositiu.';
    }
    $('camera-error').textContent = msg;
    $('empty-state-hint').textContent = msg;
    $('empty-state-hint').style.display = 'block';
    $('empty-state').hidden = false;
    setStatus('CAMERA ERROR', 'searching');
    setTracking('Error de càmera', msg);
  } finally {
    const camBtn = $('camera-button');
    if (camBtn) {
      camBtn.disabled = false;
      if (source !== 'camera') {
        camBtn.innerHTML = 'Start camera <span>↗</span>';
      }
    }
    const emptyBtn = $('empty-state-start-btn');
    if (emptyBtn) {
      emptyBtn.disabled = false;
      emptyBtn.innerHTML = 'Start camera <span>↗</span>';
    }
  }
}

$('camera-button').addEventListener('click', () => source === 'camera' ? stopSource() : startCamera());
$('video-button').addEventListener('click', () => source === 'file' ? stopSource() : $('video-file').click());
$('video-file').addEventListener('change', startVideo);
$('demo-button').addEventListener('click', () => source === 'demo' ? stopSource() : startDemo());
$('depth-button').addEventListener('click', beginDepthCalibration);
$('clear-button').addEventListener('click', () => { path = []; drawPreview(); drawOverlay(previousPose, null); });
window.addEventListener('keydown', (e) => {
  if (e.key === 'c' || e.key === 'C') {
    path = [];
    drawPreview();
    drawOverlay(previousPose, null);
  }
});
$('dictionary').addEventListener('change', () => {
  dictionaryName = $('dictionary').value;
  detector = createDetector(dictionaryName);
  resetMarkerSelection();
  previousPose = null;
  resetDepthCalibration('The marker family changed. Hold the new marker still to set a new starting position.');
  path = [];
  drawPreview();
  clearMeasurements();
  $('camera-label').textContent = familyDetails[dictionaryName].camera;
  if (source === 'demo') startDemo();
  else if (source) beginDepthCalibration();
});

function markerDataUrl() {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(markerSvg(dictionaryName))}`;
}

function showMarker() {
  $('marker-preview').src = markerDataUrl();
  $('marker-family-label').textContent = familyDetails[dictionaryName].label;
  $('marker-dialog').showModal();
}

function downloadBlob(blob, extension) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  const family = familyDetails[dictionaryName].filename;
  link.download = `surge-prep-${family}-${TARGET_MARKER_ID}.${extension}`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

$('marker-button').addEventListener('click', showMarker);
$('show-marker-button').addEventListener('click', showMarker);
$('close-marker-button').addEventListener('click', () => $('marker-dialog').close());
$('download-svg-button').addEventListener('click', () => downloadBlob(new Blob([markerSvg(dictionaryName)], { type: 'image/svg+xml' }), 'svg'));
$('download-png-button').addEventListener('click', async () => {
  const markerImage = new Image();
  markerImage.src = markerDataUrl();
  await markerImage.decode();
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 1200;
  const context = canvas.getContext('2d');
  context.fillStyle = '#fff';
  context.fillRect(0, 0, 1200, 1200);
  context.drawImage(markerImage, 100, 100, 1000, 1000);
  canvas.toBlob((blob) => { if (blob) downloadBlob(blob, 'png'); }, 'image/png');
});
$('empty-state')?.addEventListener('click', () => {
  if (!source) startCamera();
});
$('empty-state-start-btn')?.addEventListener('click', (e) => {
  e.stopPropagation();
  if (!source) startCamera();
});

// Auto-start camera if permissions already granted or on page load
function tryAutoStart() {
  if (!source) {
    startCamera().catch((err) => {
      console.log('Camera auto-start waiting for click:', err);
    });
  }
}

if (document.readyState === 'complete' || document.readyState === 'interactive') {
  setTimeout(tryAutoStart, 300);
} else {
  window.addEventListener('DOMContentLoaded', () => setTimeout(tryAutoStart, 300));
}

window.addEventListener('pagehide', stopSource);
drawPreview();
connectController();
