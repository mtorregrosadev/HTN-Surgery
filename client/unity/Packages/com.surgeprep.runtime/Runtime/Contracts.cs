using System;
using UnityEngine;

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
        public string toolId;
        public Vector3Dto positionMm;
        public QuaternionDto orientation;
        public float forceN;
        public bool contact;
        public Vector3Dto contactPointMm;
        public Vector3Dto contactNormal;
        public float reactionForceN;
        public float penetrationDepthMm;
    }

    [Serializable]
    public sealed class TissueLayerDto
    {
        public string layerId;
        public bool opened;
        public float openingProgress;
        public float deformationMm;
    }

    [Serializable]
    public sealed class TissueStateDto
    {
        public float deformationMm;
        public float incisionProgress;
        public float incisionLengthMm;
        public float incisionDepthMm;
        public string interactionMode;
        public string activeLayer;
        public TissueLayerDto[] layers;
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
        public string simulationBackend;
        public string procedureStage;
        public bool sessionDegraded;
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
    public sealed class HealthDto
    {
        public string status;
        public HealthApiDto api;
    }

    [Serializable]
    public sealed class HealthApiDto
    {
        public string status;
        public string persistence;
        public string simulation;
    }

    [Serializable]
    public sealed class StreamEnvelopeDto
    {
        public string type;
    }

    [Serializable]
    public sealed class StreamErrorDetailDto
    {
        public string detail;
    }

    [Serializable]
    public sealed class StreamErrorDto
    {
        public string type;
        public string sessionId;
        public int status;
        public StreamErrorDetailDto detail;
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
        public string inputMode;
        public bool forceMeasurementValid;
    }

    public static class ContractCompatibility
    {
        public static bool Accepts(string contractVersion)
        {
            return contractVersion == "1.0" || contractVersion == "1.1" ||
                   string.IsNullOrEmpty(contractVersion);
        }

        public static bool TryReadError(string payload, out StreamErrorDto error)
        {
            error = null;
            if (string.IsNullOrEmpty(payload)) return false;
            try
            {
                var envelope = JsonUtility.FromJson<StreamEnvelopeDto>(payload);
                if (envelope == null || envelope.type != "error") return false;
                error = JsonUtility.FromJson<StreamErrorDto>(payload);
                return true;
            }
            catch (ArgumentException)
            {
                // The error envelope is still an error even when its detail is not
                // representable by Unity's small DTO model.
                error = new StreamErrorDto { type = "error" };
                return true;
            }
        }

        public static string DescribeError(StreamErrorDto error)
        {
            var reason = error != null && error.detail != null ? error.detail.detail : null;
            if (string.IsNullOrEmpty(reason)) reason = "Controller rejected tracking data";
            if (error != null && error.status > 0)
            {
                return $"{reason} (HTTP {error.status})";
            }
            return reason;
        }
    }
}
