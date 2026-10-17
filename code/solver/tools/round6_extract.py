"""第六棒 T1：L3 五例指标提取与对拍（只读，不重跑求解）。

数据来源（均已在仓库内）：
  - solver/out/l3-<NNN>.log                求解器 stdout（dP@迭代 / flux / 末步残差 / WSS 汇总）
  - solver/out/l3-<NNN>/fields_<it>.vtk    场快照（U_max、WSS 复算）
  - solver/out/l3cases/step2/P0-OF-case-<NNN>-v1/constant/polyMesh
                                           生成该场的同一条网格（用于 WSS 的面/单元几何）
  - pipeline/out/baseline27/case-<NNN>/metrics.json   归档 OF 真值

指标口径与 src/metrics.rs 一致：
  dP      = rho * (面数平均 p_in - 面数平均 p_out)   （日志直接给出）
  U_max   = max |U_c|
  WSS     = mu * |(I - nn^T) U_c| / |C_f - C_c|      （真实法向距离；另给固定 0.4883 mm 口径）
  flux    = |Σ_in Q - Q_out| / Σ_in Q                （日志 Time=it 的 patch sum(phi)）

用法: python tools/round6_extract.py [--json PATH]
"""
import glob
import json
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import outlet_probe as op
import vtk_cells

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")
BASE = os.path.normpath(os.path.join(ROOT, "..", "pipeline", "out", "baseline27"))
MU = 2.16e-5
FIXED_DN = 0.4882998764514923e-3  # 归档 metrics.json 的 dn_mm_median


def read_text(path):
    raw = open(path, "rb").read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    return raw.decode("utf-8", errors="replace")


def parse_log(path):
    txt = read_text(path)
    d = {"dp_by_iter": {}, "flux_by_iter": {}, "files": path}
    m = re.search(r"cells (\d+) \| faces (\d+)", txt)
    if m:
        d["cells"] = int(m.group(1))
        d["faces"] = int(m.group(2))
    cur = None
    for ln in txt.splitlines():
        mt = re.match(r"Time = (\d+)\b", ln)
        if mt:
            cur = int(mt.group(1))
        if "dP(Pa)" in ln and cur is not None:
            vals = re.findall(r"dP\(Pa\)\s+([-\d.eE+]+)", ln)
            if vals:
                d["dp_by_iter"][cur] = float(vals[0])
        mf = re.match(r"Time = (\d+)\s+flux\((\w+)\s*\) sum\(phi\) = ([-\d.eE+]+)", ln)
        if mf:
            d["flux_by_iter"].setdefault(int(mf.group(1)), {})[mf.group(2)] = float(mf.group(3))
        if ln.startswith("dP (rho*p_in - p_out)"):
            d["dp_final"] = float(re.search(r"=\s*([-\d.eE+]+)", ln).group(1))
        if ln.startswith("iterations"):
            d["iterations"] = int(re.search(r":\s*(\d+)", ln).group(1))
        if ln.startswith("WSS (1st-order voxel est)"):
            mm = re.search(r"mean ([\d.eE+-]+) Pa, max ([\d.eE+-]+) Pa", ln)
            if mm:
                d["wss_mean_log"] = float(mm.group(1))
                d["wss_max_log"] = float(mm.group(2))
        if ln.startswith("final residuals"):
            d["final_residuals"] = ln.split(":", 1)[1].strip()
        if ln.startswith("Time = ") and " Ux " in ln:
            d["last_res_line"] = ln.strip()
    d["last_iter"] = max(d["dp_by_iter"]) if d["dp_by_iter"] else None
    return d


def cell_centres(pts, faces, owner, ncells):
    acc = np.zeros((ncells, 3))
    cnt = np.zeros(ncells)
    pts = np.asarray(pts, dtype=np.float64)
    for f, nodes in enumerate(faces):
        c = owner[f]
        acc[c] += pts[nodes].sum(axis=0)
        cnt[c] += len(nodes)
    return acc / cnt[:, None]


def poly_area_vec(pts, nodes):
    a = np.asarray(pts, dtype=np.float64)
    n = a[nodes]
    s = np.zeros(3)
    m = len(nodes)
    for i in range(m):
        s += 0.5 * np.cross(n[i], n[(i + 1) % m])
    return s


def wss_stats(mesh_dir, vtk_path):
    pts = op.read_points(os.path.join(mesh_dir, "points"))
    faces = op.read_faces(os.path.join(mesh_dir, "faces"))
    owner = np.asarray(op.read_int_field(os.path.join(mesh_dir, "owner")), dtype=np.int64)
    ncells = int(owner.max()) + 1
    bnd = op.read_boundary(os.path.join(mesh_dir, "boundary"))
    u, _ = op.read_vtk_cells(vtk_path, ncells)
    u = np.asarray(u, dtype=np.float64)
    cc = cell_centres(pts, faces, owner, ncells)
    pts_np = np.asarray(pts, dtype=np.float64)
    walls = [b for b in bnd if b[0] == "walls"][0]
    _, nf, sf = walls
    tau_real, tau_fix = [], []
    for f in range(sf, sf + nf):
        nodes = faces[f]
        s = poly_area_vec(pts_np, nodes)
        mag = np.linalg.norm(s)
        if mag <= 0:
            continue
        nhat = s / mag
        uc = u[owner[f]]
        un = float(np.dot(uc, nhat))
        tang = uc - un * nhat
        tm = np.linalg.norm(tang)
        cf = pts_np[nodes].mean(axis=0)
        dn = np.linalg.norm(cf - cc[owner[f]])
        tau_real.append(MU * tm / max(dn, 1e-300))
        tau_fix.append(MU * tm / FIXED_DN)
    out = {}
    for tag, arr in (("real", tau_real), ("fixed", tau_fix)):
        a = np.sort(np.asarray(arr))
        n = len(a)
        out[tag] = {
            "mean": float(a.mean()),
            "median": float(a[n // 2]),
            "p95": float(a[int(0.95 * n)]),
            "max": float(a[-1]),
        }
    return out


def pct(a, b):
    return (a - b) / b * 100.0


def main():
    rows = []
    for case in ["003", "005", "009", "014", "021"]:
        log = os.path.join(OUT, f"l3-{case}.log")
        logd = parse_log(log)
        fields = sorted(glob.glob(os.path.join(OUT, f"l3-{case}", "fields_*.vtk")))
        # 有 1500 用 1500；没有则用最大的可用快照（当前为 500）
        it = 1500
        vtk = os.path.join(OUT, f"l3-{case}", f"fields_{it}.vtk")
        if not os.path.exists(vtk):
            vtk = fields[-1]
            it = int(re.search(r"fields_(\d+)\.vtk$", vtk).group(1))
        _, U, _ = vtk_cells.parse(vtk)
        mag = np.linalg.norm(U, axis=1)
        umax = float(mag.max())
        umax_cell = int(mag.argmax())
        # step2 目录命名不统一：003 带前导零，其余为 5 / 9 / 14 / 21
        mesh_tag = {"003": "003", "005": "5", "009": "9", "014": "14", "021": "21"}[case]
        mesh_dir = os.path.join(OUT, "l3cases", "step2",
                                f"P0-OF-case-{mesh_tag}-v1", "constant", "polyMesh")
        wss = wss_stats(mesh_dir, vtk)
        flux = logd["flux_by_iter"].get(it, {})
        qin = sum(-v for k, v in flux.items() if k.startswith("inlet"))
        qout = flux.get("outlet", float("nan"))
        closure = abs(qin - qout) / qin * 100.0 if qin else float("nan")
        arch = json.load(open(os.path.join(BASE, f"case-{case}", "metrics.json"), encoding="utf-8"))
        a_dp = arch["totals"]["dP_Pa"]
        a_umax = arch["totals"]["U_max_m_s"]
        a_wss = arch["wss"]["mean_Pa"]
        a_qin = arch["totals"].get("Q_inlet_total_m3_s")
        a_qout = arch["totals"].get("Q_outlet_L_min", float("nan")) / 60000.0
        a_closure = abs(a_qin - a_qout) / a_qin * 100.0 if a_qin else float("nan")
        dp = logd["dp_by_iter"].get(it)
        rows.append({
            "case": case,
            "cells_log": logd.get("cells"),
            "field_iter": it,
            "last_iter": logd.get("last_iter"),
            "reached_1500": logd.get("last_iter") == 1500,
            "dp_iter": it,
            "dp_our": dp,
            "dp_arch": a_dp,
            "dp_pct": pct(dp, a_dp) if dp is not None else None,
            "dp_final": logd.get("dp_final"),
            "umax_our": umax,
            "umax_cell": umax_cell,
            "umax_arch": a_umax,
            "umax_pct": pct(umax, a_umax),
            "wss_real_mean": wss["real"]["mean"],
            "wss_fixed_mean": wss["fixed"]["mean"],
            "wss_arch_mean": a_wss,
            "wss_real_pct": pct(wss["real"]["mean"], a_wss),
            "wss_fixed_pct": pct(wss["fixed"]["mean"], a_wss),
            "wss_real_max": wss["real"]["max"],
            "wss_arch_max": arch["wss"]["max_Pa"],
            "flux_closure_pct": closure,
            "flux_arch_closure_pct": a_closure,
            "final_residuals": logd.get("final_residuals"),
            "last_res_line": logd.get("last_res_line"),
            "wss_log_mean": logd.get("wss_mean_log"),
            "wss_log_max": logd.get("wss_max_log"),
            "vtk": os.path.relpath(vtk, ROOT),
        })

    hdr = (f"{'case':5s} {'it':>5s} {'dP_our':>10s} {'dP_arch':>9s} {'dP%':>7s} "
           f"{'Umax_our':>9s} {'Umax_arch':>9s} {'Umax%':>7s} "
           f"{'WSSr_our':>9s} {'WSSa':>9s} {'WSS%':>7s} {'flux%':>6s}")
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(f"{r['case']:5s} {r['field_iter']:5d} {r['dp_our']:10.3f} {r['dp_arch']:9.3f} "
              f"{r['dp_pct']:7.2f} {r['umax_our']:9.3f} {r['umax_arch']:9.3f} {r['umax_pct']:7.2f} "
              f"{r['wss_real_mean']:9.5f} {r['wss_arch_mean']:9.5f} {r['wss_real_pct']:7.1f} "
              f"{r['flux_closure_pct']:6.3f}")
        if not r["reached_1500"]:
            print(f"      note: 无 fields_1500，用 fields_{r['field_iter']}（日志末步 {r['last_iter']}）")

    path = os.path.join(OUT, "round6-l3-metrics.json")
    json.dump(rows, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n-> {path}")


if __name__ == "__main__":
    main()
