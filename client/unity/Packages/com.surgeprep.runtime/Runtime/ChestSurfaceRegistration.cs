using UnityEngine;

namespace SurgePrep
{
    public static class ChestSurfaceRegistration
    {
        private static readonly float[,] OffsetsMm =
        {
            { 3f, -3f, -15f, -42f, -78f },
            { 11f, 7f, -2f, -25f, -74f },
            { 11f, 6f, 0f, -17f, -56f },
            { 6f, -1f, -12f, -25f, -57f },
            { -1f, -7f, -23f, -32f, -56f },
        };

        public static float OffsetMetres(float xMm, float zMm)
        {
            var gridX = Mathf.Clamp((xMm + 40f) / 20f, 0f, 4f);
            var gridZ = Mathf.Clamp((zMm + 40f) / 20f, 0f, 4f);
            var x0 = Mathf.Min(Mathf.FloorToInt(gridX), 3);
            var z0 = Mathf.Min(Mathf.FloorToInt(gridZ), 3);
            var xBlend = gridX - x0;
            var zBlend = gridZ - z0;
            var near = Mathf.Lerp(OffsetsMm[z0, x0], OffsetsMm[z0, x0 + 1], xBlend);
            var far = Mathf.Lerp(OffsetsMm[z0 + 1, x0], OffsetsMm[z0 + 1, x0 + 1], xBlend);
            return (Mathf.Lerp(near, far, zBlend) + 0.5f)
                * CoordinateFrame.MillimetresToMetres;
        }
    }
}
