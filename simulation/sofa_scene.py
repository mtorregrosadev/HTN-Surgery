"""Native SOFA scene for the localized chest-tube training region.

The region uses one connected tetrahedral continuum so contact propagates
through its full 16 mm depth. The mapped triangle boundary is simultaneously
the collision surface and the topology updated by SofaCarving. Coordinates are
millimetres; elastic modulus is N/mm² (MPa), and reported contact lambda is N.
"""

PATCH_HALF_MM = 40.0
PATCH_DEPTH_MM = 16.0
GRID_RESOLUTION = [13, 7, 13]
TISSUE_YOUNG_MODULUS_MPA = 0.20
TISSUE_POISSON_RATIO = 0.45


def createScene(root, carving_active=False):
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
        maxIterations=1000,
        tolerance=1e-6,
        computeConstraintForces=True,
    )
    root.addObject("CollisionPipeline", verbose=False)
    root.addObject("BruteForceBroadPhase")
    root.addObject("BVHNarrowPhase", name="narrowPhase")
    root.addObject(
        "MinProximityIntersection",
        name="proximity",
        alarmDistance=2.5,
        contactDistance=0.5,
        useSurfaceNormals=False,
    )
    root.addObject(
        "CollisionResponse",
        response="FrictionContactConstraint",
        responseParams="mu=0.05",
    )

    # Generate a regular hexahedral lattice, then use SOFA's supported
    # Hexa2Tetra mapping so dynamic tetra removal updates downstream topology.
    source = root.addChild("topologySource")
    source.addObject(
        "RegularGridTopology",
        name="hexaGrid",
        n=GRID_RESOLUTION,
        min=[-PATCH_HALF_MM, -PATCH_DEPTH_MM, -PATCH_HALF_MM],
        max=[PATCH_HALF_MM, 0.0, PATCH_HALF_MM],
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
        box=[
            -PATCH_HALF_MM - 1.0,
            -PATCH_DEPTH_MM - 1.0,
            -PATCH_HALF_MM - 1.0,
            PATCH_HALF_MM + 1.0,
            -PATCH_DEPTH_MM + 0.5,
            PATCH_HALF_MM + 1.0,
        ],
    )
    tissue.addObject(
        "FixedProjectiveConstraint",
        indices="@fixedBottom.indices",
    )
    tissue.addObject(
        "TetrahedralCorotationalFEMForceField",
        name="fem",
        youngModulus=TISSUE_YOUNG_MODULUS_MPA,
        poissonRatio=TISSUE_POISSON_RATIO,
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
        position=[[0.0, 18.0, 0.0, 0.0, 0.0, 0.0, 1.0]],
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
        radius=1.6,
        simulated=False,
        moving=True,
        tags="CarvingTool",
    )
    collision.addObject("RigidMapping", input="@../dofs", output="@particle")

    root.addObject(
        "CarvingManager",
        name="carvingManager",
        active=carving_active,
        carvingDistance=-0.05,
        narrowPhaseDetection="@narrowPhase",
        toolModel="@tool/collision/sphere",
    )
    return root
