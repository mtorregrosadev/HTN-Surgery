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
        [SerializeField] private bool swapAxes;                   // tick if the cut corridor runs along your table's other axis

        [Header("FSR -> tip height")]
        [SerializeField] private float hoverMm = 6f;               // height above skin with no pressure
        [SerializeField, Range(0f, 0.5f)] private float deadband = 0.02f;
        // Pressure (0..1) at which the tip reaches the skin. Any touch above the deadband lowers the tip here.
        [SerializeField, Range(0.005f, 0.3f)] private float touchPressure = 0.03f;
        // Control points: at pressure[i] the tip is depthMm[i] below the skin (linear in between).
        // Each layer gets a comfortable slice of the range and the tip rests inside the layer being worked:
        //   0.03-0.25 skin (0-2.8 mm)   0.25-0.45 fat (to 9.5)   0.45-0.55 open tract (to 15.3)
        //   0.55-0.75 muscle (to 22)    0.75-0.80 open tract (to 25.3)   0.80-1.00 pleura (to 31.5)
        [SerializeField] private float[] pressurePoints = { 0.03f, 0.25f, 0.45f, 0.55f, 0.75f, 0.80f, 1.00f };
        [SerializeField] private float[] depthMm = { 0f, 2.8f, 9.5f, 15.3f, 22f, 25.3f, 31.5f };
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

            var across = swapAxes ? p.y : p.x;
            var down = swapAxes ? p.x : p.y;
            var x = (across - 0.5f) * 2f * xRangeMm * (invertX ? -1f : 1f);
            var z = (down - 0.5f) * 2f * zRangeMm * (invertZ ? -1f : 1f);
            var pressed = tagsVisible ? Mathf.Clamp01((p.force - deadband) / (1f - deadband)) : 0f;
            var y = TipHeightMm(pressed);

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
            contact = pressed >= touchPressure;
        }

        /// <summary>
        /// Tip height above (+) or below (-) the skin for a pressure 0..1. A touch lowers the tip onto the skin,
        /// then the control points map pressure to depth so each layer has its own comfortable slice.
        /// </summary>
        public float TipHeightMm(float pressed)
        {
            pressed = Mathf.Clamp01(pressed);
            if (pressed <= touchPressure)
            {
                return Mathf.Lerp(hoverMm, 0f, pressed / Mathf.Max(touchPressure, 0.0001f));
            }
            var count = Mathf.Min(pressurePoints.Length, depthMm.Length);
            if (count < 2)
            {
                return 0f;
            }
            if (pressed >= pressurePoints[count - 1])
            {
                return -depthMm[count - 1];
            }
            for (var index = 1; index < count; index++)
            {
                if (pressed <= pressurePoints[index])
                {
                    var t = Mathf.InverseLerp(pressurePoints[index - 1], pressurePoints[index], pressed);
                    return -Mathf.Lerp(depthMm[index - 1], depthMm[index], t);
                }
            }
            return -depthMm[count - 1];
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
