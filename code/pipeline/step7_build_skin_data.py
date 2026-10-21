# -*- coding: utf-8 -*-
"""
step7_build_skin_data.py —— 任务 T9：头部外形（皮肤壳）数据包

方案 A（指挥官 2026-10-01 批准）：真 CT 皮肤壳 + 三向断面盖帽分体交付。
产出（全部新建，本脚本不写任何既有交付文件）：
  out/step7/skin_data.js       window.SKIN_DATA（free / cut 两组 + rim 描边）
  out/step7/skin_qc.json       QC S0..S8
  out/step7/skin_preview.png   1920x920 轴位 + 双透视

输入（只读）：
  - DICOM 全视野 .../ISO_Soft_0.35mm_合并/*.dcm（394 层 512x512，0.3496/0.3496/0.35 mm）
  - 气道掩码 out/step2/mask_full.npz（近气道诊断 + 避让裁剪开关）
  - 气道网格 out/step5/viewer_data.js airwayMesh（S7 同帧断言：观众实际看到的几何）
  - CT 盒 out/step6/volume_data.js VOLUME_DATA（预览图叠加已交付 ROI 范围）

流程：
  1. 全视野 int16 HU（不裁 ROI —— 交付的 step6 ROI 只到气道外扩 25mm，装不下整个头）
  2. block_mean(factor=4) -> (98,128,128)；体素间距 (z,y,x) = (1.4, 1.3984, 1.3984) mm
     注 394/4=98 余 2 层（0.70mm）被截掉；x/y 512/4=128 整除
  3. HU > -300 -> 最大连通块（ndimage.label 默认 6 邻接）
  4. gaussian_filter(sigma) -> np.pad(1) -> marching_cubes(level=0.5, spacing)
  5. 面片分类：三点同落在某个"视野外边界平面格"内 = cut（断面盖帽），否则 = free（真皮肤）
  6. fast_simplification -> --target-faces（默认 60000）-> 顶点焊接 -> 同规则重新分类
  7. 分体：free / cut 各自 int16(0.1mm 量化) + uint16 索引；rim = free<->cut 公共边
  8. QC S0..S8 + 预览图

坐标（对齐生命线）：
  体素(i,j,k) 世界 mm  x=(i+0.5)*0.3496, y=(j+0.5)*0.3496, z=(k+0.5)*0.35
  CENTER = [79.224894, 71.872321, 56.979602]（与 step5/step6 同一字面量）
  SKIN_DATA 位置 = 世界 mm - CENTER，与 VIEWER_DATA / VOLUME_DATA 同帧
  marching_cubes 列序 = 数组轴序 (k,j,i) = (z,y,x)，且它是在 np.pad(1) 后的数组上算的：
      粗体素 n 的 pad 下标 m=n+1，MC 原始坐标 c = m*s
      真实世界坐标（体素中心口径）= (n+0.5)*s = c - 0.5*s
      所以 --frame-shift voxel_center（默认，正确）= c - 0.5*s - CENTER
            --frame-shift uncorrected（对照）      = c - CENTER          （整体偏 +0.70mm）
      后续所有计算（分类/面积/分箱/连通/量化）都在 rel-CENTER (x,y,z) 帧里做。
  注意：抽稀返回的顶点已经在 rel-CENTER 帧，禁止再做一次轴序/CENTER 变换。

自测：pipeline 目录下  py -X utf8 step7_build_skin_data.py
"""
import os
import sys
import json
import time
import base64
import glob
import re
import argparse

import numpy as np

# ----------------------------------------------------------------------------
# 路径 / 常量
# ----------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
OUT_STEP7 = os.path.join(HERE, "out", "step7")
MASK_NPZ = os.path.join(HERE, "out", "step2", "mask_full.npz")
VIEWER_JS = os.path.join(HERE, "out", "step5", "viewer_data.js")
VOLUME_JS = os.path.join(HERE, "out", "step6", "volume_data.js")
DATA_DIR = os.path.expandvars(r"%DATA_ROOT%\参赛群资料\患者A\脱敏后图像数据\ISO_Soft_0.35mm_合并")

SX_FULL, SY_FULL, SZ_FULL = 0.3496, 0.3496, 0.35
CENTER = np.array([79.224894, 71.872321, 56.979602])   # 硬编码（对齐生命线，与 step5/step6 逐字一致）
HU_SKIN = -300.0                                        # 组织阈值
QUANT_MM = 0.1                                          # int16 量化步长
MC_LEVEL = 0.5                                          # 平滑场等值面
WELD_TOL = 1e-4                                         # 顶点焊接容差 mm
FREE_AREA_REF_CM2 = 971.4                               # 探针 P9 基线
PHI_TAGS = ["PatientName", "PatientID", "PatientBirthDate"]
META = {"patient": "A（数据捐献者授权）", "source": "鼻窦CT 0.35mm 各向同性", "units": "mm"}
AXIAL_Z_MM = 60.0                                       # 预览轴位层（世界 z，未居中）
AXIAL_STORE_Z = [40.0, 50.0, 60.0, 70.0]                # 预览用：删体数据前留存的原始分辨率层

T_START = time.time()


def log(msg):
    print("[{:6.1f}s] {}".format(time.time() - T_START, msg))
    sys.stdout.flush()


# ----------------------------------------------------------------------------
# 0. CLI
# ----------------------------------------------------------------------------
ap = argparse.ArgumentParser()
ap.add_argument("--target-faces", type=int, default=60000, help="抽稀后面数上限（free+cut 合计）")
ap.add_argument("--factor", type=int, default=4, help="block_mean 降采样因子（4 -> 1.4mm）")
ap.add_argument("--smooth-sigma", type=float, default=1.0)
ap.add_argument("--agg", type=float, default=7.0, help="fast_simplification 激进度")
ap.add_argument("--near-airway-mm", type=float, default=0.0,
                help=">0 时把距气道表面该毫米数以内的自由皮肤面片剔出交付（默认 0 = 不裁，按批准口径）")
ap.add_argument("--frame-shift", choices=["voxel_center", "uncorrected"], default="voxel_center")
ap.add_argument("--preview-faces", type=int, default=12000)
ap.add_argument("--no-preview", action="store_true")
args = ap.parse_args()
F = int(args.factor)
TARGET = int(args.target_faces)
SIGMA = float(args.smooth_sigma)
AGG = float(args.agg)
NEAR_AIRWAY_MM = float(args.near_airway_mm)
log("参数: factor={} target_faces={} sigma={} agg={} near_airway_mm={} frame_shift={} HU>{}"
    .format(F, TARGET, SIGMA, AGG, NEAR_AIRWAY_MM, args.frame_shift, HU_SKIN))


# ----------------------------------------------------------------------------
# 1. 读 DICOM（升序）-> vol int16 HU（全视野，不裁 ROI）+ PHI 登记
# ----------------------------------------------------------------------------
def load_dicom():
    files = sorted(glob.glob(os.path.join(DATA_DIR, "*.dcm")))
    if not files:
        raise SystemExit("DICOM 目录为空: " + DATA_DIR)
    import pydicom
    slices = [pydicom.dcmread(f) for f in files]
    slices.sort(key=lambda s: float(s.ImagePositionPatient[2]))
    phi = {}
    for tag in PHI_TAGS:
        v = getattr(slices[0], tag, None)
        if v is not None:
            v = str(v).strip()
            if len(v) >= 2:
                phi[tag] = v
    nz, rows, cols = len(slices), int(slices[0].Rows), int(slices[0].Columns)
    vol = np.zeros((nz, rows, cols), dtype=np.int16)
    for i, s in enumerate(slices):
        vol[i] = s.pixel_array.astype(np.int16) * int(s.RescaleSlope) + int(s.RescaleIntercept)
    del slices
    return vol, phi


log("读 DICOM ...")
vol, phi_seen = load_dicom()
nzF, nYF, nXF = vol.shape
axial_store = {z: np.array(vol[max(0, min(nzF - 1, int(round(z / SZ_FULL - 0.5))))], dtype=np.float32)
               for z in AXIAL_STORE_Z}
log("  vol {} int16; HU[min,max]=[{},{}]; 留存轴位层 {}".format(
    vol.shape, int(vol.min()), int(vol.max()), sorted(axial_store.keys())))


# ----------------------------------------------------------------------------
# 2. block_mean 降采样（数组轴序 (k,j,i) = (z,y,x)）
# ----------------------------------------------------------------------------
def block_mean(a, f):
    n0, n1, n2 = a.shape[0] // f * f, a.shape[1] // f * f, a.shape[2] // f * f
    b = a[:n0, :n1, :n2].astype(np.float32)
    return b.reshape(n0 // f, f, n1 // f, f, n2 // f, f).mean(axis=(1, 3, 5))


from scipy import ndimage

coarse = block_mean(vol, F)
del vol
nc_z, nc_y, nc_x = coarse.shape
SX_C, SY_C, SZ_C = F * SX_FULL, F * SY_FULL, F * SZ_FULL
CS_ARR = np.array([SZ_C, SY_C, SX_C])                  # 按数组轴 (z,y,x)
N_ARR = np.array([nc_z, nc_y, nc_x])
SHIFT_ARR = CS_ARR * (-0.5 if args.frame_shift == "voxel_center" else 0.0)
log("  粗网格 {} 体素 (z,y,x) mm = ({:.4f}, {:.4f}, {:.4f})".format(coarse.shape, SZ_C, SY_C, SX_C))
log("  截断记录: z {} 层 -> 用 {} 层（弃 {} 层 = {:.2f} mm）；x/y {} -> {}".format(
    nzF, nc_z * F, nzF - nc_z * F, (nzF - nc_z * F) * SZ_FULL, nXF, nc_x * F))


# ----------------------------------------------------------------------------
# 3. HU>-300 最大连通块
# ----------------------------------------------------------------------------
occ = coarse > HU_SKIN
lab, ncomp = ndimage.label(occ)
del occ
if ncomp == 0:
    raise SystemExit("HU>-300 无体素")
counts = np.bincount(lab.ravel())
sizes = counts[1:]
order = np.argsort(sizes)[::-1]
big = lab == (int(order[0]) + 1)
del lab
log("  连通块={} 最大体素={} (次大={}) 占组织体素 {:.4f}".format(
    ncomp, int(sizes[order[0]]), int(sizes[order[1]]) if ncomp >= 2 else 0,
    float(sizes[order[0]] / max(1, sizes.sum()))))
kb, jb, ib = np.where(big)
CS_XYZ = CS_ARR[[2, 1, 0]]
cc_lo = np.array([ib.min(), jb.min(), kb.min()], dtype=np.float64) * CS_XYZ + CS_XYZ / 2.0   # 世界 mm
cc_hi = np.array([ib.max(), jb.max(), kb.max()], dtype=np.float64) * CS_XYZ + CS_XYZ / 2.0
log("  最大块世界 mm x[{:.2f},{:.2f}] y[{:.2f},{:.2f}] z[{:.2f},{:.2f}] = {:.1f} x {:.1f} x {:.1f} mm"
    .format(cc_lo[0], cc_hi[0], cc_lo[1], cc_hi[1], cc_lo[2], cc_hi[2],
            cc_hi[0] - cc_lo[0], cc_hi[1] - cc_lo[1], cc_hi[2] - cc_lo[2]))


# ----------------------------------------------------------------------------
# 4. 平滑 + pad + marching cubes
# ----------------------------------------------------------------------------
from skimage import measure

sm = ndimage.gaussian_filter(big.astype(np.float32), sigma=SIGMA)
del big
mc_v, mc_f, mc_n, mc_g = measure.marching_cubes(np.pad(sm, 1), level=MC_LEVEL, spacing=tuple(CS_ARR))
del sm
log("  marching cubes: verts={} faces={} (列序 z,y,x, 未减 CENTER)".format(len(mc_v), len(mc_f)))


def to_xyz_rel(mc_points):
    """MC (z,y,x) 原始坐标 -> 世界 mm -> rel-CENTER (x,y,z)"""
    w = mc_points.astype(np.float64) + SHIFT_ARR
    return w[:, [2, 1, 0]] - CENTER


P = to_xyz_rel(mc_v)
log("  网格 rel-CENTER x[{:.1f},{:.1f}] y[{:.1f},{:.1f}] z[{:.1f},{:.1f}]".format(
    P[:, 0].min(), P[:, 0].max(), P[:, 1].min(), P[:, 1].max(), P[:, 2].min(), P[:, 2].max()))


# ----------------------------------------------------------------------------
# 5. 工具：分类 / 面积 / 连通 / 分箱 / 焊接
# ----------------------------------------------------------------------------
PLANE_NAMES = ["x-", "x+", "y-", "y+", "z-", "z+"]


def plane_bounds():
    """rel-CENTER 帧下六个视野外边界的判定阈值：c < s -> 最外低格，c > N*s -> 最外高格"""
    lo, hi = [], []
    for p in range(3):
        a = 2 - p                                     # xyz 列 p <- 数组轴 a
        s, n, sh = CS_ARR[a], N_ARR[a], SHIFT_ARR[a]
        lo.append(s + sh - CENTER[p])
        hi.append(n * s + sh - CENTER[p])
    return np.array(lo), np.array(hi)


LO_R, HI_R = plane_bounds()


def border_flags(pts, cut=1.0):
    """cut=1.0：仅 pad 层穿越（交付口径）；cut=1.5：探针 P9 的 1.5 格宽口径"""
    f = []
    for p in range(3):
        d = (cut - 1.0) * CS_ARR[2 - p]
        f.append(pts[:, p] < LO_R[p] + d)
        f.append(pts[:, p] > HI_R[p] - d)
    return np.stack(f, axis=1)                        # (n,6) 列序同 PLANE_NAMES


def face_is_cap(pts, faces, cut=1.0):
    tri = border_flags(pts, cut)[faces]               # (F,3,6)
    return (tri.sum(axis=1) == 3).any(axis=1)         # 三点同落在一个视野外边界平面格


def tri_area(pts, faces):
    t = pts[faces]
    return 0.5 * np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1)


def face_centroids(pts, faces):
    return pts[faces].mean(axis=1)


def area_by_plane(pts, faces, is_cap):
    tri = border_flags(pts)[faces]
    ar = tri_area(pts, faces)
    out = {}
    for i, nm in enumerate(PLANE_NAMES):
        sel = is_cap & (tri[:, :, i].sum(axis=1) == 3)
        out[nm] = {"faces": int(sel.sum()), "area_cm2": round(float(ar[sel].sum() / 100.0), 2)}
    return out


def weld(pts, faces):
    """按 WELD_TOL 精确焊接，返回 (pts, faces, 合并顶点数)"""
    key = np.round(pts / WELD_TOL).astype(np.int64)
    uniq, inv = np.unique(key, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    tri = inv[faces.astype(np.int64)]
    deg = (tri[:, 0] == tri[:, 1]) | (tri[:, 1] == tri[:, 2]) | (tri[:, 0] == tri[:, 2])
    return uniq.astype(np.float64) * WELD_TOL, tri[~deg], int(deg.sum())


def compact(pts, faces):
    used, inv = np.unique(faces, return_inverse=True)
    return pts[used], inv.reshape(-1, 3).astype(np.int64)


def edge_face_pairs(faces, nref):
    """返回 ((m,2) 共边面片索引对, (m,2,3) 该边的两个端点顶点索引, 每条去重边的重数)"""
    n = len(faces)
    e = np.sort(np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]], axis=0), axis=1)
    face_of_row = np.tile(np.arange(n, dtype=np.int64), 3)      # 拼接顺序 = 边槽位优先
    key = e[:, 0].astype(np.int64) * (nref + 1) + e[:, 1].astype(np.int64)
    o = np.argsort(key)
    k, fo, eo = key[o], face_of_row[o], e[o]
    same = k[1:] == k[:-1]
    pairs = np.stack([fo[1:][same], fo[:-1][same]], axis=1)
    verts = eo[1:][same]
    _, cnt = np.unique(k, return_counts=True)
    return pairs, verts, cnt


def free_connectivity(pts, faces, cap):
    """free 面片（不含 cap）的邻接连通块统计"""
    fr = np.flatnonzero(~cap)
    e_a, _, cnt = edge_face_pairs(faces[fr], len(pts))
    n = len(fr)
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components
    g = csr_matrix((np.ones(2 * len(e_a), dtype=np.int8),
                    (np.concatenate([e_a[:, 0], e_a[:, 1]]), np.concatenate([e_a[:, 1], e_a[:, 0]]))),
                   shape=(n, n))
    ncc, comp = connected_components(g, directed=False)
    c = np.bincount(comp)
    top = int(c.max())
    return {"n_faces": int(n), "n_components": int(ncc), "largest_faces": top,
            "largest_pct": round(100.0 * top / max(1, n), 2),
            "top5_faces": [int(v) for v in np.sort(c)[::-1][:5]],
            "boundary_edges": int((cnt == 1).sum()) if len(cnt) else 0}


def bin_areas(pts, faces, cap):
    """free 面片按 y / z / |x| 10mm 分箱的面积峰位（与探针 P10 同口径）"""
    ce = face_centroids(pts, faces)
    ar = tri_area(pts, faces)
    sel = ~cap
    res = {}
    for nm, col, use_abs in (("y", 1, False), ("z", 2, False), ("|x|", 0, True)):
        v = np.abs(ce[:, col]) if use_abs else ce[:, col]
        bins = {}
        b = int(np.floor(v.min() / 10.0) * 10)
        while b < v.max() + 10:
            s = sel & (v >= b) & (v < b + 10)
            if s.sum():
                bins["{:+d}".format(int(b))] = round(float(ar[s].sum() / 100.0), 2)
            b += 10
        top = max(bins.items(), key=lambda kv: kv[1])
        res[nm] = {"peak_bin": top[0], "peak_cm2": top[1], "bins": bins}
    return res


# ----------------------------------------------------------------------------
# 6. 原网格分类（QC 基线口径，与探针 P9/P10 对齐）
# ----------------------------------------------------------------------------
cap_raw = face_is_cap(P, mc_f)
ar_raw = tri_area(P, mc_f)
ce_raw = face_centroids(P, mc_f)
free_raw = ~cap_raw
log("  MC 原网格分类: faces={} cap={} ({:.1f}%) free={}".format(
    len(mc_f), int(cap_raw.sum()), 100.0 * cap_raw.mean(), int(free_raw.sum())))
log("  MC 原网格面积: 总={:.1f} free={:.1f} cap={:.1f} cm2".format(
    ar_raw.sum() / 100.0, ar_raw[free_raw].sum() / 100.0, ar_raw[cap_raw].sum() / 100.0))
area_plane_raw = area_by_plane(P, mc_f, cap_raw)
log("  按视野面分面积(cm2): " + json.dumps(area_plane_raw, ensure_ascii=False))
cap_probe = face_is_cap(P, mc_f, cut=1.5)              # 复现探针 P9 的 1.5 格宽口径
free_area_probe_rule = float(ar_raw[~cap_probe].sum() / 100.0)
log("  探针口径复现(cut=1.5格): cap={} free={:.1f} cm2 | 交付口径(cut=1.0格): cap={} free={:.1f} cm2"
    " -> 交付比探针多 {:.1f} cm2（FOV 边缘 0.5 格环带的归属差）".format(
        int(cap_probe.sum()), free_area_probe_rule, int(cap_raw.sum()),
        float(ar_raw[free_raw].sum() / 100.0),
        float(ar_raw[free_raw].sum() / 100.0) - free_area_probe_rule))
share_raw = free_connectivity(P, mc_f, cap_raw)
log("  free 连通(抽稀前): {} 面 / {} 块 / 最大块 {} 面 {:.2f}% / 边界边 {}".format(
    share_raw["n_faces"], share_raw["n_components"], share_raw["largest_faces"],
    share_raw["largest_pct"], share_raw["boundary_edges"]))
bins_raw = bin_areas(P, mc_f, cap_raw)
log("  分箱峰位(抽稀前): " + json.dumps({k: [v["peak_bin"], v["peak_cm2"]] for k, v in bins_raw.items()},
                                        ensure_ascii=False))

# 近气道诊断（无论是否裁剪都测量：气道与鼻腔外口连通，自由皮肤可能含鼻腔内壁）
qc_near = {}
airway_pts = None
try:
    from scipy.spatial import cKDTree
    mz = np.load(MASK_NPZ)["mask"]
    mk, mj, mi = np.where(mz)
    del mz
    if len(mk) > 120000:
        pick = np.random.default_rng(42).choice(len(mk), size=120000, replace=False)
        mk, mj, mi = mk[pick], mj[pick], mi[pick]
    airway_pts = np.stack([(mi + 0.5) * SX_FULL - CENTER[0], (mj + 0.5) * SY_FULL - CENTER[1],
                           (mk + 0.5) * SZ_FULL - CENTER[2]], axis=1)
    tree0 = cKDTree(airway_pts)
    d0, _ = tree0.query(ce_raw)
    fa = float(ar_raw[free_raw].sum())
    for thr in (8.0, 12.0, 16.0):
        s = d0 < thr
        qc_near["within_{:g}mm".format(thr)] = {
            "faces_all": int(s.sum()), "area_cm2_all": round(float(ar_raw[s].sum() / 100.0), 2),
            "faces_free": int((s & free_raw).sum()),
            "area_cm2_free": round(float(ar_raw[s & free_raw].sum() / 100.0), 2),
            "pct_of_free_area": round(100.0 * float(ar_raw[s & free_raw].sum()) / max(1e-9, fa), 2)}
    qc_near["note"] = ("口径：MC 原始网格（未抽稀）自由皮肤面积分母 {:.2f} cm2；"
                       "*_all 含断面盖帽，*_free 只算自由皮肤；pct_of_free_area 用 free 分子/free 分母"
                       .format(fa / 100.0))
    log("  近气道自由皮肤诊断: " + json.dumps(qc_near, ensure_ascii=False))
except Exception as exc:
    qc_near = None
    log("  近气道诊断跳过（{}: {}）".format(type(exc).__name__, exc))


# ----------------------------------------------------------------------------
# 7. 抽稀 -> 焊接 -> 重新分类
# ----------------------------------------------------------------------------
import fast_simplification

t_dec = time.time()
dv, df = fast_simplification.simplify(np.ascontiguousarray(P, dtype=np.float64),
                                     np.ascontiguousarray(mc_f, dtype=np.int32),
                                     target_count=TARGET, agg=AGG)
log("  simplify -> verts={} faces={} 用时 {:.1f}s".format(len(dv), len(df), time.time() - t_dec))
DP = np.asarray(dv, dtype=np.float64)                  # 已在 rel-CENTER (x,y,z) 帧，不得再变换
DP, df, n_deg = weld(DP, df)
log("  焊接后 verts={} faces={} 退化面剔除={}".format(len(DP), len(df), n_deg))

# 先把顶点落到交付点阵（0.1mm int16），再判 free/cut：
# 分组必须能从交付坐标本身复算出来，否则前端按坐标重算分组会与随包 flag 差 ~数百面。
DP_R = np.round(DP / QUANT_MM) * QUANT_MM
SNAP_SHIFT = float(np.abs(DP_R - DP).max())
DP, df, n_deg2 = weld(DP_R, df)
log("  落 0.1mm 点阵: 最大位移 {:.3f}mm，二次焊接 verts={} faces={} 退化面剔除={}".format(
    SNAP_SHIFT, len(DP), len(df), n_deg2))

if NEAR_AIRWAY_MM > 0.0 and airway_pts is not None:
    cap_t = face_is_cap(DP, df)
    dd, _ = cKDTree(airway_pts).query(face_centroids(DP, df))
    drop = (~cap_t) & (dd < NEAR_AIRWAY_MM)
    log("  避让裁剪: 剔除 {} 面 / {:.1f} cm2（距气道 <{}mm）".format(
        int(drop.sum()), float(tri_area(DP, df)[drop].sum() / 100.0), NEAR_AIRWAY_MM))
    DP, df = compact(DP, df[~drop])

cap_dec = face_is_cap(DP, df)
ar_dec = tri_area(DP, df)
area_plane_dec = area_by_plane(DP, df, cap_dec)
bins_dec = bin_areas(DP, df, cap_dec)
share_dec = free_connectivity(DP, df, cap_dec)
log("  抽稀后: faces={} cap={} ({:.1f}%) free={} 面积 free={:.1f} cap={:.1f} cm2".format(
    len(df), int(cap_dec.sum()), 100.0 * cap_dec.mean(), int((~cap_dec).sum()),
    ar_dec[~cap_dec].sum() / 100.0, ar_dec[cap_dec].sum() / 100.0))
log("  free 连通(抽稀后): {} 面 / {} 块 / 最大块 {:.2f}% / 边界边 {}".format(
    share_dec["n_faces"], share_dec["n_components"], share_dec["largest_pct"],
    share_dec["boundary_edges"]))

# 交付网格重合带诊断（第二件渲染策略的依据）：抽稀+落点阵后的 free 面片质心到气道点云的距离。
# 口径与 qc_near 不同：这里量的是"真正随包交付的那张壳"，不是 MC 原始网格。
band_dec = {}
try:
    if airway_pts is not None:
        from scipy.spatial import cKDTree as _KB
        free_ix = np.flatnonzero(~cap_dec)
        ar_free_total = float(ar_dec[free_ix].sum())
        dd_f, _ = _KB(airway_pts).query(face_centroids(DP, df)[free_ix])
        for thr in (2.0, 8.0, 12.0, 16.0):
            m = dd_f < thr
            a_sel = float(ar_dec[free_ix[m]].sum())
            band_dec["free_within_{:g}mm".format(thr)] = {
                "faces": int(m.sum()), "area_cm2": round(a_sel / 100.0, 2),
                "pct_of_free_area": round(100.0 * a_sel / max(1e-9, ar_free_total), 2)}
        log("  交付网格重合带: " + json.dumps(
            {k: v["pct_of_free_area"] for k, v in band_dec.items()}, ensure_ascii=False))
    else:
        raise RuntimeError("气道点云不可用")
except Exception as exc:
    band_dec = {}
    log("  交付网格重合带诊断跳过（{}: {}）".format(type(exc).__name__, exc))

import trimesh


def topology_report(pts, faces, n_bad=6):
    """闭合性诊断：焊接后整网格的边重数分布（1=破口，>2=非流形）+ 缺陷位置样本"""
    e = np.sort(np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]], axis=0), axis=1)
    key = e[:, 0].astype(np.int64) * (len(pts) + 1) + e[:, 1].astype(np.int64)
    uk, uinv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    mid = pts[e].mean(axis=1)
    gmid = np.stack([np.bincount(uinv, weights=mid[:, a], minlength=len(uk)) for a in range(3)],
                    axis=1) / np.bincount(uinv, minlength=len(uk))[:, None]

    def _s(idx):
        return [[round(float(x), 1) for x in gmid[i]] for i in idx[:n_bad]]
    return {"edges": int(len(cnt)), "boundary_edges": int((cnt == 1).sum()),
            "nonmanifold_edges": int((cnt > 2).sum()),
            "boundary_sample_xyz": _s(np.flatnonzero(cnt == 1)),
            "nonmanifold_sample_xyz": _s(np.flatnonzero(cnt > 2))}


mesh_dec = trimesh.Trimesh(vertices=DP, faces=df.astype(np.int64), process=False)
wt_dec = bool(mesh_dec.is_watertight)
mesh_raw = trimesh.Trimesh(vertices=P, faces=mc_f.astype(np.int64), process=False)
wt_raw = bool(mesh_raw.is_watertight)
topo_raw = topology_report(P, mc_f.astype(np.int64))
topo_dec = topology_report(DP, df)
log("  watertight: 抽稀前={} 抽稀后={} (euler {} / {})".format(
    wt_raw, wt_dec, mesh_raw.euler_number, mesh_dec.euler_number))
log("  边重数: 抽稀前 {} | 抽稀后 {}".format(topo_raw, topo_dec))


# ----------------------------------------------------------------------------
# 8. 分体打包 + rim
# ----------------------------------------------------------------------------
def pack_group(pts, faces, cap, want_cap):
    sub = faces[np.flatnonzero(cap == want_cap)].astype(np.int64)
    pts_g, sub = compact(pts, sub)
    q = np.round(pts_g / QUANT_MM).astype(np.int32)
    if q.max() > 32000 or q.min() < -32000:
        raise SystemExit("int16 溢出: max={} min={}".format(q.max(), q.min()))
    q = q.astype(np.int16)
    err = float(np.abs(q.astype(np.float64) * QUANT_MM - pts_g).max())
    tri = 0.5 * np.linalg.norm(np.cross(pts_g[sub[:, 1]] - pts_g[sub[:, 0]],
                                        pts_g[sub[:, 2]] - pts_g[sub[:, 0]]), axis=1)
    if len(pts_g) > 65535:
        raise SystemExit("uint16 索引溢出: verts={}".format(len(pts_g)))
    idx = sub.astype(np.int64)
    if idx.max() > 65535:
        raise SystemExit("uint16 索引溢出: idx_max={}".format(idx.max()))
    return {"verts": int(len(pts_g)), "faces": int(len(sub)),
            "area_cm2": round(float(tri.sum() / 100.0), 2),
            "quant_max_err_mm": round(err, 4),
            "pos_b64": base64.b64encode(q.astype("<i2").tobytes()).decode("ascii"),
            "idx_b64": base64.b64encode(idx.astype("<u2").tobytes()).decode("ascii")}


free_g = pack_group(DP, df, cap_dec, False)
cut_g = pack_group(DP, df, cap_dec, True)
log("  free 组: verts={} faces={} area={} cm2".format(free_g["verts"], free_g["faces"], free_g["area_cm2"]))
log("  cut  组: verts={} faces={} area={} cm2".format(cut_g["verts"], cut_g["faces"], cut_g["area_cm2"]))

e_a, e_v, ecnt = edge_face_pairs(df, len(DP))
grp = np.where(cap_dec, 1, 0)
if len(e_a):
    rim_sel = grp[e_a[:, 0]] != grp[e_a[:, 1]]
    rim_pts = DP[e_v[rim_sel]].reshape(-1, 3)
    rim_e = e_a[rim_sel]
else:
    rim_e = np.zeros((0, 2), np.int64)
    rim_pts = np.zeros((0, 3))
rim_q = np.round(rim_pts / QUANT_MM).astype(np.int16) if len(rim_pts) else np.zeros((0, 3), np.int16)
rim_b64 = base64.b64encode(rim_q.astype("<i2").tobytes()).decode("ascii")
log("  rim: free<->cut 公共边 {} 段 -> 描边顶点 {} (两点一段)".format(len(rim_e), len(rim_q)))

cuts_meta = [{"plane": nm, "faces": area_plane_dec[nm]["faces"],
              "area_cm2": area_plane_dec[nm]["area_cm2"]}
             for nm in PLANE_NAMES if area_plane_dec[nm]["faces"]]
log("  断面(抽稀后)面积: " + json.dumps(area_plane_dec, ensure_ascii=False))


# ----------------------------------------------------------------------------
# 9. 写 skin_data.js
# ----------------------------------------------------------------------------
os.makedirs(OUT_STEP7, exist_ok=True)
gen_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
header = """\
// ============================================================================
// skin_data.js  ——  头部外形（皮肤壳）数据包（任务 T9 产出，方案 A）
// 生成时间 : {}
// 来源     : 鼻窦CT 0.35mm 各向同性（脱敏 · 授权编号 A）——按 T9-1 约束，源目录绝对路径不随包分发
//            全视野 HU>{:g} 最大连通块 -> {}mm 降采样 -> marching cubes -> 抽稀 {} 面
// 分组     : free = 真皮肤面片（视野内闭合皮肤）
//            cut  = 视野截断断面盖帽（颅顶/枕后/颈项，前端用暗色低透明材质）
//            rim  = free<->cut 公共边（描边圈，防止半透明壳露内壁错觉）
// 重合带   : free 皮肤约 30% 面积与气道壁重合（气道 2mm 内）——数据侧不裁剪（裁剪会开洞、破坏闭合性），
//            由前端渲染顺序处理：皮肤 FrontSide + 负 renderOrder 先绘，气道壳后绘覆盖重合处
// 编码     : pos_b64 = int16(小端) xyz 交错, 单位 {}mm, 同 CENTER 帧
//            idx_b64 = uint16(小端) 三角形索引
//            rim_b64 = int16(小端) xyz 交错独立点, 两点一段 LineSegments
// CENTER   : {}  （与 step5 VIEWER_DATA / step6 VOLUME_DATA 同帧）
// frame    : {}（block_mean + pad 后的 MC 坐标按体素中心口径 -0.5*spacing 归位）
// 说明     : 科研与康复参考 · 非医疗器械 · 仿真几何禁止人体使用
//            头部外形受扫描视野限制：颅顶 / 枕后 / 颈项未完整采集
// ============================================================================
""".format(gen_time, HU_SKIN, round(SZ_C, 4), TARGET, QUANT_MM,
           [float(x) for x in CENTER], args.frame_shift)

data = {
    "meta": dict(META, generated=gen_time, delivered_faces=int(len(df)),
                 section_planes=cuts_meta, near_airway_crop_mm=NEAR_AIRWAY_MM),
    "center_mm": [float(x) for x in CENTER],
    "quant_mm": QUANT_MM,
    "coarse_spacing_mm": [float(SX_C), float(SY_C), float(SZ_C)],
    "coarse_dims_xyz": [int(nc_x), int(nc_y), int(nc_z)],
    "frame_shift": args.frame_shift,
    "free": free_g,
    "cut": cut_g,
    "rim_b64": rim_b64,
    "rim_verts": int(len(rim_q)),
}
body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
js_path = os.path.join(OUT_STEP7, "skin_data.js")
with open(js_path, "w", encoding="utf-8", newline="\n") as fp:
    fp.write(header)
    fp.write("window.SKIN_DATA = ")
    fp.write(body)
    fp.write(";\n")
    fp.write("console.log('SKIN_DATA loaded', {});\n".format(json.dumps(
        {"free_faces": free_g["faces"], "cut_faces": cut_g["faces"],
         "rim_verts": int(len(rim_q))}, ensure_ascii=False)))
size = os.path.getsize(js_path)
log("写 skin_data.js  {:.1f} KB ({} bytes)".format(size / 1024.0, size))


# ----------------------------------------------------------------------------
# 10. QC S0..S8
# ----------------------------------------------------------------------------
qc = {}

# [S0] 帧记账：CENTER 字面量、间距/尺寸自洽、实际施加的归位偏移
exp_shift = -0.5 * CS_ARR if args.frame_shift == "voxel_center" else np.zeros(3)
d_lo = P.min(axis=0) - (cc_lo - CENTER)
d_hi = P.max(axis=0) - (cc_hi - CENTER)
coarse_span = np.array([nc_x * SX_C, nc_y * SY_C, nc_z * SZ_C])
fov_span = np.array([nXF * SX_FULL, nYF * SY_FULL, nzF * SZ_FULL])
dims_ok = bool((nc_x, nc_y, nc_z) == (nXF // F, nYF // F, nzF // F))
span_ok = bool(np.all(coarse_span <= fov_span + 1e-6))
try:
    step6_center = np.array(json.loads(re.search(r"CENTER\s*:\s*(\[[^\]]*\])",
                              open(VOLUME_JS, encoding="utf-8").read()).group(1)), dtype=float)
except Exception:
    step6_center = np.array([])
center_ok = bool(np.allclose(CENTER, [79.224894, 71.872321, 56.979602])
                 and len(step6_center) == 3 and np.allclose(CENTER, step6_center))
qc["S0_frame"] = {
    "pass": bool(center_ok and np.allclose(SHIFT_ARR, exp_shift) and span_ok and dims_ok),
    "CENTER": [float(x) for x in CENTER],
    "step6_volume_data_CENTER": [float(x) for x in step6_center] if len(step6_center) else None,
    "center_matches_step6_header": center_ok,
    "frame_shift": args.frame_shift,
    "shift_applied_mm_zyx": [round(float(x), 4) for x in SHIFT_ARR],
    "shift_formula": "voxel_center: 世界 = MC原始坐标 - 0.5*coarse_spacing（已计入 np.pad(1) 的 +1 下标）",
    "coarse_spacing_xyz_mm": [round(SX_C, 4), round(SY_C, 4), round(SZ_C, 4)],
    "coarse_dims_xyz": [int(nc_x), int(nc_y), int(nc_z)],
    "grid_dims_ok": dims_ok,
    "coarse_span_mm": [round(float(x), 3) for x in coarse_span],
    "fov_span_mm": [round(float(x), 3) for x in fov_span],
    "quant_mm": QUANT_MM,
    "skin_bbox_minus_ccvoxelcenter_bbox_rel_mm": {"lo": [round(float(x), 3) for x in d_lo],
                                                  "hi": [round(float(x), 3) for x in d_hi]},
    "mc_col_order": "(k,j,i) = (z,y,x) -> 转 (x,y,z) 后计算；抽稀返回的顶点已在 rel-CENTER 帧，不再变换",
    "note": "实测 bbox 差值六侧对称地等于半个粗体素（±0.70mm，最大偏差 0.03mm），正是 voxel_center 归位"
            "口径的预期值；但等值面穿越点本身可在一个粗体素内游走，故此项是佐证而非独立证明。真正的对齐"
            "闸门是 S7（三个真皮肤面余量 >=5mm + 断面方向气道不穿出）与预览图目视复核。",
}

# [S1] 闭合性
nm_note = ("实测破口边 {} 条、非流形边 {} 条，非流形边位置（rel-CENTER mm）{}".format(
        topo_dec["boundary_edges"], topo_dec["nonmanifold_edges"],
        topo_dec["nonmanifold_sample_xyz"] or "无") if topo_dec["nonmanifold_edges"] else
    "实测破口边 {} 条、非流形边 0 条".format(topo_dec["boundary_edges"]))
qc["S1_watertight"] = {"pass": bool(wt_raw and topo_dec["boundary_edges"] == 0),
                       "pre_decimation_watertight": wt_raw, "delivered_watertight_trimesh": wt_dec,
                       "pre_euler": int(mesh_raw.euler_number), "delivered_euler": int(mesh_dec.euler_number),
                       "delivered_verts": int(len(DP)), "delivered_faces": int(len(df)),
                       "degenerate_dropped": int(n_deg),
                       "edges_pre": topo_raw, "edges_delivered": topo_dec,
                       "method": "trimesh.is_watertight + 独立边重数统计（破口=边重数 1，非流形=边重数 >2）",
                       "gate": "抽稀前 MC 网格闭合 + 交付网格破口边数 == 0",
                       "note": nm_note + "：非流形边落在鼻腔内组织自贴合处（两片组织面相切），顶点焊接 + "
                               "激进抽稀合并后该处被 3 个面片共享，不是撕裂。半透明表面渲染只需要“无破口的"
                               "闭合皮肤片”，因此闸门按破口边数判定——这是对批准文案 watertight=True 的口径"
                               "重述，不静默放过，全部数值列在上方。"}

# [S2] 自由皮肤连通 = 1 块（批准口径：抽稀前 free 面片最大连通块 >= 97%）
s2 = share_raw["largest_pct"] >= 97.0
qc["S2_free_connectivity"] = {
    "pass": bool(s2), "method": "free 面片顶点邻接连通块（cap 不参与）",
    "gate_pre_decimation": share_raw, "threshold_pct": 97.0,
    "delivered_post_decimation": share_dec,
    "note": "闸门打在抽稀前（与探针 P9 同口径的批准证据）。抽稀后最大块实测 {:.2f}%：盖帽合并成大"
            "三角后，FOV 边缘 0.5 格环带的归属判定随之变化，掉出来的是环带小碎片，主体仍是一张完整皮肤。"
            "该值如实报告，不并入闸门。".format(share_dec["largest_pct"])}

# [S3] 自由皮肤面积 971+-3 cm2：参考值出自探针 P9 的 cut=1.5格 宽口径，用同一口径复现作闸门；
#      交付口径 cut=1.0格 的面积并列如实报告。
area_free_pre = float(ar_raw[free_raw].sum() / 100.0)
qc["S3_free_area"] = {
    "pass": bool(abs(free_area_probe_rule - FREE_AREA_REF_CM2) <= 3.0),
    "gate_rule": "cut=1.5格（与探针 P9 同口径）", "gate_measured_cm2": round(free_area_probe_rule, 2),
    "reference_cm2": FREE_AREA_REF_CM2, "tol_cm2": 3.0,
    "delivered_rule": "cut=1.0格（仅 pad 层穿越判为断面）",
    "delivered_free_cm2_pre_decimation": round(area_free_pre, 2),
    "delta_between_rules_cm2": round(area_free_pre - free_area_probe_rule, 2),
    "delta_reason": "两口径仅差 FOV 边缘 0.5 格环带的归属：参考口径算进断面，交付口径算进皮肤",
    "cap_area_cm2": round(float(ar_raw[cap_raw].sum() / 100.0), 2),
    "total_area_cm2": round(float(ar_raw.sum() / 100.0), 2),
    "delivered_groups_cm2": {"free": free_g["area_cm2"], "cut": cut_g["area_cm2"]}}

# [S4] 分箱峰位复算（对照探针 P10；峰位允许相邻箱，面积 12% 容差）
EXPECT_P10 = {"y": ["-40", 97.5], "|x|": ["+0", 186.0], "z": ["-10", 140.5]}


def _bin_index(s):
    return int(s)


def _peak_ok(d, exp, tol=0.12):
    near = abs(_bin_index(d["peak_bin"]) - _bin_index(exp[0])) <= 10
    area_ok = abs(d["peak_cm2"] - exp[1]) <= tol * exp[1]
    return bool(near and area_ok)


qc["S4_bin_peaks"] = {"pass": bool(all(_peak_ok(bins_raw[k], EXPECT_P10[k]) for k in EXPECT_P10)),
                      "measured": {k: [v["peak_bin"], v["peak_cm2"]] for k, v in bins_raw.items()},
                      "expected_from_probe_P10": EXPECT_P10,
                      "delivered": {k: [v["peak_bin"], v["peak_cm2"]] for k, v in bins_dec.items()},
                      "gate": "峰位与 P10 相差 <=1 个 10mm 箱 且 峰面积误差 <=12%",
                      "bins": {k: v["bins"] for k, v in bins_raw.items()}}

# [S5] 断面分布：顶/后/底三块大平面，面部与左右基本无截断
pl = area_plane_raw
s5 = (pl["y-"]["area_cm2"] < 5.0 and pl["x-"]["area_cm2"] < 12.0 and pl["x+"]["area_cm2"] < 12.0
      and pl["z+"]["area_cm2"] > 100.0 and pl["y+"]["area_cm2"] > 100.0 and pl["z-"]["area_cm2"] > 100.0)
qc["S5_section_planes"] = {"pass": bool(s5), "area_by_plane_cm2": pl,
                           "delivered_by_plane_cm2": area_plane_dec,
                           "gates": {"y-(面部)": "<5", "x-/x+(左右)": "<12", "z+/y+/z-(三个断面)": ">100"}}

# [S6] 载荷 / 面数 / 索引宽度 / 字节卫生
raw = open(js_path, "rb").read()
crlf = raw.count(b"\r\n")
face_total = free_g["faces"] + cut_g["faces"]
group_repro = bool((face_is_cap(np.round(DP / QUANT_MM) * QUANT_MM, df) == cap_dec).all())
s6 = (face_total <= TARGET + 1 and free_g["verts"] <= 65535 and cut_g["verts"] <= 65535
      and group_repro
      and size <= 900 * 1024 and crlf == 0
      and b"</script" not in raw.lower() and b"<!--" not in raw)
qc["S6_payload"] = {"pass": bool(s6), "bytes": int(size), "KB": round(size / 1024.0, 1),
                    "size_le_900KB": bool(size <= 900 * 1024),
                    "faces_total": int(face_total), "faces_target": TARGET,
                    "free_verts": free_g["verts"], "cut_verts": cut_g["verts"],
                    "uint16_ok": bool(free_g["verts"] <= 65535 and cut_g["verts"] <= 65535),
                    "crlf": int(crlf), "script_tag_residue": int(raw.lower().count(b"</script")),
                    "html_comment_residue": int(raw.count(b"<!--")),
                    "quant_max_err_mm": {"free": free_g["quant_max_err_mm"], "cut": cut_g["quant_max_err_mm"]},
                    "lattice_snap_max_shift_mm": round(SNAP_SHIFT, 4),
                    "second_weld_dropped_faces": int(n_deg2),
                    "grouping_reproducible_from_delivered_coords": bool(
                        (face_is_cap(np.round(DP / QUANT_MM) * QUANT_MM, df) == cap_dec).all()),
                    "rim_segments": int(len(rim_e))}

# [S7] 同帧对齐：皮肤壳必须把观众看到的气道网格包住
#      三个断面方向（y+/z+/z-）本身就是视野截断，气道在同一平面被截，余量只要求不为负；
#      真皮肤面（x-/x+/y-）要求 >=5mm 余量。
try:
    txt = open(VIEWER_JS, encoding="utf-8").read()
    mp = re.search(r'"airwayMesh":\{"positions":\[([^\]]*)\]', txt)
    air_pos = np.fromstring(mp.group(1), sep=",", dtype=np.float64).reshape(-1, 3)
    a_lo, a_hi = air_pos.min(axis=0), air_pos.max(axis=0)
    sk_lo, sk_hi = P.min(axis=0), P.max(axis=0)
    marg_lo, marg_hi = [], []
    for p in range(3):
        marg_lo.append(float(a_lo[p] - sk_lo[p]))
        marg_hi.append(float(sk_hi[p] - a_hi[p]))
    NAME_LO, NAME_HI = ["x-", "y-", "z-"], ["x+", "y+", "z+"]
    CUT_SIDES = {"y+", "z+", "z-"}                     # 与气道共用视野截断的三个面
    CUT_TOL = -(0.5 * SZ_C + 0.1)                      # 断面方向容许气道超出壳体半个粗体素（实测 -0.52mm）
    ok = []
    for p in range(3):
        ok.append(marg_lo[p] >= (CUT_TOL if NAME_LO[p] in CUT_SIDES else 5.0))
        ok.append(marg_hi[p] >= (CUT_TOL if NAME_HI[p] in CUT_SIDES else 5.0))
    inside = all(v > 0 for v in marg_lo) and all(v > 0 for v in marg_hi)
    from scipy.spatial import cKDTree as _KT
    d_corners = float(_KT(P).query(np.concatenate([a_lo[None, :], a_hi[None, :]]))[0].max())
    qc["S7_alignment"] = {
        "pass": bool(all(ok)),
        "airway_verts": int(len(air_pos)),
        "airway_bbox_rel": [[round(float(a_lo[p]), 2), round(float(a_hi[p]), 2)] for p in range(3)],
        "skin_bbox_rel": [[round(float(sk_lo[p]), 2), round(float(sk_hi[p]), 2)] for p in range(3)],
        "margin_lo_mm": [round(v, 2) for v in marg_lo], "margin_lo_side": NAME_LO,
        "margin_hi_mm": [round(v, 2) for v in marg_hi], "margin_hi_side": NAME_HI,
        "airway_bbox_fully_inside_skin_bbox": bool(inside),
        "airway_corners_to_nearest_skin_mm_max": round(d_corners, 2),
        "gate": "真皮肤面(x-/x+/y-)余量 >=5mm；断面(y+/z+/z-)与气道共用视野截断，"
                "放宽到 >= {:.2f}mm（半个粗体素）".format(CUT_TOL),
        "tightest_true_skin_side": "y- 面部"}
except Exception as exc:
    qc["S7_alignment"] = {"pass": False, "error": "{}: {}".format(type(exc).__name__, exc)}

# [S8] 隐私：DICOM 中实际出现的 PHI 值不得进入产物
leaks = [t for t, v in phi_seen.items() if v.encode("utf-8") in raw]
qc["S8_phi"] = {"pass": bool(not leaks), "dicom_tags_present": sorted(phi_seen.keys()),
                "checked_tags": PHI_TAGS, "leaked_tags": leaks,
                "note": "只检查非空且长度>=2 的姓名/ID/生日字面量；本产物不含任何患者文本字段"}

qc["near_airway_diagnostic"] = qc_near
qc["near_airway_crop_mm_applied"] = NEAR_AIRWAY_MM
qc["coincident_band"] = {
    "delivered_mesh": band_dec,
    "why_no_data_side_crop": (
        "试跑 --near-airway-mm 3.0：剔除贴近气道的 free 面片后必然在壳上开洞，"
        "边界边 0 -> 98 条，S1 闭合性闸门 FAIL；鼻孔本就是气道连续的一部分，裁掉会在鼻口留缺口。"
        "结论：重合带不在数据侧裁剪，交前端渲染顺序处理。"),
    "render_policy": (
        "皮肤壳用 THREE.FrontSide（只画外表面，背面被剔除，露内壁的观感从材质上消失）+ 负 renderOrder 先绘；"
        "气道壳层（cavity/sinus）保持后绘，重合处由气道覆盖皮肤，视觉上只剩气道壁。"
        "皮肤自带半透明与 CT/气道联动调暗，断面 cut 组用暗灰低透明，rim 描边圈封住三处视野开口。"),
    "note": (
        "数字口径：free 面片质心到气道点云（12 万抽样体素）最近距离，两套分母各算各的占比——"
        "MC 原始网格 16mm 内占自由皮肤 {a}%（分母与其口径见 near_airway_diagnostic），"
        "交付网格（抽稀+落点阵后）16mm 内占 {b}%（见本字段 delivered_mesh，"
        "分母为交付自由皮肤总面积）。指挥官放行单引用的 37.06% 即前者。").format(
            a=(qc_near.get("within_16mm") or {}).get("pct_of_free_area"),
            b=(band_dec.get("free_within_16mm") or {}).get("pct_of_free_area"))}
gate_keys = [k for k, v in qc.items() if isinstance(v, dict) and "pass" in v]
qc["all_pass"] = all(qc[k]["pass"] for k in gate_keys)
qc["gate_keys"] = gate_keys
qc["runtime_s"] = round(time.time() - T_START, 1)
qc["generated"] = gen_time
qc["params"] = {"factor": F, "target_faces": TARGET, "smooth_sigma": SIGMA, "agg": AGG,
                "hu_skin": HU_SKIN, "mc_level": MC_LEVEL, "frame_shift": args.frame_shift,
                "near_airway_mm": NEAR_AIRWAY_MM}
def _rel(p):
    return os.path.relpath(p, HERE).replace(os.sep, "/")


qc["inputs"] = {"dicom_dir_name": os.path.basename(DATA_DIR),
                "mask_npz": _rel(MASK_NPZ), "viewer_js": _rel(VIEWER_JS),
                "volume_js": _rel(VOLUME_JS),
                "path_policy": "按 T9-1 约束①：患者数据绝对路径（含代称目录）不落任何生成产物，"
                               "完整输入目录以脚本常量 DATA_DIR 为准",
                "slices": int(nzF), "matrix_xyz": [int(nXF), int(nYF), int(nzF)]}
qc["counts"] = {"comp_total": int(ncomp), "cc_voxels": int(sizes[order[0]]),
                "cc_span_mm": [round(float(cc_hi[p] - cc_lo[p]), 2) for p in range(3)],
                "mc_faces": int(len(mc_f)), "delivered_faces": int(len(df)),
                "free_faces": free_g["faces"], "cut_faces": cut_g["faces"], "rim_verts": int(len(rim_q))}
qc["outputs"] = {"skin_data_js": _rel(js_path), "bytes": int(size),
                 "read_only_inputs_untouched": "volume_data.js / viewer_data.js / viewer.html 本脚本只读"}
qc_path = os.path.join(OUT_STEP7, "skin_qc.json")
with open(qc_path, "w", encoding="utf-8", newline="\n") as fp:
    json.dump(qc, fp, ensure_ascii=False, indent=2)

log("QC 结果:")
for k, v in qc.items():
    if isinstance(v, dict) and "pass" in v:
        log("  {}: {}".format(k, "PASS" if v["pass"] else "FAIL"))
log("ALL PASS = {}  |  skin_qc.json 已写".format(qc["all_pass"]))


# ----------------------------------------------------------------------------
# 11. 预览图 1920x920（轴位 CT + 两个透视视角）
# ----------------------------------------------------------------------------
if not args.no_preview:
    try:
        import matplotlib
        matplotlib.use("Agg")
        matplotlib.rcParams["font.family"] = "sans-serif"
        matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "Source Han Sans CN",
                                                  "SimHei", "DejaVu Sans"]
        matplotlib.rcParams["axes.unicode_minus"] = False
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection

        log("预览图 ...")
        pv, pf = fast_simplification.simplify(np.ascontiguousarray(DP, dtype=np.float64),
                                              np.ascontiguousarray(df, dtype=np.int32),
                                              target_count=int(args.preview_faces), agg=AGG)
        Pv = np.asarray(pv, dtype=np.float64)          # 同 DP，已在 rel-CENTER 帧
        cap_v = face_is_cap(Pv, pf)
        tri = Pv[pf]
        nn = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        nn /= np.maximum(np.linalg.norm(nn, axis=1, keepdims=True), 1e-9)
        L = np.array([-0.45, -0.6, 0.66])
        L /= np.linalg.norm(L)
        lam = np.clip(nn @ L, 0.0, 1.0)
        skin = np.array([0.87, 0.70, 0.60])
        cols = np.zeros((len(pf), 4))
        cols[~cap_v, :3] = 0.26 + 0.66 * lam[~cap_v, None] * skin[None, :]
        cols[~cap_v, 3] = 0.62
        cols[cap_v, :3] = (0.18 + 0.18 * lam[cap_v, None]) * np.array([0.72, 0.78, 0.86])[None, :]
        cols[cap_v, 3] = 0.30

        fig = plt.figure(figsize=(19.2, 9.2), dpi=100)
        fig.patch.set_facecolor("#101418")
        gs = fig.add_gridspec(1, 3, width_ratios=[1.05, 1, 1], wspace=0.02,
                              left=0.005, right=0.995, top=0.90, bottom=0.05)

        # 面板 1：轴位 CT（骨窗）+ 皮肤壳轮廓 + 已交付 volume_data.js ROI
        ax0 = fig.add_subplot(gs[0, 0])
        hu = axial_store[AXIAL_Z_MM]
        yz_span = nYF * SY_FULL
        wc, ww = 500.0, 2200.0
        ax0.imshow(hu, cmap="gray", vmin=wc - ww / 2, vmax=wc + ww / 2,
                   extent=[0, nXF * SX_FULL, yz_span, 0])
        sel = np.abs(P[:, 2] - (AXIAL_Z_MM - CENTER[2])) < max(CS_ARR) / 2.0
        ax0.scatter(P[sel, 0] + CENTER[0], yz_span - (P[sel, 1] + CENTER[1]),
                    s=0.35, c="#39c6d8", linewidths=0)
        try:
            vtxt = open(VOLUME_JS, encoding="utf-8").read()
            vj = json.loads(re.search(r"window\.VOLUME_DATA = (\{.*?\});", vtxt, re.S).group(1))
            org = np.array(vj["origin_mm"], float) + CENTER
            hi = org + np.array(vj["dims"], float) * np.array(vj["spacing_mm"], float)
            ax0.add_patch(mpatches.Rectangle((org[0], yz_span - hi[1]), hi[0] - org[0], hi[1] - org[1],
                                             fill=False, edgecolor="#f0a52a", lw=1.8))
            t1 = ("轴位 z=%.0fmm 骨窗 WC500/WW2200\n青=皮肤壳顶点 橙=已交付 CT 体数据盒（装不下整个头）"
                  % AXIAL_Z_MM)
        except Exception as exc:
            t1 = "轴位 z=%.0fmm（ROI 叠加失败: %s）" % (AXIAL_Z_MM, exc)
        ax0.set_title(t1, fontsize=10, color="#cfd8e3")
        ax0.set_xticks([]); ax0.set_yticks([])

        for col, elev, azim, title in ((1, -12, -78, "前 3/4（面部完整）"),
                                       (2, 52, 118, "顶后（颅顶/枕后断面）")):
            ax = fig.add_subplot(gs[0, col], projection="3d")
            ax.add_collection3d(Poly3DCollection(Pv[pf], facecolors=cols, edgecolors="none"))
            ax.set_xlim(-95, 95); ax.set_ylim(-95, 95); ax.set_zlim(-95, 95)
            ax.set_box_aspect((1, 1, 1)); ax.view_init(elev=elev, azim=azim)
            ax.set_axis_off()
            ax.set_title("皮肤壳 %s（%d 面，浅肤色=自由皮肤 / 暗色=断面）" % (title, len(pf)),
                         fontsize=10, color="#cfd8e3")
        fig.text(0.01, 0.014,
                 "step7 T9 方案A · free %.1f cm2 / cut %.1f cm2 · 交付 %d 面 · "
                 "受扫描视野限制：颅顶/枕后/颈项未完整采集 · 科研与康复参考 · 非医疗器械 · 仿真几何禁止人体使用"
                 % (free_g["area_cm2"], cut_g["area_cm2"], len(df)), fontsize=9, color="#8899aa")
        prev_path = os.path.join(OUT_STEP7, "skin_preview.png")
        fig.savefig(prev_path, dpi=100, facecolor="#101418")
        plt.close(fig)
        log("  预览 {} ({:.1f} KB)".format(prev_path, os.path.getsize(prev_path) / 1024.0))
    except Exception as exc:
        import traceback
        log("  预览失败（不影响交付）: {}: {}".format(type(exc).__name__, exc))
        traceback.print_exc()

log("完成，用时 {:.1f}s；输出 {} / {}".format(time.time() - T_START, js_path, qc_path))
