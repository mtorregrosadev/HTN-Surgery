using System;
using System.Collections.Concurrent;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;

namespace SurgePrep
{
    public sealed class ScalpelStreamClient : MonoBehaviour
    {
        [SerializeField] private string controllerUrl = "ws://localhost:8100";
        [SerializeField] private string sessionId = "replace-with-active-session";
        [SerializeField] private SimulationSceneRenderer sceneRenderer;

        private readonly ConcurrentQueue<string> received = new ConcurrentQueue<string>();
        private ClientWebSocket socket;
        private CancellationTokenSource cancellation;

        public bool Connected => socket != null && socket.State == WebSocketState.Open;

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
            socket = new ClientWebSocket();
            var uri = new Uri(
                $"{controllerUrl.TrimEnd('/')}/v1/sessions/{sessionId}/client-stream"
            );
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
