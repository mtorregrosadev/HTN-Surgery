using UnityEditor;
using UnityEditor.PackageManager;
using UnityEditor.PackageManager.Requests;
using UnityEngine;

namespace SurgePrep.Editor
{
    public static class AprilTagPackageInstaller
    {
        private const string PackageUrl =
            "https://github.com/keijiro/jp.keijiro.apriltag.git?path=/Packages/jp.keijiro.apriltag#1.0.3";

        private static AddRequest request;

        [MenuItem("Surge Prep/Install AprilTag Stylus Tracking")]
        public static void Install()
        {
            if (request != null && !request.IsCompleted)
            {
                Debug.Log("AprilTag package installation is already running.");
                return;
            }
            request = Client.Add(PackageUrl);
            EditorApplication.update += Poll;
            Debug.Log("Installing jp.keijiro.apriltag 1.0.3…");
        }

        private static void Poll()
        {
            if (request == null || !request.IsCompleted) return;
            EditorApplication.update -= Poll;
            if (request.Status == StatusCode.Success)
            {
                Debug.Log(
                    "AprilTag tracking installed. After scripts compile, run " +
                    "Surge Prep > Build Chest-Tube Showcase again."
                );
            }
            else
            {
                Debug.LogError("AprilTag installation failed: " + request.Error?.message);
            }
            request = null;
        }
    }
}
