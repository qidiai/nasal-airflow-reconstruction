# -*- coding: utf-8 -*-
"""
P0 阶段2 v2：OpenFOAM 算例包生成器（体素六面体网格直出）
修正：边界面朝向/邻居索引/owner直取；header去横幅避免转义问题
台式机产出 -> 共享文件夹 -> 笔记本WSL运行 -> 结果拷回
"""
import os, json, glob, argparse
import numpy as np
import pydicom
from scipy import ndimage

# T11 补丁（k3 终审方案 A·执行序 3）：命令行参数化。默认参数 = v5 冻结基线（逐字节等价）；
# --ext  开入口/出口圆柱延长段（v5E-ext，§5.3 预处理口径，默认关，本批开）；
# --iso  去窦对照算例（v5E-iso，与 step3_make_narrowing.py §2 同法，默认关）。
_ap = argparse.ArgumentParser(description="P0 阶段2 OpenFOAM 算例包生成器（体素六面体直出）")
_ap.add_argument("--case", default="v5", help="算例名（默认 v5=冻结基线；本批 v5E-ext/v5E-iso；禁 v6）")
_ap.add_argument("--ext", action="store_true", help="入口鼻孔+出口鼻咽圆柱延长段（默认关）")
_ap.add_argument("--ext-l-mm", type=float, default=15.0, help="延长段长度 mm（默认 15.0，§5.3）")
_ap.add_argument("--ext-r-factor", type=float, default=1.05, help="延长段半径=开口外接圆半径×系数（默认 1.05）")
_ap.add_argument("--iso", action="store_true", help="去窦对照算例（默认关）")
ARGS = _ap.parse_args()

# T11 开源脱敏：CT 数据目录由环境变量 P0_DICOM_DIR 指定（默认相对路径 ./dicom）
DATA_DIR = os.environ.get("P0_DICOM_DIR", "./dicom")
WS_OUT = r"%QIDI_WORKSPACE%\contest3_workspace\pipeline\out"
CASE_DIR = os.path.join(WS_OUT, "step2", f"P0-OF-case-pA-{ARGS.case}")
MESH_DIR = os.path.join(CASE_DIR, "constant", "polyMesh")
os.makedirs(MESH_DIR, exist_ok=True)
os.makedirs(os.path.join(CASE_DIR, "0"), exist_ok=True)
os.makedirs(os.path.join(CASE_DIR, "system"), exist_ok=True)

Q_TOTAL = 15.0 / 60000.0      # 15 L/min -> m3/s
NU_AIR = 1.80e-05             # 审计Y2：气道内空气~35C 的运动粘度 m2/s（1.48e-5对应15C，压降会低估22%）

# ========== 1. 分割 ==========
print("[1/6] 读 DICOM 分割 ...")
files = sorted(glob.glob(os.path.join(DATA_DIR, "*.dcm")))
slices = [pydicom.dcmread(f) for f in files]
slices.sort(key=lambda s: float(s.ImagePositionPatient[2]))
nz, rows, cols = len(slices), slices[0].Rows, slices[0].Columns
ps = [float(x) for x in slices[0].PixelSpacing]
dz = abs(float(slices[1].ImagePositionPatient[2]) - float(slices[0].ImagePositionPatient[2]))
vol = np.zeros((nz, rows, cols), dtype=np.int16)
for i, s in enumerate(slices):
    vol[i] = s.pixel_array.astype(np.int16) * int(s.RescaleSlope) + int(s.RescaleIntercept)
head = vol > -300
head_int = np.zeros_like(head)
for i in range(nz):
    head_int[i] = ndimage.binary_fill_holes(head[i])
air = vol < -400
airway_all = air & head_int
lab, n = ndimage.label(airway_all, structure=ndimage.generate_binary_structure(3, 1))
sizes = np.bincount(lab.ravel())
main_lab = int(np.argmax(sizes[1:]) + 1)
mask = lab == main_lab
cut = air & ~head_int
xs_all = np.arange(cols)
head_cols = head.sum(axis=(0, 1))          # (nz,rows,cols) -> 对 z 和 rows 求和 => 每列(cols=x)
head_cx = float((head_cols * xs_all).sum() / head.sum())
print(f"    气道 {mask.sum()/1e6:.2f}M 体素, 头外空气 {cut.sum()/1e6:.2f}M, 头中线 x={head_cx:.0f}")
np.savez_compressed(os.path.join(WS_OUT, "step2",
    "mask_full.npz" if ARGS.case == "v5" else f"mask_full-{ARGS.case}.npz"), mask=mask, cut=cut)

# T11 补丁（--iso，v5E-iso）：去窦对照——与 step3_make_narrowing.py §2 同法
# （全分辨率：面邻接结构元腐蚀 3 次→最大连通域→膨胀 3 次&原掩码），剔除鼻窦旁气腔，
# 只留鼻腔本体（鼻窦经狭窄窦口相接，全分辨率腐蚀 3 次即断离）。
# ★ 结构元须为 generate_binary_structure(3,1)：立方体 np.ones((3,3,3)) 26 邻接过激，
#   T11 首跑实证——腐蚀后仅 0.34M 体素、鼻孔开口全失（inlet=0 触发中止）
if ARGS.iso:
    st = ndimage.generate_binary_structure(3, 1)   # ★ §2 原文：面邻接结构元（立方体 26 邻接过激，T11 首跑实证）
    eroded = ndimage.binary_erosion(mask, structure=st, iterations=3)
    lab_i, n_i = ndimage.label(eroded)
    sizes_i = np.bincount(lab_i.ravel())
    keep_i = int(np.argmax(sizes_i[1:])) + 1
    mask = ndimage.binary_dilation(lab_i == keep_i, iterations=3) & mask
    print(f"    去窦对照（v5E-iso，全分辨率 §2 同法）: 腐蚀3→最大连通域→膨胀3&掩码, 剩余 {int(mask.sum())/1e6:.2f}M 体素")

# ========== 2. 降采样 2x ==========
print("[2/6] 2x 降采样（多数表决防几何膨胀，审计Y1）...")
def ds2(a):
    k, j, i = a.shape
    k2, j2, i2 = k // 2, j // 2, i // 2
    blk = a[:k2*2, :j2*2, :i2*2].astype(np.uint8).reshape(k2, 2, j2, 2, i2, 2)
    return blk.sum(axis=(1, 3, 5)) >= 4        # >=4/8 多数表决，无系统偏置
m, c = ds2(mask), ds2(cut)
# ★ 连通域过滤（笔记本缺陷6：多数表决降采样会产生孤立体素，导致p矩阵奇异→GAMG除零崩溃）
lab_m, n_m = ndimage.label(m, structure=ndimage.generate_binary_structure(3, 1))
if n_m > 1:
    sizes_m = np.bincount(lab_m.ravel())
    keep = int(np.argmax(sizes_m[1:]) + 1)
    removed = n_m - 1
    m = lab_m == keep
    print(f"    连通域过滤: 删除 {removed} 个孤立组件（孤立体素会致求解奇异）")
else:
    print("    连通域过滤: 单一连通域，无需清理")
K, J, I = m.shape
dx, dy, dzz = ps[1] * 2 / 1000.0, ps[0] * 2 / 1000.0, dz * 2 / 1000.0
ncells = int(m.sum())
# 回归校验：多数表决后体积应接近原始掩码（±5%），显著偏大=膨胀未除
vol_ds_cm3 = ncells * dx * dy * dzz * 1e6
vol_mask_cm3 = mask.sum() * ps[0] * ps[1] * dz / 1000
ratio_v = vol_ds_cm3 / vol_mask_cm3
print(f"    网格 {m.shape}, 单元 {ncells/1e3:.0f}k, 体素 {dx*1e3:.3f}x{dy*1e3:.3f}x{dzz*1e3:.3f} mm")
print(f"    体积回归校验: 降采样后 {vol_ds_cm3:.1f} cm3 vs 原掩码 {vol_mask_cm3:.1f} cm3 (比值 {ratio_v:.3f})")
if ratio_v > 1.06 or ratio_v < 0.94:
    print("    !!! 体积回归超限，需人工检查 !!!")

# ---- T11 补丁（k3 终审方案 A·执行序 3）：入口/出口圆柱延长段（v5E-ext，§5.3 预处理口径）----
# 设计：入口双侧鼻孔开口各接一段虚拟圆柱流体区（轴向=开口质心−掩码质心归一化，
#       半径=开口外接圆半径×系数 --ext-r-factor，长度 --ext-l-mm 默认 15mm）；
#       出口鼻咽截断面（k_min 层）向下接一段（轴向 (0,0,-1)），触及 CT 底面时零填充。
# 判定规则（§5.3"延长段体素的面，法向·圆柱轴定端口/侧壁"的体素化实现）：体素化斜圆柱的
#       阶梯侧面法向与轴点积可 ≥0.5（单纯点积阈值会把阶梯侧壁误判为端口），故以
#       "端口层（轴向坐标 t ≥ L-1.5×体素长）且法向·轴>0.2" 判端口：
#       入口圆柱端口→inlet，出口圆柱端口→outlet，其余延长段面→walls。
# 覆盖验证循环：残留开口面=0、鼻咽底面覆盖完整、三段端口皆有暴露端口面（≥5 面/段）
#       才提交；否则半径系数×1.3 重试（≤6 次）。
extm = np.zeros_like(m)
ext_kind = np.zeros(m.shape, dtype=np.uint8)   # 0=非延长段 1=侧壁层 2=入口端口层 3=出口端口层
ext_axis = np.zeros((3,) + m.shape, dtype=np.float32)
ext_cylinders = None
pad_k_ext = 0                                  # 零填充层数（v5E-ext；0=无延长段/默认路径）
if ARGS.ext:
    def _boundary_open_cells(mm, cc):
        """开口面体素（与 §3 严格同口径）：掩码体素 mm 的 ±axis 侧邻居
        同时满足"空(~mm)"与"头外空气(cc)"者——与 v5 分类
        `ok = m & ~m_nb; 再查 c[nb]` 完全一致。
        注意：ds2 多数表决后 m 与 c 可在 4/4 块重叠（一块 8 体素恰
        4:4 分属气道/头外空气），单纯 mm&cc 会多计（诊断实测每分支
        ~180 面），故必须带 ~mm 邻居条件。
        返回 (N,3)，列=(k,j,i)，即 owner 体素索引。"""
        outs = []
        for axis in (0, 1, 2):
            for sgn in (+1, -1):
                if sgn == +1:
                    if axis == 0:
                        ok = mm[:, :, :-1] & ~mm[:, :, 1:] & cc[:, :, 1:]
                    elif axis == 1:
                        ok = mm[:, :-1, :] & ~mm[:, 1:, :] & cc[:, 1:, :]
                    else:
                        ok = mm[:-1, :, :] & ~mm[1:, :, :] & cc[1:, :, :]
                    o = np.argwhere(ok)
                else:
                    if axis == 0:
                        ok = mm[:, :, 1:] & ~mm[:, :, :-1] & cc[:, :, :-1]
                    elif axis == 1:
                        ok = mm[:, 1:, :] & ~mm[:, :-1, :] & cc[:, :-1, :]
                    else:
                        ok = mm[1:, :, :] & ~mm[:-1, :, :] & cc[:-1, :, :]
                    o = np.argwhere(ok)
                    o[:, 2 - axis] += 1
                outs.append(o)
        if not outs:
            return np.zeros((0, 3), dtype=np.intp)
        return np.concatenate(outs)

    def _build_cyl(shape, p0, a, r, L, pad_k=0):
        """体素圆柱：起端 p0(mm)，轴向 a(单位向量,mm)，半径 r(mm)，长度 L(mm)。
        pad_k=零填充层数（数组底面下移 pad_k 层；物理坐标→填充后索引需 +pad_k 偏移，
        位置反算需 (ks-pad_k) 还原，否则圆柱整体错位到填充空区——T11 诊断实证）。
        返回 (sl, sub, t)：sl=(slice_k,slice_j,slice_i)，sub=bool 子数组，
        t=子数组各体素轴向坐标 mm（非圆柱体素处为 -1）。"""
        K_, J_, I_ = shape
        end = p0 + a * L
        lo = np.minimum(p0, end) - r
        hi = np.maximum(p0, end) + r
        off = np.array([0, 0, pad_k])                                # 填充偏移（仅 z 索引）
        lo_v = np.floor(lo / np.array([dx, dy, dzz])).astype(int) + off   # (i,j,k) 体素索引下界
        hi_v = np.ceil(hi / np.array([dx, dy, dzz])).astype(int) + off
        i_lo, j_lo, k_lo = np.clip(lo_v, [0, 0, 0], [I_ - 1, J_ - 1, K_ - 1])
        i_hi, j_hi, k_hi = np.clip(hi_v, [0, 0, 0], [I_ - 1, J_ - 1, K_ - 1])
        if i_hi < i_lo or j_hi < j_lo or k_hi < k_lo:
            return None
        ks, js, isx = np.mgrid[k_lo:k_hi + 1, j_lo:j_hi + 1, i_lo:i_hi + 1]
        p = np.stack([isx * dx, js * dy, (ks - pad_k) * dzz], axis=0).astype(np.float64)  # (3,x,y,z)mm
        rel = p - p0[:, None, None, None]
        t = rel[0] * a[0] + rel[1] * a[1] + rel[2] * a[2]
        rad2 = np.sum(rel * rel, axis=0) - t * t
        sub = (t >= -1e-9) & (t <= L + 1e-9) & (rad2 <= r * r + 1e-9)
        t = np.where(sub, t, -1.0)
        return (slice(k_lo, k_hi + 1), slice(j_lo, j_hi + 1), slice(i_lo, i_hi + 1)), sub, t

    DMAX = max(dx, dy, dzz)
    mctr = np.array([dx * np.argwhere(m)[:, 2].mean(),
                     dy * np.argwhere(m)[:, 1].mean(),
                     dzz * np.argwhere(m)[:, 0].mean()])
    k_min_orig = int(np.argmax(m.any(axis=(1, 2))))
    open_cells = _boundary_open_cells(m, c)
    open_cells = open_cells[open_cells[:, 0] > k_min_orig + 5]    # 排除鼻咽底面附近体素
    if len(open_cells) == 0:
        raise SystemExit("!!! 延长段：未找到鼻孔开口体素（k>k_min+5），中止 !!!")
    cxs = open_cells[:, 2].astype(float)
    ux = np.unique(np.round(cxs))
    gaps = np.diff(ux)
    if len(ux) > 1 and gaps.max() >= 3.0:
        gi = int(np.argmax(gaps))
        split_i_ext = (ux[gi] + ux[gi + 1]) / 2.0
        print(f"    延长段·鼻中隔间隙: x体素 {ux[gi]:.0f}|{ux[gi+1]:.0f} 之间 {gaps.max():.0f} 体素 -> 分割 i={split_i_ext:.1f}")
    else:
        split_i_ext = float(int(round(head_cx / 2.0)))
        print(f"    延长段·未找到鼻中隔间隙，回退头部中线 i={split_i_ext:.1f}")
    nostrils = []
    for side_name, keep in (("inletL", open_cells[:, 2] < split_i_ext),
                            ("inletR", open_cells[:, 2] >= split_i_ext)):
        cells = open_cells[keep]
        if len(cells) == 0:
            raise SystemExit(f"!!! 延长段：{side_name} 侧开口体素为空，中止 !!!")
        pts_mm = np.stack([cells[:, 2] * dx, cells[:, 1] * dy, cells[:, 0] * dzz], axis=1)
        ctr = pts_mm.mean(axis=0)
        a = ctr - mctr
        a = a / np.linalg.norm(a)
        rel = pts_mm - ctr
        rad_ip = np.sqrt(np.maximum(0.0, np.sum(rel * rel, axis=1) - (rel @ a) ** 2))
        nostrils.append(dict(name=side_name, ctr=ctr, axis=a, r_open=float(rad_ip.max())))
        print(f"    延长段·{side_name}: 开口 {len(cells)} 体素, 外接圆半径 {nostrils[-1]['r_open']*1e3:.2f} mm, 轴向 ({a[0]:.3f},{a[1]:.3f},{a[2]:.3f})")
    oi = np.argwhere(m[k_min_orig])                                # (N,2)=(j,i)
    pts_o = np.stack([oi[:, 1] * dx, oi[:, 0] * dy, np.full(len(oi), k_min_orig * dzz)], axis=1)
    ctr_o = pts_o.mean(axis=0)
    a_o = np.array([0.0, 0.0, -1.0])
    rel_o = pts_o - ctr_o
    r_open_o = float(np.sqrt(np.sum(rel_o * rel_o, axis=1)).max())
    print(f"    延长段·outlet: 鼻咽底面 {len(oi)} 体素, 外接圆半径 {r_open_o*1e3:.2f} mm, 轴向 (0,0,-1)")
    # 出口圆柱可能向下越出 CT 底面 → 按最大可能半径（6 次重试上限）预估零填充层数
    factor_max = float(ARGS.ext_r_factor) * (1.3 ** 5)
    need_max = (ARGS.ext_l_mm / 1000.0 + r_open_o * factor_max) - ctr_o[2]
    pad_k = int(np.ceil(max(0.0, need_max) / dzz)) + 1 if need_max > 0 else 0
    if pad_k > 0:
        m = np.pad(m, ((pad_k, 0), (0, 0), (0, 0)), constant_values=False)
        c = np.pad(c, ((pad_k, 0), (0, 0), (0, 0)), constant_values=False)
        extm = np.zeros_like(m)
        ext_kind = np.zeros(m.shape, dtype=np.uint8)
        ext_axis = np.zeros((3,) + m.shape, dtype=np.float32)
        print(f"    延长段·出口圆柱向下越出 CT 底面 -> 零填充 {pad_k} 层（数组底面下移 {-pad_k*dzz*1e3:.1f} mm）")
    m_orig = m.copy()                                               # 填充后原掩码（索引与 m2 同坐标系）
    k_min_p = k_min_orig + pad_k                                   # 填充后原鼻咽底面层索引
    factor = float(ARGS.ext_r_factor)
    committed = False
    diag = None
    for attempt in range(6):
        extm[:] = False
        ext_kind[:] = 0
        ext_axis[:] = 0.0
        cyls_info = []
        specs = [(nostrils[0], 2), (nostrils[1], 2),
                 (dict(name="outlet", ctr=ctr_o, axis=a_o, r_open=r_open_o), 3)]
        for spec, kind_port in specs:
            r = spec["r_open"] * factor
            p0 = spec["ctr"] - spec["axis"] * r                    # 起端=开口后方一个半径（吞没开口缘）
            L = ARGS.ext_l_mm / 1000.0 + r                         # 脚本长度单位=mm/1000（与 dx 同量纲）
            built = _build_cyl(m.shape, p0, spec["axis"], r, L, pad_k)
            if built is None:
                continue
            (sk, sj, si), sub, t = built
            extm[sk, sj, si] |= sub
            ea = ext_axis[:, sk, sj, si]
            ext_axis[:, sk, sj, si] = np.where(np.broadcast_to(sub, (3,) + sub.shape),
                                               spec["axis"].reshape(3, 1, 1, 1), ea)
            port_layer = sub & (t >= L - 1.5 * DMAX)
            ev = ext_kind[sk, sj, si]
            ev[port_layer] = kind_port
            ev[sub & ~port_layer] = 1
            cyls_info.append(dict(name=spec["name"],
                                  start_mm=[round(float(x) * 1e3, 2) for x in p0],
                                  axis=[round(float(x), 3) for x in spec["axis"]],
                                  radius_mm=round(r * 1e3, 2), length_mm=round(L * 1e3, 2)))
        m2 = m | extm
        # ① 残留开口：原始鼻孔开口体素在扩展域中仍邻接 cut 者须为 0
        open2 = _boundary_open_cells(m2, c)
        open2 = open2[open2[:, 0] > k_min_p + 5]
        n_resid = int(np.count_nonzero(m_orig[open2[:, 0], open2[:, 1], open2[:, 2]]))
        # ② 鼻咽底面覆盖：原底面体素的 -z 邻居须在扩展域内
        bot = np.argwhere(m_orig[k_min_p])
        n_uncovered = int(len(bot) - np.count_nonzero(m2[k_min_p - 1, bot[:, 0], bot[:, 1]]))
        # ③ 端口暴露面：端口层体素的法向·轴>0.2 面，其邻居不在扩展域内（含数组界外）
        capL = capR = capO = 0
        for (k1, j1, i1) in np.argwhere(ext_kind >= 2):
            av = ext_axis[:, k1, j1, i1].astype(np.float64)
            for axis in (0, 1, 2):
                for sgn in (+1, -1):
                    nrm = np.zeros(3)
                    nrm[axis] = sgn
                    if np.dot(nrm, av) <= 0.2:
                        continue
                    nk = k1 + (sgn if axis == 2 else 0)
                    nj = j1 + (sgn if axis == 1 else 0)
                    ni = i1 + (sgn if axis == 0 else 0)
                    if (0 <= nk < m2.shape[0] and 0 <= nj < m2.shape[1]
                            and 0 <= ni < m2.shape[2] and m2[nk, nj, ni]):
                        continue
                    if ext_kind[k1, j1, i1] == 3:
                        capO += 1
                    elif i1 < split_i_ext:
                        capL += 1
                    else:
                        capR += 1
        diag = dict(attempt=attempt + 1, factor=round(factor, 3), residual_open=n_resid,
                    bottom_uncovered=n_uncovered, port_faces_L=capL, port_faces_R=capR, port_faces_O=capO)
        print(f"    延长段·覆盖验证 第{attempt+1}次: 残留开口 {n_resid}, 底面未盖 {n_uncovered}, 端口面 L/R/O={capL}/{capR}/{capO}")
        if n_resid == 0 and n_uncovered == 0 and capL >= 5 and capR >= 5 and capO >= 5:
            committed = True
            m = m2
            ext_cylinders = cyls_info
            pad_k_ext = pad_k                    # 提交时记录填充层数（网格 z 坐标还原 CT 帧用）
            break
        factor *= 1.3
    if not committed:
        raise SystemExit(f"!!! 延长段覆盖验证 6 次尝试未通过（末次诊断 {diag}），中止 !!!")
    print(f"    延长段提交: 延长段体素 {int(extm.sum())/1e3:.0f}k, 扩展域总体素 {int(m.sum())/1e3:.0f}k")
    K, J, I = m.shape
    ncells = int(m.sum())

ids = np.full(m.shape, -1, dtype=np.int32)
ids[m] = np.arange(ncells, dtype=np.int32)

# ========== 3. 面 ==========
print("[3/6] 构面 ...")
def quad_pts(i0, j0, k0, axis, sgn):
    """单元(i0,j0,k0)在axis方向±侧的面4顶点网格索引；法向=±axis 由sgn定
    平面位置：+侧=本索引+1，-侧=本索引（笔记本取证发现的bug：-侧曾错置为索引-1，
    导致全部负向边界面外移一体素→~1.9万贴壁单元体积翻倍、总体积+7%、bbox外扩）"""
    if axis == 0:
        x = i0 + (1 if sgn > 0 else 0)
        p = [(x, j0, k0), (x, j0 + 1, k0), (x, j0 + 1, k0 + 1), (x, j0, k0 + 1)]
    elif axis == 1:
        y = j0 + (1 if sgn > 0 else 0)
        p = [(i0, y, k0), (i0, y, k0 + 1), (i0 + 1, y, k0 + 1), (i0 + 1, y, k0)]
    else:
        z = k0 + (1 if sgn > 0 else 0)
        p = [(i0, j0, z), (i0 + 1, j0, z), (i0 + 1, j0 + 1, z), (i0, j0 + 1, z)]
    return p[::-1] if sgn < 0 else p

# 内部面
own_list, nb_list, quad_list = [], [], []
for axis in (0, 1, 2):
    if axis == 0:
        ok = m[:, :, :-1] & m[:, :, 1:]
    elif axis == 1:
        ok = m[:, :-1, :] & m[:, 1:, :]
    else:
        ok = m[:-1, :, :] & m[1:, :, :]
    pos = np.argwhere(ok)
    for (k0, j0, i0) in pos:
        i0, j0, k0 = int(i0), int(j0), int(k0)
        if axis == 0: nb = ids[k0, j0, i0 + 1]
        elif axis == 1: nb = ids[k0, j0 + 1, i0]
        else: nb = ids[k0 + 1, j0, i0]
        own_list.append(ids[k0, j0, i0]); nb_list.append(nb)
        quad_list.append(quad_pts(i0, j0, k0, axis, 1))
own_a = np.array(own_list); nb_a = np.array(nb_list)
order = np.lexsort((nb_a, own_a))
own_a, nb_a = own_a[order], nb_a[order]
quad_list = [quad_list[t] for t in order]
n_internal = len(own_a)
print(f"    内部面 {n_internal/1e3:.0f}k")

# 边界面
k_min, k_max = 0, K - 1
for k0 in range(K):
    if m[k0].any(): k_min = k0; break
for k0 in range(K - 1, -1, -1):
    if m[k0].any(): k_max = k0; break
mid_i = int(round(head_cx / 2.0))
patches = {"inlet": [], "outlet": [], "walls": []}   # [(quad, owner), ...] 入口先合并，稍后按间隙分左右
for axis in (0, 1, 2):
    for sgn in (+1, -1):
        if sgn == +1:
            if axis == 0: ok = m[:, :, :-1] & ~m[:, :, 1:]
            elif axis == 1: ok = m[:, :-1, :] & ~m[:, 1:, :]
            else: ok = m[:-1, :, :] & ~m[1:, :, :]
            pos = np.argwhere(ok)
        else:
            if axis == 0: ok = m[:, :, 1:] & ~m[:, :, :-1]
            elif axis == 1: ok = m[:, 1:, :] & ~m[:, :-1, :]
            else: ok = m[1:, :, :] & ~m[:-1, :, :]
            pos = np.argwhere(ok)
            if axis == 0: pos[:, 2] += 1
            elif axis == 1: pos[:, 1] += 1
            else: pos[:, 0] += 1
        for (k0, j0, i0) in pos:
            i0, j0, k0 = int(i0), int(j0), int(k0)
            owner = ids[k0, j0, i0]
            if extm[k0, j0, i0]:
                # T11 补丁（v5E-ext，§5.3 判定规则）：延长段体素的面——
                # 端口层且法向·圆柱轴>0.2 → 端口（入口圆柱→inlet，出口圆柱→outlet）；
                # 其余（侧壁含体素阶梯面）→ walls
                nrm = np.zeros(3)
                nrm[axis] = sgn
                if ext_kind[k0, j0, i0] >= 2 and float(np.dot(nrm, ext_axis[:, k0, j0, i0])) > 0.2:
                    cls = "outlet" if ext_kind[k0, j0, i0] == 3 else "inlet"
                else:
                    cls = "walls"
            elif axis == 2 and sgn == -1 and k0 == k_min:
                cls = "outlet"
            elif axis == 2 and sgn == +1 and k0 == k_max:
                cls = "walls"
            else:
                nk, nj, ni = k0 + (sgn if axis == 2 else 0), j0 + (sgn if axis == 1 else 0), i0 + (sgn if axis == 0 else 0)
                if 0 <= nk < K and 0 <= nj < J and 0 <= ni < I and c[nk, nj, ni]:
                    cls = "inlet"
                else:
                    cls = "walls"
            patches[cls].append((quad_pts(i0, j0, k0, axis, sgn), owner))
patch_counts = {k: len(v) for k, v in patches.items()}
print(f"    边界面(常规): {patch_counts}  (掩码z范围 [{k_min},{k_max}])")

# 数组边界面的补充检测（常规循环覆盖不到 k=0/K-1 等数组的边）
if k_min == 0:   # 扫描底面（鼻咽截断）→ 出口
    for (j0, i0) in np.argwhere(m[0]):
        patches["outlet"].append((quad_pts(int(i0), int(j0), 0, 2, -1), ids[0, int(j0), int(i0)]))
if k_max == K - 1:  # 数组顶面 → 闭合墙
    for (j0, i0) in np.argwhere(m[K - 1]):
        patches["walls"].append((quad_pts(int(i0), int(j0), K - 1, 2, +1), ids[K - 1, int(j0), int(i0)]))
# 横向数组边缘守卫（审计R3：FOV截断需人工确认，静默封墙是错的）
if m[:, :, 0].any() or m[:, :, I - 1].any() or m[:, 0, :].any() or m[:, J - 1, :].any():
    raise SystemExit("!!! 掩码触及横向数组边缘（FOV截断头/颈），边界类型需人工确认，中止 !!!")

# ---- 鼻孔左右分组：按入口面质心 x 的最大间隙找鼻中隔 ----
inlet_faces = patches.pop("inlet")
if inlet_faces:
    cxs = np.array([np.mean([p[0] for p in q]) * dx for (q, _) in inlet_faces])
    ux = np.unique(np.round(cxs / dx))          # 量化到体素列
    gaps = np.diff(ux)
    split_i = None
    if len(ux) > 1 and gaps.max() >= 3.0:      # 间隙≥3体素(~2mm)才视为鼻中隔
        gi = int(np.argmax(gaps))
        split_i = (ux[gi] + ux[gi + 1]) / 2.0
        print(f"    鼻中隔间隙: x体素 {ux[gi]:.0f}|{ux[gi+1]:.0f} 之间 {gaps.max():.0f} 体素 -> 分割于 i={split_i:.1f} (头部中线 i={mid_i})")
    else:
        split_i = float(mid_i)
        print(f"    !!! 未找到明显鼻中隔间隙，回退头部中线 i={mid_i}")
    patches["inletL"] = [(q, o) for (q, o), cx in zip(inlet_faces, cxs) if cx < split_i * dx]
    patches["inletR"] = [(q, o) for (q, o), cx in zip(inlet_faces, cxs) if cx >= split_i * dx]
else:
    patches["inletL"], patches["inletR"] = [], []

patch_counts = {k: len(v) for k, v in patches.items()}
print(f"    边界面(最终): {patch_counts}")
if patch_counts["inletL"] == 0 or patch_counts["inletR"] == 0 or patch_counts["outlet"] == 0:
    raise SystemExit("!!! 入口/出口检测异常，中止 !!!")
if min(patch_counts["inletL"], patch_counts["inletR"]) < 30:
    print("    !!! 警告：某一侧鼻孔入口面过少，需人工复核 !!!")

# ========== 4. 写 polyMesh ==========
print("[4/6] 写 polyMesh ...")
PORDER = ["inletL", "inletR", "outlet", "walls"]
all_quads = quad_list + [q for p in PORDER for (q, _) in patches[p]]
bd_owner = [o for p in PORDER for (_, o) in patches[p]]
all_owner = np.concatenate([own_a, np.array(bd_owner, dtype=np.int32)])

arr = np.array(all_quads, dtype=np.int32).reshape(-1, 3)
uniq, inv = np.unique(arr, axis=0, return_inverse=True)
inv = np.asarray(inv).reshape(-1).reshape(-1, 4)
pts = uniq.astype(np.float64) * np.array([dx, dy, dzz])
if pad_k_ext > 0:                              # T11：v5E-ext 零填充使网格 z 整体下移，
    pts[:, 2] -= pad_k_ext * dzz               # 写盘时还原到 CT 帧（刚性平移，求解不变）

def header(cls, obj, loc):
    return ("FoamFile\n{\n    version     2.0;\n    format      ascii;\n"
            f"    class       {cls};\n    location    \"{loc}\";\n    object      {obj};\n}}\n"
            "// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //\n\n")

with open(os.path.join(MESH_DIR, "points"), "w", newline="\n") as f:
    f.write(header("vectorField", "points", "constant/polyMesh"))
    f.write(f"{len(pts):d}\n(\n")
    for p in pts:
        f.write(f"({p[0]:.6e} {p[1]:.6e} {p[2]:.6e})\n")
    f.write(")\n\n// ************************************************************************* //\n")

with open(os.path.join(MESH_DIR, "faces"), "w", newline="\n") as f:
    f.write(header("faceList", "faces", "constant/polyMesh"))
    f.write(f"{len(all_quads):d}\n(\n")
    buf = []
    for q in inv:
        buf.append(f"4({q[0]:d} {q[1]:d} {q[2]:d} {q[3]:d})")
        if len(buf) >= 50000:
            f.write("\n".join(buf) + "\n"); buf = []
    if buf: f.write("\n".join(buf) + "\n")
    f.write(")\n\n// ************************************************************************* //\n")

with open(os.path.join(MESH_DIR, "owner"), "w", newline="\n") as f:
    f.write(header("labelList", "owner", "constant/polyMesh"))
    f.write(f"{len(all_owner):d}\n(\n")
    np.savetxt(f, all_owner, fmt="%d")
    f.write(")\n\n// ************************************************************************* //\n")

with open(os.path.join(MESH_DIR, "neighbour"), "w", newline="\n") as f:
    f.write(header("labelList", "neighbour", "constant/polyMesh"))
    f.write(f"{n_internal:d}\n(\n")
    np.savetxt(f, nb_a, fmt="%d")
    f.write(")\n\n// ************************************************************************* //\n")

with open(os.path.join(MESH_DIR, "boundary"), "w", newline="\n") as f:
    f.write(header("polyBoundaryMesh", "boundary", "constant/polyMesh"))
    f.write(f"{len(PORDER):d}\n(\n")
    s = n_internal
    for name in PORDER:
        nf = patch_counts[name]
        ptype = "wall" if name == "walls" else "patch"   # 审计G1：walls 用 wall 类型
        f.write(f"    {name}\n    {{\n        type            {ptype};\n        nFaces          {nf};\n        startFace       {s};\n    }}\n")
        s += nf
    f.write(")\n\n// ************************************************************************* //\n")

# ========== 5. patch 面积 / 入流方向 ==========
print("[5/6] patch 面积与入流方向 ...")
def face_area(q):
    if len({p[0] for p in q}) == 1: return dy * dzz
    if len({p[1] for p in q}) == 1: return dx * dzz
    return dx * dy
def patch_info(pname):
    fl = patches[pname]
    if not fl:
        return 0.0, np.array([np.nan, np.nan, np.nan])
    A = sum(face_area(q) for (q, _) in fl)
    ctr = np.array([(dx * sum(p[0] for p in q), dy * sum(p[1] for p in q), dzz * sum(p[2] for p in q)) for (q, _) in fl]).mean(axis=0) / 4.0
    if pad_k_ext > 0:                          # T11：质心还原到 CT 帧（与 mask_ctr 同帧）
        ctr[2] -= pad_k_ext * dzz
    return A, ctr
mask_ctr = np.array([dx * np.argwhere(m)[:, 2].mean(), dy * np.argwhere(m)[:, 1].mean(), dzz * np.argwhere(m)[:, 0].mean()])
if pad_k_ext > 0:                              # T11：与 patch_info 质心同帧（CT 帧）
    mask_ctr[2] -= pad_k_ext * dzz
A_L, ctr_L = patch_info("inletL")
A_R, ctr_R = patch_info("inletR")
info = {}
for pname, A, ctr in (("inletL", A_L, ctr_L), ("inletR", A_R, ctr_R)):
    d = mask_ctr - ctr
    d = d / np.linalg.norm(d)
    Qi = Q_TOTAL * A / (A_L + A_R)
    U = Qi / A * d
    info[pname] = dict(area_mm2=round(A * 1e6, 1), Q_Lmin=round(Qi * 60000, 2),
                       U=[round(float(x), 3) for x in U],
                       centroid_mm=[round(float(x) * 1e3, 1) for x in ctr])
    print(f"    {pname}: 面积 {A*1e6:.1f} mm2, 流量 {Qi*60000:.2f} L/min, U={info[pname]['U']}, 质心 {info[pname]['centroid_mm']}")

# ========== 6. case 文件 ==========
print("[6/6] 生成 case ...")
def wr(rel, content):
    with open(os.path.join(CASE_DIR, rel), "w", newline="\n") as f:
        f.write(content)

uL, uR = info["inletL"]["U"], info["inletR"]["U"]
qL = Q_TOTAL * A_L / (A_L + A_R)     # Run-A（指定分配基准工况）：按开口面积比例分配，声明为建模假设（审计R2）
qR = Q_TOTAL * A_R / (A_L + A_R)
print(f"    Run-A 流量: inletL {qL*60000:.2f} L/min, inletR {qR*60000:.2f} L/min (flowRateInletVelocity)")
wr("0/U", header("volVectorField", "U", "0") + f"""
dimensions      [0 1 -1 0 0 0 0];

internalField   uniform (0 0 0);

boundaryField
{{
    inletL
    {{
        type            flowRateInletVelocity;
        volumetricFlowRate {qL:.6e};
        value           uniform (0 0 0);
    }}
    inletR
    {{
        type            flowRateInletVelocity;
        volumetricFlowRate {qR:.6e};
        value           uniform (0 0 0);
    }}
    outlet
    {{
        type            zeroGradient;
    }}
    walls
    {{
        type            fixedValue;
        value           uniform (0 0 0);
    }}
}}

// ************************************************************************* //
""")
wr("0/p", header("volScalarField", "p", "0") + """
dimensions      [0 2 -2 0 0 0 0];

internalField   uniform 0;

boundaryField
{
    inletL    { type            zeroGradient; }
    inletR    { type            zeroGradient; }
    outlet    { type            fixedValue; value uniform 0; }
    walls     { type            zeroGradient; }
}

// ************************************************************************* //
""")
wr("constant/transportProperties", header("dictionary", "transportProperties", "constant") + f"""
transportModel  Newtonian;

nu              [0 2 -1 0 0 0 0] {NU_AIR:.3e};

// ************************************************************************* //
""")
wr("constant/turbulenceProperties", header("dictionary", "turbulenceProperties", "constant") + """
simulationType  laminar;

// ************************************************************************* //
""")
wr("system/controlDict", header("dictionary", "controlDict", "system") + """
application     simpleFoam;

startFrom       latestTime;
startTime       0;
stopAt          endTime;
endTime         1500;
deltaT          1;

writeControl    timeStep;
writeInterval   500;
purgeWrite      2;
writeFormat     ascii;
writePrecision  6;
timeFormat      general;
timePrecision   6;
graphFormat     raw;

functions
{
    fluxInletL
    {
        type            surfaceFieldValue;
        libs            ("libfieldFunctionObjects.so");
        fields          (phi);
        operation       sum;
        regionType      patch;
        name            inletL;
        writeControl    writeTime;
        writeFields      false;
    }
    fluxInletR
    {
        type            surfaceFieldValue;
        libs            ("libfieldFunctionObjects.so");
        fields          (phi);
        operation       sum;
        regionType      patch;
        name            inletR;
        writeControl    writeTime;
        writeFields      false;
    }
    fluxOutlet
    {
        type            surfaceFieldValue;
        libs            ("libfieldFunctionObjects.so");
        fields          (phi);
        operation       sum;
        regionType      patch;
        name            outlet;
        writeControl    writeTime;
        writeFields      false;
    }
    wss
    {
        type            wallShearStress;
        libs            ("libfieldFunctionObjects.so");
        writeControl    writeTime;
    }
}

// ************************************************************************* //
""")
wr("system/fvSchemes", header("dictionary", "fvSchemes", "system") + """
ddtSchemes
{
    default         steadyState;
}
gradSchemes
{
    default         Gauss linear;
}
divSchemes
{
    default         none;
    div(phi,U)      bounded Gauss linearUpwind grad(U);
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}
laplacianSchemes
{
    default         Gauss linear corrected;
}
snGradSchemes
{
    default         corrected;
}
interpolationSchemes
{
    default         linear;
}

// ************************************************************************* //
""")
wr("system/fvSolution", header("dictionary", "fvSolution", "system") + """
solvers
{
    p
    {
        solver          GAMG;
        tolerance       1e-06;
        relTol          0.05;
        smoother        GaussSeidel;
    }
    U
    {
        solver          smoothSolver;
        smoother        GaussSeidel;
        tolerance       1e-05;
        relTol          0.01;
    }
}

SIMPLE
{
    nNonOrthogonalCorrectors 0;
    residualControl
    {
        p               1e-4;
        U               1e-4;
    }
}

relaxationFactors
{
    fields
    {
        p               0.3;
    }
    equations
    {
        U               0.7;
    }
}

cache
{
    grad(U);
}

// ************************************************************************* //
""")
wr("Allrun", """#!/bin/sh
set -e
cd "${0%/*}" || exit 1
echo "== checkMesh =="
checkMesh | tee log.checkMesh
echo "== simpleFoam =="
simpleFoam | tee log.simpleFoam
echo "== 导出VTK =="
foamToVTK -latestTime
echo "== 完成。把整个case目录拷回共享文件夹即可 =="
""")

# ========== 7. Run-B 压力驱动算例（审计R2：测真实自然分流） ==========
import shutil
B_DIR = os.path.join(WS_OUT, "step2", f"P0-OF-case-pA-{ARGS.case}B")
if os.path.exists(B_DIR):
    shutil.rmtree(B_DIR)
shutil.copytree(CASE_DIR, B_DIR)
print("[7/7] Run-B 压力驱动算例（自然分流）:", B_DIR)
# 覆盖 0/U 与 0/p：双侧入口等静压 80 (kinematic m2/s2, 约98Pa@rho1.225)，出口 p=0
with open(os.path.join(B_DIR, "0", "U"), "w", newline="\n") as f:
    f.write(header("volVectorField", "U", "0") + """
dimensions      [0 1 -1 0 0 0 0];

internalField   uniform (0 0 0);

boundaryField
{
    inletL    { type zeroGradient; }
    inletR    { type zeroGradient; }
    outlet    { type zeroGradient; }
    walls     { type fixedValue; value uniform (0 0 0); }
}

// ************************************************************************* //
""")
with open(os.path.join(B_DIR, "0", "p"), "w", newline="\n") as f:
    f.write(header("volScalarField", "p", "0") + """
dimensions      [0 2 -2 0 0 0 0];

internalField   uniform 0;

boundaryField
{
    inletL    { type fixedValue; value uniform 80; }
    inletR    { type fixedValue; value uniform 80; }
    outlet    { type fixedValue; value uniform 0; }
    walls     { type zeroGradient; }
}

// ************************************************************************* //
""")

stats = {
    "case": f"P0-OF-case-pA-{ARGS.case} (Run-A 指定流量) + P0-OF-case-pA-{ARGS.case}B (Run-B 压力驱动自然分流)",
    "cells": ncells, "internal_faces": n_internal,
    "patch_face_counts": patch_counts,
    "inletL": info["inletL"], "inletR": info["inletR"],
    "runA_flux_Lmin": [round(qL * 60000, 2), round(qR * 60000, 2)],
    "runA_note": "flowRateInletVelocity按法向分配(审计R1+笔记本病根②)；流量按面积分配=建模假设(审计R2)；relaxationFactors p0.3/U0.7(笔记本病根①)",
    "runB_note": "双侧入口等压80(kinematic,约98Pa)压力驱动，输出真实自然分流比与鼻腔阻力R=dp/Q",
    "baseline_ref": "笔记本v3初步基线(旧网格/nu1.48e-5/切向入口): dP=11.40Pa@15L/min, Umax=4.53m/s, Re=1155",
    "mask_z_range": [k_min - pad_k_ext, k_max - pad_k_ext], "mid_i": mid_i,
    "Q_total_Lmin": 15.0, "solver": "simpleFoam laminar steady",
    "nu_m2s": NU_AIR,
    "voxel_mm": [round(dx * 1e3, 3), round(dy * 1e3, 3), round(dzz * 1e3, 3)],
    "volume_regression_ratio": round(float(ratio_v), 3),
    "design": [(f"outlet=延长段圆柱端口(轴向(0,0,-1), 零填充{pad_k_ext}层已还原CT帧)" if pad_k_ext > 0 else "outlet=掩码最下层平面(鼻咽截断)"),
               ("inletL/R=延长段圆柱端口(鼻中隔x间隙分组)" if pad_k_ext > 0 else "inletL/R=鼻孔自然开口(鼻中隔x间隙分组)"),
               "walls=wall类型(审计G1)", "多数表决降采样(审计Y1)", "nu=1.8e-5气道温度(审计Y2)",
               "relaxationFactors(笔记本诊断)", "wallShearStress functionObject(笔记本建议)"],
    "release_gates": ["checkMesh 0 errors", "|Σφ_in-Σφ_out|/Σφ_in < 1%", "残差早停或1500步平台(如实报告)",
                      "末500步Δp变化<2%", "Run-B分流比方向与几何不对称一致"],
}
if ARGS.ext or ARGS.iso or ARGS.case != "v5":
    stats["t11_variant"] = {
        "case_name": ARGS.case,
        "extension_cylinders": ext_cylinders,
        "iso": ("去窦对照：step3_make_narrowing.py §2 同法（全分辨率腐蚀3→最大连通域→膨胀3&掩码）" if ARGS.iso else None),
        "note": "T11 合规对照算例：v5/v5B/v5C 系基线已冻结，本算例仅作披露对照，不进演示基线",
    }
stats_file = "case_stats.json" if ARGS.case == "v5" else f"case_stats-{ARGS.case}.json"
with open(os.path.join(WS_OUT, "step2", stats_file), "w", encoding="utf-8") as f:
    json.dump(stats, f, ensure_ascii=False, indent=2)
print("\n[完成]", CASE_DIR)
print(json.dumps(stats, ensure_ascii=False, indent=2))
