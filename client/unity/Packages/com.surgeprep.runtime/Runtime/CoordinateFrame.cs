using UnityEngine;

namespace SurgePrep
{
    public static class CoordinateFrame
    {
        private const float MillimetresToMetres = 0.001f;

        // The API is right-handed. Unity is left-handed, so Z is reflected.
        public static Vector3 Position(Vector3Dto source)
        {
            return new Vector3(source.x, source.y, -source.z) * MillimetresToMetres;
        }

        public static Quaternion Rotation(QuaternionDto source)
        {
            return new Quaternion(-source.qx, -source.qy, source.qz, source.qw);
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
    }
}

