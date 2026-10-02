# -*- coding: utf-8 -*-
"""v4 正式指标 v3：流式解析，零大正则"""
import re, numpy as np, json

R4 = r"G:\参加比赛\罕见无界黑客松\赛题3-鼻腔气流分析\项目\P0-鼻塞设计工具\阶段2-CFD算例包\结果\P0-result-pA-v4"
RHO = 1.2

def count_and_paren(path):
    """流式找 header 后的 N 与 ( 的行号，返回 (count, data_start_line)"""
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    for i, l in enumerate(lines):
        s = l.strip()
        if s == "(":
            # count 是上一行（纯数字）或本行"(N"
            for back in (1, 0):
                j = i - back
                if j >= 0 and re.fullmatch(r"\d+", lines[j].strip()):
                    return int(lines[j].strip()), i + 1, len(lines)
        if re.fullmatch(r"\((\d+)", s):
            return int(s[1:]), i + 1, len(lines)
    raise ValueError(f"未找到数据块: {path}")

def read_scalar_list(path):
    n, s, e = count_and_paren(path)
    vals = np.empty(n)
    idx = 0
    with open(path, encoding="utf-8") as f:
        for i, l in enumerate(f):
            if i < s:
                continue
            for tok in l.replace("(", " ").replace(")", " ").split():
                vals[idx] = float(tok)
                idx += 1
                if idx >= n:
                    return vals
    raise ValueError(f"数据不足 {idx}/{n}: {path}")

def read_vector_list(path):
    n, s, e = count_and_paren(path)
    vals = np.empty((n, 3))
    idx = 0
    with open(path, encoding="utf-8") as f:
        for i, l in enumerate(f):
            if i < s:
                continue
            if "(" in l or ")" in l:
                l = l.replace("(", " ").replace(")", " ")
            toks = l.split()
            for t_i in range(0, len(toks), 3):
                if idx >= n:
                    return vals
                if len(toks) - t_i >= 3:
                    vals[idx] = [float(toks[t_i]), float(toks[t_i+1]), float(toks[t_i+2])]
                    idx += 1
    raise ValueError(f"数据不足 {idx}/{n}: {path}")

def parse_owner_fast():
    return read_scalar_list(f"{R4}\\constant\\polyMesh\\owner").astype(np.int64)

def parse_boundary_fast():
    info = {}
    with open(f"{R4}\\constant\\polyMesh\\boundary", encoding="utf-8") as f:
        txt = f.read()
    for m in re.finditer(r"(\w+)\s*\{\s*type\s+(\w+);\s*nFaces\s+(\d+);\s*startFace\s+(\d+);", txt):
        info[m.group(1)] = dict(type=m.group(2), nFaces=int(m.group(3)), startFace=int(m.group(4)))
    return info

owner = parse_owner_fast()
bnd = parse_boundary_fast()
print("owner len:", len(owner), "| boundary:", {k: v['nFaces'] for k, v in bnd.items()})

def inlet_pressure(t, patch):
    p = read_scalar_list(f"{R4}\\{t}\\p")
    b = bnd[patch]
    cells = owner[b["startFace"]: b["startFace"] + b["nFaces"]]
    return float(p[cells].mean()) * RHO, len(cells)

print("===== 正式压降 =====")
res = {}
for t in ["1000", "1500"]:
    pL, nL = inlet_pressure(t, "inletL")
    pR, nR = inlet_pressure(t, "inletR")
    dP = (pL * nL + pR * nR) / (nL + nR)
    res[t] = (pL, pR, dP)
    print(f"  t={t}: ΔP_L={pL:.3f} Pa, ΔP_R={pR:.3f} Pa, ΔP_total={dP:.3f} Pa")
chg = abs(res['1500'][2] - res['1000'][2]) / abs(res['1000'][2]) * 100
print(f"  稳定性: 1000→1500 变化 {chg:.2f}% {'✅(<2%)' if chg < 2 else '⚠️'}")

print()
print("===== 阻力与不对称 =====")
Q_L, Q_R = 9.750341e-05 * 60, 1.524966e-04 * 60   # L/s
RL = res['1500'][0] / Q_L
RR = res['1500'][1] / Q_R
print(f"  R_L={RL:.1f} Pa/(L/s), R_R={RR:.1f} Pa/(L/s), 比值 {RL/RR:.2f}")

print()
print("===== 原生 WSS（1500步） =====")
try:
    w = read_vector_list(f"{R4}\\1500\\wallShearStress")
    mag = np.linalg.norm(w, axis=1)
    print(f"  面数 {len(mag)} | mean={mag.mean():.4f} | median={np.median(mag):.4f} | P90={np.percentile(mag,90):.4f} | P95={np.percentile(mag,95):.4f} | P99={np.percentile(mag,99):.4f} | max={mag.max():.4f} Pa")
    np.save(f"{R4}\\..\\wss_mag_1500.npy", mag)
except Exception as e:
    print("  WSS 解析失败:", e)

summary = {
    "run": "P0-OF-case-pA-v4 (Run-A, 15 L/min, nu=1.8e-5, majority-vote mesh 269913cells)",
    "deltaP_Pa": {"1000": round(res['1000'][2], 3), "1500": round(res['1500'][2], 3)},
    "deltaP_L_Pa": round(res['1500'][0], 3), "deltaP_R_Pa": round(res['1500'][1], 3),
    "stability_pct_1000to1500": round(chg, 2),
    "flux_closure_pct": 0.05,
    "R_left_Pa_per_Ls": round(RL, 1), "R_right_Pa_per_Ls": round(RR, 1),
}
print()
print(json.dumps(summary, ensure_ascii=False, indent=2))
with open(f"{R4}\\..\\v4_official_metrics.json", "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)
