"""polyMesh 层析诊断：逐 z 层统计细胞数 / 层间流通面数与面积（找瓶颈）。

用法: python mesh_layers.py <polyMesh 目录>
只读诊断，不改任何归档。
"""
import sys
import collections


def read_tokens(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.split("//")[0].replace("(", " ").replace(")", " ")
            for tok in line.split():
                yield tok


def read_list(path):
    toks = read_tokens(path)
    n = None
    out = []
    depth = 0
    for t in toks:
        if n is None:
            try:
                n = int(t)
            except ValueError:
                continue
            continue
        if t == "(":
            depth += 1
            continue
        if t == ")":
            depth -= 1
            if depth <= 0:
                break
            continue
        out.append(t)
        if len(out) > 10_000_000:
            break
    return n, out


def read_points(path):
    n, toks = read_list(path)
    pts = [(float(toks[i]), float(toks[i + 1]), float(toks[i + 2])) for i in range(0, len(toks), 3)]
    return pts


def read_faces(path):
    """返回 [(npts, [ids...])]"""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        txt = f.read()
    txt = txt[txt.index("\n(") + 2:]
    faces = []
    nums = []
    for tok in txt.replace("(", " ").replace(")", " ").split():
        try:
            nums.append(int(tok))
        except ValueError:
            break
    i = 0
    while i < len(nums):
        k = nums[i]
        faces.append(nums[i + 1:i + 1 + k])
        i += 1 + k
    return faces


def read_int_field(path):
    n, toks = read_list(path)
    return [int(t) for t in toks]


def main(meshdir):
    pts = read_points(meshdir + r"\points")
    faces = read_faces(meshdir + r"\faces")
    owner = read_int_field(meshdir + r"\owner")
    neigh = read_int_field(meshdir + r"\neighbour")
    ncells = max(max(owner), max(neigh)) + 1
    ni = len(neigh)
    print(f"points {len(pts)} faces {len(faces)} owner {len(owner)} neigh {len(neigh)} cells {ncells}")

    def poly_area(nodes):
        sx = sy = sz = 0.0
        m = len(nodes)
        for i in range(m):
            a = pts[nodes[i]]
            b = pts[nodes[(i + 1) % m]]
            sx += 0.5 * (a[1] * b[2] - a[2] * b[1])
            sy += 0.5 * (a[2] * b[0] - a[0] * b[2])
            sz += 0.5 * (a[0] * b[1] - a[1] * b[0])
        return sx, sy, sz

    sf = [poly_area(f) for f in faces]
    mag = [(s[0] ** 2 + s[1] ** 2 + s[2] ** 2) ** 0.5 for s in sf]

    # 体积（散度定理）与体心（单元全部顶点的平均；六面体下精确）
    vol = [0.0] * ncells
    vset = [set() for _ in range(ncells)]
    for f, nodes in enumerate(faces):
        o = owner[f]
        s = sf[f]
        cx = sum(pts[k][0] for k in nodes) / len(nodes)
        cy = sum(pts[k][1] for k in nodes) / len(nodes)
        cz = sum(pts[k][2] for k in nodes) / len(nodes)
        v = (cx * s[0] + cy * s[1] + cz * s[2]) / 3.0
        vol[o] += v
        vset[o].update(nodes)
        if f < ni:
            nb = neigh[f]
            vol[nb] -= v
            vset[nb].update(nodes)
    cc = []
    for c in range(ncells):
        vs = list(vset[c])
        cc.append([sum(pts[k][i] for k in vs) / len(vs) for i in range(3)])

    # 逐 z 层：用 z 坐标排序聚类
    zs = sorted(set(round(c[2], 6) for c in cc))
    print(f"z layers: {len(zs)}  range {zs[0]:.6f} .. {zs[-1]:.6f}")
    layer_of = {z: i for i, z in enumerate(zs)}
    lc = collections.Counter(layer_of[round(c[2], 6)] for c in cc)
    # 层间流通：+z 内部面
    cross_n = collections.Counter()
    cross_a = collections.Counter()
    for f in range(ni):
        s = sf[f]
        if abs(s[2]) > 0.5 * mag[f]:
            zc = (cc[owner[f]][2] + cc[neigh[f]][2]) / 2.0
            # 归到较低层
            idx = None
            for i in range(len(zs) - 1):
                if zs[i] < zc <= zs[i + 1]:
                    idx = i
                    break
            if idx is not None:
                cross_n[idx] += 1
                cross_a[idx] += mag[f]

    print("layer  z(m)      cells  crossFaces  crossArea(mm2)")
    for i, z in enumerate(zs):
        print(f"{i:4d}  {z:.6f}  {lc[i]:6d}  {cross_n[i]:8d}   {cross_a[i]*1e6:10.4f}")
    if cross_n:
        mn = min((cross_a[i], i) for i in range(len(zs) - 1))
        print(f"min crossing area {mn[0]*1e6:.4f} mm2 at layer {mn[1]} (z={zs[mn[1]]:.6f})")
    print(f"total volume {sum(vol):.6e} m3  min {min(vol):.4e} max {max(vol):.4e}")


if __name__ == "__main__":
    main(sys.argv[1])
