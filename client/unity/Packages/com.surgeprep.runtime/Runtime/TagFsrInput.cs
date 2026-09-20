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
    /// Receives scalpel input from hardware/tag_fsr_bridge.py over UDP and turns it into a
    /// scalpel pose in API/SOFA millimetres:
    ///   AprilTag position -> x / z over the skin
    ///   FSR pressure      -> tool height y, so pressing harder cuts deeper
    /// <see cref="UnityManualDemoClient"/> sends the result through the normal
    /// Unity -> controller -> API -> SOFA path; SOFA still decides contact and carving.
    /// </summary>
    public sealed class TagFsrInput : MonoBehaviour
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

        [Serializable] private class Packet { public float x, y, force; public int tags; }

        private UdpClient udp;
        private Thread thread;
        private volatile bool running;
        private readonly object lockObj = new object();
        private string latestJson;
        private readonly Stopwatch clock = Stopwatch.StartNew();
        private double receivedAt = double.NegativeInfinity;
        private Vector3 lastPose = new Vector3(0f, 6f, 0f);
        private float lastDepth01;

        /// <summary>True while the bridge is sending fresh packets.</summary>
        public bool HasSignal
        {
            get { lock (lockObj) { return latestJson != null && clock.Elapsed.TotalSeconds - receivedAt < staleSeconds; } }
        }

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
