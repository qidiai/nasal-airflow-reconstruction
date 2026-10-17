"""出口/入口一致性探针：比较「单元速度 U_c 法向投影」与「面通量等效速度 Q/A」。

用途（第四棒 D-5 复核）：
  在 SIMPLE 收敛场里，边界面通量 phi_b 与 owner 单元速度 U_c 应当一致到
  Rhie-Chow 修正的量级。若两者差 2 倍以上，说明单元速度场与连续性场脱节。

用法:
  python outlet_probe.py <polyMesh 目录> <fields_*.vtk>
只读诊断，不写任何文件。
"""
import re
import sys


def read_int_field(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        txt = f.read()
    txt = txt[txt.index("(") + 1:]
    txt = txt[:txt.index(")")]
    return [int(t) for t in txt.split()]


def read_faces(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        txt = f.read()
    txt = txt[txt.index("\n(") + 2:]
    nums = []
    for tok in txt.replace("(", " ").replace(")", " ").split():
        try:
            nums.append(int(tok))
        except ValueError:
            break
    faces, i = [], 0
    while i < len(nums):
        k = nums[i]
        faces.append(nums[i + 1:i + 1 + k])
        i += 1 + k
    return faces


def read_points(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        txt = f.read()
    txt = "\n".join(ln.split("//")[0] for ln in txt.splitlines())
    txt = txt.replace("(", " ").replace(")", " ")
    maybe_count = [t for t in txt.split() if t.isdigit()]
    n = int(maybe_count[0])
    body = txt[txt.index(maybe_count[0]) + len(maybe_count[0]):]
    nums = [float(t) for t in body.split() if t not in "{}"]
    nums = nums[: 3 * n]
    return [nums[k:k + 3] for k in range(0, len(nums), 3)]


def read_boundary(path):
    """返回 [(name, nFaces, startFace)]"""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        txt = f.read()
    body = txt[txt.index("boundaryField") if "boundaryField" in txt else txt.index("("):]
    out = []
    for m in re.finditer(r"(\w+)\s*\{([^}]*)\}", body):
        name, blk = m.group(1), m.group(2)
        nf = re.search(r"nFaces\s+(\d+)", blk)
        sf = re.search(r"startFace\s+(\d+)", blk)
        if nf and sf:
            out.append((name, int(nf.group(1)), int(sf.group(1))))
    return out


def read_vtk_cells(path, ncells):
    u = [None] * ncells
    p = [None] * ncells
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("VECTORS U"):
            for c in range(ncells):
                a = lines[i + 1 + c].split()
                u[c] = [float(x) for x in a[:3]]
        if ln.startswith("SCALARS p"):
            for c in range(ncells):
                p[c] = float(lines[i + 2 + c].split()[0])
    return u, p


def poly_area(pts, nodes):
    sx = sy = sz = 0.0
    m = len(nodes)
    for i in range(m):
        a = pts[nodes[i]]
        b = pts[nodes[(i + 1) % m]]
        sx += 0.5 * (a[1] * b[2] - a[2] * b[1])
        sy += 0.5 * (a[2] * b[0] - a[0] * b[2])
        sz += 0.5 * (a[0] * b[1] - a[1] * b[0])
    return (sx, sy, sz)


def main(meshdir, vtk):
    pts = read_points(meshdir + r"\points")
    faces = read_faces(meshdir + r"\faces")
    owner = read_int_field(meshdir + r"\owner")
    ncells = max(owner) + 1
    bnd = read_boundary(meshdir + r"\boundary")
    u, p = read_vtk_cells(vtk, ncells)

    print(f"cells {ncells}  boundary:")
    for name, nf, sf in bnd:
        area = 0.0
        un = 0.0
        unabs = 0.0
        uflux = 0.0
        umag = 0.0
        psum = 0.0
        for f in range(sf, sf + nf):
            s = poly_area(pts, faces[f])
            mag = (s[0] ** 2 + s[1] ** 2 + s[2] ** 2) ** 0.5
            c = owner[f]
            nhat = [s[0] / mag, s[1] / mag, s[2] / mag]
            uc = u[c]
            du = uc[0] * nhat[0] + uc[1] * nhat[1] + uc[2] * nhat[2]
            un += du
            unabs += abs(du)
            uflux += uc[0] * s[0] + uc[1] * s[1] + uc[2] * s[2]
            umag += (uc[0] ** 2 + uc[1] ** 2 + uc[2] ** 2) ** 0.5
            psum += p[c]
            area += mag
        print(f"  {name:8s} nf {nf:6d}  A {area:.6e} m2")
        print(f"           U_c.n mean {un/nf:+.6f}  |U_c.n| mean {unabs/nf:.6f}  |U_c| mean {umag/nf:.6f}")
        print(f"           sum(U_c.Sf) {uflux:+.6e} m3/s   (flux-implied vel {uflux/area:+.6f})")
        print(f"           p_c mean {psum/nf:.6f} kin")

    # U_max 位置
    best, bi = -1.0, 0
    for c in range(ncells):
        m = (u[c][0] ** 2 + u[c][1] ** 2 + u[c][2] ** 2) ** 0.5
        if m > best:
            best, bi = m, c
    print(f"U_max |U| {best:.6f} m/s at cell {bi}")

    # 出口面通量等效速度（由总流量 2.5e-4 反推）
    for name, nf, sf in bnd:
        if name == "outlet":
            area = sum(
                (sum(x * x for x in poly_area(pts, faces[f])) ** 0.5)
                for f in range(sf, sf + nf)
            )
            print(f"outlet Q/A for Q=2.5e-4 : {2.5e-4 / area:.6f} m/s")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
