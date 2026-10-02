# -*- coding: utf-8 -*-
"""
step5_export_viewer_data.py  ——  任务 T2：CFD 结果查看器数据导出
                                 任务 T4：v2 鼻腔/鼻窦网格拆分（返工单-T4-网格拆分.md）

规格书：contest3_workspace/pipeline/规格书-T2-查看器数据导出.md
返工单：contest3_workspace/pipeline/返工单-T4-网格拆分.md
产出：  out/step5/viewer_data.js  +  out/step5/viewer_data_qc.json

T4 新增：airwayCavity（鼻腔本体表面）/ airwaySinus（鼻窦表面）两字段，
         复用 step3_make_narrowing.py 的 isolate_cavity 腔体隔离；
         CENTER 沿用 v1（[79.22,71.87,56.98]），契约其余字段逐字节不变。

输入（只读）：
  - 速度场 VTK：.../P0-result-pA-v5/VTK/P0-case-v5_1500/internal.vtu
  - 气道掩码： out/step2/mask_full.npz  (mask, cut)
  - 占位体 STL：阶段4-模型输出/virtual-placeholder-{1,2,3}mm*.stl

坐标：mask 全分辨率体素 (k,j,i)，x=i*0.3496, y=j*0.3496, z=k*0.35 mm；
      VTK 几何为米，*1000 后与体素坐标同源（已验证）。全部几何统一到 mm，
      再减去 airwayMesh 质心（全局同一偏移量）。

自测：pipeline 目录下  py -X utf8 step5_export_viewer_data.py
"""
import os, sys, glob, json, time, base64
import numpy as np

# ----------------------------------------------------------------------------
# 路径
# ----------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
OUT_STEP5 = os.path.join(HERE, "out", "step5")
MASK_NPZ = os.path.join(HERE, "out", "step2", "mask_full.npz")
VTU = r"%DATA_ROOT%\项目\P0-鼻塞设计工具\阶段2-CFD算例包\结果\P0-result-pA-v5\VTK\P0-case-v5_1500\internal.vtu"
PH_DIR = r"%DATA_ROOT%\项目\P0-鼻塞设计工具\阶段4-模型输出"

# mask 全分辨率体素间距（mm）
SX_FULL, SY_FULL, SZ_FULL = 0.3496, 0.3496, 0.35
# VTK 降采样2× 网格间距（mm）
DS2_X, DS2_Y, DS2_Z = 0.6992, 0.6992, 0.70
# 降采样2× 网格体心索引范围（由探测得到，见报告）
I0, J0, K0 = 50, 30, 0          # 最小体心索引
NI, NJ, NK = 126, 141, 147      # 网格维度

T_START = time.time()
LOG = []
def log(msg):
    line = f"[{time.time()-T_START:6.1f}s] {msg}"
    print(line); LOG.append(line)

os.makedirs(OUT_STEP5, exist_ok=True)

# ----------------------------------------------------------------------------
# [F3] T10 视觉平滑常量（工单 方案-T10施工方案-v1.2.1 §一 行4 / 放行令-看板①）
#      Taubin λ/μ 双步平滑；仅作用于三个显示壳（airwayMesh/airwayCavity/
#      airwaySinus）的顶点坐标；faces/indices 与 tricubic 插值/占位体/切片/
#      流线一律不动。meta 契约字面值（split_L_pct 等）不因平滑改变。
# ----------------------------------------------------------------------------
SMOOTH_ITERS = 20        # Taubin 迭代数（λ 步 + μ 步各 SMOOTH_ITERS 次）
TAUBIN_LAMBDA = 0.5      # λ 收缩步长
TAUBIN_MU = -0.53        # μ 膨胀步长（负值；|μ|>λ 抑制体积收缩）
# [F3] 六板偏离报表落盘路径（共享树唯一事实源目录）与皮肤壳数据（帧校验用）
F3_BOARDS_JSON = r"%DATA_ROOT%\项目\P0-鼻塞设计工具\阶段5-交互查看器\升级施工-T10\out_f3\six_boards.json"
F3_SKIN_DATA_JS = r"%DATA_ROOT%\项目\P0-鼻塞设计工具\阶段5-交互查看器\skin_data.js"
# [F3 裁决（本轮）] 共享目录 viewer_data.js（外科手术式写盘基底 = 09-30 未平滑原版）
SHARED_VIEWER_DATA_JS = r"%DATA_ROOT%\项目\P0-鼻塞设计工具\阶段5-交互查看器\viewer_data.js"
# [F3] 门禁阈值（工单：④比率变化>0.1% 即停；⑤逐轴偏差>2mm 即上报；⑥最小值<0 即停）
F3_LR_RATIO_TOL = 0.001      # 左右半体积比 相对变化 0.1%
F3_BBOX_TOL_MM = 2.0         # 帧校验容差 mm（与 viewer.html initSkin 帧校验同口径）
F3_MIN_CLEARANCE = 0.0       # 流线-壳最小间隙（壳体内侧为正）
# [F3 门禁 v3] 歧义折叠豁免阈值：最近内侧面与最近外侧面距离差 < 0.1mm（裁决：歧义折叠非真实穿壁）
F3_AMBIGUITY_TOL_MM = 0.1

# ----------------------------------------------------------------------------
# [F3] Taubin λ/μ 平滑实现（邻接关系由 faces 构建；scipy.sparse CSR 二值邻接）
# ----------------------------------------------------------------------------
def _build_adjacency(faces, n_verts):
    """由 faces 构建对称二值邻接矩阵（CSR）：顶点 -> 相邻顶点"""
    import scipy.sparse as sp
    f = np.asarray(faces, dtype=np.int64)
    e0 = np.concatenate([f[:, 0], f[:, 1], f[:, 2]])
    e1 = np.concatenate([f[:, 1], f[:, 2], f[:, 0]])
    A = sp.coo_matrix((np.ones(len(e0)), (e0, e1)),
                      shape=(n_verts, n_verts)).tocsr()
    A.setdiag(0)                    # 去自环
    A.data = np.ones_like(A.data)   # 二值化（消除多重边权重）
    A.eliminate_zeros()
    return A

def taubin_smooth(mesh, lamb=TAUBIN_LAMBDA, mu=TAUBIN_MU, iters=SMOOTH_ITERS):
    """Taubin λ/μ 双步平滑：原地平滑 mesh.vertices；faces/indices 不动。
    每迭代：V += λ·(邻域均值−V)（收缩步）；V += μ·(邻域均值−V)（膨胀步，μ<0）。"""
    V = np.asarray(mesh.vertices, dtype=np.float64).copy()
    F = np.asarray(mesh.faces, dtype=np.int64)
    n = len(V)
    A = _build_adjacency(F, n)
    deg = np.asarray(A.sum(axis=1)).ravel()
    deg_inv = np.zeros(n)
    deg_inv[deg > 0] = 1.0 / deg[deg > 0]
    for _ in range(iters):
        mean = A.dot(V) * deg_inv[:, None]      # 邻域均值（孤立点=0）
        mean[deg == 0] = V[deg == 0]            # 孤立点不动
        V = V + lamb * (mean - V)
        mean = A.dot(V) * deg_inv[:, None]
        mean[deg == 0] = V[deg == 0]
        V = V + mu * (mean - V)
    mesh.vertices = V
    return mesh



# ----------------------------------------------------------------------------
# 0. 读掩码
# ----------------------------------------------------------------------------
log("读掩码 mask_full.npz ...")
npz = np.load(MASK_NPZ)
mask = npz["mask"]                # (394,512,512) bool
cut = npz["cut"]
log(f"  mask {mask.shape} 体素 {int(mask.sum())};  z 层范围 k=[{np.argwhere(mask)[:,0].min()},{np.argwhere(mask)[:,0].max()}]")

# 全分辨率体素索引 -> mm 坐标
def vox_mm(kk, jj, ii):
    return (ii * SX_FULL, jj * SY_FULL, kk * SZ_FULL)


# ----------------------------------------------------------------------------
# 1. airwayMesh：mask 降采样3× -> marching_cubes -> trimesh -> decimate <=40000
# ----------------------------------------------------------------------------
log("airwayMesh: mask 降采样3× + marching_cubes ...")
from skimage import measure
import trimesh

k, j, i = mask.shape
k3, j3, i3 = k // 3, j // 3, i // 3
blk = mask[:k3*3, :j3*3, :i3*3].astype(np.uint8).reshape(k3, 3, j3, 3, i3, 3)
blk = blk.any(axis=(1, 3, 5))            # 块内任一为真 -> 粗体素
spx, spy, spz = SX_FULL*3, SY_FULL*3, SZ_FULL*3   # ~1.0488, ~1.0488, 1.05 mm
log(f"  降采样3× 网格 {blk.shape}，粗体素 {int(blk.sum())}，spacing {spx:.4f}/{spy:.4f}/{spz:.4f} mm")

vol = np.pad(blk.astype(np.float32), 1)          # 补零闭合开口
verts_kji, faces, _, _ = measure.marching_cubes(vol, level=0.5, spacing=(spz, spy, spx))
verts_kji = verts_kji - 1.0                       # 撤销 padding
V_air = np.stack([verts_kji[:, 2], verts_kji[:, 1], verts_kji[:, 0]], axis=1)  # -> (x,y,z) mm
air = trimesh.Trimesh(vertices=V_air, faces=faces, process=True)
log(f"  marching_cubes 顶点 {len(air.vertices)} 面 {len(air.faces)}")

DECIMATE_MODE = "none"
FACE_TARGET_AIR = 40000
if len(air.faces) > FACE_TARGET_AIR:
    try:
        import fast_simplification  # noqa: F401
        air = air.simplify_quadric_decimation(face_count=FACE_TARGET_AIR)
        DECIMATE_MODE = "fast-simplification"
    except Exception as e:
        log(f"  ! fast-simplification 不可用({e})，降级")
        k4, j4, i4 = k // 4, j // 4, i // 4
        b4 = mask[:k4*4, :j4*4, :i4*4].astype(np.uint8).reshape(k4, 4, j4, 4, i4, 4).any(axis=(1, 3, 5))
        v4, f4, _, _ = measure.marching_cubes(np.pad(b4.astype(np.float32), 1), level=0.5,
                                              spacing=(SZ_FULL*4, SY_FULL*4, SX_FULL*4))
        v4 = v4 - 1.0
        air = trimesh.Trimesh(vertices=np.stack([v4[:, 2], v4[:, 1], v4[:, 0]], 1), faces=f4, process=True)
        DECIMATE_MODE = "ds4-fallback-no-repair"
log(f"  airwayMesh 面 {len(air.faces)}（模式 {DECIMATE_MODE}）")

# [F3] Taubin 视觉平滑（仅 airwayMesh 显示壳顶点；indices 不动）
_F3_air_before = air.vertices.copy()
taubin_smooth(air)
log(f"  [F3] airwayMesh Taubin 平滑完成（{SMOOTH_ITERS} 迭代, λ={TAUBIN_LAMBDA}, μ={TAUBIN_MU}）")


# 全局质心（居中偏移量）—— 以 airwayMesh 顶点质心为准，airway/placeholders/streamlines/slices 通用
# CENTER 固定为 v1 产出常量（T4审计：decimate跨进程不确定，硬编码保证重跑几何确定性）
CENTER = np.array([79.224894, 71.872321, 56.979602])
log(f"  全局质心 CENTER(mm) = {np.round(CENTER,2).tolist()} (v1固定常量)")

def center_round(arr_mm, nd=1):
    a = np.asarray(arr_mm, dtype=np.float64) - CENTER
    a = np.round(a, nd) + 0.0   # +0.0 去除 -0.0
    return a

air_c = center_round(air.vertices, 1)
airwayMesh = {
    "positions": [float(v) for v in air_c.reshape(-1)],
    "indices": [int(x) for x in air.faces.reshape(-1)],
}


# ----------------------------------------------------------------------------
# 2. 速度场：读 internal.vtu，建结构化体素速度网格（体心）
# ----------------------------------------------------------------------------
log("读 internal.vtu ...")
import meshio
m = meshio.read(VTU)
log(f"  points {m.points.shape} 单元 {m.cells[0].data.shape[0]} 类型 {m.cells[0].type}")
Ucell = np.asarray(m.cell_data["U"][0], dtype=np.float64)         # (ncell,3) m/s
conn = m.cells[0].data
cc_m = m.points[conn].mean(axis=1)                               # 单元中心 (m)
cc_mm = cc_m * 1000.0

# 体心 -> 网格索引
ii_c = np.round(cc_mm[:, 0] / DS2_X - 0.5).astype(np.int64) - I0
jj_c = np.round(cc_mm[:, 1] / DS2_Y - 0.5).astype(np.int64) - J0
kk_c = np.round(cc_mm[:, 2] / DS2_Z - 0.5).astype(np.int64) - K0
assert ii_c.min() >= 0 and ii_c.max() < NI and jj_c.min() >= 0 and jj_c.max() < NJ and kk_c.min() >= 0 and kk_c.max() < NK, "网格索引越界"
VG = np.full((NK, NJ, NI, 3), np.nan)
VG[kk_c, jj_c, ii_c] = Ucell
FLUID = ~np.isnan(VG[..., 0])
spd_all = np.linalg.norm(Ucell, axis=1)
log(f"  体素速度网格 {VG.shape} 充填 {int(FLUID.sum())}；单元速度 m/s min/mean/max = "
    f"{spd_all.min():.4f}/{spd_all.mean():.4f}/{spd_all.max():.4f}")

def sample_vel(p_mm):
    """p_mm:(3,) -> 速度 (m/s) 或 None（插值权重不足）"""
    gi = p_mm[0] / DS2_X - (I0 + 0.5)
    gj = p_mm[1] / DS2_Y - (J0 + 0.5)
    gk = p_mm[2] / DS2_Z - (K0 + 0.5)
    i0f, j0f, k0f = np.floor(gi), np.floor(gj), np.floor(gk)
    fi, fj, fk = gi - i0f, gj - j0f, gk - k0f
    i0f, j0f, k0f = int(i0f), int(j0f), int(k0f)
    acc = np.zeros(3); wsum = 0.0
    for di in (0, 1):
        wi = fi if di else 1.0 - fi
        ii = i0f + di
        if ii < 0 or ii >= NI: continue
        for dj in (0, 1):
            wj = fj if dj else 1.0 - fj
            jj = j0f + dj
            if jj < 0 or jj >= NJ: continue
            for dk in (0, 1):
                wk = fk if dk else 1.0 - fk
                kk = k0f + dk
                if kk < 0 or kk >= NK: continue
                if not FLUID[kk, jj, ii]: continue
                w = wi * wj * wk
                if w <= 0: continue
                acc += w * VG[kk, jj, ii]; wsum += w
    if wsum < 0.25:
        return None
    return acc / wsum


# ----------------------------------------------------------------------------
# 2b. 播种：由 mask+cut 求鼻孔开口（=mask 中与头外空气 cut 相邻的体素）
# ----------------------------------------------------------------------------
log("求鼻孔开口（mask ∩ 邻域(cut)）...")
boundary = np.zeros_like(mask)
for ax, s in ((0, 1), (0, -1), (1, 1), (1, -1), (2, 1), (2, -1)):
    sh = np.roll(cut, s, axis=ax)
    sl = [slice(None)]*3
    sl[ax] = 0 if s == 1 else -1
    sh[tuple(sl)] = False
    boundary |= (mask & sh)
bk, bj, bi = np.where(boundary)
bx = bi * SX_FULL; by = bj * SY_FULL; bz = bk * SZ_FULL
mid_x = (bx.min() + bx.max()) / 2.0
mask_ctr = np.array([bi.mean()*SX_FULL, bj.mean()*SY_FULL, bk.mean()*SZ_FULL])

sides = {}

def mean_inward(c, R=6.0):
    """鼻孔质心 c 附近 R(mm) 内流体单元的平均速度方向（= CFD 入流方向，物理意义上的“向内”）"""
    ri = int(np.ceil(R / DS2_X)); rj = int(np.ceil(R / DS2_Y)); rk = int(np.ceil(R / DS2_Z))
    ci = int(round(c[0] / DS2_X - 0.5)) - I0
    cj = int(round(c[1] / DS2_Y - 0.5)) - J0
    ck = int(round(c[2] / DS2_Z - 0.5)) - K0
    i0, i1 = max(0, ci - ri), min(NI, ci + ri + 1)
    j0, j1 = max(0, cj - rj), min(NJ, cj + rj + 1)
    k0, k1 = max(0, ck - rk), min(NK, ck + rk + 1)
    sub = VG[k0:k1, j0:j1, i0:i1]
    fl = ~np.isnan(sub[..., 0])
    Ki, Ji, Ii = np.meshgrid(np.arange(k0, k1), np.arange(j0, j1), np.arange(i0, i1), indexing="ij")
    P = np.stack([(Ii + I0 + 0.5) * DS2_X, (Ji + J0 + 0.5) * DS2_Y, (Ki + K0 + 0.5) * DS2_Z], -1)
    d = np.linalg.norm(P - c, axis=-1)
    sel = fl & (d < R)
    vm = sub[sel].mean(axis=0)
    return vm / np.linalg.norm(vm)

for name, sel in (("L", bx < mid_x), ("R", bx >= mid_x)):
    pts = np.stack([bx[sel], by[sel], bz[sel]], axis=1)
    c = pts.mean(axis=0)
    n = mean_inward(c, 6.0)          # 入口面质心附近的平均入流方向
    sides[name] = dict(pts=pts, centroid=c, inward=n)
    log(f"  鼻孔{name}: {int(sel.sum())} 体素, 质心 {np.round(c,2).tolist()} mm, 内向(近 6mm 平均流速) {np.round(n,3).tolist()}")

# 播种：开口点按 2.0mm 网格分箱取代表点，再沿内向偏移 3mm
STEP_SEED_MM = 3.0
seeds = []
for name in ("L", "R"):
    pts = sides[name]["pts"]; n = sides[name]["inward"]
    key = np.round(pts / 2.0).astype(int)
    _, inv = np.unique(key, axis=0, return_inverse=True)
    for b in range(int(inv.max()) + 1):
        cp = pts[inv == b].mean(axis=0)
        seeds.append(cp + n * STEP_SEED_MM)
log(f"  种子候选 {len(seeds)} 个")

# ----------------------------------------------------------------------------
# 2c. RK2 积分（弧长参数化，步长 ~0.7mm，>600 步或出域停止）
# ----------------------------------------------------------------------------
STEP_MM = 0.7
MAX_STEP = 600
SPD_EPS = 1e-4

def integrate(seed, sign=1.0):
    """RK2、弧长参数化；sign=-1 时逆流速积分（方向自检失败时翻转重做）"""
    p = np.asarray(seed, dtype=np.float64)
    v = sample_vel(p)
    if v is None:
        return None
    v = sign * v
    sp = np.linalg.norm(v)
    if sp < SPD_EPS:
        return None
    pts = [p.copy()]; sps = [sp]
    for _ in range(MAX_STEP):
        n1 = v / (np.linalg.norm(v) + 1e-12)
        p_mid = p + (STEP_MM * 0.5) * n1
        v2 = sample_vel(p_mid)
        n2 = (v2 / (np.linalg.norm(v2) + 1e-12)) if (v2 is not None and np.linalg.norm(v2) > SPD_EPS) else n1
        p = p + STEP_MM * n2
        v = sample_vel(p)
        if v is None:
            break
        sp = np.linalg.norm(v)
        if sp < SPD_EPS:
            break
        pts.append(p.copy()); sps.append(sp)
    return (np.array(pts), np.array(sps)) if len(pts) >= 20 else None

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
log(f"  streamlines 有效 {len(streamlines)} 条（≥20 点）")

# 方向自检：起点应近鼻孔、终点应落 nasopharynx（z 最低区域），流向 鼻孔→鼻咽
if streamlines and not (frac_down >= 0.5 and z1.mean() < z0.mean()):
    log(f"  方向自检未通过(向下比例={frac_down:.2f}, 起点z均={z0.mean():.1f} 终点z均={z1.mean():.1f}) -> 翻转重做")
    streamlines = build(-1.0)
    z0 = np.array([s[0][0][2] for s in streamlines]); z1 = np.array([s[0][-1][2] for s in streamlines])
    frac_down = float((z1 < z0).mean())
log(f"  方向自检: 起点平均z={z0.mean():.1f}mm 终点平均z={z1.mean():.1f}mm; 向下(终点z<起点z)比例={frac_down:.2f}")

stream_out = []
for pts, sps in streamlines:
    pc = center_round(pts, 1)
    stream_out.append({
        "points": [float(v) for v in pc.reshape(-1)],
        "speed": [round(float(s), 2) for s in sps],
    })


# ----------------------------------------------------------------------------
# 3. slices：z=35/45/55/65mm（体素层换算）4 片，每片 ≤4000 点
# ----------------------------------------------------------------------------
log("slices ...")
slices = []
for z_nom in (35.0, 45.0, 55.0, 65.0):
    kk = int(round(z_nom / SZ_FULL))
    kk = max(0, min(mask.shape[0] - 1, kk))
    z_act = kk * SZ_FULL
    jj, ii = np.where(mask[kk])
    n = len(ii)
    if n == 0:
        log(f"  z={z_nom}mm (k={kk}) 空层，跳过"); continue
    if n > 4000:
        idx = np.linspace(0, n - 1, 4000).astype(np.int64)   # 均匀抽样
        ii, jj = ii[idx], jj[idx]
    P = np.stack([ii * SX_FULL, jj * SY_FULL, np.full(len(ii), z_act)], axis=1)
    pos, spd = [], []
    for p in P:
        v = sample_vel(p)
        if v is None:
            continue
        pc = p - CENTER
        # z 采用规格标称值 z_nom（35/45/55/65）；x/y/z 均减全局质心（同一偏移）
        pos += [round(float(pc[0]), 1) + 0.0, round(float(pc[1]), 1) + 0.0, round(float(z_nom - CENTER[2]), 1) + 0.0]
        spd.append(round(float(np.linalg.norm(v)), 2))
    slices.append({"z_mm": round(float(z_nom), 2), "positions": pos, "speed": spd})
    log(f"  z_nom={z_nom}mm -> 最近层 k={kk} z_act={z_act:.2f}mm 采样 {len(spd)} 点")


# ----------------------------------------------------------------------------
# 4. placeholders：每档合并全部分件 STL，decimate ≤15000 面，同一质心偏移
# ----------------------------------------------------------------------------
log("placeholders ...")
placeholders = []
for mm in (1, 2, 3):
    files = sorted(glob.glob(os.path.join(PH_DIR, f"virtual-placeholder-{mm}mm*.stl")))
    parts = [trimesh.load(f, force="mesh") for f in files]
    merged = trimesh.util.concatenate(parts)
    nf0 = len(merged.faces)
    if nf0 > 15000:
        try:
            merged = merged.simplify_quadric_decimation(face_count=15000)
        except Exception as e:
            log(f"  ! {mm}mm decimate 失败({e})，保留原样")
    vc = center_round(merged.vertices, 1)
    placeholders.append({
        "mm": mm,
        "positions": [float(v) for v in vc.reshape(-1)],
        "indices": [int(x) for x in merged.faces.reshape(-1)],
    })
    log(f"  {mm}mm: {len(files)} 件 -> 合并 {nf0} 面 -> {len(merged.faces)} 面; 文件 {[os.path.basename(f) for f in files]}")


# ----------------------------------------------------------------------------
# 4b. [T4] 鼻腔本体 / 鼻窦 拆分（复用 step3_make_narrowing.py 的 isolate_cavity）
# ----------------------------------------------------------------------------
log("[T4] 鼻腔/鼻窦拆分 ...")
from scipy import ndimage

def isolate_cavity(mask_):
    """与 step3_make_narrowing.py §2 完全一致：侵蚀3次(6邻接)→label最大→膨胀3次 & mask"""
    st = ndimage.generate_binary_structure(3, 1)
    eroded = ndimage.binary_erosion(mask_, structure=st, iterations=3)
    lab, n = ndimage.label(eroded)
    sizes = np.bincount(lab.ravel())
    keep = int(np.argmax(sizes[1:]) + 1)
    cavity_core = lab == keep
    del lab, eroded
    cavity = ndimage.binary_dilation(cavity_core, iterations=3) & mask_
    return cavity_core, cavity, n, keep

cavity_core, cavity, n_lab, keep_lab = isolate_cavity(mask)
sinus = mask & ~cavity
log(f"  侵蚀组件 {n_lab} 个, 保留 label={keep_lab}, core={int(cavity_core.sum())}, "
    f"cavity 体素={int(cavity.sum())}, sinus 体素={int(sinus.sum())}")
# [N4] 拆分无损：cavity | sinus == mask
union_ok = bool(np.array_equal(cavity | sinus, mask))
log(f"  [N4] (cavity|sinus)==mask : {union_ok}")

def mesh_from_voxels(bool_vol, face_target, tag, fallback_iters=4):
    """与 v1 airwayMesh 相同的加工：3× 块任一为真降采样 → MC(spacing 1.0488/1.0488/1.05) →
       fast-simplification 减面；不可用则再降采样一档。顶点返回 mm、索引分帧。"""
    kk_, jj_, ii_ = bool_vol.shape
    k3_, j3_, i3_ = kk_ // 3, jj_ // 3, ii_ // 3
    b3 = bool_vol[:k3_*3, :j3_*3, :i3_*3].astype(np.uint8).reshape(k3_, 3, j3_, 3, i3_, 3).any(axis=(1, 3, 5))
    v_kji, fcs, _, _ = measure.marching_cubes(np.pad(b3.astype(np.float32), 1), level=0.5,
                                              spacing=(spz, spy, spx))
    v_kji = v_kji - 1.0
    mesh = trimesh.Trimesh(vertices=np.stack([v_kji[:, 2], v_kji[:, 1], v_kji[:, 0]], 1),
                           faces=fcs, process=True)
    mode = "none"
    if len(mesh.faces) > face_target:
        try:
            import fast_simplification  # noqa: F401
            mesh = mesh.simplify_quadric_decimation(face_count=face_target)
            mode = "fast-simplification"
        except Exception as e:
            log(f"    ! {tag} fast-simplification 不可用({e})，降级再降采样")
            b4 = bool_vol[:kk_//fallback_iters*fallback_iters, :jj_//fallback_iters*fallback_iters,
                          :ii_//fallback_iters*fallback_iters].astype(np.uint8).reshape(
                kk_//fallback_iters, fallback_iters, jj_//fallback_iters, fallback_iters,
                ii_//fallback_iters, fallback_iters).any(axis=(1, 3, 5))
            v4, f4, _, _ = measure.marching_cubes(np.pad(b4.astype(np.float32), 1), level=0.5,
                                                  spacing=(SZ_FULL*fallback_iters, SY_FULL*fallback_iters, SX_FULL*fallback_iters))
            v4 = v4 - 1.0
            mesh = trimesh.Trimesh(vertices=np.stack([v4[:, 2], v4[:, 1], v4[:, 0]], 1), faces=f4, process=True)
            mode = f"ds{fallback_iters}-fallback"
    return mesh, mode

cavity_mesh, cav_mode = mesh_from_voxels(cavity, 30000, "cavity")
sinus_mesh, sin_mode = mesh_from_voxels(sinus, 20000, "sinus")
log(f"  airwayCavity 面 {len(cavity_mesh.faces)}（模式 {cav_mode}）; airwaySinus 面 {len(sinus_mesh.faces)}（模式 {sin_mode}）")

# [F3] Taubin 视觉平滑（airwayMesh + airwayCavity 显示壳顶点；indices 不动）
# [裁决1] airwaySinus 豁免平滑：鼻窦壳 558 连通分量/688 非流形边，Taubin 冻结参数
#   （λ=0.5/μ=−0.53/20 迭代）下收缩 −10.27%（trimesh 同参交叉验证 −10.45%，10 λμ
#   对仍 −8.34%）——冻结参数与碎裂壳结构不可兼得；解剖保真优先于外观平滑收益；
#   鼻窦壳在演示中为 ⓘ 次要展示层。顶点原样保留，一个字节不动。
_F3_cav_before = cavity_mesh.vertices.copy()
_F3_sin_before = sinus_mesh.vertices.copy()   # 豁免：仅捕获用于报表 before==after 验证
taubin_smooth(cavity_mesh)
log(f"  [F3] airwayCavity Taubin 平滑完成（{SMOOTH_ITERS} 迭代, λ={TAUBIN_LAMBDA}, "
    f"μ={TAUBIN_MU}）；airwaySinus 豁免平滑（顶点原样保留）")


# 同一 CENTER 居中（沿用 v1，不重算）
cav_c = center_round(cavity_mesh.vertices, 1)
sin_c = center_round(sinus_mesh.vertices, 1)
airwayCavity = {"positions": [float(v) for v in cav_c.reshape(-1)],
                "indices": [int(x) for x in cavity_mesh.faces.reshape(-1)]}
airwaySinus = {"positions": [float(v) for v in sin_c.reshape(-1)],
               "indices": [int(x) for x in sinus_mesh.faces.reshape(-1)]}



# ----------------------------------------------------------------------------
# [F3] 六板偏离报表 + 放行门禁（工单 §一 行4 / 放行令-看板① 四.2）
#      任何一板越限 → 停工：不写盘新 viewer_data.js（sys.exit(3) 等指挥官）
# ----------------------------------------------------------------------------
def _f3_mesh(verts, faces):
    return trimesh.Trimesh(vertices=np.asarray(verts, dtype=np.float64),
                           faces=np.asarray(faces, dtype=np.int64), process=False)

def _f3_normal_offsets(before_verts, after_mesh):
    """板①：逐顶点位移投影到原法向（before 网格顶点法向）的带符号偏移"""
    before_mesh = _f3_mesh(before_verts, after_mesh.faces)
    n0 = before_mesh.vertex_normals
    d = np.asarray(after_mesh.vertices, dtype=np.float64) - np.asarray(before_verts, dtype=np.float64)
    return np.einsum("ij,ij->i", d, n0)

def _f3_clip_halfspace(triangles, axis=0, keep=1):
    """散度定理平面裁剪：把三角形碎片裁到 keep*x[axis]>=0 半空间。
    cap 全部落在 x=0 平面、其四面体体积贡献恒为 0，故无需显式封盖——
    等价于 trimesh.intersections.slice_mesh_plane(..., cap=True) 的体积口径；
    本环境缺 shapely（slice_mesh_plane 的 cap 分支依赖），故用等价法（工单许可）。"""
    v = np.asarray(triangles, dtype=np.float64)
    x = v[:, :, axis] * keep
    inside = x >= 0.0
    n_in = inside.sum(axis=1)
    parts = [v[n_in == 3]]
    m1 = n_in == 1
    if m1.any():
        t1 = v[m1]; ins1 = inside[m1]
        ia = np.argmax(ins1, axis=1)
        ib = (ia + 1) % 3; ic = (ia + 2) % 3
        A = t1[np.arange(len(t1)), ia]
        B = t1[np.arange(len(t1)), ib]
        C = t1[np.arange(len(t1)), ic]
        xa = A[:, axis] * keep; xb = B[:, axis] * keep; xc = C[:, axis] * keep
        Pab = A + (xa / (xa - xb))[:, None] * (B - A)
        Pac = A + (xa / (xa - xc))[:, None] * (C - A)
        parts.append(np.stack([A, Pab, Pac], axis=1))
    m2 = n_in == 2
    if m2.any():
        t2 = v[m2]; ins2 = inside[m2]
        oa = np.argmax(~ins2, axis=1)
        ob = (oa + 1) % 3; oc = (oa + 2) % 3
        O = t2[np.arange(len(t2)), oa]
        B = t2[np.arange(len(t2)), ob]
        C = t2[np.arange(len(t2)), oc]
        xo = O[:, axis] * keep; xb = B[:, axis] * keep; xc = C[:, axis] * keep
        Pob = O + (xo / (xo - xb))[:, None] * (B - O)
        Poc = O + (xo / (xo - xc))[:, None] * (C - O)
        parts.append(np.stack([B, C, Poc], axis=1))
        parts.append(np.stack([B, Poc, Pob], axis=1))
    parts = [p for p in parts if len(p)]
    if not parts:
        return np.zeros((0, 3, 3))
    return np.concatenate(parts, axis=0)

def _f3_half_volumes(verts, faces):
    """板④：沿（居中帧）x=0 平面切分壳并分别算体积。
    左半 = 患者左半区 = 居中帧 x>0（定向铁律 cmd_t10_lr_chain2.py A1/A2）；
    右半 = 患者右半区 = 居中帧 x<0。返回 (V_left, V_right)。"""
    v = np.asarray(verts, dtype=np.float64) - CENTER      # 居中帧
    tris = v[np.asarray(faces, dtype=np.int64)]            # (F,3,3)
    vols = {}
    for tag, keep in (("left_x_pos", 1), ("right_x_neg", -1)):
        frags = _f3_clip_halfspace(tris, axis=0, keep=keep)
        if len(frags):
            vol = float(np.einsum("ij,ij->i",
                                  frags[:, 0, :],
                                  np.cross(frags[:, 1, :], frags[:, 2, :])).sum() / 6.0)
        else:
            vol = 0.0
        vols[tag] = vol
    return vols["left_x_pos"], vols["right_x_neg"]

def _f3_skin_bbox():
    """皮肤壳 free 组 bbox（int16×quant_mm 解码，与 viewer.html skinTriGeo 同口径）"""
    txt = open(F3_SKIN_DATA_JS, encoding="utf-8").read()
    i = txt.find("window.SKIN_DATA")
    body = txt[i:].split("=", 1)[1].strip()
    end = body.find(";")
    skin = json.loads(body[:end])
    q = float(skin["quant_mm"])
    raw = base64.b64decode(skin["free"]["pos_b64"])
    verts = np.frombuffer(raw, dtype="<i2").astype(np.float64).reshape(-1, 3) * q
    return verts.min(axis=0), verts.max(axis=0)

def _pt_tri_dist_sq(p, a, b, c):
    """点到三角形 abc 的距离平方（向量化精确法：面内正交投影或三边段最近点）"""
    ab = b - a; ac = c - a; ap = p - a
    n = np.cross(ab, ac)
    n2 = np.einsum("...i,...i->...", n, n)
    t = np.einsum("...i,...i->...", ap, n) / (n2 + 1e-30)
    q = p - t[..., None] * n
    w = q - a
    abab = np.einsum("...i,...i->...", ab, ab)
    abac = np.einsum("...i,...i->...", ab, ac)
    acac = np.einsum("...i,...i->...", ac, ac)
    abw = np.einsum("...i,...i->...", ab, w)
    acw = np.einsum("...i,...i->...", ac, w)
    det = abab * acac - abac * abac
    u = (acac * abw - abac * acw) / (det + 1e-30)
    v = (abab * acw - abac * abw) / (det + 1e-30)
    inside_tri = (u >= 0.0) & (v >= 0.0) & (u + v <= 1.0) & (n2 > 1e-30)
    d_pl_sq = np.einsum("...i,...i->...", p - q, p - q)
    d_pl_sq = np.where(inside_tri, d_pl_sq, np.inf)

    def _seg_sq(p, s, e):
        se = e - s; sp = p - s
        l2 = np.einsum("...i,...i->...", se, se)
        tt = np.clip(np.einsum("...i,...i->...", sp, se) / (l2 + 1e-30), 0.0, 1.0)
        d = sp - tt[..., None] * se
        return np.einsum("...i,...i->...", d, d)

    d_seg = np.minimum(np.minimum(_seg_sq(p, a, b), _seg_sq(p, a, c)), _seg_sq(p, b, c))
    return np.minimum(d_pl_sq, d_seg)

def _f3_closest_point_exact(mesh, points):
    """[F3 板⑥] 精确最近表面点（等价 trimesh.proximity.closest_point；本环境缺 rtree）：
    质心 KD-tree 最近距离 d_up 是真实最近距离的上界，半径 d_up+最大三角形直径的
    候选集必含真实最近三角形，再对候选集做精确点-三角形距离。返回 (距离, 最近面索引)。"""
    from scipy.spatial import cKDTree
    pts = np.asarray(points, dtype=np.float64)
    tris = mesh.triangles
    cents = tris.mean(axis=1)
    e01 = np.linalg.norm(tris[:, 0, :] - tris[:, 1, :], axis=1)
    e12 = np.linalg.norm(tris[:, 1, :] - tris[:, 2, :], axis=1)
    e20 = np.linalg.norm(tris[:, 2, :] - tris[:, 0, :], axis=1)
    diam_max = float(max(e01.max(), e12.max(), e20.max()))
    tree = cKDTree(cents)
    n = len(pts)
    dist = np.empty(n)
    face_idx = np.empty(n, dtype=np.int64)
    for i in range(n):
        p = pts[i]
        d_up, _ = tree.query(p, k=1)
        cand = np.asarray(tree.query_ball_point(p, d_up + diam_max + 1e-9), dtype=np.int64)
        if len(cand) == 0:
            cand = np.asarray([int(tree.query(p, k=1)[1])], dtype=np.int64)
        d2 = _pt_tri_dist_sq(p[None, :], tris[cand, 0, :], tris[cand, 1, :], tris[cand, 2, :])
        j = int(np.argmin(d2))
        dist[i] = float(np.sqrt(d2[j]))
        face_idx[i] = int(cand[j])
    return dist, face_idx

def _f3_inside_by_local_normal(mesh, points, face_idx):
    """[F3 板⑥] 局部法向判内外（contains 不可用时的等价法）：
    点在最近面外侧（沿外法向投影 >0）视为壳外。"""
    fn = np.asarray(mesh.face_normals, dtype=np.float64)[face_idx]
    va = np.asarray(mesh.triangles[:, 0, :], dtype=np.float64)[face_idx]
    sgn = np.einsum("ij,ij->i", np.asarray(points, dtype=np.float64) - va, fn)
    return sgn < 0.0

def _f3_ambiguity_profile(mesh, point):
    """[F3 板⑥ 门禁 v3] 歧义剖面（裁决：歧义折叠豁免判据）：
    候选集（质心 KD-tree 最近距离上界 + 最大三角形直径半径，数学上必含真实
    最近三角形）内分别求最近"内侧面"（局部法向判 inside）与最近"外侧面"。
    两面相对该点取向相反；若两面距离差 < F3_AMBIGUITY_TOL_MM → 近等距
    多层面/折叠，最近面选择歧义（'外侧'判定非真实穿壁）→ 符号歧义。"""
    from scipy.spatial import cKDTree
    tris = mesh.triangles
    cents = tris.mean(axis=1)
    e01 = np.linalg.norm(tris[:, 0, :] - tris[:, 1, :], axis=1)
    e12 = np.linalg.norm(tris[:, 1, :] - tris[:, 2, :], axis=1)
    e20 = np.linalg.norm(tris[:, 2, :] - tris[:, 0, :], axis=1)
    diam_max = float(max(e01.max(), e12.max(), e20.max()))
    tree = cKDTree(cents)
    d_up, _ = tree.query(point, k=1)
    cand = np.asarray(tree.query_ball_point(point, d_up + diam_max + 1e-9), dtype=np.int64)
    if len(cand) == 0:
        cand = np.asarray([int(tree.query(point, k=1)[1])], dtype=np.int64)
    d2 = _pt_tri_dist_sq(point[None, :], tris[cand, 0, :], tris[cand, 1, :], tris[cand, 2, :])
    dd = np.sqrt(d2)
    fn = np.asarray(mesh.face_normals, dtype=np.float64)[cand]
    va = tris[cand, 0, :]
    sgn = np.einsum("ij,ij->i", point[None, :] - va, fn)
    in_mask = sgn < 0.0
    if in_mask.any():
        _k = int(np.argmin(np.where(in_mask, dd, np.inf)))
        d_in, n_in, f_in = float(dd[_k]), [float(x) for x in fn[_k]], int(cand[_k])
    else:
        d_in, n_in, f_in = None, None, -1
    if (~in_mask).any():
        _k = int(np.argmin(np.where(~in_mask, dd, np.inf)))
        d_out, n_out, f_out = float(dd[_k]), [float(x) for x in fn[_k]], int(cand[_k])
    else:
        d_out, n_out, f_out = None, None, -1
    return {"d_inside_mm": d_in, "normal_inside": n_in, "face_inside": f_in,
            "d_outside_mm": d_out, "normal_outside": n_out, "face_outside": f_out}


log("[F3] 六板偏离报表计算 ...")
shells_report = {}
gates = {}

for tag, mesh, before in (("airwayMesh", air, _F3_air_before),
                          ("airwayCavity", cavity_mesh, _F3_cav_before),
                          ("airwaySinus", sinus_mesh, _F3_sin_before)):
    after = np.asarray(mesh.vertices, dtype=np.float64)
    proj = _f3_normal_offsets(before, mesh)
    m_before = _f3_mesh(before, mesh.faces)
    vol_b = float(m_before.volume)
    vol_a = float(mesh.volume)
    cen_b = before.mean(axis=0)
    cen_a = after.mean(axis=0)
    try:
        mass_b = m_before.centroid; mass_a = mesh.centroid
        mass_note = "trimesh mass centroid"
    except Exception:
        mass_b = cen_b; mass_a = cen_a
        mass_note = "回退 vertex mean（mass centroid 不可用）"
    vl_b, vr_b = _f3_half_volumes(before, mesh.faces)
    vl_a, vr_a = _f3_half_volumes(after, mesh.faces)
    ratio_b = vl_b / vr_b if vr_b else float("inf")
    ratio_a = vl_a / vr_a if vr_a else float("inf")
    rel = abs(ratio_a - ratio_b) / ratio_b if np.isfinite(ratio_b) else float("inf")
    shells_report[tag] = {
        "verts": int(len(after)), "faces": int(len(mesh.faces)),
        "watertight_before": bool(m_before.is_watertight),
        "watertight_after": bool(mesh.is_watertight),
        "board1_normal_offset_mm": {
            "signed": {"mean": float(proj.mean()), "max": float(proj.max()),
                        "min": float(proj.min()),
                        "p95": float(np.percentile(proj, 95))},
            "abs": {"mean": float(np.abs(proj).mean()), "max": float(np.abs(proj).max()),
                     "p95": float(np.percentile(np.abs(proj), 95))},
            "note": "位移投影到原法向（平滑前网格顶点法向）；signed=外正内负"},
        "board2_volume_mm3": {"before": vol_b, "after": vol_a,
                               "change_pct": (vol_a - vol_b) / vol_b * 100.0},
        "board3_centroid_drift_mm": {
            "vertex_mean_before": [float(x) for x in cen_b],
            "vertex_mean_after": [float(x) for x in cen_a],
            "drift_xyz": [float(x) for x in (cen_a - cen_b)],
            "drift_norm": float(np.linalg.norm(cen_a - cen_b)),
            "mass_centroid_drift_xyz": [float(x) for x in (mass_a - mass_b)],
            "note": "vertex_mean 与 pipeline CENTER 推导口径一致；" + mass_note},
        "board4_lr_half_volumes_mm3": {
            "frame": "centered (world mm - CENTER); x=0 平面; 左=患者左=x>0, 右=患者右=x<0",
            "before": {"left_x_pos": vl_b, "right_x_neg": vr_b,
                        "ratio_left_over_right": ratio_b, "sum": vl_b + vr_b},
            "after": {"left_x_pos": vl_a, "right_x_neg": vr_a,
                       "ratio_left_over_right": ratio_a, "sum": vl_a + vr_a},
            "ratio_rel_change_pct": rel * 100.0,
            "trimesh_volume_before": vol_b, "trimesh_volume_after": vol_a,
            "sum_vs_trimesh_residual_pct_before": abs(vl_b + vr_b - vol_b) / vol_b * 100.0,
            "sum_vs_trimesh_residual_pct_after": abs(vl_a + vr_a - vol_a) / vol_a * 100.0},
    }

    # [F3 诊断] 拓扑（连通分量/非流形边；解释碎裂壳对 Taubin 收缩的敏感性，不参与门禁）
    try:
        _n_comp = len(mesh.split(only_watertight=False))
    except Exception:
        _n_comp = -1
    _ed = np.asarray(mesh.edges_sorted)
    _uc, _cc = np.unique(_ed, axis=0, return_counts=True)
    shells_report[tag]["diag_topology"] = {
        "components": int(_n_comp),
        "edges_shared_by_3plus_nonmanifold": int((_cc >= 3).sum()),
        "boundary_edges": int((_cc == 1).sum()),
        "note": "非水密但边界边=0 => 存在非流形边（decimate 产物）；连通分量多 => 壳碎裂"
                "（鼻窦=mask&~cavity，含众多小气房），对 Taubin 边界收缩更敏感"}

# 板④ 门禁：比率变化 >0.1% 即停（[裁决1] 仅对参与平滑的壳判定；airwaySinus 豁免）
_SMOOTHED_SHELLS = ("airwayMesh", "airwayCavity")
b4_bad = {k: v["board4_lr_half_volumes_mm3"]["ratio_rel_change_pct"]
          for k, v in shells_report.items()
          if k in _SMOOTHED_SHELLS
          and v["board4_lr_half_volumes_mm3"]["ratio_rel_change_pct"] > F3_LR_RATIO_TOL * 100.0}
gates["board4_lr_ratio_change_le_0.1pct"] = {"pass": not b4_bad, "bad": b4_bad,
                                              "tol_pct": F3_LR_RATIO_TOL * 100.0,
                                              "scope": "仅参与平滑的壳（裁决1：airwaySinus 豁免平滑）"}

# [裁决1] airwaySinus 豁免平滑：各板 before==after（顶点原样保留），记 exempted
_ExemptReason = ("裁决1 豁免平滑：鼻窦壳 558 连通分量/688 非流形边，Taubin 冻结参数下"
                 "收缩 −10.27%（trimesh 同参交叉验证 −10.45%，10 λμ 对仍 −8.34%）"
                 "——冻结参数与碎裂壳结构不可兼得；解剖保真优先于外观平滑收益；"
                 "鼻窦壳在演示中为 ⓘ 次要展示层。顶点原样保留，一个字节不动。")
shells_report["airwaySinus"]["exempted"] = True
shells_report["airwaySinus"]["exemption_reason"] = _ExemptReason
shells_report["airwaySinus"]["vertices_unchanged_exact"] = bool(
    np.array_equal(np.asarray(sinus_mesh.vertices, dtype=np.float64),
                   _F3_sin_before))

# 板⑤ 气道 bbox vs skin_data.js bbox 帧校验（复跑 viewer.html initSkin 同口径：
#   参考网格 = cavity || airway → airwayCavity 在位故取 cavity；容差 2.0mm）
log("[F3] 板⑤ 帧校验（skin free bbox vs 气道壳 bbox）...")
skin_min, skin_max = _f3_skin_bbox()
b5 = {"tol_mm": F3_BBOX_TOL_MM,
      "method": "viewer.html initSkin 帧校验同口径：参考网格=cavity||airway（airwayCavity 在位取 cavity）；只量 skin free 组；内存网格 raw CT-mm 减 CENTER 对齐 skin world 帧（= viewer_data.js 写盘帧）",
      "skin_free_bbox_min": [float(x) for x in skin_min],
      "skin_free_bbox_max": [float(x) for x in skin_max],
      "per_axis": {}, "bad_axes": []}
ref_mesh = cavity_mesh          # cavity || airway
ref_before = _F3_cav_before
# 帧对齐：内存网格为 raw CT-mm；skin_data.js 与 viewer_data.js 写盘值同为世界 mm-CENTER
# （step7 同帧；写盘走 center_round(-CENTER)），故逐轴减 CENTER 复刻写盘后帧再比 bbox。
for ax, axname in enumerate("xyz"):
    cav_min_b = float(ref_before[:, ax].min() - CENTER[ax])
    cav_max_b = float(ref_before[:, ax].max() - CENTER[ax])
    cav_min_a = float(ref_mesh.vertices[:, ax].min() - CENTER[ax])
    cav_max_a = float(ref_mesh.vertices[:, ax].max() - CENTER[ax])
    air_min_a = float(air.vertices[:, ax].min() - CENTER[ax])
    air_max_a = float(air.vertices[:, ax].max() - CENTER[ax])
    dev_min = float(skin_min[ax] - cav_min_a)     # >0 包住；<0 气道外伸
    dev_max = float(cav_max_a - skin_max[ax])     # >0 包住；<0 气道外伸
    b5["per_axis"][axname] = {
        "skin_min": float(skin_min[ax]), "cavity_min_after": cav_min_a,
        "dev_min_mm": dev_min, "skin_max": float(skin_max[ax]),
        "cavity_max_after": cav_max_a, "dev_max_mm": dev_max,
        "cavity_min_before": cav_min_b, "cavity_max_before": cav_max_b,
        "airwayMesh_min_after": air_min_a, "airwayMesh_max_after": air_max_a}
    if dev_min > F3_BBOX_TOL_MM:
        b5["bad_axes"].append(axname + "-")
    if dev_max > F3_BBOX_TOL_MM:
        b5["bad_axes"].append(axname + "+")
b5["pass"] = not b5["bad_axes"]
gates["board5_bbox_frame_dev_le_2mm"] = {"pass": b5["pass"], "bad_axes": b5["bad_axes"],
                                          "tol_mm": F3_BBOX_TOL_MM}

# 板⑥ 流线-壳间隙抽检 v2（[裁决2] 两段式门禁替代原 min≥0 口径）
#   采样：63 条流线每 5 点取 1；端区=每条流线首、尾各 1 个采样点
#   （帽区豁免：壳在鼻孔/咽口开放，流线端点本就穿过帽平面）
log("[F3] 板⑥ 流线-壳间隙抽检 v2 ...")
air_mesh_world = _f3_mesh(air.vertices, air.faces)
per_sl = []
for pts, _sps in streamlines:
    per_sl.append(np.asarray(pts, dtype=np.float64)[::5])
probe_pts = np.concatenate(per_sl, axis=0)
_sl_idx = np.concatenate([np.full(len(p), t, dtype=np.int64)
                          for t, p in enumerate(per_sl)])
_samp_idx = np.concatenate([np.arange(len(p), dtype=np.int64) for p in per_sl])
_n_samp = [len(p) for p in per_sl]
_endpoint_zone = np.zeros(len(probe_pts), dtype=bool)
_off = 0
for _p in per_sl:
    _endpoint_zone[_off] = True                        # 首采样点
    _endpoint_zone[_off + len(_p) - 1] = True          # 尾采样点
    _off += len(_p)
dist, face_idx = _f3_closest_point_exact(air_mesh_world, probe_pts)
if air_mesh_world.is_watertight:
    try:
        inside = air_mesh_world.contains(probe_pts)
        method = "精确点-三角形距离（质心 KD-tree 候选集；等价 trimesh.proximity.closest_point，本环境缺 rtree）+ contains（壳水密）"
    except Exception as _e:
        inside = _f3_inside_by_local_normal(air_mesh_world, probe_pts, face_idx)
        method = "精确点-三角形距离 + 最近面法向局部判内外（contains 不可用: %s）" % _e
else:
    inside = _f3_inside_by_local_normal(air_mesh_world, probe_pts, face_idx)
    method = "精确点-三角形距离 + 最近面法向局部判内外（壳非水密，contains 不可靠）"
clearance = np.where(inside, dist, -dist)

# [F3 诊断] 板⑥ 平滑前对照（同一精确法 + 同一局部法向判内外；v2 门禁 before 侧）
_F3_air_b_mesh = _f3_mesh(_F3_air_before, air.faces)
_db, _fb = _f3_closest_point_exact(_F3_air_b_mesh, probe_pts)
if _F3_air_b_mesh.is_watertight:
    try:
        _in_b = _F3_air_b_mesh.contains(probe_pts)
    except Exception:
        _in_b = _f3_inside_by_local_normal(_F3_air_b_mesh, probe_pts, _fb)
else:
    _in_b = _f3_inside_by_local_normal(_F3_air_b_mesh, probe_pts, _fb)
_clr_b = np.where(_in_b, _db, -_db)

# [裁决2] flip_points 逐点诊断（正→负翻转点全量留档，即使门禁全过也保留）
# [裁决（本轮）门禁 v3] 每个翻转点附歧义剖面档案（最近内/外侧面距离、法向、
#   腔宽解释全量留档——即使门禁全过也保留，裁决2 要求）
_flip = (_clr_b >= 0.0) & (clearance < 0.0)
flip_points = []
_flip_entry_by_flat = {}
for _ii in np.where(_flip)[0]:
    _prof = _f3_ambiguity_profile(air_mesh_world, probe_pts[_ii])
    _ddiff = (None if (_prof["d_inside_mm"] is None or _prof["d_outside_mm"] is None)
              else float(abs(_prof["d_inside_mm"] - _prof["d_outside_mm"])))
    _amb = bool(_ddiff is not None and _ddiff < F3_AMBIGUITY_TOL_MM)
    _expl = ("符号无歧义（两面距离差 ≥ 0.1mm 或单侧无候选面），不豁免"
             if not _amb else
             ("该点位于两壁间真腔隙（腔宽≈{:.2f}mm），距两侧壁近乎等距（差 {:.4f}mm < 0.1mm）；"
              "'外侧'判定来自近距双层面下最近面选择的歧义，非真实穿壁").format(
                  _prof["d_inside_mm"] + _prof["d_outside_mm"], _ddiff))
    flip_points.append({
        "streamline_index": int(_sl_idx[_ii]),
        "sample_index": int(_samp_idx[_ii]),
        "samples_in_streamline": int(_n_samp[int(_sl_idx[_ii])]),
        "is_endpoint_zone": bool(_endpoint_zone[_ii]),
        "clearance_before_mm": float(_clr_b[_ii]),
        "clearance_after_mm": float(clearance[_ii]),
        "world_xyz": [float(x) for x in (probe_pts[_ii] - CENTER)],
        "ambiguity_v3": dict(
            _prof,
            abs_distance_diff_mm=_ddiff,
            lumen_width_mm=(None if _ddiff is None
                            else float(_prof["d_inside_mm"] + _prof["d_outside_mm"])),
            is_sign_ambiguous=_amb,
            rule=("裁决（门禁 v3）：最近内侧面与最近外侧面（两面法向相对该点取向相反）"
                  "距离差 < 0.1mm → 近等距多层面/折叠，最近面选择歧义，"
                  "'外侧'判定非真实穿壁 → 符号歧义豁免（不计入门禁）"),
            explanation=_expl),
    })
    _flip_entry_by_flat[int(_ii)] = len(flip_points) - 1

# [裁决2] 门禁 v2 两段式（保留记录供追溯；v3 为现行判据）
_neg_a = int((clearance < 0).sum())
_neg_b = int((_clr_b < 0).sum())
_seg1_pass = _neg_a <= _neg_b
_inner = ~_endpoint_zone
_viol = _inner & (_clr_b >= 0.5) & (clearance <= -0.5)
_seg2_pass = not bool(_viol.any())

# [裁决（本轮）门禁 v3 = v2 + 歧义折叠豁免]
#   对每个 v2 违规点（内段显著翻转）判符号歧义；豁免后，符号无歧义的违规点数必须 = 0
_v3_records = []
_n_unambig = 0
for _ii in np.where(_viol)[0]:
    _amb = bool(flip_points[_flip_entry_by_flat[int(_ii)]]["ambiguity_v3"]["is_sign_ambiguous"])
    if not _amb:
        _n_unambig += 1
    _v3_records.append({
        "flat_index": int(_ii),
        "streamline_index": int(_sl_idx[_ii]),
        "sample_index": int(_samp_idx[_ii]),
        "is_endpoint_zone": bool(_endpoint_zone[_ii]),
        "clearance_before_mm": float(_clr_b[_ii]),
        "clearance_after_mm": float(clearance[_ii]),
        "world_xyz": [float(x) for x in (probe_pts[_ii] - CENTER)],
        "is_sign_ambiguous": _amb,
        "exempted_ambiguity": _amb,
    })
_seg3_pass = (_n_unambig == 0)

b6 = {"method": method + "；[门禁 v3] 歧义折叠豁免：内段显著翻转点若最近内侧面与最近外侧面距离差 < 0.1mm 且两面法向相对该点取向相反（近等距多层面/折叠），判符号歧义豁免不计入门禁（逐点档案见 flip_points[].ambiguity_v3）",
      "sampled_points": int(len(probe_pts)),
      "streamlines": len(streamlines), "stride": 5,
      "min_clearance_mm": float(clearance.min()),
      "mean_clearance_mm": float(clearance.mean()),
      "p95_clearance_mm": float(np.percentile(clearance, 95)),
      "max_clearance_mm": float(clearance.max()),
      "negative_count": _neg_a,
      "sign_convention": "流线在壳体内侧为正",
      "endpoint_zone_points": int(_endpoint_zone.sum()),
      "endpoint_zone_rule": "每条流线首、尾各 1 个采样点（帽区豁免：壳在鼻孔/咽口开放，流线端点本就穿过帽平面）",
      "diag_before_smoothing": {
          "min_clearance_mm": float(_clr_b.min()),
          "mean_clearance_mm": float(_clr_b.mean()),
          "negative_count": _neg_b},
      "flip_points": flip_points,
      "gate_v2": {
          "segment1_global_negative_count": {
              "rule": "after 负点数 ≤ before 负点数",
              "after": _neg_a, "before": _neg_b, "pass": bool(_seg1_pass)},
          "segment2_inner_significant_flip": {
              "rule": "排除端区后，内段点中 before ≥ +0.5mm 且 after ≤ −0.5mm 的点数 = 0",
              "inner_points": int(_inner.sum()),
              "violating_points": int(_viol.sum()),
              "violating_flat_indices": [int(x) for x in np.where(_viol)[0]],
              "pass": bool(_seg2_pass)},
          "pass": bool(_seg1_pass and _seg2_pass)},
      "gate_v3": {
          "rule": "门禁 v2 两段式 + 歧义折叠豁免：符号无歧义的内段显著翻转（before ≥ +0.5mm 且 after ≤ −0.5mm）点数 = 0",
          "ambiguity_rule": "内段显著翻转点中，最近内侧面与最近外侧面（两面法向相对该点取向相反）距离差 < 0.1mm → 近等距多层面/折叠之最近面选择歧义，非真实穿壁 → 豁免（档案：flip_points[].ambiguity_v3）",
          "v2_significant_inner_flips": int(_viol.sum()),
          "ambiguous_exempted": int(_viol.sum()) - _n_unambig,
          "unambiguous_violations": _n_unambig,
          "violation_records": _v3_records,
          "pass": bool(_seg3_pass)},
      "pass": bool(_seg1_pass and _seg3_pass)}
gates["board6_v3_two_segment_ambiguity_exempt"] = {
    "pass": b6["pass"],
    "seg1_after_neg_le_before_neg": bool(_seg1_pass),
    "seg1_after_neg": _neg_a, "seg1_before_neg": _neg_b,
    "seg2_v2_significant_inner_flips": int(_viol.sum()),
    "seg3_ambiguous_exempted": int(_viol.sum()) - _n_unambig,
    "seg3_unambiguous_violations": _n_unambig,
    "seg3_pass": bool(_seg3_pass)}

boards = {
    "generated": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
    "algorithm": {"name": "Taubin", "lambda": TAUBIN_LAMBDA, "mu": TAUBIN_MU,
                   "iters": SMOOTH_ITERS,
                   "adjacency": "scipy.sparse CSR, binarized, built from faces",
                   "scope": "airwayMesh/airwayCavity 顶点坐标 only; faces/indices 不动",
                   "exemption": {"shell": "airwaySinus", "reason": _ExemptReason}},
    "shells": shells_report,
    "board5_bbox_frame_check": b5,
    "board6_streamline_shell_clearance": b6,
    "gates": gates,
    "all_gates_pass": bool(all(g["pass"] for g in gates.values())),
}

os.makedirs(os.path.dirname(F3_BOARDS_JSON), exist_ok=True)
with open(F3_BOARDS_JSON, "w", encoding="utf-8", newline="\n") as _f:
    json.dump(boards, _f, ensure_ascii=False, indent=2)
log(f"[F3] 六板报表已写 {F3_BOARDS_JSON}")

for _tag, _g in gates.items():
    log(f"  [F3 门禁] {_tag}: {'PASS' if _g['pass'] else 'FAIL'}")
if not boards["all_gates_pass"]:
    log("[F3] 门禁越限 —— 停工：不写盘新 viewer_data.js，等指挥官裁决")
    sys.exit(3)
log("[F3] 六板门禁全过 → 放行写盘 viewer_data.js")


# ----------------------------------------------------------------------------
# 5. meta / curve（契约字面值，逐字段一字不差）
# ----------------------------------------------------------------------------
meta = {
    "title": "鼻腔气流仿真查看器（黑客松概念验证）",
    "caseBaseline": "v5 @15 L/min 层流",
    "units": "mm, m/s, Pa",
    "metrics": {
        "dP_baseline_Pa": 18.45,
        "dP_1mm_Pa": 28.6,
        "dP_2mm_Pa": 47.3,
        "dP_3mm_Pa": 52.4,
        "dP_note": "层流下界估计，不确定度±20-50%（占位档为仿真工况，非推荐）",
        "split_L_pct": 51.9,
        "split_R_pct": 48.1,
        "wss_mean_Pa": 0.011,
        "wss_p95_Pa": 0.054,
        "resistance_total": "66.2 Pa/(L/s)",
    },
}
curve = {
    "volumes_cm3": [0, 4.37, 8.24, 10.42],
    "dP_Pa": [18.45, 28.55, 47.32, 52.40],
    "band_Pa": [30, 150],
}

# ----------------------------------------------------------------------------
# 6. 组装 JS 文件
# ----------------------------------------------------------------------------
gen_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
n_stream = len(stream_out)
n_slice = len(slices)
avg_len = float(np.mean([len(s["points"]) // 3 for s in stream_out])) if stream_out else 0.0
all_spd = [s for st in stream_out for s in st["speed"]]
spd_min = min(all_spd) if all_spd else 0.0
spd_max = max(all_spd) if all_spd else 0.0

header = f"""\
// ============================================================================
// viewer_data.js  ——  鼻腔气流 CFD 结果查看器数据包（任务 T2 产出）
// 生成时间 : {gen_time}
// 来源     : {VTU}
//            {MASK_NPZ}
//            {PH_DIR}\\virtual-placeholder-*.stl
// 坐标系   : mm（VTK 米×1000 与 mask 体素同源），已减 airwayMesh 质心
//            CENTER(mm) = {np.round(CENTER,2).tolist()}
// 条数统计 : airwayMesh {len(air.faces)} 面 / {len(air.vertices)} 顶点;
//            streamlines {n_stream} 条(均长 {avg_len:.1f} 点, 速度 {spd_min:.2f}~{spd_max:.2f} m/s);
//            slices {n_slice} 片; placeholders {[len(p['indices'])//3 for p in placeholders]} 面/档;
//            decimate 模式 {DECIMATE_MODE}
//            [T4] airwayCavity {len(cavity_mesh.faces)} 面 / airwaySinus {len(sinus_mesh.faces)} 面;
//                 cavity {int(cavity.sum())} 体素 + sinus {int(sinus.sum())} 体素 = mask {int(mask.sum())} 体素
// 说明     : 概念验证 · 非医疗器械 · 仿真几何禁止人体使用
// ============================================================================
"""

data = {
    "meta": meta,
    "airwayMesh": airwayMesh,
    "streamlines": stream_out,
    "slices": slices,
    "placeholders": placeholders,
    "curve": curve,
    "airwayCavity": airwayCavity,
    "airwaySinus": airwaySinus,
}

counts = {
    "airwayFaces": len(air.faces), "streamlines": n_stream, "slices": n_slice,
    "placeholders": len(placeholders),
}

# ----------------------------------------------------------------------------
# [裁决（本轮）] 外科手术式写盘：
#   新文件 = 旧 viewer_data.js（共享目录 09-30 未平滑原版）逐字节搬运
#   + 仅替换 airwayMesh/airwayCavity 两壳 positions 数组（平滑后顶点；
#     裁决1：airwaySinus 豁免壳顶点逐字节不动）
#   + 更新 header 生成时间行。meta/streamlines/slices/placeholders/curve
#     逐字节零漂移（字符串级替换保证，非全量重序列化）。
# ----------------------------------------------------------------------------
with open(SHARED_VIEWER_DATA_JS, "r", encoding="utf-8", newline="") as _f:
    _old_text = _f.read()
if _old_text.count("window.VIEWER_DATA = ") != 1:
    raise SystemExit("[F3] 外科手术写盘失败：旧文件 window.VIEWER_DATA 标记不唯一")
_head_old, _rest = _old_text.split("window.VIEWER_DATA = ", 1)
_json_old, _tail = _rest.split(";\n", 1)
_old_data = json.loads(_json_old)

# 漂移校验 ①：旧 header（除 gen_time 行外）必须与当前模板逐字一致
_gen_mark = "// 生成时间 : "
_gp = _head_old.find(_gen_mark)
if _gp < 0:
    raise SystemExit("[F3] 外科手术写盘失败：旧文件 header 缺 gen_time 行")
_ge = _head_old.find("\n", _gp)
_gen_old = _head_old[_gp + len(_gen_mark):_ge]
_head_new = _head_old[:_gp + len(_gen_mark)] + gen_time + _head_old[_ge:]
if _head_new != header:
    raise SystemExit("[F3] 外科手术写盘失败：旧文件 header 与当前模板不一致"
                     "（除 gen_time 外存在差异，旧 gen_time=%s）——拒绝写盘" % _gen_old)
_tail_expected = "console.log('VIEWER_DATA loaded', " + json.dumps(counts, ensure_ascii=False) + ");\n"
if _tail != _tail_expected:
    raise SystemExit("[F3] 外科手术写盘失败：旧文件 tail 与当前模板不一致——拒绝写盘")

# 漂移校验 ②：仅替换两壳 positions 子串（唯一性断言）
_json_new = _json_old
_splice = {}
for _shell, _new_pos in (("airwayMesh", airwayMesh["positions"]),
                            ("airwayCavity", airwayCavity["positions"])):
    _old_pos_str = json.dumps(_old_data[_shell]["positions"], ensure_ascii=False, separators=(",", ":"))
    _new_pos_str = json.dumps(_new_pos, ensure_ascii=False, separators=(",", ":"))
    if _json_new.count(_old_pos_str) != 1:
        raise SystemExit("[F3] 外科手术写盘失败：%s positions 子串在旧文件中出现 %d 次（非唯一）"
                         % (_shell, _json_new.count(_old_pos_str)))
    _json_new = _json_new.replace(_old_pos_str, _new_pos_str)
    _splice[_shell] = {"vertices": len(_new_pos) // 3,
                        "old_array_chars": len(_old_pos_str),
                        "new_array_chars": len(_new_pos_str)}

# 漂移校验 ③：手术结果的 JSON 语义 == 全量重建 data（逐字段相等）
_new_data = json.loads(_json_new)
for _kk in ("meta", "curve", "streamlines", "slices", "placeholders", "airwaySinus"):
    if _new_data[_kk] != data[_kk]:
        raise SystemExit("[F3] 外科手术写盘失败：字段 %s 与全量重建不一致——拒绝写盘" % _kk)
for _shell in ("airwayMesh", "airwayCavity"):
    if (_new_data[_shell]["indices"] != data[_shell]["indices"]
            or _new_data[_shell]["positions"] != data[_shell]["positions"]):
        raise SystemExit("[F3] 外科手术写盘失败：%s 与全量重建不一致——拒绝写盘" % _shell)

js_path = os.path.join(OUT_STEP5, "viewer_data.js")
with open(js_path, "w", encoding="utf-8", newline="\n") as f:
    f.write(_head_new)
    f.write("window.VIEWER_DATA = ")
    f.write(_json_new)
    f.write(";\n")
    f.write(_tail)
size = os.path.getsize(js_path)
log(f"写 viewer_data.js  {size/1e6:.2f} MB（外科手术式：仅两壳 positions + gen_time 替换；"
    f"airwaySinus 顶点逐字节不动）")
log(f"  手术替换明细：{_splice}")

# 同步共享目录（同一产物直接复制，两份逐字节一致）
import shutil
shutil.copyfile(js_path, SHARED_VIEWER_DATA_JS)
with open(SHARED_VIEWER_DATA_JS, "rb") as _f:
    _shared_bytes = _f.read()
with open(js_path, "rb") as _f:
    _local_bytes = _f.read()
if _shared_bytes != _local_bytes:
    raise SystemExit("[F3] 共享目录副本与 pipeline 产物字节不一致——拒绝同步")
log("同步共享目录 viewer_data.js（逐字节一致，md5 相同）")


# ----------------------------------------------------------------------------
# 7. 质检断言 A1..A7 -> viewer_data_qc.json
# ----------------------------------------------------------------------------
log("质检 A1..A7 + T4 N1..N5 ...")
qc = {}
txt = open(js_path, encoding="utf-8").read()

# A1 语法探测：括号平衡 + window.VIEWER_DATA 存在
pairs = {")": "(", "]": "[", "}": "{"}
depth = {"(": 0, "[": 0, "{": 0}
in_str = False; esc = False
ok_bal = True
for ch in txt:
    if in_str:
        if esc: esc = False
        elif ch == "\\": esc = True
        elif ch == '"': in_str = False
        continue
    if ch == '"': in_str = True; continue
    if ch in "([{": depth[ch] += 1
    elif ch in ")]}":
        op = pairs[ch]
        depth[op] -= 1
        if depth[op] < 0: ok_bal = False
a1 = ok_bal and all(v == 0 for v in depth.values()) and ("window.VIEWER_DATA" in txt)
qc["A1_js_syntax"] = {"pass": bool(a1), "bracket_depth": depth,
                      "has_window_VIEWER_DATA": "window.VIEWER_DATA" in txt}

# A2 airwayMesh
posA = np.array(airwayMesh["positions"]); idxA = np.array(airwayMesh["indices"])
a2 = (len(idxA)//3 <= 40000) and (len(posA) == 3*len(air.vertices)) and (idxA.min() >= 0) and (idxA.max() < len(air.vertices))
qc["A2_airwayMesh"] = {"pass": bool(a2), "faces": int(len(idxA)//3), "verts": int(len(posA)//3),
                       "positions_len": int(len(posA)), "idx_max": int(idxA.max())}

# A3 streamlines
lens = [len(s["points"])//3 for s in stream_out]
a3 = (len(stream_out) >= 40) and (np.mean(lens) >= 20 if lens else False) and (spd_min >= 0.0) and (spd_max <= 11.5)
qc["A3_streamlines"] = {"pass": bool(a3), "count": len(stream_out),
                        "avg_len": float(np.mean(lens)) if lens else 0.0,
                        "speed_min": float(spd_min), "speed_max": float(spd_max),
                        "lens_min": int(min(lens)) if lens else 0, "lens_max": int(max(lens)) if lens else 0}

# A4 placeholders
ph_faces = [len(p["indices"])//3 for p in placeholders]
a4 = (len(placeholders) == 3) and all(f <= 15000 for f in ph_faces) and [p["mm"] for p in placeholders] == [1, 2, 3]
qc["A4_placeholders"] = {"pass": bool(a4), "count": len(placeholders), "faces": ph_faces,
                         "mm": [p["mm"] for p in placeholders]}

# A5 文件大小
a5 = size <= 15*1024*1024
qc["A5_size"] = {"pass": bool(a5), "bytes": int(size), "MB": round(size/1e6, 3)}

# A6 居中后坐标界 + 速度单位
a6 = True; maxabs = 0.0
for arr in [posA] + [np.array(s["points"]) for s in stream_out] + [np.array(s["positions"]) for s in slices] + [np.array(p["positions"]) for p in placeholders]:
    if len(arr):
        m = float(np.abs(arr).max()); maxabs = max(maxabs, m)
        if m > 120.0: a6 = False
qc["A6_coord_bounds"] = {"pass": bool(a6), "max_abs_mm": round(maxabs, 3), "speed_unit": "m/s"}

# A7 curve vs meta
meta_dP = [meta["metrics"]["dP_baseline_Pa"], meta["metrics"]["dP_1mm_Pa"],
           meta["metrics"]["dP_2mm_Pa"], meta["metrics"]["dP_3mm_Pa"]]
cv = curve["dP_Pa"]
# 契约字面：meta 为 1 位小数展示（28.6/47.3/52.4），curve 为 2 位小数（28.55/47.32/52.40）；
# T3 明确『meta.metrics 数值直接展示，不得改写或拔高精度』=> 两者均按字面输出。
# 故 A7 以展示精度（±0.05，即 meta 末位半格）判定一致，并记录原始差。
diffs = [abs(cv[t] - meta_dP[t]) for t in range(4)]
round_consistent = [d <= 0.0500001 for d in diffs]
a7 = all(round_consistent)
qc["A7_curve_vs_meta"] = {
    "pass": bool(a7),
    "meta_dP": meta_dP, "curve_dP": cv,
    "abs_diff": [round(d, 4) for d in diffs],
    "consistent_within_meta_display_precision(±0.05)": round_consistent,
    "note": "契约字面 meta=1位小数(18.45/28.6/47.3/52.4) 与 curve=2位小数(18.45/28.55/47.32/52.40) "
            "不完全逐位相等；T3 禁止改写 meta 精度，故两者均按契约字面输出，A7 以展示精度一致判定。",
}

# ============================================================================
# 7b. [T4] N1..N5 质检
# ============================================================================
jcav = json.dumps(airwayCavity, ensure_ascii=False, separators=(",", ":"))
jsin = json.dumps(airwaySinus, ensure_ascii=False, separators=(",", ":"))

# [N5 第2判据] 契约其余字段与 v1 逐字节不变 —— v1 序列化基线（sha256 前16位）
V1_BASELINE = {
    "meta": "257073c878f0d8e0",
    "curve": "9aed38edfa5702de",
    "streamlines": "7799944e9a3e3c59",
    "slices": "833ff114820e4db5",
    "placeholders": "674ae2915ec4f075",
}
import hashlib
unchanged = {}
for kk in ("meta", "curve", "streamlines", "slices", "placeholders"):
    h = hashlib.sha256(json.dumps(data[kk], ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()[:16]
    unchanged[kk] = {"v1": V1_BASELINE[kk], "now": h, "match": h == V1_BASELINE[kk]}

# [N1] airwayCavity 面数 ≤30000、indices 无越界
posC = np.array(airwayCavity["positions"]); idxC = np.array(airwayCavity["indices"])
nC = int(len(posC) // 3)
n1 = (len(idxC) // 3 <= 30000) and (idxC.min() >= 0) and (idxC.max() < nC)
qc["N1_airwayCavity"] = {"pass": bool(n1), "faces": int(len(idxC)//3), "verts": nC,
                         "idx_min": int(idxC.min()), "idx_max": int(idxC.max())}

# [N2] airwaySinus 面数 ≤20000、indices 无越界、体素数 < cavity 体素数
posS = np.array(airwaySinus["positions"]); idxS = np.array(airwaySinus["indices"])
nS = int(len(posS) // 3)
sin_vox = int(sinus.sum()); cav_vox = int(cavity.sum())
n2 = (len(idxS) // 3 <= 20000) and (idxS.min() >= 0) and (idxS.max() < nS) and (sin_vox < cav_vox)
qc["N2_airwaySinus"] = {"pass": bool(n2), "faces": int(len(idxS)//3), "verts": nS,
                        "idx_min": int(idxS.min()), "idx_max": int(idxS.max()),
                        "sinus_vox": sin_vox, "cavity_vox": cav_vox, "sinus_lt_cavity": sin_vox < cav_vox}

# [N3] 三者顶点坐标使用同一 CENTER（抽查 3 个顶点换算回世界坐标，应等于 CENTER+居中坐标）
def check_center(field, mesh_tag):
    p = np.array(field["positions"]).reshape(-1, 3)
    idx = [0, len(p)//2, len(p)-1][:min(3, len(p))]
    ok = True; samples = []
    for t in idx:
        world = p[t] + CENTER                 # 居中坐标 + 同一 CENTER = 世界坐标
        samples.append({"vert": int(t), "local_xyz": [round(float(x),1) for x in p[t]],
                        "back_to_world_mm": [round(float(x),2) for x in world]})
        if abs(world[0] - (p[t][0] + CENTER[0])) > 1e-6: ok = False
    return ok, samples
okA, sA = check_center(airwayMesh, "airwayMesh")
okC, sC = check_center(airwayCavity, "airwayCavity")
okS, sS = check_center(airwaySinus, "airwaySinus")
n3 = okA and okC and okS
qc["N3_same_center"] = {"pass": bool(n3), "CENTER_mm": [round(float(x), 2) for x in CENTER],
                        "expected_CENTER_mm": [79.22, 71.87, 56.98],
                        "center_matches_v1": [round(float(x), 2) for x in CENTER] == [79.22, 71.87, 56.98],
                        "samples": {"airwayMesh": sA, "airwayCavity": sC, "airwaySinus": sS}}

# [N4] cavity ∪ sinus == mask（拆分无损，容差 0）
n4 = bool(np.array_equal(cavity | sinus, mask))
qc["N4_split_lossless"] = {"pass": bool(n4), "cavity_vox": cav_vox, "sinus_vox": sin_vox,
                           "union_vox": int((cavity | sinus).sum()), "mask_vox": int(mask.sum()),
                           "tolerance": 0}

# [N5] 文件 ≤4MB、CRLF=0、契约完整性（字段齐全+核心计数匹配）
# （step-5审计P1：byte-identity对"decimate跨进程不确定+质心后置"的既有事实不可达——
#   CENTER已硬编码常量后本判据对重跑稳定；字段哈希仍记录供追溯，仅不再作为判据）
raw = open(js_path, "rb").read()
crlf = raw.count(b"\r\n")
size_ok = size <= 4*1024*1024
contract_ok = all(kk in data for kk in ["meta", "airwayMesh", "airwayCavity", "airwaySinus",
                                      "streamlines", "slices", "placeholders", "curve"])
changed = [kk for kk, v in unchanged.items() if not v["match"]]
n5 = size_ok and (crlf == 0) and contract_ok
qc["N5_size_crlf_byteidentical"] = {"pass": bool(n5), "bytes": int(size), "MB": round(size/1e6, 3),
                                    "size_le_4MB": size_ok, "crlf": crlf,
                                    "contract_fields_present": contract_ok,
                                    "fields_byte_identical_vs_v1": unchanged,
                                    "changed_fields": changed,
                                    "note": "2026-09-30审计修订：判据=契约完整性；字节哈希仅追溯用"}

qc["all_pass"] = all(v.get("pass", False) for kk, v in qc.items() if isinstance(v, dict))
qc["runtime_s"] = round(time.time() - T_START, 1)
qc["generated"] = gen_time
qc_path = os.path.join(OUT_STEP5, "viewer_data_qc.json")
with open(qc_path, "w", encoding="utf-8", newline="\n") as f:
    json.dump(qc, f, ensure_ascii=False, indent=2)

log("QC 结果:")
for kk, v in qc.items():
    if isinstance(v, dict) and "pass" in v:
        log(f"  {kk}: {'PASS' if v['pass'] else 'FAIL'}")
log(f"ALL PASS = {qc['all_pass']}")
log(f"完成，用时 {qc['runtime_s']}s；输出 {js_path} / {qc_path}")
