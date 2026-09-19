using UnityEngine;

namespace SurgePrep
{
    public sealed class ChestTubeShowcaseHud : MonoBehaviour
    {
        [SerializeField] private SimulationSceneRenderer sceneRenderer;
        [SerializeField] private UnityManualDemoClient manualDemo;
        [SerializeField] private string exerciseTitle = "Chest-tube access rehearsal";

        private GUIStyle titleStyle;
        private GUIStyle labelStyle;
        private GUIStyle valueStyle;
        private GUIStyle smallStyle;
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
            if (!visible)
            {
                if (GUI.Button(new Rect(18, 18, 160, 28), "SHOW GUIDANCE [TAB]"))
                {
                    visible = true;
                }
                return;
            }

            var snapshot = sceneRenderer != null ? sceneRenderer.LatestSnapshot : null;
            var sofaNative = manualDemo != null && manualDemo.SofaNative;
            if (snapshot != null && snapshot.simulationBackend == "sofa-native") sofaNative = true;
            if (snapshot != null && snapshot.simulationBackend == "memory-development-only") sofaNative = false;

            var panel = new Rect(18, 18, 340, completed ? 430 : 248);
            DrawRect(panel, new Color(0.07f, 0.1f, 0.14f, 0.92f));
            DrawRect(new Rect(panel.x, panel.y, 4, panel.height), new Color(0.2f, 0.55f, 0.72f));

            GUI.Label(new Rect(38, 28, 270, 24), exerciseTitle, titleStyle);
            var stage = snapshot != null ? PrettyStage(snapshot.procedureStage) : "Connecting";
            GUI.Label(new Rect(38, 54, 270, 20), stage, labelStyle);
            GUI.Label(new Rect(38, 76, 280, 36), Instruction(snapshot), valueStyle);

            var sofaLabel = sofaNative ? "SOFA NATIVE" : "SOFA OFFLINE";
            GUI.color = sofaNative ? new Color(0.35f, 0.85f, 0.55f) : new Color(1f, 0.45f, 0.3f);
            GUI.Label(new Rect(38, 118, 180, 20), sofaLabel, labelStyle);
            GUI.color = Color.white;

            if (snapshot != null && snapshot.tool != null)
            {
                var contact = snapshot.tool.contact;
                GUI.Label(
                    new Rect(38, 140, 280, 20),
                    contact
                        ? $"Contact  {snapshot.tool.reactionForceN:0.00} N  •  {snapshot.tool.penetrationDepthMm:0.1} mm"
                        : "No tissue contact",
                    smallStyle
                );
                var offset = Mathf.Sqrt(
                    snapshot.tool.positionMm.x * snapshot.tool.positionMm.x +
                    snapshot.tool.positionMm.z * snapshot.tool.positionMm.z
                );
                GUI.Label(new Rect(38, 160, 280, 18), $"Alignment  {offset:0.0} mm from corridor centre", smallStyle);
                var progress = snapshot.tissue != null ? snapshot.tissue.incisionProgress : 0f;
                DrawRect(new Rect(38, 186, 280, 8), new Color(0.12f, 0.16f, 0.2f));
                DrawRect(new Rect(38, 186, 280f * Mathf.Clamp01(progress), 8), new Color(0.25f, 0.62f, 0.7f));
            }
            else
            {
                GUI.Label(
                    new Rect(38, 140, 280, 48),
                    manualDemo != null ? manualDemo.Status : "Waiting for Scalpel controller…",
                    smallStyle
                );
            }

            if (Time.unscaledTime < toastUntil && !string.IsNullOrEmpty(toast))
            {
                DrawRect(new Rect(38, 204, 280, 28), new Color(0.45f, 0.12f, 0.08f, 0.92f));
                GUI.Label(new Rect(46, 208, 264, 22), toast, smallStyle);
            }

            if (completed && snapshot != null && snapshot.tissue != null)
            {
                GUI.Label(new Rect(38, 244, 280, 20), "SCORECARD — stored telemetry", labelStyle);
                GUI.Label(new Rect(38, 268, 280, 18), $"Incision {snapshot.tissue.incisionLengthMm:0.0} mm  •  depth {snapshot.tissue.incisionDepthMm:0.0} mm", smallStyle);
                GUI.Label(new Rect(38, 288, 280, 18), $"Reaction {snapshot.tool.reactionForceN:0.00} N  •  stage {snapshot.procedureStage}", smallStyle);
                GUI.Label(new Rect(38, 308, 280, 36), "Canonical scores come from the API/MongoDB replay, not this overlay.", smallStyle);
            }

            GUI.Label(
                new Rect(38, panel.yMax - 52, 280, 36),
                "Training prototype • No real patients • Instructor review required",
                smallStyle
            );
        }

        private static string PrettyStage(string stage)
        {
            switch (stage)
            {
                case "approach": return "1  Approach and landmarks";
                case "landmark-alignment": return "1  Landmark alignment";
                case "skin-incision": return "2  Controlled skin incision";
                case "blunt-dissection": return "3  Blunt soft-tissue dissection";
                case "pleural-entry": return "4  Pleural-layer entry";
                case "tube-placement": return "5  Tube placement";
                case "complete": return "6  Completion";
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
                    return "Lower the scalpel until skin deforms, then travel the corridor.";
                case "blunt-dissection":
                    return "Press 2 for the blunt dissector and open the soft-tissue tract.";
                case "pleural-entry":
                    return "Enter the pleural layer only through the opened tract.";
                case "tube-placement":
                    return "Press 3 and place the tube through the simulated tract.";
                case "complete":
                    return "Attempt complete. Detailed metrics are on the scorecard.";
                default:
                    return "Align over the lateral intercostal window. Q/E raises and lowers.";
            }
        }

        private void EnsureStyles()
        {
            if (titleStyle != null) return;
            titleStyle = Style(17, FontStyle.Bold, Color.white);
            labelStyle = Style(11, FontStyle.Normal, new Color(0.72f, 0.78f, 0.82f));
            valueStyle = Style(13, FontStyle.Bold, Color.white);
            valueStyle.wordWrap = true;
            smallStyle = Style(10, FontStyle.Normal, new Color(0.75f, 0.8f, 0.84f));
            smallStyle.wordWrap = true;
        }

        private static GUIStyle Style(int size, FontStyle fontStyle, Color colour)
        {
            return new GUIStyle(GUI.skin.label)
            {
                fontSize = size,
                fontStyle = fontStyle,
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
    }
}
