"""L2 场对拍：我方求解器场 vs 归档 OpenFOAM VTK 场（逐 cell）。

对齐策略：同一条 polyMesh → 单元顺序一致（owner 升序）。脚本先按
「单元体心（顶点平均）」逐 cell 核对两侧几何是否同一网格（最大体心偏差），
再算 Pearson 相关：
  - 速度场：三分类（x/y/z 三分量拼接）全网格
  - 速度场：仅「流动区」（归档 |U| > 阈值，默认 0.01 m/s，剔除死端静止细胞）
  - 速度模长 |U|
  - 压力场（运动学，m²/s²）

用法:
  python l2_compare.py <polyMesh 目录> <我方 fields_*.vtk> <归档 internal.vtu>
只读，不写文件。
"""
import sys

import numpy as np

import outlet_probe as op
import vtu_read


def cell_centres(pts, faces, owner, ncells):
    """顶点平均体心（与 OpenFOAM 六面体一致）。"""
    acc = np.zeros((ncells, 3))
    cnt = np.zeros(ncells)
    for f, nodes in enumerate(faces):
        c = owner[f]
        for k in nodes:
            acc[c] += pts[k]
        cnt[c] += len(nodes)
    return acc / cnt[:, None]


def vtu_cell_centres(vtu):
    pts = np.asarray(vtu["points"], dtype=np.float64)
    conn = np.asarray(vtu["connectivity"], dtype=np.int64)
    offs = np.asarray(vtu["offsets"], dtype=np.int64)
    ncells = vtu["n_cells"]
    cen = np.empty((ncells, 3))
    start = 0
    for c in range(ncells):
        end = offs[c]
        ids = conn[start:end]
        start = end
        cen[c] = pts[ids].mean(axis=0)
    return cen


def pearson(a, b):
    a = a.ravel().astype(np.float64)
    b = b.ravel().astype(np.float64)
    a = a - a.mean()
    b = b - b.mean()
    den = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / den) if den > 0 else float("nan")


def main(meshdir, our_vtk, arch_vtu):
    pts = np.asarray(op.read_points(meshdir + r"\points"), dtype=np.float64)
    faces = op.read_faces(meshdir + r"\faces")
    owner = np.asarray(op.read_int_field(meshdir + r"\owner"), dtype=np.int64)
    ncells = int(owner.max()) + 1

    u_our, p_our = op.read_vtk_cells(our_vtk, ncells)
    u_our = np.asarray(u_our, dtype=np.float64)
    p_our = np.asarray(p_our, dtype=np.float64)

    vtu = vtu_read.read_vtu(arch_vtu)
    assert vtu["n_cells"] == ncells, f"cell 数不一致 {vtu['n_cells']} vs {ncells}"
    u_of = np.asarray(vtu["cell"]["U"], dtype=np.float64)
    p_of = np.asarray(vtu["cell"]["p"], dtype=np.float64)

    cc = cell_centres(pts, faces, owner, ncells)
    cc_of = vtu_cell_centres(vtu)
    dev = np.linalg.norm(cc - cc_of, axis=1)
    print(f"cells {ncells}  | centre deviation max {dev.max():.3e} m  mean {dev.mean():.3e} m")
    if dev.max() > 1e-6:
        print("WARNING: 体心不对应，单元顺序或网格不一致 → 结果不可信")

    mag_our = np.linalg.norm(u_our, axis=1)
    mag_of = np.linalg.norm(u_of, axis=1)
    flowing = mag_of > 0.01

    print("\n=== Pearson 相关 ===")
    print(f"U (3 comps, all cells)      : {pearson(u_our, u_of):.6f}")
    print(f"U (3 comps, flowing |U|>1cm/s): {pearson(u_our[flowing], u_of[flowing]):.6f}"
          f"   ({flowing.sum()}/{ncells} cells)")
    print(f"|U| (all cells)             : {pearson(mag_our, mag_of):.6f}")
    print(f"|U| (flowing)               : {pearson(mag_our[flowing], mag_of[flowing]):.6f}")
    print(f"p (all cells)               : {pearson(p_our, p_of):.6f}")
    print(f"p (flowing)                 : {pearson(p_our[flowing], p_of[flowing]):.6f}")

    # 半方差式相对误差
    rel = np.linalg.norm(u_our - u_of) / np.linalg.norm(u_of)
    print(f"\n||U_our-U_of|| / ||U_of||   : {rel*100:.2f}%")
    print(f"max |U| our {mag_our.max():.4f} @ cell {mag_our.argmax()}  "
          f"of {mag_of.max():.4f} @ cell {mag_of.argmax()}")
    print(f"max |p| our {np.abs(p_our).max():.4f}  of {np.abs(p_of).max():.4f}")

    # 低相关区定位：按 |ΔU| 排序取前 10 个单元
    du = np.linalg.norm(u_our - u_of, axis=1)
    order = np.argsort(-du)[:10]
    print("\n最大偏差 cell（坐标 mm，|U|our / |U|of，|ΔU|）：")
    for c in order:
        print(f"  cell {c:6d}  ({cc[c][0]*1e3:7.2f},{cc[c][1]*1e3:7.2f},{cc[c][2]*1e3:7.2f})  "
              f"{mag_our[c]:9.4f} / {mag_of[c]:9.4f}   dU {du[c]:9.4f}")

    # 分层相关（按归档 |U| 分位）
    print("\n分层 Pearson（按归档 |U| 分位，等细胞数）：")
    qs = np.quantile(mag_of, [0.2, 0.4, 0.6, 0.8])
    bins = np.digitize(mag_of, qs)
    for b in range(5):
        m = bins == b
        if m.sum() > 10:
            print(f"  bin{b} |U|of {mag_of[m].min():.4f}-{mag_of[m].max():.4f} "
                  f"({m.sum():6d} cells)  U r={pearson(u_our[m], u_of[m]):.5f}  "
                  f"p r={pearson(p_our[m], p_of[m]):.5f}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
