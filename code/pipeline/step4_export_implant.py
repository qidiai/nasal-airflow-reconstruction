# -*- coding: utf-8 -*-
"""环节④：植入体 STL 导出（三档 + v6n2 置入后气域模型）"""
import os
import numpy as np
from scipy import ndimage
from skimage.measure import marching_cubes
import trimesh

NPZ = r"%QIDI_WORKSPACE%\contest3_workspace\pipeline\out\step2\mask_full.npz"
OUT = r"%QIDI_WORKSPACE%\contest3_workspace\pipeline\out\step4"
os.makedirs(OUT, exist_ok=True)
ZLO, ZHI = 100, 160
VOX = 0.3496 * 0.3496 * 0.35  # mm^3（实际ps）

data = np.load(NPZ)
mask = data["mask"]
print("mask:", mask.shape, mask.sum())

# 腔体隔离（与 step3 相同流程）
eroded = ndimage.binary_erosion(mask, structure=ndimage.generate_binary_structure(3, 1), iterations=3)
lab, n = ndimage.label(eroded)
sizes = np.bincount(lab.ravel())
cavity = ndimage.binary_dilation(lab == int(np.argmax(sizes[1:]) + 1), iterations=3) & mask
# EDT 一次
d_, ind = ndimage.distance_transform_edt(cavity, return_indices=True)
xgrid = np.arange(512).reshape(1, 1, 512)
dxsign = xgrid - ind[2]
zw3 = np.zeros_like(mask); zw3[ZLO:ZHI] = True
hist = mask[ZLO:ZHI].sum(axis=(0, 1))
xs_s = 200 + int(np.argmin(hist[200:271]))
print("xs_s =", xs_s)

spacing = (0.35, 0.3496, 0.3496)  # z,y,x mm

def export_mask(mask_arr, path, min_comp_vox=800):
    """导出掩码的封闭 STL（按连通分量拆分，丢弃碎屑）"""
    lab2, n2 = ndimage.label(mask_arr, structure=ndimage.generate_binary_structure(3, 1))
    szs = np.bincount(lab2.ravel())
    kept = 0
    exported = []
    for l in range(1, n2 + 1):
        if szs[l] < min_comp_vox:
            continue
        m2 = lab2 == l
        verts, faces, _, _ = marching_cubes(m2.astype(np.uint8), level=0.5, spacing=spacing)
        mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=True)
        mesh.fix_normals()
        try:
            from trimesh.smoothing import smooth_laplacian
            smooth_laplacian(mesh, iterations=6)
        except Exception:
            pass
        p2 = path.replace(".stl", f"-{kept+1}.stl") if kept > 0 else path
        mesh.export(p2)
        exported.append((os.path.basename(p2), round(abs(mesh.volume)/1000, 2), mesh.is_watertight))
        kept += 1
    dropped = int(sum(szs[l] for l in range(1, n2+1) if szs[l] < min_comp_vox))
    return exported, dropped

print()
for mm, R in [("1mm", 3), ("2mm", 6), ("3mm", 9)]:
    shellL = (d_ > 0) & (d_ <= R) & (xgrid < xs_s) & (dxsign > 0)
    shellR = (d_ > 0) & (d_ <= R) & (xgrid >= xs_s) & (dxsign < 0)
    implant = (shellL | shellR) & zw3
    vox = int(implant.sum())
    print(f"== 档位 {mm} (R={R}): implant={vox} 体素 = {vox*VOX/1000:.2f} cm³")
    exp, dropped = export_mask(implant, os.path.join(OUT, f"P0-implant-{mm}.stl"))
    for name, vol, wt in exp:
        print(f"   导出 {name}: 网格体积 {vol} cm³, 水密={wt}")
    print(f"   碎屑丢弃 {dropped} 体素")

# v6n2 置入后气域
print()
print("== 置入后气域（2mm档） ==")
shellL = (d_ > 0) & (d_ <= 6) & (xgrid < xs_s) & (dxsign > 0)
shellR = (d_ > 0) & (d_ <= 6) & (xgrid >= xs_s) & (dxsign < 0)
mask_narrow = mask & ~((shellL | shellR) & zw3)
print("气域体素:", int(mask_narrow.sum()))
verts, faces, _, _ = marching_cubes(mask_narrow.astype(np.uint8), level=0.5, spacing=spacing)
mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=True)
mesh.fix_normals()
mesh.export(os.path.join(OUT, "P0-airway-2mm-implanted.stl"))
print(f"导出 P0-airway-2mm-implanted.stl: {len(mesh.faces)} 面, 网格体积 {abs(mesh.volume)/1000:.1f} cm³, 水密={mesh.is_watertight}")
print()
print("全部输出:", OUT)
