"""Small simulation-friendly training pad for the live SOFA bridge.

The detailed anatomical OBJ files are intentionally not used as the FEM mesh.
This regular hexahedral volume is a replaceable MVP interaction region.
"""


def createScene(root):
    root.dt = 0.01
    root.gravity = [0.0, -9810.0, 0.0]  # millimetres per second squared

    root.addObject(
        "RequiredPlugin",
        pluginName=[
            "Sofa.Component.AnimationLoop",
            "Sofa.Component.Collision.Detection.Algorithm",
            "Sofa.Component.Collision.Detection.Intersection",
            "Sofa.Component.Collision.Geometry",
            "Sofa.Component.Collision.Response.Contact",
            "Sofa.Component.Constraint.Projective",
            "Sofa.Component.Engine.Select",
            "Sofa.Component.LinearSolver.Iterative",
            "Sofa.Component.Mass",
            "Sofa.Component.ODESolver.Backward",
            "Sofa.Component.SolidMechanics.FEM.Elastic",
            "Sofa.Component.StateContainer",
            "Sofa.Component.Topology.Container.Grid",
            "Sofa.Component.Topology.Container.Dynamic",
            "Sofa.Component.Topology.Mapping",
        ],
    )
    root.addObject("DefaultAnimationLoop")
    root.addObject("CollisionPipeline")
    root.addObject("BruteForceBroadPhase")
    root.addObject("BVHNarrowPhase")
    root.addObject("LocalMinDistance", alarmDistance=2.0, contactDistance=0.5)
    root.addObject("DefaultContactManager", response="PenalityContactForceField")

    tissue = root.addChild("tissue")
    tissue.addObject("EulerImplicitSolver", rayleighStiffness=0.1, rayleighMass=0.1)
    tissue.addObject("CGLinearSolver", iterations=25, tolerance=1e-9, threshold=1e-9)
    tissue.addObject(
        "RegularGridTopology", name="grid", n=[12, 4, 12],
        min=[-40.0, 0.0, -40.0], max=[40.0, 12.0, 40.0],
    )
    tissue.addObject("MechanicalObject", name="dofs", src="@grid")
    tissue.addObject("HexahedronSetTopologyContainer", src="@grid")
    tissue.addObject("UniformMass", totalMass=0.12)
    tissue.addObject(
        "HexahedronFEMForceField", youngModulus=18.0, poissonRatio=0.45,
        method="large",
    )
    tissue.addObject(
        "BoxROI", name="fixedBase", box=[-41.0, -1.0, -41.0, 41.0, 0.1, 41.0],
        drawBoxes=False,
    )
    tissue.addObject("FixedProjectiveConstraint", indices="@fixedBase.indices")
    surface = tissue.addChild("surface")
    surface.addObject("QuadSetTopologyContainer")
    surface.addObject("QuadSetTopologyModifier")
    surface.addObject("Hexa2QuadTopologicalMapping", input="@../grid", output="@.")
    surface.addObject("MechanicalObject")
    surface.addObject("QuadCollisionModel")
    surface.addObject("PointCollisionModel")
    surface.addObject("BarycentricMapping")

    tool = root.addChild("tool")
    tool.addObject(
        "MechanicalObject", name="dofs", template="Rigid3d",
        position=[[0.0, 25.0, 0.0, 0.0, 0.0, 0.0, 1.0]],
    )
    tool.addObject("SphereCollisionModel", radius=3.0, simulated=False, moving=True)
    tool.addObject("UniformMass", totalMass=0.01)
    return root

