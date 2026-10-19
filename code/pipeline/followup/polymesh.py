"""Minimal OpenFOAM ascii polyMesh reader for the follow-up diff engine.

This is a clean-room reader for the subset of the polyMesh format that the
pipeline writes: ``points``, ``faces``, ``owner``, ``neighbour`` and
``boundary``.  It is intentionally small and dependency-free (numpy only).

The geometry diff uses two levels:

* STL level: ``trimesh`` volume/watertightness + exact plane slices.
* polyMesh level: cell count, points, patch counts, divergence-theorem cell
  volumes, and a volume-per-slab cross-section curve.

The polyMesh volume is the sum of the per-cell volumes; the slab curve is the
mean cross-sectional area over each z-slab (sum of cell volumes / slab
thickness).  It is labelled as a volume-based curve so it is not confused with
the exact STL plane slice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass
class PolyMesh:
    points: np.ndarray
    face_offsets: np.ndarray
    face_indices: np.ndarray
    owner: np.ndarray
    neighbour: np.ndarray
    patches: dict[str, dict] = field(default_factory=dict)
    n_cells: int = 0
    cell_volumes: np.ndarray | None = None
    cell_centroids: np.ndarray | None = None
    face_areas: np.ndarray | None = None
    bbox: tuple[np.ndarray, np.ndarray] | None = None

    @property
    def n_faces(self) -> int:
        return len(self.owner)

    @property
    def n_internal_faces(self) -> int:
        return len(self.neighbour)

    def summary(self) -> dict:
        return {
            "cells": int(self.n_cells),
            "points": int(len(self.points)),
            "faces": int(self.n_faces),
            "internal_faces": int(self.n_internal_faces),
            "patches": self.patches,
            "bbox_mm": None
            if self.bbox is None
            else {"min": (self.bbox[0] * 1000).tolist(), "max": (self.bbox[1] * 1000).tolist()},
            "volume_cm3": None
            if self.cell_volumes is None
            else float(self.cell_volumes.sum() * 1e6),
        }


def _read_header(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    i = 0
    while i < len(lines) and not re.fullmatch(r"\s*\d+\s*", lines[i]):
        i += 1
    if i >= len(lines):
        raise ValueError(f"no array count in {path}")
    return lines[i:]


def _body(lines: list[str]) -> str:
    """Join the body and drop OpenFOAM comment lines/trailing banners."""
    keep = []
    for ln in lines[1:]:
        s = ln.strip()
        if s.startswith("//") or s.startswith("/*") or s.startswith("*"):
            continue
        keep.append(ln)
    return "\n".join(keep)


def read_points(path: str | Path) -> np.ndarray:
    path = Path(path)
    lines = _read_header(path)
    n = int(lines[0])
    body = _body(lines).replace("(", " ").replace(")", " ")
    pts = np.fromstring(body, sep=" ", dtype=np.float64)
    if pts.size < n * 3:
        raise ValueError(f"points truncated: expected {n*3}, got {pts.size}")
    return pts[: n * 3].reshape(n, 3)


def read_int_array(path: str | Path) -> np.ndarray:
    path = Path(path)
    lines = _read_header(path)
    n = int(lines[0])
    body = _body(lines).replace("(", " ").replace(")", " ")
    arr = np.fromstring(body, sep=" ", dtype=np.int64)
    if arr.size < n:
        raise ValueError(f"{path.name} truncated: expected {n}, got {arr.size}")
    return arr[:n]


def read_faces(path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(offsets, indices)`` for the face-vertex lists."""
    path = Path(path)
    lines = _read_header(path)
    n_faces = int(lines[0])
    body = _body(lines).replace("(", " ").replace(")", " ")
    flat = np.fromstring(body, sep=" ", dtype=np.int32)
    starts = np.zeros(n_faces, dtype=np.int64)
    counts = np.zeros(n_faces, dtype=np.int64)
    pos = 0
    for k in range(n_faces):
        cnt = int(flat[pos])
        starts[k] = pos + 1
        counts[k] = cnt
        pos += cnt + 1
    if pos != flat.size:
        raise ValueError(f"faces: consumed {pos} tokens, file has {flat.size}")
    # Remove the count tokens from the flat stream.
    mask = np.ones(flat.size, dtype=bool)
    mask[starts - 1] = False
    indices = flat[mask]
    offsets = np.zeros(n_faces + 1, dtype=np.int64)
    offsets[1:] = np.cumsum(counts)
    if indices.size != int(counts.sum()):
        raise ValueError("face index count mismatch")
    return offsets, indices


def read_boundary(path: str | Path) -> dict[str, dict]:
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    patches = {}
    for name, block in re.findall(r"(\w+)\s*\{([^}]*)\}", text):
        if "nFaces" not in block:
            continue
        n = int(re.search(r"nFaces\s+(\d+)\s*;", block).group(1))
        start = int(re.search(r"startFace\s+(\d+)\s*;", block).group(1))
        typ = re.search(r"type\s+(\w+)\s*;", block)
        patches[name] = {"nFaces": n, "startFace": start, "type": typ.group(1) if typ else None}
    return patches


def _face_geometry(points: np.ndarray, offsets: np.ndarray, indices: np.ndarray):
    """Return scalar volume contributions, face centroids and areas."""
    n_faces = len(offsets) - 1
    counts = np.diff(offsets)
    contrib = np.zeros(n_faces, dtype=np.float64)
    centroids = np.zeros((n_faces, 3), dtype=np.float64)
    areas = np.zeros(n_faces, dtype=np.float64)
    for n in np.unique(counts):
        ids = np.where(counts == n)[0]
        if ids.size == 0:
            continue
        if n < 3:
            continue
        starts = offsets[ids]
        idx = indices[starts[:, None] + np.arange(n)[None, :]]
        p = points[idx]  # (F, n, 3)
        p0 = p[:, 0, :]
        c = np.zeros(ids.size, dtype=np.float64)
        av = np.zeros((ids.size, 3), dtype=np.float64)
        for i in range(1, n - 1):
            cross = np.cross(p[:, i, :], p[:, i + 1, :])
            c += np.einsum("ij,ij->i", p0, cross)
            av += np.cross(p[:, i, :] - p[:, 0, :], p[:, i + 1, :] - p[:, 0, :])
        contrib[ids] = c / 6.0
        centroids[ids] = p.mean(axis=1)
        areas[ids] = 0.5 * np.linalg.norm(av, axis=1)
    return contrib, centroids, areas


def load_mesh(mesh_dir: str | Path, compute_volume: bool = True) -> PolyMesh:
    d = Path(mesh_dir)
    points = read_points(d / "points")
    offsets, indices = read_faces(d / "faces")
    owner = read_int_array(d / "owner")
    neighbour = read_int_array(d / "neighbour")
    patches = read_boundary(d / "boundary")
    n_cells = max(int(owner.max()) + 1, int(neighbour.max()) + 1) if owner.size else 0
    mesh = PolyMesh(
        points=points,
        face_offsets=offsets,
        face_indices=indices,
        owner=owner,
        neighbour=neighbour,
        patches=patches,
        n_cells=n_cells,
        bbox=(points.min(axis=0), points.max(axis=0)),
    )
    if compute_volume and n_cells:
        contrib, centroids, areas = _face_geometry(points, offsets, indices)
        vol = np.bincount(owner, weights=contrib, minlength=n_cells)
        if neighbour.size:
            vol -= np.bincount(neighbour, weights=contrib[: len(neighbour)], minlength=n_cells)
        # OpenFOAM face normals point owner→neighbour; if the sign convention is
        # reversed in a particular writer, the total is negative.  Flip once and
        # record the raw sign in the summary via the absolute value.
        if vol.sum() < 0:
            vol = -vol
            contrib = -contrib
        # Centroids: area-weighted face centroid average per cell.
        w = np.maximum(areas, 1e-30)
        csum = np.zeros((n_cells, 3), dtype=np.float64)
        wsum = np.zeros(n_cells, dtype=np.float64)
        np.add.at(csum, owner, centroids * w[:, None])
        np.add.at(wsum, owner, w)
        if neighbour.size:
            np.add.at(csum, neighbour, centroids[: len(neighbour)] * w[: len(neighbour), None])
            np.add.at(wsum, neighbour, w[: len(neighbour)])
        mesh.cell_volumes = vol
        mesh.cell_centroids = csum / np.maximum(wsum, 1e-30)[:, None]
        mesh.face_areas = areas
    return mesh


def slab_area_curve(
    mesh: PolyMesh,
    axis: int = 2,
    n_bins: int = 80,
    centroids: np.ndarray | None = None,
    z_range: tuple[float, float] | None = None,
) -> dict:
    """Volume-per-slab cross-section curve.

    ``area = sum(cell volume in slab) / slab thickness``.  This is a mean
    cross-section over the slab, not an exact plane slice; the label in the
    diff record says so.

    ``centroids`` lets a caller pass registered centroids (A transformed into
    B's frame); ``z_range`` forces both sides onto the same bin edges.
    """
    if mesh.cell_volumes is None or mesh.cell_centroids is None:
        return {}
    c = mesh.cell_centroids if centroids is None else np.asarray(centroids, dtype=float)
    z = c[:, axis]
    if z_range is None:
        lo, hi = float(z.min()), float(z.max())
    else:
        lo, hi = float(z_range[0]), float(z_range[1])
    edges = np.linspace(lo, hi, n_bins + 1)
    idx = np.clip(np.digitize(z, edges) - 1, 0, n_bins - 1)
    vol_m3 = mesh.cell_volumes
    sums = np.bincount(idx, weights=vol_m3, minlength=n_bins)
    dz = (hi - lo) / n_bins
    # m³ / m = m² → mm²
    area_mm2 = sums / dz * 1e6
    centers_mm = (edges[:-1] + edges[1:]) / 2 * 1000.0
    return {
        "z_mm": centers_mm.tolist(),
        "area_mm2": area_mm2.tolist(),
        "method": "体积法层均截面积 = 层内单元体积和 / 层厚",
        "n_bins": n_bins,
        "z_range_mm": [lo * 1000.0, hi * 1000.0],
    }
