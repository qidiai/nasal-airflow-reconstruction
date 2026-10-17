"""第六棒 T2：L2 场相关（只读）。

实际算例映射（由 log 的 cells/patch 面数与归档 metrics 逐项对上）：
  l2-pN1-1500  -> pipeline/out/*/P0-result-pN-v1   (baseline27/case-001, 53747 cells)
  l2-pN2-1500  -> pipeline/out/*/P0-result-pN2-v1  (baseline27/case-002, 87975 cells)

任务书写的 case-006 与本次实际产物不符：case-006 是 pN6（26884 cells），
而 l2-pN1/pN2 分别是 case-001/case-002。归档 OpenFOAM VTK 在仓库内已有
（pipeline/out/结果/P0-result-pN*-v1/VTK/.../internal.vtu），无需 G 盘仓库外路径。

对齐：同一条 polyMesh 的 owner 顺序；先逐 cell 核对体心偏差，再算 Pearson。
气道区域口径：归档 |U| > 0.01 m/s 的细胞（l2_compare.py 既有口径）。

用法: python tools/round6_l2.py [--json PATH]
"""
import glob
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import l2_compare as l2
import outlet_probe as op
import vtu_read

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")


def load_case(tag, result_dir):
    meshdir = os.path.join(result_dir, "constant", "polyMesh")
    our_vtk = os.path.join(OUT, tag, "fields_500.vtk")
    vtus = glob.glob(os.path.join(result_dir, "VTK", "*", "internal.vtu"))
    assert len(vtus) == 1, vtus
    arch_vtu = vtus[0]

    pts = np.asarray(op.read_points(os.path.join(meshdir, "points")), dtype=np.float64)
    faces = op.read_faces(os.path.join(meshdir, "faces"))
    owner = np.asarray(op.read_int_field(os.path.join(meshdir, "owner")), dtype=np.int64)
    ncells = int(owner.max()) + 1
    bnd = op.read_boundary(os.path.join(meshdir, "boundary"))

    u_our, p_our = op.read_vtk_cells(our_vtk, ncells)
    u_our = np.asarray(u_our, dtype=np.float64)
    p_our = np.asarray(p_our, dtype=np.float64)
    vtu = vtu_read.read_vtu(arch_vtu)
    assert vtu["n_cells"] == ncells, (vtu["n_cells"], ncells)
    u_of = np.asarray(vtu["cell"]["U"], dtype=np.float64)
    p_of = np.asarray(vtu["cell"]["p"], dtype=np.float64)

    cc = l2.cell_centres(pts, faces, owner, ncells)
    # VTU 的 polyhedron connectivity 每个顶点只出现一次；上面按面遍历会重复计权共享顶点。
    # 用去重顶点集再算一次体心，验证"偏差来自计权方式"而不是单元错位。
    vset = [set() for _ in range(ncells)]
    for f, nodes in enumerate(faces):
        vset[owner[f]].update(nodes)
    cc_unique = np.array([pts[list(vs)].mean(axis=0) for vs in vset])
    cc_of = l2.vtu_cell_centres(vtu)
    dev = np.linalg.norm(cc - cc_of, axis=1)
    dev_unique = np.linalg.norm(cc_unique - cc_of, axis=1)
    mag_our = np.linalg.norm(u_our, axis=1)
    mag_of = np.linalg.norm(u_of, axis=1)
    flowing = mag_of > 0.01

    def corr(a, b):
        return l2.pearson(a, b)

    du = np.linalg.norm(u_our - u_of, axis=1)
    order = np.argsort(-du)[:10]
    top = []
    for c in order:
        top.append({
            "cell": int(c),
            "xyz_mm": [float(x * 1e3) for x in cc[c]],
            "U_our": float(mag_our[c]),
            "U_of": float(mag_of[c]),
            "dU": float(du[c]),
        })

    qs = np.quantile(mag_of, [0.2, 0.4, 0.6, 0.8])
    bins = np.digitize(mag_of, qs)
    binned = []
    for b in range(5):
        m = bins == b
        if m.sum() > 10:
            binned.append({
                "bin": b,
                "U_of_range": [float(mag_of[m].min()), float(mag_of[m].max())],
                "cells": int(m.sum()),
                "r_U": float(corr(u_our[m], u_of[m])),
                "r_p": float(corr(p_our[m], p_of[m])),
            })

    res = {
        "tag": tag,
        "result_dir": os.path.relpath(result_dir, ROOT),
        "our_vtk": os.path.relpath(our_vtk, ROOT),
        "arch_vtu": os.path.relpath(arch_vtu, ROOT),
        "cells": ncells,
        "patches": {n: nf for n, nf, _ in bnd},
        "centre_dev_max_m": float(dev.max()),
        "centre_dev_unique_max_m": float(dev_unique.max()),
        "r_U_all": float(corr(u_our, u_of)),
        "r_U_flowing": float(corr(u_our[flowing], u_of[flowing])),
        "flowing_cells": int(flowing.sum()),
        "r_mag_all": float(corr(mag_our, mag_of)),
        "r_mag_flowing": float(corr(mag_our[flowing], mag_of[flowing])),
        "r_p_all": float(corr(p_our, p_of)),
        "r_p_flowing": float(corr(p_our[flowing], p_of[flowing])),
        "rel_norm_U_pct": float(np.linalg.norm(u_our - u_of) / np.linalg.norm(u_of) * 100.0),
        "Umax_our": float(mag_our.max()),
        "Umax_of": float(mag_of.max()),
        "Umax_cell_our": int(mag_our.argmax()),
        "Umax_cell_of": int(mag_of.argmax()),
        "top_dev_cells": top,
        "bins": binned,
    }
    return res


def main():
    results = []
    for tag, rdir_pat in (("l2-pN1-1500", "P0-result-pN-v1"),
                          ("l2-pN2-1500", "P0-result-pN2-v1")):
        cands = glob.glob(os.path.join(ROOT, "..", "pipeline", "out", "*", rdir_pat))
        assert len(cands) == 1, (rdir_pat, cands)
        r = load_case(tag, cands[0])
        results.append(r)

        print(f"=== {tag}  ({r['cells']} cells, {r['result_dir']})")
        print(f"  体心偏差 max {r['centre_dev_max_m']:.3e} m "
              f"（去重顶点复算 {r['centre_dev_unique_max_m']:.3e} m）")
        print(f"  U (3 comps, all)       r = {r['r_U_all']:.6f}")
        print(f"  U (3 comps, flowing)   r = {r['r_U_flowing']:.6f}  "
              f"({r['flowing_cells']}/{r['cells']} cells, |U_of|>1cm/s)")
        print(f"  |U| all / flowing      r = {r['r_mag_all']:.6f} / {r['r_mag_flowing']:.6f}")
        print(f"  p   all / flowing      r = {r['r_p_all']:.6f} / {r['r_p_flowing']:.6f}")
        print(f"  ||U_our-U_of||/||U_of|| = {r['rel_norm_U_pct']:.2f}%")
        print(f"  Umax our {r['Umax_our']:.4f} @ {r['Umax_cell_our']}  "
              f"of {r['Umax_of']:.4f} @ {r['Umax_cell_of']}")
        print("  最大偏差 cell（坐标 mm，|U|our / |U|of，dU）：")
        for t in r["top_dev_cells"]:
            print(f"    cell {t['cell']:6d} ({t['xyz_mm'][0]:7.2f},{t['xyz_mm'][1]:7.2f},"
                  f"{t['xyz_mm'][2]:7.2f})  {t['U_our']:9.4f} / {t['U_of']:9.4f}  "
                  f"dU {t['dU']:9.4f}")
        print("  分层 Pearson（按归档 |U| 五分位）：")
        for b in r["bins"]:
            print(f"    bin{b['bin']} |U_of {b['U_of_range'][0]:.4f}-{b['U_of_range'][1]:.4f} "
                  f"({b['cells']:6d})  U r={b['r_U']:.5f}  p r={b['r_p']:.5f}")
        print()

    path = os.path.join(OUT, "round6-l2-correlation.json")
    json.dump(results, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"-> {path}")


if __name__ == "__main__":
    main()
