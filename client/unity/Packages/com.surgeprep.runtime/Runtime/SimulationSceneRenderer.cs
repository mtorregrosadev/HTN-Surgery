using System;
using System.Collections.Generic;
using UnityEngine;

namespace SurgePrep
{
    public sealed class SimulationSceneRenderer : MonoBehaviour
    {
        [SerializeField] private Transform toolTransform;
        [SerializeField, Min(1f)] private float interpolationSpeed = 20f;
        [SerializeField] private Material tissueMaterial;
        [SerializeField] private Material toolMaterial;

        private readonly Dictionary<string, MeshView> meshes =
            new Dictionary<string, MeshView>();
        private Vector3 toolTargetPosition;
        private Quaternion toolTargetRotation = Quaternion.identity;

        public SimulationSnapshotDto LatestSnapshot { get; private set; }
        public event Action<SimulationSnapshotDto> SnapshotReceived;

        public void SetTarget(SimulationSnapshotDto snapshot)
        {
            LatestSnapshot = snapshot;
            if (snapshot.tool != null)
            {
                toolTargetPosition = CoordinateFrame.Position(snapshot.tool.positionMm);
                toolTargetRotation = CoordinateFrame.Rotation(snapshot.tool.orientation);
            }
            foreach (var state in snapshot.deformableMeshes ?? new DeformableMeshDto[0])
            {
                GetOrCreateMesh(state).SetTarget(state);
            }
            SnapshotReceived?.Invoke(snapshot);
        }

        private void Awake()
        {
            if (toolTransform == null)
            {
                var tip = new GameObject("Authoritative SOFA Tool Tip");
                tip.transform.SetParent(transform, false);
                toolTransform = tip.transform;

                var shaft = GameObject.CreatePrimitive(PrimitiveType.Capsule);
                shaft.name = "Blunt Training Tool";
                shaft.transform.SetParent(tip.transform, false);
                shaft.transform.localPosition = new Vector3(0f, 0.035f, 0f);
                shaft.transform.localScale = new Vector3(0.004f, 0.035f, 0.004f);
                var collider = shaft.GetComponent<Collider>();
                if (collider != null)
                {
                    Destroy(collider);
                }
                if (toolMaterial != null)
                {
                    shaft.GetComponent<MeshRenderer>().sharedMaterial = toolMaterial;
                }
            }
        }

        private void Update()
        {
            var amount = 1f - Mathf.Exp(-interpolationSpeed * Time.deltaTime);
            toolTransform.localPosition = Vector3.Lerp(
                toolTransform.localPosition, toolTargetPosition, amount
            );
            toolTransform.localRotation = Quaternion.Slerp(
                toolTransform.localRotation, toolTargetRotation, amount
            );
            foreach (var view in meshes.Values)
            {
                view.Interpolate(amount);
            }
        }

        private MeshView GetOrCreateMesh(DeformableMeshDto state)
        {
            if (meshes.TryGetValue(state.objectId, out var existing))
            {
                return existing;
            }
            var child = new GameObject(state.objectId);
            child.transform.SetParent(transform, false);
            var filter = child.AddComponent<MeshFilter>();
            var renderer = child.AddComponent<MeshRenderer>();
            if (tissueMaterial != null)
            {
                renderer.sharedMaterial = tissueMaterial;
            }
            var created = new MeshView(filter);
            meshes.Add(state.objectId, created);
            return created;
        }

        private sealed class MeshView
        {
            private readonly Mesh mesh;
            private Vector3[] target = new Vector3[0];
            private int topologyRevision = -1;

            public MeshView(MeshFilter filter)
            {
                mesh = new Mesh { name = "SOFA deformable surface" };
                mesh.MarkDynamic();
                filter.sharedMesh = mesh;
            }

            public void SetTarget(DeformableMeshDto state)
            {
                target = new Vector3[state.verticesMm.Length];
                for (var index = 0; index < target.Length; index++)
                {
                    target[index] = CoordinateFrame.Position(state.verticesMm[index]);
                }
                if (mesh.vertexCount != target.Length)
                {
                    mesh.vertices = target;
                }
                if (topologyRevision != state.topologyRevision)
                {
                    mesh.triangles = CoordinateFrame.ReflectedTriangles(state.triangleIndices);
                    topologyRevision = state.topologyRevision;
                }
            }

            public void Interpolate(float amount)
            {
                if (target.Length == 0)
                {
                    return;
                }
                var current = mesh.vertices;
                if (current.Length != target.Length)
                {
                    current = (Vector3[])target.Clone();
                }
                for (var index = 0; index < current.Length; index++)
                {
                    current[index] = Vector3.Lerp(current[index], target[index], amount);
                }
                mesh.vertices = current;
                mesh.RecalculateNormals();
                mesh.RecalculateBounds();
            }
        }
    }
}
