"""Metric extraction and diff for follow-up pairs."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np


def _read_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _first_existing(base: Path, candidates: list[str]) -> Path | None:
    for c in candidates:
        p = base / c
        if p.is_file():
            return p
    return None


def load_case_metrics(case_dir: str | Path) -> dict:
    """Extract a flat metric dict from a known archive layout."""
    base = Path(case_dir)
    metrics_path = _first_existing(
        base,
        ["metrics.json", "后处理/metrics.json", "cfd/validate_solve.json"],
    )
    if metrics_path is None:
        raise FileNotFoundError(f"no metrics.json / 后处理/metrics.json / cfd/validate_solve.json in {base}")
    raw = _read_json(metrics_path)
    params = {}
    params_path = base / "params.json"
    if params_path.is_file():
        params = _read_json(params_path)

    out = {
        "source": str(metrics_path),
        "design": params.get("design", {}),
        "realized": params.get("realized", {}),
        "volume_manifold_cm3": params.get("realized", {}).get("volume_cm3"),
    }

    if "totals" in raw:
        totals = raw["totals"]
        patches = raw.get("patches", {})
        wss = raw.get("wss", {})
        geom = raw.get("geometry", {})
        out.update(
            {
                "dP_Pa": totals.get("dP_Pa"),
                "dP_L_Pa": totals.get("dP_L_Pa"),
                "dP_R_Pa": totals.get("dP_R_Pa"),
                "Q_total_L_min": totals.get("Q_inlet_total_L_min"),
                "Q_L_L_min": patches.get("inletL", {}).get("Q_L_min")
                or (totals.get("flow_share_L_pct", 0) / 100.0 * totals.get("Q_inlet_total_L_min", 0) if totals.get("flow_share_L_pct") is not None else None),
                "Q_R_L_min": patches.get("inletR", {}).get("Q_L_min")
                or (totals.get("flow_share_R_pct", 0) / 100.0 * totals.get("Q_inlet_total_L_min", 0) if totals.get("flow_share_R_pct") is not None else None),
                "split_L_pct": totals.get("flow_share_L_pct"),
                "split_R_pct": totals.get("flow_share_R_pct"),
                "U_max_m_s": totals.get("U_max_m_s"),
                "wss_mean_Pa": wss.get("mean_Pa"),
                "wss_high_Pa": wss.get("p95_Pa"),
                "volume_cm3": geom.get("airway_volume_cm3"),
                "min_area_axial_mm2": params.get("realized", {}).get("a_min_axial_global_mm2", geom.get("min_axial_area_mm2")),
                "left_nostril_area_mm2": params.get("realized", {}).get("a_min_stl_mm2"),
                "cells": geom.get("cells"),
                "iterations": raw.get("residuals", {}).get("n_iter"),
                "converged": raw.get("residuals", {}).get("converged"),
            }
        )
    elif any(k in raw for k in ("demoA", "demoB", "pA", "pB")):
        key = next(k for k in ("demoA", "demoB", "pA", "pB") if k in raw)
        solve = raw[key]
        out.update(
            {
                "dP_Pa": solve.get("dP_Pa"),
                "dP_L_Pa": solve.get("inletL_p_kin", 0) * 1.2 if solve.get("inletL_p_kin") is not None else None,
                "dP_R_Pa": solve.get("inletR_p_kin", 0) * 1.2 if solve.get("inletR_p_kin") is not None else None,
                "U_max_m_s": solve.get("Umax"),
                "cells": solve.get("ncells"),
                "iterations": solve.get("n_iter"),
                "converged": bool(
                    solve.get("p_init_series")
                    and solve["p_init_series"][-1] <= 1e-4
                    and all(solve.get(k, 1) <= 1e-4 for k in ("last_Ux_init", "last_Uy_init", "last_Uz_init"))
                ),
            }
        )
    else:
        # Flat dict fallback.
        out.update(
            {
                "dP_Pa": raw.get("dP_Pa"),
                "dP_L_Pa": raw.get("dP_L_Pa"),
                "dP_R_Pa": raw.get("dP_R_Pa"),
                "Q_total_L_min": raw.get("Q_inlet_total_L_min"),
                "split_L_pct": raw.get("flow_share_L_pct"),
                "split_R_pct": raw.get("flow_share_R_pct"),
                "U_max_m_s": raw.get("U_max_m_s"),
                "wss_mean_Pa": raw.get("wss", {}).get("mean_Pa"),
                "wss_high_Pa": raw.get("wss", {}).get("p95_Pa"),
                "volume_cm3": raw.get("geometry", {}).get("airway_volume_cm3"),
                "min_area_axial_mm2": raw.get("geometry", {}).get("min_axial_area_mm2"),
                "cells": raw.get("geometry", {}).get("cells"),
                "iterations": raw.get("residuals", {}).get("n_iter"),
                "converged": raw.get("residuals", {}).get("converged"),
            }
        )

    # If the side split is missing but both side flows are present, derive it.
    ql, qr = out.get("Q_L_L_min"), out.get("Q_R_L_min")
    if out.get("split_L_pct") is None and ql is not None and qr is not None and (ql + qr) > 0:
        out["split_L_pct"] = ql / (ql + qr) * 100.0
        out["split_R_pct"] = qr / (ql + qr) * 100.0
    return out


ROWS = [
    ("dP_Pa", "总压降 ΔP", "Pa", 2),
    ("dP_L_Pa", "左侧压降", "Pa", 2),
    ("dP_R_Pa", "右侧压降", "Pa", 2),
    ("split_L_pct", "左侧流量份额", "%", 2),
    ("split_R_pct", "右侧流量份额", "%", 2),
    ("Q_L_L_min", "左侧流量", "L/min", 3),
    ("Q_R_L_min", "右侧流量", "L/min", 3),
    ("U_max_m_s", "最大流速", "m/s", 3),
    ("wss_mean_Pa", "WSS 均值", "Pa", 5),
    ("wss_high_Pa", "WSS 高值（95% 面覆盖）", "Pa", 5),
    ("volume_cm3", "气道容积（STL）", "cm³", 3),
    ("left_nostril_area_mm2", "左鼻孔最小截面", "mm²", 3),
    ("min_area_axial_mm2", "轴向最小总截面", "mm²", 3),
    ("cells", "网格单元", "个", 0),
    ("iterations", "迭代步", "步", 0),
]


def _direction(delta: float | None, pct: float | None) -> str:
    if delta is None:
        return "—"
    threshold = 1e-9
    if pct is not None and abs(pct) < 0.1:
        return "→"
    if delta > threshold:
        return "↑"
    if delta < -threshold:
        return "↓"
    return "→"


def diff_metrics(a: dict, b: dict) -> dict:
    rows = []
    for key, label, unit, digits in ROWS:
        va, vb = a.get(key), b.get(key)
        if va is None and vb is None:
            continue
        delta = float(vb - va) if (va is not None and vb is not None) else None
        pct = float(delta / va * 100.0) if (delta is not None and va not in (None, 0)) else None
        rows.append(
            {
                "key": key,
                "label": label,
                "unit": unit,
                "a": va,
                "b": vb,
                "delta": delta,
                "pct": pct,
                "direction": _direction(delta, pct),
                "digits": digits,
            }
        )
    return {
        "a_source": a.get("source"),
        "b_source": b.get("source"),
        "rows": rows,
        "a": a,
        "b": b,
    }


def format_markdown_rows(diff: dict) -> str:
    lines = ["| 指标 | 上次 (A) | 本次 (B) | 变化 | 变化率 |", "|---|---:|---:|---:|---:|"]
    for r in diff["rows"]:
        d = r["digits"]
        def f(x):
            if x is None:
                return "—"
            if d == 0:
                return f"{int(round(x)):,}"
            return f"{x:.{d}f}"
        delta = "—" if r["delta"] is None else f"{r['delta']:+.{d}f}" if d else f"{int(round(r['delta'])):+d}"
        pct = "—" if r["pct"] is None else f"{r['pct']:+.2f}%"
        lines.append(f"| {r['label']} | {f(r['a'])} {r['unit']} | {f(r['b'])} {r['unit']} | {delta} | {pct} |")
    return "\n".join(lines)
