using UnityEngine;

namespace SurgePrep
{
    /// <summary>
    /// Smooth fit of the BodyParts3D lateral chest in the final supine frame.
    /// SOFA owns this surface; Unity uses the same fit only before the first
    /// authoritative mesh arrives to place the projected guidance line.
    /// </summary>
    public static class ChestSurfaceRegistration
    {
        public static float HeightMm(float x, float z)
        {
            return
                -0.15673469389450148f
                - 0.15619047619088122f * z
                - 0.6565476190475732f * x
                - 0.019745748299286214f * z * z
                + 0.007150000000007576f * x * z
                - 0.010474914965967697f * x * x
                + 5.8333333333272285e-05f * z * z * z
                - 5.3571428570533765e-06f * x * z * z
                + 0.00012857142857144923f * x * x * z
                - 0.0001354166666667074f * x * x * x
                + 5.104166666655587e-06f * z * z * z * z
                - 1.9791666666683116e-06f * x * z * z * z
                + 3.3801020408019367e-06f * x * x * z * z
                + 1.0416666666368515e-07f * x * x * x * z
                - 2.4479166666682357e-06f * x * x * x * x;
        }

        public static float OffsetMetres(float xMm, float zMm)
        {
            return HeightMm(xMm, zMm) * CoordinateFrame.MillimetresToMetres;
        }
    }
}
