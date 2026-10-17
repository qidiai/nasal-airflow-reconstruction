# -*- coding: utf-8 -*-
"""
M2.5 合成数据产线 v1 -- 适配层 A：STL -> 合成 DICOM 序列（喂 step2 接口）

背景：pipeline/step2_make_ofcase.py 的输入契约 = 一个 DICOM 序列目录（*.dcm，
按 ImagePositionPatient[2] 排序），体数据为 HU：
  head = vol > -300（逐层 binary_fill_holes -> 气道内腔被头部掩膜包围即被填入）
  air  = vol < -400
  airway_all = air & head_int   -> 气道掩膜
  cut  = air & ~head_int        -> 头部以外空气（鼻孔分类/NOSTRIL_AT_LOW 判定用）

本脚本把 synth 的水密 STL（鼻腔腔体，鼻孔在 z=0、出口在 z=zmax）栅格化为合成
DICOM 序列，**保持 STL 原始朝向**（与 step2 的 NOSTRIL_AT_LOW=True / pC 实测
路径一致；pA 系真实 CT 是鼻孔在高 z，勿混）：
  1. 鼻孔在低 z（k_min 侧）：其底面暴露于 blob 之外空气（cut），经 step2 的
     else 分支分类为 inlet（再按 x 间断裂为 inletL/inletR）；出口在高 z
     （k_max 侧）：由 NOSTRIL_AT_LOW=True 规则（k_max,+z 面 -> outlet）分类；
  2. 头部 blob = 气道掩膜各向膨胀 8mm（xy 23px@0.35mm / z 12px@0.7mm 可分离
     1D 膨胀近似球形），按气道最底层截底——鼻孔底面暴露；出口顶盖被 blob
     包裹（不影响 outlet 分类）；blob 四周留 12mm FOV 边距；
  3. HU 编码：气道内 = -1000（air），blob 内非气道 = 40（head），其余 = -1000；
  4. 分辨率：in-plane 0.35mm / dz 0.7mm，配合 step2 --voxel-z 0.7（zf=1）
     -> ds2 后 0.7mm 各向同性体素网格，与 pA（in-plane 0.35 -> mesh 0.7mm）同档。

不修改 step2；只产出 DICOM 序列 + dicom_qc.json（栅格化 QC：体积比/水密/连通/
FOV 边距/断面面积）。许可：项目 BSL-1.1；几何由 manifold3d (Apache-2.0) 生成，
无任何患者数据（L1 合成数据）。
"""
import argparse
import json
import os
import time

import numpy as np
import pydicom
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import UID, ExplicitVRLittleEndian, CTImageStorage, generate_uid
from scipy import ndimage
import trimesh
import vtk
from vtk.util import numpy_support

# ---------------------------------------------------------------- 常量
INPLANE_MM = 0.35          # DICOM in-plane 像素间距（step2 ds2 后 mesh xy = 0.7mm）
DZ_MM = 0.7                # DICOM 层厚（step2 --voxel-z 0.7 -> zf=1 -> mesh z = 0.7mm）
HEAD_MARGIN_MM = 8.0       # 头部 blob = 气道各向膨胀 8mm
FOV_MARGIN_MM = 12.0       # FOV 在 blob 外再留 12mm
HU_AIR = -1000             # 气道 + 头部以外
HU_HEAD = 40               # blob 内非气道（> -300 即 head）

CT_SOP_CLASS = UID(CTImageStorage)


def clean_mesh(tm):
    """诊断用：不改几何（零面积面在 pinch 处承担拓扑闭合角色，删除会破坏
    watertight 但对射线奇偶填充无影响），仅如实记录原始 STL 状态。"""
    n0 = len(tm.faces)
    nd = tm.nondegenerate_faces()
    rec = {
        "faces": int(n0),
        "zero_area_faces": int((~nd).sum()),
        "watertight_raw": bool(tm.is_watertight),
        "winding_consistent": bool(tm.is_winding_consistent),
        "bodies_raw": int(tm.body_count),
        "volume_cm3_trimesh": round(float(tm.volume) / 1000.0, 3),
    }
    return tm, rec


def build_polydata(tm):
    """trimesh -> vtkPolyData（保持 STL 原始朝向：鼻孔在 z=0 低 z 侧、
    出口在 z=zmax 高 z 侧——即 step2 的 NOSTRIL_AT_LOW=True 约定，
    与 pC 实测路径一致；pA 系是鼻孔在高 z，勿混）。"""
    v = np.asarray(tm.vertices, dtype=np.float64)
    f = np.asarray(tm.faces, dtype=np.int64)
    pts = vtk.vtkPoints()
    pts.SetData(numpy_support.numpy_to_vtk(v, deep=1))
    ca = vtk.vtkCellArray()
    conn = np.ascontiguousarray(f.ravel(), dtype=np.int64)
    offsets = np.arange(0, conn.size + 1, 3, dtype=np.int64)
    ca.SetData(numpy_support.numpy_to_vtkIdTypeArray(offsets),
               numpy_support.numpy_to_vtkIdTypeArray(conn))
    poly = vtk.vtkPolyData()
    poly.SetPoints(pts)
    poly.SetPolys(ca)
    return poly, v


def rasterize(poly, bounds):
    """vtkPolyDataToImageStencil 精确栅格化（逐 z 层射线奇偶填充），
    返回 (inside[nz,ny,nx] bool, grid info)。"""
    bx0, by0, bz0 = bounds[0]
    bx1, by1, bz1 = bounds[1]
    m = HEAD_MARGIN_MM + FOV_MARGIN_MM
    x0, x1 = bx0 - m, bx1 + m
    y0, y1 = by0 - m, by1 + m
    z0, z1 = bz0 - m, bz1 + m
    nx = int(np.ceil((x1 - x0) / INPLANE_MM))
    ny = int(np.ceil((y1 - y0) / INPLANE_MM))
    nz = int(np.ceil((z1 - z0) / DZ_MM))
    nx += nx % 2   # ds2 xy 2x 取整，偶数维避免丢边
    ny += ny % 2
    nz += nz % 2
    stencil = vtk.vtkPolyDataToImageStencil()
    stencil.SetInputData(poly)
    stencil.SetOutputOrigin(float(x0), float(y0), float(z0))
    stencil.SetOutputSpacing(INPLANE_MM, INPLANE_MM, DZ_MM)
    stencil.SetOutputWholeExtent(0, nx - 1, 0, ny - 1, 0, nz - 1)
    stencil.Update()
    img = vtk.vtkImageStencil()
    image = vtk.vtkImageData()
    image.SetSpacing(INPLANE_MM, INPLANE_MM, DZ_MM)
    image.SetOrigin(float(x0), float(y0), float(z0))
    image.SetExtent(0, nx - 1, 0, ny - 1, 0, nz - 1)
    image.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 1)
    # stencil 语义：stencil 内保留输入值、外用 BackgroundValue -> 输入须填 1
    image.GetPointData().GetScalars().Fill(1)
    img.SetInputData(image)
    img.SetStencilConnection(stencil.GetOutputPort())
    img.SetBackgroundValue(0)   # stencil 外部 -> 0
    img.Update()
    out = img.GetOutput()
    dims = out.GetDimensions()          # (nx, ny, nz)
    arr = numpy_support.vtk_to_numpy(out.GetPointData().GetScalars())
    inside = arr.reshape(dims[2], dims[1], dims[0]).astype(bool)
    grid = dict(x0=float(x0), y0=float(y0), z0=float(z0), nx=nx, ny=ny, nz=nz,
                spacing=[INPLANE_MM, INPLANE_MM, DZ_MM])
    return inside, grid


def head_blob(inside):
    """头部 blob 设计（实测踩坑后定稿）：
      - xy 全向膨胀 8mm：逐层环包气道断面 -> step2 逐层 fill_holes 可把
        气道断面填入 head_int（环不能被按列截底打洞，否则断面泄漏）；
      - z 向**向上**膨胀 8.4mm：包住出口顶盖 -> 出口顶面不算 cut-邻近 ->
        _cut_high=0 -> NOSTRIL_AT_LOW=True 成立（pC 式方向）；
      - z 向**向下**膨胀 8.4mm：包住内部特征底面（鼻窦底等）-> 其底面分类
        为 walls 而非误入 inlet；
      - **例外**：鼻孔列（气道起始层 <= 全局最低层+6 层的列）不向下膨胀——
        鼻孔底面之下必须是 cut（空气），鼻孔底面才能经 step2 else 分支
        分类为 inlet（再按 x 间断裂为 inletL/inletR）。
    """
    hx = int(np.ceil(HEAD_MARGIN_MM / INPLANE_MM))
    hz = int(np.ceil(HEAD_MARGIN_MM / DZ_MM))
    NOSTRIL_MARGIN = 6      # 鼻孔列判定余量（层）；下一批内部特征 >=18 层高
    blob = ndimage.maximum_filter1d(inside, size=2 * hx + 1, axis=2,
                                    mode="constant", cval=0)
    blob = ndimage.maximum_filter1d(blob, size=2 * hx + 1, axis=1,
                                    mode="constant", cval=0)
    nz = inside.shape[0]
    # z 向上膨胀（出口顶盖覆盖）
    up = blob.copy()
    for s in range(1, hz + 1):
        up[s:] |= blob[:-s]
    # z 向下膨胀（内部特征底面覆盖）；但**不高于全局最低气道层+1**——
    # 否则鼻孔平面之下出现 head 环，逐层 fill_holes 会把环内填成伪气道
    # （实测踩坑：鼻孔口被伪延长，inlet 形心漂移）；+1 保证最低层（如倾斜
    # 帽鼻的 R 鼻孔 sliver 所在层）自身的 xy 环仍由 blob/up 提供
    down = blob.copy()
    for s in range(1, hz + 1):
        down[:-s] |= blob[s:]
    has = inside.any(axis=0)
    kc = np.where(has, np.argmax(inside.cumsum(axis=0) > 0, axis=0), nz)
    k_bot = int(kc.min())
    down[:k_bot + 1] = False
    nostril = has & (kc <= k_bot + NOSTRIL_MARGIN)          # (ny, nx)
    keep = np.arange(nz)[:, None, None] >= kc[None, :, :]   # 不低于本列起始层
    out = np.where(nostril[None, :, :], up & keep, up | down)
    return out


def section_areas_inside(inside, grid, ks):
    """栅格体在指定 k 层的断面面积（mm2）与 x 形心。"""
    out = []
    for k in ks:
        sl = inside[k]
        lab, n = ndimage.label(sl)
        for l in range(1, n + 1):
            m = lab == l
            a = float(m.sum()) * INPLANE_MM * INPLANE_MM
            js, isx = np.where(m)
            cx = grid["x0"] + isx.mean() * INPLANE_MM
            out.append((k, round(a, 2), round(cx, 2)))
    return out


def write_dicom_series(hu, grid, case, out_dir):
    """写合成 DICOM 序列（Explicit VR LE，未压缩，int16 HU）。"""
    os.makedirs(out_dir, exist_ok=True)
    nx, ny, nz = grid["nx"], grid["ny"], grid["nz"]
    study_uid = generate_uid()
    series_uid = generate_uid()
    for k in range(nz):
        ds = Dataset()
        ds.file_meta = FileMetaDataset()
        ds.file_meta.MediaStorageSOPClassUID = CT_SOP_CLASS
        sop_uid = generate_uid()
        ds.file_meta.MediaStorageSOPInstanceUID = sop_uid
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds.file_meta.ImplementationClassUID = generate_uid()
        ds.is_little_endian = True
        ds.is_implicit_VR = False
        ds.SOPClassUID = CT_SOP_CLASS
        ds.SOPInstanceUID = sop_uid
        ds.Modality = "CT"
        ds.PatientName = "SYNTH^M2.5"
        ds.PatientID = f"SYNTH-{case}"
        ds.PatientBirthDate = ""
        ds.PatientSex = "O"
        ds.StudyInstanceUID = study_uid
        ds.SeriesInstanceUID = series_uid
        ds.StudyDescription = "M2.5 synthetic nasal airway (no patient data)"
        ds.SeriesDescription = "M2.5 synth L1"
        ds.ImageType = ["DERIVED", "SECONDARY", "AXIAL"]
        ds.Rows = ny
        ds.Columns = nx
        ds.PixelSpacing = [INPLANE_MM, INPLANE_MM]
        ds.SliceThickness = DZ_MM
        ds.SpacingBetweenSlices = DZ_MM
        ds.ImagePositionPatient = [grid["x0"], grid["y0"],
                                   grid["z0"] + k * DZ_MM]
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.RescaleSlope = 1
        ds.RescaleIntercept = 0
        ds.BitsAllocated = 16
        ds.BitsStored = 16
        ds.HighBit = 15
        ds.PixelRepresentation = 1
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.PixelData = np.ascontiguousarray(hu[k], dtype="<i2").tobytes()
        p = os.path.join(out_dir, f"IMG_{k:04d}.dcm")
        ds.save_as(p, enforce_file_format=True)
    return nz


def convert(case, stl_root, dicom_root):
    t0 = time.time()
    src = os.path.join(stl_root, case, "geometry.stl")
    params = json.load(open(os.path.join(stl_root, case, "params.json"),
                            encoding="utf-8"))
    tm = trimesh.load(src)
    tm, clean = clean_mesh(tm)
    poly, verts = build_polydata(tm)
    bounds = (np.asarray(verts).min(axis=0), np.asarray(verts).max(axis=0))
    inside, grid = rasterize(poly, bounds)
    blob = head_blob(inside)
    hu = np.where(blob & ~inside, HU_HEAD, HU_AIR).astype(np.int16)
    # ---- QC ----
    vox_mm3 = INPLANE_MM * INPLANE_MM * DZ_MM
    vol_ras = float(inside.sum()) * vox_mm3 / 1000.0
    ks = np.where(inside.any(axis=(1, 2)))[0]
    k_bot = int(ks.min())
    k_top = int(ks.max())
    # FOV 边距：气道到各边界的距离（mm）
    js, isx = np.where(inside.any(axis=0))
    marg = dict(
        left_mm=round(float(isx.min()) * INPLANE_MM, 2),
        right_mm=round(float(grid["nx"] - 1 - isx.max()) * INPLANE_MM, 2),
        anterior_mm=round(float(js.min()) * INPLANE_MM, 2),
        posterior_mm=round(float(grid["ny"] - 1 - js.max()) * INPLANE_MM, 2),
        bottom_mm=round(float(k_bot) * DZ_MM, 2),
        top_mm=round(float(grid["nz"] - 1 - k_top) * DZ_MM, 2),
    )
    # 每层气道连通分量数（防碎裂）
    per_slice_n = []
    for k in range(k_bot, k_top + 1):
        lab, n = ndimage.label(inside[k])
        per_slice_n.append(int(n))
    # 鼻孔层（最底层）栅格断面 + trimesh 实测对照
    sec_ras = section_areas_inside(inside, grid, [k_bot])
    qc = {
        "case": case,
        "stl": src,
        "grid": grid,
        "fov_margin_mm": marg,
        "volume": {
            "trimesh_cm3": clean["volume_cm3_trimesh"],
            "rasterized_cm3": round(vol_ras, 3),
            "ratio": round(vol_ras / max(clean["volume_cm3_trimesh"], 1e-9), 4),
        },
        "mesh_clean": clean,
        "airway_k_range": [k_bot, k_top],
        "airway_k_span": k_top - k_bot + 1,
        "max_slice_components": int(max(per_slice_n)),
        "nostril_layer_rasterized_areas_mm2": sec_ras,
        "nostril_layer_trimesh_areas_mm2": [
            round(float(params["realized"]["nostril_area_L_mm2"]), 2),
            round(float(params["realized"]["nostril_area_R_mm2"]), 2)],
        "hu_air": HU_AIR, "hu_head": HU_HEAD,
        "head_margin_mm": HEAD_MARGIN_MM, "fov_margin_mm": FOV_MARGIN_MM,
        "orientation": ("nostrils at LOW z (k_min side), outlet at HIGH z "
                        "(k_max side) -> NOSTRIL_AT_LOW=True (pC-style path; "
                        "do NOT confuse with pA-family which has nostrils "
                        "at high z)"),
        "note": ("native STL orientation kept; head blob = 8mm dilation "
                 "clipped at airway bottom layer so nostril caps open to cut "
                 "(else-branch inlet classification); step2 --voxel-z 0.7 "
                 "zf=1 -> 0.7mm isotropic mesh"),
    }
    out_dir = os.path.join(dicom_root, case)
    n = write_dicom_series(hu, grid, case, out_dir)
    qc["n_slices"] = n
    qc["seconds"] = round(time.time() - t0, 1)
    with open(os.path.join(out_dir, "dicom_qc.json"), "w",
              encoding="utf-8", newline="\n") as f:
        json.dump(qc, f, ensure_ascii=False, indent=1)
    return qc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--stl-root", required=True,
                    help="out/synth 根（含 synth-NNN/geometry.stl）")
    ap.add_argument("--dicom-root", required=True)
    args = ap.parse_args()
    cases = sorted(d for d in os.listdir(args.stl_root)
                   if d.startswith("synth-")) if args.all else [args.case]
    for c in cases:
        qc = convert(c, args.stl_root, args.dicom_root)
        print(f"[dicom] {c}: {qc['n_slices']} slices "
              f"{qc['grid']['nx']}x{qc['grid']['ny']}, "
              f"V_ras={qc['volume']['rasterized_cm3']}cm3 "
              f"(ratio {qc['volume']['ratio']}), "
              f"k=[{qc['airway_k_range'][0]},{qc['airway_k_range'][1]}], "
              f"maxslice_comp={qc['max_slice_components']}, "
              f"watertight={qc['mesh_clean']['watertight_raw']}, "
              f"{qc['seconds']}s", flush=True)


if __name__ == "__main__":
    main()
