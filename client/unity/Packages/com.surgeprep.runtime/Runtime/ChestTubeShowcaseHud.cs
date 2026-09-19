using UnityEngine;

namespace SurgePrep
{
    public sealed class ChestTubeShowcaseHud : MonoBehaviour
    {
        [SerializeField] private SimulationSceneRenderer sceneRenderer;
        [SerializeField] private UnityManualDemoClient manualDemo;
        [SerializeField] private string exerciseTitle = "Chest-tube access rehearsal";
        [SerializeField] private float illustrativeForceMinimumN = 0.3f;
        [SerializeField] private float illustrativeForceMaximumN = 1.2f;

        private GUIStyle titleStyle;
        private GUIStyle labelStyle;
        private GUIStyle valueStyle;
        private GUIStyle smallStyle;
        private bool visible = true;

        private void Update()
        {
            if (ShowcaseInput.Pressed(KeyCode.Tab))
            {
                visible = !visible;
            }
        }

        private void OnGUI()
        {
            EnsureStyles();
            if (!visible)
            {
                if (GUI.Button(new Rect(18, 18, 150, 30), "SHOW GUIDANCE [TAB]"))
                {
                    visible = true;
                }
                return;
            }

            var panel = new Rect(18, 18, 310, 294);
            DrawRect(panel, new Color(0.025f, 0.045f, 0.065f, 0.94f));
            DrawRect(new Rect(panel.x, panel.y, 4, panel.height), new Color(0.1f, 0.85f, 0.78f));

            GUI.Label(new Rect(38, 32, 265, 26), exerciseTitle, titleStyle);
            GUI.Label(new Rect(38, 61, 255, 20), "GUIDED LANDMARK + APPROACH", labelStyle);
            if (GUI.Button(new Rect(280, 25, 38, 22), "TAB")) visible = false;

            var snapshot = sceneRenderer != null ? sceneRenderer.LatestSnapshot : null;
            if (snapshot == null)
            {
                var status = manualDemo != null ? manualDemo.Status : "Waiting for Scalpel controller…";
                GUI.Label(new Rect(38, 104, 255, 48), status, valueStyle);
                GUI.Label(
                    new Rect(38, 156, 255, 60),
                    "Docker runs in the background; no Terminal focus or session ID is needed.",
                    smallStyle
                );
                Disclaimer(panel);
                return;
            }

            var force = snapshot.tool.forceN;
            var contact = snapshot.tool.contact;
            var radialError = Mathf.Sqrt(
                snapshot.tool.positionMm.x * snapshot.tool.positionMm.x +
                snapshot.tool.positionMm.z * snapshot.tool.positionMm.z
            );
            var forceStatus = !contact
                ? "Approach the highlighted target"
                : force < illustrativeForceMinimumN
                    ? "Contact detected — increase gently"
                    : force <= illustrativeForceMaximumN
                        ? "Controlled contact"
                        : "Reduce pressure";
            var statusColour = !contact
                ? new Color(0.45f, 0.75f, 1f)
                : force <= illustrativeForceMaximumN
                    ? new Color(0.15f, 0.9f, 0.62f)
                    : new Color(1f, 0.35f, 0.28f);

            GUI.Label(new Rect(38, 96, 255, 20), "LIVE GUIDANCE", labelStyle);
            GUI.color = statusColour;
            GUI.Label(new Rect(38, 118, 255, 25), forceStatus, valueStyle);
            GUI.color = Color.white;

            Metric("Force", $"{force:0.00} N", 158);
            Metric("Target offset", $"{radialError:0.0} mm", 194);
            Metric("Simulation tick", snapshot.tick.ToString(), 230);

            GUI.Label(
                new Rect(38, 252, 255, 18),
                "WASD move  •  SPACE contact  •  [ ] pressure  •  R reset",
                smallStyle
            );

            var bar = new Rect(145, 166, 156, 8);
            DrawRect(bar, new Color(0.12f, 0.17f, 0.2f));
            DrawRect(
                new Rect(bar.x, bar.y, bar.width * Mathf.Clamp01(force / 1.5f), bar.height),
                statusColour
            );
            Disclaimer(panel);
        }

        private void Metric(string label, string value, float y)
        {
            GUI.Label(new Rect(38, y, 105, 22), label, labelStyle);
            GUI.Label(new Rect(145, y - 2, 150, 24), value, valueStyle);
        }

        private void Disclaimer(Rect panel)
        {
            GUI.Label(
                new Rect(38, panel.yMax - 40, 255, 32),
                "Training prototype • Illustrative rubric • Instructor review required",
                smallStyle
            );
        }

        private void EnsureStyles()
        {
            if (titleStyle != null)
            {
                return;
            }
            titleStyle = Style(19, FontStyle.Bold, Color.white);
            labelStyle = Style(11, FontStyle.Normal, new Color(0.65f, 0.72f, 0.78f));
            valueStyle = Style(15, FontStyle.Bold, Color.white);
            smallStyle = Style(10, FontStyle.Normal, new Color(0.7f, 0.76f, 0.8f));
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
