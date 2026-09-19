"""Native layered SOFA scene registered to the lateral chest surface.

Coordinates are millimetres. Each tissue layer is an independent curved
tetrahedral continuum with its own FEM, collision surface, and topology. The
visible Unity meshes are exported directly from these mapped SOFA surfaces.
Material values are illustrative training parameters, not clinical claims.
"""

from functools import lru_cache
from pathlib import Path

FIELD_RADIUS_X_MM = 40.0
FIELD_RADIUS_Z_MM = 36.0
GRID_X = 17
GRID_Z = 17
GRID_Y = 2

# Smooth fourth-order fit to registration samples taken from the BodyParts3D
# skin in the final supine showcase transform. This replaces the old 5x5
# client-side lookup table and keeps rendering and collision in one frame.
CHEST_SURFACE_TERMS = [
    ((0, 0), -0.15673469389450148),
    ((0, 1), -0.15619047619088122),
    ((1, 0), -0.6565476190475732),
    ((0, 2), -0.019745748299286214),
    ((1, 1), 0.007150000000007576),
    ((2, 0), -0.010474914965967697),
    ((0, 3), 5.8333333333272285e-05),
    ((1, 2), -5.3571428570533765e-06),
    ((2, 1), 0.00012857142857144923),
    ((3, 0), -0.0001354166666667074),
    ((0, 4), 5.104166666655587e-06),
    ((1, 3), -1.9791666666683116e-06),
    ((2, 2), 3.3801020408019367e-06),
    ((3, 1), 1.0416666666368515e-07),
    ((4, 0), -2.4479166666682357e-06),
]

LAYER_SPECS = {
    "skin": {"top": 0.0, "bottom": -3.0, "young": 0.35},
    "subcutaneous": {"top": -3.0, "bottom": -15.0, "young": 0.055},
    "muscle": {"top": -15.0, "bottom": -25.0, "young": 0.18},
    "pleura": {"top": -25.0, "bottom": -32.0, "young": 0.12},
}

SCALPEL_CUTTING_EDGE_MM = [
    [0.0, 0.0, 0.0],
    [0.0, 4.758, 0.809],
    [0.0, 14.5, 1.12],
    [0.0, 24.0, 1.28],
    [0.0, 33.0, 2.65],
]
SCALPEL_CUTTING_EDGE_SEGMENTS = [[index, index + 1] for index in range(4)]
RIB_CENTRES_Z_MM = (-18.0, 18.0)
RIB_RADIUS_MM = 4.0
RIB_TOP_DEPTH_MM = -18.0
ANATOMY_BIN_MM = 12.0
BODY_CONTACT_RADIUS_MM = 5.0
DEFORMABLE_RADIUS_X_MM = 30.0
DEFORMABLE_RADIUS_Z_MM = 22.0


def chest_surface_y_mm(x_mm, z_mm):
    return sum(
        coefficient * (x_mm ** x_power) * (z_mm ** z_power)
        for (x_power, z_power), coefficient in CHEST_SURFACE_TERMS
    )


def in_deformable_field(x_mm, z_mm):
    return (
        (x_mm / DEFORMABLE_RADIUS_X_MM) ** 2
        + (z_mm / DEFORMABLE_RADIUS_Z_MM) ** 2
        <= 1.0
    )


@lru_cache(maxsize=1)
def anatomy_surface_samples():
    """Downsample the registered high-resolution skin for broad contact.

    The OBJ remains the visual source in Unity. SOFA receives an invisible,
    simulation-friendly point shell derived from the same mesh, excluding the
    localized deformable field so it cannot obstruct real layer cutting.
    """
    scene_file = globals().get("__file__")
    repository = Path(scene_file).resolve().parents[1] if scene_file else Path.cwd()
    source = (
        repository
        / "bodyparts3d_highres"
        / "FJ2810_BP22617_FMA7163_Skin.obj"
    )
    if not source.exists():
        return {}
    bins = {}
    with source.open(encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if not line.startswith("v "):
                continue
            _, raw_x, raw_y, raw_z = line.split()[:4]
            # Match ChestTubeShowcaseBuilder's millimetre import, 180-degree
            # supine rotation, procedure-window origin, and Unity Z reflection.
            x_mm = -float(raw_x) - 120.0
            y_mm = -float(raw_y) - 213.0
            z_mm = 1200.0 - float(raw_z)
            if not (-150.0 <= x_mm <= 150.0 and -260.0 <= z_mm <= 260.0):
                continue
            key = (round(x_mm / ANATOMY_BIN_MM), round(z_mm / ANATOMY_BIN_MM))
            bins[key] = max(y_mm, bins.get(key, -10_000.0))
    return bins


def body_surface_y_mm(x_mm, z_mm):
    if in_deformable_field(x_mm, z_mm):
        return chest_surface_y_mm(x_mm, z_mm)
    bins = anatomy_surface_samples()
    target = (round(x_mm / ANATOMY_BIN_MM), round(z_mm / ANATOMY_BIN_MM))
    if target in bins:
        return bins[target]
    for radius in range(1, 6):
        candidates = [
            (key, value)
            for key, value in bins.items()
            if abs(key[0] - target[0]) <= radius and abs(key[1] - target[1]) <= radius
        ]
        if candidates:
            return min(
                candidates,
                key=lambda item: (item[0][0] - target[0]) ** 2
                + (item[0][1] - target[1]) ** 2,
            )[1]
    return chest_surface_y_mm(
        max(-FIELD_RADIUS_X_MM, min(FIELD_RADIUS_X_MM, x_mm)),
        max(-FIELD_RADIUS_Z_MM, min(FIELD_RADIUS_Z_MM, z_mm)),
    )


def _linspace(minimum, maximum, count):
    if count <= 1:
        return [minimum]
    return [minimum + (maximum - minimum) * index / (count - 1) for index in range(count)]


def _layer_mesh(top_mm, bottom_mm, fix_bottom=False):
    xs = _linspace(-FIELD_RADIUS_X_MM, FIELD_RADIUS_X_MM, GRID_X)
    zs = _linspace(-FIELD_RADIUS_Z_MM, FIELD_RADIUS_Z_MM, GRID_Z)
    depths = _linspace(top_mm, bottom_mm, GRID_Y)
    cells = []
    for z_index in range(GRID_Z - 1):
        for x_index in range(GRID_X - 1):
            centre_x = 0.5 * (xs[x_index] + xs[x_index + 1])
            centre_z = 0.5 * (zs[z_index] + zs[z_index + 1])
            radial = (centre_x / FIELD_RADIUS_X_MM) ** 2 + (
                centre_z / FIELD_RADIUS_Z_MM
            ) ** 2
            if radial <= 1.0:
                cells.append((x_index, z_index))

    point_indices = {}
    points = []

    def point(x_index, depth_index, z_index):
        key = (x_index, depth_index, z_index)
        if key not in point_indices:
            x_mm = xs[x_index]
            z_mm = zs[z_index]
            y_mm = chest_surface_y_mm(x_mm, z_mm) + depths[depth_index]
            point_indices[key] = len(points)
            points.append([x_mm, y_mm, z_mm])
        return point_indices[key]

    tetrahedra = []
    for x_index, z_index in cells:
        for depth_index in range(GRID_Y - 1):
            v000 = point(x_index, depth_index, z_index)
            v100 = point(x_index + 1, depth_index, z_index)
            v010 = point(x_index, depth_index + 1, z_index)
            v110 = point(x_index + 1, depth_index + 1, z_index)
            v001 = point(x_index, depth_index, z_index + 1)
            v101 = point(x_index + 1, depth_index, z_index + 1)
            v011 = point(x_index, depth_index + 1, z_index + 1)
            v111 = point(x_index + 1, depth_index + 1, z_index + 1)
            tetrahedra.extend(
                [
                    [v000, v100, v110, v111],
                    [v000, v110, v010, v111],
                    [v000, v010, v011, v111],
                    [v000, v011, v001, v111],
                    [v000, v001, v101, v111],
                    [v000, v101, v100, v111],
                ]
            )

    fixed = []
    for (x_index, depth_index, z_index), index in point_indices.items():
        radial = (xs[x_index] / FIELD_RADIUS_X_MM) ** 2 + (
            zs[z_index] / FIELD_RADIUS_Z_MM
        ) ** 2
        if radial >= 0.82 or (fix_bottom and depth_index == GRID_Y - 1):
            fixed.append(index)
    return points, tetrahedra, sorted(set(fixed))


def _add_layer(layers, name, specification, fix_bottom=False):
    points, tetrahedra, fixed = _layer_mesh(
        specification["top"], specification["bottom"], fix_bottom=fix_bottom
    )
    tissue = layers.addChild(name)
    tissue.addObject("EulerImplicitSolver", rayleighStiffness=0.12, rayleighMass=0.08)
    tissue.addObject(
        "SparseLDLSolver",
        name="linearSolver",
        template="CompressedRowSparseMatrixMat3x3d",
    )
    tissue.addObject("MechanicalObject", name="dofs", position=points)
    tissue.addObject(
        "TetrahedronSetTopologyContainer",
        name="topology",
        position=points,
        tetrahedra=tetrahedra,
    )
    tissue.addObject("TetrahedronSetTopologyModifier", name="modifier")
    tissue.addObject("TetrahedronSetGeometryAlgorithms", template="Vec3d")
    tissue.addObject("DiagonalMass", massDensity=1e-6)
    tissue.addObject("FixedProjectiveConstraint", indices=fixed)
    tissue.addObject(
        "TetrahedralCorotationalFEMForceField",
        name="fem",
        youngModulus=specification["young"],
        poissonRatio=0.45,
        method="large",
    )
    tissue.addObject("LinearSolverConstraintCorrection")

    surface = tissue.addChild("surface")
    surface.addObject("TriangleSetTopologyContainer", name="topology")
    surface.addObject("TriangleSetTopologyModifier", name="modifier")
    surface.addObject("TriangleSetGeometryAlgorithms", template="Vec3d")
    surface.addObject(
        "Tetra2TriangleTopologicalMapping", input="@../topology", output="@topology"
    )
    surface.addObject(
        "TriangleCollisionModel",
        name="triangles",
        contactStiffness=0.8,
        group=1,
        tags="CarvingSurface",
    )
    surface.addObject(
        "PointCollisionModel",
        name="points",
        contactStiffness=0.8,
        group=1,
        tags="CarvingSurface",
    )
    return tissue


def _add_tool(root):
    tool = root.addChild("tool")
    tool.addObject(
        "MechanicalObject",
        template="Rigid3d",
        name="dofs",
        position=[[0.0, 18.0, 0.0, 0.0, 0.0, 0.0, 1.0]],
    )

    blade = tool.addChild("blade")
    blade.addObject(
        "MechanicalObject", template="Vec3d", name="dofs", position=SCALPEL_CUTTING_EDGE_MM
    )
    blade.addObject(
        "EdgeSetTopologyContainer", name="topology", edges=SCALPEL_CUTTING_EDGE_SEGMENTS
    )
    blade.addObject(
        "LineCollisionModel",
        name="edge",
        simulated=False,
        moving=True,
        group=2,
        tags="CarvingTool",
    )
    blade.addObject(
        "SphereCollisionModel",
        name="thickness",
        radius=0.28,
        simulated=False,
        moving=True,
        group=2,
    )
    blade.addObject("RigidMapping", input="@../dofs", output="@dofs")

    blunt = tool.addChild("blunt")
    blunt.addObject(
        "MechanicalObject",
        template="Vec3d",
        name="dofs",
        position=[[-1.8, 0.0, 0.0], [1.8, 0.0, 0.0]],
    )
    blunt.addObject(
        "SphereCollisionModel",
        name="tips",
        radius=2.2,
        simulated=False,
        moving=True,
        active=False,
        group=2,
        tags="BluntTool",
    )
    blunt.addObject("RigidMapping", input="@../dofs", output="@dofs")

    tube = tool.addChild("tube")
    tube.addObject(
        "MechanicalObject", template="Vec3d", name="dofs", position=[[0.0, 0.0, 0.0]]
    )
    tube.addObject(
        "SphereCollisionModel",
        name="tip",
        radius=3.2,
        simulated=False,
        moving=True,
        active=False,
        group=2,
    )
    tube.addObject("RigidMapping", input="@../dofs", output="@dofs")
    return tool


def _add_protected_anatomy(root):
    """Add non-carvable rib collision bands beneath the active field."""
    ribs = root.addChild("protectedAnatomy")
    positions = []
    for z_mm in RIB_CENTRES_Z_MM:
        for x_mm in _linspace(-35.0, 35.0, 9):
            positions.append(
                [
                    x_mm,
                    chest_surface_y_mm(x_mm, z_mm)
                    + RIB_TOP_DEPTH_MM
                    - RIB_RADIUS_MM,
                    z_mm,
                ]
            )
    ribs.addObject("MechanicalObject", template="Vec3d", name="dofs", position=positions)
    ribs.addObject(
        "SphereCollisionModel",
        name="ribs",
        radius=RIB_RADIUS_MM,
        simulated=False,
        moving=False,
        # Share the tissue group so the fixed rib samples do not collide with
        # the layers that surround them; the moving tool remains group 2.
        group=1,
        tags="ProtectedAnatomy",
    )
    return ribs


def _add_body_contact_shell(root):
    positions = []
    for (x_bin, z_bin), surface_y in anatomy_surface_samples().items():
        x_mm = x_bin * ANATOMY_BIN_MM
        z_mm = z_bin * ANATOMY_BIN_MM
        if (x_mm / 28.0) ** 2 + (z_mm / 20.0) ** 2 <= 1.0:
            continue
        positions.append([x_mm, surface_y - BODY_CONTACT_RADIUS_MM, z_mm])
    if not positions:
        return None
    shell = root.addChild("bodyContactShell")
    shell.addObject("EulerImplicitSolver")
    shell.addObject(
        "SparseLDLSolver",
        name="linearSolver",
        template="CompressedRowSparseMatrixMat3x3d",
    )
    shell.addObject("MechanicalObject", template="Vec3d", name="dofs", position=positions)
    shell.addObject("UniformMass", totalMass=0.001)
    shell.addObject(
        "RestShapeSpringsForceField",
        points=list(range(len(positions))),
        stiffness=0.25,
        angularStiffness=0.0,
    )
    shell.addObject(
        "SphereCollisionModel",
        name="skin",
        radius=BODY_CONTACT_RADIUS_MM,
        simulated=True,
        moving=False,
        group=1,
        tags="BodyContact",
    )
    shell.addObject("LinearSolverConstraintCorrection")
    return shell


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
            "Sofa.Component.LinearSolver.Direct",
            "Sofa.Component.Mapping.Linear",
            "Sofa.Component.Mapping.NonLinear",
            "Sofa.Component.Mass",
            "Sofa.Component.ODESolver.Backward",
            "Sofa.Component.SolidMechanics.FEM.Elastic",
            "Sofa.Component.SolidMechanics.Spring",
            "Sofa.Component.StateContainer",
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
        "CollisionResponse", response="FrictionContactConstraint", responseParams="mu=0.08"
    )

    layers = root.addChild("layers")
    for name, specification in LAYER_SPECS.items():
        _add_layer(layers, name, specification, fix_bottom=(name == "pleura"))
    _add_body_contact_shell(root)
    _add_protected_anatomy(root)
    _add_tool(root)

    root.addObject(
        "CarvingManager",
        name="carveSkin",
        active=carving_active,
        carvingDistance=0.25,
        narrowPhaseDetection="@narrowPhase",
        toolModel="@tool/blade/edge",
        surfaceModelPath="/layers/skin/surface/triangles",
    )
    root.addObject(
        "CarvingManager",
        name="carveSubcutaneous",
        active=False,
        carvingDistance=0.25,
        narrowPhaseDetection="@narrowPhase",
        toolModel="@tool/blunt/tips",
        surfaceModelPath="/layers/subcutaneous/surface/triangles",
    )
    root.addObject(
        "CarvingManager",
        name="carveMuscle",
        active=False,
        carvingDistance=0.25,
        narrowPhaseDetection="@narrowPhase",
        toolModel="@tool/blunt/tips",
        surfaceModelPath="/layers/muscle/surface/triangles",
    )
    root.addObject(
        "CarvingManager",
        name="carvePleura",
        active=False,
        carvingDistance=0.25,
        narrowPhaseDetection="@narrowPhase",
        toolModel="@tool/blade/edge",
        surfaceModelPath="/layers/pleura/surface/triangles",
    )
    return root
