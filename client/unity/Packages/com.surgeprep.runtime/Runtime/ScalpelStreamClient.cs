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
        private bool trackingFailed;

        public bool Connected => socket != null && socket.State == WebSocketState.Open;
        public bool TrackingHealthy => !trackingFailed;
        public string Status { get; private set; } = "Starting Scalpel controller stream…";

        private async void OnEnable()
        {
            cancellation = new CancellationTokenSource();
            trackingFailed = false;
            ClearReceived();
            Status = "Connecting to Scalpel controller…";
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
                trackingFailed = true;
                Status = $"Tracking failed: {error.Message}";
                Debug.LogError($"Scalpel controller stream failed: {error.Message}");
            }
        }

        private void Update()
        {
            string latest = null;
            while (received.TryDequeue(out var payload))
            {
                if (ContractCompatibility.TryReadError(payload, out var error))
                {
                    HandleTrackingError(error);
                    continue;
                }
                if (trackingFailed)
                {
                    // Do not let a queued snapshot silently recover a failed stream; reconnect.
                    continue;
                }
                latest = payload;
            }
            if (latest == null || sceneRenderer == null)
            {
                return;
            }
            var snapshot = JsonUtility.FromJson<SimulationSnapshotDto>(latest);
            if (!trackingFailed && snapshot != null && ContractCompatibility.Accepts(snapshot.contractVersion))
            {
                sceneRenderer.SetTarget(snapshot);
            }
        }

        private void HandleTrackingError(StreamErrorDto error)
        {
            if (trackingFailed) return;
            trackingFailed = true;
            var message = ContractCompatibility.DescribeError(error);
            Status = $"Tracking failed: {message}";
            Debug.LogError($"Scalpel controller tracking rejected: {message}");
        }

        private void ClearReceived()
        {
            string ignored;
            while (received.TryDequeue(out ignored))
            {
            }
        }

        private async Task ConnectAndReceive(CancellationToken token)
        {
            socket = new ClientWebSocket();
            var uri = new Uri(
                $"{controllerUrl.TrimEnd('/')}/v1/sessions/{sessionId}/client-stream"
            );
            await socket.ConnectAsync(uri, token);
            Status = "Connected — awaiting authoritative tracking";
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
            if (!token.IsCancellationRequested)
            {
                trackingFailed = true;
                Status = "Tracking failed: controller stream closed";
                Debug.LogError("Scalpel controller stream closed before tracking recovered");
            }
        }

        private void OnDisable()
        {
            cancellation?.Cancel();
            ClearReceived();
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
