using System;
using System.Collections.Generic;
using UnityEngine;

namespace SurgePrep
{
    public sealed class SimulationSceneRenderer : MonoBehaviour
    {
        [SerializeField] private Transform toolTransform;
        [SerializeField, Min(1f)] private float interpolationSpeed = 20f;
        [SerializeField] private GameObject scalpelModel;
        [SerializeField] private Material tissueMaterial;
        [SerializeField] private Material subcutaneousMaterial;
        [SerializeField] private Material muscleMaterial;
        [SerializeField] private Material pleuraMaterial;
        [SerializeField] private Material incisionMaterial;
        [SerializeField] private Material toolMaterial;
        [SerializeField] private LineRenderer incisionGuide;

        private readonly Dictionary<string, MeshView> meshes = new Dictionary<string, MeshView>();
        private Vector3 toolTargetPosition;
        private Quaternion toolTargetRotation = Quaternion.identity;
        private GameObject scalpelVisual;
        private GameObject dissectorVisual;
        private GameObject tubeVisual;

        public SimulationSnapshotDto LatestSnapshot { get; private set; }
        public event Action<SimulationSnapshotDto> SnapshotReceived;

        public void SetTarget(SimulationSnapshotDto snapshot)
        {
            LatestSnapshot = snapshot;
            if (snapshot.tool != null)
            {
                toolTargetPosition = RegisteredPosition(snapshot.tool.positionMm);
                toolTargetRotation = CoordinateFrame.Rotation(snapshot.tool.orientation);
                UpdateToolVisual(snapshot.tool.toolId);
                if (CoordinateFrame.ShouldSnap(toolTransform.localPosition, toolTargetPosition))
                {
                    toolTransform.localPosition = toolTargetPosition;
                    toolTransform.localRotation = toolTargetRotation;
                }
            }
            foreach (var state in snapshot.deformableMeshes ?? new DeformableMeshDto[0])
            {
                var view = GetOrCreateMesh(state);
                view.SetTarget(state);
                view.SetVisible(LayerVisible(state.objectId, snapshot));
            }
            UpdateIncisionGuide(snapshot);
            SnapshotReceived?.Invoke(snapshot);
        }

        private static bool LayerVisible(string objectId, SimulationSnapshotDto snapshot)
        {
            if (objectId == "layer-skin") return true;
            if (objectId == "wound-channel") return false;
            var openedSkin = snapshot.tissue != null && snapshot.tissue.incisionProgress > 0.05f;
            if (objectId == "layer-subcutaneous") return openedSkin;
            var fatOpen = LayerOpened(snapshot, "subcutaneous");
            if (objectId == "layer-intercostal-muscle") return fatOpen;
            if (objectId == "layer-pleura") return LayerOpened(snapshot, "intercostal-muscle");
            return true;
        }

        private static bool LayerOpened(SimulationSnapshotDto snapshot, string layerId)
        {
            if (snapshot.tissue == null || snapshot.tissue.layers == null) return false;
            foreach (var layer in snapshot.tissue.layers)
            {
                if (layer != null && layer.layerId == layerId)
                {
                    return layer.opened || layer.openingProgress > 0.2f;
                }
            }
            return false;
        }

        private void Awake()
        {
            if (toolTransform == null)
            {
                var tip = new GameObject("Authoritative SOFA Tool Tip");
                tip.transform.SetParent(transform, false);
                toolTransform = tip.transform;
                CreateToolVisuals(tip.transform);
            }
        }

        private void CreateToolVisuals(Transform tip)
        {
            scalpelVisual = new GameObject("Scalpel visual");
            scalpelVisual.transform.SetParent(tip, false);
            if (scalpelModel != null)
            {
                var imported = Instantiate(scalpelModel, scalpelVisual.transform);
                imported.name = "Supplied SolidWorks scalpel";
                imported.transform.localPosition = ScalpelGeometry.ModelToToolPosition;
                imported.transform.localRotation = ScalpelGeometry.ModelToToolRotation;
                imported.transform.localScale = Vector3.one;
            }
            else
            {
                Primitive("Fallback blade handle", PrimitiveType.Capsule, scalpelVisual.transform,
                    new Vector3(0f, 0.065f, 0f), new Vector3(0.007f, 0.05f, 0.007f));
                Primitive("Fallback training blade", PrimitiveType.Cube, scalpelVisual.transform,
                    new Vector3(0.002f, 0.012f, 0f), new Vector3(0.012f, 0.024f, 0.0018f));
                Primitive("Fallback blade guard", PrimitiveType.Cube, scalpelVisual.transform,
                    new Vector3(0f, 0.029f, 0f), new Vector3(0.022f, 0.004f, 0.011f));
            }

            dissectorVisual = new GameObject("Blunt dissector visual");
            dissectorVisual.transform.SetParent(tip, false);
            var leftJaw = Primitive(
                "Left blunt jaw", PrimitiveType.Capsule, dissectorVisual.transform,
                new Vector3(-0.004f, 0.048f, 0f), new Vector3(0.0035f, 0.04f, 0.0035f)
            );
            leftJaw.transform.localRotation = Quaternion.Euler(0f, 0f, -4f);
            var rightJaw = Primitive(
                "Right blunt jaw", PrimitiveType.Capsule, dissectorVisual.transform,
                new Vector3(0.004f, 0.048f, 0f), new Vector3(0.0035f, 0.04f, 0.0035f)
            );
            rightJaw.transform.localRotation = Quaternion.Euler(0f, 0f, 4f);
            Primitive(
                "Dissector stop", PrimitiveType.Sphere, dissectorVisual.transform,
                new Vector3(0f, 0.006f, 0f), Vector3.one * 0.011f
            );

            tubeVisual = new GameObject("Chest tube visual");
            tubeVisual.transform.SetParent(tip, false);
            Primitive(
                "Training chest tube", PrimitiveType.Cylinder, tubeVisual.transform,
                new Vector3(0f, 0.055f, 0f), new Vector3(0.0064f, 0.055f, 0.0064f)
            );

            if (toolMaterial != null)
            {
                foreach (var renderer in tip.GetComponentsInChildren<MeshRenderer>())
                {
                    renderer.sharedMaterial = toolMaterial;
                }
            }
            UpdateToolVisual("scalpel");

        }

        private void UpdateToolVisual(string toolId)
        {
            if (scalpelVisual != null) scalpelVisual.SetActive(
                string.IsNullOrEmpty(toolId) || toolId == "scalpel"
            );
            if (dissectorVisual != null) dissectorVisual.SetActive(toolId == "blunt-dissector");
            if (tubeVisual != null) tubeVisual.SetActive(toolId == "chest-tube");
        }

        private static GameObject Primitive(
            string name, PrimitiveType type, Transform parent, Vector3 position, Vector3 scale
        )
        {
            var created = GameObject.CreatePrimitive(type);
            created.name = name;
            created.transform.SetParent(parent, false);
            created.transform.localPosition = position;
            created.transform.localScale = scale;
            var collider = created.GetComponent<Collider>();
            if (collider != null) Destroy(collider);
            return created;
        }

        private void Update()
        {
            if (toolTransform == null) return;
            var amount = 1f - Mathf.Exp(-interpolationSpeed * Time.deltaTime);
            if (CoordinateFrame.ShouldSnap(toolTransform.localPosition, toolTargetPosition))
            {
                toolTransform.localPosition = toolTargetPosition;
                toolTransform.localRotation = toolTargetRotation;
            }
            else
            {
                toolTransform.localPosition = Vector3.Lerp(
                    toolTransform.localPosition, toolTargetPosition, amount
                );
                toolTransform.localRotation = Quaternion.Slerp(
                    toolTransform.localRotation, toolTargetRotation, amount
                );
            }
            foreach (var view in meshes.Values)
            {
                view.Interpolate(amount);
            }
        }

        private void UpdateIncisionGuide(SimulationSnapshotDto snapshot)
        {
            if (incisionGuide == null) return;
            var incisionStarted = snapshot.tissue != null
                && snapshot.tissue.incisionProgress > 0.03f;
            incisionGuide.gameObject.SetActive(!incisionStarted);
            if (incisionStarted) return;

            DeformableMeshDto skin = null;
            foreach (var state in snapshot.deformableMeshes ?? new DeformableMeshDto[0])
            {
                if (state != null && state.objectId == "layer-skin")
                {
                    skin = state;
                    break;
                }
            }

            incisionGuide.positionCount = 17;
            for (var index = 0; index < incisionGuide.positionCount; index++)
            {
                var t = index / (float)(incisionGuide.positionCount - 1);
                var xMm = Mathf.Lerp(-18f, 18f, t);
                var zMm = -3f + 6f * Mathf.Sin(t * Mathf.PI);
                var y = ChestSurfaceRegistration.OffsetMetres(xMm, zMm);
                if (skin != null && skin.verticesMm != null && skin.verticesMm.Length > 0)
                {
                    Vector3Dto nearest = null;
                    var nearestSquared = float.PositiveInfinity;
                    foreach (var vertex in skin.verticesMm)
                    {
                        var dx = vertex.x - xMm;
                        var dz = vertex.z - zMm;
                        var squared = dx * dx + dz * dz;
                        if (squared < nearestSquared)
                        {
                            nearestSquared = squared;
                            nearest = vertex;
                        }
                    }
                    if (nearest != null)
                    {
                        y = nearest.y * CoordinateFrame.MillimetresToMetres;
                    }
                }
                incisionGuide.SetPosition(
                    index,
                    new Vector3(
                        xMm * CoordinateFrame.MillimetresToMetres,
                        y + 0.0008f,
                        -zMm * CoordinateFrame.MillimetresToMetres
                    )
                );
            }
        }

        private static Vector3 RegisteredPosition(Vector3Dto source)
        {
            return CoordinateFrame.Position(source);
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
            renderer.sharedMaterial = MaterialFor(state.objectId);
            var created = new MeshView(filter, state.objectId);
            meshes.Add(state.objectId, created);
            return created;
        }

        private Material MaterialFor(string objectId)
        {
            if (objectId.Contains("wound") || objectId.Contains("incision")) return incisionMaterial;
            if (objectId.Contains("subcutaneous")) return subcutaneousMaterial != null ? subcutaneousMaterial : tissueMaterial;
            if (objectId.Contains("muscle")) return muscleMaterial != null ? muscleMaterial : tissueMaterial;
            if (objectId.Contains("pleura")) return pleuraMaterial != null ? pleuraMaterial : tissueMaterial;
            return tissueMaterial;
        }

        private sealed class MeshView
        {
            private readonly Mesh mesh;
            private readonly GameObject owner;
            private readonly string objectId;
            private Vector3[] target = new Vector3[0];
            private int topologyRevision = -1;

            public MeshView(MeshFilter filter, string objectId)
            {
                owner = filter.gameObject;
                this.objectId = objectId;
                mesh = new Mesh { name = "SOFA deformable surface" };
                mesh.MarkDynamic();
                filter.sharedMesh = mesh;
            }

            public void SetVisible(bool visible)
            {
                if (owner != null) owner.SetActive(visible);
            }

            public void SetTarget(DeformableMeshDto state)
            {
                var nextTarget = new Vector3[state.verticesMm.Length];
                for (var index = 0; index < nextTarget.Length; index++)
                {
                    if (!Finite(state.verticesMm[index]))
                    {
                        return;
                    }
                    nextTarget[index] = RegisteredPosition(state.verticesMm[index]);
                }
                target = nextTarget;
                if (mesh.vertexCount != target.Length)
                {
                    mesh.vertices = target;
                }
                if (topologyRevision != state.topologyRevision)
                {
                    mesh.triangles = CoordinateFrame.ReflectedTriangles(
                        AnatomyFieldTriangles(state)
                    );
                    topologyRevision = state.topologyRevision;
                }
            }

            private static bool Finite(Vector3Dto value)
            {
                return value != null
                    && !float.IsNaN(value.x) && !float.IsInfinity(value.x)
                    && !float.IsNaN(value.y) && !float.IsInfinity(value.y)
                    && !float.IsNaN(value.z) && !float.IsInfinity(value.z);
            }

            private static int[] AnatomyFieldTriangles(DeformableMeshDto state)
            {
                var visible = new List<int>(state.triangleIndices.Length);
                for (var index = 0; index + 2 < state.triangleIndices.Length; index += 3)
                {
                    var a = state.verticesMm[state.triangleIndices[index]];
                    var b = state.verticesMm[state.triangleIndices[index + 1]];
                    var c = state.verticesMm[state.triangleIndices[index + 2]];
                    var xMm = (a.x + b.x + c.x) / 3f;
                    var zMm = (a.z + b.z + c.z) / 3f;
                    var ellipse = xMm * xMm / (30f * 30f)
                        + zMm * zMm / (22f * 22f);
                    if (ellipse > 1f) continue;
                    visible.Add(state.triangleIndices[index]);
                    visible.Add(state.triangleIndices[index + 1]);
                    visible.Add(state.triangleIndices[index + 2]);
                }
                return visible.ToArray();
            }

            public void Interpolate(float amount)
            {
                if (target.Length == 0) return;
                var current = mesh.vertices;
                if (current.Length != target.Length)
                {
                    current = (Vector3[])target.Clone();
                }
                else if (current.Length > 0 && CoordinateFrame.ShouldSnap(current[0], target[0]))
                {
                    current = (Vector3[])target.Clone();
                }
                else
                {
                    for (var index = 0; index < current.Length; index++)
                    {
                        current[index] = Vector3.Lerp(current[index], target[index], amount);
                    }
                }
                mesh.vertices = current;
                mesh.RecalculateNormals();
                mesh.RecalculateBounds();
            }
        }
    }
}
