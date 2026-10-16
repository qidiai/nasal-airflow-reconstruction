# -*- coding: utf-8 -*-
r"""
make_flowlines_standalone.py —— 独立流线生成工具（step5 RK2 积分器提取复刻版）

背景（2026-10-16 P0 流线根源修复）：
  pA 的完整流线（63 条 / 平均 147 点 / 全通道覆盖）由 step5_export_viewer_data.py
  内部的自研 RK2 弧长积分器生成；pB/pN/pN2 曾用现场积分（pyvista/FOAM
  streamLine）→ 种子落位差 / 死区早停 → 只有半截（实测旧 pB 流线仅占气道
  bbox 的 45.7×22.3×4.0mm 一团，且缩在咽端）。
  本工具**复制** step5 的流线全链逻辑（不 import 那个千行脚本，避免连带依赖），
  输入 VTU + mask npz + 气道 GLB，输出与 pA 同构的 flowlines JSON
  （坐标已烘烤进 GLB 帧），并内置贴合率自检。

与 step5 的差异（刻意为之）：
  - 不经过 viewer 居中帧（CENTER/airwayMesh 质心）：RK2 输出直接在 mask 体素
    mm 帧，一次性变换到 GLB 帧（perm[2,1,0] + 平移；与 pA 的
    transform_viewer_to_glb 同口径，只是平移量按本工具的对齐方法实测）。
  - 不写 viewer_data.js / 六板报表 / 切片 / 占位体：只产流线。
  - step5_export_viewer_data.py 保持只读，本工具是其逻辑的独立复刻。

核心参数（与 step5 逐字一致）：
  STEP_SEED_MM=3.0  种子=鼻孔开口体素沿内向偏移 3mm（必在体网格内）
  SEED_BIN_MM=2.0   开口点 2mm 网格分箱取代表点
  STEP_MM=0.7       RK2 弧长步长
  MAX_STEP=600      最多 600 步（≈420mm 弧长）
  SPD_EPS=1e-4      低速停止
  MIN_PTS=20        ≥20 点才收
  方向自检：frac_down≥0.5 且 z1.mean()<z0.mean()，失败 sign=-1 翻转重积

CLI 示例：
  py -X utf8 make_flowlines_standalone.py --case-id pB ^
      --vtu  "...\VTK\P0-case-pB-v1_1500\internal.vtu" ^
      --mask "...\out\step2\mask_full-pB-v1.npz" ^
      --glb  "...\webapp\models\airway_pB.glb" ^
      --dicom-dir "...\赛方CT\ISO_Soft_0.468mm" ^
      --metrics-json "...\后处理\metrics.json" ^
      --out  "...\webapp\models\flowlines_pB.json"
"""
import argparse
import glob
import json
import os
import sys
import time

import numpy as np

T0 = time.time()


def log(msg):
    print(f"[{time.time() - T0:6.1f}s] {msg}", flush=True)


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
ap = argparse.ArgumentParser(description="独立流线生成工具（step5 RK2 积分器复刻）")
ap.add_argument("--case-id", required=True, help="病例 ID（写进 JSON 的 case 字段，如 pB）")
ap.add_argument("--vtu", default=None, help="速度场 internal.vtu（米制）")
ap.add_argument("--case-dir", default=None,
                help="VTU 目录（自动找内部唯一的 internal.vtu；与 --vtu 二选一）")
ap.add_argument("--mask", required=True, help="mask_full-*.npz（含 mask/cut，体素帧）")
ap.add_argument("--glb", default=None, help="气道 GLB（贴合率自检 + 坐标对齐基准）")
ap.add_argument("--out", required=True, help="输出 flowlines JSON 路径")
ap.add_argument("--dicom-dir", default=None, help="DICOM 目录（读体素间距；与 --spacing 二选一）")
ap.add_argument("--spacing", default=None,
                help="体素间距 'sx,sy,sz' mm（覆盖 --dicom-dir）")
ap.add_argument("--metrics-json", default=None, help="后处理 metrics.json（可选，携带临床指标）")
ap.add_argument("--baseline", default=None,
                help="算例口径文案（默认 '<case-id> @15 L/min 层流，simpleFoam 稳态'）")
ap.add_argument("--perm", default="2,1,0",
                help="体素帧→GLB 帧轴置换（默认 2,1,0，与 pA 一致）")
ap.add_argument("--align", default="icp", choices=("icp", "bbox", "centroid", "walls", "none"),
                help="GLB 帧平移量确定方法：icp=GLB 顶点↔掩模边界体素表面 ICP 平移配准"
                     "（默认，残差应≈半个体素尺寸）；bbox=体素bbox↔GLB bbox；"
                     "centroid=掩模边界体素质心↔GLB 顶点质心；"
                     "walls=VTU walls.vtp 面点质心↔GLB 顶点质心；none=不平移（需 --trans）")
ap.add_argument("--trans", default=None,
                help="手动指定平移 'x,y,z' mm（覆盖 --align）")
ap.add_argument("--check-samples", type=int, default=2000,
                help="贴合率自检采样点数（默认 2000，均匀抽样）")
ap.add_argument("--no-check", action="store_true", help="跳过贴合率自检")
ARGS = ap.parse_args()

# ----------------------------------------------------------------------------
# 0. 输入解析
# ----------------------------------------------------------------------------
VTU = ARGS.vtu
if VTU is None:
    if not ARGS.case_dir:
        raise SystemExit("!!! 需 --vtu 或 --case-dir 之一")
    hits = sorted(glob.glob(os.path.join(ARGS.case_dir, "**", "internal.vtu"),
                            recursive=True))
    if len(hits) != 1:
        raise SystemExit(f"!!! --case-dir 下 internal.vtu 命中 {len(hits)} 个（需唯一）：{hits}")
    VTU = hits[0]
if not os.path.isfile(VTU):
    raise SystemExit(f"!!! VTU 不存在：{VTU}")
if not os.path.isfile(ARGS.mask):
    raise SystemExit(f"!!! mask npz 不存在：{ARGS.mask}")

if ARGS.spacing:
    SX_FULL, SY_FULL, SZ_FULL = (float(x) for x in ARGS.spacing.split(","))
elif ARGS.dicom_dir:
    import pydicom
    _fs = sorted(glob.glob(os.path.join(ARGS.dicom_dir, "*.dcm")))
    if len(_fs) < 2:
        raise SystemExit(f"!!! DICOM 目录不足 2 个 .dcm：{ARGS.dicom_dir}")
    _a = pydicom.dcmread(_fs[0], stop_before_pixels=True)
    _b = pydicom.dcmread(_fs[1], stop_before_pixels=True)
    _ps = [float(x) for x in _a.PixelSpacing]
    _dz = abs(float(_b.ImagePositionPatient[2]) - float(_a.ImagePositionPatient[2]))
    SX_FULL, SY_FULL, SZ_FULL = round(_ps[0], 4), round(_ps[1], 4), round(_dz, 4)
else:
    raise SystemExit("!!! 需 --spacing 或 --dicom-dir（体素间距）")
# VTK 降采样2× 网格间距（mm）——与 step5 一致（抽取倍率保持 2）
DS2_X = round(SX_FULL * 2, 4)
DS2_Y = round(SY_FULL * 2, 4)
DS2_Z = round(SZ_FULL * 2, 4)
log(f"间距(全分辨率) {SX_FULL}/{SY_FULL}/{SZ_FULL} mm; 降采样2x {DS2_X}/{DS2_Y}/{DS2_Z} mm")

PERM = tuple(int(x) for x in ARGS.perm.split(","))
assert sorted(PERM) == [0, 1, 2], f"--perm 须为 0,1,2 的排列：{PERM}"

# ----------------------------------------------------------------------------
# 1. 读掩码（step5 §0 同逻辑）
# ----------------------------------------------------------------------------
log(f"读掩码 {ARGS.mask} ...")
npz = np.load(ARGS.mask)
mask = npz["mask"]
cut = npz["cut"]
log(f"  mask {mask.shape} 体素 {int(mask.sum())}")

# ----------------------------------------------------------------------------
# 2. 速度场：读 internal.vtu，建结构化体素速度网格（step5 §2 逐字复刻）
# ----------------------------------------------------------------------------
log(f"读 {VTU} ...")
import meshio

m = meshio.read(VTU)
log(f"  points {m.points.shape} 单元 {m.cells[0].data.shape[0]} 类型 {m.cells[0].type}")
# T12：降采样2× 网格体心索引范围动态探测（VTU 点 bbox）
_pmin = m.points.min(axis=0) * 1000.0
_pmax = m.points.max(axis=0) * 1000.0
I0 = int(np.floor(_pmin[0] / DS2_X))
J0 = int(np.floor(_pmin[1] / DS2_Y))
K0 = int(np.floor(_pmin[2] / DS2_Z))
I1 = int(np.floor(_pmax[0] / DS2_X - 0.5))
J1 = int(np.floor(_pmax[1] / DS2_Y - 0.5))
K1 = int(np.floor(_pmax[2] / DS2_Z - 0.5))
NI, NJ, NK = I1 - I0 + 1, J1 - J0 + 1, K1 - K0 + 1
log(f"  DS2 网格动态探测: I0/J0/K0={I0}/{J0}/{K0}  NI/NJ/NK={NI}/{NJ}/{NK}")
Ucell = np.asarray(m.cell_data["U"][0], dtype=np.float64)         # (ncell,3) m/s
conn = m.cells[0].data
cc_m = m.points[conn].mean(axis=1)                               # 单元中心 (m)
cc_mm = cc_m * 1000.0

# 体心 -> 网格索引
ii_c = np.round(cc_mm[:, 0] / DS2_X - 0.5).astype(np.int64) - I0
jj_c = np.round(cc_mm[:, 1] / DS2_Y - 0.5).astype(np.int64) - J0
kk_c = np.round(cc_mm[:, 2] / DS2_Z - 0.5).astype(np.int64) - K0
assert ii_c.min() >= 0 and ii_c.max() < NI and jj_c.min() >= 0 and jj_c.max() < NJ \
    and kk_c.min() >= 0 and kk_c.max() < NK, "网格索引越界"
VG = np.full((NK, NJ, NI, 3), np.nan)
VG[kk_c, jj_c, ii_c] = Ucell
FLUID = ~np.isnan(VG[..., 0])
spd_all = np.linalg.norm(Ucell, axis=1)
log(f"  体素速度网格 {VG.shape} 充填 {int(FLUID.sum())}；单元速度 m/s "
    f"min/mean/max = {spd_all.min():.4f}/{spd_all.mean():.4f}/{spd_all.max():.4f}")


def sample_vel(p_mm):
    """p_mm:(3,) -> 速度 (m/s) 或 None（插值权重不足）。step5 sample_vel 逐字复刻。"""
    gi = p_mm[0] / DS2_X - (I0 + 0.5)
    gj = p_mm[1] / DS2_Y - (J0 + 0.5)
    gk = p_mm[2] / DS2_Z - (K0 + 0.5)
    i0f, j0f, k0f = np.floor(gi), np.floor(gj), np.floor(gk)
    fi, fj, fk = gi - i0f, gj - j0f, gk - k0f
    i0f, j0f, k0f = int(i0f), int(j0f), int(k0f)
    acc = np.zeros(3)
    wsum = 0.0
    for di in (0, 1):
        wi = fi if di else 1.0 - fi
        ii = i0f + di
        if ii < 0 or ii >= NI:
            continue
        for dj in (0, 1):
            wj = fj if dj else 1.0 - fj
            jj = j0f + dj
            if jj < 0 or jj >= NJ:
                continue
            for dk in (0, 1):
                wk = fk if dk else 1.0 - fk
                kk = k0f + dk
                if kk < 0 or kk >= NK:
                    continue
                if not FLUID[kk, jj, ii]:
                    continue
                w = wi * wj * wk
                if w <= 0:
                    continue
                acc += w * VG[kk, jj, ii]
                wsum += w
    if wsum < 0.25:
        return None
    return acc / wsum


# ----------------------------------------------------------------------------
# 2b. 播种：由 mask+cut 求鼻孔开口（=mask 中与头外空气 cut 相邻的体素）
#     step5 §2b 逐字复刻
# ----------------------------------------------------------------------------
log("求鼻孔开口（mask ∩ 邻域(cut)）...")
boundary = np.zeros_like(mask)
for ax, s in ((0, 1), (0, -1), (1, 1), (1, -1), (2, 1), (2, -1)):
    sh = np.roll(cut, s, axis=ax)
    sl = [slice(None)] * 3
    sl[ax] = 0 if s == 1 else -1
    sh[tuple(sl)] = False
    boundary |= (mask & sh)
bk, bj, bi = np.where(boundary)
bx = bi * SX_FULL
by = bj * SY_FULL
bz = bk * SZ_FULL
mid_x = (bx.min() + bx.max()) / 2.0

sides = {}


def mean_inward(c, R=6.0):
    """鼻孔质心 c 附近 R(mm) 内流体单元的平均速度方向（= CFD 入流方向）。step5 逐字复刻。"""
    ri = int(np.ceil(R / DS2_X))
    rj = int(np.ceil(R / DS2_Y))
    rk = int(np.ceil(R / DS2_Z))
    ci = int(round(c[0] / DS2_X - 0.5)) - I0
    cj = int(round(c[1] / DS2_Y - 0.5)) - J0
    ck = int(round(c[2] / DS2_Z - 0.5)) - K0
    i0, i1 = max(0, ci - ri), min(NI, ci + ri + 1)
    j0, j1 = max(0, cj - rj), min(NJ, cj + rj + 1)
    k0, k1 = max(0, ck - rk), min(NK, ck + rk + 1)
    sub = VG[k0:k1, j0:j1, i0:i1]
    fl = ~np.isnan(sub[..., 0])
    Ki, Ji, Ii = np.meshgrid(np.arange(k0, k1), np.arange(j0, j1),
                             np.arange(i0, i1), indexing="ij")
    P = np.stack([(Ii + I0 + 0.5) * DS2_X, (Ji + J0 + 0.5) * DS2_Y,
                  (Ki + K0 + 0.5) * DS2_Z], -1)
    d = np.linalg.norm(P - c, axis=-1)
    sel = fl & (d < R)
    vm = sub[sel].mean(axis=0)
    return vm / np.linalg.norm(vm)


for name, sel in (("L", bx < mid_x), ("R", bx >= mid_x)):
    pts = np.stack([bx[sel], by[sel], bz[sel]], axis=1)
    c = pts.mean(axis=0)
    n = mean_inward(c, 6.0)
    sides[name] = dict(pts=pts, centroid=c, inward=n)
    log(f"  鼻孔{name}: {int(sel.sum())} 体素, 质心 {np.round(c, 2).tolist()} mm, "
        f"内向(近 6mm 平均流速) {np.round(n, 3).tolist()}")

# 播种：开口点按 2.0mm 网格分箱取代表点，再沿内向偏移 3mm
STEP_SEED_MM = 3.0
SEED_BIN_MM = 2.0
seeds = []
for name in ("L", "R"):
    pts = sides[name]["pts"]
    n = sides[name]["inward"]
    key = np.round(pts / SEED_BIN_MM).astype(int)
    _, inv = np.unique(key, axis=0, return_inverse=True)
    for b in range(int(inv.max()) + 1):
        cp = pts[inv == b].mean(axis=0)
        seeds.append(cp + n * STEP_SEED_MM)
log(f"  种子候选 {len(seeds)} 个")

# ----------------------------------------------------------------------------
# 2c. RK2 积分（弧长参数化，步长 0.7mm，>600 步或出域停止）——step5 §2c 逐字复刻
# ----------------------------------------------------------------------------
STEP_MM = 0.7
MAX_STEP = 600
SPD_EPS = 1e-4
MIN_PTS = 20


def integrate(seed, sign=1.0):
    """RK2、弧长参数化；sign=-1 时逆流速积分（方向自检失败时翻转重做）。step5 逐字复刻。"""
    p = np.asarray(seed, dtype=np.float64)
    v = sample_vel(p)
    if v is None:
        return None
    v = sign * v
    sp = np.linalg.norm(v)
    if sp < SPD_EPS:
        return None
    pts = [p.copy()]
    sps = [sp]
    for _ in range(MAX_STEP):
        n1 = v / (np.linalg.norm(v) + 1e-12)
        p_mid = p + (STEP_MM * 0.5) * n1
        v2 = sample_vel(p_mid)
        n2 = (v2 / (np.linalg.norm(v2) + 1e-12)) if (v2 is not None
                                                  and np.linalg.norm(v2) > SPD_EPS) else n1
        p = p + STEP_MM * n2
        v = sample_vel(p)
        if v is None:
            break
        sp = np.linalg.norm(v)
        if sp < SPD_EPS:
            break
        pts.append(p.copy())
        sps.append(sp)
    return (np.array(pts), np.array(sps)) if len(pts) >= MIN_PTS else None


def build(sign):
    out = []
    for s0 in seeds:
        r = integrate(s0, sign)
        if r is not None:
            out.append(r)
    return out


streamlines = build(1.0)
if streamlines:
    z0 = np.array([s[0][0][2] for s in streamlines])
    z1 = np.array([s[0][-1][2] for s in streamlines])
    frac_down = float((z1 < z0).mean())
else:
    frac_down = 0.0
log(f"  streamlines 有效 {len(streamlines)} 条（≥{MIN_PTS} 点）")

# 方向自检：起点应近鼻孔、终点应落鼻咽（z 最低区域），流向 鼻孔→鼻咽
flipped = False
if streamlines and not (frac_down >= 0.5 and z1.mean() < z0.mean()):
    log(f"  方向自检未通过(向下比例={frac_down:.2f}, 起点z均={z0.mean():.1f} "
        f"终点z均={z1.mean():.1f}) -> 翻转重做")
    streamlines = build(-1.0)
    flipped = True
    z0 = np.array([s[0][0][2] for s in streamlines])
    z1 = np.array([s[0][-1][2] for s in streamlines])
    frac_down = float((z1 < z0).mean())
log(f"  方向自检: 起点平均z={z0.mean():.1f}mm 终点平均z={z1.mean():.1f}mm; "
    f"向下(终点z<起点z)比例={frac_down:.2f}; 翻转重积={flipped}")
if not streamlines:
    raise SystemExit("!!! 无有效流线（积分全灭）——检查 VTU/mask/间距是否配套")

# 长度分布（证据）
_plens = np.array([len(s[0]) for s in streamlines])
_arc = np.array([len(s[0]) * STEP_MM for s in streamlines])
log(f"  长度分布: 条数={len(_plens)} 点/条 min/mean/max="
    f"{_plens.min()}/{_plens.mean():.1f}/{_plens.max()}; "
    f"弧长mm min/mean/max={_arc.min():.1f}/{_arc.mean():.1f}/{_arc.max():.1f}")

# ----------------------------------------------------------------------------
# 3. 坐标变换：体素 mm 帧 -> GLB 帧（perm[2,1,0] + 平移；与 pA 口径一致）
# ----------------------------------------------------------------------------
kk_a, jj_a, ii_a = np.where(mask)
vox_pts = np.stack([ii_a * SX_FULL, jj_a * SY_FULL, kk_a * SZ_FULL], axis=1)  # 全体素中心
# 掩模边界体素（表面采样，供 centroid 对齐）
bnd = np.zeros_like(mask)
for ax, s in ((0, 1), (0, -1), (1, 1), (1, -1), (2, 1), (2, -1)):
    sh = np.roll(mask, s, axis=ax)
    sl = [slice(None)] * 3
    sl[ax] = 0 if s == 1 else -1
    sh[tuple(sl)] = False
    bnd |= (mask & ~sh)
bk_, bj_, bi_ = np.where(bnd)
bnd_pts = np.stack([bi_ * SX_FULL, bj_ * SY_FULL, bk_ * SZ_FULL], axis=1)


def apply_perm(p):
    """轴置换作用于最后一维：(...,3) -> (...,3)；PERM=(2,1,0) 即 (x,y,z)->(z,y,x)"""
    return p[..., list(PERM)]


glb_mesh = None
ICP_RESID = None
if ARGS.glb:
    import trimesh
    glb_mesh = trimesh.load(ARGS.glb, force="mesh")

if ARGS.trans:
    TRANS = np.array([float(x) for x in ARGS.trans.split(",")])
    align_note = f"手动指定 trans={TRANS.tolist()}"
elif ARGS.align == "none":
    TRANS = np.zeros(3)
    align_note = "none（无平移）"
elif glb_mesh is None:
    TRANS = np.zeros(3)
    align_note = "无 GLB 提供且未指定 trans → 零平移（体素帧直出）"
elif ARGS.align == "bbox":
    TRANS = glb_mesh.bounds[0] - apply_perm(vox_pts.min(axis=0))
    _tmax = glb_mesh.bounds[1] - apply_perm(vox_pts.max(axis=0))
    align_note = (f"bbox 对齐（掩模全体素 bbox min ↔ GLB bbox min）；"
                  f"max 侧反推 trans={np.round(_tmax, 3).tolist()} "
                  f"（与 min 侧差 {np.round(np.abs(_tmax - TRANS), 3).tolist()} mm）")
elif ARGS.align == "centroid":
    TRANS = glb_mesh.vertices.mean(axis=0) - apply_perm(bnd_pts.mean(axis=0))
    align_note = ("centroid 对齐（掩模边界体素质心 ↔ GLB 顶点质心）")
elif ARGS.align == "icp":
    # GLB 顶点（perm 后）↔ 掩模边界体素中心：仅估平移的 ICP 配准。
    # 残差应≈半个体素尺寸（掩模表面本身是体素量化采样）——残差显著偏大即配准失败。
    from scipy.spatial import cKDTree
    Gv = apply_perm(np.asarray(glb_mesh.vertices, dtype=np.float64))
    tree = cKDTree(bnd_pts)
    u = np.zeros(3)
    niter = 0
    for _ in range(12):
        q = Gv - u
        _, nidx = tree.query(q, k=1, workers=-1)
        step = (q - bnd_pts[nidx]).mean(axis=0)
        u = u + step
        niter += 1
        if np.linalg.norm(step) < 1e-4:
            break
    q = Gv - u
    dres, _ = tree.query(q, k=1, workers=-1)
    TRANS = apply_perm(u)
    ICP_RESID = float(dres.mean())
    align_note = (f"icp 表面配准（GLB {len(Gv)} 顶点 ↔ 掩模边界体素 {len(bnd_pts)} 中心，"
                  f"仅平移 {niter} 迭代收敛）；配准残差 均值 {dres.mean():.3f}/"
                  f"中位 {np.median(dres):.3f}mm（噪声地板≈半个体素 "
                  f"{max(SX_FULL, SY_FULL, SZ_FULL) / 2:.2f}mm）")
elif ARGS.align == "walls":
    # walls.vtp：与 internal.vtu 同目录的 boundary/walls.vtp（气道壁面，体素帧）
    _wd = os.path.join(os.path.dirname(VTU), "boundary", "walls.vtp")
    if not os.path.isfile(_wd):
        raise SystemExit(f"!!! --align walls 需要 {_wd}（不存在）")
    _wm = meshio.read(_wd, file_format="vtk")
    _wp = np.asarray(_wm.points, dtype=np.float64) * 1000.0
    TRANS = glb_mesh.vertices.mean(axis=0) - apply_perm(_wp.mean(axis=0))
    align_note = (f"walls 对齐（{os.path.basename(_wd)} {len(_wp)} 面点质心 ↔ "
                  f"GLB {len(glb_mesh.vertices)} 顶点质心）")
log(f"  坐标变换: perm={list(PERM)} trans={np.round(TRANS, 4).tolist()} mm; {align_note}")

lines_vox = [s[0] for s in streamlines]          # 体素帧
lines_glb = [apply_perm(p) + TRANS for p in lines_vox]  # GLB 帧

# ----------------------------------------------------------------------------
# 4. 贴合率自检（流线点在气道腔内的验证；无 rtree 依赖的 numpy 实现）
# ----------------------------------------------------------------------------
fit = {}
if glb_mesh is not None and not ARGS.no_check:
    log("贴合率自检 ...")
    V = np.asarray(glb_mesh.vertices, dtype=np.float64)
    F = np.asarray(glb_mesh.faces, dtype=np.int64)
    TRIS = V[F]                                        # (m,3,3)
    allpts = np.concatenate(lines_glb, axis=0)
    n_all = len(allpts)
    ns = min(ARGS.check_samples, n_all)
    sidx = np.unique(np.linspace(0, n_all - 1, ns).astype(np.int64))
    P = allpts[sidx]

    # --- 4a. 射线奇偶 inside 判定（与 pA 定标同法：Möller–Trumbore；
    #       GLB 在鼻孔/咽端有开口致非 watertight，绕组数会漏，
    #       故用 3 轴方向多数票增强开口鲁棒性） ---
    v0 = TRIS[:, 0, :]
    e1 = TRIS[:, 1, :] - v0
    e2 = TRIS[:, 2, :] - v0
    DIRS = [np.array([1.0, 0, 0]), np.array([0, 1.0, 0]), np.array([0, 0, 1.0])]
    votes = np.zeros(len(P), dtype=np.int64)
    per_dir = []
    for d in DIRS:
        pv = np.cross(d, e2)                                   # (m,3)
        det = np.einsum("mj,mj->m", e1, pv)                    # (m,)
        ok = np.abs(det) > 1e-12
        inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        hits = np.zeros(len(P), dtype=bool)
        CH = 50
        for i in range(0, len(P), CH):
            o = P[i:i + CH]                                    # (c,3)
            tv = o[:, None, :] - v0[None, :, :]                # (c,m,3)
            u = np.einsum("cmj,mj->cm", tv, pv) * inv[None, :]
            qv = np.cross(tv, e1[None, :, :])                  # (c,m,3)
            vv = np.einsum("j,cmj->cm", d, qv) * inv[None, :]
            t = np.einsum("mj,cmj->cm", e2, qv) * inv[None, :]
            hit = (ok[None, :] & (u >= 0) & (u <= 1) & (vv >= 0)
                   & (u + vv <= 1) & (t > 1e-9))
            hits[i:i + CH] = (hit.sum(axis=1) % 2) == 1
        votes += hits
        per_dir.append(round(float(hits.mean()), 4))
    inside_mask = votes * 2 > len(DIRS)
    inside_rate = float(inside_mask.mean())
    log(f"  射线奇偶 inside 率（{len(P)} 采样点，3 轴多数票）: {inside_rate * 100:.1f}%"
        f"（分方向 {[round(x * 100, 1) for x in per_dir]}%）")

    # --- 4b. 到 GLB 表面距离（面质心 cKDTree 候选 + 精确点三角距离） ---
    from scipy.spatial import cKDTree

    def pt_tri_dist(p, a, b, c):
        """Ericson《Real-Time Collision Detection》closestPointOnTriangle，向量化。
        p/a/b/c 同形广播 (...,3) -> 最近距离 (...)"""
        ab, ac, ap = b - a, c - a, p - a
        d1 = np.einsum("...i,...i->...", ab, ap)
        d2 = np.einsum("...i,...i->...", ac, ap)
        bp = p - b
        d3 = np.einsum("...i,...i->...", ab, bp)
        d4 = np.einsum("...i,...i->...", ac, bp)
        cp = p - c
        d5 = np.einsum("...i,...i->...", ab, cp)
        d6 = np.einsum("...i,...i->...", ac, cp)
        vc = d1 * d4 - d3 * d2
        vb = d5 * d2 - d1 * d6
        va = d3 * d6 - d5 * d4
        # 各区域最近点（全部算出再按条件选，避免分支）
        pA = a
        pB = b
        pC = c
        vAB = d1 / np.where(d1 - d3 == 0, 1e-30, d1 - d3)
        pAB = a + vAB[..., None] * ab
        wAC = d2 / np.where(d2 - d6 == 0, 1e-30, d2 - d6)
        pAC = a + wAC[..., None] * ac
        wBC = (d4 - d3) / np.where((d4 - d3) + (d5 - d6) == 0, 1e-30,
                                   (d4 - d3) + (d5 - d6))
        pBC = b + wBC[..., None] * (c - b)
        den = np.where(va + vb + vc == 0, 1e-30, va + vb + vc)
        v = (vb / den)[..., None]
        w = (vc / den)[..., None]
        pIN = a + ab * v + ac * w
        regA = (d1 <= 0) & (d2 <= 0)
        regB = (d3 >= 0) & (d4 <= d3)
        regC = (d6 >= 0) & (d5 <= d6)
        eAB = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
        eAC = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
        eBC = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
        # 区域优先级与 Ericson 原文一致：A 顶点 → B 顶点 → AB 边 → C 顶点 → AC 边 → BC 边 → 面内
        q = np.where(regA[..., None], pA,
            np.where(regB[..., None], pB,
            np.where(eAB[..., None], pAB,
            np.where(regC[..., None], pC,
            np.where(eAC[..., None], pAC,
            np.where(eBC[..., None], pBC, pIN))))))
        return np.linalg.norm(p - q, axis=-1)

    cent = TRIS.mean(axis=1)
    tree = cKDTree(cent)
    KC = 48
    _, cidx = tree.query(P, k=KC)
    cidx = np.atleast_2d(cidx)
    cand = TRIS[cidx]                                  # (n,KC,3,3)
    dd = pt_tri_dist(P[:, None, :], cand[..., 0, :], cand[..., 1, :], cand[..., 2, :])
    dmin = dd.min(axis=1)

    # 候选充分性抽检（16 点 brute force 全网格对比）
    rng = np.random.default_rng(7)
    vidx = rng.choice(len(P), size=min(16, len(P)), replace=False)
    dev = []
    for vi in vidx:
        dall = pt_tri_dist(P[vi], TRIS[:, 0, :], TRIS[:, 1, :], TRIS[:, 2, :])
        dev.append(abs(float(dall.min()) - float(dmin[vi])))
    dev_max = float(np.max(dev)) if dev else 0.0

    fit = {
        "samples": int(len(P)),
        "inside_rate": round(inside_rate, 4),
        "inside_rate_per_dir": per_dir,
        "dist_median_mm": round(float(np.median(dmin)), 3),
        "dist_p90_mm": round(float(np.percentile(dmin, 90)), 3),
        "dist_max_mm": round(float(dmin.max()), 3),
        "frac_within_2mm": round(float((dmin < 2.0).mean()), 4),
        "cand_check_max_dev_mm": round(dev_max, 4),
        "icp_residual_mean_mm": (None if ICP_RESID is None else round(ICP_RESID, 4)),
        "method": ("ray-parity inside（Möller–Trumbore，3 轴多数票）+ "
                   "face-centroid cKDTree(48) 候选精确点三角距离"),
    }
    log(f"  距 GLB 表面: 中位 {fit['dist_median_mm']}mm p90 {fit['dist_p90_mm']}mm "
        f"max {fit['dist_max_mm']}mm; <2mm 占比 {fit['frac_within_2mm'] * 100:.1f}%; "
        f"候选抽检最大偏差 {fit['cand_check_max_dev_mm']}mm")

# ----------------------------------------------------------------------------
# 5. 输出 JSON（与 pA 同构：{p,s} / vmax_p98 / metrics）
# ----------------------------------------------------------------------------
all_s = np.concatenate([s[1] for s in streamlines])
vmax_p98 = round(float(np.percentile(all_s, 98)), 4)
speed_abs_max = round(float(np.abs(all_s).max()), 2)

stream_out = []
for pts, sps in zip(lines_glb, [s[1] for s in streamlines]):
    pc = np.round(pts, 2) + 0.0
    stream_out.append({
        "p": [float(v) for v in pc.reshape(-1)],
        "s": [round(float(s), 2) for s in sps],
    })

metrics = {}
if ARGS.metrics_json and os.path.isfile(ARGS.metrics_json):
    with open(ARGS.metrics_json, "r", encoding="utf-8") as f:
        MJ = json.load(f)
    tot = MJ.get("totals", {})
    wss = MJ.get("wss", {})
    q_lmin = float(tot.get("Q_inlet_total_L_min", 15.0) or 15.0)
    dp = float(tot.get("dP_Pa", 0.0) or 0.0)
    metrics = {
        "dP_baseline_Pa": round(dp, 2),
        "split_L_pct": round(float(tot.get("flow_share_L_pct", 0.0)), 1),
        "split_R_pct": round(float(tot.get("flow_share_R_pct", 0.0)), 1),
        "wss_mean_Pa": round(float(wss.get("mean_Pa", 0.0)), 4),
        "wss_p95_Pa": round(float(wss.get("p95_Pa", 0.0)), 4),
        "resistance_total": f"{dp / (q_lmin / 60.0):.1f} Pa/(L/s)",
        "Re_eq": round(float(tot.get("Re_eq", 0.0)), 1),
    }

baseline = ARGS.baseline or f"{ARGS.case_id} @15 L/min 层流，simpleFoam 稳态"
n_points = int(sum(len(o["p"]) // 3 for o in stream_out))
glb_name = os.path.basename(ARGS.glb) if ARGS.glb else "(未提供)"

doc = {
    "case": ARGS.case_id,
    "kind": "cfd_streamlines",
    "source": ("make_flowlines_standalone.py（step5_export_viewer_data.py 自研 RK2 弧长"
               "积分器独立复刻；种子=鼻孔开口体素沿内向内推 3mm；步长 0.7mm×≤600 步；"
               "方向自检+翻转重积）"),
    "case_baseline": baseline,
    "units": "mm, m/s",
    "frame": (f"{glb_name} 同帧（体素 mm 帧 perm{list(PERM)} + 平移 "
              f"{np.round(TRANS, 4).tolist()}；前端渲染时减模型 bbox 中心，无需再变换）"),
    "transform_viewer_to_glb": {"perm": list(PERM), "sgn": [1, 1, 1],
                                "trans": [round(float(x), 4) for x in TRANS]},
    "transform_evidence": (f"{align_note}；前端 loadCfdFlow 不再应用任何变换"
                           "（坐标已烘烤），transform 字段仅作溯源记录"),
    "n_lines": len(stream_out),
    "n_points": n_points,
    "vmax_p98": vmax_p98,
    "speed_abs_max": speed_abs_max,
    "metrics": metrics,
    "fit_check": fit,
    "lines": stream_out,
}

os.makedirs(os.path.dirname(os.path.abspath(ARGS.out)), exist_ok=True)
tmp = ARGS.out + ".tmp"
with open(tmp, "w", encoding="utf-8", newline="\n") as f:
    json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
os.replace(tmp, ARGS.out)
log(f"已写出 {ARGS.out}")
log(f"汇总: case={ARGS.case_id} lines={doc['n_lines']} points={doc['n_points']} "
    f"pts/line mean={n_points / max(1, doc['n_lines']):.1f} "
    f"vmax_p98={vmax_p98} speed_abs_max={speed_abs_max}")
if fit:
    # 硬门（工具可控量：坐标变换与落位）：
    #   inside ≥85%（pA 冻结基线 85.4%；旧版现场积分产物反面对照 99%+ 但距壁中位 2.75-3.62mm）
    #   <2mm 占比 ≥70%（pA 基线 77.1%；"贴壁"签名——旧版仅 11.6-28.9%）
    #   ICP 配准残差 ≤1.0mm（噪声地板≈半个体素 0.17-0.31mm；>1mm 即配准失败）
    gate_in = fit["inside_rate"] >= 0.85
    gate_hug = fit["frac_within_2mm"] >= 0.70
    gate_icp = (ICP_RESID is None) or (ICP_RESID <= 1.0)
    # 软告警（例依赖量：流线长度由本例 CFD 流场结构决定——
    #   pN/pN2 气道含 1-2mm 窄通道、DS2 网格(≈1mm)不可分辨，线在窄通道口出域，
    #   与官方后处理 fig3_streamlines.png 同特征；pA 基线 147.5 点/条）
    mean_len = n_points / max(1, doc["n_lines"])
    warn_len = mean_len < 80.0
    log(f"硬门: inside={fit['inside_rate'] * 100:.1f}%"
        f"({'PASS' if gate_in else 'FAIL'} ≥85%) ; "
        f"<2mm 占比={fit['frac_within_2mm'] * 100:.1f}%"
        f"({'PASS' if gate_hug else 'FAIL'} ≥70%) ; "
        f"ICP 残差({'PASS' if gate_icp else 'FAIL'} ≤1.0mm)")
    if warn_len:
        log(f"提示: 点/条均值 {mean_len:.1f} < 80（pA 基线 147.5）——"
            f"长度由本例 CFD 流场结构决定（窄通道出域），非坐标/落位问题；"
            f"请结合 inside/贴壁指标与官方 fig3 判读")
    if not (gate_in and gate_hug and gate_icp):
        log("!!! 硬门未过——坐标变换或输入配套可疑，请先取证再采用")
        sys.exit(3)
log("DONE")
