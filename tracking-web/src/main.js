import './style.css';
import { appendPath, createDetector, estimatedDepthMm, markerPose2d, markerSvg, movementSpeed, selectMarker, TARGET_MARKER_ID } from './tracking.js';

const $ = (id) => document.getElementById(id);
const video = $('camera');
const overlay = $('overlay');
const overlayContext = overlay.getContext('2d');
const processingCanvas = document.createElement('canvas');
const processingContext = processingCanvas.getContext('2d', { willReadFrequently: true });
const preview = $('path-preview');
const previewContext = preview.getContext('2d');
const detector = createDetector();

let stream = null;
let fileUrl = null;
let source = null;
let demoTimer = null;
let animationFrame = 0;
let lastProcessedMs = 0;
let previousPose = null;
let path = [];
let frameCount = 0;
let missingFrames = 0;
let currentPose = null;
let depthReference = null;

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

function drawPath(context, points, scaleX, scaleY) {
  if (points.length < 2) return;
  context.beginPath();
  context.moveTo(points[0].x * scaleX, points[0].y * scaleY);
  for (const point of points.slice(1)) context.lineTo(point.x * scaleX, point.y * scaleY);
  context.strokeStyle = '#a7edba';
  context.lineWidth = 2.5;
  context.lineJoin = 'round';
  context.lineCap = 'round';
  context.stroke();
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
  animationFrame = requestAnimationFrame(processFrame);
  if (!source || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA || timestampMs - lastProcessedMs < 66) return;
  lastProcessedMs = timestampMs;
  processingContext.drawImage(video, 0, 0, processingCanvas.width, processingCanvas.height);
  const pixels = processingContext.getImageData(0, 0, processingCanvas.width, processingCanvas.height);
  const marker = selectMarker(detector.detect(pixels));
  frameCount += 1;
  $('frame-count').textContent = String(frameCount);

  const pose = markerPose2d(marker, timestampMs);
  currentPose = pose;
  if (pose) {
    missingFrames = 0;
    const speed = movementSpeed(previousPose, pose);
    previousPose = pose;
    path = appendPath(path, pose);
    setStatus('MARKER FOUND', 'detected');
    setTracking('Motion detected', 'Marker #0 is visible to the camera.');
    $('position-x').textContent = Math.round(pose.x);
    $('position-y').textContent = Math.round(pose.y);
    const zMm = estimatedDepthMm(depthReference, pose.sizePx);
    $('position-z').textContent = zMm == null ? '—' : Math.round(zMm);
    $('marker-size').textContent = Math.round(pose.sizePx);
    $('angle').textContent = `${Math.round(pose.angleDeg)}°`;
    $('speed').textContent = speed == null ? '—' : Math.round(speed);
    $('marker-id').textContent = `#${pose.markerId}`;
  } else {
    missingFrames += 1;
    if (missingFrames >= 3) {
      previousPose = null;
      setStatus('MARKER LOST', 'searching');
      setTracking('Looking for marker', 'Show the full marker #0, well lit and in focus.');
      clearMeasurements();
    }
  }
  drawOverlay(pose);
  drawPreview();
}

function stopSource() {
  cancelAnimationFrame(animationFrame);
  animationFrame = 0;
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
  previousPose = null;
  currentPose = null;
  depthReference = null;
  missingFrames = 0;
  overlayContext.clearRect(0, 0, overlay.width, overlay.height);
  $('empty-state').hidden = false;
  $('camera-button').innerHTML = 'Start camera <span>↗</span>';
  $('video-button').textContent = 'Open video file';
  $('demo-button').textContent = 'Try synthetic demo';
  $('depth-hint').textContent = 'Measure camera-to-marker distance, enter it here, then set the reference while marker #0 is visible. Keep its face toward the camera.';
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
  markerImage.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(markerSvg())}`;
  try {
    await markerImage.decode();
    let frame = 0;
    const render = () => {
      frame += 1;
      context.fillStyle = '#dce8e3';
      context.fillRect(0, 0, canvas.width, canvas.height);
      const x = 320 + Math.sin(frame / 24) * 130;
      const y = 240 + Math.cos(frame / 37) * 75;
      const side = 130 + Math.sin(frame / 31) * 32;
      context.save();
      context.translate(x, y);
      context.rotate(Math.sin(frame / 39) * 0.2);
      context.drawImage(markerImage, -side / 2, -side / 2, side, side);
      context.restore();
    };
    render();
    demoTimer = setInterval(render, 65);
    stream = canvas.captureStream(15);
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
  processingCanvas.width = Math.min(video.videoWidth, 640);
  processingCanvas.height = Math.round(processingCanvas.width * video.videoHeight / video.videoWidth);
  overlay.width = processingCanvas.width;
  overlay.height = processingCanvas.height;
  $('camera-stage').style.aspectRatio = `${video.videoWidth} / ${video.videoHeight}`;
  $('empty-state').hidden = true;
  $('camera-button').innerHTML = kind === 'camera' ? 'Stop camera <span>■</span>' : 'Start camera <span>↗</span>';
  $('video-button').textContent = kind === 'file' ? 'Stop video' : 'Open video file';
  $('demo-button').textContent = kind === 'demo' ? 'Stop demo' : 'Try synthetic demo';
  setStatus('LOOKING FOR MARKER', 'searching');
  setTracking('Looking for marker', kind === 'file' ? 'Play a video that shows marker #0.' : kind === 'demo' ? 'Detecting a generated moving marker.' : 'Show marker #0 to the camera.');
  lastProcessedMs = 0;
  animationFrame = requestAnimationFrame(processFrame);
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
$('depth-button').addEventListener('click', () => {
  const distanceMm = Number($('reference-distance').value);
  if (!currentPose) {
    $('depth-hint').textContent = 'Show marker #0 in the camera or video before setting a depth reference.';
  } else if (!Number.isFinite(distanceMm) || distanceMm < 50 || distanceMm > 5000) {
    $('depth-hint').textContent = 'Enter a measured camera-to-marker distance between 50 and 5000 mm.';
  } else {
    depthReference = { distanceMm, sizePx: currentPose.sizePx };
    $('depth-hint').textContent = `Reference set at ${distanceMm} mm. Z is an approximate camera distance; marker tilt changes the estimate.`;
    $('position-z').textContent = Math.round(distanceMm);
  }
});
$('clear-button').addEventListener('click', () => { path = []; drawPreview(); drawOverlay(null); });
$('marker-button').addEventListener('click', () => {
  const blob = new Blob([markerSvg()], { type: 'image/svg+xml' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `surge-prep-aruco-mip-36h12-${TARGET_MARKER_ID}.svg`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
window.addEventListener('pagehide', stopSource);
drawPreview();
