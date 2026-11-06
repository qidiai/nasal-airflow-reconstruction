# -*- coding: utf-8 -*-
"""环节④：植入体 STL 导出（三档 + v6n2 置入后气域模型）"""
import os
import glob
import argparse
import numpy as np
from scipy import ndimage
from skimage.measure import marching_cubes
import trimesh

_WS = os.environ.get("QIDI_WORKSPACE")
if not _WS:
    raise SystemExit("[错误] 环境变量 QIDI_WORKSPACE 未设置——本一次性脚本需显式指定工作区后再运行"
                     "（避免在未配置环境的机器上创建字面量 %QIDI_WORKSPACE% 目录）")
NPZ = os.path.join(_WS, "contest3_workspace", "pipeline", "out", "step2", "mask_full.npz")
OUT = os.path.join(_WS, "contest3_workspace", "pipeline", "out", "step4")
os.makedirs(OUT, exist_ok=True)
ZLO, ZHI = 100, 160


def read_case_spacing(dicom_dir):
    """从本例 DICOM 头推导 (dz, ps[0], ps[1]) mm（z,y,x）—— T6/B1。

    同源口径：step1_airway_segment.py:439 spacing=(dz, ps[0], ps[1])、
    step3_make_narrowing.py:609 同式；字段读法参考
    step5_export_viewer_data.py:74-85（pydicom 只读头、取前两张切片
    PixelSpacing + ImagePositionPatient[2] 实测层间距，round 到 4 位）。
    fail-closed：无头/缺字段/不可解析一律 SystemExit，不回退任何写死常量。
    """
    import pydicom
    dcm_files = sorted(glob.glob(os.path.join(dicom_dir, "*.dcm")))
    if len(dcm_files) < 2:
        raise SystemExit(
            f"[错误] DICOM 目录不足 2 个 .dcm：{dicom_dir} —— 无法从本例头推导 spacing，"
            "不回退写死常量（T6/B1）")
    try:
        ds_a = pydicom.dcmread(dcm_files[0], stop_before_pixels=True)
        ds_b = pydicom.dcmread(dcm_files[1], stop_before_pixels=True)
        ps = [float(x) for x in ds_a.PixelSpacing]
        dz = abs(float(ds_b.ImagePositionPatient[2]) - float(ds_a.ImagePositionPatient[2]))
    except Exception as e:
        raise SystemExit(
            f"[错误] 本例 DICOM 头缺 PixelSpacing / ImagePositionPatient 或字段不可解析：{e} "
            "—— 不回退写死常量（T6/B1）")
    if len(ps) < 2 or dz <= 0 or not np.isfinite(dz) or not all(np.isfinite(ps[:2])):
        raise SystemExit(
            f"[错误] 本例 DICOM 头 spacing 不可重建：PixelSpacing={ps}, dz={dz} "
            "—— 不回退写死常量（T6/B1）")
    spacing = (round(dz, 4), round(ps[0], 4), round(ps[1], 4))  # z,y,x mm（step5:83-85 口径）
    return spacing, ds_a


def assert_mask_normalized(mask, ds_a):
    """T6/B1 次选：显式断言输入 mask 已归一化到本例头读 spacing。

    mask 来自 step2 的 mask_full.npz（DICOM 体素坐标，step4 内无重采样；
    step2_make_ofcase.py:725-730 只落盘 mask/cut[/z_frame]，未存 spacing 元数据）。
    故以「面内网格 == 本例 DICOM Rows/Columns」作为「已归一化到该 spacing」的
    可证代理：不一致即说明 mask 已被裁剪/重采样，头读 spacing 不可套用，
    fail-closed 明确报错，绝不静默导出错尺寸 STL。
    层数不比（step1 read_ct_series 会去重/跳过非图像，有效层数可少于 .dcm 文件数）；
    若 step2 未来写入 spacing 键，应在此补一次逐分量数值比对。
    """
    if mask.ndim != 3:
        raise SystemExit(
            f"[错误] 输入 mask 不是三维体素网格（ndim={mask.ndim}）—— 头读 spacing 不可套用，"
            "不导出错尺寸 STL（T6/B1 次选断言）")
    try:
        expected_xy = (int(ds_a.Rows), int(ds_a.Columns))
    except (AttributeError, TypeError, ValueError) as e:
        raise SystemExit(
            f"[错误] 本例 DICOM 头缺 Rows/Columns，无法断言 mask 归一化：{e} "
            "—— 不回退写死常量（T6/B1）")
    if tuple(mask.shape[1:3]) != expected_xy:
        raise SystemExit(
            f"[错误] 输入 mask 未按本例 DICOM 体素网格归一化：mask.shape={tuple(mask.shape)} "
            f"但头读面内 (Rows,Columns)={expected_xy} —— 头读 spacing 不可套用，"
            "不导出错尺寸 STL（T6/B1 次选断言）")
    return True


_AP4 = argparse.ArgumentParser(description="环节④ 植入体 STL 导出（本例 DICOM 头推导 spacing）")
_AP4.add_argument("--dicom-dir", default=None,
                  help="本例 DICOM 目录（默认环境变量 P0_DICOM_DIR；与 step3/cli.py 同源）")
_ARGS4 = _AP4.parse_args()
DICOM_DIR = _ARGS4.dicom_dir or os.environ.get("P0_DICOM_DIR")
if not DICOM_DIR:
    raise SystemExit("[错误] 未指定本例 DICOM 目录（--dicom-dir 或环境变量 P0_DICOM_DIR）"
                     "—— 无法从本例头推导 spacing，不回退写死常量（T6/B1）")

data = np.load(NPZ)
mask = data["mask"]
print("mask:", mask.shape, mask.sum())

# T6/B1：spacing 一律从本例 DICOM 头推导（PixelSpacing + 实测层间距 dz），
# 与 step1:439 / step3:609 / step5:74-85 同源；不再写死参考例体素间距常量。
spacing, _ds_a = read_case_spacing(DICOM_DIR)
assert_mask_normalized(mask, _ds_a)
VOX = spacing[0] * spacing[1] * spacing[2]   # mm^3 = dz * ps[0] * ps[1]（本例头推导）
print(f"spacing(本例 DICOM 头): z={spacing[0]} y={spacing[1]} x={spacing[2]} mm; 体素 {VOX:.6f} mm^3")

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
