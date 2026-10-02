# -*- coding: utf-8 -*-
"""环节③指挥官抽验 + 占位量-ΔP曲线拟合与最终推荐"""
import re, numpy as np

RES = r"%DATA_ROOT%\项目\P0-鼻塞设计工具\阶段2-CFD算例包\结果"
RHO = 1.2

def read_scalar_list(path):
    lines = open(path, encoding="utf-8").read().splitlines()
    for i, l in enumerate(lines):
        s = l.strip()
        if s == "(":
            n = int(lines[i-1].strip())
            vals = []
            for l2 in lines[i+1:]:
                s2 = l2.strip()
                if s2 == ")": break
                vals.append(float(s2))
            a = np.array(vals)
            assert len(a) == n, f"{path}: {len(a)} != {n}"
            return a
        if re.fullmatch(r"\((\d+)", s):
            n = int(s[1:]); vals = []
            for l2 in lines[i+1:]:
                s2 = l2.strip()
                if s2 == ")": break
                vals.append(float(s2))
            return np.array(vals)
    raise ValueError(path)

def parse_owner(path):
    return read_scalar_list(path).astype(np.int64)

def parse_boundary(d):
    txt = open(d + r"\constant\polyMesh\boundary", encoding="utf-8").read()
    info = {}
    for m in re.finditer(r"(\w+)\s*\{\s*type\s+(\w+);\s*nFaces\s+(\d+);\s*startFace\s+(\d+);", txt):
        info[m.group(1)] = dict(nFaces=int(m.group(3)), startFace=int(m.group(4)))
    return info

print("===== 指挥官独立抽验（v6n2，1500步） =====")
d = RES + r"\P0-result-pA-v6n2"
owner = parse_owner(d + r"\constant\polyMesh\owner")
bnd = parse_boundary(d)
p = read_scalar_list(d + r"\1500\p")
tot_w, tot_p = 0.0, 0.0
for patch in ["inletL", "inletR"]:
    b = bnd[patch]
    cells = owner[b["startFace"]: b["startFace"] + b["nFaces"]]
    pm = float(p[cells].mean()) * RHO
    w = b["nFaces"]
    print(f"  {patch}: {w}面, p̄={pm:.2f} Pa")
    tot_w += w; tot_p += pm * w
dP = tot_p / tot_w
print(f"  ΔP(v6n2) = {dP:.2f} Pa  | 笔记本口径 47.32 Pa")

print()
print("===== 占位量-ΔP 曲线拟合（二次，最小二乘） =====")
V = np.array([0.0, 4.366, 8.239, 10.415])       # cm³（narrowing_qc.json）
P = np.array([18.45, 28.55, 47.32, 52.40])      # Pa（诊断报告4）
c = np.polyfit(V, P, 2)
fit = np.polyval(c, V)
res = np.abs(fit - P).max()
print(f"  拟合: ΔP = {c[0]:.4f}·V² + {c[1]:.4f}·V + {c[2]:.3f}")
print(f"  各点拟合偏差: {np.round(fit - P, 2).tolist()} (max {res:.2f} Pa)")
r30 = np.roots([c[0], c[1], c[2] - 30])
v30 = [float(r) for r in r30 if r.imag == 0 and r.real > 0]
v30 = v30[0] if v30 else None
print(f"  ΔP=30 Pa 解: V ≈ {v30:.2f} cm³" if v30 else "  无正根")
r45 = np.roots([c[0], c[1], c[2] - 47.32])
v45 = [float(r) for r in r45 if r.imag == 0 and r.real > 0]
print(f"  ΔP=47.32 Pa 解（交叉验证 v6n2 点）: V ≈ {v45[0]:.2f} cm³ (实测 8.24)")
print()
print("===== 推荐汇总 =====")
print(f"  恢复常人带下限(30 Pa)最小占位: ≈{v30:.1f} cm³（介于1mm档4.37与2mm档8.24之间，≈1.2mm壳）")
print(f"  工程推荐: 2mm档（8.24 cm³ → 47.3 Pa，常人带中部，安全余量）")
print(f"  1mm档（4.37 cm³ → 28.6 Pa）: 略低于带下限，保守可选")
