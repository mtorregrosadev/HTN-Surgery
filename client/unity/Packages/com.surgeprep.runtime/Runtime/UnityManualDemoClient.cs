using System;
using System.Collections.Concurrent;
using System.Diagnostics;
using System.IO;
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
        private const int SnapshotChunkBytes = 16 * 1024;
        private const int MaxSnapshotBytes = 4 * 1024 * 1024;

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
        private bool hasKeyboardMovement;
        private bool isSessionOwner;

        public bool Connected => socket != null && socket.State == WebSocketState.Open;
        public string SessionId => sessionId;
        public string Status { get; private set; } = "Starting controller session…";
        public string SimulationBackend { get; private set; } = "unknown";
        public string ToolId => toolId;
        public bool SofaNative => SimulationBackend == "sofa-native";

        private async void OnEnable()
        {
            var physicalStream = GetComponent<ScalpelStreamClient>();
            if (physicalStream != null && physicalStream.isActiveAndEnabled)
            {
                Status = "Physical scalpel stream selected";
                return;
            }
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
            string latest = null;
            while (received.TryDequeue(out var payload))
            {
                latest = payload;
            }
            if (latest == null || sceneRenderer == null)
            {
                return;
            }
            try
            {
                var snapshot = JsonUtility.FromJson<SimulationSnapshotDto>(latest);
                if (snapshot == null || !ContractCompatibility.Accepts(snapshot.contractVersion))
                {
                    return;
                }
                if (!string.IsNullOrEmpty(snapshot.sessionId)
                    && !string.IsNullOrEmpty(sessionId)
                    && snapshot.sessionId != sessionId)
                {
                    return;
                }
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

                // When keyboard is not being actively moved, mirror physical scalpel pose
                if (!hasKeyboardMovement && snapshot.tool != null && snapshot.tool.positionMm != null)
                {
                    lock (stateLock)
                    {
                        xMm = snapshot.tool.positionMm.x;
                        yMm = snapshot.tool.positionMm.y;
                        zMm = snapshot.tool.positionMm.z;
                    }
                }
            }
            catch (Exception error)
            {
                UnityEngine.Debug.LogWarning($"[UnityManualDemoClient] Ignoring invalid simulation snapshot: {error.Message}");
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

            hasKeyboardMovement = (horizontal != 0f || vertical != 0f || raise != 0f);

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
                    if (Time.unscaledTime < resetArmedUntil)
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
            Status = SofaNative ? "Connecting to active session…" : "SOFA OFFLINE";

            // 1. Check if there is already an active session (e.g. from physical scalpel tracker)
            try
            {
                using (var response = await http.GetAsync("v1/sessions/active", token))
                {
                    if (response.IsSuccessStatusCode)
                    {
                        var payload = await response.Content.ReadAsStringAsync();
                        var active = JsonUtility.FromJson<SessionDto>(payload);
                        if (active != null && !string.IsNullOrEmpty(active.sessionId))
                        {
                            sessionId = active.sessionId;
                            calibrationId = "calib-demo-default";
                            clock = Stopwatch.StartNew();
                            isSessionOwner = false;
                            Status = SofaNative ? "LIVE — Attached to physical scalpel session" : "SOFA OFFLINE";
                            UnityEngine.Debug.Log($"[UnityManualDemoClient] Auto-attached to active tracker session: {sessionId}");
                            return;
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                UnityEngine.Debug.LogWarning($"[UnityManualDemoClient] Could not query active session: {ex.Message}");
            }

            // 2. Fallback: create fresh session if none exists
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
            isSessionOwner = true;
            Status = SofaNative ? "LIVE — Calibrated session started" : "SOFA OFFLINE";
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
            sceneRenderer?.BindSession(sessionId);
            Status = SofaNative
                ? "LIVE — Keyboard fallback through Scalpel controller"
                : "SOFA OFFLINE";

            // The controller returns authoritative snapshots on this hardware-stream socket.
            _ = ReceiveClientStreamLoop(token);

            // Forward keyboard inputs through the controller's hardware ingress.
            while (!token.IsCancellationRequested && socket.State == WebSocketState.Open)
            {
                if (hasKeyboardMovement)
                {
                    var sample = NextSample();
                    try
                    {
                        var payload = Encoding.UTF8.GetBytes(JsonUtility.ToJson(sample));
                        await socket.SendAsync(
                            new ArraySegment<byte>(payload),
                            WebSocketMessageType.Text,
                            true,
                            token
                        );
                    }
                    catch (OperationCanceledException)
                    {
                        throw;
                    }
                    catch (Exception error)
                    {
                        UnityEngine.Debug.LogWarning(
                            $"[UnityManualDemoClient] Keyboard sample send failed: {error.Message}"
                        );
                        break;
                    }
                }
                await Task.Delay(33, token);
            }
        }

        private async Task ReceiveClientStreamLoop(CancellationToken token)
        {
            try
            {
                while (!token.IsCancellationRequested && socket != null && socket.State == WebSocketState.Open)
                {
                    var payload = await ReceiveTextMessage(socket, token);
                    if (payload == null)
                    {
                        break;
                    }
                    received.Enqueue(payload);
                }
            }
            catch (OperationCanceledException)
            {
            }
            catch (Exception ex)
            {
                UnityEngine.Debug.LogWarning($"[UnityManualDemoClient] Client stream receive loop ended: {ex.Message}");
            }
        }

        private static async Task<string> ReceiveTextMessage(
            ClientWebSocket clientSocket, CancellationToken token
        )
        {
            var buffer = new byte[SnapshotChunkBytes];
            using (var message = new MemoryStream())
            {
                while (true)
                {
                    var result = await clientSocket.ReceiveAsync(
                        new ArraySegment<byte>(buffer), token
                    );
                    if (result.MessageType == WebSocketMessageType.Close)
                    {
                        return null;
                    }
                    if (result.MessageType != WebSocketMessageType.Text)
                    {
                        throw new InvalidOperationException(
                            $"Unexpected WebSocket message type: {result.MessageType}"
                        );
                    }
                    message.Write(buffer, 0, result.Count);
                    if (message.Length > MaxSnapshotBytes)
                    {
                        throw new InvalidOperationException(
                            $"Simulation snapshot exceeds {MaxSnapshotBytes / (1024 * 1024)} MiB"
                        );
                    }
                    if (result.EndOfMessage)
                    {
                        return Encoding.UTF8.GetString(message.GetBuffer(), 0, (int)message.Length);
                    }
                }
            }
        }

        private ToolSampleDto NextSample()
        {
            float sampleX;
            float sampleY;
            float sampleZ;
            string sampleTool;
            lock (stateLock)
            {
                sampleX = xMm;
                sampleY = yMm;
                sampleZ = zMm;
                sampleTool = toolId;
            }
            return new ToolSampleDto
            {
                contractVersion = "1.1",
                sessionId = sessionId,
                toolId = sampleTool,
                deviceId = "unity-manual-demo",
                calibrationId = calibrationId,
                sequence = sequence++,
                timestampMs = clock.ElapsedMilliseconds,
                positionMm = new Vector3Dto { x = sampleX, y = sampleY, z = sampleZ },
                orientation = IncisionHold,
                forceN = 0f,
                contact = false,
                quality = 1f,
                sourceHealthy = true,
                inputMode = "pose-only",
                forceMeasurementValid = false
            };
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
            if (isSessionOwner && http != null && !string.IsNullOrEmpty(sessionId))
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
