# -*- coding: utf-8 -*-
"""
M2.5 合成数据产线 v1 -- 终装：metrics.json + provenance.json + MD5（复刻
baseline27 / M1 trackC validate27.py 口径，零手写指标——全部来自 VTK 实测
与 log.simpleFoam 解析）。

每例产出（out/synth/synth-NNN/）：
  metrics.json   补丁统计（p/U/WSS/流量）+ 总量（dP/Re/Umax）+ 残差 + 几何
  provenance.json 生成参数 + manifold 版本 + 适配层配方 + step2 参数 + 求解环境
  MD5.txt        本目录文件 md5 清单
根目录另出 MD5-MANIFEST.md（汇总 10 例 + 脚本 md5）。

用法: python finalize_case.py --case synth-001 [--all] --repo ... --work ...
"""
import argparse
import glob
import hashlib
import json
import os
import re
import sys
import time

import numpy as np
import pyvista as pv

HERE = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(PIPELINE))
if PIPELINE not in sys.path:
    sys.path.insert(0, PIPELINE)
import solver_backend as _backend  # noqa: E402  inputs 段来源共用一个实现（裁定五）
GEN_GEOMETRY = os.path.join(HERE, "gen_geometry.py")
STL_TO_DICOM = os.path.join(HERE, "stl_to_dicom.py")
STEP2 = os.path.join(PIPELINE, "step2_make_ofcase.py")

RHO = 1.2
NU = 1.8e-5


def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def md5_or_none(p):
    return md5(p) if os.path.isfile(p) else None


def latest_vtk_dir(vtk_root, case):
    cands = []
    for p in glob.glob(os.path.join(vtk_root, f"{case}_*")):
        if os.path.isdir(p):
            tag = p.rsplit("_", 1)[1]
            if tag.isdigit():
                cands.append((int(tag), p))
    cands.sort()
    return cands[-1][1] if cands else None


def patch_stats(vtp):
    g = pv.read(vtp)
    g = g.compute_cell_sizes()
    g = g.compute_normals(cell_normals=True, point_normals=False,
                          inplace=True, flip_normals=False)
    A = np.asarray(g.cell_data["Area"], dtype=np.float64)      # m^2
    area_mm2 = float(A.sum()) * 1e6
    n = g.n_cells
    out = {"n_cells": float(n), "area_mm2": area_mm2}
    if "p" in g.cell_data:
        out["p_mean_kin"] = float(np.mean(g.cell_data["p"]))
    if "U" in g.cell_data:
        U = np.asarray(g.cell_data["U"], dtype=np.float64)
        nrm = np.asarray(g.cell_data["Normals"], dtype=np.float64)
        un = np.sum(U * nrm, axis=1)
        ref = np.mean(un)
        if ref != 0:
            flip = np.sign(un) != np.sign(ref)
            un_fixed = np.where(flip, -un, un)
        else:
            un_fixed = un
        q_signed = float(np.sum(un_fixed * A))
        out["Q_signed_m3_s"] = float(np.sign(ref) * q_signed) if ref != 0 else 0.0
        out["U_normal_mean_m_s"] = float(np.mean(un_fixed))
        spd = np.linalg.norm(U, axis=1)
        out["U_mag_mean_m_s"] = float(spd.mean())
        out["U_mag_max_m_s"] = float(spd.max())
    if "wallShearStress" in g.cell_data:
        w = np.asarray(g.cell_data["wallShearStress"], dtype=np.float64)
        mag = np.linalg.norm(w, axis=1)
        out["wss"] = {
            "n_faces": float(len(mag)),
            "mean_Pa": float(mag.mean()),
            "median_Pa": float(np.median(mag)),
            "p95_Pa": float(np.percentile(mag, 95)),
            "max_Pa": float(mag.max()),
            "area_weighted_mean_Pa": float(np.sum(mag * A) / A.sum()),
        }
    return out


def internal_stats(vtu):
    g = pv.read(vtu)
    r = {}
    if "U" in g.cell_data:
        U = np.asarray(g.cell_data["U"], dtype=np.float64)
        spd = np.linalg.norm(U, axis=1)
        r["ncells"] = int(spd.shape[0])
        r["U_max_m_s"] = float(spd.max())
        r["U_mean_m_s"] = float(spd.mean())
        i = int(np.argmax(spd))
        c = np.asarray(g.cell_centers().points[i], dtype=np.float64)
        r["U_max_pos_mm"] = [float(x * 1000.0) for x in c]
    return r


def parse_log(logpath):
    txt = open(logpath, encoding="utf-8", errors="replace").read()
    r = {}
    times = re.findall(r"^Time = (\d+)\s*$", txt, re.M)
    r["n_iter"] = len(times)
    r["final_iter"] = int(times[-1]) if times else None
    m = re.findall(r"ExecutionTime = ([0-9.]+) s", txt)
    r["execution_time_s"] = float(m[-1]) if m else None
    m = re.findall(r"ClockTime = ([0-9.]+) s", txt)
    r["clock_time_s"] = float(m[-1]) if m else None
    blocks = re.split(r"^Time = \d+\s*$", txt, flags=re.M)
    last = blocks[-1] if blocks else ""
    for k in ("Ux", "Uy", "Uz", "p"):
        m = re.search(rf"Solving for {k}, Initial residual = ([0-9.eE+-]+)", last)
        r[f"last_{k}_init"] = float(m.group(1)) if m else None
    m = re.search(r"cumulative = ([0-9.eE+-]+)", last)
    r["last_cont_cum"] = float(m.group(1)) if m else None
    lu = [r.get(f"last_{k}_init") for k in ("Ux", "Uy", "Uz")]
    r["converged"] = bool(r.get("last_p_init") is not None
                          and all(u is not None for u in lu)
                          and r["last_p_init"] < 1e-4 and max(lu) < 1e-4)
    p_series = [float(x) for x in
                re.findall(r"Solving for p, Initial residual = ([0-9.eE+-]+)", txt)]
    r["p_init_first"] = p_series[0] if p_series else None
    r["p_init_last"] = p_series[-1] if p_series else None
    fl = {}
    for name in ("fluxInletL", "fluxInletR", "fluxOutlet"):
        m = re.search(rf"surfaceFieldValue {name} write:(?:.*\n)*?\s*sum\(\w+\) of phi = (-?[0-9.eE+-]+)", txt)
        fl[name] = float(m.group(1)) if m else None
    r["flux"] = fl
    return r


def finalize(case, repo, work):
    out_synth = os.path.join(repo, "code", "pipeline", "out", "synth")
    dst = os.path.join(out_synth, case)
    pull = os.path.join(work, "wslpull", case)
    params = json.load(open(os.path.join(dst, "params.json"), encoding="utf-8"))
    stats = json.load(open(os.path.join(dst, "case_stats.json"), encoding="utf-8"))
    qc = json.load(open(os.path.join(dst, "dicom_qc.json"), encoding="utf-8"))
    vd = latest_vtk_dir(os.path.join(pull, "VTK"), f"P0-OF-case-{case}")
    logp = os.path.join(pull, "log.simpleFoam")
    if vd is None or not os.path.isfile(logp):
        return {"case": case, "status": "NO_SOLVE",
                "vtk": vd, "log": os.path.isfile(logp)}
    bdir = os.path.join(vd, "boundary")
    internal = os.path.join(vd, "internal.vtu")
    # inputs 段的 nu/rho/mu 必须从该次求解实际使用的 case 文件回读（裁定五）：
    # 求解发生在 pull（WSL 侧运行目录）里，拿不到就退到仓库侧同名 case 目录，
    # 两处都读不到就写 null + warnings —— 不回落到模块常量 NU。
    inputs, input_warnings = None, []
    for cd in (pull, os.path.join(dst, "case")):
        if os.path.isfile(os.path.join(cd, "constant", "transportProperties")):
            inputs, input_warnings = _backend.build_inputs_provenance(
                cd, vtk_dir=vd, solver_backend="openfoam")
            break
    if inputs is None:
        inputs, input_warnings = _backend.build_inputs_provenance(
            None, vtk_dir=vd, solver_backend="openfoam")
    inputs["solve"] = "Run-A 15L/min simpleFoam laminar steady"
    m = {
        "case": case,
        "inputs": inputs,
        "files": {"internal": internal,
                  "inletL": os.path.join(bdir, "inletL.vtp"),
                  "inletR": os.path.join(bdir, "inletR.vtp"),
                  "outlet": os.path.join(bdir, "outlet.vtp"),
                  "walls": os.path.join(bdir, "walls.vtp")},
    }
    patches = {}
    for p in ("inletL", "inletR", "outlet", "walls"):
        patches[p] = patch_stats(os.path.join(bdir, p + ".vtp"))
    m["patches"] = patches
    il, ir, ot = patches["inletL"], patches["inletR"], patches["outlet"]
    nl, nr = il["n_cells"], ir["n_cells"]
    pL, pR = il.get("p_mean_kin"), ir.get("p_mean_kin")
    pO = ot.get("p_mean_kin")
    res = parse_log(logp)
    tot = {}
    if pL is not None and pR is not None:
        p_in = (pL * nl + pR * nr) / (nl + nr)
        tot["p_inlet_Pa"] = p_in * RHO
        tot["dP_L_Pa"] = pL * RHO
        tot["dP_R_Pa"] = pR * RHO
        tot["p_outlet_Pa"] = (pO or 0.0) * RHO
        tot["dP_Pa"] = tot["p_inlet_Pa"] - tot["p_outlet_Pa"]
    ql, qr, qo = il.get("Q_signed_m3_s"), ir.get("Q_signed_m3_s"), ot.get("Q_signed_m3_s")
    if None not in (ql, qr, qo):
        qin = ql + qr
        tot["Q_inlet_total_m3_s"] = qin
        tot["Q_inlet_total_L_min"] = qin * 60000.0
        tot["Q_outlet_L_min"] = qo * 60000.0
        if qin > 0:
            tot["flow_share_L_pct"] = ql / qin * 100.0
            tot["flow_share_R_pct"] = qr / qin * 100.0
            tot["cont_rel_err"] = abs(qin - qo) / qin
    fl = res.get("flux", {})
    fL, fR, fO = fl.get("fluxInletL"), fl.get("fluxInletR"), fl.get("fluxOutlet")
    if None not in (fL, fR, fO) and (fL + fR) != 0:
        qin_log = -(fL + fR)
        tot["Q_inlet_total_L_min"] = qin_log * 60000.0
        tot["Q_outlet_L_min"] = fO * 60000.0
        tot["flow_share_L_pct"] = -fL / qin_log * 100.0
        tot["flow_share_R_pct"] = -fR / qin_log * 100.0
        tot["cont_rel_err"] = abs(qin_log - fO) / qin_log
        tot["Q_source"] = "log surfaceFieldValue phi"
    else:
        tot["Q_source"] = "VTK Udotn estimate"
    tot["outlet_area_mm2"] = ot["area_mm2"]
    tot["outlet_D_eq_mm"] = float((4 * ot["area_mm2"] / np.pi) ** 0.5)
    if ot.get("U_normal_mean_m_s"):
        tot["outlet_V_mean_m_s"] = abs(ot["U_normal_mean_m_s"])
        tot["Re_eq"] = tot["outlet_V_mean_m_s"] * (tot["outlet_D_eq_mm"] * 1e-3) / NU
        tot["laminar"] = bool(tot["Re_eq"] < 2300)
    ist = internal_stats(internal)
    tot.update({k: v for k, v in ist.items() if k != "ncells"})
    m["totals"] = tot
    if "wss" in patches["walls"]:
        m["wss"] = patches["walls"].pop("wss")
    m["residuals"] = res
    dcp = os.path.join(pull, "dpcheck.txt")
    if os.path.isfile(dcp):
        dtxt = open(dcp, encoding="utf-8", errors="replace").read().strip()
        m["dp_stability"] = dtxt
        mm = re.search(r"change=([0-9.]+)%", dtxt)
        if mm:
            m["dp_stability_change_pct"] = float(mm.group(1))
    r = params.get("realized", {})
    m["geometry"] = {
        "airway_volume_cm3": r.get("volume_cm3"),
        "nostril_area_L_mm2": r.get("nostril_area_L_mm2"),
        "nostril_area_R_mm2": r.get("nostril_area_R_mm2"),
        "a_min_stl_mm2": r.get("a_min_stl_mm2"),
        "watertight": r.get("watertight"),
        "cells": stats.get("cells"),
        "inletL_area_mm2_step2": (stats.get("inletL") or {}).get("area_mm2"),
        "inletR_area_mm2_step2": (stats.get("inletR") or {}).get("area_mm2"),
        "outlet_area_mm2_step2": stats.get("outlet_area_mm2"),
        "voxel_mm": stats.get("voxel_mm"),
        "rasterization_ratio": qc.get("volume", {}).get("ratio"),
    }
    m["warnings"] = list(input_warnings)
    if tot.get("cont_rel_err") is not None and tot["cont_rel_err"] > 0.05:
        m["warnings"].append(f"continuity rel err {tot['cont_rel_err']:.3%} > 5%")
    m["status"] = "OK"
    with open(os.path.join(dst, "metrics.json"), "w", encoding="utf-8",
              newline="\n") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)
    # ---- provenance ----
    prov = {
        "case": case,
        "data_class": "L1 synthetic (manifold3d parametric geometry; NO patient data)",
        "license": "project BSL-1.1 (Change Date 2099-01-01); geometry kernel manifold3d Apache-2.0",
        "generator": {
            "script": "synth/gen_geometry.py",
            "script_md5": md5_or_none(GEN_GEOMETRY),
            "manifold_version": params.get("generator", {}).get("manifold_version"),
            "manifold_license": "Apache-2.0",
            "design": params.get("design"),
            "realized": {k: r.get(k) for k in
                         ("volume_cm3", "nostril_area_L_mm2", "nostril_area_R_mm2",
                          "a_min_stl_mm2", "watertight", "n_tri")},
            "volume_tuning": params.get("volume_tuning"),
        },
        "adapter": {
            "script": "synth/stl_to_dicom.py",
            "script_md5": md5_or_none(STL_TO_DICOM),
            "recipe": {"inplane_mm": 0.35, "dz_mm": 0.7, "head_margin_mm": 8.0,
                       "fov_margin_mm": 12.0, "hu_air": -1000, "hu_head": 40,
                       "orientation": "nostrils at LOW z (NOSTRIL_AT_LOW=True)"},
            "dicom_qc": {"volume_ratio": qc.get("volume", {}).get("ratio"),
                         "n_slices": qc.get("n_slices"),
                         "max_slice_components": qc.get("max_slice_components")},
        },
        "step2": {
            "script": "pipeline/step2_make_ofcase.py",
            "script_md5": md5_or_none(STEP2),
            "args": {"merge-mode": "largest", "voxel-z": 0.7,
                     "case-prefix": "synth", "ext": False},
            "case_stats_md5": md5_or_none(os.path.join(dst, "case_stats.json")),
        },
        "solver": {"env": "WSL Ubuntu OpenFOAM-2406 (simpleFoam laminar steady)",
                   "bc": "Run-A total 15 L/min, flowRateInletVelocity split by "
                         "inlet patch area (baseline27 convention)",
                   "nu_m2s": NU, "rho_kg_m3": RHO,
                   "endTime": 1500, "residualControl": "p/U 1e-4",
                   "mesh_voxel_mm": stats.get("voxel_mm"),
                   "cells": stats.get("cells"),
                   "patch_face_counts": stats.get("patch_face_counts")},
        "metrics_md5": md5_or_none(os.path.join(dst, "metrics.json")),
        "finalized_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(os.path.join(dst, "provenance.json"), "w", encoding="utf-8",
              newline="\n") as f:
        json.dump(prov, f, ensure_ascii=False, indent=1)
    # ---- MD5.txt（含 provenance 后重算；不自列自身，避免自引用漂移）----
    lines = [f"# {case} 交付 md5 清单 {prov['finalized_at']}", "",
             "| 文件 | bytes | md5 |", "|---|---|---|"]
    for fn in sorted(os.listdir(dst)):
        p = os.path.join(dst, fn)
        if os.path.isfile(p) and fn != "MD5.txt":
            lines.append(f"| {fn} | {os.path.getsize(p)} | {md5(p)} |")
    with open(os.path.join(dst, "MD5.txt"), "w", encoding="utf-8",
              newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--work", required=True)
    args = ap.parse_args()
    out_synth = os.path.join(args.repo, "code", "pipeline", "out", "synth")
    cases = sorted(d for d in os.listdir(out_synth)
                   if d.startswith("synth-")) if args.all else [args.case]
    rows = []
    for c in cases:
        try:
            m = finalize(c, args.repo, args.work)
        except Exception as e:
            m = {"case": c, "status": "FAIL", "error": str(e)[:300]}
        t = m.get("totals", {})
        r = m.get("residuals", {})
        rows.append({"case": m.get("case"), "status": m.get("status"),
                     "dP_Pa": t.get("dP_Pa"),
                     "Q_Lmin": t.get("Q_inlet_total_L_min"),
                     "split_L_pct": t.get("flow_share_L_pct"),
                     "U_max_m_s": t.get("U_max_m_s"),
                     "Re_eq": t.get("Re_eq"),
                     "wss_mean_Pa": (m.get("wss") or {}).get("mean_Pa"),
                     "cont_err": t.get("cont_rel_err"),
                     "n_iter": r.get("n_iter"),
                     "exec_s": r.get("execution_time_s"),
                     "converged": r.get("converged"),
                     "error": m.get("error")})
        print(f"[finalize] {m.get('case')} status={m.get('status')} "
              f"dP={t.get('dP_Pa')} Q_Lmin={t.get('Q_inlet_total_L_min')} "
              f"splitL={t.get('flow_share_L_pct')} Umax={t.get('U_max_m_s')} "
              f"Re={t.get('Re_eq')} iter={r.get('n_iter')} "
              f"conv={r.get('converged')} err={m.get('error')}", flush=True)
    with open(os.path.join(args.work, "finalize_rows.json"), "w",
              encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
