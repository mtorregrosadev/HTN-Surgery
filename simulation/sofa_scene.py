"""Localized 80 x 80 mm layered chest region for native SOFA v26.06.

Visual BodyParts3D meshes are never used as the FEM volume. Topology change is
bounded to the instructor corridor. Protected rib strips cannot be carved.
Tool collision follows the official SofaCarving example: a rigid handle with a
Vec3 sphere tagged CarvingTool.
"""

LAYER_BOXES = {
    "skin": {"min": [-40.0, -3.0, -40.0], "max": [40.0, 0.0, 40.0], "young": 22.0},
    "subcutaneous": {"min": [-40.0, -8.0, -40.0], "max": [40.0, -3.0, 40.0], "young": 12.0},
    "muscle": {"min": [-40.0, -13.0, -40.0], "max": [40.0, -8.0, 40.0], "young": 28.0},
    "pleura": {"min": [-40.0, -16.0, -40.0], "max": [40.0, -13.0, 40.0], "young": 16.0},
}


def _add_layer(root, name, spec, resolution, carve=False):
    tissue = root.addChild(name)
    tissue.addObject("EulerImplicitSolver", rayleighStiffness=0.12, rayleighMass=0.08)
    tissue.addObject("CGLinearSolver", iterations=25, tolerance=1e-9, threshold=1e-9)
    tissue.addObject(
        "RegularGridTopology",
        name="grid",
        n=resolution,
        min=spec["min"],
        max=spec["max"],
    )
    tissue.addObject("MechanicalObject", name="dofs", src="@grid")
    tissue.addObject("UniformMass", totalMass=0.05)
    tissue.addObject(
        "HexahedronFEMForceField",
        youngModulus=spec["young"],
        poissonRatio=0.45,
        method="large",
    )
    tissue.addObject(
        "BoxROI",
        name="fixedRim",
        box=[
            spec["min"][0] - 1.0, spec["min"][1] - 0.5, spec["min"][2] - 1.0,
            spec["max"][0] + 1.0, spec["min"][1] + 0.4, spec["max"][2] + 1.0,
        ],
        drawBoxes=False,
    )
    tissue.addObject("FixedProjectiveConstraint", indices="@fixedRim.indices")

    quads = tissue.addChild("quads")
    quads.addObject("QuadSetTopologyContainer", name="container")
    quads.addObject("QuadSetTopologyModifier")
    quads.addObject("Hexa2QuadTopologicalMapping", input="@../grid", output="@container")

    surface = quads.addChild("surface")
    surface.addObject("TriangleSetTopologyContainer", name="topology")
    surface.addObject("TriangleSetTopologyModifier")
    surface.addObject("Quad2TriangleTopologicalMapping", input="@../container", output="@topology")
    surface.addObject("MechanicalObject", name="dofs")
    collision_kwargs = {"tags": "CarvingSurface"} if carve else {}
    surface.addObject("TriangleCollisionModel", **collision_kwargs)
    surface.addObject("BarycentricMapping")
    return tissue


def _add_protected_rib(root, name, z_centre):
    rib = root.addChild(name)
    rib.addObject(
        "MechanicalObject",
        name="dofs",
        template="Vec3d",
        position=[[0.0, -13.0, z_centre]],
    )
    rib.addObject("SphereCollisionModel", radius=4.0, simulated=False, moving=False)
    return rib


def createScene(root, carving_active=True):
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
            "Sofa.Component.Constraint.Projective",
            "Sofa.Component.Engine.Select",
            "Sofa.Component.LinearSolver.Iterative",
            "Sofa.Component.Mass",
            "Sofa.Component.Mapping.Linear",
            "Sofa.Component.Mapping.NonLinear",
            "Sofa.Component.ODESolver.Backward",
            "Sofa.Component.SolidMechanics.FEM.Elastic",
            "Sofa.Component.StateContainer",
            "Sofa.Component.Topology.Container.Grid",
            "Sofa.Component.Topology.Container.Dynamic",
            "Sofa.Component.Topology.Mapping",
            "SofaCarving",
        ],
    )
    root.addObject("DefaultAnimationLoop")
    root.addObject("CollisionPipeline", verbose=False)
    root.addObject("BruteForceBroadPhase")
    root.addObject("BVHNarrowPhase", name="narrowPhase")
    root.addObject("LocalMinDistance", alarmDistance=2.5, contactDistance=0.6)
    root.addObject("CollisionResponse", response="PenalityContactForceField")

    _add_layer(root, "skin", LAYER_BOXES["skin"], [13, 3, 9], carve=True)
    _add_layer(root, "subcutaneous", LAYER_BOXES["subcutaneous"], [11, 3, 7], carve=False)
    _add_layer(root, "muscle", LAYER_BOXES["muscle"], [11, 3, 7], carve=False)
    _add_layer(root, "pleura", LAYER_BOXES["pleura"], [9, 2, 7], carve=False)
    _add_protected_rib(root, "ribA", -18.0)
    _add_protected_rib(root, "ribB", 18.0)

    tool = root.addChild("tool")
    tool.addObject(
        "MechanicalObject",
        name="dofs",
        template="Rigid3d",
        position=[[0.0, 18.0, 0.0, 0.0, 0.0, 0.0, 1.0]],
    )
    tool.addObject("UniformMass", template="Rigid3d", totalMass=0.008)
    collision = tool.addChild("CollisionModel")
    collision.addObject(
        "MechanicalObject",
        template="Vec3d",
        name="Particle",
        position=[[0.0, 0.0, 0.0]],
    )
    collision.addObject(
        "SphereCollisionModel",
        name="ParticleModel",
        radius=1.6,
        tags="CarvingTool",
        simulated=False,
        moving=True,
    )
    collision.addObject("RigidMapping", input="@../dofs", output="@Particle")

    root.addObject(
        "CarvingManager",
        active=carving_active,
        carvingDistance=-0.05,
        narrowPhaseDetection="@narrowPhase",
        toolModel="@tool/CollisionModel/ParticleModel",
    )
    return root
