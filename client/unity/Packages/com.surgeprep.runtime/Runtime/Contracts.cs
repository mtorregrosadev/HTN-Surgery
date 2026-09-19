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
}

