using System;
using System.Net;
using System.Net.Sockets;
using System.Threading;
using UnityEngine;

namespace SurgePrep
{
    /// <summary>
    /// Diagnostic bypass: renders the tracker's desk-frame pose directly.
    ///
    /// The authoritative path (tracker -> controller -> API -> SOFA -> Unity)
    /// rewrites Y by the chest surface height and is capped at the solver's
    /// step rate, so the instrument can land far below the body and is
    /// deactivated whenever a snapshot is older than the staleness timeout.
    /// This receiver reads the pose straight off UDP and assigns the transform,
    /// so the instrument renders at camera rate regardless of solver health.
    ///
    /// Read-only with respect to the rest of the showcase: it never sends,
    /// never touches <see cref="SimulationSceneRenderer"/>, and spawns its own
    /// visual. Deleting this file fully reverts the behaviour.
    /// </summary>
    public sealed class DirectPoseReceiver : MonoBehaviour
    {
        public const int DefaultPort = 8301;

        // The anchor the SOFA tool tip also hangs from, so the bypass marker
        // and the authoritative tool share one frame and can be compared.
        private const string AnchorName = "RegistrationAnchor_SimulationPatch";

        [SerializeField] private int port = DefaultPort;

        // Desk millimetres -> Unity metres. Kept separate from the 1:1 scale so
        // the physical-to-virtual mapping can be tuned without touching units.
        [SerializeField] private float workspaceScale = 1f;

        // 0 disables smoothing. Camera-rate input needs far less filtering than
        // the 4 Hz snapshot path, and smoothing here would hide real latency.
        [SerializeField, Min(0f)] private float interpolationSpeed = 0f;

        private UdpClient socket;
        private Thread receiveThread;
        private volatile bool running;

        private readonly object gate = new object();
        private Vector3 latestPositionMm;
        private Quaternion latestRotation = Quaternion.identity;
        private long packetCount;
        private bool hasPose;

        private Transform tool;
        private float lastReportTime = -1f;
        private long lastReportedCount;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        private static void Bootstrap()
        {
            var host = new GameObject("DirectPoseReceiver (bypass)");
            host.AddComponent<DirectPoseReceiver>();
            DontDestroyOnLoad(host);
        }

        private void Start()
        {
            var anchor = GameObject.Find(AnchorName);
            if (anchor == null)
            {
                Debug.LogWarning(
                    $"[DirectPose] Anchor '{AnchorName}' not found; using world origin. "
                    + "The marker will appear at the scene origin instead of the incision site."
                );
            }

            tool = BuildMarker(anchor != null ? anchor.transform : null);

            try
            {
                socket = new UdpClient(port);
                running = true;
                receiveThread = new Thread(ReceiveLoop) { IsBackground = true };
                receiveThread.Start();
                Debug.Log($"[DirectPose] Listening on udp://127.0.0.1:{port}");
            }
            catch (Exception error)
            {
                Debug.LogError($"[DirectPose] Could not bind UDP port {port}: {error.Message}");
            }
        }

        private Transform BuildMarker(Transform parent)
        {
            var root = new GameObject("Direct scalpel (bypass)");
            root.transform.SetParent(parent, false);

            // A bright unlit blade reads clearly against the tissue materials
            // even when it ends up inside a mesh, which is the failure this
            // component exists to diagnose.
            var blade = GameObject.CreatePrimitive(PrimitiveType.Cube);
            blade.name = "Blade";
            blade.transform.SetParent(root.transform, false);
            blade.transform.localPosition = new Vector3(0f, 0.02f, 0f);
            blade.transform.localScale = new Vector3(0.004f, 0.04f, 0.012f);
            Paint(blade, new Color(1f, 0.25f, 0.1f));

            var tip = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            tip.name = "Tip";
            tip.transform.SetParent(root.transform, false);
            tip.transform.localScale = Vector3.one * 0.006f;
            Paint(tip, new Color(1f, 0.95f, 0.2f));

            foreach (var collider in root.GetComponentsInChildren<Collider>())
            {
                // Purely a visual probe; colliders would perturb the showcase.
                Destroy(collider);
            }
            return root.transform;
        }

        private static void Paint(GameObject target, Color colour)
        {
            var shader = Shader.Find("Unlit/Color")
                ?? Shader.Find("Universal Render Pipeline/Unlit")
                ?? Shader.Find("Sprites/Default");
            if (shader == null) return;
            var material = new Material(shader) { name = "DirectPoseMarker" };
            if (material.HasProperty("_Color")) material.color = colour;
            if (material.HasProperty("_BaseColor")) material.SetColor("_BaseColor", colour);
            target.GetComponent<MeshRenderer>().sharedMaterial = material;
        }

        private void ReceiveLoop()
        {
            var endpoint = new IPEndPoint(IPAddress.Any, 0);
            while (running)
            {
                try
                {
                    var payload = socket.Receive(ref endpoint);
                    var json = System.Text.Encoding.UTF8.GetString(payload);
                    var pose = JsonUtility.FromJson<DirectPoseDto>(json);
                    if (pose == null) continue;
                    lock (gate)
                    {
                        latestPositionMm = new Vector3(pose.x, pose.y, pose.z);
                        latestRotation = new Quaternion(pose.qx, pose.qy, pose.qz, pose.qw);
                        hasPose = true;
                        packetCount++;
                    }
                }
                catch (SocketException)
                {
                    // Socket closed during shutdown.
                    return;
                }
                catch (Exception error)
                {
                    Debug.LogWarning($"[DirectPose] Dropped packet: {error.Message}");
                }
            }
        }

        private void Update()
        {
            if (tool == null) return;

            Vector3 positionMm;
            Quaternion rotation;
            long count;
            lock (gate)
            {
                if (!hasPose) return;
                positionMm = latestPositionMm;
                rotation = latestRotation;
                count = packetCount;
            }

            // Same handedness convention as CoordinateFrame: right-handed
            // millimetres in, left-handed metres out.
            var target = new Vector3(positionMm.x, positionMm.y, -positionMm.z)
                * (CoordinateFrame.MillimetresToMetres * workspaceScale);
            var targetRotation = new Quaternion(-rotation.x, -rotation.y, rotation.z, rotation.w);

            if (interpolationSpeed <= 0f)
            {
                tool.localPosition = target;
                tool.localRotation = targetRotation;
            }
            else
            {
                var amount = 1f - Mathf.Exp(-interpolationSpeed * Time.deltaTime);
                tool.localPosition = Vector3.Lerp(tool.localPosition, target, amount);
                tool.localRotation = Quaternion.Slerp(tool.localRotation, targetRotation, amount);
            }

            if (lastReportTime < 0f || Time.unscaledTime - lastReportTime >= 1f)
            {
                Debug.Log(
                    $"[DirectPose] {count - lastReportedCount} pkt/s  "
                    + $"in ({positionMm.x:0.0}, {positionMm.y:0.0}, {positionMm.z:0.0}) mm  "
                    + $"-> local {tool.localPosition}"
                );
                lastReportTime = Time.unscaledTime;
                lastReportedCount = count;
            }
        }

        private void OnDestroy()
        {
            running = false;
            socket?.Close();
            receiveThread?.Join(200);
        }

        [Serializable]
        private sealed class DirectPoseDto
        {
            public float x;
            public float y;
            public float z;
            public float qx;
            public float qy;
            public float qz;
            public float qw;
        }
    }
}
