using System;
using System.Collections.Concurrent;
using System.Diagnostics;
using System.Net.Http;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;

namespace SurgePrep
{
    /// <summary>
    /// Pose-only keyboard input. Samples still travel Unity -> controller -> API -> SOFA.
    /// </summary>
    public sealed class UnityManualDemoClient : MonoBehaviour
    {
        private static readonly float[] IdentityTransform =
        {
            1, 0, 0, 0,
            0, 1, 0, 0,
            0, 0, 1, 0,
            0, 0, 0, 1
        };

        [SerializeField] private string controllerUrl = "http://localhost:8100";
        [SerializeField] private SimulationSceneRenderer sceneRenderer;
        [SerializeField, Min(1f)] private float movementSpeedMmPerSecond = 24f;
        [SerializeField] private Camera sceneCamera;
        // Optional AprilTag + FSR scalpel. When it is sending, it replaces WASD.
        [SerializeField] private TagFsrInput tagInput;

        private readonly ConcurrentQueue<string> received = new ConcurrentQueue<string>();
        private readonly object stateLock = new object();
        private CancellationTokenSource cancellation;
        private ClientWebSocket socket;
        private HttpClient http;
        private float xMm;
        private float yMm = 12f;
        private float zMm;
        // SOFA/right-handed millimetres: 40° about +X lays the handle back
        // so the CAD blade meets the chest instead of standing as a needle.
        private static readonly QuaternionDto IncisionHold = new QuaternionDto
        {
            qx = 0.34202014f,
            qy = 0f,
            qz = 0f,
            qw = 0.93969262f
        };
        private string toolId = "scalpel";
        private long sequence;
        private string calibrationId;
        private string sessionId;
        private Stopwatch clock;
        private float resetArmedUntil;
        private bool hardwareActive;
        private float hardwareForceN;
        private bool hardwareContact;
        private Quaternion hardwareOrientation = Quaternion.identity;
        private bool hardwareHasOrientation;
        private float hardwareQuality = 1f;
        private bool hardwareSourceHealthy = true;
        private bool hardwareForceMeasurementValid;
        private string hardwareDeviceId = "unity-manual-demo";
        private TrackedToolInput[] trackedInputs;

        public bool Connected => socket != null && socket.State == WebSocketState.Open;
        public string SessionId => sessionId;
        public string Status { get; private set; } = "Starting controller session…";
        public string SimulationBackend { get; private set; } = "unknown";
        public string ToolId => toolId;
        public bool SofaNative => SimulationBackend == "sofa-native";

        private async void OnEnable()
        {
            cancellation = new CancellationTokenSource();
            http = new HttpClient { BaseAddress = new Uri(controllerUrl.TrimEnd('/') + "/") };
            try
            {
                await ReadHealth(cancellation.Token);
                await CreateSession(cancellation.Token);
                await StreamSamples(cancellation.Token);
            }
            catch (OperationCanceledException)
            {
            }
            catch (Exception error)
            {
                Status = SimulationBackend == "sofa-native"
                    ? "Controller unavailable"
                    : "SOFA OFFLINE — start scripts/start-showcase.sh";
                UnityEngine.Debug.LogError($"Unity manual demo failed: {error.Message}");
            }
        }

        private void Update()
        {
            UpdateKeyboardState();
            Update_TagFsr();
            string latest = null;
            while (received.TryDequeue(out var payload))
            {
                latest = payload;
            }
            if (latest == null || sceneRenderer == null)
            {
                return;
            }
            var snapshot = JsonUtility.FromJson<SimulationSnapshotDto>(latest);
            if (snapshot != null && ContractCompatibility.Accepts(snapshot.contractVersion))
            {
                if (!string.IsNullOrEmpty(snapshot.simulationBackend))
                {
                    SimulationBackend = snapshot.simulationBackend;
                    if (SimulationBackend != "sofa-native")
                    {
                        Status = "SOFA OFFLINE";
                    }
                }
                if (snapshot.sessionDegraded)
                {
                    Status = "SOFA stream recovering…";
                }
                sceneRenderer.SetTarget(snapshot);
            }
        }

        private void Update_TagFsr()
        {
            if (trackedInputs == null || trackedInputs.Length == 0)
            {
                trackedInputs = GetComponents<TrackedToolInput>();
            }
            TrackedToolInput activeInput = null;
            foreach (var candidate in trackedInputs)
            {
                if (candidate != null && candidate.isActiveAndEnabled && candidate.HasSignal)
                {
                    activeInput = candidate;
                    break;
                }
            }
            if (activeInput == null && tagInput != null && tagInput.HasSignal)
            {
                activeInput = tagInput;
            }
            var sample = default(TrackedToolSample);
            var hasSample = activeInput != null && activeInput.TryRead(out sample);

            lock (stateLock)
            {
                hardwareActive = hasSample;
                if (!hardwareActive)
                {
                    hardwareForceN = 0f;
                    hardwareContact = false;
                    hardwareHasOrientation = false;
                    hardwareForceMeasurementValid = false;
                    return;
                }
                xMm = sample.PositionMm.x;
                yMm = sample.PositionMm.y;
                zMm = sample.PositionMm.z;
                hardwareOrientation = sample.OrientationApi;
                hardwareHasOrientation = sample.HasOrientation;
                hardwareForceN = sample.ForceN;
                hardwareContact = sample.Contact;
                hardwareQuality = sample.Quality;
                hardwareSourceHealthy = sample.SourceHealthy;
                hardwareForceMeasurementValid = sample.ForceMeasurementValid;
                hardwareDeviceId = string.IsNullOrEmpty(sample.DeviceId)
                    ? "tracked-training-tool"
                    : sample.DeviceId;
                Status = sample.Status;
            }
        }

        private void UpdateKeyboardState()
        {
            var camera = sceneCamera != null ? sceneCamera : Camera.main;
            var horizontal = 0f;
            var vertical = 0f;
            if (ShowcaseInput.Held(KeyCode.A) || ShowcaseInput.Held(KeyCode.LeftArrow)) horizontal -= 1f;
            if (ShowcaseInput.Held(KeyCode.D) || ShowcaseInput.Held(KeyCode.RightArrow)) horizontal += 1f;
            if (ShowcaseInput.Held(KeyCode.S) || ShowcaseInput.Held(KeyCode.DownArrow)) vertical -= 1f;
            if (ShowcaseInput.Held(KeyCode.W) || ShowcaseInput.Held(KeyCode.UpArrow)) vertical += 1f;
            var raise = 0f;
            if (ShowcaseInput.Held(KeyCode.Q)) raise += 1f;
            if (ShowcaseInput.Held(KeyCode.E)) raise -= 1f;

            var world = Vector3.zero;
            var speedMm = movementSpeedMmPerSecond;
            if (camera != null)
            {
                var right = Vector3.ProjectOnPlane(camera.transform.right, Vector3.up);
                var forward = Vector3.ProjectOnPlane(camera.transform.forward, Vector3.up);
                if (right.sqrMagnitude < 0.04f)
                {
                    right = Vector3.Cross(Vector3.up, forward);
                }
                if (forward.sqrMagnitude < 0.04f)
                {
                    forward = Vector3.Cross(right, Vector3.up);
                }
                if (right.sqrMagnitude < 0.04f) right = Vector3.right;
                if (forward.sqrMagnitude < 0.04f) forward = Vector3.forward;
                right.Normalize();
                forward.Normalize();
                if (!IsFinite(right) || !IsFinite(forward))
                {
                    right = Vector3.right;
                    forward = Vector3.forward;
                }
                var viewMetres = Vector3.Distance(
                    camera.transform.position, new Vector3(0.12f, 1.05f, 0.04f)
                );
                speedMm = movementSpeedMmPerSecond * Mathf.Clamp(viewMetres / 0.72f, 1f, 6f);
                world = (right * horizontal + forward * vertical)
                    * (speedMm * CoordinateFrame.MillimetresToMetres)
                    * Time.unscaledDeltaTime;
            }
            var api = CoordinateFrame.InverseDeltaMetres(world);
            if (!IsFinite(api))
            {
                api = Vector3.zero;
            }
            lock (stateLock)
            {
                xMm += api.x;
                zMm += api.z;
                // Keyboard testing can traverse the registered torso. Only
                // the subtle surgical field is carvable.
                xMm = Mathf.Clamp(xMm, -150f, 150f);
                zMm = Mathf.Clamp(zMm, -260f, 260f);
                yMm += raise * speedMm * Time.unscaledDeltaTime;
                // Keyboard sandbox only. Calibrated hardware pose is not clamped
                // here; SOFA contact, ribs, and the tissue volume stop the tool.
                yMm = Mathf.Clamp(yMm, -80f, 40f);
                if (!IsFinite(xMm) || !IsFinite(yMm) || !IsFinite(zMm))
                {
                    xMm = 0f;
                    yMm = 12f;
                    zMm = 0f;
                }
                if (ShowcaseInput.Pressed(KeyCode.Alpha1)) toolId = "scalpel";
                if (ShowcaseInput.Pressed(KeyCode.Alpha2)) toolId = "blunt-dissector";
                if (ShowcaseInput.Pressed(KeyCode.Alpha3)) toolId = "chest-tube";
                if (ShowcaseInput.Pressed(KeyCode.R))
                {
                    if (Time.unscaledTime <= resetArmedUntil)
                    {
                        xMm = 0f;
                        yMm = 12f;
                        zMm = 0f;
                        toolId = "scalpel";
                        resetArmedUntil = 0f;
                        Status = "Attempt reset";
                    }
                    else
                    {
                        resetArmedUntil = Time.unscaledTime + 2f;
                        Status = "Press R again to reset";
                    }
                }
            }
        }

        private async Task ReadHealth(CancellationToken token)
        {
            try
            {
                using (var response = await http.GetAsync("health", token))
                {
                    var payload = await response.Content.ReadAsStringAsync();
                    var health = JsonUtility.FromJson<HealthDto>(payload);
                    if (health != null && health.api != null && !string.IsNullOrEmpty(health.api.simulation))
                    {
                        SimulationBackend = health.api.simulation;
                    }
                }
            }
            catch (Exception)
            {
                SimulationBackend = "sofa-offline";
            }
            if (SimulationBackend != "sofa-native")
            {
                Status = "SOFA OFFLINE";
            }
        }

        private async Task CreateSession(CancellationToken token)
        {
            Status = SofaNative ? "Validating demo calibration…" : "SOFA OFFLINE";
            var calibration = await Post<CalibrationCreateDto, CalibrationDto>(
                "v1/calibrations",
                new CalibrationCreateDto
                {
                    deviceId = "unity-manual-demo",
                    transform = IdentityTransform,
                    rmsErrorMm = 0.1f
                },
                token
            );
            calibrationId = calibration.calibrationId;
            var session = await Post<SessionCreateDto, SessionDto>(
                "v1/sessions",
                new SessionCreateDto
                {
                    exerciseId = "chest-tube-access-demo",
                    calibrationId = calibrationId,
                    toolId = "scalpel",
                    deviceId = "unity-manual-demo"
                },
                token
            );
            sessionId = session.sessionId;
            clock = Stopwatch.StartNew();
            Status = SofaNative ? "Connecting to native SOFA…" : "SOFA OFFLINE";
        }

        private async Task<TResponse> Post<TRequest, TResponse>(
            string path, TRequest body, CancellationToken token
        )
        {
            var content = new StringContent(JsonUtility.ToJson(body), Encoding.UTF8, "application/json");
            using (var response = await http.PostAsync(path, content, token))
            {
                var payload = await response.Content.ReadAsStringAsync();
                if (!response.IsSuccessStatusCode)
                {
                    throw new InvalidOperationException($"{path} returned {(int)response.StatusCode}: {payload}");
                }
                return JsonUtility.FromJson<TResponse>(payload);
            }
        }

        private async Task StreamSamples(CancellationToken token)
        {
            socket = new ClientWebSocket();
            var websocketBase = controllerUrl.StartsWith("https://", StringComparison.OrdinalIgnoreCase)
                ? "wss://" + controllerUrl.Substring(8)
                : "ws://" + controllerUrl.Substring(controllerUrl.IndexOf("://", StringComparison.Ordinal) + 3);
            var uri = new Uri($"{websocketBase.TrimEnd('/')}/v1/sessions/{sessionId}/hardware-stream");
            await socket.ConnectAsync(uri, token);
            Status = SofaNative
                ? "LIVE — WASD fallback; calibrated hardware uses the same pose contract"
                : "SOFA OFFLINE";

            while (!token.IsCancellationRequested && socket.State == WebSocketState.Open)
            {
                var sample = NextSample();
                var bytes = Encoding.UTF8.GetBytes(JsonUtility.ToJson(sample));
                await socket.SendAsync(
                    new ArraySegment<byte>(bytes), WebSocketMessageType.Text, true, token
                );
                received.Enqueue(await ReceiveMessage(token));
                await Task.Delay(33, token);
            }
        }

        private ToolSampleDto NextSample()
        {
            float sampleX;
            float sampleY;
            float sampleZ;
            string sampleTool;
            bool hardware;
            float sampleForce;
            bool sampleContact;
            Quaternion sampleOrientation;
            bool sampleHasOrientation;
            float sampleQuality;
            bool sampleSourceHealthy;
            bool sampleForceValid;
            string sampleDeviceId;
            lock (stateLock)
            {
                sampleX = xMm;
                sampleY = yMm;
                sampleZ = zMm;
                sampleTool = toolId;
                hardware = hardwareActive;
                sampleForce = hardwareForceN;
                sampleContact = hardwareContact;
                sampleOrientation = hardwareOrientation;
                sampleHasOrientation = hardwareHasOrientation;
                sampleQuality = hardwareQuality;
                sampleSourceHealthy = hardwareSourceHealthy;
                sampleForceValid = hardwareForceMeasurementValid;
                sampleDeviceId = hardwareDeviceId;
            }
            var orientation = hardware && sampleHasOrientation
                ? new QuaternionDto
                {
                    qx = sampleOrientation.x,
                    qy = sampleOrientation.y,
                    qz = sampleOrientation.z,
                    qw = sampleOrientation.w
                }
                : IncisionHold;
            return new ToolSampleDto
            {
                contractVersion = "1.1",
                sessionId = sessionId,
                toolId = sampleTool,
                deviceId = hardware ? sampleDeviceId : "unity-manual-demo",
                calibrationId = calibrationId,
                sequence = sequence++,
                timestampMs = clock.ElapsedMilliseconds,
                positionMm = new Vector3Dto { x = sampleX, y = sampleY, z = sampleZ },
                orientation = orientation,
                forceN = hardware ? sampleForce : 0f,
                contact = hardware && sampleContact,
                quality = hardware ? sampleQuality : 1f,
                sourceHealthy = hardware ? sampleSourceHealthy : true,
                inputMode = hardware ? "calibrated-hardware" : "pose-only",
                forceMeasurementValid = hardware && sampleForceValid
            };
        }

        private async Task<string> ReceiveMessage(CancellationToken token)
        {
            var buffer = new byte[1024 * 1024];
            var count = 0;
            WebSocketReceiveResult result;
            do
            {
                result = await socket.ReceiveAsync(
                    new ArraySegment<byte>(buffer, count, buffer.Length - count), token
                );
                count += result.Count;
                if (count == buffer.Length && !result.EndOfMessage)
                {
                    throw new InvalidOperationException("Simulation snapshot exceeds 1 MiB");
                }
            } while (!result.EndOfMessage);
            return Encoding.UTF8.GetString(buffer, 0, count);
        }

        private static bool IsFinite(float value)
        {
            return !float.IsNaN(value) && !float.IsInfinity(value);
        }

        private static bool IsFinite(Vector3 value)
        {
            return IsFinite(value.x) && IsFinite(value.y) && IsFinite(value.z);
        }

        private async void OnDisable()
        {
            cancellation?.Cancel();
            socket?.Dispose();
            socket = null;
            if (http != null && !string.IsNullOrEmpty(sessionId))
            {
                try
                {
                    using (var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(2)))
                    using (await http.PostAsync($"v1/sessions/{sessionId}/complete", null, timeout.Token))
                    {
                    }
                }
                catch (Exception)
                {
                }
            }
            http?.Dispose();
            http = null;
            cancellation?.Dispose();
            cancellation = null;
        }
    }
}
