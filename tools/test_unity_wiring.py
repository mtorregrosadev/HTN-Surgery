"""Static checks for the Unity package (there is no C# compiler in CI, so catch the easy mistakes here).

Run:  python -m pytest tools/test_unity_wiring.py
"""
import glob
import os
import re

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = os.path.join(ROOT, "client", "unity", "Packages", "com.surgeprep.runtime")
RUNTIME = sorted(glob.glob(os.path.join(PACKAGE, "Runtime", "**", "*.cs"), recursive=True))
EDITOR = sorted(glob.glob(os.path.join(PACKAGE, "Editor", "**", "*.cs"), recursive=True))
ALL = RUNTIME + EDITOR


def read(path):
    return open(path, encoding="utf-8").read()


def strip_code(text):
    """Blank out comments, strings and char literals with a small scanner (regexes get '//' in URLs wrong)."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        two = text[i:i + 2]
        if two == "//":
            while i < n and text[i] != chr(10):
                i += 1
        elif two == "/*":
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
        elif c == "@" and text[i + 1:i + 2] == '"' or two in ('$@', '@$') and text[i + 2:i + 3] == '"':
            i = text.index('"', i) + 1                     # verbatim string: "" is an escaped quote
            while i < n:
                if text[i] == '"':
                    if text[i + 1:i + 2] == '"':
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            out.append('""')
        elif c == '"' or (c == "$" and text[i + 1:i + 2] == '"'):
            i = text.index('"', i) + 1
            while i < n and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
            i += 1
            out.append('""')
        elif c == "'":
            i += 1
            while i < n and text[i] != "'":
                i += 2 if text[i] == "\\" else 1
            i += 1
            out.append("' '")
        else:
            out.append(c)
            i += 1
    return "".join(out)


@pytest.mark.parametrize("path", ALL, ids=lambda p: os.path.basename(p))
def test_brackets_are_balanced(path):
    code = strip_code(read(path))
    for open_char, close_char in ("{}", "()", "[]"):
        assert code.count(open_char) == code.count(close_char), f"unbalanced {open_char}{close_char} in {path}"


@pytest.mark.parametrize("path", ALL, ids=lambda p: os.path.basename(p))
def test_line_endings_are_consistent(path):
    data = open(path, "rb").read()
    crlf = data.count(b"\r\n")
    lf_only = data.count(b"\n") - crlf
    assert crlf == 0 or lf_only == 0, f"{path} mixes CRLF and LF line endings"


@pytest.mark.parametrize("path", RUNTIME, ids=lambda p: os.path.basename(p))
def test_runtime_code_does_not_use_the_editor(path):
    assert "using UnityEditor" not in read(path), "runtime scripts must compile in player builds"


@pytest.mark.parametrize("path", ALL, ids=lambda p: os.path.basename(p))
def test_namespaces_are_declared(path):
    assert re.search(r"namespace\s+SurgePrep", read(path))


def declared_fields():
    names = set()
    pattern = re.compile(r"\b(?:private|public|protected|internal)\s+(?:static\s+|readonly\s+|const\s+)*[\w<>\[\],\.]+\s+(\w+)\s*[;=]")
    for path in RUNTIME:
        names.update(pattern.findall(strip_code(read(path))))
        # [SerializeField] private float a, b;  style multi-declarations
        for group in re.findall(r"\b(?:private|public)\s+[\w<>\[\]\.]+\s+((?:\w+\s*,\s*)+\w+)\s*;", strip_code(read(path))):
            names.update(n.strip() for n in group.split(","))
    return names


def test_every_field_the_builder_sets_exists():
    fields = declared_fields()
    builder = read(os.path.join(PACKAGE, "Editor", "ChestTubeShowcaseBuilder.cs"))
    wired = re.findall(r'SetObject\(\s*\w+\s*,\s*"(\w+)"', builder)
    assert len(wired) > 10
    missing = sorted({name for name in wired if name not in fields})
    assert not missing, f"the builder sets fields that no runtime class declares: {missing}"


def test_new_camera_and_hardware_fields_are_wired():
    builder = read(os.path.join(PACKAGE, "Editor", "ChestTubeShowcaseBuilder.cs"))
    for needle in ('"headFocus"', '"tagInput"', "CreateAmbience(", "HairModelPath"):
        assert needle in builder, needle


def test_every_key_used_is_mapped_for_the_input_system():
    """ShowcaseInput.InputSystemKey returns Key.None for unmapped keys, which the Input System rejects."""
    mapped = set(re.findall(r"case KeyCode\.(\w+):\s*return Key\.", read(os.path.join(PACKAGE, "Runtime", "ShowcaseInput.cs"))))
    used = set()
    for path in RUNTIME:
        used.update(re.findall(r"ShowcaseInput\.(?:Held|Pressed)\(KeyCode\.(\w+)\)", read(path)))
    assert used, "expected to find keyboard input usage"
    assert used <= mapped, f"unmapped keys: {sorted(used - mapped)}"


def test_keys_do_not_clash_between_camera_and_manual_client():
    camera = set(re.findall(r"Pressed\(KeyCode\.(\w+)\)", read(os.path.join(PACKAGE, "Runtime", "ShowcaseExperienceController.cs"))))
    manual_text = read(os.path.join(PACKAGE, "Runtime", "UnityManualDemoClient.cs"))
    manual = set(re.findall(r"(?:Held|Pressed)\(KeyCode\.(\w+)\)", manual_text))
    shared = (camera & manual) - {"R"}
    assert not shared, f"camera and tool controls both use: {sorted(shared)}"


def test_hud_lists_every_camera_key():
    hud = read(os.path.join(PACKAGE, "Runtime", "ChestTubeShowcaseHud.cs"))
    for label in ("H / B", "T", "K", "F / C / O"):
        assert f'"{label}"' in hud


def test_components_added_by_the_builder_exist():
    builder = read(os.path.join(PACKAGE, "Editor", "ChestTubeShowcaseBuilder.cs"))
    declared = set(re.findall(r"\bclass\s+(\w+)", "\n".join(read(p) for p in RUNTIME)))
    for name in re.findall(r"AddComponent<(?:SurgePrep\.)?(\w+)>", builder):
        unity_builtin = {"Light", "Camera", "AudioListener", "ReflectionProbe", "LineRenderer", "MeshFilter", "MeshRenderer"}
        assert name in declared or name in unity_builtin, name


def test_tag_fsr_packet_fields_match_the_bridge():
    """TagFsrInput reads x, y, force, tags; the bridge must send them (extra fields are ignored by JsonUtility)."""
    unity = read(os.path.join(PACKAGE, "Runtime", "TagFsrInput.cs"))
    assert re.search(r"class Packet \{ public float x, y, force; public int tags; \}", unity)
    bridge = read(os.path.join(ROOT, "hardware", "tag_fsr_bridge.py"))
    for key in ('"x"', '"y"', '"force"', '"tags"'):
        assert key in bridge


def test_physical_inputs_share_the_controller_bound_pose_contract():
    base = read(os.path.join(PACKAGE, "Runtime", "TrackedToolInput.cs"))
    tag_fsr = read(os.path.join(PACKAGE, "Runtime", "TagFsrInput.cs"))
    client = read(os.path.join(PACKAGE, "Runtime", "UnityManualDemoClient.cs"))
    assert "abstract class TrackedToolInput" in base
    assert "TagFsrInput : TrackedToolInput" in tag_fsr
    assert "GetComponents<TrackedToolInput>()" in client
    assert 'inputMode = hardware ? "calibrated-hardware" : "pose-only"' in client


def test_optional_keijiro_tracker_is_isolated_and_six_dof():
    integration = os.path.join(PACKAGE, "Runtime", "AprilTag")
    asmdef = read(os.path.join(integration, "SurgePrep.AprilTag.asmdef"))
    tracker = read(os.path.join(integration, "AprilTagStylusInput.cs"))
    installer = read(os.path.join(PACKAGE, "Editor", "AprilTagPackageInstaller.cs"))
    builder = read(os.path.join(PACKAGE, "Editor", "ChestTubeShowcaseBuilder.cs"))
    assert '"AprilTag.Runtime"' in asmdef
    assert '"SURGE_PREP_HAS_APRILTAG"' in asmdef
    assert "tagStandard41h12" in tracker
    assert "tag.Position" in tracker and "tag.Rotation" in tracker
    assert "orientationApi" in tracker and "PositionMm" in tracker
    assert "Client.Add(PackageUrl)" in installer
    assert "AddOptionalAprilTagStylusInput(simulation)" in builder


# ---------------------------------------------------------------- generated hair mesh


HAIR = os.path.join(PACKAGE, "Runtime", "Models", "Hair", "hair.obj")


@pytest.fixture(scope="module")
def hair():
    verts, normals, faces = [], [], []
    for line in open(HAIR):
        if line.startswith("v "):
            verts.append([float(x) for x in line.split()[1:4]])
        elif line.startswith("vn "):
            normals.append([float(x) for x in line.split()[1:4]])
        elif line.startswith("f "):
            faces.append([int(p.split("/")[0]) for p in line.split()[1:4]])
    return np.array(verts), np.array(normals), np.array(faces)


def test_hair_mesh_is_well_formed(hair):
    verts, normals, faces = hair
    assert len(verts) == len(normals) > 10_000
    assert faces.min() >= 1 and faces.max() <= len(verts)
    assert np.isfinite(verts).all() and np.isfinite(normals).all()


def test_hair_sits_on_the_head_in_metres(hair):
    verts, _, _ = hair
    assert 1.40 < verts[:, 2].min() and verts[:, 2].max() < 1.75          # head height of the 1.64 m body
    assert np.abs(verts[:, 0]).max() < 0.16                              # head is about 0.16 m wide
    assert -0.30 < verts[:, 1].min() and verts[:, 1].max() < 0.10


def test_hair_does_not_cover_the_face(hair):
    """The face points toward -Y: nothing may hang below the forehead in front of the head centre."""
    verts, _, _ = hair
    front = verts[verts[:, 1] < -0.15]
    assert len(front) == 0 or front[:, 2].min() > 1.53


def test_hair_normals_are_unit_length(hair):
    _, normals, _ = hair
    assert np.linalg.norm(normals, axis=1) == pytest.approx(1.0, abs=0.01)


def test_hair_generation_is_deterministic():
    import sys
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import generate_hair as gh
    a = gh.build(300, 7)
    b = gh.build(300, 7)
    assert np.array_equal(a[0], b[0]) and np.array_equal(a[2], b[2])
    c = gh.build(300, 8)
    assert not np.array_equal(a[0], c[0])
