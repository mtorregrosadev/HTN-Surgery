using UnityEngine;

namespace SurgePrep
{
    public enum SetupStep
    {
        FramingAndDistance = 1,
        WindowSelection = 2,
        ReadyToStart = 3
    }

    /// <summary>
    /// Guides the learner through a linear 3-step physical workspace setup:
    /// Step 1: Camera positioning and stepping back for tabletop clearance.
    /// Step 2: Interactive procedure window definition via camera feed.
    /// Step 3: Registration validation and launching active surgical rehearsal.
    /// </summary>
    public sealed class WorkspaceConfigurationPanel : MonoBehaviour
    {
        [SerializeField] private Transform workspaceAnchor;
        [SerializeField, Min(20f)] private float widthMm = 120f;
        [SerializeField, Min(20f)] private float depthMm = 90f;
        [SerializeField, Min(0f)] private float heightMm = 0f;
        [SerializeField] private bool configurationValid;
        [SerializeField] private bool validatedViaCamera;
        [SerializeField] private SetupStep currentStep = SetupStep.FramingAndDistance;
        [SerializeField] private bool isRehearsalStarted = true;

        private bool panelVisible = true;
        private LineRenderer outline;
        private GUIStyle titleStyle;
        private GUIStyle headerStyle;
        private GUIStyle bodyStyle;
        private GUIStyle alertStyle;
        private GUIStyle statusStyle;
        private GUIStyle buttonPrimaryStyle;

        public bool ConfigurationValid => configurationValid;
        public Vector2 WorkspaceSizeMm => new Vector2(widthMm, depthMm);
        public float HeightMm => heightMm;
        public bool ValidatedViaCamera => validatedViaCamera;
        public SetupStep CurrentStep => currentStep;
        public bool IsRehearsalStarted => isRehearsalStarted;

        public void SetFromCamera(float newWidthMm, float newDepthMm)
        {
            widthMm = Mathf.Clamp(newWidthMm, 40f, 240f);
            depthMm = Mathf.Clamp(newDepthMm, 40f, 200f);
            configurationValid = widthMm >= 50f && depthMm >= 50f;
            validatedViaCamera = true;
            RefreshOutline();
        }

        public void ValidateArea()
        {
            configurationValid = widthMm >= 50f && depthMm >= 50f;
            RefreshOutline();
        }

        public void ResetArea()
        {
            widthMm = 120f;
            depthMm = 90f;
            heightMm = 0f;
            configurationValid = false;
            validatedViaCamera = false;
            currentStep = SetupStep.FramingAndDistance;
            isRehearsalStarted = false;
            RefreshOutline();
        }

        public void StartRehearsal()
        {
            configurationValid = true;
            isRehearsalStarted = true;
            var camCtrl = FindFirstObjectByType<ShowcaseExperienceController>();
            if (camCtrl != null)
            {
                camCtrl.SetTargetView(false);
            }
        }

        public void SetStep(SetupStep step)
        {
            currentStep = step;
            var camCtrl = FindFirstObjectByType<ShowcaseExperienceController>();
            if (camCtrl != null)
            {
                if (step == SetupStep.FramingAndDistance)
                {
                    camCtrl.SetSurgeonView(false);
                }
                else
                {
                    camCtrl.SetTargetView(false);
                }
            }
        }

        public void ReopenSetup()
        {
            isRehearsalStarted = false;
            SetStep(SetupStep.WindowSelection);
            panelVisible = true;
        }

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
            if (ShowcaseInput.Pressed(KeyCode.Tab) && isRehearsalStarted)
            {
                panelVisible = !panelVisible;
            }

            // Keyboard shortcut to advance linear steps
            if (!isRehearsalStarted)
            {
                if (ShowcaseInput.Pressed(KeyCode.Space))
                {
                    if (currentStep == SetupStep.FramingAndDistance) SetStep(SetupStep.WindowSelection);
                    else if (currentStep == SetupStep.WindowSelection) SetStep(SetupStep.ReadyToStart);
                    else if (currentStep == SetupStep.ReadyToStart) StartRehearsal();
                }
            }

            RefreshOutline();
        }

        public void RefreshOutline()
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
            EnsureStyles();

            // When rehearsal is running, keep screen clear with just a small badge
            if (isRehearsalStarted)
            {
                if (GUI.Button(new Rect(Screen.width - 240f, 14f, 224f, 28f), $"Workspace: {widthMm:0}×{depthMm:0} mm  [Setup]"))
                {
                    ReopenSetup();
                }
                return;
            }

            if (!panelVisible) return;

            var panelWidth = 380f;
            var panelHeight = currentStep == SetupStep.WindowSelection ? 340f : 280f;
            var panel = new Rect(Screen.width - panelWidth - 20f, 20f, panelWidth, panelHeight);

            DrawSolid(panel, new Color(0.07f, 0.1f, 0.14f, 0.95f));
            DrawBorder(panel, 2f, new Color(0.2f, 0.55f, 0.75f, 0.85f));

            var x = panel.x + 18f;
            var w = panelWidth - 36f;
            var y = panel.y + 14f;

            GUI.Label(new Rect(x, y, w, 24f), $"SURGE PREP — SETUP ({(int)currentStep} / 3)", titleStyle);
            y += 26f;

            switch (currentStep)
            {
                case SetupStep.FramingAndDistance:
                    RenderStep1(x, ref y, w, panel);
                    break;
                case SetupStep.WindowSelection:
                    RenderStep2(x, ref y, w, panel);
                    break;
                case SetupStep.ReadyToStart:
                    RenderStep3(x, ref y, w, panel);
                    break;
            }
        }

        private void RenderStep1(float x, ref float y, float w, Rect panel)
        {
            GUI.Label(new Rect(x, y, w, 22f), "Step 1: Position Camera & Workstation", headerStyle);
            y += 26f;

            // Prominent recommendation callout
            var alertBox = new Rect(x, y, w, 70f);
            DrawSolid(alertBox, new Color(0.12f, 0.25f, 0.35f, 0.85f));
            DrawBorder(alertBox, 1.5f, new Color(0.3f, 0.75f, 0.95f, 0.9f));
            GUI.Label(new Rect(alertBox.x + 10f, alertBox.y + 8f, alertBox.width - 20f, 54f),
                "RECOMMENDATION:\nPlease step back from the camera to ensure your physical hands and tabletop workspace are clearly visible.",
                alertStyle);
            y += 82f;

            GUI.Label(new Rect(x, y, w, 36f),
                "Check the live camera video on the bottom-left to frame your synthetic surface.",
                bodyStyle);
            y += 42f;

            if (GUI.Button(new Rect(x, panel.yMax - 44f, w, 32f), "Next: Define Procedure Window →"))
            {
                SetStep(SetupStep.WindowSelection);
            }
        }

        private void RenderStep2(float x, ref float y, float w, Rect panel)
        {
            GUI.Label(new Rect(x, y, w, 22f), "Step 2: Define Procedure Window with Camera", headerStyle);
            y += 24f;

            GUI.Label(new Rect(x, y, w, 36f),
                "Click and drag on the live camera video below to frame the surgical incision corridor on your physical surface.",
                bodyStyle);
            y += 40f;

            // Sliders for fine-tuning
            GUI.Label(new Rect(x, y, 120, 20), $"Width   {widthMm:0} mm", bodyStyle);
            var prevW = widthMm;
            widthMm = GUI.HorizontalSlider(new Rect(x + 120, y + 4, w - 120, 18), widthMm, 40f, 240f);
            y += 26f;

            GUI.Label(new Rect(x, y, 120, 20), $"Depth   {depthMm:0} mm", bodyStyle);
            var prevD = depthMm;
            depthMm = GUI.HorizontalSlider(new Rect(x + 120, y + 4, w - 120, 18), depthMm, 40f, 200f);
            y += 26f;

            GUI.Label(new Rect(x, y, 120, 20), $"Height  {heightMm:0} mm", bodyStyle);
            heightMm = GUI.HorizontalSlider(new Rect(x + 120, y + 4, w - 120, 18), heightMm, 0f, 80f);
            y += 28f;

            if (!Mathf.Approximately(prevW, widthMm) || !Mathf.Approximately(prevD, depthMm))
            {
                var cam = GetComponent<UnityCameraPreview>();
                if (cam != null) cam.SyncFromWorkspace(widthMm, depthMm);
            }

            var statusMsg = validatedViaCamera
                ? "✓ Window selected via camera: " + widthMm.ToString("0") + " × " + depthMm.ToString("0") + " mm"
                : (configurationValid ? "✓ Area ready: " + widthMm.ToString("0") + " × " + depthMm.ToString("0") + " mm" : "Area not validated — frame on camera below");

            var prevCol = GUI.color;
            GUI.color = configurationValid ? new Color(0.25f, 0.95f, 0.6f) : new Color(1f, 0.75f, 0.25f);
            GUI.Label(new Rect(x, y, w, 22f), statusMsg, statusStyle);
            GUI.color = prevCol;

            var btnY = panel.yMax - 44f;
            if (GUI.Button(new Rect(x, btnY, 80f, 32f), "← Back"))
            {
                SetStep(SetupStep.FramingAndDistance);
            }
            if (GUI.Button(new Rect(x + 90f, btnY, w - 90f, 32f), "Confirm Window & Continue →"))
            {
                ValidateArea();
                SetStep(SetupStep.ReadyToStart);
            }
        }

        private void RenderStep3(float x, ref float y, float w, Rect panel)
        {
            GUI.Label(new Rect(x, y, w, 22f), "Step 3: Surface Registration & Tool Ready", headerStyle);
            y += 26f;

            var summaryBox = new Rect(x, y, w, 78f);
            DrawSolid(summaryBox, new Color(0.09f, 0.14f, 0.2f, 0.9f));
            DrawBorder(summaryBox, 1f, new Color(0.25f, 0.6f, 0.7f, 0.7f));
            var sy = summaryBox.y + 8f;
            GUI.Label(new Rect(summaryBox.x + 12f, sy, summaryBox.width - 24f, 18f), $"• Procedure Window:  {widthMm:0} × {depthMm:0} mm (Registered)", bodyStyle);
            sy += 20f;
            GUI.Label(new Rect(summaryBox.x + 12f, sy, summaryBox.width - 24f, 18f), "• Physical Simulation:  Online (SOFA physics stream)", bodyStyle);
            sy += 20f;
            var demoClient = FindFirstObjectByType<UnityManualDemoClient>();
            var toolStatusText = demoClient != null && demoClient.HardwareConnected
                ? $"• Surgical Tool:  ESP32 Scalpel connected ({demoClient.HardwarePort})"
                : "• Surgical Tool:  Scalpel ready (USB auto-detect active)";
            GUI.Label(new Rect(summaryBox.x + 12f, sy, summaryBox.width - 24f, 18f), toolStatusText, bodyStyle);
            y += 92f;

            var btnY = panel.yMax - 48f;
            if (GUI.Button(new Rect(x, btnY, 80f, 36f), "← Edit"))
            {
                SetStep(SetupStep.WindowSelection);
            }

            var prevColor = GUI.color;
            GUI.color = new Color(0.3f, 0.95f, 0.6f);
            if (GUI.Button(new Rect(x + 90f, btnY, w - 90f, 36f), "▶  START REHEARSAL"))
            {
                StartRehearsal();
            }
            GUI.color = prevColor;
        }

        private static void DrawSolid(Rect rect, Color color)
        {
            var prev = GUI.color;
            GUI.color = color;
            GUI.DrawTexture(rect, Texture2D.whiteTexture);
            GUI.color = prev;
        }

        private static void DrawBorder(Rect rect, float thickness, Color color)
        {
            DrawSolid(new Rect(rect.x, rect.y, rect.width, thickness), color);
            DrawSolid(new Rect(rect.x, rect.yMax - thickness, rect.width, thickness), color);
            DrawSolid(new Rect(rect.x, rect.y, thickness, rect.height), color);
            DrawSolid(new Rect(rect.xMax - thickness, rect.y, thickness, rect.height), color);
        }

        private void EnsureStyles()
        {
            if (titleStyle != null) return;
            var font = Font.CreateDynamicFontFromOSFont(new[] { "Helvetica Neue", "Helvetica", "Arial" }, 14);
            titleStyle = new GUIStyle(GUI.skin.label) { font = font, fontSize = 15, fontStyle = FontStyle.Bold, normal = { textColor = Color.white } };
            headerStyle = new GUIStyle(GUI.skin.label) { font = font, fontSize = 13, fontStyle = FontStyle.Bold, normal = { textColor = new Color(0.55f, 0.85f, 0.95f) } };
            bodyStyle = new GUIStyle(GUI.skin.label) { font = font, fontSize = 11, wordWrap = true, normal = { textColor = new Color(0.82f, 0.86f, 0.9f) } };
            alertStyle = new GUIStyle(GUI.skin.label) { font = font, fontSize = 11, fontStyle = FontStyle.Bold, wordWrap = true, normal = { textColor = new Color(0.95f, 0.95f, 0.6f) } };
            statusStyle = new GUIStyle(GUI.skin.label) { font = font, fontSize = 11, fontStyle = FontStyle.Bold, wordWrap = true };
        }
    }
}
