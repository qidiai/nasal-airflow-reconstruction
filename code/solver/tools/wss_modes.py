"""WSS 多口径计算（我方场）：d_n = |Cf−Cc| / nf·(Cf−Cc) / V/(2A) / 固定 0.488 mm。

几何口径**逐位复刻** `solver/src/mesh.rs`：
  - face_cf = 三角扇面积加权重心（polygon_centroid）
  - cell_cc = tet 分解体积重心（c0 = 该单元各面 face_cf 的算术平均）
这样 mode A 应精确复现求解器打印的 WSS mean，可用于交叉验证。

用法:
  python wss_modes.py <polyMesh 目录> <我方 fields_*.vtk> [--of-wss <file>]
"""
import sys

import numpy as np

import of_wss_stats
import outlet_probe as op

MU = 2.16e-5


def polygon_centroid(pts, nodes):
    m = len(nodes)
    if m < 3:
        return pts[nodes].mean(axis=0)
    p0 = pts[nodes[0]]
    c = np.zeros(3)
    a_sum = 0.0
    for i in range(1, m - 1):
        p1 = pts[nodes[i]]
        p2 = pts[nodes[i + 1]]
        cr = np.cross(p1 - p0, p2 - p0)
        a = 0.5 * np.linalg.norm(cr)
        c += a * (p0 + p1 + p2) / 3.0
        a_sum += a
    return c / a_sum if a_sum > 0 else p0


def build_geometry(pts, faces, owner, ncells, neighbour=None):
    face_cf = np.array([polygon_centroid(pts, nd) for nd in faces])
    # 每单元的面列表：owner 覆盖全部面，内部面还要登记到 neighbour 单元
    cell_faces = [[] for _ in range(ncells)]
    for f, o in enumerate(owner):
        cell_faces[o].append(f)
    if neighbour is not None:
        for f, n in enumerate(neighbour):
            if n >= 0:
                cell_faces[n].append(f)
    cc = np.zeros((ncells, 3))
    vol = np.zeros(ncells)
    for c in range(ncells):
        fl = cell_faces[c]
        c0 = face_cf[fl].mean(axis=0) if fl else np.zeros(3)
        csum = np.zeros(3)
        vsum = 0.0
        v = 0.0
        for f in fl:
            nodes = faces[f]
            if len(nodes) < 3:
                continue
            s = np.asarray(op.poly_area(pts, nodes))
            v += np.dot(s, face_cf[f]) / 3.0
            for i in range(1, len(nodes) - 1):
                a = pts[nodes[i]]
                b = pts[nodes[i + 1]]
                d = pts[nodes[0]]
                vt = abs(np.dot(np.cross(a - c0, b - c0), d - c0)) / 6.0
                ct = (c0 + a + b + d) / 4.0
                csum += vt * ct
                vsum += vt
        vol[c] = abs(v)
        cc[c] = csum / vsum if vsum > 0 else c0
    return face_cf, cc, vol, cell_faces


def main(meshdir, vtk, of_wss=None):
    pts = np.asarray(op.read_points(meshdir + r"\points"), dtype=np.float64)
    faces = op.read_faces(meshdir + r"\faces")
    owner = np.asarray(op.read_int_field(meshdir + r"\owner"), dtype=np.int64)
    ncells = int(owner.max()) + 1
    neighbour = np.asarray(op.read_int_field(meshdir + r"\neighbour"), dtype=np.int64)
    bnd = op.read_boundary(meshdir + r"\boundary")
    _, nf, sf = [b for b in bnd if b[0] == "walls"][0]
    u, _ = op.read_vtk_cells(vtk, ncells)
    u = np.asarray(u, dtype=np.float64)

    face_cf, cc, vol, _ = build_geometry(pts, faces, owner, ncells, neighbour)

    keys = ["A |Cf-Cc|", "B nf.(Cf-Cc)", "C V/(2A)", "D fixed 0.488mm"]
    vals = {k: np.empty(nf) for k in keys}
    areas = np.empty(nf)
    for k, f in enumerate(range(sf, sf + nf)):
        nodes = faces[f]
        s = np.asarray(op.poly_area(pts, nodes))
        mag = np.linalg.norm(s)
        areas[k] = mag
        nhat = s / mag if mag > 0 else np.array([1.0, 0, 0])
        c = owner[f]
        uc = u[c]
        ut = uc - np.dot(uc, nhat) * nhat
        m = np.linalg.norm(ut)
        dvec = face_cf[f] - cc[c]
        dn = {"A |Cf-Cc|": np.linalg.norm(dvec),
              "B nf.(Cf-Cc)": abs(np.dot(nhat, dvec)),
              "C V/(2A)": 0.5 * vol[c] / mag,
              "D fixed 0.488mm": 0.488e-3}
        for key, d in dn.items():
            vals[key][k] = MU * m / max(d, 1e-300)

    print(f"walls faces {nf}")
    print(f"{'mode':18s} {'mean':>10s} {'median':>10s} {'p95':>10s} {'max':>10s} {'areaMean':>10s}")
    for k in keys:
        v = vals[k]
        print(f"{k:18s} {v.mean():10.6f} {np.median(v):10.6f} {np.quantile(v,0.95):10.6f} "
              f"{v.max():10.6f} {(v*areas).sum()/areas.sum():10.6f}")

    if of_wss:
        tau_of = of_wss_stats.read_patch_vectors(of_wss)
        mag_of = np.linalg.norm(tau_of, axis=1)
        print(f"\n{'OF field':18s} {mag_of.mean():10.6f} {np.median(mag_of):10.6f} "
              f"{np.quantile(mag_of,0.95):10.6f} {mag_of.max():10.6f}")
        for k in keys:
            v = vals[k]
            print(f"  {k:16s} mean ratio {v.mean()/mag_of.mean():.4f}  "
                  f"Pearson {np.corrcoef(v, mag_of)[0,1]:.5f}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    of = None
    if "--of-wss" in sys.argv:
        of = sys.argv[sys.argv.index("--of-wss") + 1]
    main(args[0], args[1], of)
