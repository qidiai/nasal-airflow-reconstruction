# -*- coding: utf-8 -*-
"""
M2.5 synth README 矩阵/单调性节填充器：把 10 例的参数×几何×指标矩阵和
单调性抽查结论写进 out/synth/README.md 的 <!-- MATRIX --> / <!-- MONO --> 占位符。
用法: python fill_readme.py --repo ...
"""
import argparse
import json
import os


def f(v, nd=2):
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    args = ap.parse_args()
    out_synth = os.path.join(args.repo, "code", "pipeline", "out", "synth")
    rows = []
    for c in sorted(d for d in os.listdir(out_synth) if d.startswith("synth-")):
        p = os.path.join(out_synth, c)
        try:
            params = json.load(open(os.path.join(p, "params.json"), encoding="utf-8"))
            stats = json.load(open(os.path.join(p, "case_stats.json"), encoding="utf-8"))
            met = json.load(open(os.path.join(p, "metrics.json"), encoding="utf-8"))
        except Exception:
            continue
        d = params["design"]
        r = params.get("realized", {})
        t = met.get("totals", {})
        res = met.get("residuals", {})
        rows.append({
            "case": c, "a_min": d["a_min_mm2"], "V": d["V_target_cm3"],
            "curv": d["curv"], "asym": d["asym"], "seed": d["seed"],
            "V_real": r.get("volume_cm3"), "wt": r.get("watertight"),
            "cells": stats.get("cells"),
            "A_L": (stats.get("inletL") or {}).get("area_mm2"),
            "A_R": (stats.get("inletR") or {}).get("area_mm2"),
            "A_out": stats.get("outlet_area_mm2"),
            "dP": t.get("dP_Pa"), "dP_L": t.get("dP_L_Pa"), "dP_R": t.get("dP_R_Pa"),
            "Q": t.get("Q_inlet_total_L_min"), "splitL": t.get("flow_share_L_pct"),
            "Umax": t.get("U_max_m_s"), "Re": t.get("Re_eq"),
            "wss": (met.get("wss") or {}).get("mean_Pa"),
            "cont": t.get("cont_rel_err"), "iter": res.get("n_iter"),
            "conv": res.get("converged"), "status": met.get("status"),
        })
    lines = ["| case | a_min mm² | V cm³ | curv | asym | seed | V实测 cm³ | cells | "
             "inletL mm² | inletR mm² | outlet mm² | ΔP Pa | ΔP_L Pa | ΔP_R Pa | "
             "Q L/min | L分流% | Umax m/s | Re_eq | WSS均值 Pa | cont误差 | 迭代 | 收敛 |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(
            f"| {r['case']} | {r['a_min']} | {r['V']:.0f} | {r['curv']} | {r['asym']} "
            f"| {r['seed']} | {f(r['V_real'],1)} | {r['cells']} | {f(r['A_L'],1)} "
            f"| {f(r['A_R'],1)} | {f(r['A_out'],1)} | {f(r['dP'],2)} | {f(r['dP_L'],2)} "
            f"| {f(r['dP_R'],2)} | {f(r['Q'],2)} | {f(r['splitL'],1)} | {f(r['Umax'],2)} "
            f"| {f(r['Re'],0)} | {f(r['wss'],4)} | {f(r['cont'],5)} | {r['iter']} "
            f"| {'是' if r['conv'] else '否(1500步平台)'} |")
    matrix = "\n".join(lines)

    mono = ""
    mp = os.path.join(out_synth, "monotonicity.json")
    if os.path.isfile(mp):
        mono_data = json.load(open(mp, encoding="utf-8"))
        ml = ["| 组 | 参数走向 | dP_Pa 单调? | dP_L_Pa 单调? | inletL 面积单调? "
              "| spearman(x,dP) |", "|---|---|---|---|---|---|"]
        for g in mono_data.get("groups", []):
            ml.append(f"| {g['group']} | {g['x']} | "
                      f"{'✓' if g['monotonic_dP_Pa'] else '✗(违背'+str(g['violations_dP_Pa'])+')'} | "
                      f"{'✓' if g['monotonic_dP_L_Pa'] else '✗'} | "
                      f"{'✓' if g['monotonic_inletL_area'] else '✗'} | "
                      f"{f(g['spearman_x_vs_dP'],3)} |")
        mono = "\n".join(ml) + "\n\n逐组数值见 `monotonicity.json`。"

    rp = os.path.join(out_synth, "README.md")
    txt = open(rp, encoding="utf-8").read()
    txt = txt.replace("<!-- MATRIX -->", matrix)
    txt = txt.replace("<!-- MONO -->", mono if mono else "（待 finalize 后生成）")
    open(rp, "w", encoding="utf-8", newline="\n").write(txt)
    print(f"[readme] matrix {len(rows)} rows -> {rp}")


if __name__ == "__main__":
    main()
