using System;
using System.Collections.Concurrent;
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
        [SerializeField] private string controllerUrl = "http://localhost:8100";
        [SerializeField] private string sessionId = "replace-with-active-session";
        [SerializeField] private SimulationSceneRenderer sceneRenderer;

        private readonly ConcurrentQueue<string> received = new ConcurrentQueue<string>();
        private ClientWebSocket socket;
        private CancellationTokenSource cancellation;

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
            try
            {
                await ConnectAndReceive(cancellation.Token);
            }
            catch (OperationCanceledException)
            {
                // Expected during scene shutdown.
            }
            catch (Exception error)
            {
                Debug.LogError($"Scalpel controller stream failed: {error.Message}");
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
            var snapshot = JsonUtility.FromJson<SimulationSnapshotDto>(latest);
            if (snapshot != null && ContractCompatibility.Accepts(snapshot.contractVersion))
            {
                sceneRenderer.SetTarget(snapshot);
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
            if (string.IsNullOrEmpty(sessionId) || sessionId == "replace-with-active-session")
            {
                using (var http = new HttpClient())
                {
                    while (!token.IsCancellationRequested && (string.IsNullOrEmpty(sessionId) || sessionId == "replace-with-active-session"))
                    {
                        try
                        {
                            var resp = await http.GetAsync($"{httpBase}/v1/sessions/active", token);
                            if (resp.IsSuccessStatusCode)
                            {
                                var json = await resp.Content.ReadAsStringAsync();
                                var sess = JsonUtility.FromJson<SessionDto>(json);
                                if (sess != null && !string.IsNullOrEmpty(sess.sessionId))
                                {
                                    sessionId = sess.sessionId;
                                    Debug.Log($"[ScalpelStreamClient] Auto-attached to active session: {sessionId}");
                                    break;
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

            if (string.IsNullOrEmpty(sessionId) || sessionId == "replace-with-active-session")
            {
                return;
            }

            socket = new ClientWebSocket();
            var uri = new Uri($"{wsBase}/v1/sessions/{sessionId}/client-stream");
            await socket.ConnectAsync(uri, token);
            var buffer = new byte[1024 * 256];
            while (!token.IsCancellationRequested && socket.State == WebSocketState.Open)
            {
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
                        throw new InvalidOperationException("Simulation snapshot exceeds 256 KiB");
                    }
                } while (!result.EndOfMessage);
                if (result.MessageType == WebSocketMessageType.Close)
                {
                    break;
                }
                received.Enqueue(Encoding.UTF8.GetString(buffer, 0, count));
            }
        }

        private void OnDisable()
        {
            cancellation?.Cancel();
            if (socket != null)
            {
                socket.Dispose();
                socket = null;
            }
            cancellation?.Dispose();
            cancellation = null;
        }
    }
}
