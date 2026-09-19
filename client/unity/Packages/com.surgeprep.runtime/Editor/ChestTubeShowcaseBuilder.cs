using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.PackageManager;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.SceneManagement;

namespace SurgePrep.Editor
{
    public static class ChestTubeShowcaseBuilder
    {
        private const string ShowcaseRoot = "Assets/SurgePrepShowcase";
        private const string AnatomyRoot = ShowcaseRoot + "/Anatomy";
        private const string MaterialRoot = ShowcaseRoot + "/Materials";
        private const string GeneratedRoot = ShowcaseRoot + "/Generated";
        private const string SceneRoot = ShowcaseRoot + "/Scenes";

        private static readonly string[] AnatomyFiles =
        {
            "FJ2810_BP22617_FMA7163_Skin.obj",
            "FJ3178_BP22232_FMA7487_Body of sternum.obj",
            "FJ3290_BP22794_FMA7486_Manubrium.obj",
            "FJ3153_BP22299_FMA7488_Xiphoid process.obj",
            "FJ3237_BP23283_FMA13323_Left clavicle.obj",
            "FJ3362_BP23174_FMA13322_Right clavicle.obj",
            "FJ3231_BP22488_FMA8148_Left fourth rib.obj",
            "FJ3232_BP22285_FMA8093_Left fifth rib.obj",
            "FJ3233_BP22298_FMA8202_Left sixth rib.obj",
            "FJ3234_BP22332_FMA8256_Left seventh rib.obj",
            "FJ3235_BP23684_FMA8310_Left eighth rib.obj",
            "FJ3340_BP22336_FMA7957_Right fourth rib.obj",
            "FJ3342_BP22307_FMA8066_Right fifth rib.obj",
            "FJ3344_BP22272_FMA8175_Right sixth rib.obj",
            "FJ3346_BP22330_FMA8229_Right seventh rib.obj",
            "FJ3347_BP23993_FMA8283_Right eighth rib.obj",
            "FJ3248_BP22751_FMA8167_Left fourth costal cartilage.obj",
            "FJ3251_BP21380_FMA8112_Left fifth costal cartilage.obj",
            "FJ3254_BP21377_FMA8221_Left sixth costal cartilage.obj",
            "FJ3255_BP22753_FMA8275_Left seventh costal cartilage.obj",
            "FJ3339_BP21410_FMA7976_Right fourth costal cartilage.obj",
            "FJ3341_BP21376_FMA8070_Right fifth costal cartilage.obj",
            "FJ3343_BP22071_FMA8194_Right sixth costal cartilage.obj",
            "FJ3345_BP21381_FMA8248_Right seventh costal cartilage.obj",
            "FJ1451M_BP23614_FMA9756_External intercostal muscle.obj",
            "FJ1451_BP23614_FMA9756_External intercostal muscle.obj",
            "FJ1456M_BP23831_FMA13376_Left pectoralis minor.obj",
            "FJ1456_BP23886_FMA13375_Right pectoralis minor.obj",
            "FJ1464M_BP24065_FMA79980_Sternocostal part of left pectoralis major.obj",
            "FJ1464_BP23276_FMA79979_Sternocostal part of right pectoralis major.obj",
            "FJ3131_BP23131_FMA13295_Diaphragm.obj"
        };

        [MenuItem("Surge Prep/Build Chest-Tube Showcase")]
        public static void BuildShowcase()
        {
            if (!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo())
            {
                return;
            }

            var source = FindAnatomySource();
            if (source == null)
            {
                EditorUtility.DisplayDialog(
                    "Surge Prep anatomy not found",
                    "The package must remain linked to the surgery-htn repository so its " +
                    "bodyparts3d_highres directory can be imported.",
                    "OK"
                );
                return;
            }

            try
            {
                ImportAnatomy(source);
                CreateScene();
            }
            catch (Exception error)
            {
                Debug.LogException(error);
                EditorUtility.DisplayDialog("Showcase build failed", error.Message, "OK");
            }
            finally
            {
                EditorUtility.ClearProgressBar();
            }
        }

        private static string FindAnatomySource()
        {
            var package = UnityEditor.PackageManager.PackageInfo.FindForAssembly(
                typeof(ChestTubeShowcaseBuilder).Assembly
            );
            if (package == null)
            {
                return null;
            }
            var repository = Path.GetFullPath(Path.Combine(package.resolvedPath, "../../../.."));
            var source = Path.Combine(repository, "bodyparts3d_highres");
            return Directory.Exists(source) ? source : null;
        }

        private static void ImportAnatomy(string source)
        {
            Directory.CreateDirectory(AnatomyRoot);
            for (var index = 0; index < AnatomyFiles.Length; index++)
            {
                var file = AnatomyFiles[index];
                EditorUtility.DisplayProgressBar(
                    "Preparing chest anatomy",
                    file,
                    (float)index / AnatomyFiles.Length
                );
                var sourcePath = Path.Combine(source, file);
                if (!File.Exists(sourcePath))
                {
                    throw new FileNotFoundException("Required anatomy mesh is missing", sourcePath);
                }
                var destination = Path.Combine(AnatomyRoot, file);
                if (!File.Exists(destination))
                {
                    File.Copy(sourcePath, destination);
                }
                AssetDatabase.ImportAsset(destination, ImportAssetOptions.ForceSynchronousImport);
                var importer = AssetImporter.GetAtPath(destination) as ModelImporter;
                if (importer != null && !Mathf.Approximately(importer.globalScale, 0.001f))
                {
                    importer.globalScale = 0.001f;
                    importer.materialImportMode = ModelImporterMaterialImportMode.None;
                    importer.SaveAndReimport();
                }
            }
        }

        private static void CreateScene()
        {
            Directory.CreateDirectory(MaterialRoot);
            Directory.CreateDirectory(GeneratedRoot);
            Directory.CreateDirectory(SceneRoot);
            var bone = Material("Bone", new Color(0.68f, 0.58f, 0.42f), 0.03f, 0.32f);
            var cartilage = Material("Cartilage", new Color(0.08f, 0.38f, 0.55f), 0.0f, 0.48f);
            var muscle = Material("Muscle", new Color(0.33f, 0.025f, 0.045f), 0.0f, 0.38f);
            var diaphragm = Material("Diaphragm", new Color(0.3f, 0.055f, 0.22f), 0.0f, 0.38f);
            var skin = TransparentMaterial("Skin", new Color(0.46f, 0.18f, 0.13f, 0.18f));
            var target = Material("Target", new Color(0.05f, 0.95f, 0.78f), 0.0f, 0.65f);
            var tissue = TransparentMaterial(
                "InteractiveTissue", new Color(0.42f, 0.025f, 0.045f, 0.82f)
            );
            var incision = EmissiveMaterial(
                "IncisionChannel", new Color(0.12f, 0.002f, 0.006f)
            );
            var pressure = TransparentMaterial(
                "PressureIndicator", new Color(0.05f, 1f, 0.65f, 0.7f)
            );
            var tool = Material("TrainingTool", new Color(0.65f, 0.72f, 0.78f), 0.65f, 0.7f);
            var roomWall = Material("RoomWall", new Color(0.018f, 0.035f, 0.065f), 0.0f, 0.3f);
            var roomFloor = Material("RoomFloor", new Color(0.008f, 0.018f, 0.028f), 0.1f, 0.5f);
            var roomPanel = Material("RoomPanel", new Color(0.025f, 0.08f, 0.12f), 0.2f, 0.5f);
            var neon = EmissiveMaterial("RoomNeon", new Color(0.04f, 0.8f, 0.72f));
            var warmNeon = EmissiveMaterial("RoomWarmNeon", new Color(0.9f, 0.22f, 0.1f));

            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            RenderSettings.ambientLight = new Color(0.18f, 0.22f, 0.27f);

            var anatomy = new GameObject("Layered Chest Anatomy");
            anatomy.transform.rotation = Quaternion.Euler(-90f, 0f, 0f);
            anatomy.transform.position = new Vector3(0f, -1.23f, 0f);
            var skinLayer = Layer("Skin layer", anatomy.transform);
            var muscleLayer = Layer("Muscle layer", anatomy.transform);
            var boneLayer = Layer("Bone layer", anatomy.transform);
            var cartilageLayer = Layer("Cartilage layer", anatomy.transform);
            var diaphragmLayer = Layer("Diaphragm layer", anatomy.transform);

            foreach (var file in AnatomyFiles)
            {
                var assetPath = AnatomyRoot + "/" + file;
                var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(assetPath);
                if (prefab == null)
                {
                    throw new InvalidOperationException("Unity could not import " + file);
                }
                var parent = LayerFor(
                    file, skinLayer, muscleLayer, boneLayer, cartilageLayer, diaphragmLayer
                );
                var instance = PrefabUtility.InstantiatePrefab(prefab, parent) as GameObject;
                instance.name = FriendlyName(file);
                AssignMaterial(instance, MaterialFor(file, bone, cartilage, muscle, diaphragm, skin));
                if (file.Contains("Skin"))
                {
                    CropSkinToTorso(instance);
                }
            }
            skinLayer.gameObject.SetActive(false);

            CreateTrainingRoom(roomWall, roomFloor, roomPanel, neon, warmNeon);

            var simulation = new GameObject("Surge Prep Simulation");
            simulation.transform.position = new Vector3(-0.105f, 0.005f, 0.215f);
            simulation.transform.rotation = Quaternion.Euler(90f, 0f, 0f);
            var renderer = simulation.AddComponent<SimulationSceneRenderer>();
            var stream = simulation.AddComponent<ScalpelStreamClient>();
            stream.enabled = false;
            var manualDemo = simulation.AddComponent<UnityManualDemoClient>();
            var hud = simulation.AddComponent<ChestTubeShowcaseHud>();
            SetObject(renderer, "tissueMaterial", tissue);
            SetObject(renderer, "incisionMaterial", incision);
            SetObject(renderer, "toolMaterial", tool);
            SetObject(renderer, "pressureIndicatorMaterial", pressure);
            SetObject(stream, "sceneRenderer", renderer);
            SetObject(manualDemo, "sceneRenderer", renderer);
            SetObject(hud, "sceneRenderer", renderer);
            SetObject(hud, "manualDemo", manualDemo);
            CreateTargetGuide(simulation.transform, target);

            var camera = CreateCamera();
            CreateLighting();

            var focusObject = new GameObject("Chest camera focus");
            focusObject.transform.position = new Vector3(-0.045f, -0.07f, 0.14f);
            var targetFocusObject = new GameObject("Procedure target camera focus");
            targetFocusObject.transform.position = new Vector3(-0.105f, 0.005f, 0.225f);
            var experienceObject = new GameObject("Interactive showcase controls");
            var experience = experienceObject.AddComponent<SurgePrep.ShowcaseExperienceController>();
            SetObject(experience, "sceneCamera", camera);
            SetObject(experience, "chestFocus", focusObject.transform);
            SetObject(experience, "targetFocus", targetFocusObject.transform);
            SetObject(experience, "skinLayer", skinLayer.gameObject);
            SetObject(experience, "muscleLayer", muscleLayer.gameObject);
            SetObject(experience, "boneLayer", boneLayer.gameObject);
            SetObject(experience, "cartilageLayer", cartilageLayer.gameObject);
            SetObject(experience, "diaphragmLayer", diaphragmLayer.gameObject);

            var scenePath = SceneRoot + "/ChestTubeShowcase.unity";
            EditorSceneManager.SaveScene(scene, scenePath);
            Selection.activeGameObject = simulation;
            EditorGUIUtility.PingObject(AssetDatabase.LoadAssetAtPath<SceneAsset>(scenePath));
            Debug.Log(
                "Surge Prep showcase created. Start Docker, enter Play Mode, and click " +
                "the Game view to control the training tool."
            );
        }

        private static void CreateTrainingRoom(
            Material wall,
            Material floor,
            Material panel,
            Material neon,
            Material warmNeon
        )
        {
            var room = new GameObject("Surge Prep Training Lab");
            Cube("Floor", room.transform, new Vector3(0f, -1.31f, -0.1f), new Vector3(4f, 0.08f, 4f), floor);
            Cube("Back wall", room.transform, new Vector3(0f, 0.0f, -0.82f), new Vector3(4f, 2.8f, 0.08f), wall);
            Cube("Left wall", room.transform, new Vector3(-2f, 0.0f, 0.1f), new Vector3(0.08f, 2.8f, 4f), wall);
            Cube("Right wall", room.transform, new Vector3(2f, 0.0f, 0.1f), new Vector3(0.08f, 2.8f, 4f), wall);
            Cube("Ceiling", room.transform, new Vector3(0f, 1.4f, 0.1f), new Vector3(4f, 0.08f, 4f), wall);

            Cube("Anatomy display panel", room.transform, new Vector3(0f, -0.02f, -0.74f), new Vector3(1.55f, 2.35f, 0.04f), panel);
            Cube("Panel top light", room.transform, new Vector3(0f, 1.15f, -0.69f), new Vector3(1.5f, 0.018f, 0.012f), neon);
            Cube("Panel left light", room.transform, new Vector3(-0.76f, -0.02f, -0.69f), new Vector3(0.018f, 2.3f, 0.012f), neon);
            Cube("Panel right light", room.transform, new Vector3(0.76f, -0.02f, -0.69f), new Vector3(0.018f, 2.3f, 0.012f), neon);
            Cube("Hologram pedestal", room.transform, new Vector3(0f, -0.38f, 0.02f), new Vector3(0.9f, 0.08f, 0.62f), panel);
            Cube("Pedestal front light", room.transform, new Vector3(0f, -0.33f, 0.33f), new Vector3(0.9f, 0.012f, 0.012f), neon);
            Cube("Pedestal back light", room.transform, new Vector3(0f, -0.33f, -0.29f), new Vector3(0.9f, 0.012f, 0.012f), neon);
            Cube("Pedestal left light", room.transform, new Vector3(-0.45f, -0.33f, 0.02f), new Vector3(0.012f, 0.012f, 0.62f), neon);
            Cube("Pedestal right light", room.transform, new Vector3(0.45f, -0.33f, 0.02f), new Vector3(0.012f, 0.012f, 0.62f), neon);

            Cube("Instructor console", room.transform, new Vector3(-1.3f, -0.92f, 0.2f), new Vector3(0.95f, 0.08f, 0.5f), panel);
            Cube("Console screen", room.transform, new Vector3(-1.3f, -0.63f, 0.17f), new Vector3(0.62f, 0.34f, 0.04f), wall);
            Cube("Console status light", room.transform, new Vector3(-1.3f, -0.63f, 0.13f), new Vector3(0.48f, 0.012f, 0.01f), warmNeon);

            for (var index = -3; index <= 3; index++)
            {
                Cube("Floor guide " + index, room.transform, new Vector3(index * 0.35f, -1.265f, 0.85f), new Vector3(0.015f, 0.006f, 0.8f), neon);
            }
            Cube("Floor guide crossbar", room.transform, new Vector3(0f, -1.258f, 0.1f), new Vector3(2.5f, 0.006f, 0.015f), warmNeon);
        }

        private static GameObject Cube(
            string name, Transform parent, Vector3 position, Vector3 scale, Material material
        )
        {
            var cube = GameObject.CreatePrimitive(PrimitiveType.Cube);
            cube.name = name;
            cube.transform.SetParent(parent, false);
            cube.transform.localPosition = position;
            cube.transform.localScale = scale;
            cube.GetComponent<MeshRenderer>().sharedMaterial = material;
            var collider = cube.GetComponent<Collider>();
            if (collider != null)
            {
                UnityEngine.Object.DestroyImmediate(collider);
            }
            return cube;
        }

        private static Transform Layer(string name, Transform parent)
        {
            var layer = new GameObject(name);
            layer.transform.SetParent(parent, false);
            return layer.transform;
        }

        private static Transform LayerFor(
            string file,
            Transform skin,
            Transform muscle,
            Transform bone,
            Transform cartilage,
            Transform diaphragm
        )
        {
            if (file.Contains("Skin")) return skin;
            if (file.Contains("Diaphragm")) return diaphragm;
            if (file.Contains("cartilage")) return cartilage;
            if (file.Contains("muscle") || file.Contains("pectoralis")) return muscle;
            return bone;
        }

        private static Camera CreateCamera()
        {
            var cameraObject = new GameObject("Main Camera");
            cameraObject.tag = "MainCamera";
            var camera = cameraObject.AddComponent<Camera>();
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(0.018f, 0.03f, 0.045f);
            camera.fieldOfView = 38f;
            camera.nearClipPlane = 0.01f;
            cameraObject.transform.position = new Vector3(-0.045f, -0.07f, 0.78f);
            cameraObject.transform.LookAt(new Vector3(-0.045f, -0.07f, 0.14f));
            camera.fieldOfView = 44f;
            cameraObject.AddComponent<AudioListener>();
            return camera;
        }

        private static void CreateLighting()
        {
            var key = new GameObject("Clinical Key Light");
            var keyLight = key.AddComponent<Light>();
            keyLight.type = LightType.Directional;
            keyLight.intensity = 0.72f;
            keyLight.color = new Color(0.86f, 0.93f, 1f);
            key.transform.rotation = Quaternion.Euler(35f, -25f, 0f);

            var fill = new GameObject("Warm Fill Light");
            var fillLight = fill.AddComponent<Light>();
            fillLight.type = LightType.Point;
            fillLight.intensity = 1.15f;
            fillLight.range = 1.5f;
            fillLight.color = new Color(1f, 0.62f, 0.48f);
            fill.transform.position = new Vector3(-0.35f, 0.22f, 0.45f);

            var rim = new GameObject("Cool Rim Light");
            var rimLight = rim.AddComponent<Light>();
            rimLight.type = LightType.Point;
            rimLight.intensity = 1.6f;
            rimLight.range = 1.2f;
            rimLight.color = new Color(0.1f, 0.65f, 0.9f);
            rim.transform.position = new Vector3(0.45f, 0.28f, -0.15f);
        }

        private static void CreateTargetGuide(Transform parent, Material material)
        {
            var guide = new GameObject("Illustrative target region - instructor review required");
            guide.transform.SetParent(parent, false);
            guide.transform.localPosition = new Vector3(0f, 0.0145f, 0f);
            var line = guide.AddComponent<LineRenderer>();
            line.useWorldSpace = false;
            line.loop = true;
            line.positionCount = 64;
            line.startWidth = 0.0015f;
            line.endWidth = 0.0015f;
            line.sharedMaterial = material;
            for (var index = 0; index < line.positionCount; index++)
            {
                var angle = index * Mathf.PI * 2f / line.positionCount;
                line.SetPosition(index, new Vector3(Mathf.Cos(angle), 0f, Mathf.Sin(angle)) * 0.021f);
            }
        }

        private static Material Material(
            string name, Color colour, float metallic, float smoothness
        )
        {
            var path = MaterialRoot + "/" + name + ".mat";
            var material = AssetDatabase.LoadAssetAtPath<Material>(path);
            var shader = ShowcaseShader();
            if (material == null)
            {
                material = new Material(shader) { name = name };
                AssetDatabase.CreateAsset(material, path);
            }
            else
            {
                material.shader = shader;
            }
            material.color = colour;
            material.SetFloat("_Metallic", metallic);
            material.SetFloat("_Smoothness", smoothness);
            EditorUtility.SetDirty(material);
            return material;
        }

        private static Material TransparentMaterial(string name, Color colour)
        {
            var material = Material(name, colour, 0f, 0.2f);
            material.color = colour;
            material.SetOverrideTag("RenderType", "Transparent");
            material.SetFloat("_ZWrite", 0f);
            material.SetFloat("_SrcBlend", (float)BlendMode.SrcAlpha);
            material.SetFloat("_DstBlend", (float)BlendMode.OneMinusSrcAlpha);
            if (GraphicsSettings.currentRenderPipeline == null)
            {
                material.SetFloat("_Mode", 3f);
                material.DisableKeyword("_ALPHATEST_ON");
                material.EnableKeyword("_ALPHABLEND_ON");
                material.DisableKeyword("_ALPHAPREMULTIPLY_ON");
            }
            else
            {
                material.SetFloat("_Surface", 1f);
                material.EnableKeyword("_SURFACE_TYPE_TRANSPARENT");
            }
            material.renderQueue = 3000;
            EditorUtility.SetDirty(material);
            return material;
        }

        private static Material EmissiveMaterial(string name, Color colour)
        {
            var material = Material(name, colour, 0f, 0.45f);
            material.EnableKeyword("_EMISSION");
            material.SetColor("_EmissionColor", colour * 3.0f);
            EditorUtility.SetDirty(material);
            return material;
        }

        private static Shader ShowcaseShader()
        {
            var shaderName = GraphicsSettings.currentRenderPipeline == null
                ? "Standard"
                : "Universal Render Pipeline/Lit";
            var shader = Shader.Find(shaderName);
            if (shader == null)
            {
                throw new InvalidOperationException(
                    $"The showcase could not find the required '{shaderName}' shader."
                );
            }
            return shader;
        }

        private static Material MaterialFor(
            string file,
            Material bone,
            Material cartilage,
            Material muscle,
            Material diaphragm,
            Material skin
        )
        {
            if (file.Contains("Skin")) return skin;
            if (file.Contains("Diaphragm")) return diaphragm;
            if (file.Contains("cartilage")) return cartilage;
            if (file.Contains("muscle") || file.Contains("pectoralis")) return muscle;
            return bone;
        }

        private static void AssignMaterial(GameObject root, Material material)
        {
            foreach (var renderer in root.GetComponentsInChildren<Renderer>(true))
            {
                renderer.sharedMaterial = material;
            }
        }

        private static void CropSkinToTorso(GameObject root)
        {
            var filters = root.GetComponentsInChildren<MeshFilter>(true);
            for (var filterIndex = 0; filterIndex < filters.Length; filterIndex++)
            {
                var filter = filters[filterIndex];
                var source = filter.sharedMesh;
                if (source == null)
                {
                    continue;
                }

                var vertices = source.vertices;
                var sourceTriangles = source.triangles;
                var torsoTriangles = new List<int>();
                var sourceUnitsPerMetre = source.bounds.max.z > 10f ? 1000f : 1f;
                for (var index = 0; index + 2 < sourceTriangles.Length; index += 3)
                {
                    var a = sourceTriangles[index];
                    var b = sourceTriangles[index + 1];
                    var c = sourceTriangles[index + 2];
                    var centre = (vertices[a] + vertices[b] + vertices[c]) / 3f;
                    if (
                        centre.z >= 0.94f * sourceUnitsPerMetre &&
                        centre.z <= 1.43f * sourceUnitsPerMetre &&
                        Mathf.Abs(centre.x) <= 0.285f * sourceUnitsPerMetre
                    )
                    {
                        torsoTriangles.Add(a);
                        torsoTriangles.Add(b);
                        torsoTriangles.Add(c);
                    }
                }

                var cropped = new Mesh
                {
                    name = "High-resolution torso skin",
                    indexFormat = source.indexFormat,
                    vertices = vertices,
                    normals = source.normals,
                    tangents = source.tangents,
                    uv = source.uv,
                };
                cropped.SetTriangles(torsoTriangles, 0);
                cropped.RecalculateBounds();

                var path = $"{GeneratedRoot}/TorsoSkin{filterIndex}.asset";
                var existing = AssetDatabase.LoadAssetAtPath<Mesh>(path);
                if (existing == null)
                {
                    AssetDatabase.CreateAsset(cropped, path);
                    filter.sharedMesh = cropped;
                }
                else
                {
                    EditorUtility.CopySerialized(cropped, existing);
                    UnityEngine.Object.DestroyImmediate(cropped);
                    filter.sharedMesh = existing;
                    EditorUtility.SetDirty(existing);
                }
            }
        }

        private static string FriendlyName(string file)
        {
            var withoutExtension = Path.GetFileNameWithoutExtension(file);
            var pieces = withoutExtension.Split('_');
            return pieces.Length > 3 ? string.Join(" ", pieces.Skip(3)) : withoutExtension;
        }

        private static void SetObject(UnityEngine.Object target, string property, UnityEngine.Object value)
        {
            var serialized = new SerializedObject(target);
            serialized.FindProperty(property).objectReferenceValue = value;
            serialized.ApplyModifiedPropertiesWithoutUndo();
        }
    }
}
