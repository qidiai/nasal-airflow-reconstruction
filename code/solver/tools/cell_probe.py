"""单元邻域细查：polyMesh + fields npz -> 打印 cell 及其邻接的 p/U/几何。

用法: python cell_probe.py <polyMesh dir> <fields.npz> <cell> [<cell> ...]
"""
import sys
import numpy as np
from mesh_layers import read_points, read_faces, read_int_field


def build(meshdir):
    pts = read_points(meshdir + r"\points")
    faces = read_faces(meshdir + r"\faces")
    owner = np.array(read_int_field(meshdir + r"\owner"))
    neigh = np.array(read_int_field(meshdir + r"\neighbour"))
    ncells = max(owner.max(), neigh.max()) + 1
    ni = len(neigh)
    sf = np.zeros((len(faces), 3))
    mag = np.zeros(len(faces))
    for f, nodes in enumerate(faces):
        sx = sy = sz = 0.0
        m = len(nodes)
        for i in range(m):
            a = pts[nodes[i]]
            b = pts[nodes[(i + 1) % m]]
            sx += 0.5 * (a[1] * b[2] - a[2] * b[1])
            sy += 0.5 * (a[2] * b[0] - a[0] * b[2])
            sz += 0.5 * (a[0] * b[1] - a[1] * b[0])
        sf[f] = (sx, sy, sz)
        mag[f] = (sx * sx + sy * sy + sz * sz) ** 0.5
    vol = np.zeros(ncells)
    vset = [set() for _ in range(ncells)]
    for f, nodes in enumerate(faces):
        o = owner[f]
        c = np.mean([pts[k] for k in nodes], axis=0)
        v = float(np.dot(c, sf[f])) / 3.0
        vol[o] += v
        vset[o].update(nodes)
        if f < ni:
            nb = neigh[f]
            vol[nb] -= v
            vset[nb].update(nodes)
    cc = np.array([np.mean([pts[k] for k in list(vset[c])], axis=0) for c in range(ncells)])
    return dict(pts=pts, faces=faces, owner=owner, neigh=neigh, ncells=ncells, ni=ni,
                sf=sf, mag=mag, vol=vol, cc=cc)


def main(meshdir, npz, cells):
    g = build(meshdir)
    d = np.load(npz)
    U, p = d["U"], d["p"]
    owner, neigh, ni = g["owner"], g["neigh"], g["ni"]
    # 单元->面
    cf = [[] for _ in range(g["ncells"])]
    for f in range(len(owner)):
        cf[owner[f]].append((f, 1))
    for f in range(ni):
        cf[neigh[f]].append((f, -1))
    print(f"p range {p.min():.4f} .. {p.max():.4f}   |U| max {np.abs(U).max():.4f}")
    for c in cells:
        print(f"---- cell {c}  cc {g['cc'][c]}  V {g['vol'][c]:.6e}  p {p[c]:.6f}  U {U[c]}")
        for f, sgn in sorted(cf[c]):
            nb = neigh[f] if sgn > 0 else owner[f]
            if f < ni:
                print(f"   f{f:6d} nb {nb:6d} cc {g['cc'][nb]} p {p[nb]:10.6f} dp {p[nb]-p[c]:+10.6f} U {U[nb]} |Sf|{g['mag'][f]:.3e} Sf {g['sf'][f]}")
            else:
                print(f"   f{f:6d} BOUNDARY |Sf|{g['mag'][f]:.3e} Sf {g['sf'][f]}")
    # 顶速单元的 z 层邻域大小
    return g, U, p


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], [int(x) for x in sys.argv[3:]])
