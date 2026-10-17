# -*- coding: utf-8 -*-
"""
M2.5 合成数据产线 v1 -- 参数-指标单调性抽查（任务书验证标准第 3 条）

3 组 DoE（其余参数固定或受控）：
  G1 a_min 扫描  : synth-001..005（a_min=1.5/2.0/2.5/3.0/4.0 mm2，V=105, curv=0.5, asym=0.2）
                  预期：a_min↑（没那么窄）-> ΔP 单调下降
  G2 V 扫描      : synth-003/006/007/008/009（V=80/95/105/115/130 cm3，a_min=2.5）
                  预期：V 主要缩放鼻窦（滞留容积）-> 对 ΔP 影响弱（如实报告）
  G3 curv/asym   : synth-002 vs synth-010（a_min 同为 2.0；curv 0.5->1.0, asym 0.2->0.8）
                  预期：弯曲度↑ -> ΔP↑

指标取 metrics.json 的 totals.dP_Pa（面积加权入口-出口压降，baseline27 同款口径）
与 dP_L_Pa（stenosis 侧入口压降）。同时用**实测** inletL 面积（case_stats，网格
量化后的真实狭窄参数）做第二套单调性判定。全部实测值，零手写。
"""
import argparse
import json
import os


def load(out_synth):
    rows = []
    for c in sorted(d for d in os.listdir(out_synth) if d.startswith("synth-")):
        p = os.path.join(out_synth, c)
        try:
            params = json.load(open(os.path.join(p, "params.json"), encoding="utf-8"))
            stats = json.load(open(os.path.join(p, "case_stats.json"), encoding="utf-8"))
            met = json.load(open(os.path.join(p, "metrics.json"), encoding="utf-8"))
        except Exception:
            continue
        rows.append({
            "case": c,
            "design": params["design"],
            "realized": params.get("realized", {}),
            "inletL_area_mm2": (stats.get("inletL") or {}).get("area_mm2"),
            "cells": stats.get("cells"),
            "dP_Pa": met.get("totals", {}).get("dP_Pa"),
            "dP_L_Pa": met.get("totals", {}).get("dP_L_Pa"),
            "dP_R_Pa": met.get("totals", {}).get("dP_R_Pa"),
            "U_max_m_s": met.get("totals", {}).get("U_max_m_s"),
            "Re_eq": met.get("totals", {}).get("Re_eq"),
            "converged": met.get("residuals", {}).get("converged"),
            "n_iter": met.get("residuals", {}).get("n_iter"),
            "status": met.get("status"),
        })
    return rows


def spearman(xs, ys):
    def rank(a):
        order = sorted(range(len(a)), key=lambda i: a[i])
        r = [0.0] * len(a)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and a[order[j + 1]] == a[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    if len(xs) < 3:
        return None
    rx, ry = rank(xs), rank(ys)
    n = len(xs)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den > 0 else None


def monotone_dir(vals, direction):
    """direction=-1 要求非增，+1 要求非减；返回 (是否单调, 违背处数)"""
    viol = 0
    for a, b in zip(vals, vals[1:]):
        if a is None or b is None:
            continue
        if direction < 0 and b > a + 1e-9:
            viol += 1
        if direction > 0 and b < a - 1e-9:
            viol += 1
    return viol == 0, viol


def group_report(name, rows, xkey, xlabel, expect_dir, note):
    xs = [r[xkey] for r in rows]
    dP = [r["dP_Pa"] for r in rows]
    dPL = [r["dP_L_Pa"] for r in rows]
    A = [r["inletL_area_mm2"] for r in rows]
    ok_dp, v_dp = monotone_dir(dP, expect_dir)
    ok_pl, v_pl = monotone_dir(dPL, expect_dir)
    ok_a, v_a = monotone_dir(A, expect_dir)
    return {
        "group": name,
        "x": xlabel,
        "expect": ("a_min↑ -> ΔP↓" if expect_dir < 0 else "x↑ -> ΔP↑"),
        "note": note,
        "rows": [{**{k: r[k] for k in ("case",)}, xkey: r[xkey],
                  "inletL_area_mm2": r["inletL_area_mm2"],
                  "dP_Pa": r["dP_Pa"], "dP_L_Pa": r["dP_L_Pa"],
                  "converged": r["converged"]} for r in rows],
        "monotonic_dP_Pa": ok_dp, "violations_dP_Pa": v_dp,
        "monotonic_dP_L_Pa": ok_pl, "violations_dP_L_Pa": v_pl,
        "monotonic_inletL_area": ok_a, "violations_inletL_area": v_a,
        "spearman_x_vs_dP": spearman([x for x in xs if x is not None],
                                     [d for d, x in zip(dP, xs) if x is not None]),
        "spearman_area_vs_dP": spearman([a for a in A if a is not None],
                                        [d for d, a in zip(dP, A) if a is not None]),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    args = ap.parse_args()
    out_synth = os.path.join(args.repo, "code", "pipeline", "out", "synth")
    rows = load(out_synth)
    by = {r["case"]: r for r in rows}
    groups = []

    g1 = [by[f"synth-{i:03d}"] for i in range(1, 6)]
    groups.append(group_report("G1 a_min 扫描（1.5→4.0 mm²）", g1,
                               "design", None, -1,
                               "狭窄参数增大 → ΔP 应下降"))
    for r in g1:
        r["design"] = r["design"]["a_min_mm2"]
    groups[-1]["x"] = "design.a_min_mm2"

    g2 = [by[c] for c in ("synth-003", "synth-006", "synth-007", "synth-008",
                          "synth-009")]
    for r in g2:
        r["design"] = r["design"]["V_target_cm3"]
    groups.append(group_report("G2 V 扫描（80→130 cm³，a_min=2.5）", g2,
                               "design", None, +1,
                               "V 主要缩放鼻窦滞留容积，预期对 ΔP 影响弱；"
                               "若近似平坦属预期（如实报告）"))
    groups[-1]["x"] = "design.V_target_cm3"

    g3 = [by["synth-002"], by["synth-010"]]
    for r in g3:
        r["design"] = r["design"]["curv"]
    groups.append(group_report("G3 弯曲度（curv 0.5→1.0，a_min 同=2.0）", g3,
                               "design", None, +1,
                               "弯曲度增大 → ΔP 应上升"))
    groups[-1]["x"] = "design.curv"

    verdict = []
    for g in groups:
        v = (f"{g['group']}: dP_Pa 单调={g['monotonic_dP_Pa']} "
             f"(违背 {g['violations_dP_Pa']}), "
             f"dP_L_Pa 单调={g['monotonic_dP_L_Pa']}, "
             f"inletL 面积单调={g['monotonic_inletL_area']}, "
             f"spearman(x,dP)={g['spearman_x_vs_dP']}, "
             f"spearman(area,dP)={g['spearman_area_vs_dP']}")
        verdict.append(v)
        print("[mono]", v, flush=True)
    out = {"groups": groups, "verdict": verdict,
           "generated_at": __import__("time").strftime("%Y-%m-%d %H:%M:%S")}
    with open(os.path.join(out_synth, "monotonicity.json"), "w",
              encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"[mono] -> {os.path.join(out_synth, 'monotonicity.json')}")


if __name__ == "__main__":
    main()
