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
        [SerializeField] private Material subcutaneousMaterial;
        [SerializeField] private Material muscleMaterial;
        [SerializeField] private Material pleuraMaterial;
        [SerializeField] private Material incisionMaterial;
        [SerializeField] private Material toolMaterial;
        [SerializeField] private Material pressureIndicatorMaterial;
        [SerializeField] private Material bloodMaterial;

        private readonly Dictionary<string, MeshView> meshes = new Dictionary<string, MeshView>();
        private Vector3 toolTargetPosition;
        private Quaternion toolTargetRotation = Quaternion.identity;
        private Transform pressureIndicator;
        private Transform contactMarker;
        private Transform toolShadow;
        private Transform bloodDecal;
        private GameObject scalpelVisual;
        private GameObject dissectorVisual;
        private GameObject tubeVisual;
        private Material pressureIndicatorInstance;

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
                UpdateContactVisuals(snapshot);
            }
            foreach (var state in snapshot.deformableMeshes ?? new DeformableMeshDto[0])
            {
                var view = GetOrCreateMesh(state);
                view.SetTarget(state);
                view.SetVisible(LayerVisible(state.objectId, snapshot));
            }
            SnapshotReceived?.Invoke(snapshot);
        }

        private static bool LayerVisible(string objectId, SimulationSnapshotDto snapshot)
        {
            if (objectId == "layer-skin" || objectId == "wound-channel") return true;
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
            Primitive("Training blade handle", PrimitiveType.Capsule, scalpelVisual.transform,
                new Vector3(0f, 0.065f, 0f), new Vector3(0.007f, 0.05f, 0.007f));
            Primitive("Visible blunt training blade", PrimitiveType.Cube, scalpelVisual.transform,
                new Vector3(0.002f, 0.012f, 0f), new Vector3(0.012f, 0.024f, 0.0018f));
            Primitive("Training blade guard", PrimitiveType.Cube, scalpelVisual.transform,
                new Vector3(0f, 0.029f, 0f), new Vector3(0.022f, 0.004f, 0.011f));

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

            var indicator = Primitive("Contact pressure indicator", PrimitiveType.Sphere, tip,
                Vector3.zero, Vector3.one * 0.008f);
            pressureIndicator = indicator.transform;
            if (pressureIndicatorMaterial != null)
            {
                pressureIndicatorInstance = new Material(pressureIndicatorMaterial);
                indicator.GetComponent<MeshRenderer>().sharedMaterial = pressureIndicatorInstance;
            }
            indicator.SetActive(false);

            var marker = Primitive("SOFA contact marker", PrimitiveType.Sphere, transform,
                Vector3.zero, Vector3.one * 0.0045f);
            contactMarker = marker.transform;
            marker.SetActive(false);

            var shadow = Primitive("Instrument depth cue", PrimitiveType.Cylinder, transform,
                Vector3.zero, new Vector3(0.012f, 0.0004f, 0.012f));
            toolShadow = shadow.transform;

            var blood = Primitive("Controlled blood decal", PrimitiveType.Quad, transform,
                new Vector3(0f, -0.001f, 0f), Vector3.one * 0.018f);
            blood.transform.localRotation = Quaternion.Euler(90f, 0f, 0f);
            bloodDecal = blood.transform;
            if (bloodMaterial != null)
            {
                blood.GetComponent<MeshRenderer>().sharedMaterial = bloodMaterial;
            }
            blood.SetActive(false);
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

        private void UpdateContactVisuals(SimulationSnapshotDto snapshot)
        {
            var tool = snapshot.tool;
            if (pressureIndicator != null)
            {
                pressureIndicator.gameObject.SetActive(tool.contact);
                pressureIndicator.localScale = Vector3.one * (0.006f + tool.reactionForceN * 0.004f);
                if (pressureIndicatorInstance != null)
                {
                    var colour = tool.reactionForceN > 1.2f
                        ? new Color(1f, 0.08f, 0.03f, 0.75f)
                        : tool.reactionForceN < 0.3f
                            ? new Color(0.2f, 0.55f, 1f, 0.65f)
                            : new Color(0.05f, 1f, 0.65f, 0.7f);
                    if (pressureIndicatorInstance.HasProperty("_BaseColor"))
                        pressureIndicatorInstance.SetColor("_BaseColor", colour);
                    if (pressureIndicatorInstance.HasProperty("_Color"))
                        pressureIndicatorInstance.SetColor("_Color", colour);
                }
            }
            if (contactMarker != null)
            {
                contactMarker.gameObject.SetActive(tool.contact);
                if (tool.contact)
                {
                    var point = tool.contactPointMm != null
                        ? RegisteredPosition(tool.contactPointMm)
                        : RegisteredPosition(tool.positionMm);
                    contactMarker.localPosition = point;
                }
            }
            if (toolShadow != null)
            {
                var tip = RegisteredPosition(tool.positionMm);
                toolShadow.localPosition = new Vector3(
                    tip.x,
                    ChestSurfaceRegistration.OffsetMetres(
                        tool.positionMm.x, tool.positionMm.z
                    ) + 0.0004f,
                    tip.z
                );
            }
            if (bloodDecal != null && snapshot.tissue != null)
            {
                var show = snapshot.tissue.incisionProgress > 0.08f;
                bloodDecal.gameObject.SetActive(show);
            }
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

        private static Vector3 RegisteredPosition(Vector3Dto source)
        {
            var position = CoordinateFrame.Position(source);
            if (source != null)
            {
                position.y += ChestSurfaceRegistration.OffsetMetres(source.x, source.z);
            }
            return position;
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
            var created = new MeshView(filter);
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
            private Vector3[] target = new Vector3[0];
            private int topologyRevision = -1;

            public MeshView(MeshFilter filter)
            {
                owner = filter.gameObject;
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
                target = new Vector3[state.verticesMm.Length];
                for (var index = 0; index < target.Length; index++)
                {
                    target[index] = RegisteredPosition(state.verticesMm[index]);
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
