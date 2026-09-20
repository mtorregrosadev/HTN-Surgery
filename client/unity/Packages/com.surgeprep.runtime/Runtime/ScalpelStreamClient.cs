using System;
using System.Collections.Concurrent;
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
    /// Receive-only client for calibrated hardware sessions.
    /// Samples still travel hardware -> controller -> API -> SOFA; this
    /// component only renders the returned snapshots. Keep WASD
    /// <see cref="UnityManualDemoClient"/> as the software fallback.
    /// </summary>
    public sealed class ScalpelStreamClient : MonoBehaviour
    {
        private const string ActiveSessionPlaceholder = "replace-with-active-session";
        private const int SnapshotChunkBytes = 16 * 1024;
        private const int MaxSnapshotBytes = 4 * 1024 * 1024;
        private const int InitialReconnectDelayMs = 250;
        private const int MaxReconnectDelayMs = 5000;

        [SerializeField] private string controllerUrl = "http://localhost:8100";
        [SerializeField] private string sessionId = ActiveSessionPlaceholder;
        [SerializeField] private SimulationSceneRenderer sceneRenderer;

        private readonly ConcurrentQueue<string> received = new ConcurrentQueue<string>();
        private ClientWebSocket socket;
        private CancellationTokenSource cancellation;
        private int lifecycleGeneration;

        public bool Connected => socket != null && socket.State == WebSocketState.Open;
        public string SessionId => sessionId;

        public void SetSessionId(string id)
        {
            if (!string.IsNullOrEmpty(id) && id != sessionId)
            {
                sessionId = id;
                if (isActiveAndEnabled)
                {
                    OnDisable();
                    OnEnable();
                }
            }
        }

        private async void OnEnable()
        {
            cancellation = new CancellationTokenSource();
            var generation = Interlocked.Increment(ref lifecycleGeneration);
            try
            {
                await RunStreamLoop(cancellation.Token, generation);
            }
            catch (OperationCanceledException)
            {
                // Expected during scene shutdown.
            }
            catch (Exception error)
            {
                Debug.LogError($"Scalpel controller stream stopped: {error.Message}");
            }
        }

        private void Update()
        {
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
                sceneRenderer.SetTarget(snapshot);
            }
            catch (Exception error)
            {
                Debug.LogWarning($"[ScalpelStreamClient] Ignoring invalid simulation snapshot: {error.Message}");
            }
        }

        private async Task RunStreamLoop(CancellationToken token, int generation)
        {
            var reconnectDelayMs = InitialReconnectDelayMs;
            while (!token.IsCancellationRequested)
            {
                var discoveredSession = IsSessionPlaceholder();
                try
                {
                    await ConnectAndReceive(token);
                    reconnectDelayMs = InitialReconnectDelayMs;
                }
                catch (OperationCanceledException)
                {
                    throw;
                }
                catch (Exception error)
                {
                    Debug.LogWarning(
                        $"[ScalpelStreamClient] Stream disconnected; retrying: {error.Message}"
                    );
                }
                finally
                {
                    if (generation == lifecycleGeneration)
                    {
                        CloseSocket();
                    }
                }

                if (generation != lifecycleGeneration)
                {
                    return;
                }
                if (discoveredSession)
                {
                    sessionId = ActiveSessionPlaceholder;
                }
                await Task.Delay(reconnectDelayMs, token);
                reconnectDelayMs = Math.Min(reconnectDelayMs * 2, MaxReconnectDelayMs);
            }
        }

        private async Task ConnectAndReceive(CancellationToken token)
        {
            var httpBase = controllerUrl.TrimEnd('/')
                .Replace("ws://", "http://")
                .Replace("wss://", "https://");
            var wsBase = httpBase
                .Replace("http://", "ws://")
                .Replace("https://", "wss://");

            // Auto-discover active session if not configured
            if (IsSessionPlaceholder())
            {
                using (var http = new HttpClient())
                {
                    while (!token.IsCancellationRequested && IsSessionPlaceholder())
                    {
                        try
                        {
                            using (var response = await http.GetAsync($"{httpBase}/v1/sessions/active", token))
                            {
                                if (response.IsSuccessStatusCode)
                                {
                                    var json = await response.Content.ReadAsStringAsync();
                                    var sess = JsonUtility.FromJson<SessionDto>(json);
                                    if (sess != null && !string.IsNullOrEmpty(sess.sessionId))
                                    {
                                        sessionId = sess.sessionId;
                                        Debug.Log($"[ScalpelStreamClient] Auto-attached to active session: {sessionId}");
                                        break;
                                    }
                                }
                            }
                        }
                        catch
                        {
                            // Await session creation
                        }
                        await Task.Delay(1000, token);
                    }
                }
            }

            if (IsSessionPlaceholder())
            {
                return;
            }

            var connectedSocket = new ClientWebSocket();
            socket = connectedSocket;
            var uri = new Uri($"{wsBase}/v1/sessions/{sessionId}/client-stream");
            await connectedSocket.ConnectAsync(uri, token);
            sceneRenderer?.BindSession(sessionId);
            while (!token.IsCancellationRequested && connectedSocket.State == WebSocketState.Open)
            {
                var payload = await ReceiveTextMessage(connectedSocket, token);
                if (payload == null)
                {
                    break;
                }
                received.Enqueue(payload);
            }
        }

        private bool IsSessionPlaceholder()
        {
            return string.IsNullOrEmpty(sessionId) || sessionId == ActiveSessionPlaceholder;
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

        private void CloseSocket()
        {
            var activeSocket = socket;
            socket = null;
            if (activeSocket != null)
            {
                activeSocket.Dispose();
            }
        }

        private void OnDisable()
        {
            Interlocked.Increment(ref lifecycleGeneration);
            cancellation?.Cancel();
            CloseSocket();
            cancellation?.Dispose();
            cancellation = null;
        }
    }
}
