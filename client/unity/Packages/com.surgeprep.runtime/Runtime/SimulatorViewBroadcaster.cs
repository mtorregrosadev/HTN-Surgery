using System;
using System.Net;
using System.Net.Sockets;
using UnityEngine;

namespace SurgePrep
{
    /// <summary>
    /// Streams a top-down orthographic plan view of the surgical field to the
    /// Python tracker, which warps it onto the physical desk so the operator
    /// works inside the virtual field instead of glancing at a second screen.
    ///
    /// Deliberately does *not* follow the operator's viewpoint: the image has
    /// to be a stable, true-scale plan of the field for the homography onto
    /// the flat desk to hold. A perspective or user-steered view would shear
    /// the anatomy and break the mapping.
    ///
    /// Read-only with respect to the showcase: it renders the scene through
    /// its own off-screen camera and never alters it. Deleting this file fully
    /// reverts the behaviour.
    /// </summary>
    public sealed class SimulatorViewBroadcaster : MonoBehaviour
    {
        public const int DefaultPort = 8302;

        // 384x264 is 320:220, the aspect of the tracker's default desk area, so
        // the warp onto the table introduces no stretching.
        private const int Width = 384;
        private const int Height = 264;
        private const int JpegQuality = 55;
        private const float TargetFps = 15f;

        // Half-depth, in metres, of the patch of simulation the top-down camera
        // covers. 0.11 m makes the captured field 320x220 mm, matching the
        // tracker's default desk area one-to-one: a 10 mm hand movement is a
        // 10 mm movement across the projected image. Shrink this to magnify the
        // surgical field at the cost of breaking that 1:1 correspondence.
        private const float FieldHalfDepthMetres = 0.11f;

        // Height above the incision site to sit at. Orthographic, so this only
        // needs to clear the anatomy; it does not affect framing or scale.
        private const float CameraHeightMetres = 0.5f;

        // The same anchor DirectPoseReceiver hangs the tool from, so the
        // captured field and the tracked scalpel share one origin.
        private const string AnchorName = "RegistrationAnchor_SimulationPatch";

        // IPv4 caps a datagram at 65535 bytes including headers, and large
        // fragmented datagrams drop as a unit. Staying under this keeps every
        // frame to one unfragmented packet.
        private const int MaxDatagramBytes = 60000;

        [SerializeField] private int port = DefaultPort;

        private Camera previewCamera;
        private RenderTexture target;
        private Texture2D readback;
        private UdpClient socket;
        private IPEndPoint destination;
        private float nextCaptureTime;
        private bool warnedOversize;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        private static void Bootstrap()
        {
            var host = new GameObject("SimulatorViewBroadcaster");
            host.AddComponent<SimulatorViewBroadcaster>();
            DontDestroyOnLoad(host);
        }

        private void Start()
        {
            target = new RenderTexture(Width, Height, 24) { name = "SimulatorViewStream" };
            readback = new Texture2D(Width, Height, TextureFormat.RGB24, false);

            var cameraHost = new GameObject("Simulator view camera");
            cameraHost.transform.SetParent(transform, false);
            previewCamera = cameraHost.AddComponent<Camera>();
            // Rendered manually in LateUpdate so it costs nothing on frames
            // between captures, and never draws to the screen.
            previewCamera.enabled = false;
            previewCamera.targetTexture = target;

            // Straight down over the incision site. Orthographic so the image
            // is a true scale plan of the surgical field: a perspective view
            // would shear the anatomy and break the mapping onto the flat desk.
            previewCamera.orthographic = true;
            previewCamera.orthographicSize = FieldHalfDepthMetres;
            previewCamera.aspect = (float)Width / Height;
            previewCamera.nearClipPlane = 0.01f;
            previewCamera.farClipPlane = CameraHeightMetres * 2f;
            // A flat dark background keeps the composite legible where the
            // anatomy does not cover the field; a skybox from directly
            // overhead would just be noise.
            previewCamera.clearFlags = CameraClearFlags.SolidColor;
            previewCamera.backgroundColor = new Color(0.03f, 0.03f, 0.04f, 1f);

            var anchor = GameObject.Find(AnchorName);
            var centre = anchor != null ? anchor.transform.position : Vector3.zero;
            if (anchor == null)
            {
                Debug.LogWarning(
                    $"[SimView] Anchor '{AnchorName}' not found; framing the world origin. "
                    + "The projected area may not line up with the incision site."
                );
            }
            // Looking down -Y. Yaw 0 keeps simulation +X to image right and
            // +Z to image up, which is the mapping the tracker assumes when it
            // warps this onto the desk.
            cameraHost.transform.SetPositionAndRotation(
                centre + Vector3.up * CameraHeightMetres,
                Quaternion.Euler(90f, 0f, 0f)
            );

            try
            {
                socket = new UdpClient();
                destination = new IPEndPoint(IPAddress.Loopback, port);
                Debug.Log($"[SimView] Streaming simulator view to udp://127.0.0.1:{port}");
            }
            catch (Exception error)
            {
                Debug.LogError($"[SimView] Could not open UDP socket: {error.Message}");
            }
        }

        private void LateUpdate()
        {
            if (socket == null || previewCamera == null) return;
            if (Time.unscaledTime < nextCaptureTime) return;
            nextCaptureTime = Time.unscaledTime + 1f / TargetFps;

            // The camera is fixed over the incision site, so nothing needs
            // re-aiming per frame; it deliberately does not follow the
            // operator's viewpoint, because the image must stay a stable plan
            // view to map onto the desk.
            previewCamera.Render();

            var previous = RenderTexture.active;
            RenderTexture.active = target;
            readback.ReadPixels(new Rect(0, 0, Width, Height), 0, 0, false);
            readback.Apply(false);
            RenderTexture.active = previous;

            var jpeg = readback.EncodeToJPG(JpegQuality);
            if (jpeg.Length > MaxDatagramBytes)
            {
                if (!warnedOversize)
                {
                    warnedOversize = true;
                    Debug.LogWarning(
                        $"[SimView] Frame is {jpeg.Length} B, above the {MaxDatagramBytes} B "
                        + "datagram budget; skipping oversized frames."
                    );
                }
                return;
            }

            try
            {
                socket.Send(jpeg, jpeg.Length, destination);
            }
            catch (Exception error)
            {
                Debug.LogWarning($"[SimView] Send failed: {error.Message}");
            }
        }

        private void OnDestroy()
        {
            if (socket != null)
            {
                socket.Close();
                socket = null;
            }
            if (previewCamera != null)
            {
                previewCamera.targetTexture = null;
            }
            if (target != null)
            {
                target.Release();
                target = null;
            }
        }
    }
}
