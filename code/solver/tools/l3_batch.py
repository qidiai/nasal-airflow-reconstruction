# -*- coding: utf-8 -*-
"""L3 批量对拍驱动（G-C2）：22 个 baseline27 成功例，各跑 1500 步后与归档 metrics 对拍。

范围：case-001..027，排除 OpenFOAM 自身发散的 5 例（011/012/013/018/022）。
算例来源（本脚本解决）：
  baseline27/case-NNN/ 是平的（只有 OF 结果），本脚本用 provenance.json 里的
  source_dicom_dir 调 pipeline/step2_make_ofcase.py 独立重建算例
  （step2 自带重分割，不吃 step1 产物；实测日志见 out/l3b-step2-NNN.log）。
  输出布局：solver/out/l3cases/step2/P0-OF-case-NNN-v1（及 -v1B）。

用法：
  python tools/l3_batch.py --build            # 顺序重建缺失算例（内存重，串行）
  python tools/l3_batch.py --solve --jobs 2   # 并行求解（默认冒烟 3 例：--smoke）
  python tools/l3_batch.py --extract          # 汇总对拍（dP/U_max/flux 闭合）
  python tools/l3_batch.py --all --jobs 2     # build -> solve -> extract

纪律：单例日志 out/l3b-NNN.log；快照 out/l3b-NNN/fields_1500.vtk（--write-every 1500，
只留终态，避免 3×VTK 占盘）；全部结果落盘，失败如实记录（returncode/NaN 不修饰）。
"""
import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # code/solver
CODE = os.path.dirname(ROOT)  # code
BASE = os.path.join(CODE, "pipeline", "out", "baseline27")
STEP2 = os.path.join(CODE, "pipeline", "step2_make_ofcase.py")
L3ROOT = os.path.join(ROOT, "out", "l3cases")
OUT = os.path.join(ROOT, "out")
EXE = os.path.join(ROOT, "target", "release", "flowscope.exe")
EXCLUDE = {11, 12, 13, 18, 22}
CASES = [f"{i:03d}" for i in range(1, 28) if i not in EXCLUDE]


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def case_dir(n):
    return os.path.join(L3ROOT, "step2", f"P0-OF-case-{n}-v1")


def archive_cells(n):
    try:
        d = json.load(open(os.path.join(BASE, f"case-{n}", "metrics.json"), encoding="utf-8"))
        return int(d["geometry"]["cells"])
    except Exception:
        return 10**9


def case_ready(d):
    """算例完整判据：polyMesh/points 存在（只判目录存在会误把中断产物当完成——
    2026-10-18 实测 025/027 被 kill 后仅剩空 polyMesh 目录）。"""
    return os.path.isfile(os.path.join(d, "constant", "polyMesh", "points"))


def build_one(n):
    d = case_dir(n)
    if case_ready(d):
        log(f"build {n}: 已存在，跳过")
        return True
    if os.path.isdir(d):
        import shutil
        log(f"build {n}: 发现中断残目录，删除后重建")
        shutil.rmtree(d)
    prov_p = os.path.join(BASE, f"case-{n}", "provenance.json")
    src = json.load(open(prov_p, encoding="utf-8"))["source_dicom_dir"]
    cmd = [sys.executable, STEP2, "--dicom-dir", src, "--case-prefix", n,
           "--case", "v1", "--out-root", L3ROOT]
    lp = os.path.join(OUT, f"l3b-step2-{n}.log")
    log(f"build {n}: step2 开始（日志 {os.path.basename(lp)}）")
    with open(lp, "w", encoding="utf-8", errors="replace") as f:
        rc = subprocess.call(cmd, cwd=os.path.join(CODE, "pipeline"), stdout=f, stderr=subprocess.STDOUT)
    ok = rc == 0 and case_ready(d)
    log(f"build {n}: {'OK' if ok else 'FAIL rc=%d' % rc}")
    return ok


def solve_done(n):
    vtk = os.path.join(OUT, f"l3b-{n}", "fields_1500.vtk")
    lp = os.path.join(OUT, f"l3b-{n}.log")
    if not os.path.exists(vtk):
        return False
    try:
        txt = open(lp, "rb").read().decode("utf-8", errors="replace")
    except Exception:
        return False
    return "契约 §11 口径指标" in txt


def start_solve(n, fh):
    cmd = [EXE, "run", case_dir(n), "--max-iter", "1500", "--p-reltol", "1e-3",
           "--write-every", "1500", "--out", os.path.join(OUT, f"l3b-{n}")]
    log(f"solve {n}: 启动（cells {archive_cells(n)}）")
    return subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT)


def solve_many(ns, jobs):
    todo = [n for n in ns if not solve_done(n)]
    done = [n for n in ns if n not in todo]
    for n in done:
        log(f"solve {n}: 已有完整产物，跳过")
    running = {}
    while todo or running:
        while todo and len(running) < jobs:
            n = todo.pop(0)
            fh = open(os.path.join(OUT, f"l3b-{n}.log"), "w", encoding="utf-8", errors="replace")
            running[n] = (start_solve(n, fh), fh)
        time.sleep(10)
        for n in list(running):
            pr, fh = running[n]
            if pr.poll() is not None:
                fh.close()
                ok = pr.returncode == 0 and solve_done(n)
                log(f"solve {n}: 结束 rc={pr.returncode} {'OK' if ok else 'FAIL/INCOMPLETE'}")
                del running[n]


def do_build():
    ns = sorted(CASES, key=archive_cells)  # 先建小算例，早出验证样本
    return all(build_one(n) for n in ns)


def do_solve(jobs, smoke):
    ns = sorted(CASES, key=archive_cells)
    if smoke:
        ns = ns[:3]
    solve_many(ns, jobs)


# ---------------- 对拍汇总 ----------------
def parse_log(path):
    d = {"dp_by_iter": {}, "flux_by_iter": {}}
    txt = open(path, "rb").read().decode("utf-8", errors="replace")
    cur = None
    import re
    for ln in txt.splitlines():
        m = re.match(r"Time = (\d+)\b", ln)
        if m:
            cur = int(m.group(1))
        if "dP(Pa)" in ln and cur is not None:
            v = re.findall(r"dP\(Pa\)\s+([-\d.eE+]+)", ln)
            if v:
                d["dp_by_iter"][cur] = float(v[0])
        mf = re.match(r"Time = (\d+)\s+flux\((\w+)\s*\) sum\(phi\) = ([-\d.eE+]+)", ln)
        if mf:
            d["flux_by_iter"].setdefault(int(mf.group(1)), {})[mf.group(2)] = float(mf.group(3))
        if ln.startswith("iterations"):
            d["iterations"] = int(re.search(r":\s*(\d+)", ln).group(1))
        if ln.startswith("final residuals"):
            d["final_residuals"] = ln.split(":", 1)[1].strip()
        if ln.startswith("Time = ") and " Ux " in ln:
            d["last_res_line"] = ln.strip()
    d["last_iter"] = max(d["dp_by_iter"]) if d["dp_by_iter"] else None
    return d


def mesh_dir_for(n):
    for tag in (n, str(int(n))):
        d = os.path.join(L3ROOT, "step2", f"P0-OF-case-{tag}-v1", "constant", "polyMesh")
        if os.path.isdir(d):
            return d
    return None


def do_extract():
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import numpy as np
    import vtk_cells
    import round6_extract as r6

    rows = []
    for n in CASES:
        arch = json.load(open(os.path.join(BASE, f"case-{n}", "metrics.json"), encoding="utf-8"))
        a_dp = arch["totals"]["dP_Pa"]
        a_umax = arch["totals"]["U_max_m_s"]
        a_wss = arch["wss"]["mean_Pa"]
        a_qin = arch["totals"].get("Q_inlet_total_m3_s")
        a_qout = arch["totals"].get("Q_outlet_L_min", float("nan")) / 60000.0
        a_closure = abs(a_qin - a_qout) / a_qin * 100 if a_qin else float("nan")
        lp = os.path.join(OUT, f"l3b-{n}.log")
        row = {"case": n, "cells_arch": arch["geometry"]["cells"], "dp_arch": a_dp,
               "umax_arch": a_umax, "wss_arch": a_wss, "flux_arch_closure_pct": a_closure}
        if not os.path.exists(lp):
            row.update({"status": "NOT_RUN", "verdict": "NOT_RUN"})
            rows.append(row)
            continue
        ld = parse_log(lp)
        it = 1500 if 1500 in ld["dp_by_iter"] else ld.get("last_iter")
        row.update({"last_iter": ld.get("last_iter"), "dp_iter": it,
                    "dp_our": ld["dp_by_iter"].get(it),
                    "dp_pct": r6.pct(ld["dp_by_iter"].get(it), a_dp) if ld["dp_by_iter"].get(it) is not None else None,
                    "final_residuals": ld.get("final_residuals")})
        fx = ld["flux_by_iter"].get(it, {})
        if fx:
            qin = sum(-v for k, v in fx.items() if k.startswith("inlet"))
            qout = fx.get("outlet", float("nan"))
            row["qin"] = qin
            row["qout"] = qout
            row["flux_closure_pct"] = abs(qin - qout) / qin * 100 if qin else float("nan")
        vtk = os.path.join(OUT, f"l3b-{n}", f"fields_{it}.vtk") if it else None
        if vtk and os.path.exists(vtk):
            _, U, _ = vtk_cells.parse(vtk)
            mag = np.linalg.norm(U, axis=1)
            row["umax_our"] = float(mag.max())
            row["umax_pct"] = r6.pct(row["umax_our"], a_umax)
            md = mesh_dir_for(n)
            if md:
                try:
                    w = r6.wss_stats(md, vtk)
                    row["wss_real_mean"] = w["real"]["mean"]
                    row["wss_real_pct"] = r6.pct(w["real"]["mean"], a_wss)
                except Exception as e:  # 网格/字段不匹配时不阻断汇总
                    row["wss_err"] = str(e)
        dp_ok = row.get("dp_pct") is not None and abs(row["dp_pct"]) < 2.0
        complete = row.get("last_iter") == 1500
        if not complete:
            row["verdict"] = "INCOMPLETE"
        else:
            row["verdict"] = "PASS" if dp_ok else "FAIL"
        row["status"] = "OK" if complete else "INCOMPLETE"
        rows.append(row)
        log(f"extract {n}: dP {row.get('dp_our')} vs {a_dp:.3f} "
            f"({row.get('dp_pct') if row.get('dp_pct') is None else round(row['dp_pct'], 3)}%) -> {row['verdict']}")

    jp = os.path.join(OUT, "l3b-summary.json")
    json.dump(rows, open(jp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # markdown 表
    md = ["# L3 批量对拍（G-C2 · 22 例成功案例，自研求解器 1500 步 / p_reltol 1e-3）", "",
          "| case | cells | dP_our (Pa) | dP_arch (Pa) | dP% | U_max_our | U_max_arch | U_max% | flux 闭合% | 判定 |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        def f(x, fmt="{:.4g}"):
            return "—" if x is None else fmt.format(x)
        md.append("| {case} | {cells} | {dp} | {dpa:.3f} | {dpp} | {um} | {uma:.4f} | {ump} | {fc} | {v} |".format(
            case=r["case"], cells=r["cells_arch"], dp=f(r.get("dp_our"), "{:.3f}"), dpa=r["dp_arch"],
            dpp=f(r.get("dp_pct"), "{:+.2f}"), um=f(r.get("umax_our"), "{:.3f}"),
            uma=r["umax_arch"], ump=f(r.get("umax_pct"), "{:+.2f}"),
            fc=f(r.get("flux_closure_pct"), "{:.3f}"), v=r["verdict"]))
    n_pass = sum(1 for r in rows if r["verdict"] == "PASS")
    md += ["", f"**汇总：PASS {n_pass}/22（判据 |dP%| < 2%）**"]
    mp = os.path.join(OUT, "l3b-summary.md")
    open(mp, "w", encoding="utf-8").write("\n".join(md) + "\n")
    log(f"extract: {jp} / {mp}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--solve", action="store_true")
    ap.add_argument("--extract", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--smoke", action="store_true", help="只跑最小的 3 例")
    a = ap.parse_args()
    if a.all:
        do_build()
        do_solve(a.jobs, a.smoke)
        do_extract()
        return
    if a.build:
        do_build()
    if a.solve:
        do_solve(a.jobs, a.smoke)
    if a.extract:
        do_extract()


if __name__ == "__main__":
    main()
