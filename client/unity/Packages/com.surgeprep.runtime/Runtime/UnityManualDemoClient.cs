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
    /// Development-only input source. It keeps keyboard input in the Unity Game view,
    /// while still routing samples through Scalpel, the API, and the simulation adapter.
    /// Disable this component when the physical hardware stream is connected.
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
        [SerializeField] private bool invertHorizontalForFrontCamera = true;

        private readonly ConcurrentQueue<string> received = new ConcurrentQueue<string>();
        private readonly object stateLock = new object();
        private CancellationTokenSource cancellation;
        private ClientWebSocket socket;
        private HttpClient http;
        private float xMm;
        private float zMm;
        private float forceN;
        private long sequence;
        private string calibrationId;
        private string sessionId;
        private Stopwatch clock;

        public bool Connected => socket != null && socket.State == WebSocketState.Open;
        public string SessionId => sessionId;
        public string Status { get; private set; } = "Starting controller session…";

        private async void OnEnable()
        {
            cancellation = new CancellationTokenSource();
            http = new HttpClient { BaseAddress = new Uri(controllerUrl.TrimEnd('/') + "/") };
            try
            {
                await CreateSession(cancellation.Token);
                await StreamSamples(cancellation.Token);
            }
            catch (OperationCanceledException)
            {
                // Expected when Play Mode stops.
            }
            catch (Exception error)
            {
                Status = "Controller unavailable — start Docker";
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
            var snapshot = JsonUtility.FromJson<SimulationSnapshotDto>(latest);
            if (snapshot != null && snapshot.contractVersion == "1.0")
            {
                sceneRenderer.SetTarget(snapshot);
            }
        }

        private void UpdateKeyboardState()
        {
            var horizontal = 0f;
            var vertical = 0f;
            if (Input.GetKey(KeyCode.A) || Input.GetKey(KeyCode.LeftArrow)) horizontal -= 1f;
            if (Input.GetKey(KeyCode.D) || Input.GetKey(KeyCode.RightArrow)) horizontal += 1f;
            if (Input.GetKey(KeyCode.S) || Input.GetKey(KeyCode.DownArrow)) vertical -= 1f;
            if (Input.GetKey(KeyCode.W) || Input.GetKey(KeyCode.UpArrow)) vertical += 1f;

            // The front-facing anatomy camera mirrors the simulation X axis on screen.
            if (invertHorizontalForFrontCamera) horizontal *= -1f;
            lock (stateLock)
            {
                xMm += horizontal * movementSpeedMmPerSecond * Time.unscaledDeltaTime;
                zMm += vertical * movementSpeedMmPerSecond * Time.unscaledDeltaTime;
                if (Input.GetKeyDown(KeyCode.Space))
                {
                    forceN = forceN > 0f ? 0f : 0.75f;
                }
                if (Input.GetKeyDown(KeyCode.LeftBracket)) forceN = Mathf.Max(0f, forceN - 0.1f);
                if (Input.GetKeyDown(KeyCode.RightBracket)) forceN = Mathf.Min(1.5f, forceN + 0.1f);
                if (Input.GetKeyDown(KeyCode.R))
                {
                    xMm = 0f;
                    zMm = 0f;
                    forceN = 0f;
                }
            }
        }

        private async Task CreateSession(CancellationToken token)
        {
            Status = "Validating demo calibration…";
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
                    toolId = "blunt-stylus-1",
                    deviceId = "unity-manual-demo"
                },
                token
            );
            sessionId = session.sessionId;
            clock = Stopwatch.StartNew();
            Status = "Connecting to authoritative simulation…";
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
            Status = "LIVE — click here and use WASD";

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
            float sampleZ;
            float sampleForce;
            lock (stateLock)
            {
                sampleX = xMm;
                sampleZ = zMm;
                sampleForce = forceN;
            }
            return new ToolSampleDto
            {
                contractVersion = "1.0",
                sessionId = sessionId,
                toolId = "blunt-stylus-1",
                deviceId = "unity-manual-demo",
                calibrationId = calibrationId,
                sequence = sequence++,
                timestampMs = clock.ElapsedMilliseconds,
                positionMm = new Vector3Dto { x = sampleX, y = 16f - sampleForce * 2f, z = sampleZ },
                orientation = new QuaternionDto { qx = 0.173648f, qy = 0f, qz = 0f, qw = 0.984808f },
                forceN = sampleForce,
                contact = sampleForce > 0.08f,
                quality = 1f,
                sourceHealthy = true
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
                    // Play Mode can close before the completion request finishes.
                }
            }
            http?.Dispose();
            http = null;
            cancellation?.Dispose();
            cancellation = null;
        }
    }
}
