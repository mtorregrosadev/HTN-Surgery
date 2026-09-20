using System;
using UnityEngine;

namespace SurgePrep
{
    /// <summary>
    /// Optional six-degree-of-freedom stylus tracker backed by
    /// jp.keijiro.apriltag. The physical tag must be tagStandard41h12.
    /// </summary>
    public sealed class AprilTagStylusInput : TrackedToolInput
    {
        [Header("Camera")]
        [SerializeField, Min(0)] private int cameraIndex;
        [SerializeField, Min(320)] private int requestedWidth = 1280;
        [SerializeField, Min(240)] private int requestedHeight = 720;
        [SerializeField, Min(1)] private int requestedFps = 60;
        [SerializeField, Range(20f, 140f)] private float cameraFieldOfViewDegrees = 60f;

        [Header("tagStandard41h12 marker")]
        [SerializeField, Min(0)] private int tagId;
        [SerializeField, Min(0.005f)] private float tagSizeMetres = 0.05f;
        [SerializeField, Range(1, 8)] private int decimation = 2;

        [Header("Rigid tag-to-stylus transform")]
        [Tooltip("Measured vector from tag centre to blade tip, in tag-local metres.")]
        [SerializeField] private Vector3 tagToTipMetres = new Vector3(0f, -0.14f, 0f);
        [Tooltip("Fixed tool-axis correction when the printed tag is mounted at an angle.")]
        [SerializeField] private Vector3 tagToToolEulerDegrees;

        [Header("Registration")]
        [Tooltip("Put the physical tip here, hold the desired reference angle, then press Space.")]
        [SerializeField] private Vector3 registrationTipPositionMm = Vector3.zero;
        [SerializeField] private Vector3 registrationToolEulerApi = new Vector3(40f, 0f, 0f);
        [SerializeField, Min(0.05f)] private float staleSeconds = 0.35f;
        [SerializeField, Min(0f)] private float positionResponse = 24f;
        [SerializeField, Min(0f)] private float rotationResponse = 30f;

        private WebCamTexture webcam;
        private AprilTag.TagDetector detector;
        private Color32[] pixels;
        private Matrix4x4 latestCameraTool;
        private Matrix4x4 cameraToApiUnity;
        private Vector3 positionMm;
        private Quaternion orientationApi = Quaternion.identity;
        private float lastDetectionTime = float.NegativeInfinity;
        private bool detected;
        private bool registered;
        private bool hasFilteredPose;
        private string status = "AprilTag tracker starting…";

        public override bool HasSignal => registered && detected &&
            Time.realtimeSinceStartup - lastDetectionTime <= staleSeconds;

        public override string TrackingStatus => status;

        public override bool TryRead(out TrackedToolSample sample)
        {
            sample = new TrackedToolSample
            {
                PositionMm = positionMm,
                OrientationApi = orientationApi,
                HasOrientation = true,
                ForceN = 0f,
                Contact = false,
                Quality = detected ? 1f : 0f,
                SourceHealthy = HasSignal,
                ForceMeasurementValid = false,
                DeviceId = "unity-keijiro-apriltag-stylus",
                Status = status
            };
            return HasSignal;
        }

        private void OnEnable()
        {
            var devices = WebCamTexture.devices;
            if (devices.Length == 0)
            {
                status = "No camera found for AprilTag stylus";
                return;
            }
            var selected = Mathf.Clamp(cameraIndex, 0, devices.Length - 1);
            webcam = new WebCamTexture(
                devices[selected].name, requestedWidth, requestedHeight, requestedFps
            );
            webcam.Play();
            status = "Show tagStandard41h12 ID " + tagId + " to the camera";
        }

        private void OnDisable()
        {
            detector?.Dispose();
            detector = null;
            if (webcam != null)
            {
                webcam.Stop();
                webcam = null;
            }
        }

        private void LateUpdate()
        {
            if (webcam == null || !webcam.isPlaying || !webcam.didUpdateThisFrame)
            {
                ExpireDetection();
                return;
            }
            if (webcam.width < 32 || webcam.height < 32)
            {
                status = "Waiting for webcam frames…";
                return;
            }
            EnsureDetector();
            webcam.GetPixels32(pixels);
            detector.ProcessImage(
                pixels, cameraFieldOfViewDegrees * Mathf.Deg2Rad, tagSizeMetres
            );

            detected = false;
            foreach (var tag in detector.DetectedTags)
            {
                if (tag.ID != tagId) continue;
                detected = true;
                lastDetectionTime = Time.realtimeSinceStartup;
                latestCameraTool = Matrix4x4.TRS(
                    tag.Position, tag.Rotation, Vector3.one
                ) * Matrix4x4.TRS(
                    tagToTipMetres,
                    Quaternion.Euler(tagToToolEulerDegrees),
                    Vector3.one
                );
                break;
            }

            if (!detected)
            {
                ExpireDetection();
                return;
            }
            if (ShowcaseInput.Pressed(KeyCode.Space))
            {
                RegisterCurrentPose();
            }
            if (!registered)
            {
                status = "Tag found — place tip at target centre, then press Space";
                return;
            }
            UpdateRegisteredPose();
        }

        private void EnsureDetector()
        {
            if (detector != null && pixels != null && pixels.Length == webcam.width * webcam.height)
            {
                return;
            }
            detector?.Dispose();
            detector = new AprilTag.TagDetector(webcam.width, webcam.height, decimation);
            pixels = new Color32[webcam.width * webcam.height];
        }

        private void RegisterCurrentPose()
        {
            var targetPosition = new Vector3(
                registrationTipPositionMm.x,
                registrationTipPositionMm.y,
                -registrationTipPositionMm.z
            ) * CoordinateFrame.MillimetresToMetres;
            var apiRotation = Quaternion.Euler(registrationToolEulerApi);
            var targetRotation = new Quaternion(
                -apiRotation.x, -apiRotation.y, apiRotation.z, apiRotation.w
            );
            var target = Matrix4x4.TRS(targetPosition, targetRotation, Vector3.one);
            cameraToApiUnity = target * latestCameraTool.inverse;
            registered = true;
            hasFilteredPose = false;
            status = "LIVE — one-tag 6-DoF stylus tracking";
            UpdateRegisteredPose();
        }

        private void UpdateRegisteredPose()
        {
            var mapped = cameraToApiUnity * latestCameraTool;
            var mappedPosition = mapped.GetColumn(3);
            var rawPositionMm = new Vector3(
                mappedPosition.x, mappedPosition.y, -mappedPosition.z
            ) * CoordinateFrame.MetresToMillimetres;
            var unityRotation = mapped.rotation.normalized;
            var rawOrientationApi = new Quaternion(
                -unityRotation.x, -unityRotation.y, unityRotation.z, unityRotation.w
            ).normalized;

            if (!hasFilteredPose)
            {
                positionMm = rawPositionMm;
                orientationApi = rawOrientationApi;
                hasFilteredPose = true;
            }
            else
            {
                var positionAlpha = 1f - Mathf.Exp(-positionResponse * Time.unscaledDeltaTime);
                var rotationAlpha = 1f - Mathf.Exp(-rotationResponse * Time.unscaledDeltaTime);
                positionMm = Vector3.Lerp(positionMm, rawPositionMm, positionAlpha);
                orientationApi = Quaternion.Slerp(
                    orientationApi, rawOrientationApi, rotationAlpha
                ).normalized;
            }
            status = "LIVE — one-tag 6-DoF stylus tracking";
        }

        private void ExpireDetection()
        {
            if (Time.realtimeSinceStartup - lastDetectionTime > staleSeconds)
            {
                detected = false;
                status = registered
                    ? "AprilTag hidden — keyboard fallback active"
                    : "Show tagStandard41h12 ID " + tagId + " to the camera";
            }
        }
    }
}
