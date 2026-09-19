using System.Collections;
using UnityEngine;

namespace SurgePrep
{
    /// <summary>Shows the physical camera feed; pose detection remains controller-owned.</summary>
    public sealed class UnityCameraPreview : MonoBehaviour
    {
        [SerializeField] private int requestedWidth = 640;
        [SerializeField] private int requestedHeight = 480;
        [SerializeField] private int requestedFps = 30;
        [SerializeField] private bool visible = true;
        [SerializeField] private bool mirror = true;
        private WebCamTexture cameraTexture;
        private string status = "Camera: starting…";
        private GUIStyle titleStyle;
        private GUIStyle statusStyle;

        public bool CameraAvailable => cameraTexture != null && cameraTexture.isPlaying;
        public string Status => status;

        private void Start() { StartCoroutine(StartCamera()); }

        private IEnumerator StartCamera()
        {
            if (!Application.HasUserAuthorization(UserAuthorization.WebCam))
                yield return Application.RequestUserAuthorization(UserAuthorization.WebCam);
            if (!Application.HasUserAuthorization(UserAuthorization.WebCam))
            {
                status = "Camera: permission denied";
                yield break;
            }
            var devices = WebCamTexture.devices;
            if (devices == null || devices.Length == 0)
            {
                status = "Camera: no device found";
                yield break;
            }
            cameraTexture = new WebCamTexture(devices[0].name, requestedWidth, requestedHeight, requestedFps);
            cameraTexture.Play();
            status = $"Camera: {devices[0].name}";
        }

        private void Update()
        {
            if (ShowcaseInput.Pressed(KeyCode.V)) visible = !visible;
        }

        private void OnGUI()
        {
            if (!visible) return;
            EnsureStyles();
            var panel = new Rect(18f, Screen.height - 244f, 350f, 226f);
            GUI.Box(panel, GUIContent.none);
            GUI.Label(new Rect(panel.x + 12f, panel.y + 10f, 320f, 22f), "PHYSICAL CAMERA", titleStyle);
            GUI.Label(new Rect(panel.x + 12f, panel.y + 34f, 320f, 20f), status + "  [V] hide", statusStyle);
            if (cameraTexture == null || !cameraTexture.isPlaying)
            {
                GUI.Label(new Rect(panel.x + 12f, panel.y + 72f, 320f, 60f),
                    "No live image yet. Check permission and device connection.", statusStyle);
                return;
            }
            var preview = new Rect(panel.x + 12f, panel.y + 60f, 326f, 154f);
            var previousMatrix = GUI.matrix;
            if (mirror)
                GUIUtility.ScaleAroundPivot(new Vector2(-1f, 1f),
                    new Vector2(preview.x + preview.width / 2f, preview.y + preview.height / 2f));
            GUI.DrawTexture(preview, cameraTexture, ScaleMode.ScaleToFit, false);
            GUI.matrix = previousMatrix;
        }

        private void OnDestroy()
        {
            if (cameraTexture != null && cameraTexture.isPlaying) cameraTexture.Stop();
        }

        private void EnsureStyles()
        {
            if (titleStyle != null) return;
            titleStyle = new GUIStyle(GUI.skin.label) { fontSize = 15, fontStyle = FontStyle.Bold };
            statusStyle = new GUIStyle(GUI.skin.label) { fontSize = 10, wordWrap = true };
        }
    }
}
