using System.Collections.Generic;
using UnityEngine;

namespace SurgePrep
{
    /// <summary>
    /// Builds the small visual wound channel from authoritative SOFA metrics.
    /// Geometry is bounded to the procedure patch and updated incrementally;
    /// it never calculates contact, force, or canonical procedure progress.
    /// </summary>
    public sealed class IncrementalWoundRenderer : MonoBehaviour
    {
        private const int Segments = 16;

        private Mesh mesh;
        private MeshRenderer meshRenderer;

        public void Initialize(Material woundMaterial)
        {
            if (mesh != null) return;
            var child = new GameObject("SOFA-driven incremental wound");
            child.transform.SetParent(transform, false);
            var filter = child.AddComponent<MeshFilter>();
            meshRenderer = child.AddComponent<MeshRenderer>();
            meshRenderer.sharedMaterial = woundMaterial;
            mesh = new Mesh { name = "Incremental wound walls and bed" };
            mesh.MarkDynamic();
            filter.sharedMesh = mesh;
            child.SetActive(false);
        }

        public void SetTarget(TissueStateDto tissue, DeformableMeshDto skin)
        {
            if (mesh == null || meshRenderer == null || tissue == null) return;
            var visible = tissue.incisionProgress > 0.02f
                && tissue.incisionLengthMm > 0.5f;
            meshRenderer.gameObject.SetActive(visible);
            if (!visible) return;

            var halfLengthMm = Mathf.Clamp(tissue.incisionLengthMm * 0.5f, 1f, 18f);
            var halfWidthMm = Mathf.Lerp(
                0.65f, 3.2f, Mathf.Clamp01(tissue.incisionProgress)
            );
            var depthMm = Mathf.Clamp(tissue.incisionDepthMm, 0.8f, 15.5f);
            var vertices = new Vector3[(Segments + 1) * 4];
            var triangles = new List<int>(Segments * 3 * 12);

            for (var section = 0; section <= Segments; section++)
            {
                var t = section / (float)Segments;
                var xMm = Mathf.Lerp(-halfLengthMm, halfLengthMm, t);
                var pathT = Mathf.InverseLerp(-18f, 18f, xMm);
                var centreZMm = -3f + 6f * Mathf.Sin(pathT * Mathf.PI);
                var surfaceY = ChestSurfaceRegistration.OffsetMetres(xMm, centreZMm)
                    + NearestSkinDisplacementMetres(skin, xMm, centreZMm);
                var topY = surfaceY + 0.0006f;
                var bottomY = surfaceY - depthMm * CoordinateFrame.MillimetresToMetres;
                var leftZ = -(centreZMm - halfWidthMm)
                    * CoordinateFrame.MillimetresToMetres;
                var rightZ = -(centreZMm + halfWidthMm)
                    * CoordinateFrame.MillimetresToMetres;
                var x = xMm * CoordinateFrame.MillimetresToMetres;
                var offset = section * 4;
                vertices[offset] = new Vector3(x, topY, leftZ);
                vertices[offset + 1] = new Vector3(x, bottomY, leftZ);
                vertices[offset + 2] = new Vector3(x, bottomY, rightZ);
                vertices[offset + 3] = new Vector3(x, topY, rightZ);
            }

            for (var section = 0; section < Segments; section++)
            {
                var current = section * 4;
                var next = (section + 1) * 4;
                AddTwoSidedQuad(triangles, current, next, next + 1, current + 1);
                AddTwoSidedQuad(triangles, current + 1, next + 1, next + 2, current + 2);
                AddTwoSidedQuad(triangles, current + 2, next + 2, next + 3, current + 3);
            }

            mesh.Clear();
            mesh.vertices = vertices;
            mesh.triangles = triangles.ToArray();
            mesh.RecalculateNormals();
            mesh.RecalculateBounds();
        }

        private static void AddTwoSidedQuad(
            List<int> triangles, int a, int b, int c, int d
        )
        {
            triangles.Add(a);
            triangles.Add(b);
            triangles.Add(c);
            triangles.Add(a);
            triangles.Add(c);
            triangles.Add(d);
            triangles.Add(c);
            triangles.Add(b);
            triangles.Add(a);
            triangles.Add(d);
            triangles.Add(c);
            triangles.Add(a);
        }

        private static float NearestSkinDisplacementMetres(
            DeformableMeshDto skin, float xMm, float zMm
        )
        {
            if (skin == null || skin.verticesMm == null) return 0f;
            Vector3Dto nearest = null;
            var nearestSquared = float.PositiveInfinity;
            foreach (var vertex in skin.verticesMm)
            {
                var dx = vertex.x - xMm;
                var dz = vertex.z - zMm;
                var squared = dx * dx + dz * dz;
                if (squared < nearestSquared)
                {
                    nearestSquared = squared;
                    nearest = vertex;
                }
            }
            return nearest == null
                ? 0f
                : nearest.y * CoordinateFrame.MillimetresToMetres;
        }
    }
}
