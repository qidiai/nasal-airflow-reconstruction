"""归档 wallShearStress（OpenFOAM 边界场）统计 + 与 metrics.json 的 wss 口径核对。

用法: python of_wss_stats.py <wallShearStress 文件>
"""
import re
import sys

import numpy as np


def read_patch_vectors(path, patch="walls"):
    txt = open(path, "r", encoding="utf-8", errors="replace").read()
    m = re.search(rf"\n\s*{patch}\s*\n\s*\{{", txt)
    if not m:
        raise SystemExit(f"未找到 patch {patch}")
    body = txt[m.end():]
    n = int(re.search(r"\n(\d+)\s*\n\s*\(", body).group(1))
    start = body.index("(", re.search(r"\n(\d+)\s*\n\s*\(", body).end() - 1)
    vecs = []
    for tok in body[start + 1:].split(")"):
        tok = tok.strip().strip("(")
        if not tok or tok.startswith(";"):
            break
        parts = tok.split()
        if len(parts) != 3:
            break
        vecs.append([float(x) for x in parts])
        if len(vecs) == n:
            break
    return np.array(vecs)


if __name__ == "__main__":
    t = read_patch_vectors(sys.argv[1])
    mag = np.linalg.norm(t, axis=1)
    print(f"n_faces {len(t)}")
    print(f"|tau| mean {mag.mean():.6f}  median {np.median(mag):.6f}  "
          f"p95 {np.quantile(mag,0.95):.6f}  max {mag.max():.6f}")
    comp = np.abs(t)
    print("component means:", comp.mean(axis=0))
