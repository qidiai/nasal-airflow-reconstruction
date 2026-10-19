"""STL and polyMesh geometry diff for follow-up pairs.

Two levels are reported, following the F-15 methodology:

* **STL level** — watertightness (trimesh), volume, surface area, exact plane
  slice curves, and a vertex-set difference after registration.
* **polyMesh level** — cell/point/face counts, patch counts, divergence-theorem
  cell volumes, and a volume-per-slab cross-section curve.

The two levels answer different questions.  The STL volume is the geometric
volume of the marching-cubes surface; the polyMesh volume is the sum of the
solver cells and includes the rasterisation ratio.  Both are reported so the
difference cannot be hidden inside one number.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from . import polymesh as pm
from .registration import apply_transform


def load_stl(path: str | Path):
    import trimesh

    return trimesh.load(str(path), process=True)


def stl_summary(path: str | Path) -> dict:
    mesh = load_stl(path)
    return {
        "vertices": int(len(mesh.vertices)),
        "faces": int(len(mesh.faces)),
        "watertight": bool(mesh.is_watertight),
        "volume_cm3": float(mesh.volume / 1000.0),  # STL is in mm, volume is mm³
        "area_mm2": float(mesh.area),
        "bounds_mm": {"min": mesh.bounds[0].tolist(), "max": mesh.bounds[1].tolist()},
        "extents_mm": mesh.extents.tolist(),
    }


def _slice_area(mesh, z: float) -> float:
    from trimesh.intersections import mesh_plane

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


def stl_slice_curve(mesh, n: int = 80, z_start: float | None = None) -> dict:
    zmin, zmax = float(mesh.bounds[0][2]), float(mesh.bounds[1][2])
    if z_start is not None:
        zmin = float(z_start)
    zs = np.linspace(zmin, zmax - 1e-3, n)
    areas = np.array([_slice_area(mesh, float(z)) for z in zs])
    return {
        "z_mm": zs.tolist(),
        "area_mm2": areas.tolist(),
        "n": int(n),
        "method": "STL 逐层平面求交 + 闭合环面积（shoelace）",
    }


def vertex_diff(a_vertices: np.ndarray, b_vertices: np.ndarray, T: np.ndarray) -> dict:
    a_t = apply_transform(a_vertices, T)
    tree_b = cKDTree(b_vertices)
    dist_ab, _ = tree_b.query(a_t, k=1)
    tree_a = cKDTree(a_t)
    dist_ba, _ = tree_a.query(b_vertices, k=1)
    i_max = int(np.argmax(dist_ab))
    return {
        "n_a": int(len(a_t)),
        "n_b": int(len(b_vertices)),
        "a_to_b": {
            "min_mm": float(dist_ab.min()),
            "median_mm": float(np.median(dist_ab)),
            "p95_mm": float(np.percentile(dist_ab, 95)),
            "max_mm": float(dist_ab.max()),
            "max_location_mm": a_t[i_max].tolist(),
            "count_gt_0_5mm": int((dist_ab > 0.5).sum()),
            "count_gt_1mm": int((dist_ab > 1.0).sum()),
            "count_gt_2mm": int((dist_ab > 2.0).sum()),
            "fraction_gt_1mm": float(np.mean(dist_ab > 1.0)),
        },
        "b_to_a": {
            "median_mm": float(np.median(dist_ba)),
            "p95_mm": float(np.percentile(dist_ba, 95)),
            "max_mm": float(dist_ba.max()),
            "count_gt_1mm": int((dist_ba > 1.0).sum()),
            "fraction_gt_1mm": float(np.mean(dist_ba > 1.0)),
        },
        "method": "配准后顶点集 cKDTree 最近邻距离（双向）；顶点数随网格 tessellation 改变，仅作定位证据",
    }


def _central_min(curve: dict, fraction: float = 0.8) -> dict:
    z = np.asarray(curve["z_mm"], dtype=float)
    a = np.asarray(curve["area_mm2"], dtype=float)
    if z.size == 0:
        return {"z_mm": None, "area_mm2": None}
    lo, hi = float(z.min()), float(z.max())
    m = (z >= lo + (1 - fraction) / 2 * (hi - lo)) & (z <= hi - (1 - fraction) / 2 * (hi - lo))
    if not m.any():
        m = np.ones_like(z, dtype=bool)
    i = int(np.argmin(a[m]))
    zz = z[m][i]
    return {"z_mm": float(zz), "area_mm2": float(a[m][i])}


def compare_stl(a_path: str | Path, b_path: str | Path, T: np.ndarray, n_slices: int = 80) -> dict:
    a = load_stl(a_path)
    b = load_stl(b_path)
    sa = stl_summary(a_path)
    sb = stl_summary(b_path)
    # Put A into B's frame for a common slice axis.
    a_reg = a.copy()
    a_reg.vertices = apply_transform(np.asarray(a.vertices), T)
    ca = stl_slice_curve(a_reg, n=n_slices)
    cb = stl_slice_curve(b, n=n_slices)
    va, vb = sa["volume_cm3"], sb["volume_cm3"]
    return {
        "a": sa,
        "b": sb,
        "volume_delta_cm3": float(vb - va),
        "volume_delta_pct": float((vb - va) / va * 100.0) if va else None,
        "area_delta_mm2": float(sb["area_mm2"] - sa["area_mm2"]),
        "watertight": {"a": sa["watertight"], "b": sb["watertight"]},
        "slice_curve": {
            "a": ca,
            "b": cb,
            "min_global": {
                "a": {"z_mm": float(np.asarray(ca["z_mm"])[int(np.argmin(ca["area_mm2"]))]), "area_mm2": float(np.min(ca["area_mm2"]))},
                "b": {"z_mm": float(np.asarray(cb["z_mm"])[int(np.argmin(cb["area_mm2"]))]), "area_mm2": float(np.min(cb["area_mm2"]))},
            },
            "min_central_80pct": {"a": _central_min(ca), "b": _central_min(cb)},
            "note": "A 已按配准矩阵变换到 B 的坐标系；两端开口收敛段会拉低全局最小值，中央 80% 口径另列。",
        },
        "vertex_diff": vertex_diff(np.asarray(a.vertices), np.asarray(b.vertices), T),
    }


def compare_polymesh(a_dir: str | Path, b_dir: str | Path, T: np.ndarray, n_bins: int = 80) -> dict:
    a = pm.load_mesh(a_dir)
    b = pm.load_mesh(b_dir)
    b_z = b.cell_centroids[:, 2] if b.cell_centroids is not None else None
    z_range = (float(b_z.min()), float(b_z.max())) if b_z is not None else None
    ca = pm.slab_area_curve(a, n_bins=n_bins, centroids=apply_transform(a.cell_centroids, T), z_range=z_range)
    cb = pm.slab_area_curve(b, n_bins=n_bins, z_range=z_range)
    va = a.summary()["volume_cm3"]
    vb = b.summary()["volume_cm3"]
    return {
        "a": a.summary(),
        "b": b.summary(),
        "volume_delta_cm3": float(vb - va),
        "volume_delta_pct": float((vb - va) / va * 100.0) if va else None,
        "cells_delta": int(b.n_cells - a.n_cells),
        "points_delta": int(len(b.points) - len(a.points)),
        "faces_delta": int(b.n_faces - a.n_faces),
        "patch_counts": {
            k: {"a": a.patches.get(k, {}).get("nFaces"), "b": b.patches.get(k, {}).get("nFaces")}
            for k in sorted(set(a.patches) | set(b.patches))
        },
        "slab_curve": {"a": ca, "b": cb},
        "note": "polyMesh 体积为单元体积和；层均截面积 = 层内单元体积和 / 层厚。A 的单元质心已按配准矩阵变换到 B 坐标系。",
    }
