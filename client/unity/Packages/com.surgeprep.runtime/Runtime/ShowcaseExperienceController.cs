using UnityEngine;

namespace SurgePrep
{
    public sealed class ShowcaseExperienceController : MonoBehaviour
    {
        [SerializeField] private Camera sceneCamera;
        [SerializeField] private Transform chestFocus;
        [SerializeField] private GameObject skinLayer;
        [SerializeField] private GameObject muscleLayer;
        [SerializeField] private GameObject boneLayer;
        [SerializeField] private GameObject cartilageLayer;
        [SerializeField] private GameObject diaphragmLayer;
        [SerializeField] private float orbitSensitivity = 3.0f;
        [SerializeField] private float zoomSensitivity = 0.09f;

        private Vector3 focus;
        private float distance;
        private float yaw;
        private float pitch;
        private GUIStyle hintStyle;
        private GUIStyle buttonStyle;

        private void Awake()
        {
            if (sceneCamera == null)
            {
                sceneCamera = Camera.main;
            }
            SetChestView();
            ApplyCamera();
        }

        private void Update()
        {
            if (sceneCamera == null)
            {
                return;
            }

            if (Input.GetKeyDown(KeyCode.C)) SetChestView();
            if (Input.GetKeyDown(KeyCode.O)) SetRoomView();
            if (Input.GetKeyDown(KeyCode.Alpha1)) Toggle(skinLayer);
            if (Input.GetKeyDown(KeyCode.Alpha2)) Toggle(muscleLayer);
            if (Input.GetKeyDown(KeyCode.Alpha3)) Toggle(boneLayer);

            var scroll = Input.mouseScrollDelta.y;
            if (Mathf.Abs(scroll) > 0.001f)
            {
                distance = Mathf.Clamp(distance - scroll * zoomSensitivity, 0.38f, 2.4f);
            }
            if (Input.GetMouseButton(1))
            {
                yaw += Input.GetAxis("Mouse X") * orbitSensitivity;
                pitch -= Input.GetAxis("Mouse Y") * orbitSensitivity;
                yaw = Mathf.Clamp(yaw, -78f, 78f);
                pitch = Mathf.Clamp(pitch, -42f, 42f);
            }
        }

        private void LateUpdate()
        {
            ApplyCamera();
        }

        private void OnGUI()
        {
            EnsureStyles();
            var width = 620f;
            var toolbar = new Rect((Screen.width - width) * 0.5f, Screen.height - 60f, width, 42f);
            DrawRect(toolbar, new Color(0.018f, 0.035f, 0.055f, 0.94f));

            if (GUI.Button(new Rect(toolbar.x + 10f, toolbar.y + 7f, 82f, 28f), "CHEST", buttonStyle))
                SetChestView();
            if (GUI.Button(new Rect(toolbar.x + 98f, toolbar.y + 7f, 82f, 28f), "ROOM", buttonStyle))
                SetRoomView();
            if (GUI.Button(new Rect(toolbar.x + 194f, toolbar.y + 7f, 82f, 28f), Label("SKIN", skinLayer), buttonStyle))
                Toggle(skinLayer);
            if (GUI.Button(new Rect(toolbar.x + 282f, toolbar.y + 7f, 92f, 28f), Label("MUSCLE", muscleLayer), buttonStyle))
                Toggle(muscleLayer);
            if (GUI.Button(new Rect(toolbar.x + 380f, toolbar.y + 7f, 82f, 28f), Label("BONE", boneLayer), buttonStyle))
                Toggle(boneLayer);
            GUI.Label(
                new Rect(toolbar.x + 474f, toolbar.y + 7f, 138f, 28f),
                "Right-drag orbit\nScroll to zoom",
                hintStyle
            );
        }

        private void SetChestView()
        {
            focus = chestFocus != null ? chestFocus.position : new Vector3(0f, -0.07f, 0.15f);
            distance = 0.64f;
            yaw = 0f;
            pitch = 2f;
        }

        private void SetRoomView()
        {
            focus = new Vector3(0f, -0.18f, 0.05f);
            distance = 1.75f;
            yaw = 0f;
            pitch = 4f;
        }

        private void ApplyCamera()
        {
            if (sceneCamera == null)
            {
                return;
            }
            var orbit = Quaternion.Euler(pitch, yaw, 0f);
            sceneCamera.transform.position = focus + orbit * Vector3.forward * distance;
            sceneCamera.transform.LookAt(focus, Vector3.up);
        }

        private static void Toggle(GameObject layer)
        {
            if (layer != null)
            {
                layer.SetActive(!layer.activeSelf);
            }
        }

        private static string Label(string name, GameObject layer)
        {
            return $"{name} {(layer != null && layer.activeSelf ? "ON" : "OFF")}";
        }

        private void EnsureStyles()
        {
            if (buttonStyle != null)
            {
                return;
            }
            buttonStyle = new GUIStyle(GUI.skin.button)
            {
                fontSize = 11,
                fontStyle = FontStyle.Bold,
                normal = { textColor = Color.white },
                hover = { textColor = new Color(0.1f, 0.95f, 0.82f) }
            };
            hintStyle = new GUIStyle(GUI.skin.label)
            {
                fontSize = 10,
                alignment = TextAnchor.MiddleLeft,
                normal = { textColor = new Color(0.65f, 0.76f, 0.82f) }
            };
        }

        private static void DrawRect(Rect rectangle, Color colour)
        {
            var previous = GUI.color;
            GUI.color = colour;
            GUI.DrawTexture(rectangle, Texture2D.whiteTexture);
            GUI.color = previous;
        }
    }
}
