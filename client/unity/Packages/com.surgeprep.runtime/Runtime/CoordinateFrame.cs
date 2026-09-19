using UnityEngine;

namespace SurgePrep
{
    public static class CoordinateFrame
    {
        public const float MillimetresToMetres = 0.001f;
        public const float MetresToMillimetres = 1000f;
        public const float SnapDivergenceMetres = 0.05f;

        // The API/SOFA frame is right-handed millimetres. Unity is left-handed metres.
        public static Vector3 Position(Vector3Dto source)
        {
            if (source == null) return Vector3.zero;
            return new Vector3(source.x, source.y, -source.z) * MillimetresToMetres;
        }

        public static Vector3 Direction(Vector3Dto source)
        {
            if (source == null) return Vector3.up;
            return new Vector3(source.x, source.y, -source.z).normalized;
        }

        public static Quaternion Rotation(QuaternionDto source)
        {
            if (source == null) return Quaternion.identity;
            return new Quaternion(-source.qx, -source.qy, source.qz, source.qw);
        }

        public static Vector3 InverseDeltaMetres(Vector3 unityMetres)
        {
            return new Vector3(
                unityMetres.x * MetresToMillimetres,
                unityMetres.y * MetresToMillimetres,
                -unityMetres.z * MetresToMillimetres
            );
        }

        public static int[] ReflectedTriangles(int[] source)
        {
            var result = (int[])source.Clone();
            for (var index = 0; index + 2 < result.Length; index += 3)
            {
                (result[index + 1], result[index + 2]) =
                    (result[index + 2], result[index + 1]);
            }
            return result;
        }

        public static bool ShouldSnap(Vector3 current, Vector3 target)
        {
            return Vector3.Distance(current, target) > SnapDivergenceMetres;
        }
    }
}
