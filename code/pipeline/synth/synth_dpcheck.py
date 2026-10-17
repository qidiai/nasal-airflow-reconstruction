#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M2.5 synth WSL 内 ΔP 稳定性检查（stdlib only，改编自 M1 trackC wsl_dpcheck.py，
baseline27 同款口径）。读 polyMesh owner/boundary + 最后两个写盘时刻的 p 场，
按 owner 映射到 inletL/inletR/outlet patch cell，算术平均 p -> ΔP 变化率。
用法: python3 synth_dpcheck.py <case_dir> [T1 T2]（缺省取最后两个时刻目录）
"""
import sys, os, re, glob


def read_boundary(path):
    txt = open(path, encoding="utf-8", errors="replace").read()
    out = {}
    for m in re.finditer(r"(\w+)\s*\{\s*type\s+(\w+);\s*nFaces\s+(\d+);\s*startFace\s+(\d+);", txt):
        out[m.group(1)] = (int(m.group(3)), int(m.group(4)))
    return out


def read_owner(path):
    vals = []
    with open(path, encoding="utf-8", errors="replace") as f:
        started = False
        for ln in f:
            s = ln.strip()
            if s == "(":
                started = True
                continue
            if s == ")" or s.startswith(")"):
                break
            if started:
                for tok in s.replace("(", " ").replace(")", " ").split():
                    vals.append(int(tok))
    return vals


def read_p(path):
    """读取 OpenFOAM ascii volScalarField（nonuniform 列表 or uniform 值）"""
    txt = open(path, encoding="utf-8", errors="replace").read()
    seg = txt[txt.find("internalField"):]
    if "boundaryField" in seg:
        seg = seg[:seg.find("boundaryField")]
    num = r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?"
    if "nonuniform" in seg:
        i = seg.find("(")
        vals = [float(x) for x in re.findall(num, seg[i + 1:])]
        return vals, None
    m = re.search(r"uniform\s+(" + num + ")", seg)
    return None, (float(m.group(1)) if m else None)


def patch_cells(owner, bnd, patch):
    nF, sF = bnd[patch]
    return owner[sF:sF + nF]


def dp_at(case, t):
    md = os.path.join(case, "constant", "polyMesh")
    bnd = read_boundary(os.path.join(md, "boundary"))
    owner = read_owner(os.path.join(md, "owner"))
    pfile = os.path.join(case, t, "p")
    if not os.path.isfile(pfile):
        return None
    vals, uni = read_p(pfile)
    if vals is None and uni is None:
        return None

    def pget(i):
        return uni if vals is None else (vals[i] if i < len(vals) else None)

    cl, cr, co = patch_cells(owner, bnd, "inletL"), patch_cells(owner, bnd, "inletR"), patch_cells(owner, bnd, "outlet")
    pl = [pget(i) for i in cl]
    pr = [pget(i) for i in cr]
    po = [pget(i) for i in co]
    if any(v is None for v in pl + pr + po):
        return None
    p_in = (sum(pl) + sum(pr)) / (len(pl) + len(pr))
    p_o = sum(po) / len(po)
    return {"t": t, "p_inlet_kin": p_in, "p_outlet_kin": p_o, "dP_kin": p_in - p_o,
            "dP_Pa": (p_in - p_o) * 1.2, "nL": len(pl), "nR": len(pr)}


def main():
    case = sys.argv[1]
    times = sorted([os.path.basename(d) for d in glob.glob(os.path.join(case, "[0-9]*")) if os.path.isdir(d)],
                   key=lambda x: int(x))
    times = [t for t in times if t != "0"]
    if len(times) < 2:
        print(f"DPCHECK_SKIP {os.path.basename(case)}: 仅 {len(times)} 个写盘时刻，"
              f"当前依赖 residualControl 提前收敛，改用 ΔP 趋势估算口径")
        return
    if len(sys.argv) > 3:
        t1, t2 = sys.argv[2], sys.argv[3]
    else:
        t1, t2 = times[-2], times[-1]
    r1, r2 = dp_at(case, t1), dp_at(case, t2)
    if not r1 or not r2:
        print("DPCHECK_FAIL", case, t1, t2)
        return
    chg = abs(r2["dP_Pa"] - r1["dP_Pa"]) / abs(r1["dP_Pa"]) * 100.0 if r1["dP_Pa"] else 0.0
    print(f"DPCHECK {os.path.basename(case)} t{t1}: dP={r1['dP_Pa']:.4f}Pa  t{t2}: dP={r2['dP_Pa']:.4f}Pa  "
          f"change={chg:.3f}%  {'STABLE(<2%)' if chg < 2 else 'UNSTABLE(>=2%)'}  "
          f"(p_inlet_kin {r1['p_inlet_kin']:.4f}->{r2['p_inlet_kin']:.4f}, p_outlet {r2['p_outlet_kin']:.2e})")


if __name__ == "__main__":
    main()
