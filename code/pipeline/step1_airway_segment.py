# -*- coding: utf-8 -*-
"""
P0 阶段1 v2：鼻腔气道三维重建（修正版）
修正点：鼻孔开放导致 3D 连通失败 → 改用"逐层2D头部填充"法：
  气道 = 空气 ∧ 头部组织二值图填洞后的头内部
"""
import os, json, glob
import numpy as np
import pydicom
from scipy import ndimage
from skimage.measure import marching_cubes
import trimesh
try:
    from trimesh.smoothing import smooth_laplacian as _smooth
except ImportError:
    try:
        from trimesh.smoothing import filter_laplacian as _smooth
    except ImportError:
        _smooth = None
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# T11 开源脱敏：CT 数据目录由环境变量 P0_DICOM_DIR 指定（默认相对路径 ./dicom）
DATA_DIR = os.environ.get("P0_DICOM_DIR", "./dicom")
OUT_DIR = r"%QIDI_WORKSPACE%\contest3_workspace\pipeline\out\step1"
os.makedirs(OUT_DIR, exist_ok=True)

# ---------- 1. 读入 ----------
files = sorted(glob.glob(os.path.join(DATA_DIR, "*.dcm")))
print(f"[1/7] 读取 {len(files)} 层 DICOM ...")
slices = [pydicom.dcmread(f) for f in files]
slices.sort(key=lambda s: float(s.ImagePositionPatient[2]))
nz, rows, cols = len(slices), slices[0].Rows, slices[0].Columns
ps = [float(x) for x in slices[0].PixelSpacing]
dz = abs(float(slices[1].ImagePositionPatient[2]) - float(slices[0].ImagePositionPatient[2]))
vol = np.zeros((nz, rows, cols), dtype=np.int16)
for i, s in enumerate(slices):
    vol[i] = s.pixel_array.astype(np.int16) * int(s.RescaleSlope) + int(s.RescaleIntercept)
print(f"    体数据 {vol.shape}, 像素 {ps[0]:.4f}x{ps[1]:.4f}mm, 层厚 {dz}mm, HU [{vol.min()},{vol.max()}]")

vox_vol = ps[0] * ps[1] * dz  # mm3

# ---------- 2. 逐层2D头部填充 ----------
# 头部组织 = HU > -300（软组织+骨）；填洞后 = 头内部（含鼻腔/鼻窦/咽腔等被包围的空气）
print("[2/7] 逐层2D头部填充（这一步定义'头内部'）...")
head = vol > -300
head_int = np.zeros((nz, rows, cols), dtype=bool)
for i in range(nz):
    head_int[i] = ndimage.binary_fill_holes(head[i])
print(f"    头部体素 {head.sum()/1e6:.1f}M, 头内部 {head_int.sum()/1e6:.1f}M")

# ---------- 3. 气道 = 头内部 ∧ 空气 ----------
air = vol < -400
airway_all = air & head_int
print(f"[3/7] 头内空气: {airway_all.sum()/1e6:.2f}M 体素 = {airway_all.sum()*vox_vol/1000:.2f} cm3")

# ---------- 4. 连通域分析（区分 气道路径 / 鼻窦 / 其他） ----------
lab, n = ndimage.label(airway_all, structure=ndimage.generate_binary_structure(3, 1))
sizes = np.bincount(lab.ravel())
order = np.argsort(sizes)[::-1]
print(f"[4/7] 头内气腔连通域: {n} 个, 前8:")
comps = []
for l in order[:9]:
    if l == 0: continue
    idx = np.where(lab == l)
    zc = idx[0].mean(); vol_cm3 = sizes[l]*vox_vol/1000
    comps.append((int(l), int(sizes[l]), float(vol_cm3), float(zc)))
    print(f"    #{l}: {sizes[l]} 体素 = {vol_cm3:.2f} cm3, z中心层 {int(zc)+1}")
main_lab = comps[0][0]
airway = lab == main_lab
# 合并与主气道邻接的组件（经自然口相连的鼻窦）
main_d = ndimage.binary_dilation(airway)
merged = [f"main {comps[0][2]:.2f}cm3"]
for l, sz, v, zc in comps[1:]:
    if (lab == l).any() and ((lab == l) & main_d).any():
        airway |= (lab == l)
        main_d = ndimage.binary_dilation(airway)
        merged.append(f"#{l} {v:.2f}cm3")
total_cm3 = airway.sum()*vox_vol/1000
print(f"    气道组件合并: {len(merged)} 个 -> 合并后 {total_cm3:.2f} cm3")

# ---------- 5. 截面积曲线 ----------
areas = airway.sum(axis=(1, 2)) * ps[0] * ps[1]
zpos = np.array([float(s.ImagePositionPatient[2]) for s in slices])
xs = np.arange(cols)
cx = float((airway.sum(axis=2).sum(axis=0) * xs).sum() / max(airway.sum(), 1))
mid = int(round(cx))
l_areas = airway[:, :, :mid].sum(axis=(1, 2)) * ps[0] * ps[1]
r_areas = airway[:, :, mid:].sum(axis=(1, 2)) * ps[0] * ps[1]

valid = areas > 0
main_body = valid & (areas >= max(areas) * 0.1)   # 主气道区（去两端边界噪声）
min_idx = int(np.argmin(np.where(main_body, areas, np.inf)))
min_area = float(areas[min_idx])
print(f"[5/7] 截面积: 最大 {max(areas):.0f}, 最小 {min_area:.1f} mm2 @ z={zpos[min_idx]:.1f} (层{min_idx+1}/{nz})")
print(f"    该层 左/右: {l_areas[min_idx]:.1f}/{r_areas[min_idx]:.1f} mm2")
# 左右各自的最小（主气道区内）
lm = int(np.argmin(np.where(main_body, l_areas, np.inf)))
rm = int(np.argmin(np.where(main_body, r_areas, np.inf)))
print(f"    左侧最小 {l_areas[lm]:.1f} @ 层{lm+1}; 右侧最小 {r_areas[rm]:.1f} @ 层{rm+1}")

# ---------- 6. STL ----------
verts, faces, _, _ = marching_cubes(airway.astype(np.uint8), level=0.5,
                                    spacing=(dz, ps[0], ps[1]))
mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=True)
mesh.fix_normals()
if _smooth is not None:
    try:
        _smooth(mesh, iterations=8)
    except Exception as e:
        print("    平滑跳过:", e)
stl_path = os.path.join(OUT_DIR, "airway_pA_v2.stl")
mesh.export(stl_path)
wt = mesh.is_watertight
print(f"[6/7] STL: {os.path.basename(stl_path)} | 顶点 {len(mesh.vertices)}, 面 {len(mesh.faces)}, "
      f"水密={wt}, 网格体积 {abs(mesh.volume)/1000:.2f} vs 掩码 {total_cm3:.2f} cm3")

# ---------- 7. 可视化 + 指标 ----------
fig, ax = plt.subplots(figsize=(12, 5))
ax.plot(zpos[valid], areas[valid], lw=1.6, label="total")
ax.plot(zpos[valid], l_areas[valid], lw=0.9, alpha=0.75, label="left")
ax.plot(zpos[valid], r_areas[valid], lw=0.9, alpha=0.75, label="right")
ax.axvline(zpos[min_idx], color="r", ls="--", label=f"min {min_area:.0f} mm2")
ax.set_xlabel("z (mm, inferior -> superior)")
ax.set_ylabel("axial cross-section area (mm2)")
ax.set_title(f"Patient A nasal airway cross-section curve | vol {total_cm3:.1f} cm3")
ax.legend(); ax.grid(alpha=0.3)
fig.savefig(os.path.join(OUT_DIR, "area_curve_v2.png"), dpi=130, bbox_inches="tight")
plt.close(fig)

fig2, axs = plt.subplots(1, 3, figsize=(13, 4.5))
axs[0].imshow(airway[min_idx], cmap="gray"); axs[0].set_title(f"axial @min layer {min_idx+1} ({min_area:.0f}mm2)")
col_mid = int(np.median(np.where(airway.sum(axis=(0, 1)) > 0)[0]))
row_mid = int(np.median(np.where(airway.sum(axis=(0, 2)) > 0)[0]))
axs[1].imshow(airway[:, :, col_mid][::-1], cmap="gray", aspect=1.0); axs[1].set_title(f"coronal @col {col_mid}")
axs[2].imshow(airway[:, row_mid, :][::-1], cmap="gray", aspect=dz/ps[0]); axs[2].set_title(f"sagittal @row {row_mid}")
for a in axs: a.axis("off")
fig2.savefig(os.path.join(OUT_DIR, "mask_views_v2.png"), dpi=130, bbox_inches="tight")
plt.close(fig2)

np.savetxt(os.path.join(OUT_DIR, "area_per_slice_v2.csv"),
           np.column_stack([np.arange(1, nz + 1), zpos, areas, l_areas, r_areas]),
           delimiter=",", header="slice,z_mm,total_mm2,left_mm2,right_mm2", comments="")

metrics = {
    "patient": "A (soft tissue window, ISO 0.35mm)",
    "method": "per-slice 2D head fill (nostrils open to exterior) -> head-interior air -> largest 3D component",
    "airway_volume_cm3": round(total_cm3, 2),
    "n_components_merged": len(merged),
    "stl": "airway_pA_v2.stl", "stl_watertight": bool(wt),
    "min_axial_area_mm2": round(min_area, 1), "min_layer": min_idx + 1,
    "min_z_mm": round(float(zpos[min_idx]), 1),
    "left_min_mm2": round(float(l_areas[lm]), 1), "left_min_layer": lm + 1,
    "right_min_mm2": round(float(r_areas[rm]), 1), "right_min_layer": rm + 1,
    "left_right_asymmetry": round(float(abs(l_areas[lm]-r_areas[rm]) / max(l_areas[lm], r_areas[rm], 0.01)), 2),
    "midline_x": mid, "n_slices_with_air": int(valid.sum()),
    "caveat": "axial area is not perpendicular to centerline; true nasal-valve area needs centerline analysis (next stage)",
}
with open(os.path.join(OUT_DIR, "metrics_v2.json"), "w", encoding="utf-8") as f:
    json.dump(metrics, f, ensure_ascii=False, indent=2)
print(f"[7/7] 全部输出 -> {OUT_DIR}")
print(json.dumps(metrics, ensure_ascii=False, indent=2))
