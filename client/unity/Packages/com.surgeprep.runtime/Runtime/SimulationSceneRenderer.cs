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
            if (objectId == "wound-channel")
            {
                return snapshot.tissue != null
                    && (snapshot.tissue.incisionDepthMm > 0.2f
                        || snapshot.tissue.incisionProgress > 0.01f
                        || snapshot.tissue.interactionMode == "cutting");
            }
            var openedSkin = snapshot.tissue != null
                && (snapshot.tissue.incisionProgress > 0.02f || snapshot.tissue.incisionDepthMm > 0.4f);
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
            scalpelVisual.transform.localPosition = Vector3.zero;
            scalpelVisual.transform.localRotation = Quaternion.identity;
            if (scalpelModel != null)
            {
                var imported = Instantiate(scalpelModel, scalpelVisual.transform);
                imported.name = "Supplied CAD scalpel — tip registered";
                imported.transform.localPosition = ScalpelGeometry.ModelToToolPosition;
                imported.transform.localRotation = ScalpelGeometry.ModelToToolRotation;
                imported.transform.localScale = Vector3.one;
            }
            else
            {
                CreateReadableScalpel(scalpelVisual.transform);
            }

            dissectorVisual = new GameObject("Blunt dissector visual");
            dissectorVisual.transform.SetParent(tip, false);
            dissectorVisual.transform.localPosition = Vector3.zero;
            dissectorVisual.transform.localRotation = Quaternion.identity;
            Primitive(
                "Left blunt tip", PrimitiveType.Sphere, dissectorVisual.transform,
                new Vector3(-0.0018f, 0f, 0f), Vector3.one * 0.0044f
            );
            Primitive(
                "Right blunt tip", PrimitiveType.Sphere, dissectorVisual.transform,
                new Vector3(0.0018f, 0f, 0f), Vector3.one * 0.0044f
            );
            var leftJaw = Primitive(
                "Left blunt jaw", PrimitiveType.Capsule, dissectorVisual.transform,
                new Vector3(-0.0042f, 0.044f, 0f), new Vector3(0.0032f, 0.040f, 0.0032f)
            );
            leftJaw.transform.localRotation = Quaternion.Euler(0f, 0f, -4f);
            var rightJaw = Primitive(
                "Right blunt jaw", PrimitiveType.Capsule, dissectorVisual.transform,
                new Vector3(0.0042f, 0.044f, 0f), new Vector3(0.0032f, 0.040f, 0.0032f)
            );
            rightJaw.transform.localRotation = Quaternion.Euler(0f, 0f, 4f);
            Primitive(
                "Dissector guard", PrimitiveType.Cube, dissectorVisual.transform,
                new Vector3(0f, 0.083f, 0f), new Vector3(0.020f, 0.006f, 0.012f)
            );
            Primitive(
                "Dissector handle", PrimitiveType.Cylinder, dissectorVisual.transform,
                new Vector3(0f, 0.108f, 0f), new Vector3(0.008f, 0.026f, 0.008f)
            );

            tubeVisual = new GameObject("Chest tube visual");
            tubeVisual.transform.SetParent(tip, false);
            tubeVisual.transform.localPosition = Vector3.zero;
            tubeVisual.transform.localRotation = Quaternion.identity;
            Primitive(
                "Chest tube rounded tip", PrimitiveType.Sphere, tubeVisual.transform,
                Vector3.zero, Vector3.one * 0.0064f
            );
            Primitive(
                "Training chest tube", PrimitiveType.Cylinder, tubeVisual.transform,
                new Vector3(0f, 0.055f, 0f), new Vector3(0.0064f, 0.055f, 0.0064f)
            );
            Primitive(
                "Tube hub", PrimitiveType.Cylinder, tubeVisual.transform,
                new Vector3(0f, 0.108f, 0f), new Vector3(0.0095f, 0.008f, 0.0095f)
            );
            Primitive(
                "Tube stripe", PrimitiveType.Cylinder, tubeVisual.transform,
                new Vector3(0f, 0.04f, 0f), new Vector3(0.007f, 0.004f, 0.007f)
            );

            if (toolMaterial != null)
            {
                foreach (var meshRenderer in tip.GetComponentsInChildren<MeshRenderer>())
                {
                    if (meshRenderer.sharedMaterial != null && meshRenderer.sharedMaterial.name == "ScalpelBlade")
                    {
                        continue;
                    }
                    meshRenderer.sharedMaterial = toolMaterial;
                }
            }
            PaintTools();
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

        private static void CreateReadableScalpel(Transform parent)
        {
            Primitive(
                "Scalpel handle", PrimitiveType.Capsule, parent,
                new Vector3(0f, 0.072f, 0f), new Vector3(0.011f, 0.048f, 0.011f)
            );
            Primitive(
                "Grip ring A", PrimitiveType.Cube, parent,
                new Vector3(0f, 0.058f, 0f), new Vector3(0.0124f, 0.006f, 0.0124f)
            );
            Primitive(
                "Grip ring B", PrimitiveType.Cube, parent,
                new Vector3(0f, 0.086f, 0f), new Vector3(0.0124f, 0.006f, 0.0124f)
            );
            Primitive(
                "Scalpel guard", PrimitiveType.Cube, parent,
                new Vector3(0f, 0.032f, 0f), new Vector3(0.018f, 0.006f, 0.012f)
            );
            var blade = Primitive(
                "Scalpel blade", PrimitiveType.Cube, parent,
                new Vector3(0f, 0.014f, 0f), new Vector3(0.016f, 0.028f, 0.0024f)
            );
            var renderer = blade.GetComponent<MeshRenderer>();
            if (renderer != null)
            {
                var bladeMaterial = new Material(renderer.sharedMaterial)
                {
                    name = "ScalpelBlade",
                    color = new Color(0.86f, 0.88f, 0.90f)
                };
                renderer.sharedMaterial = bladeMaterial;
            }
        }

        private void PaintTools()
        {
            PaintNamed(scalpelVisual, "Scalpel handle", new Color(0.93f, 0.78f, 0.12f));
            PaintNamed(scalpelVisual, "Grip ring A", new Color(0.10f, 0.10f, 0.11f));
            PaintNamed(scalpelVisual, "Grip ring B", new Color(0.10f, 0.10f, 0.11f));
            PaintNamed(scalpelVisual, "Scalpel guard", new Color(0.12f, 0.12f, 0.13f));
            PaintNamed(dissectorVisual, "Left blunt jaw", new Color(0.72f, 0.74f, 0.76f));
            PaintNamed(dissectorVisual, "Right blunt jaw", new Color(0.72f, 0.74f, 0.76f));
            PaintNamed(dissectorVisual, "Left blunt tip", new Color(0.72f, 0.74f, 0.76f));
            PaintNamed(dissectorVisual, "Right blunt tip", new Color(0.72f, 0.74f, 0.76f));
            PaintNamed(dissectorVisual, "Dissector guard", new Color(0.18f, 0.42f, 0.70f));
            PaintNamed(dissectorVisual, "Dissector handle", new Color(0.18f, 0.42f, 0.70f));
            PaintNamed(tubeVisual, "Chest tube rounded tip", new Color(0.82f, 0.62f, 0.28f));
            PaintNamed(tubeVisual, "Training chest tube", new Color(0.82f, 0.62f, 0.28f));
            PaintNamed(tubeVisual, "Tube hub", new Color(0.18f, 0.42f, 0.70f));
            PaintNamed(tubeVisual, "Tube stripe", new Color(0.93f, 0.94f, 0.95f));
        }

        private static void PaintNamed(GameObject root, string childName, Color color)
        {
            if (root == null) return;
            var child = root.transform.Find(childName);
            if (child == null) return;
            var meshRenderer = child.GetComponent<MeshRenderer>();
            if (meshRenderer == null) return;
            var source = meshRenderer.sharedMaterial;
            if (source == null) return;
            var painted = new Material(source) { color = color };
            meshRenderer.sharedMaterial = painted;
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
                        objectId.Contains("wound") || objectId.Contains("incision")
                            ? state.triangleIndices
                            : AnatomyFieldTriangles(state)
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
