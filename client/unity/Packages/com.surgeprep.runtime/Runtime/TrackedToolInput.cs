using UnityEngine;

namespace SurgePrep
{
    public struct TrackedToolSample
    {
        public Vector3 PositionMm;
        public Quaternion OrientationApi;
        public bool HasOrientation;
        public float ForceN;
        public bool Contact;
        public float Quality;
        public bool SourceHealthy;
        public bool ForceMeasurementValid;
        public string DeviceId;
        public string Status;
    }

    /// <summary>
    /// Replaceable physical-tool input boundary. Implementations only measure
    /// the tool; UnityManualDemoClient still routes every sample through the
    /// Scalpel controller and the API before SOFA changes the scene.
    /// </summary>
    public abstract class TrackedToolInput : MonoBehaviour
    {
        public abstract bool HasSignal { get; }
        public abstract bool TryRead(out TrackedToolSample sample);
    }
}
