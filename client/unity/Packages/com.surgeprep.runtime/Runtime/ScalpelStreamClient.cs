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
        private const int ActiveSessionPollIntervalMs = 1000;

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
            var followActiveSession = IsSessionPlaceholder();
            while (!token.IsCancellationRequested)
            {
                var switchedSession = false;
                try
                {
                    await ConnectAndReceive(token, followActiveSession);
                    reconnectDelayMs = InitialReconnectDelayMs;
                }
                catch (SessionChangedException change)
                {
                    if (!followActiveSession || string.IsNullOrEmpty(change.NewSessionId))
                    {
                        throw;
                    }
                    sessionId = change.NewSessionId;
                    DrainReceivedSnapshots();
                    switchedSession = true;
                    reconnectDelayMs = InitialReconnectDelayMs;
                    Debug.Log(
                        $"[ScalpelStreamClient] Active session changed; reconnecting to {sessionId}"
                    );
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
                if (switchedSession)
                {
                    continue;
                }
                if (followActiveSession)
                {
                    sessionId = ActiveSessionPlaceholder;
                }
                await Task.Delay(reconnectDelayMs, token);
                reconnectDelayMs = Math.Min(reconnectDelayMs * 2, MaxReconnectDelayMs);
            }
        }

        private async Task ConnectAndReceive(CancellationToken token, bool followActiveSession)
        {
            var httpBase = controllerUrl.TrimEnd('/')
                .Replace("ws://", "http://")
                .Replace("wss://", "https://");
            var wsBase = httpBase
                .Replace("http://", "ws://")
                .Replace("https://", "wss://");

            // Auto-discover active session if not configured
            if (followActiveSession && IsSessionPlaceholder())
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

            var connectedSession = sessionId;
            var connectedSocket = new ClientWebSocket();
            socket = connectedSocket;
            using (var connectionCancellation = CancellationTokenSource.CreateLinkedTokenSource(token))
            {
                Task<string> monitorTask = null;
                Task<string> receiveTask = null;
                try
                {
                    var uri = new Uri($"{wsBase}/v1/sessions/{connectedSession}/client-stream");
                    await connectedSocket.ConnectAsync(uri, connectionCancellation.Token);
                    sceneRenderer?.BindSession(connectedSession, true);
                    if (followActiveSession)
                    {
                        monitorTask = MonitorActiveSession(
                            httpBase, connectedSession, connectionCancellation.Token
                        );
                    }
                    while (!connectionCancellation.IsCancellationRequested
                        && connectedSocket.State == WebSocketState.Open)
                    {
                        receiveTask = ReceiveTextMessage(
                            connectedSocket, connectionCancellation.Token
                        );
                        Task completed = monitorTask == null
                            ? (Task)receiveTask
                            : await Task.WhenAny(receiveTask, monitorTask);
                        if (monitorTask != null && completed == monitorTask)
                        {
                            var changedSession = await monitorTask;
                            if (!string.IsNullOrEmpty(changedSession))
                            {
                                throw new SessionChangedException(changedSession);
                            }
                            break;
                        }
                        var payload = await receiveTask;
                        receiveTask = null;
                        if (payload == null)
                        {
                            break;
                        }
                        received.Enqueue(payload);
                    }
                }
                finally
                {
                    connectionCancellation.Cancel();
                    CloseSocket(connectedSocket);
                    await ObserveTask(receiveTask);
                    await ObserveTask(monitorTask);
                }
            }
        }

        private async Task<string> MonitorActiveSession(
            string httpBase, string connectedSession, CancellationToken token
        )
        {
            using (var http = new HttpClient { Timeout = TimeSpan.FromSeconds(2) })
            {
                while (!token.IsCancellationRequested)
                {
                    await Task.Delay(ActiveSessionPollIntervalMs, token);
                    try
                    {
                        using (var response = await http.GetAsync(
                            $"{httpBase}/v1/sessions/active", token
                        ))
                        {
                            if (!response.IsSuccessStatusCode)
                            {
                                continue;
                            }
                            var json = await response.Content.ReadAsStringAsync();
                            var active = JsonUtility.FromJson<SessionDto>(json);
                            if (active != null
                                && !string.IsNullOrEmpty(active.sessionId)
                                && active.sessionId != connectedSession)
                            {
                                return active.sessionId;
                            }
                        }
                    }
                    catch (OperationCanceledException) when (!token.IsCancellationRequested)
                    {
                        // HttpClient.Timeout also uses cancellation. A slow
                        // active-session poll must not tear down a healthy
                        // WebSocket stream.
                    }
                    catch (OperationCanceledException)
                    {
                        throw;
                    }
                    catch
                    {
                        // Keep the current stream when active-session discovery is unavailable.
                    }
                }
            }
            return null;
        }

        private static async Task ObserveTask(Task task)
        {
            if (task == null)
            {
                return;
            }
            try
            {
                await task;
            }
            catch
            {
                // The connection task owns the original exception, if any.
            }
        }

        private void DrainReceivedSnapshots()
        {
            while (received.TryDequeue(out _))
            {
                // Discard snapshots queued for the previous session.
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

        private void CloseSocket(ClientWebSocket expectedSocket)
        {
            if (ReferenceEquals(socket, expectedSocket))
            {
                socket = null;
            }
            expectedSocket?.Dispose();
        }

        private sealed class SessionChangedException : Exception
        {
            public readonly string NewSessionId;

            public SessionChangedException(string newSessionId)
                : base($"Active session changed to {newSessionId}")
            {
                NewSessionId = newSessionId;
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
