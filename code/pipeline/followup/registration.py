"""Rigid registration for follow-up pairs (cKDTree + trimmed ICP).

The t25-ma precedent used a cKDTree nearest-neighbour alignment with a reported
0.357 mm residual.  This module keeps the same spirit but makes the method
explicit and records the precision in the output:

1. align centroids;
2. iteratively match source vertices to the target with a cKDTree;
3. trim the worst 10% of pairs (outliers from real geometry change);
4. solve the rigid transform with SVD (Umeyama, no scale);
5. stop when the RMS change is below ``tol``.

Only rigid motion is estimated.  If the two time points have different voxel
grids or a different field of view, the residual will say so; the diff report
must not hide it.
"""

from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree


def _umeyama(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    mu_s = src.mean(axis=0)
    mu_d = dst.mean(axis=0)
    s = src - mu_s
    d = dst - mu_d
    H = s.T @ d
    U, _, Vt = np.linalg.svd(H)
    R = Vt.T @ U.T
    if np.linalg.det(R) < 0:
        Vt[-1, :] *= -1
        R = Vt.T @ U.T
    t = mu_d - R @ mu_s
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = t
    return T


def apply_transform(points: np.ndarray, T: np.ndarray) -> np.ndarray:
    p = np.asarray(points, dtype=float)
    return (T[:3, :3] @ p.T).T + T[:3, 3]


def _sample(points: np.ndarray, n: int, seed: int = 7) -> np.ndarray:
    if len(points) <= n:
        return points
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(points), n, replace=False)
    return points[idx]


def register(
    src: np.ndarray,
    dst: np.ndarray,
    *,
    max_points: int = 40000,
    max_iter: int = 40,
    tol: float = 1e-4,
) -> dict:
    """Register ``src`` to ``dst`` (both in mm) and return a precision record."""
    src_all = np.asarray(src, dtype=float)
    dst_all = np.asarray(dst, dtype=float)
    if len(src_all) < 3 or len(dst_all) < 3:
        raise ValueError("registration needs at least 3 points on each side")
    src_s = _sample(src_all, max_points)
    dst_s = _sample(dst_all, max_points)

    # Initial centroid alignment.
    T = np.eye(4)
    T[:3, 3] = dst_s.mean(axis=0) - src_s.mean(axis=0)
    src_t = apply_transform(src_s, T)

    prev_rms = None
    it = 0
    for it in range(1, max_iter + 1):
        tree = cKDTree(dst_s)
        dist, idx = tree.query(src_t, k=1)
        # Trimmed ICP: drop the worst 10% of correspondences.
        thr = float(np.percentile(dist, 90))
        keep = dist <= max(thr, 1e-6)
        if keep.sum() < 10:
            break
        dT = _umeyama(src_t[keep], dst_s[idx[keep]])
        T = dT @ T
        src_t = apply_transform(src_s, T)
        rms = float(np.sqrt(np.mean(dist[keep] ** 2)))
        if prev_rms is not None and abs(prev_rms - rms) < tol:
            prev_rms = rms
            break
        prev_rms = rms

    # Evaluate on the full source point set after the final transform.
    tree = cKDTree(dst_all)
    src_final = apply_transform(src_all, T)
    dist, _ = tree.query(src_final, k=1)
    return {
        "matrix": T.tolist(),
        "n_src": int(len(src_all)),
        "n_dst": int(len(dst_all)),
        "n_src_sampled": int(len(src_s)),
        "n_dst_sampled": int(len(dst_s)),
        "n_iter": int(it),
        "converged": bool(prev_rms is not None and it < max_iter),
        "rms_mm": float(np.sqrt(np.mean(dist**2))),
        "median_mm": float(np.median(dist)),
        "p95_mm": float(np.percentile(dist, 95)),
        "max_mm": float(np.max(dist)),
        "inlier_ratio_1mm": float(np.mean(dist <= 1.0)),
        "inlier_ratio_2mm": float(np.mean(dist <= 2.0)),
        "method": "cKDTree + trimmed ICP（10% 截尾）+ SVD 刚体配准（无缩放）",
    }
