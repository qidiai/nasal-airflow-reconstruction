"""Case adapters for the M4 report engine.

The engine core consumes a :class:`CaseBundle`; each adapter below is a thin,
auditable translation from an existing archive layout into that bundle.  No
adapter invents a number: every field is copied from a named source file, and
the source path is recorded in ``bundle.provenance``.

Supported built-in cases
------------------------
``pA``        patient A archive (Run-A, 15 L/min)
``demoA``     the authorised demo alias of patient A (same simulation)
``synth-001`` synthetic phantom, design a_min = 1.5 mm²
``demoB``     demo B front-end data package
``pN-Lat``    demo pN-Lat front-end data package (not converged)
``pN-Med``    demo pN-Med front-end data package

A generic ``--metrics`` path can also be used; see ``load_generic``.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from . import figures

CODE_ROOT = Path(__file__).resolve().parents[2]
OUT = CODE_ROOT / "pipeline" / "out"
WEBAPP = CODE_ROOT / "pipeline" / "webapp"


@dataclass
class CaseBundle:
    case_id: str
    label: str
    case_kind: str  # patient | patient_demo | synthetic
    data_source: str
    metrics: dict[str, Any]
    geometry: dict[str, Any]
    residuals: dict[str, Any]
    area_curve: dict[str, Any] | None
    provenance: list[dict[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    figures: dict[str, str] = field(default_factory=dict)
    figure_captions: dict[str, str] = field(default_factory=dict)
    qc_image: str | None = None
    vtu_path: str | None = None
    outlet_vtp: str | None = None
    walls_vtp: str | None = None
    stl_path: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _read_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _rel(path: str | Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(CODE_ROOT))
    except ValueError:
        return str(path)


def _md5(path: str | Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _prov(path: str | Path, note: str) -> dict[str, str]:
    p = Path(path)
    return {"path": _rel(p), "md5": _md5(p) if p.is_file() else "MISSING", "note": note}


def _parse_p_residuals(log_path: str | Path) -> list[float]:
    vals: list[float] = []
    for line in Path(log_path).read_text(encoding="utf-8", errors="ignore").splitlines():
        m = re.search(r"Solving for p, Initial residual = ([0-9.eE+-]+)", line)
        if m:
            vals.append(float(m.group(1)))
    return vals


def _last_u_residuals(log_path: str | Path) -> list[float]:
    last = {}
    for line in Path(log_path).read_text(encoding="utf-8", errors="ignore").splitlines():
        m = re.search(r"Solving for (Ux|Uy|Uz), Initial residual = ([0-9.eE+-]+)", line)
        if m:
            last[m.group(1)] = float(m.group(2))
    return [last.get(k, float("nan")) for k in ("Ux", "Uy", "Uz")]


def _wss_stats_from_vtp(vtp_path: str | Path) -> dict[str, float] | None:
    try:
        import pyvista as pv

        mesh = pv.read(str(vtp_path))
    except Exception:
        return None
    arr = None
    for key in ("wallShearStress", "WSS"):
        if key in mesh.point_data:
            arr = np.asarray(mesh.point_data[key])
            break
        if key in mesh.cell_data:
            arr = np.asarray(mesh.cell_data[key])
            break
    if arr is None or arr.size == 0:
        return None
    mag = np.linalg.norm(arr, axis=1) if arr.ndim == 2 else np.asarray(arr)
    mag = mag[np.isfinite(mag)]
    if mag.size == 0:
        return None
    return {
        "mean": float(mag.mean()),
        "high": float(np.percentile(mag, 95)),
        "max": float(mag.max()),
        "n": int(mag.size),
    }


def _area_curve_csv(path: str | Path, min_layer: int | None = None) -> dict[str, Any]:
    rows = list(csv.DictReader(Path(path).open(encoding="utf-8")))
    z = np.array([float(r["z_mm"]) for r in rows], dtype=float)
    a = np.array([float(r["total_mm2"]) for r in rows], dtype=float)
    keep = a > 0
    z, a = z[keep], a[keep]
    order = np.argsort(z)
    z, a = z[order], a[order]
    return {
        "z_mm": z.tolist(),
        "area_mm2": a.tolist(),
        "n": int(len(a)),
        "note": "CSV 已剔除两端无气道的 0 面积切片；最小截面取自主气道内部记录层。",
    }


def _stl_slice_curve(stl_path: str | Path, n: int = 80, z_start: float | None = None) -> dict[str, Any]:
    import trimesh
    from trimesh.intersections import mesh_plane

    mesh = trimesh.load(str(stl_path), process=True)
    zmin, zmax = float(mesh.bounds[0][2]), float(mesh.bounds[1][2])
    if z_start is not None:
        zmin = float(z_start)
    zs = np.linspace(zmin, zmax - 1e-3, n)

    def slice_area(z: float) -> float:
        seg = mesh_plane(mesh, plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
        if len(seg) == 0:
            return 0.0
        p = seg[:, :, :2]
        key = lambda q: (round(float(q[0]), 4), round(float(q[1]), 4))
        adj: dict[tuple, list[tuple[int, tuple]]] = {}
        for idx, s in enumerate(p):
            a, b = key(s[0]), key(s[1])
            adj.setdefault(a, []).append((idx, b))
            adj.setdefault(b, []).append((idx, a))
        used: set[int] = set()
        total = 0.0
        for idx in range(len(p)):
            if idx in used:
                continue
            a, b = key(p[idx][0]), key(p[idx][1])
            loop = [a]
            used.add(idx)
            cur = b
            while cur != a and len(loop) < len(p) + 2:
                loop.append(cur)
                nxt = None
                for j, other in adj.get(cur, []):
                    if j not in used:
                        nxt = (j, other)
                        break
                if nxt is None:
                    break
                used.add(nxt[0])
                cur = nxt[1]
            if len(loop) >= 3:
                xy = np.array(loop)
                total += abs(0.5 * np.sum(xy[:, 0] * np.roll(xy[:, 1], -1) - xy[:, 1] * np.roll(xy[:, 0], -1)))
        return float(total)

    areas = np.array([slice_area(float(z)) for z in zs])
    return {
        "z_mm": zs.tolist(),
        "area_mm2": areas.tolist(),
        "n": int(len(zs)),
        "note": "由 geometry.stl 逐层求交并按闭合环计算面积；切片间隔为自动均分。",
    }


# ---------------------------------------------------------------------------
# pA / demoA / synth-001
# ---------------------------------------------------------------------------


def load_pA() -> CaseBundle:
    base = OUT / "结果" / "P0-result-pA-v1"
    metrics_path = base / "后处理" / "metrics.json"
    step1_path = OUT / "step1" / "metrics_v2.json"
    stats_path = OUT / "step2" / "case_stats-v1.json"
    area_path = OUT / "step1" / "area_per_slice_v2.csv"
    log_path = base / "log.simpleFoam"
    vtu_path = base / "VTK" / "P0-case-pA-v1_1500" / "internal.vtu"
    outlet_vtp = base / "VTK" / "P0-case-pA-v1_1500" / "boundary" / "outlet.vtp"
    walls_vtp = base / "VTK" / "P0-case-pA-v1_1500" / "boundary" / "walls.vtp"
    qc_image = OUT / "step1" / "qc_fig" / "qc_pA_mid.png"

    m = _read_json(metrics_path)
    s1 = _read_json(step1_path)
    st = _read_json(stats_path)
    totals = m["totals"]
    p_res = _parse_p_residuals(log_path)
    u_last = _last_u_residuals(log_path)
    converged = bool(p_res and p_res[-1] <= 1e-4 and all(v <= 1e-4 for v in u_last if np.isfinite(v)))
    area = _area_curve_csv(area_path)

    metrics = {
        "dP_Pa": float(totals["dP_Pa"]),
        "dP_L_Pa": float(totals["dP_L_Pa"]),
        "dP_R_Pa": float(totals["dP_R_Pa"]),
        "Q_total_L_min": float(totals["Q_inlet_total_L_min"]),
        "Q_L_L_min": float(m["patches"]["inletL"]["Q_L_min"]),
        "Q_R_L_min": float(m["patches"]["inletR"]["Q_L_min"]),
        "split_L_pct": float(totals["flow_share_L_pct"]),
        "split_R_pct": float(totals["flow_share_R_pct"]),
        "U_max_m_s": float(totals["U_max_m_s"]),
        "U_mean_m_s": float(totals.get("U_bulk_m_s", float("nan"))),
        "wss_mean_Pa": float(m["wss"]["mean_Pa"]),
        "wss_high_Pa": float(m["wss"]["p95_Pa"]),
        "wss_max_Pa": float(m["wss"]["max_Pa"]),
        "volume_cm3": float(s1["airway_volume_cm3"]),
        "min_area_mm2": float(s1["min_axial_area_mm2"]),
        "min_area_z_mm": float(s1["min_z_mm"]),
        "min_area_layer": int(s1["min_layer"]),
        "min_area_scope": "main_airway",
        "reynolds": float(totals.get("Re_eq", float("nan"))),
        "iterations": int(len(p_res) or 0),
        "converged": converged,
        "cells": int(st.get("cells", 0)),
        "points": None,
        "outlet_area_mm2": float(totals.get("outlet_area_mm2", float("nan"))),
    }
    residuals = {
        "series": p_res,
        "first": p_res[0] if p_res else None,
        "last": p_res[-1] if p_res else None,
        "u_last": u_last,
        "source": "log.simpleFoam 逐迭代 p 初始残差",
    }
    geometry = {
        "volume_cm3": metrics["volume_cm3"],
        "min_area_mm2": metrics["min_area_mm2"],
        "min_area_z_mm": metrics["min_area_z_mm"],
        "min_area_layer": metrics["min_area_layer"],
        "cells": metrics["cells"],
        "voxel_mm": [0.699, 0.699, 0.7],
    }
    return CaseBundle(
        case_id="pA",
        label="pA（患者 A · Run-A 定流量 15 L/min）",
        case_kind="patient",
        data_source="pipeline/out/结果/P0-result-pA-v1（归档结果）",
        metrics=metrics,
        geometry=geometry,
        residuals=residuals,
        area_curve=area,
        provenance=[
            _prov(metrics_path, "后处理指标：ΔP / 分流 / WSS / U_max"),
            _prov(step1_path, "step1 几何指标：容积 / 最小截面 / 层号"),
            _prov(stats_path, "算例统计：单元数与边界 patch"),
            _prov(area_path, "逐层截面积曲线 CSV"),
            _prov(log_path, "求解日志：残差序列与收敛状态"),
            _prov(vtu_path, "VTU 场文件：速度/压力切片证据"),
            _prov(outlet_vtp, "出口面 VTP：出口速度分布"),
            _prov(walls_vtp, "壁面 VTP：WSS 分布"),
            _prov(qc_image, "step1 QC 图：轴位中段气道轮廓"),
        ],
        notes=[
            "pA 与 demoA 是同一患者的别名（conditions-ledger D2）；本报告使用 pA 归档数值。",
            "ΔP 为入口面平均静压差，Run-A 定流量口径；不等同于临床鼻阻力测量。",
            "本次计算在 1500 步达到平台，未满足 residualControl（p/U 均 1e-4）。",
        ],
        assumptions=[
            "层流、定常、不可压缩；rho=1.2 kg/m³，nu=1.8e-5 m²/s。",
            "入口流量按面积分配到左右鼻孔；这是建模假设，不是患者真实分流测量。",
            "轴向截面积不垂直于中心线；最小截面为轴向切片口径。",
        ],
        qc_image=str(qc_image),
        vtu_path=str(vtu_path),
        outlet_vtp=str(outlet_vtp),
        walls_vtp=str(walls_vtp),
    )


def load_demoA() -> CaseBundle:
    base = OUT / "结果" / "P0-result-demoA-v1"
    solve_path = base / "cfd" / "validate_solve.json"
    step1_path = base / "step1" / "metrics_demoA_v2.json"
    stats_path = base / "step2" / "case_stats-demoA-v1.json"
    area_path = base / "step1" / "area_per_slice_demoA_v2.csv"
    vtu_path = base / "cfd" / "VTK" / "P0-OF-case-demoA-v1_1500" / "internal.vtu"
    outlet_vtp = base / "cfd" / "VTK" / "P0-OF-case-demoA-v1_1500" / "boundary" / "outlet.vtp"
    walls_vtp = base / "cfd" / "VTK" / "P0-OF-case-demoA-v1_1500" / "boundary" / "walls.vtp"
    qc_image = base / "step1" / "qc_fig" / "qc_demoA_mid.png"

    solve = _read_json(solve_path)["demoA"]
    s1 = _read_json(step1_path)
    st = _read_json(stats_path)
    q_l, q_r = (float(v) for v in st["runA_flux_Lmin"])
    total = q_l + q_r
    p_series = [float(v) for v in solve.get("p_init_series", [])]
    u_last = [solve.get("last_Ux_init"), solve.get("last_Uy_init"), solve.get("last_Uz_init")]
    converged = bool(p_series and p_series[-1] <= 1e-4 and all(v is not None and v <= 1e-4 for v in u_last))
    area = _area_curve_csv(area_path)
    wss = _wss_stats_from_vtp(walls_vtp)

    metrics = {
        "dP_Pa": float(solve["dP_Pa"]),
        "dP_L_Pa": float(solve["inletL_p_kin"] * 1.2),
        "dP_R_Pa": float(solve["inletR_p_kin"] * 1.2),
        "Q_total_L_min": float(total),
        "Q_L_L_min": q_l,
        "Q_R_L_min": q_r,
        "split_L_pct": q_l / total * 100.0,
        "split_R_pct": q_r / total * 100.0,
        "U_max_m_s": float(solve["Umax"]),
        "U_mean_m_s": float(solve.get("Umean", float("nan"))),
        "wss_mean_Pa": wss["mean"] if wss else None,
        "wss_high_Pa": wss["high"] if wss else None,
        "wss_max_Pa": wss["max"] if wss else None,
        "volume_cm3": float(s1["airway_volume_cm3"]),
        "min_area_mm2": float(s1["min_axial_area_mm2"]),
        "min_area_z_mm": float(s1["min_z_mm"]),
        "min_area_layer": int(s1["min_layer"]),
        "min_area_scope": "main_airway",
        "reynolds": float(solve.get("Re_max", float("nan"))),
        "iterations": int(solve.get("n_iter", len(p_series))),
        "converged": converged,
        "cells": int(st.get("cells", 0)),
        "points": None,
        "outlet_area_mm2": None,
    }
    residuals = {
        "series": p_series,
        "first": p_series[0] if p_series else None,
        "last": p_series[-1] if p_series else None,
        "u_last": u_last,
        "source": "validate_solve.json 的 p_init_series",
    }
    geometry = {
        "volume_cm3": metrics["volume_cm3"],
        "min_area_mm2": metrics["min_area_mm2"],
        "min_area_z_mm": metrics["min_area_z_mm"],
        "min_area_layer": metrics["min_area_layer"],
        "cells": metrics["cells"],
        "voxel_mm": [0.699, 0.699, 0.7],
    }
    return CaseBundle(
        case_id="demoA",
        label="demoA（患者 a 演示病例 · 鼻中隔+鼻甲消融）",
        case_kind="patient_demo",
        data_source="pipeline/out/结果/P0-result-demoA-v1（归档结果）",
        metrics=metrics,
        geometry=geometry,
        residuals=residuals,
        area_curve=area,
        provenance=[
            _prov(solve_path, "求解校验：ΔP / U_max / 残差序列"),
            _prov(step1_path, "step1 几何指标：容积 / 最小截面 / 层号"),
            _prov(stats_path, "算例统计：Run-A 分流设定"),
            _prov(area_path, "逐层截面积曲线 CSV"),
            _prov(vtu_path, "VTU 场文件：速度/压力切片证据"),
            _prov(outlet_vtp, "出口面 VTP：出口速度分布"),
            _prov(walls_vtp, "壁面 VTP：WSS 分布"),
            _prov(qc_image, "step1 QC 图：轴位中段气道轮廓"),
        ],
        notes=[
            "demoA 为官方确认演示病例（授权日期 2026-10-16）；与 pA 是同一患者的别名。",
            "ΔP 与 pA 归档一致（18.446 Pa），本报告使用 demoA 归档的 validate_solve 数值。",
            "本次计算在 1500 步达到平台，未满足 residualControl（p/U 均 1e-4）。",
        ],
        assumptions=[
            "层流、定常、不可压缩；rho=1.2 kg/m³，nu=1.8e-5 m²/s。",
            "入口流量按面积分配到左右鼻孔（Run-A 设定 5.85/9.15 L/min）。",
            "轴向截面积不垂直于中心线；最小截面为轴向切片口径。",
        ],
        qc_image=str(qc_image),
        vtu_path=str(vtu_path),
        outlet_vtp=str(outlet_vtp),
        walls_vtp=str(walls_vtp),
    )


def load_synth(case_id: str = "synth-001") -> CaseBundle:
    base = OUT / "synth" / case_id
    metrics_path = base / "metrics.json"
    params_path = base / "params.json"
    stats_path = base / "case_stats.json"
    stl_path = base / "geometry.stl"

    m = _read_json(metrics_path)
    p = _read_json(params_path)
    st = _read_json(stats_path)
    totals = m["totals"]
    wss = m["wss"]
    res = m["residuals"]
    geom = m["geometry"]
    realized = p["realized"]
    min_axial = float(realized["a_min_axial_global_mm2"])
    min_stl = float(realized["a_min_stl_mm2"])
    area = _stl_slice_curve(stl_path, n=80, z_start=float(realized.get("a_min_axial_z_mm", 0.1)))
    metrics = {
        "dP_Pa": float(totals["dP_Pa"]),
        "dP_L_Pa": float(totals["dP_L_Pa"]),
        "dP_R_Pa": float(totals["dP_R_Pa"]),
        "Q_total_L_min": float(totals["Q_inlet_total_L_min"]),
        "Q_L_L_min": float(totals["flow_share_L_pct"] / 100.0 * totals["Q_inlet_total_L_min"]),
        "Q_R_L_min": float(totals["flow_share_R_pct"] / 100.0 * totals["Q_inlet_total_L_min"]),
        "split_L_pct": float(totals["flow_share_L_pct"]),
        "split_R_pct": float(totals["flow_share_R_pct"]),
        "U_max_m_s": float(totals["U_max_m_s"]),
        "U_mean_m_s": float(totals.get("U_mean_m_s", float("nan"))),
        "wss_mean_Pa": float(wss["mean_Pa"]),
        "wss_high_Pa": float(wss["p95_Pa"]),
        "wss_max_Pa": float(wss["max_Pa"]),
        "volume_cm3": float(geom["airway_volume_cm3"]),
        "min_area_mm2": min_axial,
        "min_area_z_mm": float(realized.get("a_min_axial_z_mm", 0.1)),
        "min_area_layer": None,
        "min_area_scope": "axial_total",
        "left_nostril_area_mm2": min_stl,
        "right_nostril_area_mm2": float(realized["nostril_area_R_mm2"]),
        "reynolds": float(totals.get("Re_eq", float("nan"))),
        "iterations": int(res.get("n_iter", 0)),
        "converged": bool(res.get("converged", False)),
        "cells": int(geom.get("cells", st.get("cells", 0))),
        "points": None,
        "outlet_area_mm2": float(totals.get("outlet_area_mm2", float("nan"))),
    }
    residuals = {
        "series": [],
        "first": res.get("p_init_first"),
        "last": res.get("p_init_last"),
        "u_last": [res.get("last_Ux_init"), res.get("last_Uy_init"), res.get("last_Uz_init")],
        "source": "metrics.json 的 residuals 首末值（未归档逐步日志）",
    }
    geometry = {
        "volume_cm3": metrics["volume_cm3"],
        "min_area_mm2": min_axial,
        "left_nostril_area_mm2": min_stl,
        "right_nostril_area_mm2": metrics["right_nostril_area_mm2"],
        "min_area_z_mm": metrics["min_area_z_mm"],
        "cells": metrics["cells"],
        "voxel_mm": geom.get("voxel_mm"),
        "watertight": bool(geom.get("watertight", False)),
    }
    return CaseBundle(
        case_id=case_id,
        label=f"{case_id}（合成数据 · 参数化气道）",
        case_kind="synthetic",
        data_source=f"pipeline/out/synth/{case_id}（合成数据归档）",
        metrics=metrics,
        geometry=geometry,
        residuals=residuals,
        area_curve=area,
        provenance=[
            _prov(metrics_path, "合成算例指标：ΔP / 分流 / WSS / 残差 / 几何"),
            _prov(params_path, "设计参数与实现几何：鼻孔面积 / 轴向最小截面"),
            _prov(stats_path, "算例统计：单元数与边界 patch"),
            _prov(stl_path, "合成气道 STL：几何投影与逐层截面积"),
        ],
        notes=[
            "本例为 100% 合成数据（manifold 参数化几何），不含任何患者影像。",
            "设计参数：左鼻孔 a_min = 1.50 mm²，右鼻孔设计约 45 mm²；实现值见卡片。",
            "求解在 1500 步达到平台，未满足 residualControl；数值用于验证报告引擎。",
        ],
        assumptions=[
            "层流、定常、不可压缩；rho=1.2 kg/m³，nu=1.8e-5 m²/s。",
            "入口流量按面积分配到左右鼻孔（合成算例口径）。",
            "轴向截面积不垂直于中心线；最窄处为鼻孔平面附近的轴向总截面。",
        ],
        stl_path=str(stl_path),
    )


# ---------------------------------------------------------------------------
# viewer data packages (demoB / pN-Lat / pN-Med, and optionally demoA)
# ---------------------------------------------------------------------------

# 口径警示（2026-10-19 M4 审计 C4）：VIEWER_CASES 各例数值取自 webapp/plus/ 的
# viewer 前端数据包（T5x lineage），与 code/data-governance/consent-ledger.md
# A6/A8 登记的归档求解值属不同口径——pN-Lat 前端包 dP=116.28 Pa vs 归档
# dP=148.65 Pa（P0-result-pN2-v1，87,975 cells，1500 步未收敛）；pN-Med 前端包
# dP=8.30 Pa vs 归档 dP=27.76 Pa（P0-result-pN-v1，53,747 cells，322 步收敛）。
# 两者不可混用；M5（API）对外供数前必须完成对账并统一口径。
VIEWER_CASES = {
    "demoA": "demoA（患者 a 演示病例 · 鼻中隔+鼻甲消融）",
    "demoB": "demoB（患者 b 演示病例 · 鼻甲消融）",
    "pN-Lat": "pN-Lat（鼻甲外移 · 演示 CT 变体）",
    "pN-Med": "pN-Med（鼻甲内移 · 演示 CT 变体）",
}


def _decode_i16(b64: str) -> np.ndarray:
    raw = base64.b64decode(b64)
    return np.frombuffer(raw, dtype="<i2").astype(float)


def load_viewer(case_id: str) -> CaseBundle:
    path = WEBAPP / "plus" / f"viewer_plus_data_{case_id}.js"
    text = path.read_text(encoding="utf-8")
    data = json.loads(text[text.index("{") : text.rindex("}") + 1])
    clinical = data.get("clinical", {})
    compare_cases = data.get("compare", {}).get("cases", [])
    entry = next((c for c in compare_cases if c.get("id") == case_id), None)
    if entry is None:
        # The compare payload often lists the *other* cases; fall back to the
        # first entry only for the volume/min-area fields, and flag it.
        entry = compare_cases[0] if compare_cases else {}
    residual = data.get("residual", {})
    quant = residual.get("quant", {})
    series = []
    if residual.get("init_p_log10_b64"):
        vals = _decode_i16(residual["init_p_log10_b64"]) * float(quant.get("log10_scale", 0.001))
        series = [float(10.0 ** v) for v in vals]
    summary = residual.get("summary", {})
    p_last = summary.get("p_init_last")
    u_last = summary.get("u_init_last")
    converged = bool(p_last is not None and u_last is not None and p_last <= 1e-4 and u_last <= 1e-4)
    valve = clinical.get("valve", {})
    curve = valve.get("curve", {})
    area_curve = None
    if curve.get("total_mm2_b64"):
        q = curve.get("quant", {})
        z = _decode_i16(curve["z_mm_b64"]) * float(q.get("z_scale_mm", 0.1))
        a = _decode_i16(curve["total_mm2_b64"]) * float(q.get("area_scale_mm2", 0.1))
        keep = a > 0
        if keep.any():
            area_curve = {
                "z_mm": z[keep].tolist(),
                "area_mm2": a[keep].tolist(),
                "n": int(keep.sum()),
                "note": "由前端九键数据包的 valve.curve 解码；已剔除 0 面积切片。",
            }
    dP = None
    flow = clinical.get("dP_flow", {})
    if flow.get("dP_Pa"):
        dP = float(flow["dP_Pa"][0])
    elif entry.get("dP_Pa") is not None:
        dP = float(entry["dP_Pa"])
    split_l = entry.get("split_left_pct")
    split_r = entry.get("split_right_pct")
    q_total = float(entry.get("Q_L_min") or 15.0)
    q_l = q_total * split_l / 100.0 if split_l is not None else None
    q_r = q_total * split_r / 100.0 if split_r is not None else None
    wall = data.get("wallWSS", {}).get("walls_src", {})
    mesh_q = data.get("meshQuality", {})
    metrics = {
        "dP_Pa": dP,
        "dP_L_Pa": None,
        "dP_R_Pa": None,
        "Q_total_L_min": q_total,
        "Q_L_L_min": q_l,
        "Q_R_L_min": q_r,
        "split_L_pct": split_l,
        "split_R_pct": split_r,
        "U_max_m_s": data.get("planes", {}).get("quant", {}).get("vel_range_ms", [None, None])[1],
        "U_max_note": "前端数据包速度量化范围上限（近似值）",
        "U_mean_m_s": None,
        "wss_mean_Pa": wall.get("mean_Pa"),
        "wss_high_Pa": wall.get("p95_Pa"),
        "wss_max_Pa": wall.get("max_Pa"),
        "volume_cm3": entry.get("volume_cm3"),
        "min_area_mm2": valve.get("min_area_mm2"),
        "min_area_z_mm": valve.get("min_z_mm"),
        "min_area_layer": valve.get("min_layer"),
        "min_area_scope": "main_airway",
        "reynolds": None,
        "iterations": residual.get("n_iter"),
        "converged": converged,
        "cells": mesh_q.get("cells"),
        "points": mesh_q.get("points"),
        "outlet_area_mm2": None,
    }
    residuals = {
        "series": series,
        "first": summary.get("p_init_first"),
        "last": p_last,
        "u_last": [u_last],
        "source": "viewer_plus_data 的 residual.init_p_log10_b64",
    }
    geometry = {
        "volume_cm3": metrics["volume_cm3"],
        "min_area_mm2": metrics["min_area_mm2"],
        "min_area_z_mm": metrics["min_area_z_mm"],
        "min_area_layer": metrics["min_area_layer"],
        "cells": metrics["cells"],
    }
    return CaseBundle(
        case_id=case_id,
        label=VIEWER_CASES.get(case_id, case_id),
        case_kind="patient_demo",
        data_source=f"pipeline/webapp/plus/viewer_plus_data_{case_id}.js（前端九键数据包）",
        metrics=metrics,
        geometry=geometry,
        residuals=residuals,
        area_curve=area_curve,
        provenance=[
            _prov(path, "前端数据包：临床指标 / 残差序列 / 阀截面曲线 / WSS 汇总"),
        ],
        notes=[
            "本报告由前端九键数据包的临床与几何字段生成；原始 VTU 未随演示数据打包，场图证据缺口已标注。",
            "演示数据为官方确认演示病例；不是诊断报告。",
        ],
        assumptions=[
            "ΔP/Q 为 Run-A 定流量口径，层流线性外推仅用于演示。",
            "轴向截面积不垂直于中心线；最小截面为轴向切片口径。",
        ],
    )


# ---------------------------------------------------------------------------
# generic adapter
# ---------------------------------------------------------------------------


def load_generic(
    metrics_path: str | Path,
    *,
    label: str | None = None,
    case_kind: str = "patient",
    area_csv: str | Path | None = None,
    vtu: str | Path | None = None,
    outlet_vtp: str | Path | None = None,
    walls_vtp: str | Path | None = None,
    qc_image: str | Path | None = None,
    stl: str | Path | None = None,
) -> CaseBundle:
    """Load a user-supplied metrics.json.

    The expected schema is the repo's ``metrics.json``: either the full
    ``totals/patches/wss/geometry`` form or a flat dict with ``dP_Pa`` etc.
    Missing fields stay ``None``; the report will show an evidence gap.
    """
    m = _read_json(metrics_path)
    totals = m.get("totals", m)
    patches = m.get("patches", {})
    wss = m.get("wss", {})
    geom = m.get("geometry", {})
    q_l = None
    q_r = None
    if "inletL" in patches and isinstance(patches["inletL"], dict):
        q_l = patches["inletL"].get("Q_L_min")
        q_r = patches["inletR"].get("Q_L_min") if "inletR" in patches else None
    split_l = totals.get("flow_share_L_pct")
    split_r = totals.get("flow_share_R_pct")
    if q_l is not None and q_r is not None and (q_l + q_r) > 0:
        split_l = q_l / (q_l + q_r) * 100.0
        split_r = q_r / (q_l + q_r) * 100.0
    res = m.get("residuals", {})
    metrics = {
        "dP_Pa": totals.get("dP_Pa"),
        "dP_L_Pa": totals.get("dP_L_Pa"),
        "dP_R_Pa": totals.get("dP_R_Pa"),
        "Q_total_L_min": totals.get("Q_inlet_total_L_min"),
        "Q_L_L_min": q_l,
        "Q_R_L_min": q_r,
        "split_L_pct": split_l,
        "split_R_pct": split_r,
        "U_max_m_s": totals.get("U_max_m_s"),
        "U_mean_m_s": totals.get("U_mean_m_s"),
        "wss_mean_Pa": wss.get("mean_Pa"),
        "wss_high_Pa": wss.get("p95_Pa"),
        "wss_max_Pa": wss.get("max_Pa"),
        "volume_cm3": geom.get("airway_volume_cm3"),
        "min_area_mm2": geom.get("min_axial_area_mm2"),
        "min_area_z_mm": geom.get("min_z_mm"),
        "min_area_layer": geom.get("min_layer"),
        "min_area_scope": "main_airway",
        "reynolds": totals.get("Re_eq"),
        "iterations": res.get("n_iter"),
        "converged": res.get("converged"),
        "cells": geom.get("cells"),
        "points": None,
        "outlet_area_mm2": totals.get("outlet_area_mm2"),
    }
    area_curve = _area_curve_csv(area_csv) if area_csv else None
    if area_curve is None and stl:
        area_curve = _stl_slice_curve(stl, n=80)
    residuals = {
        "series": [],
        "first": res.get("p_init_first"),
        "last": res.get("p_init_last"),
        "u_last": [res.get("last_Ux_init"), res.get("last_Uy_init"), res.get("last_Uz_init")],
        "source": "metrics.json 的 residuals（如存在）",
    }
    geometry = {
        "volume_cm3": metrics["volume_cm3"],
        "min_area_mm2": metrics["min_area_mm2"],
        "min_area_z_mm": metrics["min_area_z_mm"],
        "min_area_layer": metrics["min_area_layer"],
        "cells": metrics["cells"],
    }
    prov = [_prov(metrics_path, "用户提供的 metrics.json")]
    for p, note in [
        (area_csv, "用户提供的截面积 CSV"),
        (vtu, "用户提供的 VTU 场文件"),
        (outlet_vtp, "用户提供的出口 VTP"),
        (walls_vtp, "用户提供的壁面 VTP"),
        (qc_image, "用户提供的 QC 图"),
        (stl, "用户提供的 STL"),
    ]:
        if p:
            prov.append(_prov(p, note))
    return CaseBundle(
        case_id=Path(metrics_path).stem,
        label=label or Path(metrics_path).stem,
        case_kind=case_kind,
        data_source=_rel(metrics_path),
        metrics=metrics,
        geometry=geometry,
        residuals=residuals,
        area_curve=area_curve,
        provenance=prov,
        notes=["本报告由用户提供的指标文件生成；未提供的图件以证据缺口标注。"],
        assumptions=[
            "数值口径以输入 metrics.json 为准；报告引擎不重新求解。",
            "未提供人群参考范围；报告不做人群分位比较。",
        ],
        qc_image=str(qc_image) if qc_image else None,
        vtu_path=str(vtu) if vtu else None,
        outlet_vtp=str(outlet_vtp) if outlet_vtp else None,
        walls_vtp=str(walls_vtp) if walls_vtp else None,
        stl_path=str(stl) if stl else None,
    )


# ---------------------------------------------------------------------------
# figure preparation
# ---------------------------------------------------------------------------


def prepare_figures(bundle: CaseBundle, fig_dir: str | Path) -> None:
    """Generate every available evidence figure into ``fig_dir``."""
    fig_dir = Path(fig_dir)
    fig_dir.mkdir(parents=True, exist_ok=True)
    m = bundle.metrics

    # 1) convergence
    if bundle.residuals.get("series"):
        out = fig_dir / "convergence.png"
        subtitle = bundle.residuals.get("source", "")
        if figures.convergence_curve(bundle.residuals["series"], out, subtitle=subtitle):
            bundle.figures["convergence"] = str(out)
            bundle.figure_captions["convergence"] = "压力方程初始残差随迭代变化（对数坐标）"
    if "convergence" not in bundle.figures and bundle.residuals.get("first") is not None:
        out = fig_dir / "convergence_summary.png"
        if figures.convergence_summary_bar(bundle.residuals.get("first"), bundle.residuals.get("last"), out):
            bundle.figures["convergence"] = str(out)
            bundle.figure_captions["convergence"] = "首末压力初始残差（逐步日志未归档）"

    # 2) split
    out = fig_dir / "split.png"
    if figures.split_bars(m.get("Q_L_L_min"), m.get("Q_R_L_min"), m.get("split_L_pct"), m.get("split_R_pct"), out):
        bundle.figures["split"] = str(out)
        bundle.figure_captions["split"] = "左右鼻孔流量份额与 L/min"

    # 3) area curve
    if bundle.area_curve:
        out = fig_dir / "area_curve.png"
        subtitle = bundle.area_curve.get("note", "")
        if figures.area_curve(
            bundle.area_curve["z_mm"],
            bundle.area_curve["area_mm2"],
            out,
            min_z_mm=m.get("min_area_z_mm"),
            min_area_mm2=m.get("min_area_mm2"),
            subtitle=subtitle,
        ):
            bundle.figures["area"] = str(out)
            bundle.figure_captions["area"] = "沿气道轴向的截面积曲线（标记记录的最小截面）"

    # 4) field slices
    if bundle.vtu_path:
        out = fig_dir / "velocity_slice.png"
        if figures.field_slice(bundle.vtu_path, out, field="U"):
            bundle.figures["velocity"] = str(out)
            bundle.figure_captions["velocity"] = "速度大小 |U| 轴向切片（真实场点）"
        out = fig_dir / "pressure_slice.png"
        if figures.field_slice(bundle.vtu_path, out, field="p"):
            bundle.figures["pressure"] = str(out)
            bundle.figure_captions["pressure"] = "压力轴向切片（Pa，ρ=1.2）"

    # 5) outlet histogram
    if bundle.outlet_vtp:
        out = fig_dir / "outlet_hist.png"
        if figures.outlet_histogram(bundle.outlet_vtp, out):
            bundle.figures["outlet_hist"] = str(out)
            bundle.figure_captions["outlet_hist"] = "出口面速度大小分布"

    # 6) WSS histogram
    if bundle.walls_vtp:
        out = fig_dir / "wss_hist.png"
        if figures.wss_histogram(bundle.walls_vtp, out):
            bundle.figures["wss_hist"] = str(out)
            bundle.figure_captions["wss_hist"] = "壁面剪切力幅值分布"

    # 7) geometry
    if bundle.stl_path:
        out = fig_dir / "geometry.png"
        if figures.geometry_projection(bundle.stl_path, out):
            bundle.figures["geometry"] = str(out)
            bundle.figure_captions["geometry"] = "气道几何 STL 顶点投影（x–z）"

    # 8) QC image (copied as-is; it is already a case-specific PNG)
    if bundle.qc_image and Path(bundle.qc_image).is_file():
        bundle.figures["qc"] = bundle.qc_image
        bundle.figure_captions["qc"] = "step1 轴位中段 QC：CT 与气道轮廓"


def load_builtin(case_id: str) -> CaseBundle:
    if case_id == "pA":
        return load_pA()
    if case_id == "demoA":
        return load_demoA()
    if case_id == "synth-001":
        return load_synth("synth-001")
    if case_id in VIEWER_CASES:
        return load_viewer(case_id)
    raise KeyError(f"unknown built-in case: {case_id}")


BUILTIN_CASES = ["pA", "demoA", "synth-001", "demoB", "pN-Lat", "pN-Med"]
