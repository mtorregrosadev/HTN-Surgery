using UnityEngine;

namespace SurgePrep
{
    public sealed class ShowcaseExperienceController : MonoBehaviour
    {
        [SerializeField] private Camera sceneCamera;
        [SerializeField] private Transform chestFocus;
        [SerializeField] private Transform targetFocus;
        [SerializeField] private Transform roomFocus;
        [SerializeField] private GameObject skinLayer;
        [SerializeField] private GameObject muscleLayer;
        [SerializeField] private GameObject boneLayer;
        [SerializeField] private GameObject cartilageLayer;
        [SerializeField] private GameObject diaphragmLayer;
        [SerializeField] private float orbitSensitivity = 0.18f;
        [SerializeField] private float zoomSensitivity = 0.09f;
        [SerializeField] private float panSensitivity = 0.0018f;
        [SerializeField] private float presetSeconds = 0.85f;
        [SerializeField] private float introOrbitSeconds = 3.2f;

        private Vector3 focus;
        private Vector3 targetFocusPoint;
        private float distance;
        private float targetDistance;
        private float yaw;
        private float targetYaw;
        private float pitch;
        private float targetPitch;
        private float introRemaining;
        private bool cutaway;
        private float presetBlend;

        private void Awake()
        {
            if (sceneCamera == null)
            {
                sceneCamera = Camera.main;
            }
            SetRoomView(false);
            introRemaining = introOrbitSeconds;
            ApplyCamera(true);
        }

        private void Update()
        {
            if (sceneCamera == null)
            {
                return;
            }

            if (introRemaining > 0f)
            {
                introRemaining -= Time.unscaledDeltaTime;
                targetYaw += 42f * Time.unscaledDeltaTime;
                if (introRemaining <= 0f)
                {
                    SetSurgeonView(false);
                }
            }
            else
            {
                if (ShowcaseInput.Pressed(KeyCode.C)) SetSurgeonView(false);
                if (ShowcaseInput.Pressed(KeyCode.F)) SetTargetView(false);
                if (ShowcaseInput.Pressed(KeyCode.O)) SetRoomView(false);
                if (ShowcaseInput.Pressed(KeyCode.K))
                {
                    cutaway = !cutaway;
                    ApplyCutaway();
                }
            }

            var scroll = ShowcaseInput.MouseScroll();
            if (Mathf.Abs(scroll) > 0.001f)
            {
                targetDistance = Mathf.Clamp(targetDistance - scroll * zoomSensitivity, 0.18f, 4.8f);
            }
            if (ShowcaseInput.RightMouseHeld())
            {
                var delta = ShowcaseInput.MouseDelta();
                targetYaw += delta.x * orbitSensitivity;
                targetPitch = Mathf.Clamp(targetPitch - delta.y * orbitSensitivity, 8f, 82f);
            }
            if (ShowcaseInput.MiddleMouseHeld())
            {
                var delta = ShowcaseInput.MouseDelta();
                var right = sceneCamera.transform.right;
                var up = Vector3.up;
                targetFocusPoint -= (right * delta.x + up * delta.y) * panSensitivity * targetDistance;
            }
        }

        private void LateUpdate()
        {
            var amount = 1f - Mathf.Exp(-8f * Time.unscaledDeltaTime / Mathf.Max(0.12f, presetSeconds));
            yaw = Mathf.LerpAngle(yaw, targetYaw, amount);
            pitch = Mathf.Lerp(pitch, targetPitch, amount);
            distance = Mathf.Lerp(distance, targetDistance, amount);
            focus = Vector3.Lerp(focus, targetFocusPoint, amount);
            ApplyCamera(false);
        }

        public void SetSurgeonView(bool snap)
        {
            targetFocusPoint = chestFocus != null ? chestFocus.position : new Vector3(0.12f, 1.02f, 0.04f);
            targetDistance = 0.72f;
            targetYaw = 18f;
            targetPitch = 52f;
            if (snap) Snap();
        }

        public void SetRoomView(bool snap)
        {
            targetFocusPoint = roomFocus != null ? roomFocus.position : new Vector3(0f, 0.95f, 0f);
            targetDistance = 3.4f;
            targetYaw = 28f;
            targetPitch = 28f;
            if (snap) Snap();
        }

        public void SetTargetView(bool snap)
        {
            targetFocusPoint = targetFocus != null
                ? targetFocus.position
                : new Vector3(0.12f, 1.03f, 0.04f);
            targetDistance = 0.26f;
            targetYaw = 8f;
            targetPitch = 62f;
            if (snap) Snap();
        }

        private void Snap()
        {
            focus = targetFocusPoint;
            distance = targetDistance;
            yaw = targetYaw;
            pitch = targetPitch;
        }

        private void ApplyCamera(bool immediate)
        {
            if (immediate) Snap();
            if (sceneCamera == null) return;
            var orbit = Quaternion.Euler(pitch, yaw, 0f);
            sceneCamera.transform.position = focus + orbit * (Vector3.back * distance);
            sceneCamera.transform.LookAt(focus, Vector3.up);
        }

        private void ApplyCutaway()
        {
            if (skinLayer != null) skinLayer.SetActive(!cutaway);
            if (muscleLayer != null) muscleLayer.SetActive(true);
            if (boneLayer != null) boneLayer.SetActive(true);
        }
    }
}
