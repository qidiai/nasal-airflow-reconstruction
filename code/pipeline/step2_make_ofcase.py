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
# T14c 补丁（诊断决定轮·对照实验）：并合模式三选一（语义同
# step1 --merge-mode）。largest=现状默认；facegrow=咽部以 6-conn
# 面连接生长并入（BFS 只走 6-conn 面-邻接步，生长介质=头内部
# HU<-300 体素，可达即并入、不可达即不并入——生长天然面连通，
# 零插入体素）；base=仅最大 6-conn 连通域（对照变体 X1）。
# pA/pB 咽部本就 6-conn 连通于主域（咽部识别为空）-> facegrow/
# base 分支不触发，与 largest 逐字节一致（回归铁闸）。
_ap.add_argument("--merge-mode", default="largest",
                 choices=["largest", "facegrow", "base"],
                 help="T14c 并合模式（largest 现状默认/facegrow "
                      "6-conn 面连接生长并入咽部/base 仅最大 "
                      "6-conn 连通域）")
# T14d 补丁（E1 实验·z 降采样参数化）：z 向降采样以
# 体素尺寸参数化（mm 口径）。默认 2.0 = 现状 z 向 2 层
# 多数表决（向后兼容哨兵：pA 层厚 0.35mm/pB 0.3mm 下
# 2.0/dz 非整数，唯哨兵语义可保默认路径逐字节回归铁闸
# ——默认路径 pA/pB/pC 皆 zf=2，与 T14d 前逐字节一致）；
# 显式非 2.0 值须为源层厚整数倍（pC 层厚 1.0mm：
# 2.0=现状 / 1.0=不降采样=E1）。xy 口径不动（恒 2×2）。
_ap.add_argument("--voxel-z", type=float, default=2.0,
                 help="z 向体素尺寸 mm（默认 2.0=现状 z 向 2 层"
                      "多数表决，逐字节兼容；1.0=不降采样，T14d/E1）")
# T12 补丁（多患者通用化）：DICOM 目录与病例前缀参数化。默认值 = 患者A 路径/pA（向后兼容）。
_ap.add_argument("--dicom-dir", default=os.path.expandvars(r"%DATA_ROOT%\参赛群资料\患者A\脱敏后图像数据\ISO_Soft_0.35mm_合并"),
                 help="DICOM 目录（默认患者A 序列，向后兼容）")
_ap.add_argument("--case-prefix", default="pA",
                 help="病例前缀（默认 pA；算例目录 P0-OF-case-<prefix>-<case>，pA 与原版一致）")
_ap.add_argument("--out-root", default=None,
                 help="输出根目录（默认 pipeline/out；T12 自测隔离用）")
ARGS = _ap.parse_args()
PREFIX = ARGS.case_prefix

DATA_DIR = os.path.expandvars(ARGS.dicom_dir)
WS_OUT = os.path.expandvars(ARGS.out_root or r"%QIDI_WORKSPACE%\contest3_workspace\pipeline\out")
CASE_DIR = os.path.join(WS_OUT, "step2", f"P0-OF-case-{PREFIX}-{ARGS.case}")
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
# T14d：z 降采样因子（--voxel-z 口径）。默认 2.0 =
# 遗留哨兵（zf=2；pA 0.35mm/pB 0.3mm 层厚下 2.0/dz
# 非整数，哨兵语义保默认路径逐字节回归铁闸）；显式
# 非 2.0 值 = 目标 z 体素尺寸，须为层厚整数倍。
if ARGS.voxel_z == 2.0:
    _zf = 2
    print(f"[T14d] z 降采样因子 zf={_zf}"
          f"（--voxel-z 默认 2.0mm=现状 z 向 2 层多数表决，"
          f"逐字节兼容路径）")
else:
    _zf_raw = ARGS.voxel_z / dz
    _zf = int(round(_zf_raw))
    if _zf < 1 or abs(_zf_raw - _zf) > 1e-9:
        raise SystemExit(
            f"[T14d] --voxel-z {ARGS.voxel_z}mm 非源层厚 "
            f"{dz}mm 的整数倍（zf={_zf_raw:.4f}）——仅支持"
            f"整数倍 z 降采样因子，停工上报")
    print(f"[T14d] z 降采样因子 zf={_zf}（--voxel-z "
          f"{ARGS.voxel_z}mm / 源层厚 {dz}mm；z 体素 "
          f"{dz * _zf:.4g}mm）")
vol = np.zeros((nz, rows, cols), dtype=np.int16)
for i, s in enumerate(slices):
    vol[i] = s.pixel_array.astype(np.int16) * int(s.RescaleSlope) + int(s.RescaleIntercept)
head = vol > -300
head_int = np.zeros_like(head)
for i in range(nz):
    head_int[i] = ndimage.binary_fill_holes(head[i])
air = vol < -400
airway_all = air & head_int
# ---- T14/L1'：26-conn 识别 + 规范序 HU 过滤补桥 ----
# （DeepSeek round2 §5.2：step2 独立重分割，不吃
# step1 输出；§2.1：6-conn 下 pC 咽部 7,355 体素
# =2.77cm3 真实解剖是独立组件被丢弃——26-conn
# 识别后经对角邻接并入主组件，再规范序补桥为
# 6-conn 单域。实测：pA +0 体素（逐字节回归）、
# pB +7 / pC +7,620；鼻窦与主域距离 >=3.76mm >
# 对角接触半径 1.73mm，三例均不误并）
_S26 = np.ones((3, 3, 3), dtype=bool)
_S6 = ndimage.generate_binary_structure(3, 1)
lab26, n26 = ndimage.label(airway_all, structure=_S26)
sizes26 = np.bincount(lab26.ravel())
main_lab26 = int(np.argmax(sizes26[1:]) + 1)
mask26 = lab26 == main_lab26
# 咽部识别（补桥前 6-conn label：非主组件、体积
# >1000 体素、k_min<=2、且并入 26-conn 主域——
# pC 咽部 7,355 体素 k[0,22]；pA/pB 无候选组件
# -> None，L3 出口通用化不触发）
lab6p, n6p = ndimage.label(airway_all, structure=_S6)
sizes6p = np.bincount(lab6p.ravel())
main_lab6p = int(np.argmax(sizes6p[1:]) + 1)
pharynx_mask = None
pharynx_label_t14c = None
for _l in range(1, n6p + 1):
    if _l == main_lab6p or sizes6p[_l] <= 1000:
        continue
    _kk6 = np.where(lab6p == _l)[0]
    if int(_kk6.min()) > 2:
        continue
    if not ((lab6p == _l) & mask26).any():
        continue
    pharynx_mask = lab6p == _l
    pharynx_label_t14c = int(_l)
    break
# ---- T14c：--merge-mode 三模式（largest 现状默认 / facegrow
#       6-conn 面连接生长并入咽部 / base 仅最大 6-conn 连通域）。
#       pA/pB 咽部本就 6-conn 连通于主域（咽部识别为空）->
#       facegrow/base 分支不触发，与 largest 逐字节一致（回归铁闸）。
#       base 模式：咽部识别结果仅作披露（excluded），不并入域——
#       L3 出口通用化不触发（咽部不在域内，其稳定性准则出口层
#       k=10 超出主域 k 范围 [23,92]，出口层退化为自域末端向
#       内首个实质截面 + T13b 出口层多数表决塌缩豁免，"出口层
#       豁免"）。
pharynx_excluded_t14c = None
pharynx_excluded_mask_t14c = None
merge_stats_t14c = None
_t14c_corridor = None
if ARGS.merge_mode == "base" and pharynx_mask is not None:
    pharynx_excluded_t14c = {
        "voxels": int(pharynx_mask.sum()),
        "k_range": [int(np.where(pharynx_mask)[0].min()),
                      int(np.where(pharynx_mask)[0].max())],
        "note": ("T14c base 模式：咽部识别但未并入（对照变体 "
                 "X1）——L3 出口通用化不触发，出口层=自域末端"
                 "向内首个实质截面（>=200 体素准入）+ T13b "
                 "出口层塌缩豁免"),
    }
    pharynx_excluded_mask_t14c = pharynx_mask
    pharynx_mask = None

def bridge_to_6conn_canonical(mask26_, vol_, hu_max=-300, max_iter=80):
    """26-conn 掩码 -> 6-conn 单域（规范序 HU 过滤补桥，
    T4 确定性：boundary 按 (k,j,i) 字典序、对角候选按
    (HU,坐标) 择最低——消除顺序依赖，t19 实证）。"""
    bridged = mask26_.copy()
    n_ins = 0
    shape = bridged.shape
    dirs = [(dk, dj, di) for dk in (-1, 0, 1) for dj in (-1, 0, 1)
            for di in (-1, 0, 1)
            if sum(1 for x in (dk, dj, di) if x != 0) >= 2]
    for _it in range(max_iter):
        lab_, n_ = ndimage.label(bridged, structure=_S6)
        if n_ <= 1:
            break
        boundary = bridged & ndimage.binary_dilation(
            ~bridged, structure=_S26)
        idx = np.argwhere(boundary)
        idx = idx[np.lexsort((idx[:, 2], idx[:, 1], idx[:, 0]))]
        added = 0
        for a in idx:
            k, j, i = int(a[0]), int(a[1]), int(a[2])
            la = lab_[k, j, i]
            for (dk, dj, di) in dirs:
                kk, jj, ii = k + dk, j + dj, i + di
                if not (0 <= kk < shape[0] and 0 <= jj < shape[1]
                        and 0 <= ii < shape[2]):
                    continue
                lb = lab_[kk, jj, ii]
                if lb == 0 or lb == la:
                    continue
                cands = []
                if dk != 0:
                    cands.append((k + dk, j, i))
                if dj != 0:
                    cands.append((k, j + dj, i))
                if di != 0:
                    cands.append((k, j, i + di))
                best = None
                for c in cands:
                    if bridged[c[0], c[1], c[2]]:
                        continue
                    hu = int(vol_[c[0], c[1], c[2]])
                    if hu < hu_max:
                        key = (hu, c)
                        if best is None or key < best[0]:
                            best = (key, c)
                if best is not None:
                    c = best[1]
                    bridged[c[0], c[1], c[2]] = True
                    n_ins += 1
                    added += 1
        if added == 0:
            break
    lab_, n_ = ndimage.label(bridged, structure=_S6)
    return bridged, n_, n_ins

# ---- T14b：面连接修复（补桥对角接触 -> 面连接通路）----
# 根因（笔记本 v3 回报 2026-10-05）：T14 规范序补桥体素与主域/咽部
# 仅对角接触（对角相邻无共面 -> 压力-速度耦合断裂；simpleFoam 首步
# 连续性失衡 350x(Run-A)/156,000x(Run-B)，FPE x2，checkMesh
# conflicting 1019/bad edges 703 不降反升）。本步对融合域全体
# edge_only/corner_only 对角配置做面连接修复：
#   edge_only（面对角对 (x, x+d)，共享棱周围 4 体素恰 x,y 在域内）
#     -> 插入 1 拐角体素（两候选各保留一个非零轴；(HU, 坐标) 字典序
#     择最低）-> x-c-y L 形面连通
#   corner_only（体对角对，共享顶点周围 8 体素恰 x,y 在域内）
#     -> 插入 2 体素面路径（6 条候选路径"先一轴再另一轴"；
#     (HU 和, 坐标) 字典序择最低）-> 面连通
# 规范方向（首非零分量为正）单趟检测+决策：每个对角对恰检测一次
# （d 与 -d 互为镜像）；迭代至不动点（无可插入即收敛，有界
# max_iter=10）。硬约束（T13b 红线不变）：插入体素 HU<-300；候选体素
# HU>=-300（软组织/骨壁）-> 配置不可修复，如实计数（零软组织侵入
# 不变）。条件触发：n_bridge>0（pA no-op -> step1/step2 产物逐字节
# 回归铁闸）。
def _shift(a, dk, dj, di):
    """out[x] = a[x + d]（边界外 False）。"""
    out = np.zeros_like(a)
    sk = slice(max(0, -dk), a.shape[0] - max(0, dk))
    sj = slice(max(0, -dj), a.shape[1] - max(0, dj))
    si = slice(max(0, -di), a.shape[2] - max(0, di))
    tk = slice(max(0, dk), a.shape[0] - max(0, -dk))
    tj = slice(max(0, dj), a.shape[1] - max(0, -dj))
    ti = slice(max(0, di), a.shape[2] - max(0, -di))
    out[sk, sj, si] = a[tk, tj, ti]
    return out

_FC_EDGE_DIRS = ([(dk, dj, 0) for dk in (1,) for dj in (-1, 1)] +
                 [(dk, 0, di) for dk in (1,) for di in (-1, 1)] +
                 [(0, dj, di) for dj in (1,) for di in (-1, 1)])
_FC_CORNER_DIRS = [(dk, dj, di) for dk in (1,) for dj in (-1, 1)
                   for di in (-1, 1)]

def _edge_bridges(dk, dj, di):
    """面对角方向的两个面桥接位移：各保留一个非零轴。
    (dk,dj,0) -> ((dk,0,0),(0,dj,0))；(dk,0,di) -> ((dk,0,0),(0,0,di))；
    (0,dj,di) -> ((0,dj,0),(0,0,di))。"""
    nz = []
    for _c in ((dk, 0, 0), (0, dj, 0), (0, 0, di)):
        if _c != (0, 0, 0):
            nz.append(_c)
    return nz[0], nz[1]

def _count_diag_configs(mask_):
    """完备体素级口径（规范方向，每个对角对恰一次）。
    返回 (edge_only 数, corner_only 数)。"""
    n_edge = 0
    n_corner = 0
    for (dk, dj, di) in _FC_EDGE_DIRS:
        y_m = _shift(mask_, dk, dj, di)
        pair = mask_ & y_m
        b1, b2 = _edge_bridges(dk, dj, di)
        n_edge += int((pair & ~_shift(mask_, *b1)
                       & ~_shift(mask_, *b2)).sum())
    for (dk, dj, di) in _FC_CORNER_DIRS:
        y_m = _shift(mask_, dk, dj, di)
        pair = mask_ & y_m
        others = (_shift(mask_, dk, 0, 0) | _shift(mask_, 0, dj, 0) |
                  _shift(mask_, 0, 0, di) | _shift(mask_, dk, dj, 0) |
                  _shift(mask_, dk, 0, di) | _shift(mask_, 0, dj, di))
        n_corner += int((pair & ~others).sum())
    return n_edge, n_corner

def _collect_config_coords(mask_):
    """对角配置主顶点坐标集（规范方向，每个对角对一次）。
    返回 (edge 坐标集, corner 坐标集)。"""
    s_edge = set()
    s_corner = set()
    for (dk, dj, di) in _FC_EDGE_DIRS:
        y_m = _shift(mask_, dk, dj, di)
        pair = mask_ & y_m
        b1, b2 = _edge_bridges(dk, dj, di)
        cfg = pair & ~_shift(mask_, *b1) & ~_shift(mask_, *b2)
        for x in np.argwhere(cfg):
            s_edge.add((int(x[0]), int(x[1]), int(x[2])))
    for (dk, dj, di) in _FC_CORNER_DIRS:
        y_m = _shift(mask_, dk, dj, di)
        pair = mask_ & y_m
        others = (_shift(mask_, dk, 0, 0) | _shift(mask_, 0, dj, 0) |
                  _shift(mask_, 0, 0, di) | _shift(mask_, dk, dj, 0) |
                  _shift(mask_, dk, 0, di) | _shift(mask_, 0, dj, di))
        cfg = pair & ~others
        for x in np.argwhere(cfg):
            s_corner.add((int(x[0]), int(x[1]), int(x[2])))
    return s_edge, s_corner

def _face_connect_canonical(mask_, vol_, hu_max=-300, max_iter=10):
    """T14b 面连接修复：消除 edge_only/corner_only 对角配置。
    返回 (mask_fixed, n_edge_fixed, n_corner_fixed, n_inserted,
          inserted_hu_min, inserted_hu_max, n_unfixable,
          edge_only_after, corner_only_after)。"""
    fixed = mask_.copy()
    n_ins = 0
    tot_edge = 0
    tot_corner = 0
    n_unfix = 0
    for it in range(max_iter):
        inserts = []          # 本轮待插入体素坐标（去重）
        seen = set()
        it_edge = 0
        it_corner = 0
        # ---- edge_only 修复（单趟：检测与决策合并）----
        for (dk, dj, di) in _FC_EDGE_DIRS:
            y_m = _shift(fixed, dk, dj, di)
            pair = fixed & y_m
            b1, b2 = _edge_bridges(dk, dj, di)
            p1_m = _shift(fixed, *b1)
            p2_m = _shift(fixed, *b2)
            cfg = pair & ~p1_m & ~p2_m
            if not cfg.any():
                continue
            for x in np.argwhere(cfg):
                k, j, i = int(x[0]), int(x[1]), int(x[2])
                p1 = (k + b1[0], j + b1[1], i + b1[2])
                p2 = (k + b2[0], j + b2[1], i + b2[2])
                if p1 in seen or p2 in seen:
                    continue
                ok1 = (not fixed[p1]) and int(vol_[p1]) < hu_max
                ok2 = (not fixed[p2]) and int(vol_[p2]) < hu_max
                if ok1 and ok2:
                    hu1, hu2 = int(vol_[p1]), int(vol_[p2])
                    c = p1 if (hu1, p1) <= (hu2, p2) else p2
                elif ok1:
                    c = p1
                elif ok2:
                    c = p2
                else:
                    n_unfix += 1
                    continue
                seen.add(c)
                inserts.append(c)
                it_edge += 1
        # ---- corner_only 修复（6 条 2 体素面路径）----
        for (dk, dj, di) in _FC_CORNER_DIRS:
            y_m = _shift(fixed, dk, dj, di)
            pair = fixed & y_m
            others = (_shift(fixed, dk, 0, 0) | _shift(fixed, 0, dj, 0) |
                      _shift(fixed, 0, 0, di) | _shift(fixed, dk, dj, 0) |
                      _shift(fixed, dk, 0, di) | _shift(fixed, 0, dj, di))
            cfg = pair & ~others
            if not cfg.any():
                continue
            for x in np.argwhere(cfg):
                k, j, i = int(x[0]), int(x[1]), int(x[2])
                cands = [
                    ((k + dk, j, i), (k + dk, j + dj, i)),
                    ((k + dk, j, i), (k + dk, j, i + di)),
                    ((k, j + dj, i), (k + dk, j + dj, i)),
                    ((k, j + dj, i), (k, j + dj, i + di)),
                    ((k, j, i + di), (k + dk, j, i + di)),
                    ((k, j, i + di), (k, j + dj, i + di)),
                ]
                best = None      # (hu_sum, a, b, path)
                for pa in cands:
                    a, b = pa
                    if a in seen or b in seen:
                        continue
                    if fixed[a] or fixed[b]:
                        continue
                    hua, hub = int(vol_[a]), int(vol_[b])
                    if hua < hu_max and hub < hu_max:
                        key = (hua + hub, a, b)
                        if best is None or key < best[:3]:
                            best = (hua + hub, a, b, pa)
                if best is None:
                    n_unfix += 1
                    continue
                for c in (best[1], best[2]):
                    if c not in seen:
                        seen.add(c)
                        inserts.append(c)
                it_corner += 1
        if not inserts:
            break             # 无可插入 -> 剩余配置均为 HU 不可修复（不动点）
        for c in inserts:
            fixed[c[0], c[1], c[2]] = True
        n_ins += len(inserts)
        tot_edge += it_edge
        tot_corner += it_corner
        print(f"    [T14b 面连接 iter {it}] edge 修复 {it_edge} / "
              f"corner 修复 {it_corner} / 插入 {len(inserts)} 体素")
    ne, nc = _count_diag_configs(fixed)
    if n_ins > 0:
        _ins_hu = vol_[fixed & ~mask_]
        hu_lo = int(_ins_hu.min())
        hu_hi = int(_ins_hu.max())
    else:
        hu_lo = 0
        hu_hi = 0
    return (fixed, tot_edge, tot_corner, n_ins,
            hu_lo, hu_hi, n_unfix, ne, nc)

def facegrow_merge_6conn(mask26_, vol_, head_int_, lab6_,
                           main_lab6_, n6_, sizes6_, hu_max=-300):
    """T14c 6-conn 面连接生长并入（facegrow，指挥官令 T14c）。
    BFS（FIFO 队列、确定性种子序/邻居序）从主域（最大 6-conn 组件）
    出发，只走 6-conn 面-邻接步；生长介质 = head_int_ & (vol_ < hu_max)
    （空气 + 部分容积体素）。mask26_ 内非主 6-conn 组件（咽部及并合链
    小组件）凡经介质 6-conn 可达者，取其字典序首达体素沿 BFS 前驱树
    回溯、逐体素并入走廊，再整组件并入——生长天然面连通，零插入体素；
    不可达组件不并入（交下游规范序补桥兜底）。
    返回 (grown, n_comp6, n_bridge, stats, corridor)。"""
    from collections import deque
    medium = head_int_ & (vol_ < hu_max)
    main6_ = (lab6_ == main_lab6_)
    reach = main6_.copy()
    parent = {}
    dq = deque()
    for _x in np.argwhere(main6_):
        dq.append((int(_x[0]), int(_x[1]), int(_x[2])))
    _dirs6 = ((-1, 0, 0), (1, 0, 0), (0, -1, 0), (0, 1, 0),
              (0, 0, -1), (0, 0, 1))
    _sh = medium.shape
    while dq:
        _k, _j, _i = dq.popleft()
        for _dk, _dj, _di in _dirs6:
            _kk, _jj, _ii = _k + _dk, _j + _dj, _i + _di
            if not (0 <= _kk < _sh[0] and 0 <= _jj < _sh[1]
                    and 0 <= _ii < _sh[2]):
                continue
            if not medium[_kk, _jj, _ii] or reach[_kk, _jj, _ii]:
                continue
            reach[_kk, _jj, _ii] = True
            parent[(_kk, _jj, _ii)] = (_k, _j, _i)
            dq.append((_kk, _jj, _ii))
    targets = [_l for _l in range(1, n6_ + 1)
               if _l != main_lab6_ and ((lab6_ == _l) & mask26_).any()]
    grown = main6_.copy()
    corridor = np.zeros_like(grown)
    merged = []
    unreachable = []
    for _l in targets:
        _tm = lab6_ == _l
        _rt = reach & _tm
        if not _rt.any():
            unreachable.append(int(_l))
            continue
        _cand = np.argwhere(_rt)
        _cand = _cand[np.lexsort((_cand[:, 2], _cand[:, 1], _cand[:, 0]))]
        _cur = (int(_cand[0][0]), int(_cand[0][1]), int(_cand[0][2]))
        _plen = 0
        while _cur in parent:
            corridor[_cur] = True
            _cur = parent[_cur]
            _plen += 1
        grown |= _tm
        merged.append({"label": int(_l), "voxels": int(sizes6_[_l]),
                       "tree_path_voxels": int(_plen)})
    grown |= corridor
    lab_g, n_g = ndimage.label(
        grown, structure=ndimage.generate_binary_structure(3, 1))
    stats = {
        "mode": "facegrow",
        "algorithm": ("6-conn face-connected BFS growth from main domain "
                      "(FIFO queue, deterministic seed/neighbor order); "
                      "medium = head-interior HU<-300 voxels (air + "
                      "partial volume); per target component: "
                      "lexicographically-first reached voxel -> BFS "
                      "predecessor-tree path union, then whole component "
                      "merged; unreachable components not merged "
                      "(mop-up canonical bridge downstream)"),
        "main_component_6conn_cells": int(main6_.sum()),
        "corridor_voxels": int(corridor.sum()),
        "corridor_hu_range": ([int(vol_[corridor].min()),
                                 int(vol_[corridor].max())]
                                if corridor.any() else None),
        "corridor_all_hu_below_max": (bool((vol_[corridor] < hu_max).all())
                                         if corridor.any() else None),
        "merged_components": merged,
        "unreachable_components": unreachable,
        "grown_voxels": int(grown.sum()),
        "inserted_voxels": 0,
        "n_components_6conn_after_growth": int(n_g),
        "note": ("T14c facegrow：生长天然 6-conn 面连通（零插入体素）"
                 "——对照变体 X2（pC-facegrow），验证咽部面连接并入"
                 "可解性（指挥官令 T14c 诊断决定轮）"),
    }
    print(f"    T14c facegrow 生长: 主域 {int(main6_.sum()):,} 体素 + "
          f"走廊 {int(corridor.sum())} 介质体素"
          + (f"（HU [{stats['corridor_hu_range'][0]},"
             f"{stats['corridor_hu_range'][1]}]，全 <{hu_max}: "
             f"{stats['corridor_all_hu_below_max']}）"
             if corridor.any() else "")
          + f" -> 并入 {len(merged)} 组件"
          + (f"；不可达 {len(unreachable)} 组件不并入"
             if unreachable else "")
          + f" -> {int(grown.sum()):,} 体素，6-conn 组件 {n_g} 个"
          + ("（单域）" if n_g == 1 else "（非单域，mop-up 兜底）"))
    return grown, n_g, 0, stats, corridor

# ---- T14c：--merge-mode 三模式并合分发 ----
if ARGS.merge_mode == "facegrow" and pharynx_mask is not None:
    # facegrow：6-conn 面连接生长并入（生长天然面连通，零插入体素）
    (mask, n_comp6, n_bridge,
     merge_stats_t14c, _t14c_corridor) = facegrow_merge_6conn(
         mask26, vol, head_int, lab6p, main_lab6p, n6p, sizes6p)
    merge_stats_t14c["pharynx_label"] = pharynx_label_t14c
    merge_stats_t14c["pharynx_voxels"] = int(
        (lab6p == pharynx_label_t14c).sum())
    merge_stats_t14c["pharynx_merged"] = any(
        m["label"] == pharynx_label_t14c
        for m in merge_stats_t14c["merged_components"])
    # mop-up：生长不可达的残余 6-conn 子域规范序补桥兜底
    _mask_mop, n_comp6, _n_mop = bridge_to_6conn_canonical(mask, vol)
    if _n_mop > 0:
        n_bridge += _n_mop
        merge_stats_t14c["mopup_bridge_voxels"] = int(_n_mop)
    mask = _mask_mop
    print(f"    T14c facegrow 并合: 生长 {merge_stats_t14c['grown_voxels']:,} "
          f"体素（主域 {merge_stats_t14c['main_component_6conn_cells']:,} + "
          f"走廊 {merge_stats_t14c['corridor_voxels']} 介质体素 + 并入 "
          f"{len(merge_stats_t14c['merged_components'])} 组件，咽部 "
          f"{'已' if merge_stats_t14c['pharynx_merged'] else '未'}并入）；"
          f"mop-up 补桥 {n_bridge} 体素 -> 6-conn 组件 {n_comp6} 个"
          + ("（6-conn 单域）" if n_comp6 == 1
             else "（!!! 仍非 6-conn 单域，需人工复核）"))
elif (ARGS.merge_mode == "base"
        and pharynx_excluded_mask_t14c is not None):
    # base：仅最大 6-conn 连通域（对照变体 X1——无咽部并入、无补桥。
    #       pA/pB 咽部识别为空 -> 本分支不触发 -> 与 largest
    #       逐字节一致（回归铁闸））
    mask = (lab6p == main_lab6p)
    n_comp6, n_bridge = 1, 0
    merge_stats_t14c = {
        "mode": "base",
        "algorithm": ("largest 6-conn component only; pharynx and all "
                      "26-conn-diagonal components excluded (no bridge, "
                      "no insertion)"),
        "main_component_6conn_cells": int(mask.sum()),
        "main_component_k_range": [int(np.where(mask)[0].min()),
                                     int(np.where(mask)[0].max())],
        "excluded_pharynx_label": pharynx_label_t14c,
        "excluded_pharynx_voxels": (
            int(pharynx_excluded_mask_t14c.sum())
            if pharynx_excluded_mask_t14c is not None else 0),
        "excluded_pharynx_k_range": (
            [int(np.where(pharynx_excluded_mask_t14c)[0].min()),
             int(np.where(pharynx_excluded_mask_t14c)[0].max())]
            if pharynx_excluded_mask_t14c is not None else None),
        "note": ("T14c 对照变体 X1（pC-base）：咽部不并入、无补桥——"
                 "验证咽部 26-conn 并合界面是否首步失衡源（诊断报告10）"),
    }
    print(f"    T14c base 并合: 仅最大 6-conn 连通域 {int(mask.sum()):,} "
          f"体素"
          + (f"（咽部 {int(pharynx_excluded_mask_t14c.sum()):,} 体素"
             f"未并入）" if pharynx_excluded_mask_t14c is not None else "")
          + f"、无补桥 -> 6-conn 组件 {n_comp6} 个（单域）")
else:
    mask, n_comp6, n_bridge = bridge_to_6conn_canonical(mask26, vol)
print(f"    26-conn 识别 {n26} 组件 -> 主组件 "
      f"{int(mask26.sum())/1e6:.2f}M 体素；规范序补桥 "
      f"{n_bridge} 体素 -> 6-conn 组件 {n_comp6} 个"
      + ("（6-conn 单域）" if n_comp6 == 1
         else "（!!! 仍非 6-conn 单域，需人工复核）"))
# T14b 面连接修复（条件触发：n_bridge>0；pA n_bridge=0 -> no-op，
# step1/step2 产物逐字节回归铁闸）
fc_stats = None
if n_bridge > 0:
    fc_cfg_before = _count_diag_configs(mask)
    fc_pre_coords = _collect_config_coords(mask26)
    (mask, fc_edge_fixed, fc_corner_fixed, fc_inserted,
     fc_hu_min, fc_hu_max, fc_unfixable,
     fc_edge_after, fc_corner_after) = _face_connect_canonical(mask, vol)
    fc_post_coords = _collect_config_coords(mask)
    fc_rem_pre_e = len(fc_post_coords[0] & fc_pre_coords[0])
    fc_rem_int_e = len(fc_post_coords[0] - fc_pre_coords[0])
    fc_rem_pre_c = len(fc_post_coords[1] & fc_pre_coords[1])
    fc_rem_int_c = len(fc_post_coords[1] - fc_pre_coords[1])
    lab_fc, n_fc6 = ndimage.label(mask, structure=_S6)
    fc_stats = {
        "algorithm": ("edge_only -> 1 corner voxel (HU,coord lexmin); "
                      "corner_only -> 2-voxel face path (6 candidates, "
                      "HU-sum lexmin); canonical directions "
                      "(first nonzero positive), single-pass "
                      "detect+decide; iterate to fixpoint "
                      "(max_iter=10)"),
        "trigger": "n_bridge>0 (pA no-op: byte-identical regression)",
        "configs_before": {"edge_only": int(fc_cfg_before[0]),
                           "corner_only": int(fc_cfg_before[1])},
        "configs_fixed": {"edge": int(fc_edge_fixed),
                          "corner": int(fc_corner_fixed)},
        "voxels_inserted": int(fc_inserted),
        "inserted_hu_range": [int(fc_hu_min), int(fc_hu_max)],
        "hu_constraint": ("all inserted voxels HU<-300 (T13b red line); "
                          "zero soft-tissue intrusion"),
        "unfixable_hu_blocked_configs": int(fc_unfixable),
        "configs_after": {"edge_only": int(fc_edge_after),
                          "corner_only": int(fc_corner_after)},
        "remaining_split": {
            "edge_preexisting": int(fc_rem_pre_e),
            "edge_introduced": int(fc_rem_int_e),
            "corner_preexisting": int(fc_rem_pre_c),
            "corner_introduced": int(fc_rem_int_c)},
        "n_components_6conn_after": int(n_fc6),
        "note": ("T14b 补桥面连接修复（笔记本 v3 阻断根因：补桥对角接触 "
                 "-> 压力-速度耦合断裂；剩余配置候选体素 HU>=-300 "
                 "软组织/骨壁，红线阻止插入，如实计数）"),
    }
    print(f"    T14b 面连接修复：edge 修复 {fc_edge_fixed} / corner 修复 "
          f"{fc_corner_fixed} / 插入 {fc_inserted} 体素 "
          f"（HU [{fc_hu_min}, {fc_hu_max}]，全 < -300: "
          f"{fc_hu_max < -300}）/ HU 阻断不可修复 {fc_unfixable}；"
          f"修复后对角配置 edge {fc_edge_after} / corner "
          f"{fc_corner_after}（固有 {fc_rem_pre_e + fc_rem_pre_c} + "
          f"引入 {fc_rem_int_e + fc_rem_int_c}，均 HU 阻断）；"
          f"6-conn 组件 {n_fc6}"
          + ("（单域）" if n_fc6 == 1 else "（!!! 非单域）"))
# ---- T14c：桥区/并合界面体素坐标随包（诊断报告10 建议④——
#       笔记本侧 nonManifoldPoints 空间分布三分类（桥区/薄壁区/其他）
#       可复算；全分辨率 (k,j,i) 坐标，merge 模式 engaged 时落盘，
#       run_all 打入算例 zip 随包下发）----
merge_zone_npz_t14c = None
if merge_stats_t14c is not None:
    _main6 = (lab6p == main_lab6p)
    _nonmain26 = mask26 & ~_main6
    _bridge_in = mask & ~mask26
    _nm_dil = (ndimage.binary_dilation(_nonmain26, structure=_S26)
               & ~_nonmain26)
    _iface_nonmain = (_nonmain26
                      & ndimage.binary_dilation(_main6, structure=_S26))
    _iface_main = (_main6 & _nm_dil)
    _comp_rows = []
    _comp_cent = []
    _labs_in26 = set(np.unique(lab6p[mask26]).tolist())
    for _l in range(1, n6p + 1):
        if _l != main_lab6p and _l not in _labs_in26:
            continue
        _m = lab6p == _l
        _sz = int(_m.sum())
        if _sz == 0:
            continue
        _in26 = bool(_l in _labs_in26)
        _kk = np.where(_m)[0]
        _cm = np.argwhere(_m).mean(axis=0)
        _comp_rows.append([_l, _sz, int(_kk.min()), int(_kk.max()),
                           int(_in26), int(_l == main_lab6p),
                           int(bool((mask & _m).any()))])
        _comp_cent.append([float(_cm[0]), float(_cm[1]), float(_cm[2])])
    merge_zone_npz_t14c = f"bridge_zone_coords-{PREFIX}-{ARGS.case}.npz"
    _bz_bridge = np.ascontiguousarray(
        np.argwhere(_bridge_in), dtype=np.int32)
    _bz_corr = (np.ascontiguousarray(np.argwhere(_t14c_corridor),
                                       dtype=np.int32)
                if _t14c_corridor is not None
                else np.zeros((0, 3), dtype=np.int32))
    _bz_if_nm = np.ascontiguousarray(
        np.argwhere(_iface_nonmain), dtype=np.int32)
    _bz_if_m = np.ascontiguousarray(
        np.argwhere(_iface_main), dtype=np.int32)
    _bz_ph = (np.ascontiguousarray(
        np.argwhere(pharynx_excluded_mask_t14c), dtype=np.int32)
        if pharynx_excluded_mask_t14c is not None
        else np.zeros((0, 3), dtype=np.int32))
    np.savez_compressed(
        os.path.join(WS_OUT, "step2", merge_zone_npz_t14c),
        bridge_voxels=_bz_bridge,
        grow_corridor_voxels=_bz_corr,
        merge_interface_nonmain_voxels=_bz_if_nm,
        merge_interface_main_voxels=_bz_if_m,
        excluded_pharynx_voxels=_bz_ph,
        component_table=np.array(_comp_rows, dtype=np.int32),
        component_centroids=np.array(_comp_cent, dtype=np.float32))
    print(f"    T14c 桥区坐标随包: {merge_zone_npz_t14c}"
          f"（补桥体素 {len(_bz_bridge)} / 生长走廊 {len(_bz_corr)} / "
          f"并合界面 非主 {len(_bz_if_nm)} + 主 {len(_bz_if_m)} / "
          f"未并入咽部 {len(_bz_ph)} 体素；组件表 {len(_comp_rows)} 行"
          f"——列: label,size,k_min,k_max,in_mask26,is_main,"
          f"in_final_domain）")

cut = air & ~head_int
xs_all = np.arange(cols)
head_cols = head.sum(axis=(0, 1))          # (nz,rows,cols) -> 对 z 和 rows 求和 => 每列(cols=x)
head_cx = float((head_cols * xs_all).sum() / head.sum())
print(f"    气道 {mask.sum()/1e6:.2f}M 体素, 头外空气 {cut.sum()/1e6:.2f}M, 头中线 x={head_cx:.0f}")
# T12：mask 文件名按病例前缀隔离（pA 保持原命名向后兼容）
if PREFIX == "pA":
    _mask_name = "mask_full.npz" if ARGS.case == "v5" else f"mask_full-{ARGS.case}.npz"
else:
    _mask_name = f"mask_full-{PREFIX}-{ARGS.case}.npz"
# T14 帧序卫生（DeepSeek round2 §0.5 帧事故预警
# 落地）：26-conn 架构 engaged（n_bridge>0）时落盘
# z_frame 元数据（0 = 物理 z 升序帧——本脚本
# slices.sort(ImagePositionPatient[2]) 排序），防
# npy 帧混用事故（t14_pC/ling/vol_pC_hu16.npy
# 文件名序=物理降序 vs round2 物理升序，混用 xor
# 184,492 事故在案）。pA（n_bridge=0，架构
# no-op）不写 z_frame——mask npz 逐字节回归铁闸。
if n_bridge > 0 or merge_stats_t14c is not None:
    np.savez_compressed(os.path.join(WS_OUT, "step2", _mask_name),
                        mask=mask, cut=cut,
                        z_frame=np.array([0], dtype=np.int8))
else:
    np.savez_compressed(os.path.join(WS_OUT, "step2", _mask_name),
                        mask=mask, cut=cut)

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
# ---- T13b 注：降采样保持原版多数表决（≥4/8） ----
# 半块序列条件化降采样方案实测废除（2026-10-04）：
# 原算法满块在 pC 上为膨胀（连通域过滤前回归比
# 1.0816）——"主体层边缘块系统性损失"假设不成立；
# 回补（半块→有效层 x/y ≥2、满块→z 合计 ≥3/8）
# 实测过强（1.270）且破坏鼻孔管几何（ds2 k=38–44
# 膨胀 +29~+98 体素/层→鼻孔开口暴露面 102→55 面、
# 鼻中隔分组失效、inletL=0）。回归比 0.915 真因
# =鼻窦气腔经窦口自然断离（连通域过滤删除）+
# 细气道多数表决固有膨胀（主域口径 1.181）——
# 均为 pC 数据结构性特征，降采样算法本身
# 零改动——pA/pB/pC 同算法，已验证几何回归门禁
# （逐字节一致）保持。
def _blk2(a, zf_=2):
    k, j, i = a.shape
    k2, j2, i2 = k // zf_, j // 2, i // 2
    return a[:k2*zf_, :j2*2, :i2*2].astype(np.uint8)\
        .reshape(k2, zf_, j2, 2, i2, 2)
def _ds2_majority(blk, zf_=2):
    # 块体素 4*zf_ 的半数多数表决（zf=2: >=4/8 现状；
    # zf=1: >=2/4——z 向不降采样，仅 xy 2×2 表决）
    return blk.sum(axis=(1, 3, 5)) >= 2 * zf_
_blk_m = _blk2(mask, _zf)
_blk_votes = _blk_m.sum(axis=(1, 3, 5))      # (k2,j2,i2) 块票数
m = _ds2_majority(_blk_m, _zf)
c = _ds2_majority(_blk2(cut, _zf), _zf)      # cut 仅作分类判定，保持原算法
# ---- T14/L2'：6-conn 最小走廊守卫（DeepSeek round2
# §2.3/§5.1——替换 T13 迭代 OR 守卫：该守卫 26-conn
# 驱动，ds2 后已 26-conn 单域 -> 0 迭代 = no-op，
# 咽部仍被下方 6-conn 连通域过滤删除（t20 实测
# 在案：ds2 26-conn 1 域 / 6-conn 52 组件））----
# 算法（t25/t28 通过口径）：主域在 OR 表决网格
# （块票数 >=1，即 ds2_votes>=1）BFS 建前驱树 ->
# 每个非主域 6-conn 组件取其距主域最近 cell，沿
# 最短路径逐 cell 回写 -> 迭代至 6-conn 单域。
# 实测增量 pA +1 / pB +22 / pC +66 cells，
# pC 咽部 993/993 保留（t28 口径：全分辨率咽部
# 7,355 体素投影 ds2 与守卫输出交集 993 cells，
# 993/993 全在主 6-conn 组件）。
# 全孤立特判（T14 施工定案）：非主域组件全部为
# 1 体素（纯孤立体素噪声，pA 情形：仅 1 个 1 体素
# 组件）-> 守卫 no-op，交下方连通域过滤删除
# （pA 269,913 cells 逐字节回归铁闸。指挥官令
# "pA +1"为 DeepSeek 实验口径，与验收"pA step2
# 逐字节一致"冲突——实测忠实版 pA +1 cell 破坏
# 逐字节回归，本批按验收口径执行并看板披露）。
def minimal_corridor_guard(m_, d_or_, max_iter=60):
    """6-conn 驱动最小走廊守卫（确定性，无随机）。
    返回 (m_guard, n_iter, n_corridor_cells, n_comp6, all_single)。"""
    from collections import deque
    total_added = 0
    for it in range(max_iter):
        lab_, n_ = ndimage.label(m_, structure=_S6)
        if n_ <= 1:
            return m_, it, total_added, int(n_), False
        s_ = np.bincount(lab_.ravel())
        main_ = int(np.argmax(s_[1:]) + 1)
        comps_ = [l for l in range(1, n_ + 1) if l != main_]
        if all(int(s_[l]) <= 1 for l in comps_):
            # 全孤立特判：纯孤立体素噪声，守卫 no-op
            return m_, it, total_added, int(n_), True
        dist_ = np.full(m_.shape, -1, np.int32)
        prev_ = np.full(m_.shape + (3,), -1, np.int32)
        dq_ = deque()
        for cc in np.argwhere(lab_ == main_):
            dist_[tuple(cc)] = 0
            dq_.append(tuple(cc))
        dirs6_ = [(1, 0, 0), (-1, 0, 0), (0, 1, 0),
                  (0, -1, 0), (0, 0, 1), (0, 0, -1)]
        while dq_:
            k, j, i = dq_.popleft()
            dd = dist_[k, j, i]
            for (dk, dj, di) in dirs6_:
                kk, jj, ii = k + dk, j + dj, i + di
                if (0 <= kk < m_.shape[0] and 0 <= jj < m_.shape[1]
                        and 0 <= ii < m_.shape[2]):
                    if d_or_[kk, jj, ii] and dist_[kk, jj, ii] < 0:
                        dist_[kk, jj, ii] = dd + 1
                        prev_[kk, jj, ii] = (k, j, i)
                        dq_.append((kk, jj, ii))
        for l in comps_:
            cells = np.argwhere(lab_ == l)
            best_cell = None
            best_d = 1e9
            for cc in cells:
                dcv = dist_[tuple(cc)]
                if dcv >= 0 and dcv < best_d:
                    best_d = dcv
                    best_cell = tuple(cc)
            if best_cell is None:
                # OR 网格不可达组件：保留原状，
                # 交下方连通域过滤处置
                continue
            cur = best_cell
            while cur[0] >= 0:
                if not m_[cur]:
                    m_[cur] = True
                    total_added += 1
                p = prev_[cur]
                if p[0] < 0:
                    break
                cur = tuple(p)
    lab_, n_ = ndimage.label(m_, structure=_S6)
    return m_, max_iter, total_added, int(n_), False

_d_or = _blk_votes >= 1
m, guard_iter, guard_added, guard_ncomp6, guard_all_single = \
    minimal_corridor_guard(m, _d_or)
if guard_all_single:
    _g_note = ("全孤立特判：非主域组件皆 1 体素 -> "
               "守卫 no-op（交连通域过滤删除，"
               "pA 逐字节回归口径）")
elif guard_added > 0:
    _g_note = f"走廊回写 +{guard_added} cells"
else:
    _g_note = "无增量"
if guard_all_single:
    _g_tail = "（守卫后待过滤——预期态）"
elif guard_ncomp6 == 1:
    _g_tail = " -> 6-conn 单域"
else:
    _g_tail = "（!!! 仍非 6-conn 单域，需人工复核）"
print(f"    L2' 最小走廊守卫: 6-conn 组件 "
      f"{guard_ncomp6} 个；{_g_note}{_g_tail}")
# T14b：DS2 级守卫停工上报（指挥官令：z 向 2.0mm 多数表决降采样后断言
# 融合域 DS2 6-conn 面连通单域；不连通则走廊 OR 回写（有界迭代），
# 达迭代上限仍非单域即停工上报。全孤立特判（纯 1 体素噪声，交下方
# 连通域过滤删除）不触发——pA 逐字节回归铁闸。）
if n_bridge > 0 and guard_ncomp6 > 1 and not guard_all_single:
    print(f"    !!! T14b DS2 级守卫停工上报：n_bridge={n_bridge}，"
          f"守卫 {guard_iter} 轮迭代后仍 {guard_ncomp6} 个 6-conn 组件"
          f"（非全孤立特判）——融合域未达 DS2 6-conn 面连通单域，"
          f"按指挥官令停工上报（证据：ds2 {int(m.sum()):,} cells，"
          f"守卫增量 {guard_added} cells）")
    raise SystemExit(1)
# ★ 连通域过滤（笔记本缺陷6：多数表决降采样会产生孤立体素，导致p矩阵奇异→GAMG除零崩溃）
lab_m, n_m = ndimage.label(m, structure=ndimage.generate_binary_structure(3, 1))
# T13b：回归比病灶诊断（QC 证据链）——记录 ds2
# 组件体量分布与主域口径回归比，供闸门报错与
# 指挥官裁决（pC 实测：鼻窦气腔经细窦口与鼻腔
# 相连，多数表决后窦口断离成第二大组件被过滤
# 删除→全 mask 口径回归比失真；主域口径则因
# 细气道块平均票数低而膨胀——两病灶方向相反）
_t13b_diag = {"n_components": int(n_m)}
if n_m > 1:
    sizes_m = np.bincount(lab_m.ravel())
    _order = np.argsort(sizes_m[1:])[::-1] + 1
    _t13b_diag["main_cells"] = int(sizes_m[_order[0]])
    _t13b_diag["second_cells"] = int(sizes_m[_order[1]])
    _t13b_diag["second_ratio"] = round(
        float(sizes_m[_order[1]]) / max(int(m.sum()), 1), 4)
    # 主域对应全分辨率票数（主域口径回归比之分母）
    _main_vox = int(_blk_votes[lab_m == _order[0]].sum())
    _t13b_diag["main_domain_voxels"] = _main_vox
    keep = int(np.argmax(sizes_m[1:]) + 1)
    removed = n_m - 1
    m = lab_m == keep
    print(f"    连通域过滤: 删除 {removed} 个孤立组件（孤立体素会致求解奇异）")
else:
    print("    连通域过滤: 单一连通域，无需清理")
# ---- T13b：鼻腔朝向检测（构面前，端面窗口法） ----
# pC 实测（诊断报告8 病灶的深层根因）：pC 鼻腔在
# ds2 空间的 z 方向与 pA/pB 相反——鼻孔端在 z 小
# 端（ds2 k=16/17：鼻孔开口面邻接头外空气 cut，
# 左侧 k=16、右侧 k=17），鼻咽端在 z 大端
# （ds2 k=46：暴露面邻接头组织）。step2 原构面
# 逻辑（pA 系）假设"z 小端=鼻咽（出口）"——pC
# 上出口被定在鼻孔前庭末端（ds2 k=13，1 面
# 1.5045mm²）——出口漂移→15L/min÷1.5mm²≈166m/s
# 射流→GAMG 压力求解器 FPE（笔记本侧回报
# Run-A Time=16 / Run-B Time=23 步崩溃真因）。
# 检测法（diag9_T13b 三例标定）：鼻孔开口是气道
# 唯一与外界（头外空气 cut）连通的端面，位于气
# 道终端前庭内（pC 实测距低端 3 层）；鼻咽端被
# 咽壁包绕（cut 邻接 0）。判据：气道两端各 10
# 个 ds2 层端面窗口内 cut 邻接体素数——低端 >
# 高端 = 鼻孔端在 z 小端。
# 旧判据（全气道 cut 邻接体素 z 质心 vs 范围中点）
# 实测废除：pA/pB 鼻孔开口位于气道内部中段
#（pA ds2 k=48–51 计 710 体素、pB k=41–42 计 164
# 体素，距低端 41–48 层），质心落气道范围下半区
# →误判翻转→出口漂移（pA 536→56 面回归失败）；
# 端面窗口法 pA/pB 两端窗口 0/0→不翻转（零改动
# 回归门禁保持），pC 低端 102/高端 0→翻转（修复
# 生效）。
def _cut_adj_mask(m_, c_):
    st6 = ndimage.generate_binary_structure(3, 1)
    return m_ & ndimage.binary_dilation(c_, structure=st6)

_K2 = m.shape[0]
_k_lo_end = next(k for k in range(_K2) if m[k].any())
_k_hi_end = next(k for k in range(_K2 - 1, -1, -1)
                 if m[k].any())
_adj_all = _cut_adj_mask(m, c)
_adj_ks = np.where(_adj_all)[0]
_z_mean = float(_adj_ks.mean()) if len(_adj_ks) else 0.0
# 端面窗口判据（diag9 三例标定，见上方注释）：
# 两端各 10 个 ds2 层窗口内 cut 邻接体素数比较
_W_END = 10
_cut_low = int(_adj_all[_k_lo_end:_k_lo_end + _W_END].sum())
_cut_high = int(
    _adj_all[max(_k_lo_end, _k_hi_end - _W_END + 1):
             _k_hi_end + 1].sum())
NOSTRIL_AT_LOW = _cut_low > _cut_high
print(f"    鼻腔朝向检测: 气道 ds2 z 范围 "
      f"[{_k_lo_end},{_k_hi_end}]，cut 邻接体素 "
      f"{int(_adj_all.sum())} 个（端面 {_W_END} 层"
      f"窗口: 低 {_cut_low}/高 {_cut_high}；全气道"
      f" z 质心 {_z_mean:.1f} 仅 QC）→ 鼻孔端在"
      + ("z 小端（鼻咽端在 z 大端，出口端翻转）"
         "【T13b 朝向修复生效】" if NOSTRIL_AT_LOW
         else "z 大端/气道内部（pA 系朝向，出口端"
              "不翻转）"))
# ---- T13b：出口截面层重定义（全分辨率，方向感知） ----
# 出口端（朝向感知确定）以亚分辨率渐细尾巴收尾
#（B 核 1mm 层厚部分容积：pC 鼻咽端末端 1 体素、
# 每层 <1 个 ds2 体素），第一个实质截面
#（≥200 体素准入）才是 CFD 出口。阈值 200 为
# 回归门禁与 pC 校准双重约束下的取值：
# · pA/pB 出口端（z 小端）截面完整（数百–数千
#   体素 ≥200）→ 出口层 = 末端层、截断的是空层
#   → 零变化（回归逐字节一致门禁，实测验证）；
# · pC 鼻咽端渐细尾巴（末端 1–102 体素/层）
#   被跳过，出口层 = 首个实质截面 k=86（242
#   体素→ds2 82 块），多数表决保留 47/82
#   （0.57）→ 触发下方兜底 OR 并集回写 →
#   出口 82 面 ~123mm²（落 82.1–152.5mm² 验收带）。
# 阈值提高方案实测废除：400 使 pA/pB 出口端
# 截面（∈[200,400)）不达标→出口层内移、出口
# 漂移（pA 536→108 面、pB 236→118 面），
# 破坏已验证几何回归——严禁。渐细尾巴从 CFD
# 域截断（亚分辨率体素在 ds2 网格中不具几何
# 意义，保留反而构成"细弱颈部"使出口漂移
# ——pC-v1 病灶）。
sec_counts = mask.sum(axis=(1, 2))            # 全分辨率每层截面体素数
_k_nonempty = np.where(sec_counts > 0)[0]
k_full_min = int(_k_nonempty.min())
k_full_max = int(_k_nonempty.max())
_end_k = k_full_max if NOSTRIL_AT_LOW else k_full_min
if NOSTRIL_AT_LOW:
    # 出口端 = z 大端（鼻咽）：自末端向内找首个实质截面
    k_out_full = k_full_max
    for _k in range(k_full_max, -1, -1):
        if sec_counts[_k] >= 200:
            k_out_full = _k
            break
else:
    # 出口端 = z 小端（鼻咽，pA 系）：自末端向内找首个实质截面
    k_out_full = k_full_min
    for _k in range(k_full_min, mask.shape[0]):
        if sec_counts[_k] >= 200:
            k_out_full = _k
            break
# ---- T14/L3：出口通用化（主轴端面条件触发）----
# 触发判据（T14 exp1 实验 2 标定）：出口端 z 层
# 截面面积 <30mm2（全分辨率口径）——pA 259.1 /
# pB 195.8mm2 不触发（行为不变，回归逐字节一致）；
# pC 融合后出口端 k=0 截面 1.1mm2 触发 -> 出口
# 层改咽部实质截面：咽部面积曲线 A(k) 上首个
# A>=0.8*A_max 且双侧 |dA/A|<0.10 的稳定层
# （T14 exp1 实验 3：pC k=10，594 体素 / 223.4mm2 /
# 97.9%max / dA_in 0.021 / dA_out 0.049；备选 k=9
# 607 体素 228.3mm2——DeepSeek round2 §4.2/§5.1
# 出口口径 k=9/10）。原"首个 >=200 体素"扫描
# （pC k=6，115.8mm2，t26 口径）被稳定性准则
# 覆盖（指挥官令 T14 实现件 3：出口=咽部最大
# 截面 k=9/10）。
l3_triggered = False
l3_info = None
if pharynx_mask is not None:
    _end_area_mm2 = float(sec_counts[_end_k] * ps[0] * ps[1])
    if _end_area_mm2 < 30.0:
        l3_triggered = True
        _pa = pharynx_mask.sum(axis=(1, 2)).astype(np.int64)
        _nzp = np.where(_pa > 0)[0]
        _pkmin = int(_nzp.min())
        _pkmax = int(_nzp.max())
        _A = _pa[_pkmin:_pkmax + 1].astype(float) * ps[0] * ps[1]
        _Amax = float(_A.max())
        _rel = np.abs(np.diff(_A)) / np.maximum(_A[:-1], 1e-9)
        _rec_k = None
        _a_rec = _ri_rec = _ro_rec = None
        _scan = (range(_pkmin, _pkmax + 1) if not NOSTRIL_AT_LOW
                 else range(_pkmax, _pkmin - 1, -1))
        for _kk in _scan:
            _a = float(_pa[_kk] * ps[0] * ps[1])
            _ri = (_rel[_kk - _pkmin - 1]
                   if _kk - _pkmin - 1 >= 0 else np.inf)
            _ro = (_rel[_kk - _pkmin]
                   if _kk - _pkmin < len(_rel) else np.inf)
            if (_a >= 0.8 * _Amax and np.isfinite(_ri)
                    and np.isfinite(_ro)
                    and float(_ri) < 0.10 and float(_ro) < 0.10):
                _rec_k = int(_kk)
                _a_rec, _ri_rec, _ro_rec = _a, float(_ri), float(_ro)
                break
        l3_info = {
            "trigger": "outlet_end_section_mm2<30",
            "end_section_mm2": round(_end_area_mm2, 2),
            "pharynx_voxels": int(pharynx_mask.sum()),
            "pharynx_k_range": [_pkmin, _pkmax],
            "pharynx_Amax_mm2": round(_Amax, 1),
            "criterion": ("first k with A>=0.8*Amax and "
                          "both-side |dA/A|<0.10"),
            "selected_k": _rec_k,
            "selected_section_voxels": (int(_pa[_rec_k])
                                        if _rec_k is not None else None),
            "selected_section_mm2": (round(_a_rec, 1)
                                     if _rec_k is not None else None),
            "frac_of_max": (round(_a_rec / _Amax, 3)
                            if _rec_k is not None else None),
            "dA_in": (round(_ri_rec, 3) if _rec_k is not None else None),
            "dA_out": (round(_ro_rec, 3) if _rec_k is not None else None),
        }
        if _rec_k is not None:
            k_out_full = _rec_k
            print(f"    L3 出口通用化触发（出口端截面 "
                  f"{_end_area_mm2:.1f}mm2 < 30mm2）-> 咽部"
                  f"稳定性准则出口层 k={_rec_k}（{int(_pa[_rec_k])} "
                  f"体素 / {_a_rec:.1f}mm2 / "
                  f"{_a_rec / _Amax * 100:.1f}%max / "
                  f"dA_in {_ri_rec:.3f} / dA_out {_ro_rec:.3f}）"
                  f"【T14/L3 生效】")
        else:
            print(f"    L3 出口通用化触发但咽部曲线无稳定层"
                  f"（Amax {_Amax:.1f}mm2）-> 保留原出口层 "
                  f"k={k_out_full}")
k_out_ds = k_out_full // _zf     # T14d：z 因子参数化（zf=2 与原式逐字节一致；zf=1 不降采样——鼻咽截断层不再合并）
# ---- T13b 修复 1：渐细尾巴截断（方向感知） ----
if NOSTRIL_AT_LOW:
    _tail_vox = int(m[k_out_ds + 1:].sum())
    m[k_out_ds + 1:] = False
else:
    _tail_vox = int(m[:k_out_ds].sum())
    m[:k_out_ds] = False
print(f"    出口截面层重定义: 全分辨率末端 k={_end_k}（截面 "
      f"{int(sec_counts[_end_k])} 体素）→ 实质截面层 k={k_out_full}"
      f"（截面 {int(sec_counts[k_out_full])} 体素）→ ds2 k={k_out_ds}；"
      f"渐细尾巴截断 {_tail_vox} ds2 体素【T13b 修复 1 生效】")
# ---- T13b 兜底：出口截面层多数表决塌缩豁免（重定义后的出口层） ----
# 出口层重定义后若 ds2 层仍塌缩（多数表决保留率 <0.7——pC 鼻咽端
# 渐细截面 k=86 实测 47/82=0.57 触发；pA/pB 出口端截面完整
# 保留率 0.95–0.99 不触发），按 x/y 2×2 OR 并集回写（只增不减
# ——等价于指挥官令第一步"出口截断层豁免多数表决降采样、原样
# 保留"的 ds2 实现：凡含气道体素的 2×2 块全部保留，零表决损失）。
outlet_exempt = False
n_or = n_keep = 0
keep_ratio = 1.0
if k_out_ds < m.shape[0]:
    _j2, _i2 = m.shape[1], m.shape[2]
    _sec = mask[k_out_full, :_j2 * 2, :_i2 * 2].reshape(_j2, 2, _i2, 2)
    _sec_or = _sec.sum(axis=(1, 3)) >= 1
    n_or = int(_sec_or.sum())
    n_keep = int(m[k_out_ds].sum())
    keep_ratio = (n_keep / n_or) if n_or > 0 else 1.0
    print(f"    出口截面层: 全分辨率 k={k_out_full} → ds2 k={k_out_ds}；"
          f"多数表决保留 {n_keep}/{n_or} 体素（保留率 {keep_ratio:.2f}）")
    if n_or > 0 and keep_ratio < 0.7:
        m[k_out_ds] |= _sec_or
        outlet_exempt = True
        print(f"    !!! 出口层多数表决塌缩（保留率 {keep_ratio:.2f} < 0.7）"
              f"→ 豁免回写 OR 截面并集（{n_or} 体素）【T13b 兜底生效】")
    else:
        print(f"    出口层保留正常（保留率 {keep_ratio:.2f} ≥ 0.7），零改动")
# （连通域过滤已上移至降采样段——朝向检测须在
#  过滤后 m 上执行；回归比病灶诊断随之上移）
K, J, I = m.shape
dx, dy, dzz = ps[1] * 2 / 1000.0, ps[0] * 2 / 1000.0, dz * _zf / 1000.0   # T14d：z 向体素尺寸 = 源层厚 × zf
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
            elif axis == 2 and sgn == -1 and k0 == k_min \
                    and not NOSTRIL_AT_LOW:
                cls = "outlet"
            elif axis == 2 and sgn == +1 and k0 == k_max \
                    and not NOSTRIL_AT_LOW:
                cls = "walls"
            elif axis == 2 and sgn == +1 and k0 == k_max \
                    and NOSTRIL_AT_LOW:
                # T13b 朝向翻转：鼻孔端在 z 小端时，
                # z 大端（k_max）为鼻咽端 → 出口；
                # k_min 端（鼻孔端）的 -z 面走下方
                # 通用分类（邻接头外空气 → inlet）
                cls = "outlet"
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
# T13b 朝向感知：NOSTRIL_AT_LOW 时底面（k=0）是
# 鼻孔侧 → 入口（鼻孔向 -z 延伸出扫描范围），
# 顶面（k=K-1）是鼻咽侧 → 出口；pA 系朝向
# 反之（原逻辑：底面=鼻咽侧出口、顶面=闭合墙）。
if k_min == 0:   # 扫描底面
    _bd_cls = "inlet" if NOSTRIL_AT_LOW else "outlet"
    for (j0, i0) in np.argwhere(m[0]):
        patches[_bd_cls].append((quad_pts(int(i0), int(j0), 0, 2, -1), ids[0, int(j0), int(i0)]))
if k_max == K - 1:  # 数组顶面
    _tp_cls = "outlet" if NOSTRIL_AT_LOW else "walls"
    for (j0, i0) in np.argwhere(m[K - 1]):
        patches[_tp_cls].append((quad_pts(int(i0), int(j0), K - 1, 2, +1), ids[K - 1, int(j0), int(i0)]))
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
A_out, ctr_out = patch_info("outlet")   # T13b：出口截面面积（case_stats 记录 + run_all 出口多面断言数据源）
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
print(f"    outlet: 面积 {A_out*1e6:.1f} mm2（T13b 记录，出口多面断言数据源）")

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
B_DIR = os.path.join(WS_OUT, "step2", f"P0-OF-case-{PREFIX}-{ARGS.case}B")
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
    "case": f"P0-OF-case-{PREFIX}-{ARGS.case} (Run-A 指定流量) + P0-OF-case-{PREFIX}-{ARGS.case}B (Run-B 压力驱动自然分流)",
    "cells": ncells, "internal_faces": n_internal,
    "patch_face_counts": patch_counts,
    "inletL": info["inletL"], "inletR": info["inletR"],
    "outlet_area_mm2": round(A_out * 1e6, 1),
    "nostril_at_low": NOSTRIL_AT_LOW,
    "t13b_orientation": {
        "cut_adj_low_end": _cut_low,
        "cut_adj_high_end": _cut_high,
        "end_window_layers": _W_END,
        "cut_adj_total": int(_adj_all.sum()),
        "cut_adj_z_mean": round(_z_mean, 1),
        "note": ("鼻腔朝向检测（端面窗口法，diag9 三例"
                 "标定）：气道两端各 10 个 ds2 层窗口内"
                 "气道体素与头外空气（cut）6 邻接体素"
                 "数——鼻孔开口是气道唯一与外界连通的"
                 "端面（终端前庭内）；低端>高端=鼻孔端"
                 "在 z 小端（pC：102/0→翻转）；pA/pB "
                 "鼻孔开口在气道内部中段（两端窗口 "
                 "0/0）→不翻转，出口=z 小端鼻咽（原"
                 "构面约定）"),
    },
    "t13b_outlet_layer_fix": {
        "k_full_res_end": _end_k,
        "end_section_voxels": int(sec_counts[_end_k]),
        "k_full_res_outlet": k_out_full,
        "outlet_section_voxels": int(sec_counts[k_out_full]),
        "k_ds2": k_out_ds,
        "tail_voxels_removed": _tail_vox,
        "majority_kept_voxels": n_keep, "section_or_voxels": n_or,
        "keep_ratio": round(keep_ratio, 3),
        "exempt_applied": outlet_exempt,
        "note": ("鼻腔朝向检测（端面窗口 z 小端 "
                 f"{_cut_low}/z 大端 {_cut_high}）→"
                 + ("鼻孔端在 z 小端（pC 朝向）：出口端"
                    "翻转至 z 大端，出口截面层重定义至"
                    "首个实质截面层（截面≥200 体素"
                    "=实质截面准入），鼻咽端渐细尾巴"
                    "截断"
                    if NOSTRIL_AT_LOW
                    else "pA 系朝向（鼻孔端在 z 大端）："
                         "出口端 z 小端，截面完整零截断")
                 + ("；出口层塌缩→OR 并集回写（兜底）"
                    if outlet_exempt else "")),
    },
    "t13b_regression_diagnosis": {
        **_t13b_diag,
        "main_domain_volume_cm3": round(
            _t13b_diag.get("main_domain_voxels", 0)
            * ps[0] * ps[1] * dz / 1000, 2),
        "note": ("ds2 组件体量分布（回归比病灶诊断）："
                 "鼻窦气腔经细窦口与鼻腔相连，多数表决后"
                 "窦口断离成第二大组件被连通域过滤删除"
                 "→全 mask 口径回归比失真（分母含鼻窦）；"
                 "主域口径则因细气道块平均票数低而膨胀"
                 "——两病灶方向相反，pC 数据结构性特征"),
    },
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
# ---- T14 架构诊断字段（条件写入：pA 三重 no-op
#       ——n_bridge=0 且守卫无增量且 L3 未触发——
#       不写任何字段，case_stats.json 逐字节回归
#       铁闸；pB/pC 架构 engaged 时全量写入）----
if l3_triggered:
    stats["t13b_outlet_layer_fix"][
        "l3_outlet_generalization"] = l3_info
if (n_bridge > 0 or guard_added > 0 or l3_triggered
        or merge_stats_t14c is not None):
    stats["t14_arch"] = {
        "T14d_ds2_z_factor": {
            "voxel_z_mm": ARGS.voxel_z,
            "z_factor": int(_zf),
            "source_slice_thickness_mm": round(dz, 4),
            "xy_factor": 2,
            "vote_threshold": (f">=2*zf（块体素 4*zf 的半数"
                               f"多数表决；zf={_zf} 即 "
                               f">= {2 * _zf}/{4 * _zf}）"),
            "note": ("T14d z 降采样参数化：默认 2.0=现状 "
                     "zf=2 逐字节兼容；E1=1.0 不降采样"
                     "（pC 源序列层厚 1.0mm 全分辨率 z 向）"),
        },
        "L1_segmentation_26conn": {
            "conn_identification": "26-conn",
            "n_components_26conn": int(n26),
            "main_component_26conn_cells": int(mask26.sum()),
            "bridge_voxels": int(n_bridge),
            "n_components_6conn_after_bridge": int(n_comp6),
            "bridge_criterion": ("canonical (k,j,i) lexorder; "
                                 "diagonal candidate by (HU, coord); "
                                 "HU<-300"),
        },
        "L1b_face_connect": (fc_stats if fc_stats is not None else {
            "engaged": False,
            "note": "n_bridge=0 -> face-connect repair no-op (pA regression path)"}),
        "pharynx": {
            "identified": pharynx_mask is not None,
            "voxels": (int(pharynx_mask.sum())
                       if pharynx_mask is not None else 0),
            "k_range": ([int(np.where(pharynx_mask)[0].min()),
                         int(np.where(pharynx_mask)[0].max())]
                        if pharynx_mask is not None else None),
            "identification_criterion": ("pre-bridge 6-conn label, "
                                         "non-main component, "
                                         "volume>1000 voxels, "
                                         "k_min<=2, merged into "
                                         "26-conn main domain"),
        },
        "L2_minimal_corridor_guard": {
            "algorithm": ("6-conn driven minimal corridor "
                          "(t25/t28): BFS predecessor tree on "
                          "OR-vote grid (>=1 vote); shortest-path "
                          "writeback per non-main 6-conn component"),
            "all_single_special_case": bool(guard_all_single),
            "corridor_cells_added": int(guard_added),
            "iterations": int(guard_iter),
            "n_components_6conn_after": int(guard_ncomp6),
        },
        "L3_outlet_generalization": l3_info,
        "z_frame_metadata": ("npz z_frame=0 (physical z ascending) "
                             "written" if (n_bridge > 0
                                           or merge_stats_t14c is not None)
                             else None),
        "note": ("T14 架构修复（患者C 咽部 2.77cm3 真实解剖"
                 "纳入；DeepSeek round2 §2/§5；Ling L2 守卫 "
                 "no-op 否决实验与 pA +1 口径冲突披露在案）+ "
                 "T14b 面连接修复（补桥对角接触 -> 面连接通路；"
                 "笔记本 v3 阻断根因修复）"),
    }
    # T14c：并合模式扩展（仅 facegrow/base engaged 时写入——
    #       pA/pB 咽部识别为空不触发，case_stats 逐字节回归铁闸）
    if merge_stats_t14c is not None:
        stats["t14_arch"]["merge_mode"] = ARGS.merge_mode
        stats["t14_arch"]["L1c_merge_mode"] = merge_stats_t14c
        stats["t14_arch"]["merge_zone_coords_npz"] =             merge_zone_npz_t14c
        stats["t14_arch"]["merge_zone_coords_format"] = {
            "bridge_voxels": "L1 补桥/mop-up 插入体素 (k,j,i) int32",
            "grow_corridor_voxels": ("facegrow 生长走廊介质体素 "
                                     "(k,j,i) int32（base 为空）"),
            "merge_interface_nonmain_voxels": ("mask26 内非主 6-conn "
                                               "组件中与主域 26-conn "
                                               "邻接的体素 (k,j,i)"),
            "merge_interface_main_voxels": ("主域中与非主组件 26-conn "
                                            "邻接的体素 (k,j,i)"),
            "excluded_pharynx_voxels": ("base 模式未并入咽部体素 "
                                        "(k,j,i)（facegrow 为空）"),
            "component_table": ("mask26 内 6-conn 组件表 int32，"
                                "列: label,size,k_min,k_max,"
                                "in_mask26,is_main,in_final_domain"),
            "component_centroids": "组件质心 (k,j,i) float32",
        }
        if pharynx_excluded_t14c is not None:
            stats["t14_arch"]["pharynx"][
                "excluded_by_merge_mode"] = pharynx_excluded_t14c
if ARGS.ext or ARGS.iso or ARGS.case != "v5":
    if PREFIX == "pA":
        stats["t11_variant"] = {
            "case_name": ARGS.case,
            "extension_cylinders": ext_cylinders,
            "iso": ("去窦对照：step3_make_narrowing.py §2 同法（全分辨率腐蚀3→最大连通域→膨胀3&掩码）" if ARGS.iso else None),
            "note": "T11 合规对照算例：v5/v5B/v5C 系基线已冻结，本算例仅作披露对照，不进演示基线",
        }
    else:
        stats["t12_variant"] = {
            "case_name": ARGS.case,
            "extension_cylinders": ext_cylinders,
            "iso": ("去窦对照：step3_make_narrowing.py §2 同法（全分辨率腐蚀3→最大连通域→膨胀3&掩码）" if ARGS.iso else None),
            "note": "T12 多患者通用化算例：与患者A 全系隔离的独立病例，不进演示基线",
        }
# T12：case_stats 文件名按病例前缀隔离（pA 保持原命名向后兼容）
if PREFIX == "pA":
    stats_file = "case_stats.json" if ARGS.case == "v5" else f"case_stats-{ARGS.case}.json"
else:
    stats_file = f"case_stats-{PREFIX}-{ARGS.case}.json"
with open(os.path.join(WS_OUT, "step2", stats_file), "w", encoding="utf-8") as f:
    json.dump(stats, f, ensure_ascii=False, indent=2)
print("\n[完成]", CASE_DIR)
print(json.dumps(stats, ensure_ascii=False, indent=2))
