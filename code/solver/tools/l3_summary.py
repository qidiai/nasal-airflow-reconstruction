"""L3 批量回归汇总：解析我方日志 + fields_*.vtk，与 baseline27 归档 metrics.json 对比。

用法:
  python l3_summary.py [--json out.json]
扫描 solver/out/l3-<NNN>.log 与 solver/out/l3-<NNN>/fields_1500.vtk，
对应 pipeline/out/baseline27/case-<NNN>/metrics.json。
"""
import glob
import json
import os
import re
import sys

import numpy as np

import outlet_probe as op
import vtk_cells

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")
BASE = os.path.normpath(os.path.join(ROOT, "..", "pipeline", "out", "baseline27"))


def read_text(path):
    """PowerShell 5.1 的 `*>` 重定向写 UTF-16LE（带 BOM）；Rust 直写为 UTF-8。"""
    raw = open(path, "rb").read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    return raw.decode("utf-8", errors="replace")


def parse_log(path):
    txt = read_text(path)
    d = {}
    m = re.search(r"dP \(rho\*p_in - p_out\) = ([-\d.eE+]+) Pa", txt)
    if m:
        d["dP"] = float(m.group(1))
    m = re.search(r"WSS \(1st-order voxel est\): mean ([\d.eE+-]+) Pa, max ([\d.eE+-]+) Pa", txt)
    if m:
        d["wss_mean"] = float(m.group(1))
        d["wss_max"] = float(m.group(2))
    flux = {}
    for name, v in re.findall(r"patch (\w+)\s*:\s*sum\(phi\) = ([-\d.eE+]+) m3/s", txt):
        flux[name] = float(v)
    d["flux"] = flux
    m = re.search(r"iterations\s*:\s*(\d+)", txt)
    if m:
        d["iter"] = int(m.group(1))
    m = re.search(r"final residuals\s*:\s*Ux ([\d.eE+-]+) Uy ([\d.eE+-]+) Uz ([\d.eE+-]+) p ([\d.eE+-]+)", txt)
    if m:
        d["res"] = [float(x) for x in m.groups()]
    return d


def umax_from_vtk(path, ncells):
    _, U, _ = vtk_cells.parse(path)
    mag = np.linalg.norm(U, axis=1)
    return float(mag.max()), int(mag.argmax())


def pct(a, b):
    return (a - b) / b * 100.0


def main():
    rows = []
    cases = sorted(glob.glob(os.path.join(OUT, "l3-*.log")))
    for log in cases:
        m = re.search(r"l3-(\d+)\.log$", log)
        if not m:
            continue
        case = m.group(1)
        base = os.path.join(BASE, f"case-{case}", "metrics.json")
        if not os.path.exists(base):
            continue
        ours = parse_log(log)
        if "dP" not in ours:
            print(f"  [case-{case}] 未跑完（日志无 dP 终值），跳过")
            continue
        arch = json.load(open(base, encoding="utf-8"))
        vtk = os.path.join(OUT, f"l3-{case}", "fields_1500.vtk")
        umax = None
        if os.path.exists(vtk):
            ncell = int(arch["geometry"]["cells"])
            try:
                umax, _ = umax_from_vtk(vtk, ncell)
            except Exception as e:  # noqa: BLE001
                print(f"  [{case}] VTK 读取失败: {e}")
        qin = sum(-v for k, v in ours["flux"].items() if k.startswith("inlet"))
        qout = ours["flux"].get("outlet", float("nan"))
        rows.append({
            "case": case,
            "cells": arch["geometry"]["cells"],
            "dP_our": ours.get("dP"),
            "dP_arch": arch["totals"]["dP_Pa"],
            "dP_pct": pct(ours.get("dP", float("nan")), arch["totals"]["dP_Pa"]),
            "Umax_our": umax,
            "Umax_arch": arch["totals"]["U_max_m_s"],
            "Umax_pct": pct(umax, arch["totals"]["U_max_m_s"]) if umax else None,
            "wss_our": ours.get("wss_mean"),
            "wss_arch": arch["wss"]["mean_Pa"],
            "wss_pct": pct(ours.get("wss_mean", float("nan")), arch["wss"]["mean_Pa"]),
            "flux_err_pct": abs(qin - qout) / qin * 100.0,
            "iter": ours.get("iter"),
            "res": ours.get("res"),
        })

    hdr = (f"{'case':7s} {'cells':>7s} {'dP_our':>10s} {'dP_arch':>10s} {'dP%':>7s} "
           f"{'Umax_our':>9s} {'Umax_arch':>9s} {'Umax%':>7s} "
           f"{'wss_our':>9s} {'wss_arch':>9s} {'wss%':>7s} {'flux%':>7s}")
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(f"{r['case']:7s} {r['cells']:7d} {r['dP_our']:10.3f} {r['dP_arch']:10.3f} "
              f"{r['dP_pct']:7.2f} {r['Umax_our']:9.3f} {r['Umax_arch']:9.3f} "
              f"{r['Umax_pct'] if r['Umax_pct'] is None else round(r['Umax_pct'],2):>7} "
              f"{r['wss_our']:9.5f} {r['wss_arch']:9.5f} {r['wss_pct']:7.1f} "
              f"{r['flux_err_pct']:7.3f}")

    if "--json" in sys.argv:
        path = sys.argv[sys.argv.index("--json") + 1]
        json.dump(rows, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n-> {path}")


if __name__ == "__main__":
    main()
