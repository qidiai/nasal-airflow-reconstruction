"""WSS 口径复核：per-face d_n = V/(2A_f) vs 归档的固定 d_n = 0.488 mm。

契约 §11：tau = mu·|(I−nnᵀ)U_c| / d_n，归档 metrics 记 dn_mm_median = 0.488。
本脚本对同一速度场用两种 d_n 口径重算 mean/median/p95/max，判断 WSS 差
是「场差」还是「口径差」。

用法: python wss_probe.py <polyMesh 目录> <fields_*.vtk>
"""
import sys

import outlet_probe as op  # 复用同一套只读解析器

MU = 2.16e-5  # Pa·s


def main(meshdir, vtk):
    pts = op.read_points(meshdir + r"\points")
    faces = op.read_faces(meshdir + r"\faces")
    owner = op.read_int_field(meshdir + r"\owner")
    ncells = max(owner) + 1
    bnd = op.read_boundary(meshdir + r"\boundary")
    u, p = op.read_vtk_cells(vtk, ncells)

    # 体积（散度定理）
    vol = [0.0] * ncells
    for f, nodes in enumerate(faces):
        s = op.poly_area(pts, nodes)
        cx = sum(pts[k][0] for k in nodes) / len(nodes)
        cy = sum(pts[k][1] for k in nodes) / len(nodes)
        cz = sum(pts[k][2] for k in nodes) / len(nodes)
        v = (cx * s[0] + cy * s[1] + cz * s[2]) / 3.0
        vol[owner[f]] += v

    # 单元体心（顶点平均）与面心
    vset = [set() for _ in range(ncells)]
    for f, nodes in enumerate(faces):
        vset[owner[f]].update(nodes)
    cc = [
        [sum(pts[k][i] for k in vs) / len(vs) for i in range(3)] for vs in vset
    ]

    for name, nf, sf in bnd:
        if name != "walls":
            continue
        for tag, mode in (
            ("per-face V/(2A)", "vol"),
            ("fixed 0.488mm", "fix"),
            ("|Cf-Cc| 真实距离", "dist"),
        ):
            taus = []
            dn_list = []
            for f in range(sf, sf + nf):
                s = op.poly_area(pts, faces[f])
                mag = (s[0] ** 2 + s[1] ** 2 + s[2] ** 2) ** 0.5
                if mag <= 0:
                    continue
                nhat = [s[0] / mag, s[1] / mag, s[2] / mag]
                uc = u[owner[f]]
                un = uc[0] * nhat[0] + uc[1] * nhat[1] + uc[2] * nhat[2]
                tang = [uc[0] - un * nhat[0], uc[1] - un * nhat[1], uc[2] - un * nhat[2]]
                if mode == "fix":
                    dn = 0.488e-3
                elif mode == "vol":
                    dn = 0.5 * vol[owner[f]] / mag
                else:
                    nodes = faces[f]
                    cf = [sum(pts[k][i] for k in nodes) / len(nodes) for i in range(3)]
                    c = cc[owner[f]]
                    dn = sum((cf[i] - c[i]) ** 2 for i in range(3)) ** 0.5
                dn_list.append(dn)
                taus.append(MU * (tang[0] ** 2 + tang[1] ** 2 + tang[2] ** 2) ** 0.5 / dn)
            taus.sort()
            n = len(taus)
            dn_sorted = sorted(dn_list)
            print(
                f"walls {tag:16s}: mean {sum(taus)/n:.6f}  median {taus[n//2]:.6f}  "
                f"p95 {taus[int(0.95*n)]:.6f}  max {taus[-1]:.6f}  "
                f"dn_median {dn_sorted[n//2]*1e3:.4f} mm"
            )


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
