using UnityEngine;

namespace SurgePrep
{
    /// <summary>
    /// Purely visual motion for room dressing: a constant spin and/or a gentle back-and-forth
    /// bob along an axis. It never touches the simulation.
    /// </summary>
    public sealed class AmbientMotion : MonoBehaviour
    {
        [SerializeField] private Vector3 spinDegreesPerSecond = Vector3.zero;
        [SerializeField] private Vector3 bobAxis = Vector3.up;
        [SerializeField] private float bobAmplitude;
        [SerializeField] private float bobCyclesPerSecond = 0.25f;

        private Vector3 startLocalPosition;

        public void Configure(Vector3 spin, Vector3 axis, float amplitude, float cyclesPerSecond)
        {
            spinDegreesPerSecond = spin;
            bobAxis = axis;
            bobAmplitude = amplitude;
            bobCyclesPerSecond = cyclesPerSecond;
        }

        private void Awake()
        {
            startLocalPosition = transform.localPosition;
        }

        private void Update()
        {
            if (spinDegreesPerSecond != Vector3.zero)
            {
                transform.Rotate(spinDegreesPerSecond * Time.deltaTime, Space.Self);
            }
            if (bobAmplitude > 0f && bobAxis.sqrMagnitude > 0.0001f)
            {
                var phase = Mathf.Sin(Time.time * bobCyclesPerSecond * 2f * Mathf.PI);
                transform.localPosition = startLocalPosition + bobAxis.normalized * (phase * bobAmplitude);
            }
        }
    }
}
