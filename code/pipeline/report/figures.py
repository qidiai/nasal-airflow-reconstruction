"""Evidence figures for the M4 single-file report.

Every figure is generated from data that belongs to the case being reported.
When a required input is missing, the caller must render an explicit evidence-gap
panel instead of a fabricated chart; this module returns ``False`` in that case.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager

# Chinese labels need a CJK font.  Microsoft YaHei ships with Windows; the
# fallbacks keep the engine usable on a bare Linux box (labels may fall back to
# boxes, but the numbers and layout remain correct).
_CJK = ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Source Han Sans SC", "DejaVu Sans"]
plt.rcParams["font.sans-serif"] = _CJK
plt.rcParams["axes.unicode_minus"] = False

INK = "#1f2d3d"
MUTED = "#61758a"
GRID = "#dbe4ee"
MINT = "#2a9d8f"
ORANGE = "#e07b39"
BLUE = "#3d6fb4"
RED = "#c0392b"


def _save(fig, out: str | Path, dpi: int = 110) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


def _footnote(fig, text: str) -> None:
    """Place a source/caveat line below the axes without colliding with labels."""
    if not text:
        return
    fig.tight_layout()
    fig.text(0.01, 0.01, text, color=MUTED, fontsize=8, va="bottom")


def _axes(ax, title: str, xlabel: str = "", ylabel: str = ""):
    ax.set_title(title, color=INK, fontsize=12, pad=10)
    ax.set_xlabel(xlabel, color=MUTED, fontsize=9)
    ax.set_ylabel(ylabel, color=MUTED, fontsize=9)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.grid(True, color=GRID, linewidth=0.6, alpha=0.9)
    for spine in ax.spines.values():
        spine.set_color(GRID)


def convergence_curve(
    series: list[float] | np.ndarray,
    out: str | Path,
    title: str = "压力方程初始残差随迭代变化",
    subtitle: str = "",
) -> bool:
    """Plot the pressure initial residual.  Requires at least two points."""
    vals = np.asarray([v for v in series if v is not None and np.isfinite(v) and v > 0], dtype=float)
    if vals.size < 2:
        return False
    fig, ax = plt.subplots(figsize=(7.4, 3.3))
    it = np.arange(1, vals.size + 1)
    ax.semilogy(it, vals, color=BLUE, linewidth=1.4)
    ax.scatter([it[-1]], [vals[-1]], color=ORANGE, zorder=3, s=28)
    ax.axhline(1e-4, color=RED, linestyle="--", linewidth=1.0, label="设定判据 1e-4")
    ax.legend(loc="upper right", fontsize=8, frameon=False)
    _axes(ax, title, "迭代步", "初始残差（对数）")
    _footnote(fig, subtitle)
    _save(fig, out)
    return True


def convergence_summary_bar(
    first: float | None,
    last: float | None,
    out: str | Path,
    title: str = "首末压力初始残差（仅首末值可用）",
) -> bool:
    """Two-bar fallback when no per-iteration series is archived."""
    if first is None or last is None or first <= 0 or last <= 0:
        return False
    fig, ax = plt.subplots(figsize=(7.4, 3.0))
    labels = ["首个迭代", "末个迭代"]
    vals = [first, last]
    bars = ax.bar(labels, vals, color=[BLUE, ORANGE], width=0.45)
    ax.set_yscale("log")
    ax.axhline(1e-4, color=RED, linestyle="--", linewidth=1.0, label="设定判据 1e-4")
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v * 1.15, f"{v:.3g}", ha="center", color=INK, fontsize=9)
    ax.legend(loc="upper right", fontsize=8, frameon=False)
    _axes(ax, title, "", "初始残差（对数）")
    _save(fig, out)
    return True


def split_bars(
    q_l: float | None,
    q_r: float | None,
    split_l: float | None,
    split_r: float | None,
    out: str | Path,
    title: str = "两侧鼻孔流量分配",
) -> bool:
    if q_l is None or q_r is None or (q_l + q_r) <= 0:
        return False
    fig, ax = plt.subplots(figsize=(7.4, 2.8))
    total = q_l + q_r
    left = q_l / total * 100.0
    ax.barh(["本病例"], [left], color=MINT, height=0.42, label=f"左侧 {left:.1f}%")
    ax.barh(["本病例"], [100 - left], left=[left], color=BLUE, height=0.42, label=f"右侧 {100-left:.1f}%")
    ax.set_xlim(0, 100)
    ax.text(left / 2, 0, f"{left:.1f}%", ha="center", va="center", color="white", fontsize=11, fontweight="bold")
    ax.text(left + (100 - left) / 2, 0, f"{100-left:.1f}%", ha="center", va="center", color="white", fontsize=11, fontweight="bold")
    ax.text(100.5, 0, f"L {q_l:.2f} / R {q_r:.2f} L/min", va="center", color=MUTED, fontsize=8)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.28), ncol=2, fontsize=8, frameon=False)
    _axes(ax, title, "流量份额（%）", "")
    ax.set_yticks([])
    _save(fig, out)
    return True


def area_curve(
    z_mm: list[float] | np.ndarray,
    area_mm2: list[float] | np.ndarray,
    out: str | Path,
    min_z_mm: float | None = None,
    min_area_mm2: float | None = None,
    title: str = "沿气道轴向的截面积曲线",
    subtitle: str = "",
) -> bool:
    z = np.asarray(z_mm, dtype=float)
    a = np.asarray(area_mm2, dtype=float)
    if z.size < 3 or z.size != a.size:
        return False
    fig, ax = plt.subplots(figsize=(7.4, 3.2))
    ax.plot(z, a, color=MINT, linewidth=1.5)
    if min_z_mm is not None and np.isfinite(min_z_mm):
        ax.axvline(min_z_mm, color=ORANGE, linestyle="--", linewidth=1.0)
        if min_area_mm2 is not None:
            ax.scatter([min_z_mm], [min_area_mm2], color=ORANGE, zorder=3, s=36)
            span = float(z.max() - z.min()) if z.size else 1.0
            near_left = (min_z_mm - float(z.min())) < 0.18 * span
            near_right = (float(z.max()) - min_z_mm) < 0.18 * span
            dx, dy, ha = (20, 70, "left") if near_left else ((-14, 40, "right") if near_right else (12, 30, "left"))
            ax.annotate(
                f"记录的最小截面\n{min_area_mm2:.1f} mm²",
                xy=(min_z_mm, min_area_mm2),
                xytext=(dx, dy),
                textcoords="offset points",
                ha=ha,
                color=ORANGE,
                fontsize=8,
            )
    _axes(ax, title, "轴向位置 z（mm）", "截面积（mm²）")
    _footnote(fig, subtitle)
    _save(fig, out)
    return True


def field_slice(
    vtu_path: str | Path,
    out: str | Path,
    field: str = "U",
    slice_z_mm: float | None = None,
    rho: float = 1.2,
    title: str | None = None,
) -> bool:
    """Render a thin axial slice of a VTU point field as a scatter map.

    This is a 2-D view of real field points, not a volumetric render.  It is
    deliberately labelled as a slice so the reader does not mistake it for a
    surface or volume rendering.
    """
    import meshio

    path = Path(vtu_path)
    if not path.is_file():
        return False
    mesh = meshio.read(path)
    pts = np.asarray(mesh.points, dtype=float)
    if field not in mesh.point_data:
        return False
    vals = np.asarray(mesh.point_data[field], dtype=float)
    if vals.ndim == 2:
        vals = np.linalg.norm(vals, axis=1)
    z = pts[:, 2]
    zmin, zmax = float(z.min()), float(z.max())
    if slice_z_mm is None:
        hist, edges = np.histogram(z, bins=40)
        i = int(np.argmax(hist))
        zc = (edges[i] + edges[i + 1]) / 2
    else:
        zc = slice_z_mm / 1000.0
    half = 0.0008  # 0.8 mm half-thickness
    mask = np.abs(z - zc) <= half
    if mask.sum() < 20:
        return False
    x = pts[mask, 0] * 1000.0
    y = pts[mask, 1] * 1000.0
    v = vals[mask]
    if field.lower() == "p":
        v = v * rho
        label = "压力（Pa）"
    else:
        label = "速度大小 |U|（m/s）"
    # Keep the colour scale readable: clip the extreme 1% tails, state it in the
    # caption rather than silently changing the data.
    lo, hi = np.percentile(v, [1, 99])
    if hi <= lo:
        hi = float(v.max()) if v.max() > lo else lo + 1e-9
    if x.size > 60000:
        idx = np.random.default_rng(7).choice(x.size, 60000, replace=False)
        x, y, v = x[idx], y[idx], v[idx]
    fig, ax = plt.subplots(figsize=(7.4, 4.0))
    sc = ax.scatter(x, y, c=v, s=5, cmap="turbo", vmin=lo, vmax=hi, linewidths=0, alpha=0.95, rasterized=True)
    cb = fig.colorbar(sc, ax=ax, fraction=0.035, pad=0.02)
    cb.set_label(label, color=MUTED, fontsize=9)
    cb.ax.tick_params(labelsize=8, colors=MUTED)
    ax.set_aspect("equal", adjustable="box")
    _axes(ax, title or f"{label}轴向切片（z ≈ {zc*1000:.1f} mm，±0.8 mm）", "x（mm）", "y（mm）")
    _footnote(fig, "色标范围按 1%–99% 点截断；每个点都是该切片内的真实场点。")
    _save(fig, out)
    return True


def outlet_histogram(
    vtp_path: str | Path,
    out: str | Path,
    title: str = "出口面速度大小分布",
) -> bool:
    import pyvista as pv

    path = Path(vtp_path)
    if not path.is_file():
        return False
    try:
        mesh = pv.read(path)
    except Exception:
        return False
    arr = None
    if "U" in mesh.point_data:
        arr = np.asarray(mesh.point_data["U"])
    elif "U" in mesh.cell_data:
        arr = np.asarray(mesh.cell_data["U"])
    if arr is None or arr.size == 0:
        return False
    mag = np.linalg.norm(arr, axis=1) if arr.ndim == 2 else np.asarray(arr)
    mag = mag[np.isfinite(mag)]
    if mag.size < 5:
        return False
    fig, ax = plt.subplots(figsize=(7.4, 3.0))
    ax.hist(mag, bins=30, color=BLUE, alpha=0.86, edgecolor="white", linewidth=0.4)
    ax.axvline(float(mag.mean()), color=ORANGE, linestyle="--", linewidth=1.2, label=f"均值 {mag.mean():.2f} m/s")
    ax.axvline(float(mag.max()), color=RED, linestyle=":", linewidth=1.1, label=f"最大 {mag.max():.2f} m/s")
    ax.legend(loc="upper right", fontsize=8, frameon=False)
    _axes(ax, title, "速度大小 |U|（m/s）", "面/点计数")
    _footnote(fig, f"样本数 {mag.size}；数据来自出口面 VTP 的 U 场。")
    _save(fig, out)
    return True


def wss_histogram(
    vtp_path: str | Path,
    out: str | Path,
    title: str = "壁面剪切力幅值分布",
) -> bool:
    import pyvista as pv

    path = Path(vtp_path)
    if not path.is_file():
        return False
    try:
        mesh = pv.read(path)
    except Exception:
        return False
    arr = None
    for key in ("wallShearStress", "WSS", "wallShearStressMean"):
        if key in mesh.point_data:
            arr = np.asarray(mesh.point_data[key])
            break
        if key in mesh.cell_data:
            arr = np.asarray(mesh.cell_data[key])
            break
    if arr is None or arr.size == 0:
        return False
    mag = np.linalg.norm(arr, axis=1) if arr.ndim == 2 else np.asarray(arr)
    mag = mag[np.isfinite(mag)]
    if mag.size < 20:
        return False
    fig, ax = plt.subplots(figsize=(7.4, 3.0))
    ax.hist(mag, bins=40, color=MINT, alpha=0.86, edgecolor="white", linewidth=0.4)
    ax.axvline(float(mag.mean()), color=ORANGE, linestyle="--", linewidth=1.2, label=f"均值 {mag.mean():.3f} Pa")
    ax.legend(loc="upper right", fontsize=8, frameon=False)
    _axes(ax, title, "壁面剪切力幅值（Pa）", "面/点计数")
    _footnote(fig, "由 walls 面 VTP 的 wallShearStress 矢量取模；与后处理 WSS 口径可能相差数个百分点。")
    _save(fig, out)
    return True


def geometry_projection(
    stl_path: str | Path,
    out: str | Path,
    title: str = "气道几何 STL 顶点投影（x–z）",
) -> bool:
    import trimesh

    path = Path(stl_path)
    if not path.is_file():
        return False
    mesh = trimesh.load(path, process=True)
    v = np.asarray(mesh.vertices)
    if v.size == 0:
        return False
    fig, ax = plt.subplots(figsize=(7.4, 3.6))
    hb = ax.hexbin(v[:, 0], v[:, 2], gridsize=65, cmap="viridis", mincnt=1, linewidths=0)
    cb = fig.colorbar(hb, ax=ax, fraction=0.035, pad=0.02)
    cb.set_label("顶点密度", color=MUTED, fontsize=9)
    cb.ax.tick_params(labelsize=8, colors=MUTED)
    ax.set_aspect("equal", adjustable="box")
    _axes(ax, title, "x（mm）", "z（mm）")
    _footnote(fig, f"STL 顶点 {len(v)} 个；投影只用于展示几何轮廓，不替代三维查看器。")
    _save(fig, out)
    return True
