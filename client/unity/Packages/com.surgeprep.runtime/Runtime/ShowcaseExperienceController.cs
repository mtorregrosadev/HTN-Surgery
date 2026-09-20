using UnityEngine;

namespace SurgePrep
{
    public sealed class ShowcaseExperienceController : MonoBehaviour
    {
        [SerializeField] private Camera sceneCamera;
        [SerializeField] private Transform chestFocus;
        [SerializeField] private Transform targetFocus;
        [SerializeField] private Transform roomFocus;
        [SerializeField] private Transform headFocus;
        [SerializeField] private GameObject skinLayer;
        [SerializeField] private GameObject muscleLayer;
        [SerializeField] private GameObject boneLayer;
        [SerializeField] private GameObject cartilageLayer;
        [SerializeField] private GameObject diaphragmLayer;
        [SerializeField] private float orbitSensitivity = 0.42f;
        [SerializeField] private float zoomSensitivity = 0.22f;
        [SerializeField] private float panSensitivity = 0.0045f;
        [SerializeField] private float presetSeconds = 0.85f;
        [SerializeField] private float introOrbitSeconds = 3.2f;
        [SerializeField] private float turntableDegreesPerSecond = 16f;
        private const float MinOrbitDistance = 0.42f;
        private const float MaxOrbitDistanceCap = 3.55f;
        private static readonly Bounds RoomBounds = new Bounds(
            new Vector3(0f, 1.52f, 0f), new Vector3(7.5f, 2.7f, 7.5f)
        );

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
        private bool turntable;

        private void Awake()
        {
            orbitSensitivity = 0.42f;
            zoomSensitivity = 0.22f;
            panSensitivity = 0.0045f;
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
                if (ShowcaseInput.Pressed(KeyCode.H)) SetHeadView(false);
                if (ShowcaseInput.Pressed(KeyCode.B)) SetOverheadView(false);
                if (ShowcaseInput.Pressed(KeyCode.T)) turntable = !turntable;
                if (ShowcaseInput.Pressed(KeyCode.K))
                {
                    cutaway = !cutaway;
                    ApplyCutaway();
                }
            }

            if (turntable && introRemaining <= 0f && !ShowcaseInput.OrbitMouseHeld())
            {
                // Slow 360-degree turntable around whatever is in focus.
                targetYaw += turntableDegreesPerSecond * Time.unscaledDeltaTime;
            }

            var scroll = ShowcaseInput.MouseScroll();
            if (Mathf.Abs(scroll) > 0.001f)
            {
                targetDistance = Mathf.Clamp(
                    targetDistance - scroll * zoomSensitivity,
                    MinOrbitDistance,
                    AllowedOrbitDistance(targetFocusPoint, targetPitch, targetYaw)
                );
                distance = targetDistance;
            }
            if (ShowcaseInput.OrbitMouseHeld())
            {
                var delta = ShowcaseInput.MouseDelta();
                targetYaw += delta.x * orbitSensitivity;
                targetPitch = Mathf.Clamp(targetPitch - delta.y * orbitSensitivity, -12f, 88f);
                yaw = targetYaw;
                pitch = targetPitch;
            }
            if (ShowcaseInput.MiddleMouseHeld())
            {
                var delta = ShowcaseInput.MouseDelta();
                var right = sceneCamera.transform.right;
                var up = Vector3.up;
                targetFocusPoint -= (right * delta.x + up * delta.y) * panSensitivity * targetDistance;
                targetFocusPoint = ClampInsideRoom(targetFocusPoint);
                focus = targetFocusPoint;
            }
        }

        private void LateUpdate()
        {
            var amount = 1f - Mathf.Exp(-8f * Time.unscaledDeltaTime / Mathf.Max(0.12f, presetSeconds));
            yaw = Mathf.LerpAngle(yaw, targetYaw, amount);
            pitch = Mathf.Lerp(pitch, targetPitch, amount);
            focus = Vector3.Lerp(focus, ClampInsideRoom(targetFocusPoint), amount);
            var maxDistance = AllowedOrbitDistance(focus, pitch, yaw);
            targetDistance = Mathf.Clamp(targetDistance, MinOrbitDistance, maxDistance);
            distance = Mathf.Clamp(Mathf.Lerp(distance, targetDistance, amount), MinOrbitDistance, maxDistance);
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
            // Look from the foot of the table toward the cabinet wall. This keeps
            // the ceiling booms above the sightline instead of clipping through
            // the camera and presents the room like a staffed teaching theatre.
            targetDistance = 3.25f;
            targetYaw = 154f;
            targetPitch = 20f;
            if (snap) Snap();
        }

        public void SetHeadView(bool snap)
        {
            targetFocusPoint = headFocus != null ? headFocus.position : new Vector3(0f, 1.1f, 0.8f);
            targetDistance = 0.7f;
            targetYaw = 165f;
            targetPitch = 42f;
            if (snap) Snap();
        }

        public void SetOverheadView(bool snap)
        {
            targetFocusPoint = roomFocus != null ? roomFocus.position : new Vector3(0f, 0.95f, 0f);
            targetDistance = 2.4f;
            targetYaw = 180f;
            targetPitch = 84f;
            if (snap) Snap();
        }

        public void SetTargetView(bool snap)
        {
            targetFocusPoint = targetFocus != null
                ? targetFocus.position
                : new Vector3(0.12f, 1.03f, 0.04f);
            targetDistance = 0.48f;
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
            var maxDistance = AllowedOrbitDistance(focus, pitch, yaw);
            distance = Mathf.Clamp(distance, MinOrbitDistance, maxDistance);
            var position = ClampInsideRoom(focus + orbit * (Vector3.back * distance));
            if (Vector3.Distance(position, focus) < MinOrbitDistance)
            {
                position = ClampInsideRoom(focus + orbit * (Vector3.back * MinOrbitDistance));
            }
            sceneCamera.transform.position = position;
            var toFocus = focus - position;
            if (toFocus.sqrMagnitude > 0.0001f)
            {
                var up = Vector3.up;
                if (Mathf.Abs(Vector3.Dot(toFocus.normalized, up)) > 0.96f)
                {
                    up = Vector3.forward;
                }
                sceneCamera.transform.rotation = Quaternion.LookRotation(toFocus, up);
            }
        }

        private static Vector3 ClampInsideRoom(Vector3 point)
        {
            return new Vector3(
                Mathf.Clamp(point.x, RoomBounds.min.x, RoomBounds.max.x),
                Mathf.Clamp(point.y, RoomBounds.min.y, RoomBounds.max.y),
                Mathf.Clamp(point.z, RoomBounds.min.z, RoomBounds.max.z)
            );
        }

        private static float AllowedOrbitDistance(Vector3 from, float pitchDeg, float yawDeg)
        {
            var dir = Quaternion.Euler(pitchDeg, yawDeg, 0f) * Vector3.back;
            return Mathf.Clamp(ExitDistance(from, dir) - 0.12f, MinOrbitDistance, MaxOrbitDistanceCap);
        }

        private static float ExitDistance(Vector3 origin, Vector3 dir)
        {
            if (dir.sqrMagnitude < 0.000001f)
            {
                return MinOrbitDistance;
            }
            dir.Normalize();
            var farthest = float.PositiveInfinity;
            for (var axis = 0; axis < 3; axis++)
            {
                var step = dir[axis];
                var start = origin[axis];
                var min = RoomBounds.min[axis];
                var max = RoomBounds.max[axis];
                if (Mathf.Abs(step) < 0.000001f)
                {
                    if (start < min || start > max)
                    {
                        return MinOrbitDistance;
                    }
                    continue;
                }
                farthest = Mathf.Min(farthest, Mathf.Max((min - start) / step, (max - start) / step));
            }
            return float.IsInfinity(farthest) ? MinOrbitDistance : Mathf.Max(MinOrbitDistance, farthest);
        }

        private void ApplyCutaway()
        {
            if (skinLayer != null) skinLayer.SetActive(!cutaway);
            if (muscleLayer != null) muscleLayer.SetActive(true);
            if (boneLayer != null) boneLayer.SetActive(true);
        }
    }
}
