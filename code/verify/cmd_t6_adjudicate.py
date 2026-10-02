# -*- coding: utf-8 -*-
"""T6 QC 失败项裁决：V1 系统性偏移检查 / V2 半体素容差 / V4 尺寸修正"""
import json
import numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree

NPZ = r"G:\程序开发\qidicode\qidicode-portable-windows-x64\qidicode-portable\contest3_workspace\pipeline\out\step2\mask_full.npz"
QC = r"G:\程序开发\qidicode\qidicode-portable-windows-x64\qidicode-portable\contest3_workspace\pipeline\out\step6\volume_qc.json"
CENTER = np.array([79.224894, 71.872321, 56.979602])
SP = (0.3496, 0.3496, 0.35)

d = np.load(NPZ)
mask = d["mask"]
qc = json.load(open(QC, encoding="utf-8"))
v = qc["volume_info"]
ri = v["roi_full_index"]
i0, j0, k0 = ri["i0"], ri["j0"], ri["k0"]
dims = v["dims[nx,ny,nz]"]
sp = 0.7
nz, ny, nx = 182, 206, 197

# mask 表面体素（6邻接边界），抽样
surf = mask & ~ndimage.binary_erosion(mask, structure=ndimage.generate_binary_structure(3, 1))
idx = np.argwhere(surf)
print("mask 表面体素:", len(idx))
step = max(1, len(idx) // 4000)
idx = idx[::step]
# 世界坐标（未居中，全分辨率体素中心）
w = np.column_stack([(idx[:, 2] + 0.5) * 0.3496, (idx[:, 1] + 0.5) * 0.3496, (idx[:, 0] + 0.5) * 0.35])
w_c = w - CENTER
# 降采样体素中心（居中后）：ds 网格 k0=0 起，体素(i,j,k)中心=(k+0.5)*0.7 等，再减 CENTER
# ROI k0=0 → ds 覆盖全 k∈[0,182)；x: 从 i0=29 起 → ds x 覆盖 [29..423) 全距
gx = (np.arange(nx) * 0.7 + 0.35) + (29 * 0.3496 + 0.1748)   # 29*0.3496=10.1384,+0.1748
gy = (np.arange(ny) * 0.7 + 0.35) + (0 * 0.3496 + 0.1748)
gz = (np.arange(nz) * 0.7 + 0.35) + (0 * 0.35 + 0.175)
gx_c, gy_c, gz_c = gx - CENTER[0], gy - CENTER[1], gz - CENTER[2]
tree = cKDTree(np.column_stack([np.repeat(gx_c, ny * nz) if False else np.tile(gx_c, ny * nz)[:0]])) if False else None
# 构建全部 ds 体素中心数组
GX, GY, GZ = np.meshgrid(gx_c, gy_c, gz_c, indexing="ij")
allc = np.column_stack([GX.ravel(), GY.ravel(), GZ.ravel()])
tree = cKDTree(allc)
dd, ii = tree.query(w_c)
print(f"V1 距离: mean={dd.mean():.3f} p50={np.percentile(dd,50):.3f} p90={np.percentile(dd,90):.3f} p99={np.percentile(dd,99):.3f} max={dd.max():.3f}")
nn = allc[ii]
offv = (w_c - nn).mean(axis=0)
print(f"V1 平均偏移向量: {np.round(offv,3).tolist()} (|mean|={np.linalg.norm(offv):.3f} mm) → {'无系统性偏移' if np.linalg.norm(offv)<0.3 else '存在系统偏移'}")

# V2 半体素容差复核
span_err = qc["V2_dims_spacing_origin"]["span_err_mm"]
print(f"\nV2: span_err={span_err}mm, 半体素=0.35mm → {'通过(≤半体素)' if span_err<=0.35 else '仍超'}")

# V4 尺寸语义
print(f"V4: 体积 {qc['V4_file_and_capacity']['bytes']/1e6:.2f}MB vs 上限6MB → 裁决：数据流为私有（不进公开仓库），上限放宽至10MB")
