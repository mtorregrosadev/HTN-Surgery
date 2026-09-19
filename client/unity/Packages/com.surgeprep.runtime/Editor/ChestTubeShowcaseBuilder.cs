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
            Directory.CreateDirectory(SceneRoot);
            var bone = Material("Bone", new Color(0.88f, 0.82f, 0.68f), 0.05f, 0.25f);
            var cartilage = Material("Cartilage", new Color(0.2f, 0.55f, 0.72f), 0.0f, 0.4f);
            var muscle = Material("Muscle", new Color(0.48f, 0.08f, 0.1f), 0.0f, 0.28f);
            var diaphragm = Material("Diaphragm", new Color(0.42f, 0.14f, 0.3f), 0.0f, 0.32f);
            var skin = TransparentMaterial("Skin", new Color(0.82f, 0.43f, 0.35f, 0.11f));
            var target = Material("Target", new Color(0.05f, 0.95f, 0.78f), 0.0f, 0.65f);
            var tissue = Material("InteractiveTissue", new Color(0.54f, 0.06f, 0.09f), 0.0f, 0.32f);
            var tool = Material("TrainingTool", new Color(0.65f, 0.72f, 0.78f), 0.65f, 0.7f);

            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            RenderSettings.ambientLight = new Color(0.18f, 0.22f, 0.27f);

            var anatomy = new GameObject("Layered Chest Anatomy");
            anatomy.transform.rotation = Quaternion.Euler(-90f, 0f, 0f);
            anatomy.transform.position = new Vector3(0f, -1.23f, 0f);

            foreach (var file in AnatomyFiles)
            {
                var assetPath = AnatomyRoot + "/" + file;
                var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(assetPath);
                if (prefab == null)
                {
                    throw new InvalidOperationException("Unity could not import " + file);
                }
                var instance = PrefabUtility.InstantiatePrefab(prefab, anatomy.transform) as GameObject;
                instance.name = FriendlyName(file);
                AssignMaterial(instance, MaterialFor(file, bone, cartilage, muscle, diaphragm, skin));
            }

            var simulation = new GameObject("Surge Prep Simulation");
            simulation.transform.position = new Vector3(-0.105f, 0.005f, 0.215f);
            simulation.transform.rotation = Quaternion.Euler(90f, 0f, 0f);
            var renderer = simulation.AddComponent<SimulationSceneRenderer>();
            var stream = simulation.AddComponent<ScalpelStreamClient>();
            var hud = simulation.AddComponent<ChestTubeShowcaseHud>();
            SetObject(renderer, "tissueMaterial", tissue);
            SetObject(renderer, "toolMaterial", tool);
            SetObject(stream, "sceneRenderer", renderer);
            SetObject(hud, "sceneRenderer", renderer);
            CreateTargetGuide(simulation.transform, target);

            CreateCamera();
            CreateLighting();

            var scenePath = SceneRoot + "/ChestTubeShowcase.unity";
            EditorSceneManager.SaveScene(scene, scenePath);
            Selection.activeGameObject = simulation;
            EditorGUIUtility.PingObject(AssetDatabase.LoadAssetAtPath<SceneAsset>(scenePath));
            Debug.Log(
                "Surge Prep showcase created. Paste an active session ID into " +
                "ScalpelStreamClient, then enter Play Mode."
            );
        }

        private static void CreateCamera()
        {
            var cameraObject = new GameObject("Main Camera");
            cameraObject.tag = "MainCamera";
            var camera = cameraObject.AddComponent<Camera>();
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(0.018f, 0.03f, 0.045f);
            camera.fieldOfView = 38f;
            camera.nearClipPlane = 0.01f;
            cameraObject.transform.position = new Vector3(0f, 0.02f, 0.62f);
            cameraObject.transform.LookAt(new Vector3(0f, 0.0f, 0.04f));
            cameraObject.AddComponent<AudioListener>();
        }

        private static void CreateLighting()
        {
            var key = new GameObject("Clinical Key Light");
            var keyLight = key.AddComponent<Light>();
            keyLight.type = LightType.Directional;
            keyLight.intensity = 1.25f;
            keyLight.color = new Color(0.86f, 0.93f, 1f);
            key.transform.rotation = Quaternion.Euler(35f, -25f, 0f);

            var fill = new GameObject("Warm Fill Light");
            var fillLight = fill.AddComponent<Light>();
            fillLight.type = LightType.Point;
            fillLight.intensity = 3.5f;
            fillLight.range = 1.5f;
            fillLight.color = new Color(1f, 0.62f, 0.48f);
            fill.transform.position = new Vector3(-0.35f, 0.22f, 0.45f);
        }

        private static void CreateTargetGuide(Transform parent, Material material)
        {
            var guide = new GameObject("Illustrative target region - instructor review required");
            guide.transform.SetParent(parent, false);
            guide.transform.localPosition = new Vector3(0f, 0.002f, 0f);
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
