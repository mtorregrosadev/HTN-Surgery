using UnityEngine;

namespace SurgePrep
{
    /// <summary>
    /// The one authoritative transform between the supplied CAD mesh and the
    /// normalized tool frame. The normalized origin is the physical blade tip,
    /// +Y points toward the handle, and SOFA uses the same millimetre geometry.
    /// </summary>
    public static class ScalpelGeometry
    {
        // Measured from scalepl.obj. The source file is authored in metres.
        public static readonly Vector3 ModelTipMetres = new Vector3(
            -0.159158f, 0.0016f, 0.00570772f
        );

        public static readonly Quaternion ModelToToolRotation = Quaternion.Euler(0f, 0f, 90f);

        public static Vector3 ModelToToolPosition =>
            -(ModelToToolRotation * ModelTipMetres);

        // Cutting edge in the normalized tool frame, millimetres. These points
        // trace the lower edge of the imported blade rather than a spherical
        // proxy. Keep simulation/sofa_scene.py in sync; tests enforce the values.
        public static readonly Vector3[] CuttingEdgeMm =
        {
            new Vector3(0f, 0f, 0f),
            new Vector3(0f, 4.758f, 0.809f),
            new Vector3(0f, 14.5f, 1.12f),
            new Vector3(0f, 24.0f, 1.28f),
            new Vector3(0f, 33.0f, 2.65f),
        };
    }
}
