using UnityEngine;

namespace SurgePrep
{
    /// <summary>
    /// Desktop preview for the phone-VR presentation. An Android build should
    /// enable its Cardboard/XR loader; this component then leaves the camera to
    /// Unity XR. Press V in the editor to preview side-by-side eye views.
    /// </summary>
    public sealed class PhoneVrRig : MonoBehaviour
    {
        [SerializeField] private Camera sceneCamera;
        [SerializeField] private bool sideBySidePreview;
        [SerializeField, Range(0.04f, 0.08f)] private float eyeSeparationMetres = 0.064f;

        private Camera rightEye;
        private Rect originalRect;

        private void Awake()
        {
            if (sceneCamera == null)
            {
                sceneCamera = GetComponent<Camera>();
            }
            originalRect = sceneCamera != null ? sceneCamera.rect : new Rect(0f, 0f, 1f, 1f);
            if (sideBySidePreview)
            {
                SetSideBySide(true);
            }
        }

        private void Update()
        {
            if (sceneCamera != null && Input.GetKeyDown(KeyCode.V))
            {
                SetSideBySide(rightEye == null);
            }
        }

        private void OnDestroy()
        {
            if (rightEye != null)
            {
                Destroy(rightEye.gameObject);
            }
        }

        public void SetSideBySide(bool enabled)
        {
            if (sceneCamera == null)
            {
                return;
            }
            if (!enabled)
            {
                sceneCamera.rect = originalRect;
                if (rightEye != null)
                {
                    Destroy(rightEye.gameObject);
                    rightEye = null;
                }
                return;
            }

            sceneCamera.rect = new Rect(0f, 0f, 0.5f, 1f);
            var rightObject = new GameObject("Phone VR Right Eye");
            rightObject.transform.SetParent(sceneCamera.transform.parent, true);
            rightEye = rightObject.AddComponent<Camera>();
            rightEye.CopyFrom(sceneCamera);
            rightEye.rect = new Rect(0.5f, 0f, 0.5f, 1f);
            rightEye.transform.SetPositionAndRotation(
                sceneCamera.transform.position + sceneCamera.transform.right * eyeSeparationMetres,
                sceneCamera.transform.rotation
            );
            rightEye.depth = sceneCamera.depth + 1f;
            var listener = rightObject.GetComponent<AudioListener>();
            if (listener != null)
            {
                Destroy(listener);
            }
        }
    }
}
