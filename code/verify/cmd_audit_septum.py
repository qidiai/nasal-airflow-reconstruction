# -*- coding: utf-8 -*-
"""指挥官审计：中隔位置核查 + 壳层污染定量（R=9 最坏档）"""
import numpy as np
from scipy import ndimage

NPZ = r"G:\程序开发\qidicode\qidicode-portable-windows-x64\qidicode-portable\contest3_workspace\pipeline\out\step2\mask_full.npz"
ZLO, ZHI = 100, 160

data = np.load(NPZ)
mask, cut = data["mask"], data["cut"]
print("mask/cut:", mask.shape, mask.sum(), cut.sum())

# 1) x 直方图（z 窗口内）——看中隔真实位置
hist = mask[ZLO:ZHI, :, :].sum(axis=(0, 1))
print()
print("zwin x-histogram（x=150~300，步长5）:")
for x in range(150, 301, 5):
    print(f"  x={x:3d}: {hist[x]:6d}")

# 真实中隔：在 [180,280] 中找连续≥3列近零(<=hist峰值0.5%)的区间
seg_min = int(hist[180:281].min())
xs_argmin = 180 + int(np.argmin(hist[180:281]))
print(f"\n[180,280] 最小值 x={xs_argmin} hist={seg_min}（若>500 说明该区间无干净中隔）")

# 2) 复算 cavity（与编码手相同流程）
eroded = ndimage.binary_erosion(mask, structure=ndimage.generate_binary_structure(3, 1), iterations=3)
lab, n = ndimage.label(eroded)
sizes = np.bincount(lab.ravel())
keep = int(np.argmax(sizes[1:]) + 1)
cavity = ndimage.binary_dilation(lab == keep, iterations=3) & mask
print(f"cavity_vox={int(cavity.sum())} (编码手报告 1544965)")

# 3) EDT + 壳层（R=9）
d_, ind = ndimage.distance_transform_edt(cavity, return_indices=True)
xgrid = np.arange(512).reshape(1, 1, 512)
dxsign = xgrid - ind[2]
zw3 = np.zeros_like(mask); zw3[ZLO:ZHI] = True
R = 9
shellL = (d_ > 0) & (d_ <= R) & (xgrid < 215) & (dxsign > 0)
shellR = (d_ > 0) & (d_ <= R) & (xgrid >= 215) & (dxsign < 0)
implant = (shellL | shellR) & zw3
print(f"R=9: shellL={int(shellL.sum())} shellR={int(shellR.sum())} (编码手: 274427/268425)")

# 4) 污染分析：壳层体素的 x 分布（直方图化）
imp_x = np.where(implant)[2]
h_imp, edges = np.histogram(imp_x, bins=[100, 120, 140, 160, 180, 200, 215, 230, 240, 250, 270, 290, 310, 330, 351])
print()
print("implant 体素 x 分布:")
for i in range(len(h_imp)):
    print(f"  x∈[{edges[i]:.0f},{edges[i+1]:.0f}): {h_imp[i]:7d}")
# 关键区间：x∈[215,240) 是"疑似左腔中隔带被计入 shellR"的高危区
susp = int(((implant) & (xgrid >= 215)[0, 0][:, None, :].sum(axis=0) == 0).sum()) if False else 0
suspN = int((implant & (np.arange(512) >= 215)[None, None, :] & (np.arange(512) < 240)[None, None, :]).sum())
print(f"\n高危区 x∈[215,240) 的 implant 体素数: {suspN} / {int(implant.sum())} = {suspN/implant.sum()*100:.1f}%")

# 5) 逐层看 x∈[215,240) 的 implant 集中在哪几个 z
susp_z = np.where(implant & (np.arange(512) >= 215)[None, None, :] & (np.arange(512) < 240)[None, None, :])[0]
if len(susp_z):
    print("高危 implant 的 z 分布（前10个层）:", np.unique(susp_z)[:10], "... 层数:", len(np.unique(susp_z)))
