using UnityEngine;

namespace SurgePrep
{
    public sealed class ChestTubeShowcaseHud : MonoBehaviour
    {
        [SerializeField] private SimulationSceneRenderer sceneRenderer;
        [SerializeField] private UnityManualDemoClient manualDemo;
        [SerializeField] private WorkspaceConfigurationPanel workspaceSetup;
        [SerializeField] private string exerciseTitle = "Chest-tube access rehearsal";

        private GUIStyle titleStyle;
        private GUIStyle labelStyle;
        private GUIStyle valueStyle;
        private GUIStyle smallStyle;
        private GUIStyle keyStyle;
        private bool visible = true;
        private string toast;
        private float toastUntil;
        private bool completed;

        private void Update()
        {
            if (ShowcaseInput.Pressed(KeyCode.Tab))
            {
                visible = !visible;
            }
            var snapshot = sceneRenderer != null ? sceneRenderer.LatestSnapshot : null;
            if (snapshot == null || snapshot.events == null)
            {
                return;
            }
            foreach (var item in snapshot.events)
            {
                if (item == "excessive-force") ShowToast("Excess force — ease the instrument");
                if (item == "outside-corridor") ShowToast("Outside the target corridor");
                if (item == "layer-violation") ShowToast("Wrong instrument or layer order");
                if (item == "session-completed") completed = true;
            }
            if (snapshot.procedureStage == "complete") completed = true;
        }

        private void ShowToast(string message)
        {
            toast = message;
            toastUntil = Time.unscaledTime + 2.4f;
        }

        private void OnGUI()
        {
            EnsureStyles();
            DrawCameraControlBar();

            if (!visible)
            {
                if (GUI.Button(new Rect(18, 18, 220, 32), "Show guidance  [Tab]"))
                {
                    visible = true;
                }
                return;
            }

            if (workspaceSetup == null)
            {
                workspaceSetup = GetComponentInParent<WorkspaceConfigurationPanel>();
                if (workspaceSetup == null) workspaceSetup = FindFirstObjectByType<WorkspaceConfigurationPanel>();
            }
            if (workspaceSetup != null && !workspaceSetup.IsRehearsalStarted)
            {
                var promptRect = new Rect(20f, 20f, 400f, 32f);
                DrawRect(promptRect, new Color(0.07f, 0.1f, 0.14f, 0.92f));
                DrawRect(new Rect(promptRect.x, promptRect.y, 4, promptRect.height), new Color(0.2f, 0.55f, 0.72f));
                GUI.Label(new Rect(32f, 26f, 380f, 20f), "Surge Prep — Complete setup on the right to start rehearsal", labelStyle);
                return;
            }

            var snapshot = sceneRenderer != null ? sceneRenderer.LatestSnapshot : null;
            var isSimActive = (manualDemo != null && manualDemo.SofaNative) ||
                (snapshot != null && (snapshot.simulationBackend == "sofa-native" || snapshot.simulationBackend == "memory-development-only" || snapshot.simulationBackend == "sofa"));
            var isNative = (manualDemo != null && manualDemo.SimulationBackend == "sofa-native") ||
                (snapshot != null && snapshot.simulationBackend == "sofa-native");

            var panel = new Rect(16, 16, 420, completed ? 580 : 478);
            DrawRect(panel, new Color(0.07f, 0.1f, 0.14f, 0.94f));
            DrawRect(new Rect(panel.x, panel.y, 4, panel.height), new Color(0.2f, 0.55f, 0.72f));

            var y = 26f;
            GUI.Label(new Rect(38, y, 380, 24), exerciseTitle, titleStyle);
            y += 26f;
            GUI.Label(
                new Rect(38, y, 380, 20),
                snapshot != null ? PrettyStage(snapshot.procedureStage) : "Connecting",
                labelStyle
            );
            y += 22f;
            GUI.Label(new Rect(38, y, 380, 40), Instruction(snapshot), valueStyle);
            y += 44f;

            GUI.color = isNative ? new Color(0.35f, 0.85f, 0.55f) : new Color(1f, 0.45f, 0.3f);
            var statusLabel = isNative ? "SOFA  NATIVE" : (isSimActive ? "SOFA OFFLINE — DEV SIMULATOR" : "SOFA  OFFLINE");
            GUI.Label(new Rect(38, y, 380, 20), statusLabel, labelStyle);
            GUI.color = Color.white;
            y += 20f;

            if (manualDemo != null && manualDemo.HardwareConnected)
            {
                GUI.color = new Color(0.35f, 0.95f, 0.65f);
                var portText = string.IsNullOrEmpty(manualDemo.HardwarePort) ? "USB" : manualDemo.HardwarePort;
                var forceInfo = manualDemo.HardwareContact ? $"  •  {manualDemo.HardwareForceN:0.00} N" : "  •  Idle";
                GUI.Label(new Rect(38, y, 380, 20), $"PHYSICAL SCALPEL  ONLINE ({portText}){forceInfo}", labelStyle);
            }
            else
            {
                GUI.color = new Color(0.72f, 0.78f, 0.82f);
                GUI.Label(new Rect(38, y, 380, 20), "PHYSICAL SCALPEL  STANDBY (Auto-detecting USB...)", labelStyle);
            }
            GUI.color = Color.white;
            y += 22f;

            if (manualDemo != null && manualDemo.TrackingActive)
            {
                GUI.color = new Color(0.85f, 0.45f, 1f);
                var src = string.IsNullOrEmpty(manualDemo.TrackingSource) ? "OPTICAL" : manualDemo.TrackingSource.ToUpperInvariant();
                GUI.Label(new Rect(38, y, 380, 20), $"OPTICAL TRACKING  ONLINE ({src} CAMERA ESTIMATE)", labelStyle);
            }
            else
            {
                GUI.color = new Color(0.72f, 0.78f, 0.82f);
                GUI.Label(new Rect(38, y, 380, 20), "OPTICAL TRACKING  STANDBY (tracking-web :5173)", labelStyle);
            }
            GUI.color = Color.white;
            y += 22f;

            if (snapshot != null && snapshot.tool != null)
            {
                var contact = snapshot.tool.contact;
                GUI.Label(
                    new Rect(38, y, 380, 20),
                    contact
                        ? "Contact  " + snapshot.tool.reactionForceN.ToString("0.00")
                            + " N    depth  " + snapshot.tool.penetrationDepthMm.ToString("0.1") + " mm"
                        : "No tissue contact",
                    smallStyle
                );
                y += 20f;
                var offset = Mathf.Sqrt(
                    snapshot.tool.positionMm.x * snapshot.tool.positionMm.x +
                    snapshot.tool.positionMm.z * snapshot.tool.positionMm.z
                );
                GUI.Label(
                    new Rect(38, y, 380, 18),
                    "Alignment  " + offset.ToString("0.0") + " mm from corridor centre",
                    smallStyle
                );
                y += 20f;
                var progress = snapshot.tissue != null ? snapshot.tissue.incisionProgress : 0f;
                DrawRect(new Rect(38, y, 360, 8), new Color(0.12f, 0.16f, 0.2f));
                DrawRect(new Rect(38, y, 360f * Mathf.Clamp01(progress), 8), new Color(0.25f, 0.62f, 0.7f));
                y += 18f;
            }
            else
            {
                GUI.Label(
                    new Rect(38, y, 380, 36),
                    manualDemo != null ? manualDemo.Status : "Waiting for Scalpel controller…",
                    smallStyle
                );
                y += 36f;
            }

            if (Time.unscaledTime < toastUntil && !string.IsNullOrEmpty(toast))
            {
                DrawRect(new Rect(38, y, 360, 26), new Color(0.45f, 0.12f, 0.08f, 0.92f));
                GUI.Label(new Rect(46, y + 3, 344, 20), toast, smallStyle);
                y += 30f;
            }

            y += 6f;
            GUI.Label(new Rect(38, y, 380, 18), "Controls", labelStyle);
            y += 20f;
            DrawRect(new Rect(38, y, 360, 186), new Color(0.05f, 0.07f, 0.1f, 0.8f));
            y += 8f;
            ControlLine(ref y, "W A S D", "move on the chest");
            ControlLine(ref y, "Q / E", "raise / lower the tool");
            ControlLine(ref y, "1 / 2 / 3", "scalpel / dissector / tube");
            ControlLine(ref y, "F / C / T / O", "close-up / surgeon / top / room");
            ControlLine(ref y, "Home / 🎯", "re-center on incision field");
            ControlLine(ref y, "K", "anatomy cutaway");
            ControlLine(ref y, "R then R", "reset the attempt");
            ControlLine(ref y, "Tab", "hide this panel");
            y += 8f;

            if (completed && snapshot != null && snapshot.tissue != null)
            {
                GUI.Label(new Rect(38, y, 380, 18), "Scorecard  —  stored telemetry", labelStyle);
                y += 20f;
                GUI.Label(
                    new Rect(38, y, 380, 18),
                    "Incision  " + snapshot.tissue.incisionLengthMm.ToString("0.0")
                        + " mm    depth  " + snapshot.tissue.incisionDepthMm.ToString("0.0") + " mm",
                    smallStyle
                );
                y += 18f;
            }

            GUI.Label(
                new Rect(38, panel.yMax - 36, 380, 28),
                "Training prototype. No real patients. Instructor review required.",
                smallStyle
            );
        }

        private void ControlLine(ref float y, string keys, string meaning)
        {
            GUI.Label(new Rect(48, y, 110, 18), keys, keyStyle);
            GUI.Label(new Rect(164, y, 230, 18), meaning, smallStyle);
            y += 22f;
        }

        private static string PrettyStage(string stage)
        {
            switch (stage)
            {
                case "approach": return "1    Approach and landmarks";
                case "landmark-alignment": return "1    Landmark alignment";
                case "skin-incision": return "2    Controlled skin incision";
                case "blunt-dissection": return "3    Blunt soft-tissue dissection";
                case "pleural-entry": return "4    Pleural-layer entry";
                case "tube-placement": return "5    Tube placement";
                case "complete": return "6    Completion";
                case "degraded": return "Session degraded";
                default: return stage ?? "Approach";
            }
        }

        private string Instruction(SimulationSnapshotDto snapshot)
        {
            if (manualDemo != null && !manualDemo.SofaNative &&
                (snapshot == null || snapshot.simulationBackend != "sofa-native"))
            {
                return "SOFA is offline. Start the host showcase stack.";
            }
            if (snapshot == null) return "Approach the lateral-chest window with the scalpel.";
            if (snapshot.sessionDegraded) return "Simulation frozen. Restart the attempt.";
            switch (snapshot.procedureStage)
            {
                case "skin-incision":
                    return "Hold E to lower until the skin dents, then sweep A/D along the guide.";
                case "blunt-dissection":
                    return "Press 2 for the blunt dissector and open the soft-tissue tract.";
                case "pleural-entry":
                    return "Enter the pleural layer only through the opened tract.";
                case "tube-placement":
                    return "Press 3 and place the tube through the simulated tract.";
                case "complete":
                    return "Attempt complete. Detailed metrics are on the scorecard.";
                default:
                    return "Align on the guide. E lowers. Q raises. WASD moves.";
            }
        }

        private void EnsureStyles()
        {
            if (titleStyle != null) return;
            var font = Font.CreateDynamicFontFromOSFont(
                new[] { "Helvetica Neue", "Helvetica", "Arial", "Lucida Grande" },
                14
            );
            titleStyle = Style(font, 17, FontStyle.Bold, Color.white);
            labelStyle = Style(font, 12, FontStyle.Normal, new Color(0.72f, 0.78f, 0.82f));
            valueStyle = Style(font, 13, FontStyle.Bold, Color.white);
            valueStyle.wordWrap = true;
            smallStyle = Style(font, 12, FontStyle.Normal, new Color(0.78f, 0.82f, 0.86f));
            smallStyle.wordWrap = true;
            keyStyle = Style(font, 12, FontStyle.Bold, new Color(0.55f, 0.85f, 0.95f));
        }

        private static GUIStyle Style(Font font, int size, FontStyle fontStyle, Color colour)
        {
            return new GUIStyle(GUI.skin.label)
            {
                font = font,
                fontSize = size,
                fontStyle = fontStyle,
                wordWrap = false,
                clipping = TextClipping.Overflow,
                normal = { textColor = colour }
            };
        }

        private static void DrawRect(Rect rectangle, Color colour)
        {
            var previous = GUI.color;
            GUI.color = colour;
            GUI.DrawTexture(rectangle, Texture2D.whiteTexture);
            GUI.color = previous;
        }

        private void DrawCameraControlBar()
        {
            var camCtrl = FindFirstObjectByType<ShowcaseExperienceController>();
            if (camCtrl == null) return;

            var barWidth = 470f;
            var barHeight = 28f;
            var bar = new Rect((Screen.width - barWidth) / 2f, 14f, barWidth, barHeight);

            DrawRect(bar, new Color(0.07f, 0.1f, 0.14f, 0.90f));
            DrawBorder(bar, 1f, new Color(0.25f, 0.55f, 0.72f, 0.8f));

            var bx = bar.x + 6f;
            var by = bar.y + 3f;
            var btnW = 86f;
            var btnH = 22f;

            var isCloseUp = camCtrl.CurrentDistance < 0.35f;

            var prevCol = GUI.color;
            GUI.color = isCloseUp ? new Color(0.3f, 0.95f, 0.65f) : Color.white;
            if (GUI.Button(new Rect(bx, by, btnW, btnH), "🔍 Close-Up")) camCtrl.SetTargetView(false);
            bx += btnW + 5f;

            GUI.color = !isCloseUp && camCtrl.CurrentDistance < 1.2f ? new Color(0.3f, 0.95f, 0.65f) : Color.white;
            if (GUI.Button(new Rect(bx, by, btnW, btnH), "👤 Surgeon")) camCtrl.SetSurgeonView(false);
            bx += btnW + 5f;

            GUI.color = Color.white;
            if (GUI.Button(new Rect(bx, by, btnW, btnH), "⬇ Top-Down")) camCtrl.SetTopDownView(false);
            bx += btnW + 5f;

            if (GUI.Button(new Rect(bx, by, btnW, btnH), "🏥 Room")) camCtrl.SetRoomView(false);
            bx += btnW + 5f;

            GUI.color = new Color(0.95f, 0.85f, 0.35f);
            if (GUI.Button(new Rect(bx, by, btnW + 10f, btnH), "🎯 Re-Center")) camCtrl.SetTargetView(false);
            GUI.color = prevCol;
        }

        private static void DrawBorder(Rect rect, float thickness, Color color)
        {
            DrawRect(new Rect(rect.x, rect.y, rect.width, thickness), color);
            DrawRect(new Rect(rect.x, rect.yMax - thickness, rect.width, thickness), color);
            DrawRect(new Rect(rect.x, rect.y, thickness, rect.height), color);
            DrawRect(new Rect(rect.xMax - thickness, rect.y, thickness, rect.height), color);
        }
    }
}
