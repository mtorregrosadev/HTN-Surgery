import './style.css';
import { advanceDepthCalibration, appendPath, CALIBRATION_FRAMES, createDetector, DEFAULT_DICTIONARY, demoMarkerState, DICTIONARIES, relativeDepthPercent, markerPose2d, markerSvg, movementSpeed, selectMarker, TARGET_MARKER_ID } from './tracking.js';

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

function drawOverlay(pose) {
  overlayContext.clearRect(0, 0, overlay.width, overlay.height);
  drawPath(overlayContext, path, 1, 1);
  if (!pose) return;
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
    if (pose) {
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
      const hadPreviousPose = previousPose !== null;
      const speed = movementSpeed(previousPose, pose);
      path = appendPath(path, pose, hadPreviousPose && speed !== null);
      previousPose = pose;
      setStatus('MARKER FOUND', 'detected');
      setTracking('Motion detected', `Marker #${pose.markerId} is visible to the camera.`);
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
    } else {
      // A lost or malformed detection is a real gap. Clear stale readouts and
      // drop the speed baseline immediately; the next valid pose starts a new
      // path segment and is never fabricated across this gap.
      previousPose = null;
      if (!depthReference) {
        calibrationSamples = [];
        setCalibrationStatus('SHOW MARKER');
        $('depth-hint').textContent = 'Keep the full marker visible and hold it still to set the starting position.';
      } else {
        setCalibrationStatus('Z PAUSED');
      }
      setStatus('MARKER LOST', 'searching');
      const hint = selectedMarkerId !== null
        ? `Marker #${selectedMarkerId} is not visible. Keep it in view; another marker will not be selected automatically.`
        : markers.length
          ? dictionaryName === DICTIONARIES.SURGE_PREP
            ? 'This marker does not match Surge Prep #0. Select the family shown by your marker generator, or use the marker from this page.'
            : 'The square is not a reliable match. Check the exact marker family in your generator, then keep its white margin visible.'
          : detector.candidates.length
            ? 'A square is visible, but its code does not match. Check the marker family above.'
            : 'Keep a clear white margin around the full black square; avoid glare and fill less of the frame.';
      setTracking('Looking for marker', hint);
      clearMeasurements();
    }
    drawOverlay(pose);
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
  video.pause();
  video.srcObject = null;
  video.removeAttribute('src');
  video.load();
  if (fileUrl) URL.revokeObjectURL(fileUrl);
  fileUrl = null;
  source = null;
  $('video-file').value = '';
  resetMarkerSelection();
  previousPose = null;
  resetDepthCalibration('Start the camera or demo, then show the marker.');
  path = [];
  frameCount = 0;
  $('frame-count').textContent = '0';
  drawPreview();
  overlayContext.clearRect(0, 0, overlay.width, overlay.height);
  $('empty-state').hidden = false;
  $('camera-button').innerHTML = 'Start camera <span>↗</span>';
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
  processingCanvas.width = Math.min(video.videoWidth, 480);
  processingCanvas.height = Math.round(processingCanvas.width * video.videoHeight / video.videoWidth);
  overlay.width = processingCanvas.width;
  overlay.height = processingCanvas.height;
  $('camera-stage').style.aspectRatio = `${video.videoWidth} / ${video.videoHeight}`;
  $('empty-state').hidden = true;
  $('camera-button').innerHTML = kind === 'camera' ? 'Stop camera <span>■</span>' : 'Start camera <span>↗</span>';
  $('video-button').textContent = kind === 'file' ? 'Stop video' : 'Open video file';
  $('demo-button').textContent = kind === 'demo' ? 'Stop demo' : 'Try synthetic demo';
  setStatus('LOOKING FOR MARKER', 'searching');
  setTracking('Looking for marker', kind === 'file' ? `Play a video that shows ${markerDescription()}.` : kind === 'demo' ? 'Detecting a generated moving marker.' : `Show ${markerDescription()} to the camera.`);
  lastProcessedMs = 0;
  beginDepthCalibration();
  scheduleFrame();
}

async function startCamera() {
  $('camera-error').textContent = '';
  if (!navigator.mediaDevices?.getUserMedia) {
    $('camera-error').textContent = 'Camera access requires localhost or HTTPS.';
    return;
  }
  try {
    stopSource();
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: { facingMode: 'environment', width: { ideal: 960 }, height: { ideal: 720 } } });
    } catch (error) {
      if (error.name !== 'NotFoundError') throw error;
      stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: true });
    }
    video.srcObject = stream;
    await video.play();
    startProcessing('camera');
    stream.getVideoTracks()[0].addEventListener('ended', stopSource, { once: true });
  } catch (error) {
    stopSource();
    $('camera-error').textContent = error.name === 'NotAllowedError'
      ? 'Allow camera access in your browser.'
      : error.name === 'NotFoundError'
        ? 'No camera is available to this browser. Connect a webcam or open a recorded video.'
        : `Could not open the camera: ${error.message}`;
    setStatus(error.name === 'NotFoundError' ? 'NO CAMERA FOUND' : 'CAMERA ERROR');
    setTracking(error.name === 'NotFoundError' ? 'No camera available' : 'Camera could not start', $('camera-error').textContent);
  }
}

$('camera-button').addEventListener('click', () => source === 'camera' ? stopSource() : startCamera());
$('video-button').addEventListener('click', () => source === 'file' ? stopSource() : $('video-file').click());
$('video-file').addEventListener('change', startVideo);
$('demo-button').addEventListener('click', () => source === 'demo' ? stopSource() : startDemo());
$('depth-button').addEventListener('click', beginDepthCalibration);
$('clear-button').addEventListener('click', () => { path = []; drawPreview(); drawOverlay(null); });
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
window.addEventListener('pagehide', stopSource);
drawPreview();
