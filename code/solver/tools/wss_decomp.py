"""WSS 口径归因（T3）：用**归档自己的**速度场重算 d_n 口径，
与归档 wallShearStress 场逐面对比 → 判定「口径差」还是「场差」。

几何口径逐位复刻 `solver/src/mesh.rs`（见 wss_modes.build_geometry）。
归档 wallShearStress 场 = OpenFOAM 自己的壁面切应力（baseline27 metrics.json 的 wss 即此值）。

用法:
  python wss_decomp.py <polyMesh> <归档 U> <归档 wallShearStress> [我方 fields_*.vtk]
"""
import sys

import numpy as np

import of_wss_stats
import outlet_probe as op
import wss_modes

MU = 2.16e-5


def read_of_vector_field(path):
    txt = open(path, "r", encoding="utf-8", errors="replace").read()
    i = txt.index("internalField")
    body = txt[i:]
    n = int(body[body.index("List<vector>") + len("List<vector>"):].split("(")[0].split()[0])
    start = body.index("(", body.index(str(n)))
    vals = []
    for tok in body[start + 1:].split(")"):
        tok = tok.strip().strip("(")
        parts = tok.split()
        if len(parts) != 3:
            break
        vals.append([float(x) for x in parts])
        if len(vals) == n:
            break
    assert len(vals) == n, f"解析到 {len(vals)} / {n}"
    return np.array(vals)


def main(meshdir, ufile, wssfile, our_vtk=None):
    pts = np.asarray(op.read_points(meshdir + r"\points"), dtype=np.float64)
    faces = op.read_faces(meshdir + r"\faces")
    owner = np.asarray(op.read_int_field(meshdir + r"\owner"), dtype=np.int64)
    neigh = np.asarray(op.read_int_field(meshdir + r"\neighbour"), dtype=np.int64)
    ncells = int(owner.max()) + 1
    bnd = op.read_boundary(meshdir + r"\boundary")
    _, nf, sf = [b for b in bnd if b[0] == "walls"][0]

    U = read_of_vector_field(ufile)
    tau_of = of_wss_stats.read_patch_vectors(wssfile)
    mag_of = np.linalg.norm(tau_of, axis=1)
    assert len(mag_of) == nf

    face_cf, cc, vol, _ = wss_modes.build_geometry(pts, faces, owner, ncells, neigh)

    def wss(field):
        out = np.empty(nf)
        dns = np.empty(nf)
        for k, f in enumerate(range(sf, sf + nf)):
            nodes = faces[f]
            s = np.asarray(op.poly_area(pts, nodes))
            mag = np.linalg.norm(s)
            nhat = s / mag
            c = owner[f]
            uc = field[c]
            ut = uc - np.dot(uc, nhat) * nhat
            dn = np.linalg.norm(face_cf[f] - cc[c])
            dns[k] = dn
            out[k] = MU * np.linalg.norm(ut) / max(dn, 1e-300)
        return out, dns

    tau_A, dns = wss(U)

    def line(name, v):
        print(f"{name:22s} {v.mean():10.6f} {np.median(v):10.6f} "
              f"{np.quantile(v,0.95):10.6f} {v.max():10.6f}")

    print(f"{'case':22s} {'mean':>10s} {'median':>10s} {'p95':>10s} {'max':>10s}")
    line("OF wallShearStress", mag_of)
    line("A |Cf-Cc| on OF field", tau_A)
    print(f"  mean ratio A/OF {tau_A.mean()/mag_of.mean():.4f}   "
          f"Pearson {np.corrcoef(tau_A, mag_of)[0,1]:.5f}   "
          f"median ratio {np.median(tau_A)/np.median(mag_of):.4f}")
    print(f"  dn median {np.median(dns)*1e3:.4f} mm")

    if our_vtk:
        u_our, _ = op.read_vtk_cells(our_vtk, ncells)
        u_our = np.asarray(u_our, dtype=np.float64)
        tau_our, _ = wss(u_our)
        line("OUR solver, same formula", tau_our)
        print(f"  our/A(OF) mean {tau_our.mean()/tau_A.mean():.4f}   "
              f"Pearson {np.corrcoef(tau_our, mag_of)[0,1]:.5f}")
        # 纯场差：同一批面，比较近壁切向速度
        ut_of = np.empty(nf)
        ut_our = np.empty(nf)
        for k, f in enumerate(range(sf, sf + nf)):
            nodes = faces[f]
            s = np.asarray(op.poly_area(pts, nodes))
            nhat = s / np.linalg.norm(s)
            c = owner[f]
            ut_of[k] = np.linalg.norm(U[c] - np.dot(U[c], nhat) * nhat)
            ut_our[k] = np.linalg.norm(u_our[c] - np.dot(u_our[c], nhat) * nhat)
        print(f"  |U_t| mean: OF {ut_of.mean():.6f}  ours {ut_our.mean():.6f}  "
              f"ratio {ut_our.mean()/ut_of.mean():.4f}  "
              f"Pearson {np.corrcoef(ut_our, ut_of)[0,1]:.5f}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None)
