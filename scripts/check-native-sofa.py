#!/usr/bin/env python3
"""Validate a host SOFA v26.06 install for the Surge Prep showcase."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

SEARCH_ROOTS = [
    Path(os.environ["SURGE_PREP_SOFA_ROOT"]) if os.environ.get("SURGE_PREP_SOFA_ROOT") else None,
    Path(os.environ["SOFA_ROOT"]) if os.environ.get("SOFA_ROOT") else None,
    Path.home() / "SOFA",
    Path.home() / "sofa",
    Path("/opt/sofa"),
    Path("/Applications/SOFA"),
]


def fail(message: str) -> None:
    print(f"SOFA CHECK FAILED: {message}", file=sys.stderr)
    sys.exit(1)


def python_ok() -> None:
    version = sys.version_info
    if version[:2] != (3, 12):
        print(
            f"warning: SOFA v26.06 SofaPython3 is documented for Python 3.12; "
            f"this interpreter is {version.major}.{version.minor}.{version.micro}",
            file=sys.stderr,
        )


def find_sofa_root() -> Path:
    for candidate in SEARCH_ROOTS:
        if candidate is None:
            continue
        if (candidate / "lib" / "python3" / "site-packages").is_dir() or (
            candidate / "plugins" / "SofaPython3"
        ).exists() or (candidate / "bin").is_dir():
            return candidate
        if candidate.is_dir():
            for child in sorted(candidate.glob("SOFA_*")):
                if child.is_dir():
                    return child
    fail(
        "Could not locate SOFA. Install official v26.06.00 for macOS and set "
        "SURGE_PREP_SOFA_ROOT to that directory. Do not commit the ~185 MB package."
    )


def configure_paths(root: Path) -> None:
    site = root / "lib" / "python3" / "site-packages"
    lib = root / "lib"
    plugins = root / "plugins"
    paths = [str(site), str(plugins / "SofaPython3" / "lib" / "python3" / "site-packages")]
    pythonpath = os.pathsep.join(path for path in paths if Path(path).is_dir())
    if pythonpath:
        os.environ["PYTHONPATH"] = pythonpath + os.pathsep + os.environ.get("PYTHONPATH", "")
        sys.path[:0] = [path for path in paths if Path(path).is_dir() and path not in sys.path]
    if lib.is_dir():
        lib_paths = [str(lib)]
        if plugins.is_dir():
            lib_paths.extend(str(path) for path in plugins.glob("*/lib") if path.is_dir())
        joined = os.pathsep.join(lib_paths)
        os.environ["DYLD_LIBRARY_PATH"] = joined + os.pathsep + os.environ.get("DYLD_LIBRARY_PATH", "")
        os.environ["LD_LIBRARY_PATH"] = joined + os.pathsep + os.environ.get("LD_LIBRARY_PATH", "")
    os.environ["SOFA_ROOT"] = str(root)
    os.environ["SURGE_PREP_SOFA_ROOT"] = str(root)
    os.environ.setdefault("SOFAPYTHON3_ROOT", str(plugins / "SofaPython3"))


def import_plugins() -> None:
    try:
        import numpy  # noqa: F401
    except ImportError:
        fail(
            "numpy is required by SofaPython3. Create a Python 3.12 venv and install it: "
            "python3.12 -m venv .venv-sofa && .venv-sofa/bin/pip install numpy"
        )
    try:
        import Sofa  # noqa: F401
        import SofaRuntime
    except ImportError as error:
        fail(f"SofaPython3 did not import ({error}).")
    try:
        loaded = SofaRuntime.importPlugin("SofaCarving")
    except Exception as error:
        fail(f"SofaCarving plugin failed to load ({error}).")
    else:
        if loaded is False:
            fail("SofaCarving plugin was not found in the SOFA install.")
    print("Loaded Sofa, SofaRuntime, and SofaCarving.")


def smoke_test() -> None:
    import Sofa
    import Sofa.Simulation

    repo = Path(__file__).resolve().parents[1]
    scene_path = repo / "simulation" / "sofa_scene.py"
    spec_ns: dict = {}
    exec(scene_path.read_text(), spec_ns)
    root = Sofa.Core.Node("smoke")
    # First verify stable constraint contact and solver-derived deformation.
    spec_ns["createScene"](root, carving_active=False)
    Sofa.Simulation.init(root)
    rest = [list(point) for point in root.tissue.dofs.rest_position.value]
    root.tool.dofs.position.value = [[0.0, 5.0, 0.0, 0.0, 0.0, 0.0, 1.0]]
    for _ in range(3):
        Sofa.Simulation.animate(root, 0.01)
    for y_mm in (2.5, 1.8, 1.0, 0.0):
        root.tool.dofs.position.value = [
            [0.0, y_mm, 0.0, 0.0, 0.0, 0.0, 1.0]
        ]
        for _ in range(4):
            Sofa.Simulation.animate(root, 0.01)
    current = root.tissue.dofs.position.value
    deformation = max(
        sum((float(point[i]) - rest_point[i]) ** 2 for i in range(3)) ** 0.5
        for point, rest_point in zip(current, rest)
    )
    reaction_n = abs(
        sum(float(force[1]) for force in root.tissue.dofs.getData("lambda").value)
    )
    constraint_count = len(root.contactSolver.constraintForces.value)

    # Then verify that the exact mapped tetrahedral topology used by the API
    # can be carved without corrupting or crashing the graph.
    before = len(root.tissue.topology.tetrahedra.value)
    root.carvingManager.active.value = True
    for x_mm in range(-10, 11, 2):
        root.tool.dofs.position.value = [
            [float(x_mm), -1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
        ]
        Sofa.Simulation.animate(root, 0.01)
    after = len(root.tissue.topology.tetrahedra.value)
    Sofa.Simulation.unload(root)
    if deformation < 0.5:
        fail(f"SOFA contact deformation was too small ({deformation:.3f} mm).")
    if reaction_n <= 0.0 or constraint_count == 0:
        fail("SOFA did not produce solver-derived contact force.")
    if after >= before:
        fail("SofaCarving did not remove tetrahedra from the mapped tissue topology.")
    print(
        "Headless contact/deformation/carving smoke test passed "
        f"({deformation:.3f} mm, {reaction_n:.3f} N, {before-after} tetrahedra removed)."
    )


def print_exports(root: Path) -> None:
    print(f"export SOFA_ROOT={root}")
    print(f"export SURGE_PREP_SOFA_ROOT={root}")
    print("export SURGE_PREP_SIMULATION_BACKEND=sofa")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-env", action="store_true")
    parser.add_argument("--skip-smoke", action="store_true")
    args = parser.parse_args()
    python_ok()
    root = find_sofa_root()
    configure_paths(root)
    print(f"Using SOFA at {root}")
    import_plugins()
    if not args.skip_smoke:
        smoke_test()
    if args.export_env:
        print_exports(root)


if __name__ == "__main__":
    main()
