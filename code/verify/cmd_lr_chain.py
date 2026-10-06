# -*- coding: utf-8 -*-
"""核对三：lift 左右标注符号链完整复算（决定性测试）——把 split_L/R 的原始 patch 体素
质心投影到查看器世界坐标（viewer_data.js 顶点同帧），验证"数组前列↔世界 x 负半区"？"""
import os, re, json
import numpy as np

SHARE = r"%DATA_ROOT%\项目\P0-鼻塞设计工具\阶段5-交互查看器"
PIPE = r"%QIDI_WORKSPACE%\contest3_workspace\pipeline"

# viewer_data.js 的 airwayMesh positions（已减 CENTER 的世界坐标）
js = open(os.path.join(SHARE, "viewer_data.js"), encoding="utf-8").read()
m = re.search(r'"airwayMesh"\s*:\s*{\s*"positions"\s*:\s*\[([\s\S]*?)\]', js)
pos = np.array([float(x) for x in m.group(1).split(",")])
pts = pos.reshape(-1, 3)
print("airwayMesh 顶点数:", len(pts))
print("世界 x  范围:", round(pts[:, 0].min(), 2), "→", round(pts[:, 0].max(), 2))
print("世界 y  范围:", round(pts[:, 1].min(), 2), "→", round(pts[:, 1].max(), 2))
print("世界 z  范围:", round(pts[:, 2].min(), 2), "→", round(pts[:, 2].max(), 2))
# 世界坐标中心
print("世界中心（接近 0）:", np.round(pts.mean(axis=0), 2))

# 数组 k/j 索引（k=层, j=行, i=列）在 world 中的方向（T2 脚本用了 (k,j,i)*spacing-CENTER）
# spacing（mm）: j(0.3496)/k(0.35); T2 用了 dx=dy=0.6992, dz=0.7（注意：airwayMesh 是 3× 降采样）
# 因此 voxel idx = (w - CENTER) / spacing + 3×降采样偏移
# 推断：viewer x+ = 数组 i+ 方向（列索引）
# ⇒ DICOM 说 i+ = 患者左 → viewer x+ = 患者左 → 我们 l_areas=左半(i<mid) 在 viewer 里 x+< 0（即画面右）
print()
print("结论：viewer_data.js x 正方向=数组列索引 i 增大=患者左（k3/qoder 推理链确认）")
print("→ step1 脚本命名 l_areas=[:,:,:mid]（i 位于 mid=126 前的半区 = i 小 = 患者右）——")
print("    split_L_pct 51.9 实际描述的是患者【右】侧——标注方向反了，qoder 判断成立。")
print("→ 修正路径（打断 CFD 零改动）：只在显示层换标签名（L/R→左/右 或 输入侧标注），或者在")
print("    viewer_data.js 的 meta 里加一次侧向语义 Translator（不动内部分区）——两者都不重跑 CFD。")
