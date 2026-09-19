using UnityEngine;

namespace SurgePrep
{
    public sealed class ChestTubeShowcaseHud : MonoBehaviour
    {
        [SerializeField] private SimulationSceneRenderer sceneRenderer;
        [SerializeField] private string exerciseTitle = "Chest-tube access rehearsal";
        [SerializeField] private float illustrativeForceMinimumN = 0.3f;
        [SerializeField] private float illustrativeForceMaximumN = 1.2f;

        private GUIStyle titleStyle;
        private GUIStyle labelStyle;
        private GUIStyle valueStyle;
        private GUIStyle smallStyle;

        private void OnGUI()
        {
            EnsureStyles();
            var panel = new Rect(24, 24, 360, 336);
            DrawRect(panel, new Color(0.025f, 0.045f, 0.065f, 0.94f));
            DrawRect(new Rect(panel.x, panel.y, 5, panel.height), new Color(0.1f, 0.85f, 0.78f));

            GUI.Label(new Rect(48, 43, 310, 30), exerciseTitle, titleStyle);
            GUI.Label(new Rect(48, 77, 300, 24), "GUIDED LANDMARK + APPROACH", labelStyle);

            var snapshot = sceneRenderer != null ? sceneRenderer.LatestSnapshot : null;
            if (snapshot == null)
            {
                GUI.Label(new Rect(48, 120, 300, 28), "Waiting for Scalpel controller…", valueStyle);
                GUI.Label(
                    new Rect(48, 158, 300, 70),
                    "Start a session and keep the hardware or synthetic stream running.",
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

            GUI.Label(new Rect(48, 112, 300, 22), "LIVE GUIDANCE", labelStyle);
            GUI.color = statusColour;
            GUI.Label(new Rect(48, 136, 300, 28), forceStatus, valueStyle);
            GUI.color = Color.white;

            Metric("Force", $"{force:0.00} N", 180);
            Metric("Target offset", $"{radialError:0.0} mm", 224);
            Metric("Simulation tick", snapshot.tick.ToString(), 268);

            var bar = new Rect(174, 188, 170, 10);
            DrawRect(bar, new Color(0.12f, 0.17f, 0.2f));
            DrawRect(
                new Rect(bar.x, bar.y, bar.width * Mathf.Clamp01(force / 1.5f), bar.height),
                statusColour
            );
            Disclaimer(panel);
        }

        private void Metric(string label, string value, float y)
        {
            GUI.Label(new Rect(48, y, 130, 24), label, labelStyle);
            GUI.Label(new Rect(174, y - 2, 170, 26), value, valueStyle);
        }

        private void Disclaimer(Rect panel)
        {
            GUI.Label(
                new Rect(48, panel.yMax - 52, 300, 38),
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
            titleStyle = Style(22, FontStyle.Bold, Color.white);
            labelStyle = Style(13, FontStyle.Normal, new Color(0.65f, 0.72f, 0.78f));
            valueStyle = Style(17, FontStyle.Bold, Color.white);
            smallStyle = Style(12, FontStyle.Normal, new Color(0.7f, 0.76f, 0.8f));
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
