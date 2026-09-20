"""Generate a head of hair for the BodyParts3D skin model.

Reads bodyparts3d_highres/FJ2810_BP22617_FMA7163_Skin.obj (millimetres, Z up, face toward -Y),
grows a scalp shell plus tapered hair strands from the real scalp surface, and writes an OBJ in
METRES so Unity's default OBJ import lines it up with the anatomy (which Unity imports at 0.001).

Usage:  python tools/generate_hair.py [--strands 6000] [--seed 7] [--preview PREFIX]
"""
import argparse
import os

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIN = os.path.join(ROOT, "bodyparts3d_highres", "FJ2810_BP22617_FMA7163_Skin.obj")
OUT = os.path.join(ROOT, "client", "unity", "Packages", "com.surgeprep.runtime",
                   "Runtime", "Models", "Hair", "hair.obj")
HEAD_MIN_Z = 1450.0     # everything above the neck


def load_head():
    verts, faces = [], []
    with open(SKIN, errors="ignore") as f:
        for line in f:
            if line.startswith("v "):
                verts.append([float(x) for x in line.split()[1:4]])
            elif line.startswith("f "):
                faces.append([int(p.split("/")[0]) - 1 for p in line.split()[1:4]])
    v = np.array(verts)
    f = np.array(faces)
    keep = (v[f, 2] > HEAD_MIN_Z).all(axis=1)
    f = f[keep]
    used = np.unique(f)
    remap = -np.ones(len(v), int)
    remap[used] = np.arange(len(used))
    return v[used], remap[f]


def vertex_normals(v, f):
    fn = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    n = np.zeros_like(v)
    for k in range(3):
        np.add.at(n, f[:, k], fn)
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
    return n


def polar_angle(p, centre):
    d = p - centre
    r = np.linalg.norm(d, axis=1)
    return np.degrees(np.arccos(np.clip(d[:, 2] / np.maximum(r, 1e-9), -1, 1)))


def scalp_region(v, centre):
    """Hair covers the top of the head, lower at the back than at the forehead."""
    d = v - centre
    phi = polar_angle(v, centre)                        # 0 = straight up
    theta = np.arctan2(d[:, 0], -d[:, 1])               # 0 = facing front (-Y)
    limit = 54 + 66 * ((1 - np.cos(theta)) / 2) ** 0.9  # forehead 54, sides ~83, nape 120
    return phi < limit, phi


def lumps(p, seed):
    rng = np.random.default_rng(seed)
    k = rng.uniform(-1, 1, (3, 3)) * 0.05
    ph = rng.uniform(0, 6.28, 3)
    return np.sin(p @ k + ph).sum(axis=1) / 3


def build(strands, seed):
    rng = np.random.default_rng(seed)
    v, f = load_head()
    centre = np.array([0.0, v[v[:, 2] > 1500][:, 1].mean(), 1545.0])
    n = vertex_normals(v, f)
    in_region, phi = scalp_region(v, centre)
    sf = f[in_region[f].all(axis=1)]

    # scalp shell: offset along the normal, thicker on top and slightly lumpy
    thick = 2.5 + 7.0 * np.clip(np.cos(np.radians(phi)), 0, 1) ** 1.3 + 2.0 * lumps(v, seed)
    shell_v = v + n * thick[:, None]
    used = np.unique(sf)
    remap = -np.ones(len(v), int)
    remap[used] = np.arange(len(used))
    out_v, out_n, out_f = [shell_v[used]], [n[used]], [remap[sf]]

    # strands rooted on the scalp, area-weighted
    a, b, c = v[sf[:, 0]], v[sf[:, 1]], v[sf[:, 2]]
    area = np.linalg.norm(np.cross(b - a, c - a), axis=1)
    pick = rng.choice(len(sf), strands, p=area / area.sum())
    w = rng.dirichlet([1, 1, 1], strands)
    root = a[pick] * w[:, :1] + b[pick] * w[:, 1:2] + c[pick] * w[:, 2:]
    nrm = n[sf[pick, 0]] * w[:, :1] + n[sf[pick, 1]] * w[:, 1:2] + n[sf[pick, 2]] * w[:, 2:]
    nrm /= np.linalg.norm(nrm, axis=1, keepdims=True)
    root = root + nrm * 2.0

    # combed back from a point above the forehead, then falling with gravity
    front_top = centre + np.array([0.0, -130.0, 40.0])
    flow = root - front_top
    flow -= nrm * np.sum(flow * nrm, axis=1, keepdims=True)
    flow /= np.maximum(np.linalg.norm(flow, axis=1, keepdims=True), 1e-9)
    up_amt = np.clip(np.cos(np.radians(polar_angle(root, centre))), 0, 1)
    length = (16 + 26 * up_amt) * rng.uniform(0.75, 1.25, strands)   # long on top, short at the sides
    length *= 1 - 0.5 * np.clip((centre[1] - root[:, 1]) / 60.0, 0, 1)   # no fringe over the face
    segs = 3
    pts = np.zeros((strands, segs + 1, 3))
    pts[:, 0] = root
    d = nrm * 0.45 + flow * 0.95
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    for s in range(segs):
        d = d + np.array([0, 0, -0.55]) * (s + 1) / segs + rng.normal(0, 0.12, (strands, 3))
        d /= np.linalg.norm(d, axis=1, keepdims=True)
        pts[:, s + 1] = pts[:, s] + d * (length / segs)[:, None]

    width = np.array([1.7, 1.4, 1.0, 0.35])
    verts, normals, faces = [], [], []
    base = len(out_v[0])
    for i in range(strands):
        side = np.cross(pts[i, 1] - pts[i, 0], nrm[i])
        side /= max(np.linalg.norm(side), 1e-9)
        idx0 = base + len(verts)
        for s in range(segs + 1):
            verts.append(pts[i, s] - side * width[s] / 2)
            verts.append(pts[i, s] + side * width[s] / 2)
            normals.append(nrm[i])
            normals.append(nrm[i])
        for s in range(segs):
            p = idx0 + s * 2
            faces.append([p, p + 1, p + 2])
            faces.append([p + 1, p + 3, p + 2])
            faces.append([p, p + 2, p + 1])          # back sides so the hair shows from both faces
            faces.append([p + 1, p + 2, p + 3])
    out_v.append(np.array(verts))
    out_n.append(np.array(normals))
    out_f.append(np.array(faces))
    return np.vstack(out_v), np.vstack(out_n), np.vstack(out_f), v, f


def write_obj(path, v, n, f):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    m = v / 1000.0                                    # mm -> metres
    with open(path, "w") as o:
        o.write("# Generated by tools/generate_hair.py (metres, Z up, face toward -Y)\ng Hair\n")
        for p in m:
            o.write(f"v {p[0]:.5f} {p[1]:.5f} {p[2]:.5f}\n")
        for q in n:
            o.write(f"vn {q[0]:.3f} {q[1]:.3f} {q[2]:.3f}\n")
        for t in f + 1:
            o.write(f"f {t[0]}//{t[0]} {t[1]}//{t[1]} {t[2]}//{t[2]}\n")


def preview(path, hv, hf, sv, sf, view):
    import cv2
    size = 700
    az = np.radians(view)
    rot = np.array([[np.cos(az), -np.sin(az), 0], [np.sin(az), np.cos(az), 0], [0, 0, 1]])
    light = np.array([0.4, -0.6, 0.7])
    light /= np.linalg.norm(light)
    eye = np.array([0.0, -85.0, 1545.0])
    tris, cols = [], []
    for verts, faces, col in ((sv, sf, (170, 200, 235)), (hv, hf, (30, 45, 70))):
        q = (verts - eye) @ rot.T
        p2 = np.stack([size / 2 + q[:, 0] * 2.2, size / 2 - q[:, 2] * 2.2], 1)
        a, b, c = verts[faces[:, 0]], verts[faces[:, 1]], verts[faces[:, 2]]
        nn = np.cross(b - a, c - a)
        nn /= np.maximum(np.linalg.norm(nn, axis=1, keepdims=True), 1e-9)
        shade = 0.55 + 0.45 * np.abs(nn @ (rot.T @ light))
        for k in range(len(faces)):
            tris.append((q[faces[k], 1].mean(), p2[faces[k]], shade[k], col))
    tris.sort(key=lambda t: -t[0])                      # far to near, skin and hair together
    img = np.full((size, size, 3), 235, np.uint8)
    for _, pts, shade, col in tris:
        cv2.fillConvexPoly(img, pts.astype(np.int32), tuple(int(x * shade) for x in col))
    cv2.imwrite(path, img)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--strands", type=int, default=6000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--preview", help="write preview PNGs with this prefix (needs opencv)")
    args = ap.parse_args()
    hv, hn, hf, sv, sf = build(args.strands, args.seed)
    write_obj(OUT, hv, hn, hf)
    print(f"wrote {OUT}: {len(hv)} vertices, {len(hf)} triangles")
    if args.preview:
        for name, ang in (("front", 0), ("side", 90), ("back", 180), ("threeq", 45)):
            preview(f"{args.preview}_{name}.png", hv, hf, sv, sf, ang)
