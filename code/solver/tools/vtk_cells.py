"""解析 flowscope legacy VTK（UNSTRUCTURED_GRID + polyhedron），取 POINTS / U / p。

用法: python vtk_cells.py <file.vtk>  -> 写出同名 .npz（points, U, p）
"""
import sys
import numpy as np


def parse(path):
    with open(path, "r", errors="replace") as f:
        lines = f.read().split("\n")
    i = 0
    pts = None
    U = None
    p = None
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("POINTS"):
            n = int(ln.split()[1])
            arr = np.empty((n, 3))
            i += 1
            for k in range(n):
                v = lines[i + k].split()
                arr[k] = (float(v[0]), float(v[1]), float(v[2]))
            pts = arr
            i += n
            continue
        if ln.startswith("CELL_DATA"):
            n = int(ln.split()[1])
            i += 1
            while i < len(lines):
                ln2 = lines[i]
                if ln2.startswith("VECTORS"):
                    arr = np.empty((n, 3))
                    i += 1
                    for k in range(n):
                        v = lines[i + k].split()
                        arr[k] = (float(v[0]), float(v[1]), float(v[2]))
                    U = arr
                    i += n
                    continue
                if ln2.startswith("SCALARS"):
                    i += 2  # LOOKUP_TABLE
                    arr = np.empty(n)
                    for k in range(n):
                        arr[k] = float(lines[i + k].split()[0])
                    p = arr
                    i += n
                    continue
                if ln2.startswith("POINT_DATA") or ln2.startswith("CELL_TYPES"):
                    break
                i += 1
            continue
        i += 1
    return pts, U, p


if __name__ == "__main__":
    pts, U, p = parse(sys.argv[1])
    out = sys.argv[1].rsplit(".", 1)[0] + ".npz"
    np.savez(out, points=pts, U=U, p=p)
    print("points", pts.shape, "U", None if U is None else U.shape, "p", None if p is None else p.shape, "->", out)
    if U is not None:
        m = np.abs(U).max(axis=1)
        idx = np.argsort(-m)[:15]
        print("top |U| cells:")
        for c in idx:
            print(f"  cell {c:6d} |U| {m[c]:10.4f}  U {U[c]}  p {p[c] if p is not None else 0:12.4f}")
