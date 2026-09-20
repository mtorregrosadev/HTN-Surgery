using UnityEngine;

namespace SurgePrep
{
    /// <summary>
    /// Represents the calibrated physical tabletop workspace on the virtual operating table.
    /// Provides spatial visual boundaries (e.g. 280 x 200 mm) matching the physical desk area.
    /// </summary>
    [ExecuteAlways]
    public sealed class DeskWorkspaceAnchor : MonoBehaviour
    {
        [SerializeField] private Vector2 deskDimensionsMm = new Vector2(280f, 200f);
        [SerializeField] private Color boundaryColor = new Color(0.18f, 0.65f, 0.85f, 0.45f);
        [SerializeField] private bool showInGame = false;

        private LineRenderer lineRenderer;

        public Vector2 DeskDimensionsMm => deskDimensionsMm;

        private void Awake()
        {
            SetupVisualBoundary();
        }

        private void OnValidate()
        {
            if (lineRenderer != null)
            {
                lineRenderer.enabled = showInGame;
            }
        }

        private void SetupVisualBoundary()
        {
            lineRenderer = GetComponent<LineRenderer>();
            if (lineRenderer == null)
            {
                lineRenderer = gameObject.AddComponent<LineRenderer>();
            }

            if (lineRenderer.sharedMaterial == null)
            {
                var shader = Shader.Find("Sprites/Default") ?? Shader.Find("Unlit/Color") ?? Shader.Find("Hidden/Internal-Colored");
                if (shader != null)
                {
                    lineRenderer.material = new Material(shader);
                }
            }

            lineRenderer.useWorldSpace = false;
            lineRenderer.loop = true;
            lineRenderer.positionCount = 4;
            lineRenderer.startWidth = 0.003f;
            lineRenderer.endWidth = 0.003f;

            var halfX = (deskDimensionsMm.x * 0.5f) * CoordinateFrame.MillimetresToMetres;
            var halfZ = (deskDimensionsMm.y * 0.5f) * CoordinateFrame.MillimetresToMetres;

            lineRenderer.SetPosition(0, new Vector3(-halfX, 0.001f, -halfZ));
            lineRenderer.SetPosition(1, new Vector3( halfX, 0.001f, -halfZ));
            lineRenderer.SetPosition(2, new Vector3( halfX, 0.001f,  halfZ));
            lineRenderer.SetPosition(3, new Vector3(-halfX, 0.001f,  halfZ));

            lineRenderer.startColor = boundaryColor;
            lineRenderer.endColor = boundaryColor;
            lineRenderer.enabled = showInGame;
        }

        public bool IsInsideWorkspace(Vector3 posMm)
        {
            var halfX = deskDimensionsMm.x * 0.5f;
            var halfZ = deskDimensionsMm.y * 0.5f;
            return Mathf.Abs(posMm.x) <= halfX && Mathf.Abs(posMm.z) <= halfZ;
        }

        private void OnDrawGizmos()
        {
            Gizmos.color = boundaryColor;
            var halfX = (deskDimensionsMm.x * 0.5f) * CoordinateFrame.MillimetresToMetres;
            var halfZ = (deskDimensionsMm.y * 0.5f) * CoordinateFrame.MillimetresToMetres;
            var size = new Vector3(halfX * 2f, 0.002f, halfZ * 2f);
            Gizmos.DrawWireCube(transform.position, size);
        }
    }
}
