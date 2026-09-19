using UnityEngine;

namespace SurgePrep
{
    /// <summary>Configures and previews the learner's physical work area.</summary>
    public sealed class WorkspaceConfigurationPanel : MonoBehaviour
    {
        [SerializeField] private Transform workspaceAnchor;
        [SerializeField, Min(20f)] private float widthMm = 120f;
        [SerializeField, Min(20f)] private float depthMm = 90f;
        [SerializeField, Min(0f)] private float heightMm;
        [SerializeField] private bool configurationValid;

        private bool visible = true;
        private LineRenderer outline;
        private GUIStyle titleStyle;
        private GUIStyle bodyStyle;

        public bool ConfigurationValid => configurationValid;
        public Vector2 WorkspaceSizeMm => new Vector2(widthMm, depthMm);
        public float HeightMm => heightMm;

        private void Awake()
        {
            if (workspaceAnchor == null) workspaceAnchor = transform;
            outline = gameObject.AddComponent<LineRenderer>();
            outline.useWorldSpace = false;
            outline.loop = true;
            outline.widthMultiplier = 0.0025f;
            outline.material = new Material(Shader.Find("Sprites/Default"));
            RefreshOutline();
        }

        private void Update()
        {
            if (ShowcaseInput.Pressed(KeyCode.Tab)) visible = !visible;
            RefreshOutline();
        }

        private void RefreshOutline()
        {
            if (outline == null) return;
            var width = widthMm * CoordinateFrame.MillimetresToMetres;
            var depth = depthMm * CoordinateFrame.MillimetresToMetres;
            var y = heightMm * CoordinateFrame.MillimetresToMetres + 0.002f;
            outline.positionCount = 4;
            outline.SetPosition(0, new Vector3(-width / 2f, y, -depth / 2f));
            outline.SetPosition(1, new Vector3(width / 2f, y, -depth / 2f));
            outline.SetPosition(2, new Vector3(width / 2f, y, depth / 2f));
            outline.SetPosition(3, new Vector3(-width / 2f, y, depth / 2f));
            outline.startColor = outline.endColor = configurationValid
                ? new Color(0.2f, 0.95f, 0.7f, 0.9f)
                : new Color(0.95f, 0.72f, 0.2f, 0.9f);
        }

        private void OnGUI()
        {
            if (!visible) return;
            EnsureStyles();
            var panel = new Rect(Screen.width - 332f, 22f, 310f, 260f);
            GUI.Box(panel, GUIContent.none);
            GUI.Label(new Rect(panel.x + 16, panel.y + 14, 280, 25), "WORKSTATION SETUP", titleStyle);
            GUI.Label(new Rect(panel.x + 16, panel.y + 44, 280, 28),
                "Define the physical tool area before calibration.", bodyStyle);
            GUI.Label(new Rect(panel.x + 16, panel.y + 82, 120, 20), $"Width  {widthMm:0} mm", bodyStyle);
            widthMm = GUI.HorizontalSlider(new Rect(panel.x + 130, panel.y + 88, 150, 18), widthMm, 40f, 240f);
            GUI.Label(new Rect(panel.x + 16, panel.y + 118, 120, 20), $"Depth  {depthMm:0} mm", bodyStyle);
            depthMm = GUI.HorizontalSlider(new Rect(panel.x + 130, panel.y + 124, 150, 18), depthMm, 40f, 200f);
            GUI.Label(new Rect(panel.x + 16, panel.y + 154, 120, 20), $"Height  {heightMm:0} mm", bodyStyle);
            heightMm = GUI.HorizontalSlider(new Rect(panel.x + 130, panel.y + 160, 150, 18), heightMm, 0f, 80f);
            GUI.Label(new Rect(panel.x + 16, panel.y + 190, 280, 22),
                configurationValid ? "AREA READY — proceed to calibration" : "AREA NOT VALIDATED", bodyStyle);
            if (GUI.Button(new Rect(panel.x + 16, panel.y + 220, 130, 28), "Validate area"))
            {
                configurationValid = widthMm >= 60f && depthMm >= 60f;
            }
            if (GUI.Button(new Rect(panel.x + 156, panel.y + 220, 124, 28), "Reset"))
            {
                widthMm = 120f;
                depthMm = 90f;
                heightMm = 0f;
                configurationValid = false;
            }
        }

        private void EnsureStyles()
        {
            if (titleStyle != null) return;
            titleStyle = new GUIStyle(GUI.skin.label) { fontSize = 16, fontStyle = FontStyle.Bold };
            bodyStyle = new GUIStyle(GUI.skin.label) { fontSize = 11, wordWrap = true };
        }
    }
}
