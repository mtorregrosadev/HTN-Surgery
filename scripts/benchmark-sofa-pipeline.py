#!/usr/bin/env python3
"""Measure native SOFA solve and snapshot costs without MongoDB or WebSockets."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import statistics
import sys
import time


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "backend" / "src"))


def configure_native_sofa() -> None:
    checker_path = REPOSITORY / "scripts" / "check-native-sofa.py"
    specification = importlib.util.spec_from_file_location(
        "check_native_sofa", checker_path
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("Unable to load the native SOFA checker")
    checker = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(checker)
    checker.configure_paths(checker.find_sofa_root())


async def benchmark() -> None:
    configure_native_sofa()

    from surge_prep.models import Quaternion, ToolSample, Vector3
    from surge_prep.simulation import SofaSimulator

    simulator = SofaSimulator(str(REPOSITORY / "simulation" / "sofa_scene.py"))
    session_id = "sofa-benchmark"
    await simulator.start()
    await simulator.begin_session(session_id)
    state = simulator._sessions[session_id]
    vertices = sum(
        len(simulator._layer(state.root, layer).dofs.position.value)
        for layer in simulator.layer_nodes
    )
    tetrahedra = sum(state.initial_tetrahedra.values())
    trajectory = [
        (-15.0, 5.0),
        (-15.0, 2.5),
        (-15.0, 1.0),
        (-15.0, 0.0),
        (-15.0, -1.0),
        *[(float(x), -2.0) for x in range(-15, 16, 2)],
    ]
    step_ms: list[float] = []
    serialization_ms: list[float] = []
    payload_bytes: list[int] = []
    topology_changes = 0
    peak_deformation = 0.0
    peak_reaction = 0.0
    try:
        for sequence, (x_mm, y_mm) in enumerate(trajectory):
            sample = ToolSample(
                session_id=session_id,
                tool_id="scalpel",
                device_id="benchmark-device",
                calibration_id="benchmark-calibration",
                sequence=sequence,
                timestamp_ms=sequence * 33,
                position_mm=Vector3(x=x_mm, y=y_mm, z=0.0),
                orientation=Quaternion(qx=0.0, qy=0.0, qz=0.0, qw=1.0),
                force_n=0.0,
                contact=False,
            )
            started = time.perf_counter()
            snapshot = await simulator.step(sample)
            step_ms.append((time.perf_counter() - started) * 1000.0)

            started = time.perf_counter()
            payload = snapshot.model_dump_json(by_alias=True)
            serialization_ms.append((time.perf_counter() - started) * 1000.0)
            payload_bytes.append(len(payload.encode("utf-8")))
            topology_changes += int("topology-changed" in snapshot.events)
            peak_deformation = max(
                peak_deformation, snapshot.tissue.deformation_mm
            )
            peak_reaction = max(peak_reaction, snapshot.tool.reaction_force_n)
    finally:
        await simulator.end_session(session_id)
        await simulator.close()

    total_seconds = sum(step_ms) / 1000.0
    print("SOFA PIPELINE BENCHMARK")
    print(f"  mesh: {vertices:,} vertices / {tetrahedra:,} tetrahedra")
    print(
        f"  solve + mesh export: median {statistics.median(step_ms):.1f} ms, "
        f"p95 {sorted(step_ms)[int(0.95 * (len(step_ms) - 1))]:.1f} ms"
    )
    print(
        f"  sustained authoritative rate: {len(step_ms) / total_seconds:.1f} snapshots/s"
    )
    print(
        f"  JSON serialization: median {statistics.median(serialization_ms):.1f} ms, "
        f"largest payload {max(payload_bytes) / 1024.0:.1f} KiB"
    )
    print(
        f"  response: {topology_changes} topology changes, "
        f"{peak_deformation:.3f} mm peak deformation, "
        f"{peak_reaction:.3f} N peak reaction"
    )


if __name__ == "__main__":
    asyncio.run(benchmark())
