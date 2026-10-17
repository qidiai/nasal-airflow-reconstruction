"""沿程压力梯度诊断：找出 |grad p| 最大的单元及其几何/邻居信息。

用法: python grad_probe.py <polyMesh dir> <fields.npz> [topN]
"""
import sys
import numpy as np
from cell_probe import build


def main(meshdir, npz, topn=20):
    g = build(meshdir)
    d = np.load(npz)
    U, p = d["U"], d["p"]
    owner, neigh, ni, cc = g["owner"], g["neigh"], g["ni"], g["cc"]
    vol = g["vol"]
    # 逐面两点差分的梯度估计（每单元取最大面法向梯度与体积加权高斯梯度）
    ncell = g["ncells"]
    gsum = np.zeros((ncell, 3))
    gmax = np.zeros(ncell)
    wallcount = np.zeros(ncell, dtype=int)
    for f in range(len(owner)):
        o = owner[f]
        s = g["sf"][f]
        if f < ni:
            nb = neigh[f]
            dvec = cc[nb] - cc[o]
            dp = p[nb] - p[o]
            dd = float(dvec @ dvec)
            if dd > 0:
                gm = abs(dp) / np.sqrt(dd)
                gmax[o] = max(gmax[o], gm)
                gmax[nb] = max(gmax[nb], gm)
            gsum[o] += s * (0.5 * (p[o] + p[nb]))
            gsum[nb] -= s * (0.5 * (p[o] + p[nb]))
        else:
            gsum[o] += s * p[o]
            wallcount[o] += 1
    grad = gsum / vol[:, None]
    gmag = np.linalg.norm(grad, axis=1)
    print(f"p range {p.min():.4f}..{p.max():.4f}  |grad p| median {np.median(gmag):.3e} max {gmag.max():.3e}")
    idx = np.argsort(-gmag)[:topn]
    Umag = np.linalg.norm(U, axis=1)
    print("rank  cell    x(mm)   y(mm)   z(mm)   p        |gradp|   |U|      wallFaces  gradp dir")
    for r, c in enumerate(idx):
        print(f"{r:3d}  {c:6d} {cc[c][0]*1e3:7.2f} {cc[c][1]*1e3:7.2f} {cc[c][2]*1e3:7.2f} "
              f"{p[c]:9.4f} {gmag[c]:9.3e} {Umag[c]:8.3f}  {wallcount[c]:3d}  {grad[c]}")
    # 按 p 分层统计：p 的直方图
    hist, edges = np.histogram(p, bins=20)
    print("\np histogram (kinematic m2/s2):")
    for h, e0, e1 in zip(hist, edges[:-1], edges[1:]):
        print(f"  [{e0:9.3f},{e1:9.3f})  {h:6d}")
    # 每个 z 层的平均 p / 平均 |U|
    zs = np.unique(np.round(cc[:, 2], 6))
    print("\nz layer   ncell   p_mean    |U|mean  |U|max   gradp_mean")
    for z in zs:
        m = np.isclose(cc[:, 2], z)
        print(f"{z*1e3:8.3f} {m.sum():6d}   {p[m].mean():9.4f}  {Umag[m].mean():8.4f} {Umag[m].max():8.4f}  {gmag[m].mean():9.3e}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 20)
