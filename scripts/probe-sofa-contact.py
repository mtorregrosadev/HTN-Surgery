#!/usr/bin/env python3
"""Headless native-SOFA probe for deformable tool contact and force extraction."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path


def configure_sofa() -> None:
    checker_path = Path(__file__).with_name("check-native-sofa.py")
    spec = importlib.util.spec_from_file_location("check_native_sofa", checker_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {checker_path}")
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    checker.configure_paths(checker.find_sofa_root())
    checker.import_plugins()


def create_scene(root):
    root.dt = 0.01
    root.gravity = [0.0, 0.0, 0.0]
    root.addObject(
        "RequiredPlugin",
        pluginName=[
            "Sofa.Component.AnimationLoop",
            "Sofa.Component.Collision.Detection.Algorithm",
            "Sofa.Component.Collision.Detection.Intersection",
            "Sofa.Component.Collision.Geometry",
            "Sofa.Component.Collision.Response.Contact",
            "Sofa.Component.Constraint.Lagrangian.Correction",
            "Sofa.Component.Constraint.Lagrangian.Solver",
            "Sofa.Component.Constraint.Projective",
            "Sofa.Component.Engine.Select",
            "Sofa.Component.LinearSolver.Direct",
            "Sofa.Component.LinearSolver.Iterative",
            "Sofa.Component.Mapping.Linear",
            "Sofa.Component.Mapping.NonLinear",
            "Sofa.Component.Mass",
            "Sofa.Component.ODESolver.Backward",
            "Sofa.Component.SolidMechanics.FEM.Elastic",
            "Sofa.Component.StateContainer",
            "Sofa.Component.Topology.Container.Grid",
            "Sofa.Component.Topology.Container.Dynamic",
            "Sofa.Component.Topology.Mapping",
            "SofaCarving",
        ],
    )
    root.addObject("FreeMotionAnimationLoop")
    root.addObject(
        "BlockGaussSeidelConstraintSolver",
        name="contactSolver",
        maxIterations=500,
        tolerance=1e-7,
        computeConstraintForces=True,
    )
    root.addObject("CollisionPipeline")
    root.addObject("BruteForceBroadPhase")
    root.addObject("BVHNarrowPhase", name="narrowPhase")
    root.addObject(
        "LocalMinDistance",
        alarmDistance=2.5,
        contactDistance=0.2,
        useLMDFilters=False,
    )
    root.addObject(
        "CollisionResponse",
        response="FrictionContactConstraint",
        responseParams="mu=0.05",
    )

    source = root.addChild("topologySource")
    source.addObject(
        "RegularGridTopology",
        name="hexaGrid",
        n=[11, 4, 11],
        min=[-40.0, -16.0, -40.0],
        max=[40.0, 0.0, 40.0],
    )
    tetra_source = source.addChild("tetraSource")
    tetra_source.addObject(
        "TetrahedronSetTopologyContainer",
        name="container",
        position="@../hexaGrid.position",
    )
    tetra_source.addObject("TetrahedronSetTopologyModifier", name="modifier")
    tetra_source.addObject(
        "Hexa2TetraTopologicalMapping",
        input="@../hexaGrid",
        output="@container",
        swapping=False,
    )

    tissue = root.addChild("tissue")
    tissue.addObject(
        "EulerImplicitSolver",
        rayleighStiffness=0.15,
        rayleighMass=0.1,
    )
    tissue.addObject(
        "SparseLDLSolver",
        name="linearSolver",
        template="CompressedRowSparseMatrixMat3x3d",
    )
    tissue.addObject(
        "MechanicalObject",
        name="dofs",
        position="@../topologySource/tetraSource/container.position",
    )
    tissue.addObject(
        "TetrahedronSetTopologyContainer",
        name="topology",
        src="@../topologySource/tetraSource/container",
    )
    tissue.addObject("TetrahedronSetTopologyModifier", name="modifier")
    tissue.addObject("TetrahedronSetGeometryAlgorithms", template="Vec3d")
    tissue.addObject("DiagonalMass", massDensity=1e-6)
    tissue.addObject(
        "BoxROI",
        name="fixedBottom",
        box=[-41.0, -17.0, -41.0, 41.0, -15.5, 41.0],
    )
    tissue.addObject(
        "FixedProjectiveConstraint",
        indices="@fixedBottom.indices",
    )
    tissue.addObject(
        "TetrahedralCorotationalFEMForceField",
        name="fem",
        youngModulus=0.35,
        poissonRatio=0.45,
        method="large",
    )
    tissue.addObject("LinearSolverConstraintCorrection")

    surface = tissue.addChild("surface")
    surface.addObject("TriangleSetTopologyContainer", name="topology")
    surface.addObject("TriangleSetTopologyModifier", name="modifier")
    surface.addObject("TriangleSetGeometryAlgorithms", template="Vec3d")
    surface.addObject(
        "Tetra2TriangleTopologicalMapping",
        input="@../topology",
        output="@topology",
    )
    surface.addObject(
        "TriangleCollisionModel",
        name="triangles",
        contactStiffness=0.8,
        tags="CarvingSurface",
    )
    surface.addObject(
        "PointCollisionModel",
        name="points",
        contactStiffness=0.8,
        tags="CarvingSurface",
    )

    tool = root.addChild("tool")
    tool.addObject(
        "MechanicalObject",
        template="Rigid3d",
        name="dofs",
        position=[[0.0, 8.0, 0.0, 0.0, 0.0, 0.0, 1.0]],
    )
    collision = tool.addChild("collision")
    collision.addObject(
        "MechanicalObject",
        template="Vec3d",
        name="particle",
        position=[[0.0, 0.0, 0.0]],
    )
    collision.addObject(
        "SphereCollisionModel",
        name="sphere",
        radius=2.0,
        simulated=False,
        moving=True,
        tags="CarvingTool",
    )
    collision.addObject("RigidMapping", input="@../dofs", output="@particle")
    root.addObject(
        "CarvingManager",
        name="carvingManager",
        active=False,
        carvingDistance=-0.05,
        narrowPhaseDetection="@narrowPhase",
        toolModel="@tool/collision/sphere",
    )
    return root


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--carve", action="store_true")
    args = parser.parse_args()
    configure_sofa()
    import Sofa
    import Sofa.Simulation

    root = Sofa.Core.Node("contact_probe")
    create_scene(root)
    Sofa.Simulation.init(root)
    surface_positions = root.tissue.surface.topology.position.value
    surface_triangles = root.tissue.surface.topology.triangles.value
    print(
        f"surface topology: vertices={len(surface_positions)} "
        f"triangles={len(surface_triangles)}"
    )
    rest = [list(point) for point in root.tissue.dofs.rest_position.value]
    for tool_y in [5.0, 2.5, 1.8, 1.0, 0.0, -1.0, 5.0]:
        root.tool.dofs.position.value = [
            [0.0, tool_y, 0.0, 0.0, 0.0, 0.0, 1.0]
        ]
        for _ in range(12):
            Sofa.Simulation.animate(root, 0.01)
        current = root.tissue.dofs.position.value
        deformation = max(
            sum((float(point[index]) - rest_i[index]) ** 2 for index in range(3)) ** 0.5
            for point, rest_i in zip(current, rest)
        )
        nodal_contact = root.tissue.dofs.getData("lambda").value
        reaction_y = abs(sum(float(force[1]) for force in nodal_contact))
        constraints = root.contactSolver.constraintForces.value
        print(
            f"toolY={tool_y:5.1f} mm  deformation={deformation:8.4f} mm  "
            f"reactionY={reaction_y:10.6f}  constraints={len(constraints)}"
        )
    if args.carve:
        before = len(root.tissue.topology.tetrahedra.value)
        root.carvingManager.active.value = True
        for tool_x in range(-12, 13, 2):
            root.tool.dofs.position.value = [
                [float(tool_x), -1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
            ]
            for _ in range(3):
                Sofa.Simulation.animate(root, 0.01)
        after = len(root.tissue.topology.tetrahedra.value)
        print(f"carving tetrahedra: before={before} after={after} removed={before-after}")
    Sofa.Simulation.unload(root)


if __name__ == "__main__":
    main()
