# -*- coding: utf-8 -*-
"""v4 网格取证 + 正式压降计算"""
import re, numpy as np

RET = r"G:\参加比赛\罕见无界黑客松\赛题3-鼻腔气流分析\项目\P0-鼻塞设计工具\阶段2-CFD算例包\结果\P0-result-pA-v4\constant\polyMesh"
LOC = r"G:\程序开发\qidicode\qidicode-portable-windows-x64\qidicode-portable\contest3_workspace\pipeline\out\step2\P0-OF-case-pA-v4\constant\polyMesh"

def read_count(path):
    """读 OpenFOAM ASCII 列表文件的元素个数（header后第一个 (N 行）"""
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            s = line.strip()
            m = re.fullmatch(r"\((\d+)", s)
            if m:
                return int(m.group(1))
    return -1

print("===== 文件级对比 =====")
for name in ["points", "faces", "owner", "neighbour", "boundary"]:
    cr, cl = read_count(f"{RET}\\{name}"), read_count(f"{LOC}\\{name}")
    with open(f"{RET}\\{name}", "rb") as f: hr = f.read()
    with open(f"{LOC}\\{name}", "rb") as f: hl = f.read()
    same = "相同" if hr == hl else "不同"
    print(f"  {name:10s} 返回计数={cr:>8}  本地计数={cl:>8}  内容={same}")

print()
print("===== faces/owner 首个差异定位 =====")
for name in ["faces", "owner", "neighbour"]:
    with open(f"{RET}\\{name}", encoding="utf-8", errors="replace") as f: lr = f.readlines()
    with open(f"{LOC}\\{name}", encoding="utf-8", errors="replace") as f: ll = f.readlines()
    n = min(len(lr), len(ll))
    diff_at = None
    for i in range(n):
        if lr[i] != ll[i]:
            diff_at = i
            break
    if diff_at is None:
        print(f"  {name}: 前{n}行无差异 (返回{len(lr)}行 vs 本地{len(ll)}行)")
        if len(lr) != len(ll):
            tail = lr[n:n+3] if len(lr) > len(ll) else ll[n:n+3]
            print(f"    多出行示例: {tail}")
    else:
        print(f"  {name}: 首个差异在行{diff_at}")
        print(f"    返回: {lr[diff_at].strip()[:80]}")
        print(f"    本地: {ll[diff_at].strip()[:80]}")

print()
print("===== z 范围取证 =====")
with open(f"{RET}\\points", encoding="utf-8", errors="replace") as f:
    txt = f.read()
m = re.search(r"\((\d+)\n(.*?)\)\n", txt, re.S)
pts = np.array([list(map(float, l.split())) for l in m.group(2).strip().split("\n")])
print(f"  返回 points: {len(pts)} 个, z范围 [{pts[:,2].min():.4f}, {pts[:,2].max():.4f}] m")
with open(f"{LOC}\\points", encoding="utf-8", errors="replace") as f:
    txt2 = f.read()
m2 = re.search(r"\((\d+)\n(.*?)\)\n", txt2, re.S)
pts2 = np.array([list(map(float, l.split())) for l in m2.group(2).strip().split("\n")])
print(f"  本地 points: {len(pts2)} 个, z范围 [{pts2[:,2].min():.4f}, {pts2[:,2].max():.4f}] m")

print()
print("===== 正式压降（1500步 p 场） =====")
R4 = RET.replace("\\constant\\polyMesh", "")
def patch_p_values(time_dir, patch):
    """从 0/1500 的 p 文件 boundaryField 提取某 patch 的值列表"""
    with open(f"{R4}\\{time_dir}\\p", encoding="utf-8") as f:
        txt = f.read()
    m = re.search(patch + r"\s*\{(.*?)\}", txt, re.S)
    body = m.group(1)
    mv = re.search(r"value\s+(nonuniform List<scalar>|uniform)\s*\(?\s*([\d.eE+-]+)?", body)
    if "nonuniform" in body:
        mm = re.search(r"\(([\s\S]*?)\)", body[body.index("nonuniform"):])
        vals = [float(x) for x in mm.group(1).split()]
        return vals
    return [float(mv.group(2))]

for t in ["1000", "1500"]:
    pl = patch_p_values(t, "inletL"); pr = patch_p_values(t, "inletR")
    pL = sum(pl)/len(pl) * 1.2   # kinematic -> Pa (rho=1.2, 与笔记本口径一致)
    pR = sum(pr)/len(pr) * 1.2
    print(f"  t={t}: p_inletL={pL:.3f} Pa, p_inletR={pR:.3f} Pa, ΔP_mass={((pL*len(pl)+pR*len(pr))/(len(pl)+len(pr))):.3f} Pa")

print()
print("===== 原生 WSS 场统计（1500步 walls） =====")
with open(f"{R4}\\1500\\wallShearStress", encoding="utf-8") as f:
    txt = f.read()
mm = re.search(r"walls\s*\{\s*type\s+\w+;\s*value\s+nonuniform List<vector>\s*\d+\s*\(([\s\S]*?)\)", txt)
if mm:
    vals = np.array([[float(x) for x in line.split()] for line in mm.group(1).strip().split("\n") if line.strip()])
    mag = np.linalg.norm(vals, axis=1)
    print(f"  面数 {len(mag)}, mean={mag.mean():.4f} Pa, median={np.median(mag):.4f}, P95={np.percentile(mag,95):.4f}, max={mag.max():.4f}")
else:
    print("  walls 段解析失败（可能 uniform 或格式不同）")
