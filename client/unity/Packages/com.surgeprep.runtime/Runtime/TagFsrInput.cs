using System;
using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using UnityEngine;

namespace SurgePrep
{
    /// <summary>
    /// Receives scalpel input from the hardware bridges over UDP and turns it into a
    /// scalpel pose in API/SOFA millimetres:
    ///   AprilTag position -> x / z over the skin
    ///   FSR pressure      -> tool height y, so pressing harder cuts deeper
    /// <see cref="UnityManualDemoClient"/> sends the result through the normal
    /// Unity -> controller -> API -> SOFA path; SOFA still decides contact and carving.
    /// </summary>
    public sealed class TagFsrInput : TrackedToolInput
    {
        [Header("Network")]
        [SerializeField] private int port = 5005;

        [Header("Tag position -> skin field (mm, API frame)")]
        [SerializeField, Min(1f)] private float xRangeMm = 30f;   // matches the carvable field
        [SerializeField, Min(1f)] private float zRangeMm = 22f;
        [SerializeField] private bool invertX;
        [SerializeField] private bool invertZ;

        [Header("FSR -> cut depth")]
        [SerializeField] private float hoverMm = 6f;              // height above skin with no pressure
        [SerializeField, Min(1f)] private float maxDepthMm = 32f; // depth below skin at full pressure (pleural floor)
        [SerializeField, Range(0f, 0.5f)] private float deadband = 0.08f;
        [SerializeField, Min(0.1f)] private float maxForceN = 5f;
        [SerializeField, Min(0.05f)] private float staleSeconds = 0.5f;

        [Header("Single 36h11 tag -> complete stylus pose")]
        [Tooltip("Measured vector from the tag centre to the stylus tip in tag-local metres.")]
        [SerializeField] private Vector3 tagToTipMetres = new Vector3(0f, -0.14f, 0f);
        [SerializeField] private Vector3 tagToToolEulerDegrees;
        [SerializeField] private Vector3 registrationTipPositionMm = Vector3.zero;
        [SerializeField] private Vector3 registrationToolEulerApi = new Vector3(40f, 0f, 0f);
        [SerializeField] private bool autoRegisterOnFirstPose = true;
        [SerializeField, Min(0f)] private float positionResponse = 24f;
        [SerializeField, Min(0f)] private float rotationResponse = 30f;

        [Serializable]
        private class Packet
        {
            public string mode;
            public float x, y, force;
            public float px, py, pz, qx, qy, qz, qw = 1f;
            public float quality;
            public int tags;
            public int tagId;
        }

        private UdpClient udp;
        private Thread thread;
        private volatile bool running;
        private readonly object lockObj = new object();
        private string latestJson;
        private readonly Stopwatch clock = Stopwatch.StartNew();
        private double receivedAt = double.NegativeInfinity;
        private Vector3 lastPose = new Vector3(0f, 6f, 0f);
        private float lastDepth01;
        private Matrix4x4 cameraToApiUnity;
        private Vector3 trackedPositionMm;
        private Quaternion trackedOrientationApi = Quaternion.identity;
        private bool registered6D;
        private bool hasFiltered6D;
        private string status = "Waiting for AprilTag bridge";

        /// <summary>True while the bridge is sending fresh packets.</summary>
        public override bool HasSignal
        {
            get { lock (lockObj) { return latestJson != null && clock.Elapsed.TotalSeconds - receivedAt < staleSeconds; } }
        }

        public override string TrackingStatus => HasSignal ? status : "Waiting for AprilTag bridge";

        /// <summary>Cut depth 0..1 (0 = resting above skin, 1 = full depth).</summary>
        public float Depth01 => lastDepth01;

        /// <summary>Reads the current pose. The pose is held when tags are lost; force is dropped so the blade lifts.</summary>
        public void Read(out Vector3 positionMm, out float forceN, out bool contact, out bool tagsVisible)
        {
            string json;
            lock (lockObj) { json = latestJson; }
            var p = json == null ? null : JsonUtility.FromJson<Packet>(json);   // parsed on the main thread
            tagsVisible = p != null && p.tags > 0;
            if (p == null)
            {
                positionMm = lastPose; forceN = 0f; contact = false;
                return;
            }

            var x = (p.x - 0.5f) * 2f * xRangeMm * (invertX ? -1f : 1f);
            var z = (p.y - 0.5f) * 2f * zRangeMm * (invertZ ? -1f : 1f);
            var pressed = tagsVisible ? Mathf.Clamp01((p.force - deadband) / (1f - deadband)) : 0f;
            var y = hoverMm - pressed * (hoverMm + maxDepthMm);

            if (tagsVisible)
            {
                lastPose = new Vector3(x, y, z);
            }
            else
            {
                lastPose = new Vector3(lastPose.x, hoverMm, lastPose.z);
            }
            lastDepth01 = pressed;
            positionMm = lastPose;
            forceN = pressed * maxForceN;
            contact = pressed > 0f;
        }

        public override bool TryRead(out TrackedToolSample sample)
        {
            string json;
            lock (lockObj) { json = latestJson; }
            var packet = json == null ? null : JsonUtility.FromJson<Packet>(json);
            if (packet != null && packet.mode == "pose6d")
            {
                return TryReadSixDof(packet, out sample);
            }

            Read(out var positionMm, out var forceN, out var contact, out var tagsVisible);
            status = tagsVisible
                ? "LIVE — AprilTag position, FSR cut depth"
                : "AprilTag hidden — tool lifted";
            sample = new TrackedToolSample
            {
                PositionMm = positionMm,
                OrientationApi = Quaternion.identity,
                HasOrientation = false,
                ForceN = forceN,
                Contact = contact,
                Quality = tagsVisible ? 1f : 0f,
                SourceHealthy = HasSignal && tagsVisible,
                ForceMeasurementValid = true,
                DeviceId = "apriltag-fsr-bridge",
                Status = status
            };
            return HasSignal;
        }

        private bool TryReadSixDof(Packet packet, out TrackedToolSample sample)
        {
            sample = default;
            if (!HasSignal || packet.tags <= 0)
            {
                status = registered6D
                    ? "36h11 tag hidden — WASD fallback active"
                    : "Show the 36h11 tag to the camera";
                return false;
            }

            var cameraRotation = new Quaternion(packet.qx, packet.qy, packet.qz, packet.qw);
            if (!IsFinite(cameraRotation) || Quaternion.Dot(cameraRotation, cameraRotation) < 0.9f)
            {
                status = "Rejected invalid 36h11 pose — WASD fallback active";
                return false;
            }
            cameraRotation = cameraRotation.normalized;
            var cameraTool = Matrix4x4.TRS(
                new Vector3(packet.px, packet.py, packet.pz),
                cameraRotation,
                Vector3.one
            ) * Matrix4x4.TRS(
                tagToTipMetres,
                Quaternion.Euler(tagToToolEulerDegrees),
                Vector3.one
            );

            if ((autoRegisterOnFirstPose && !registered6D) || ShowcaseInput.Pressed(KeyCode.Space))
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
                cameraToApiUnity = Matrix4x4.TRS(
                    targetPosition, targetRotation, Vector3.one
                ) * cameraTool.inverse;
                registered6D = true;
                hasFiltered6D = false;
            }
            if (!registered6D)
            {
                status = "36h11 found — place tip at target centre and press Space";
                return false;
            }

            var mapped = cameraToApiUnity * cameraTool;
            var mappedPosition = mapped.GetColumn(3);
            var rawPositionMm = new Vector3(
                mappedPosition.x, mappedPosition.y, -mappedPosition.z
            ) * CoordinateFrame.MetresToMillimetres;
            var unityRotation = mapped.rotation.normalized;
            var rawOrientationApi = new Quaternion(
                -unityRotation.x, -unityRotation.y, unityRotation.z, unityRotation.w
            ).normalized;
            if (!hasFiltered6D)
            {
                trackedPositionMm = rawPositionMm;
                trackedOrientationApi = rawOrientationApi;
                hasFiltered6D = true;
            }
            else
            {
                var positionAlpha = 1f - Mathf.Exp(-positionResponse * Time.unscaledDeltaTime);
                var rotationAlpha = 1f - Mathf.Exp(-rotationResponse * Time.unscaledDeltaTime);
                trackedPositionMm = Vector3.Lerp(
                    trackedPositionMm, rawPositionMm, positionAlpha
                );
                trackedOrientationApi = Quaternion.Slerp(
                    trackedOrientationApi, rawOrientationApi, rotationAlpha
                ).normalized;
            }

            status = "LIVE — one 36h11 tag, 6-DoF stylus";
            sample = new TrackedToolSample
            {
                PositionMm = trackedPositionMm,
                OrientationApi = trackedOrientationApi,
                HasOrientation = true,
                ForceN = 0f,
                Contact = false,
                Quality = Mathf.Clamp01(packet.quality),
                SourceHealthy = true,
                ForceMeasurementValid = false,
                DeviceId = "opencv-36h11-stylus",
                Status = status
            };
            return true;
        }

        private static bool IsFinite(Quaternion value)
        {
            return !float.IsNaN(value.x) && !float.IsInfinity(value.x) &&
                   !float.IsNaN(value.y) && !float.IsInfinity(value.y) &&
                   !float.IsNaN(value.z) && !float.IsInfinity(value.z) &&
                   !float.IsNaN(value.w) && !float.IsInfinity(value.w);
        }

        private void OnEnable()
        {
            try
            {
                udp = new UdpClient(port);
            }
            catch (SocketException error)
            {
                UnityEngine.Debug.LogError($"Tag/FSR input could not bind UDP port {port}: {error.Message}");
                return;
            }
            running = true;
            thread = new Thread(Listen) { IsBackground = true };
            thread.Start();
        }

        private void OnDisable()
        {
            running = false;
            udp?.Close();
            udp = null;
        }

        private void Listen()
        {
            var endpoint = new IPEndPoint(IPAddress.Any, 0);
            while (running)
            {
                try
                {
                    var bytes = udp.Receive(ref endpoint);
                    var json = Encoding.UTF8.GetString(bytes);
                    lock (lockObj) { latestJson = json; receivedAt = clock.Elapsed.TotalSeconds; }
                }
                catch (SocketException) { }
                catch (ObjectDisposedException) { break; }
            }
        }
    }
}
