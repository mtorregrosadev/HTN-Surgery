using System;

namespace SurgePrep
{
    [Serializable]
    public sealed class Vector3Dto
    {
        public float x;
        public float y;
        public float z;
    }

    [Serializable]
    public sealed class QuaternionDto
    {
        public float qx;
        public float qy;
        public float qz;
        public float qw = 1f;
    }

    [Serializable]
    public sealed class ToolStateDto
    {
        public Vector3Dto positionMm;
        public QuaternionDto orientation;
        public float forceN;
        public bool contact;
    }

    [Serializable]
    public sealed class TissueStateDto
    {
        public float deformationMm;
        public float incisionProgress;
        public float incisionLengthMm;
        public float incisionDepthMm;
        public string interactionMode;
    }

    [Serializable]
    public sealed class DeformableMeshDto
    {
        public string objectId;
        public int topologyRevision;
        public Vector3Dto[] verticesMm;
        public int[] triangleIndices;
    }

    [Serializable]
    public sealed class SimulationSnapshotDto
    {
        public string contractVersion;
        public string sessionId;
        public long tick;
        public long simulationTimeMs;
        public ToolStateDto tool;
        public TissueStateDto tissue;
        public DeformableMeshDto[] deformableMeshes;
        public string[] events;
    }

    [Serializable]
    public sealed class CalibrationCreateDto
    {
        public string deviceId;
        public float[] transform;
        public float rmsErrorMm;
    }

    [Serializable]
    public sealed class CalibrationDto
    {
        public string calibrationId;
    }

    [Serializable]
    public sealed class SessionCreateDto
    {
        public string exerciseId;
        public string calibrationId;
        public string toolId;
        public string deviceId;
    }

    [Serializable]
    public sealed class SessionDto
    {
        public string sessionId;
    }

    [Serializable]
    public sealed class ToolSampleDto
    {
        public string contractVersion;
        public string sessionId;
        public string toolId;
        public string deviceId;
        public string calibrationId;
        public long sequence;
        public long timestampMs;
        public Vector3Dto positionMm;
        public QuaternionDto orientation;
        public float forceN;
        public bool contact;
        public float quality;
        public bool sourceHealthy;
    }
}
