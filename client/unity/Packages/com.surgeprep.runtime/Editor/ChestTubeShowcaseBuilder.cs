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
            var bone = Material("Bone", new Color(0.86f, 0.8f, 0.7f), 0.02f, 0.28f);
            var cartilage = Material("Cartilage", new Color(0.72f, 0.78f, 0.74f), 0.0f, 0.42f);
            var muscle = Material("Muscle", new Color(0.42f, 0.12f, 0.14f), 0.0f, 0.34f);
            var diaphragm = Material("Diaphragm", new Color(0.4f, 0.16f, 0.22f), 0.0f, 0.34f);
            var skin = Material("SiliconeSkin", new Color(0.83f, 0.66f, 0.56f), 0.0f, 0.38f);
            var target = Material("Target", new Color(0.2f, 0.55f, 0.62f), 0.0f, 0.45f);
            var tissue = Material("InteractiveTissue", new Color(0.78f, 0.48f, 0.42f), 0.0f, 0.28f);
            var fat = Material("Subcutaneous", new Color(0.9f, 0.78f, 0.55f), 0.0f, 0.22f);
            var pleura = Material("Pleura", new Color(0.72f, 0.7f, 0.68f), 0.0f, 0.5f);
            var incision = Material("IncisionChannel", new Color(0.35f, 0.08f, 0.08f), 0.0f, 0.55f);
            var blood = TransparentMaterial("BloodDecal", new Color(0.35f, 0.04f, 0.05f, 0.55f));
            var pressure = TransparentMaterial("PressureIndicator", new Color(0.05f, 1f, 0.65f, 0.7f));
            var tool = Material("TrainingTool", new Color(0.72f, 0.74f, 0.76f), 0.7f, 0.55f);
            var drape = Material("SurgicalDrape", new Color(0.16f, 0.32f, 0.55f), 0.0f, 0.18f);
            var metal = Material("BrushedMetal", new Color(0.62f, 0.64f, 0.66f), 0.85f, 0.55f);
            var steel = Material("Stainless", new Color(0.75f, 0.76f, 0.78f), 0.9f, 0.62f);
            var plastic = Material("ClinicalPlastic", new Color(0.9f, 0.91f, 0.92f), 0.05f, 0.4f);
            var rubber = Material("Rubber", new Color(0.12f, 0.12f, 0.13f), 0.0f, 0.18f);
            var wall = Material("OrWall", new Color(0.86f, 0.88f, 0.9f), 0.0f, 0.22f);
            var floor = Material("OrFloor", new Color(0.55f, 0.6f, 0.63f), 0.15f, 0.35f);
            var mattress = Material("Mattress", new Color(0.93f, 0.93f, 0.94f), 0.0f, 0.2f);

            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            RenderSettings.ambientLight = new Color(0.42f, 0.44f, 0.48f);
            RenderSettings.ambientMode = UnityEngine.Rendering.AmbientMode.Trilight;
            RenderSettings.ambientSkyColor = new Color(0.55f, 0.58f, 0.62f);
            RenderSettings.ambientEquatorColor = new Color(0.4f, 0.42f, 0.44f);
            RenderSettings.ambientGroundColor = new Color(0.22f, 0.22f, 0.24f);
            RenderSettings.fog = true;
            RenderSettings.fogColor = new Color(0.72f, 0.75f, 0.78f);
            RenderSettings.fogDensity = 0.012f;

            var room = CreateOperatingRoom(wall, floor, metal, steel, plastic, rubber, mattress, drape);
            var tableTop = room.transform.Find("RegistrationAnchor_Table");

            var mannequin = new GameObject("Supine training mannequin");
            mannequin.transform.SetParent(tableTop, false);
            var skinLayer = Layer("Silicone mannequin shell", mannequin.transform);
            CreateMannequinShell(skinLayer, skin);

            var anatomy = new GameObject("Registered internal anatomy");
            anatomy.transform.SetParent(mannequin.transform, false);
            // BodyParts3D is Z-up. Keep anatomical Z along the table and flip
            // anterior Y upward, with the feet near the table's negative end.
            anatomy.transform.localRotation = Quaternion.Euler(0f, 0f, 180f);
            anatomy.transform.localPosition = new Vector3(0f, 0.13f, -0.82f);
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
            }
            muscleLayer.gameObject.SetActive(false);
            boneLayer.gameObject.SetActive(false);
            cartilageLayer.gameObject.SetActive(false);
            diaphragmLayer.gameObject.SetActive(false);
            CreateDrapes(tableTop, drape);

            var window = new GameObject("RegistrationAnchor_ProcedureWindow");
            window.transform.SetParent(tableTop, false);
            window.transform.localPosition = new Vector3(0.205f, 0.31f, 0.18f);
            window.transform.localRotation = Quaternion.identity;

            var simulation = new GameObject("RegistrationAnchor_SimulationPatch");
            simulation.transform.SetParent(window.transform, false);
            var renderer = simulation.AddComponent<SimulationSceneRenderer>();
            var stream = simulation.AddComponent<ScalpelStreamClient>();
            stream.enabled = false;
            var manualDemo = simulation.AddComponent<UnityManualDemoClient>();
            var hud = simulation.AddComponent<ChestTubeShowcaseHud>();
            SetObject(renderer, "tissueMaterial", tissue);
            SetObject(renderer, "subcutaneousMaterial", fat);
            SetObject(renderer, "muscleMaterial", muscle);
            SetObject(renderer, "pleuraMaterial", pleura);
            SetObject(renderer, "incisionMaterial", incision);
            SetObject(renderer, "toolMaterial", tool);
            SetObject(renderer, "pressureIndicatorMaterial", pressure);
            SetObject(renderer, "bloodMaterial", blood);
            SetObject(stream, "sceneRenderer", renderer);
            SetObject(manualDemo, "sceneRenderer", renderer);
            SetObject(hud, "sceneRenderer", renderer);
            SetObject(hud, "manualDemo", manualDemo);
            CreateTargetGuide(simulation.transform, target);
            CreateInstrumentHome(room.transform, tool);

            var camera = CreateCamera();
            CreateLighting(window.transform);
            CreateReflectionProbe(tableTop.position);

            var roomFocus = new GameObject("RegistrationAnchor_RoomFocus");
            roomFocus.transform.position = tableTop.position + Vector3.up * 0.2f;
            var experienceObject = new GameObject("Interactive showcase controls");
            var experience = experienceObject.AddComponent<SurgePrep.ShowcaseExperienceController>();
            SetObject(experience, "sceneCamera", camera);
            SetObject(experience, "chestFocus", window.transform);
            SetObject(experience, "targetFocus", window.transform);
            SetObject(experience, "roomFocus", roomFocus.transform);
            SetObject(experience, "skinLayer", skinLayer.gameObject);
            SetObject(experience, "muscleLayer", muscleLayer.gameObject);
            SetObject(experience, "boneLayer", boneLayer.gameObject);
            SetObject(experience, "cartilageLayer", cartilageLayer.gameObject);
            SetObject(experience, "diaphragmLayer", diaphragmLayer.gameObject);
            SetObject(manualDemo, "sceneCamera", camera);

            var scenePath = SceneRoot + "/ChestTubeShowcase.unity";
            EditorSceneManager.SaveScene(scene, scenePath);
            Selection.activeGameObject = simulation;
            EditorGUIUtility.PingObject(AssetDatabase.LoadAssetAtPath<SceneAsset>(scenePath));
            Debug.Log(
                "Surge Prep OR showcase created. Run scripts/start-showcase.sh, then Play Mode."
            );
        }

        private static GameObject CreateOperatingRoom(
            Material wall, Material floor, Material metal, Material steel,
            Material plastic, Material rubber, Material mattress, Material drape
        )
        {
            var room = new GameObject("Modern Operating Room");
            Cube("Floor", room.transform, new Vector3(0f, 0f, 0f), new Vector3(8f, 0.08f, 8f), floor);
            Cube("Ceiling", room.transform, new Vector3(0f, 3.05f, 0f), new Vector3(8f, 0.08f, 8f), wall);
            Cube("Back wall", room.transform, new Vector3(0f, 1.5f, -4f), new Vector3(8f, 3f, 0.1f), wall);
            Cube("Front wall", room.transform, new Vector3(0f, 1.5f, 4f), new Vector3(8f, 3f, 0.1f), wall);
            Cube("Left wall", room.transform, new Vector3(-4f, 1.5f, 0f), new Vector3(0.1f, 3f, 8f), wall);
            Cube("Right wall", room.transform, new Vector3(4f, 1.5f, 0f), new Vector3(0.1f, 3f, 8f), wall);
            Cube("Wall panel", room.transform, new Vector3(-3.9f, 1.4f, 0f), new Vector3(0.04f, 1.6f, 2.4f), plastic);
            Cube("Outlet bank", room.transform, new Vector3(-3.88f, 0.9f, 1.4f), new Vector3(0.04f, 0.18f, 0.4f), metal);

            var table = new GameObject("RegistrationAnchor_Table");
            table.transform.SetParent(room.transform, false);
            table.transform.localPosition = new Vector3(0f, 0.92f, 0f);
            Cube("Table base", table.transform, new Vector3(0f, -0.55f, 0f), new Vector3(0.42f, 0.7f, 0.42f), metal);
            Cube("Table column", table.transform, new Vector3(0f, -0.22f, 0f), new Vector3(0.16f, 0.4f, 0.16f), steel);
            Cube("Table top", table.transform, new Vector3(0f, 0f, 0f), new Vector3(0.55f, 0.06f, 1.9f), steel);
            Cube("Mattress", table.transform, new Vector3(0f, 0.06f, 0f), new Vector3(0.5f, 0.07f, 1.85f), mattress);
            Cube("Side rail L", table.transform, new Vector3(-0.28f, 0.02f, 0f), new Vector3(0.03f, 0.04f, 1.6f), metal);
            Cube("Side rail R", table.transform, new Vector3(0.28f, 0.02f, 0f), new Vector3(0.03f, 0.04f, 1.6f), metal);
            Cube("Table control", table.transform, new Vector3(0.22f, -0.18f, 0.55f), new Vector3(0.12f, 0.04f, 0.18f), plastic);

            Cube("Instrument trolley", room.transform, new Vector3(1.15f, 0.72f, 0.35f), new Vector3(0.55f, 0.04f, 0.4f), steel);
            Cube("Trolley leg A", room.transform, new Vector3(0.95f, 0.35f, 0.2f), new Vector3(0.04f, 0.7f, 0.04f), metal);
            Cube("Trolley leg B", room.transform, new Vector3(1.35f, 0.35f, 0.5f), new Vector3(0.04f, 0.7f, 0.04f), metal);
            Cube("Anesthesia cart", room.transform, new Vector3(-1.35f, 0.7f, -0.4f), new Vector3(0.5f, 1.2f, 0.42f), plastic);
            Cube("Monitor", room.transform, new Vector3(-1.15f, 1.55f, -0.15f), new Vector3(0.42f, 0.28f, 0.06f), metal);
            Cube("Monitor screen", room.transform, new Vector3(-1.15f, 1.55f, -0.12f), new Vector3(0.38f, 0.24f, 0.01f), rubber);
            Cube("Cabinet", room.transform, new Vector3(3.4f, 0.9f, -2.4f), new Vector3(0.9f, 1.8f, 1.4f), wall);
            Cube("Work surface", room.transform, new Vector3(2.4f, 0.9f, -3.4f), new Vector3(1.8f, 0.06f, 0.55f), steel);
            Cube("Boom arm", room.transform, new Vector3(0.2f, 2.55f, 0.1f), new Vector3(1.8f, 0.05f, 0.05f), metal);
            return room;
        }

        private static void CreateMannequinShell(Transform parent, Material skin)
        {
            Capsule(
                "Silicone torso", parent,
                new Vector3(0f, 0.20f, 0.18f),
                new Vector3(0.48f, 0.54f, 0.31f),
                Quaternion.Euler(90f, 0f, 0f), skin
            );
            Sphere(
                "Silicone head", parent,
                new Vector3(0f, 0.19f, 0.79f),
                new Vector3(0.25f, 0.22f, 0.29f), skin
            );
            Capsule(
                "Left arm", parent,
                new Vector3(-0.31f, 0.15f, 0.08f),
                new Vector3(0.12f, 0.40f, 0.12f),
                Quaternion.Euler(90f, 0f, 0f), skin
            );
            Capsule(
                "Right arm", parent,
                new Vector3(0.31f, 0.15f, 0.08f),
                new Vector3(0.12f, 0.40f, 0.12f),
                Quaternion.Euler(90f, 0f, 0f), skin
            );
            Capsule(
                "Left leg", parent,
                new Vector3(-0.13f, 0.14f, -0.52f),
                new Vector3(0.17f, 0.48f, 0.17f),
                Quaternion.Euler(90f, 0f, 0f), skin
            );
            Capsule(
                "Right leg", parent,
                new Vector3(0.13f, 0.14f, -0.52f),
                new Vector3(0.17f, 0.48f, 0.17f),
                Quaternion.Euler(90f, 0f, 0f), skin
            );
        }

        private static void CreateDrapes(Transform table, Material drape)
        {
            var root = new GameObject("Fitted surgical drapes");
            root.transform.SetParent(table, false);
            const float y = 0.305f;
            // Lower-body blanket plus four fitted pieces around a
            // 120 x 110 mm right lateral-chest procedure window.
            Cube(
                "Lower body drape", root.transform,
                new Vector3(0f, y, -0.48f), new Vector3(0.70f, 0.018f, 0.72f), drape
            );
            Cube(
                "Medial chest drape", root.transform,
                new Vector3(-0.105f, y, 0.24f), new Vector3(0.47f, 0.018f, 0.48f), drape
            );
            Cube(
                "Lateral outer drape", root.transform,
                new Vector3(0.335f, y, 0.24f), new Vector3(0.13f, 0.018f, 0.48f), drape
            );
            Cube(
                "Window cranial drape", root.transform,
                new Vector3(0.215f, y, 0.395f), new Vector3(0.11f, 0.018f, 0.17f), drape
            );
            Cube(
                "Window caudal drape", root.transform,
                new Vector3(0.215f, y, 0.065f), new Vector3(0.11f, 0.018f, 0.17f), drape
            );
        }

        private static void CreateInstrumentHome(Transform parent, Material tool)
        {
            var home = new GameObject("RegistrationAnchor_InstrumentHome");
            home.transform.SetParent(parent, false);
            home.transform.localPosition = new Vector3(1.15f, 0.77f, 0.35f);
            Cube("Tray scalpel", home.transform, new Vector3(-0.12f, 0.02f, 0f), new Vector3(0.18f, 0.012f, 0.025f), tool);
            Cube("Tray dissector", home.transform, new Vector3(0.08f, 0.02f, 0f), new Vector3(0.18f, 0.012f, 0.025f), tool);
            Capsule(
                "Tray tube", home.transform,
                new Vector3(0f, 0.025f, 0.10f), new Vector3(0.025f, 0.20f, 0.025f),
                Quaternion.Euler(0f, 0f, 90f), tool
            );
        }

        private static Camera CreateCamera()
        {
            var cameraObject = new GameObject("Main Camera");
            cameraObject.tag = "MainCamera";
            var camera = cameraObject.AddComponent<Camera>();
            camera.clearFlags = CameraClearFlags.Skybox;
            camera.backgroundColor = new Color(0.62f, 0.66f, 0.7f);
            camera.fieldOfView = 42f;
            camera.nearClipPlane = 0.02f;
            camera.farClipPlane = 18f;
            cameraObject.transform.position = new Vector3(0.9f, 2.1f, 1.6f);
            cameraObject.transform.LookAt(new Vector3(0.12f, 1.05f, 0.04f));
            cameraObject.AddComponent<AudioListener>();
            return camera;
        }

        private static void CreateLighting(Transform window)
        {
            var key = new GameObject("Surgical lamp A");
            var keyLight = key.AddComponent<Light>();
            keyLight.type = LightType.Spot;
            keyLight.intensity = 3.4f;
            keyLight.range = 6f;
            keyLight.spotAngle = 42f;
            keyLight.color = new Color(0.98f, 0.97f, 0.94f);
            keyLight.shadows = LightShadows.Soft;
            key.transform.position = window.position + new Vector3(0.15f, 1.35f, 0.35f);
            key.transform.LookAt(window.position);

            var lampB = new GameObject("Surgical lamp B");
            var fill = lampB.AddComponent<Light>();
            fill.type = LightType.Spot;
            fill.intensity = 2.2f;
            fill.range = 6f;
            fill.spotAngle = 48f;
            fill.color = new Color(0.95f, 0.96f, 1f);
            fill.shadows = LightShadows.Soft;
            lampB.transform.position = window.position + new Vector3(-0.45f, 1.4f, 0.2f);
            lampB.transform.LookAt(window.position);

            var ambient = new GameObject("OR ambient");
            var ambientLight = ambient.AddComponent<Light>();
            ambientLight.type = LightType.Directional;
            ambientLight.intensity = 0.35f;
            ambientLight.color = new Color(0.82f, 0.86f, 0.9f);
            ambientLight.shadows = LightShadows.Soft;
            ambient.transform.rotation = Quaternion.Euler(50f, -20f, 0f);
        }

        private static void CreateReflectionProbe(Vector3 centre)
        {
            var probeObject = new GameObject("OR reflection probe");
            probeObject.transform.position = centre + Vector3.up * 0.4f;
            var probe = probeObject.AddComponent<ReflectionProbe>();
            probe.size = new Vector3(6f, 3f, 6f);
            probe.mode = UnityEngine.Rendering.ReflectionProbeMode.Realtime;
            probe.refreshMode = UnityEngine.Rendering.ReflectionProbeRefreshMode.OnAwake;
        }

        private static void CreateTargetGuide(Transform parent, Material material)
        {
            var guide = new GameObject("Illustrative target corridor - instructor review required");
            guide.transform.SetParent(parent, false);
            guide.transform.localPosition = Vector3.zero;
            var line = guide.AddComponent<LineRenderer>();
            line.useWorldSpace = false;
            line.loop = true;
            line.positionCount = 4;
            line.startWidth = 0.0012f;
            line.endWidth = 0.0012f;
            line.sharedMaterial = material;
            line.SetPosition(0, new Vector3(-0.018f, 0.001f, -0.006f));
            line.SetPosition(1, new Vector3(0.018f, 0.001f, -0.006f));
            line.SetPosition(2, new Vector3(0.018f, 0.001f, 0.006f));
            line.SetPosition(3, new Vector3(-0.018f, 0.001f, 0.006f));
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

        private static GameObject Capsule(
            string name,
            Transform parent,
            Vector3 position,
            Vector3 scale,
            Quaternion rotation,
            Material material
        )
        {
            var capsule = GameObject.CreatePrimitive(PrimitiveType.Capsule);
            capsule.name = name;
            capsule.transform.SetParent(parent, false);
            capsule.transform.localPosition = position;
            capsule.transform.localRotation = rotation;
            capsule.transform.localScale = scale;
            capsule.GetComponent<MeshRenderer>().sharedMaterial = material;
            var collider = capsule.GetComponent<Collider>();
            if (collider != null)
            {
                UnityEngine.Object.DestroyImmediate(collider);
            }
            return capsule;
        }

        private static GameObject Sphere(
            string name,
            Transform parent,
            Vector3 position,
            Vector3 scale,
            Material material
        )
        {
            var sphere = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            sphere.name = name;
            sphere.transform.SetParent(parent, false);
            sphere.transform.localPosition = position;
            sphere.transform.localScale = scale;
            sphere.GetComponent<MeshRenderer>().sharedMaterial = material;
            var collider = sphere.GetComponent<Collider>();
            if (collider != null)
            {
                UnityEngine.Object.DestroyImmediate(collider);
            }
            return sphere;
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
