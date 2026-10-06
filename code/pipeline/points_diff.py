# -*- coding: utf-8 -*-
"""决定性测试：笔记本返回网格的坐标点是否偏离我的均匀网格（体积异常溯源）"""
import re, numpy as np

RET = r"%DATA_ROOT%\项目\P0-鼻塞设计工具\阶段2-CFD算例包\结果\P0-result-pA-v4\constant\polyMesh\points"
LOC = r"%QIDI_WORKSPACE%\contest3_workspace\pipeline\out\step2\P0-OF-case-pA-v4\constant\polyMesh\points"

def load_points(path):
    lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    pts = set()
    in_data = False
    for l in lines:
        s = l.strip()
        if s == "(":
            in_data = True
            continue
        if s == ")":
            break
        if in_data and s.startswith("(") and s.endswith(")"):
            x, y, z = map(float, s[1:-1].split())
            pts.add((round(x, 9), round(y, 9), round(z, 9)))
    return pts

pr = load_points(RET)
pl = load_points(LOC)
print(f"返回点数: {len(pr)}, 本地点数: {len(pl)}")
only_ret = pr - pl
only_loc = pl - pr
print(f"仅返回有: {len(only_ret)}, 仅本地有: {len(only_loc)}")
for p in sorted(only_ret)[:10]:
    print("  返回独有点:", p)
for p in sorted(only_loc)[:10]:
    print("  本地独有点:", p)

# z 值分布对比（网格间距 0.7mm 应全部是 0.7 的整数倍）
zr = np.array([p[2] for p in pr])
zl = np.array([p[2] for p in pl])
mod_r = np.abs(zr / 7e-4 - np.round(zr / 7e-4)).max()
mod_l = np.abs(zl / 7e-4 - np.round(zl / 7e-4)).max()
print(f"z 网格性: 返回最大偏差 {mod_r:.2e} | 本地最大偏差 {mod_l:.2e}（0=严格0.7mm整数倍）")
dr = np.diff(np.sort(np.unique(zr)))
dl = np.diff(np.sort(np.unique(zl)))
print(f"z 唯一层间距: 返回 唯一值 {np.unique(np.round(dr, 6))} | 本地 {np.unique(np.round(dl, 6))}")
