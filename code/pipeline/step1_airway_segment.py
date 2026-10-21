# -*- coding: utf-8 -*-
"""
P0 阶段1 v2：鼻腔气道三维重建（修正版）
修正点：鼻孔开放导致 3D 连通失败 → 改用"逐层2D头部填充"法：
  气道 = 空气 ∧ 头部组织二值图填洞后的头内部
"""
import os, json, glob, argparse
import numpy as np
from airway_geom import centroid_split_x, read_ct_series  # 与回归测试共用同一份实现：x 向质心/左右分界、DICOM 读入规则
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

# T12 补丁（多患者通用化）：DICOM 目录/输出目录/病例前缀/分割阈值全部 CLI 参数化。
# 默认值 = 患者A 路径与阈值（向后兼容：默认参数输出与原版逐字节一致）。
_ap = argparse.ArgumentParser(description="P0 阶段1 v2：鼻腔气道三维重建（逐层2D头部填充法）")
_ap.add_argument("--dicom-dir", default=os.path.expandvars(r"%DATA_ROOT%\参赛群资料\患者A\脱敏后图像数据\ISO_Soft_0.35mm_合并"),
                 help="DICOM 目录（默认患者A 序列，向后兼容）")
_ap.add_argument("--out-dir", default=os.path.expandvars(r"%QIDI_WORKSPACE%\contest3_workspace\pipeline\out\step1"),
                 help="输出目录（默认 pipeline/out/step1）")
_ap.add_argument("--case-prefix", default="pA",
                 help="病例前缀（默认 pA；输出文件名 airway_<prefix>_v2.stl 等）")
_ap.add_argument("--hu-air", type=int, default=-400,
                 help="空气阈值 HU（默认 -400，§5.3 允许口径）")
_ap.add_argument("--hu-head", type=int, default=-300,
                 help="头部组织阈值 HU（默认 -300）")
_ap.add_argument("--patient-label", default="A (soft tissue window, ISO 0.35mm)",
                 help="metrics patient 字段（默认患者A 描述，向后兼容）")
_ap.add_argument("--closing", action="store_true",
                 help="T14 可选：STL 水密修复 closing(3,3,3)（默认关；"
                      "患者C 融合域在扫描底面截断非水密，closing 达成水密"
                      "但体积 +15%%——仅 step1 STL 质量修复，step2 算例口径"
                      "不用 closing，DeepSeek round2 §3-Q3）")
# T14c 补丁（诊断决定轮·对照实验）：并合模式三选一。
# largest=现状默认（26-conn 识别+规范序 HU<-300 补桥）；
# facegrow=咽部以 6-conn 面连接生长并入主域（BFS 只走 6-conn
#   面-邻接步，生长介质=头内部 HU<-300 体素，可达即并入、
#   不可达即不并入——生长天然面连通，零插入体素）；
# base=仅最大 6-conn 连通域（无咽部并入、无补桥，对照变体 X1）。
# pA/pB 咽部本就 6-conn 连通于主域（咽部识别为空）-> facegrow/
# base 分支不触发，与 largest 逐字节一致（回归铁闸）。
_ap.add_argument("--merge-mode", default="largest",
                 choices=["largest", "facegrow", "base"],
                 help="T14c 并合模式（largest 现状默认/facegrow 6-conn "
                      "面连接生长并入咽部/base 仅最大 6-conn 连通域）")
ARGS = _ap.parse_args()
DATA_DIR = os.path.expandvars(ARGS.dicom_dir)
OUT_DIR = os.path.expandvars(ARGS.out_dir)
PREFIX = ARGS.case_prefix
HU_AIR = ARGS.hu_air
HU_HEAD = ARGS.hu_head
# 输出文件名：pA 前缀与原版一致（airway_pA_v2.stl / area_curve_v2.png ...）；
# 其他前缀追加 _{prefix} 隔离（airway_pB_v2.stl / area_curve_pB_v2.png ...）
_suf = "" if PREFIX == "pA" else f"_{PREFIX}"
STL_NAME = f"airway_{PREFIX}_v2.stl"
CURVE_PNG = f"area_curve{_suf}_v2.png"
VIEWS_PNG = f"mask_views{_suf}_v2.png"
CSV_NAME = f"area_per_slice{_suf}_v2.csv"
METRICS_NAME = f"metrics{_suf}_v2.json"
# 病例字母（标题/图注用）：pA->A, pB->B
_letter = PREFIX[1].upper() if len(PREFIX) > 1 and PREFIX[0].lower() == "p" else PREFIX.upper()
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(os.path.join(OUT_DIR, "qc_fig"), exist_ok=True)

# ---------- 1. 读入 ----------
files = sorted(glob.glob(os.path.join(DATA_DIR, "*.dcm")))
if not files:
    print("[错误] 在目录未找到任何 DICOM 文件（*.dcm）：" + DATA_DIR)
    print("请通过 --dicom-dir 或环境变量 P0_DICOM_DIR 指定真实 CT 的 DICOM 目录后再运行。")
    raise SystemExit(1)
# 真实上传目录的匹配规则（airway_geom.read_ct_series，与回归测试共用同一份实现）：
#   逐文件过滤（读不开 / 非图像 / 缺 IPP 或 Rows,Columns）并计数，绝不中断；
#   按 SeriesInstanceUID 只留层数最多的一组（scout、报告、DICOMDIR 全部挡在外面）；
#   同 z 去重；有效层 < 2 直接报错退出。两行摘要（[1/7] 与序列选择）由它打印。
slices, _slices_sel = read_ct_series(files)
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
head = vol > HU_HEAD
head_int = np.zeros((nz, rows, cols), dtype=bool)
for i in range(nz):
    head_int[i] = ndimage.binary_fill_holes(head[i])
print(f"    头部体素 {head.sum()/1e6:.1f}M, 头内部 {head_int.sum()/1e6:.1f}M")

# ---------- 3. 气道 = 头内部 ∧ 空气 ----------
air = vol < HU_AIR
airway_all = air & head_int
print(f"[3/7] 头内空气: {airway_all.sum()/1e6:.2f}M 体素 = {airway_all.sum()*vox_vol/1000:.2f} cm3")

# ---------- 4. 连通域分析（区分 气道路径 / 鼻窦 / 其他） ----------
# T14/L1（架构修复·患者C 咽部纳入；DeepSeek round2
# §2.1/§5.1）：识别结构元改为 26-邻接。6-conn 下咽部
# （鼻咽/口咽本体）是独立组件被丢弃（pC 7,355 体素
# = 2.77cm³ 真实解剖）——26-conn 识别后经对角邻接并入
# 主组件（实测：pA 逐字节 +0、pB +7、pC +7,620 体素；
# 鼻窦与主域距离 ≥3.76mm > 对角接触半径 1.73mm，
# 三例均不误并）。26-conn 主组件在 6-conn 下分裂
# （pC 29 子域），须配下方显式补桥方可输出 6-conn
# 单域——体素六面体网格器要求 6-邻接连通（t14 §4.1
# 实测：不补桥 = 29 不连通块 + 10 孤立单元 = 不可解）。
_S26 = np.ones((3, 3, 3), dtype=bool)
lab, n = ndimage.label(airway_all, structure=_S26)
sizes = np.bincount(lab.ravel())
order = np.argsort(sizes)[::-1]
print(f"[4/7] 头内气腔连通域(26-conn): {n} 个, 前8:")
comps = []
for l in order[:9]:
    if l == 0: continue
    idx = np.where(lab == l)
    zc = idx[0].mean(); vol_cm3 = sizes[l]*vox_vol/1000
    comps.append((int(l), int(sizes[l]), float(vol_cm3), float(zc)))
    print(f"    #{l}: {sizes[l]} 体素 = {vol_cm3:.2f} cm3, z中心层 {int(zc)+1}")
main_lab = comps[0][0]
mask26 = lab == main_lab

# ---- T14c：咽部预识别（补桥前 6-conn label 判据，与 step2 一致：
#       非主组件、体积>1000 体素、k_min<=2、且并入 26-conn 主域）。
#       pA/pB 无候选组件 -> None：facegrow/base 分支不触发（回归铁闸）。
lab6_t14c, n6_t14c = ndimage.label(
    airway_all, structure=ndimage.generate_binary_structure(3, 1))
sizes6_t14c = np.bincount(lab6_t14c.ravel())
main_lab6_t14c = int(np.argmax(sizes6_t14c[1:]) + 1)
pharynx_mask_t14c = None
pharynx_label_t14c = None
for _l in range(1, n6_t14c + 1):
    if _l == main_lab6_t14c or sizes6_t14c[_l] <= 1000:
        continue
    _kk6 = np.where(lab6_t14c == _l)[0]
    if int(_kk6.min()) > 2:
        continue
    if not ((lab6_t14c == _l) & mask26).any():
        continue
    pharynx_mask_t14c = lab6_t14c == _l
    pharynx_label_t14c = int(_l)
    break

# ---- T14/L1：规范序 HU 过滤补桥（26-conn 域 -> 6-conn 单域） ----
# 依据 t14_pC/deepseek/round2 §2.2（t19 规范序实证）：
# 对 6-conn 不同子域间 26-邻接（对角）体素对，在两个
# 单轴中间体素中取 HU<-300 者插入（空气/部分容积体素
# ——实测 pC 插入 210 体素 HU 全落 [-400,-300)，零软
# 组织侵入；被拒对角对 382 为软组织隔开，正确拒绝）。
# 确定性（T4）：边界体素按 (k,j,i) 字典序（np.lexsort）、
# 候选按 (HU,坐标) 择最低——消除遍历顺序依赖（实测乱序
# 遍历 207/208/208≠210），同输入双跑逐字节一致。
def bridge_to_6conn_canonical(mask26_, vol_, hu_max=-300, max_iter=80):
    """26-conn 掩码 -> 6-conn 单域（规范序 HU 过滤补桥）。
    返回 (bridged, n_comp6, n_inserted)。"""
    bridged = mask26_.copy()
    n_ins = 0
    shape = bridged.shape
    dirs = [(dk, dj, di) for dk in (-1, 0, 1) for dj in (-1, 0, 1)
            for di in (-1, 0, 1)
            if sum(1 for x in (dk, dj, di) if x != 0) >= 2]
    for _it in range(max_iter):
        lab_, n_ = ndimage.label(
            bridged, structure=ndimage.generate_binary_structure(3, 1))
        if n_ <= 1:
            break
        boundary = bridged & ndimage.binary_dilation(~bridged, structure=_S26)
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
    lab_, n_ = ndimage.label(
        bridged, structure=ndimage.generate_binary_structure(3, 1))
    return bridged, n_, n_ins

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
merge_stats_t14c = None
if ARGS.merge_mode == "facegrow" and pharynx_mask_t14c is not None:
    # facegrow：6-conn 面连接生长并入（生长天然面连通，零插入体素）
    (airway, n_comp6, n_bridge,
     merge_stats_t14c, _corr_t14c) = facegrow_merge_6conn(
         mask26, vol, head_int, lab6_t14c, main_lab6_t14c,
         n6_t14c, sizes6_t14c)
    merge_stats_t14c["pharynx_label"] = pharynx_label_t14c
    merge_stats_t14c["pharynx_voxels"] = int(pharynx_mask_t14c.sum())
    merge_stats_t14c["pharynx_merged"] = any(
        m["label"] == pharynx_label_t14c
        for m in merge_stats_t14c["merged_components"])
    # mop-up：生长不可达的残余 6-conn 子域规范序补桥兜底
    _airway_mop, n_comp6, _n_mop = bridge_to_6conn_canonical(airway, vol)
    if _n_mop > 0:
        n_bridge += _n_mop
        merge_stats_t14c["mopup_bridge_voxels"] = int(_n_mop)
    airway = _airway_mop
    print(f"    T14c facegrow 并合: 生长 {merge_stats_t14c['grown_voxels']:,} "
          f"体素（主域 {merge_stats_t14c['main_component_6conn_cells']:,} + "
          f"走廊 {merge_stats_t14c['corridor_voxels']} 介质体素 + 并入 "
          f"{len(merge_stats_t14c['merged_components'])} 组件，咽部 "
          f"{'已' if merge_stats_t14c['pharynx_merged'] else '未'}并入）；"
          f"mop-up 补桥 {n_bridge} 体素 -> 6-conn 组件 {n_comp6} 个"
          + ("（6-conn 单域）" if n_comp6 == 1
             else "（!!! 仍非 6-conn 单域，需人工复核）"))
elif ARGS.merge_mode == "base" and pharynx_mask_t14c is not None:
    # base：仅最大 6-conn 连通域（对照变体 X1——无咽部并入、无补桥）
    airway = (lab6_t14c == main_lab6_t14c)
    n_comp6, n_bridge = 1, 0
    merge_stats_t14c = {
        "mode": "base",
        "algorithm": ("largest 6-conn component only; pharynx and all "
                      "26-conn-diagonal components excluded (no bridge, "
                      "no insertion)"),
        "main_component_6conn_cells": int(airway.sum()),
        "main_component_k_range": [
            int(np.where(airway)[0].min()),
            int(np.where(airway)[0].max())],
        "excluded_pharynx_label": pharynx_label_t14c,
        "excluded_pharynx_voxels": int(pharynx_mask_t14c.sum()),
        "excluded_pharynx_k_range": [
            int(np.where(pharynx_mask_t14c)[0].min()),
            int(np.where(pharynx_mask_t14c)[0].max())],
        "note": ("T14c 对照变体 X1（pC-base）：咽部不并入、无补桥——"
                 "验证咽部 26-conn 并合界面是否首步失衡源（诊断报告10）"),
    }
    print(f"    T14c base 并合: 仅最大 6-conn 连通域 {int(airway.sum()):,} "
          f"体素（咽部 {int(pharynx_mask_t14c.sum()):,} 体素未并入、"
          f"无补桥）-> 6-conn 组件 {n_comp6} 个（单域）")
else:
    airway, n_comp6, n_bridge = bridge_to_6conn_canonical(mask26, vol)
    print(f"    规范序 HU 过滤补桥: 插入 {n_bridge} 体素"
          f" -> 6-conn 组件 {n_comp6} 个"
          + ("（6-conn 单域）" if n_comp6 == 1
             else "（!!! 仍非 6-conn 单域，需人工复核）"))
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
# 左右分界（x 轴）：x 向质心 = 沿 z、y 两轴求和后的 x 边缘分布的重心。
# 2026-10-21 修复（服务器实测非方形体数据 (230,308,360) 崩溃）：
# 旧式 airway.sum(axis=2).sum(axis=0) 先沿 x 再沿 z 求和 -> 长度 ny 的 y 分布，
# 与长度 nx 的 xs 相乘 -> ValueError: shapes (308,) (360,)；方形视野虽不崩，
# 但拿 y 分布乘 x 坐标语义错 -> 左右分界错位。实现见 airway_geom.centroid_split_x。
cx, mid = centroid_split_x(airway)
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
# T14 可选 closing：pC 融合域在扫描底面截断 -> 非水密；
# closing(3,3,3) 修复水密（体积 +15%，仅 STL 质量修复，
# step2 算例口径不用——DeepSeek round2 §3-Q3）
airway_stl = (ndimage.binary_closing(
    airway, structure=_S26) if ARGS.closing else airway)
verts, faces, _, _ = marching_cubes(airway_stl.astype(np.uint8), level=0.5,
                                    spacing=(dz, ps[0], ps[1]))
mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=True)
mesh.fix_normals()
if _smooth is not None:
    try:
        _smooth(mesh, iterations=8)
    except Exception as e:
        print("    平滑跳过:", e)
stl_path = os.path.join(OUT_DIR, STL_NAME)
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
ax.set_title(f"Patient {_letter} nasal airway cross-section curve | vol {total_cm3:.1f} cm3")
ax.legend(); ax.grid(alpha=0.3)
fig.savefig(os.path.join(OUT_DIR, CURVE_PNG), dpi=130, bbox_inches="tight")
plt.close(fig)

fig2, axs = plt.subplots(1, 3, figsize=(13, 4.5))
axs[0].imshow(airway[min_idx], cmap="gray"); axs[0].set_title(f"axial @min layer {min_idx+1} ({min_area:.0f}mm2)")
col_mid = int(np.median(np.where(airway.sum(axis=(0, 1)) > 0)[0]))
row_mid = int(np.median(np.where(airway.sum(axis=(0, 2)) > 0)[0]))
axs[1].imshow(airway[:, :, col_mid][::-1], cmap="gray", aspect=1.0); axs[1].set_title(f"coronal @col {col_mid}")
axs[2].imshow(airway[:, row_mid, :][::-1], cmap="gray", aspect=dz/ps[0]); axs[2].set_title(f"sagittal @row {row_mid}")
for a in axs: a.axis("off")
fig2.savefig(os.path.join(OUT_DIR, VIEWS_PNG), dpi=130, bbox_inches="tight")
plt.close(fig2)

# ---------- T12：QC 图（中层切片 mask 叠加 CT，人工可读） ----------
_any_z = airway.any(axis=(1, 2))
k_lo = int(np.argmax(_any_z))
k_hi = nz - 1 - int(np.argmax(_any_z[::-1]))
k_mid = int((k_lo + k_hi) // 2)
ct = vol[k_mid].astype("float64")
_win_lo, _win_hi = -500.0, 500.0
ctwin = np.clip((ct - _win_lo) / (_win_hi - _win_lo), 0.0, 1.0)
fig_qc, ax_qc = plt.subplots(figsize=(7, 7))
ax_qc.imshow(ctwin, cmap="gray", vmin=0, vmax=1)
ax_qc.contour(airway[k_mid], levels=[0.5], colors="red", linewidths=0.8)
ax_qc.set_title(f"QC {_letter} | axial mid slice {k_mid + 1}/{nz} (z={zpos[k_mid]:.1f}mm) | airway contour(red) vs CT\n"
                f"airway voxels this slice: {int(airway[k_mid].sum())}")
ax_qc.axis("off")
qc_path = os.path.join(OUT_DIR, "qc_fig", f"qc_{PREFIX}_mid.png")
fig_qc.savefig(qc_path, dpi=130, bbox_inches="tight")
plt.close(fig_qc)
print(f"    QC 图 -> {qc_path}")

np.savetxt(os.path.join(OUT_DIR, CSV_NAME),
           np.column_stack([np.arange(1, nz + 1), zpos, areas, l_areas, r_areas]),
           delimiter=",", header="slice,z_mm,total_mm2,left_mm2,right_mm2", comments="")

metrics = {
    "patient": ARGS.patient_label,
    "method": "per-slice 2D head fill (nostrils open to exterior) -> head-interior air -> largest 3D component",
    "airway_volume_cm3": round(total_cm3, 2),
    "n_components_merged": len(merged),
    "stl": STL_NAME, "stl_watertight": bool(wt),
    "min_axial_area_mm2": round(min_area, 1), "min_layer": min_idx + 1,
    "min_z_mm": round(float(zpos[min_idx]), 1),
    "left_min_mm2": round(float(l_areas[lm]), 1), "left_min_layer": lm + 1,
    "right_min_mm2": round(float(r_areas[rm]), 1), "right_min_layer": rm + 1,
    "left_right_asymmetry": round(float(abs(l_areas[lm]-r_areas[rm]) / max(l_areas[lm], r_areas[rm], 0.01)), 2),
    "midline_x": mid, "n_slices_with_air": int(valid.sum()),
    "caveat": "axial area is not perpendicular to centerline; true nasal-valve area needs centerline analysis (next stage)",
}
# T14/L1 诊断字段：仅当补桥发生（n_bridge>0）时写入——
# pA 三重 no-op（26-conn 识别 +0 体素 / 补桥 0 / 合并不变）
# 不写本字段 -> metrics 逐字节回归（回归铁闸）
if n_bridge > 0 or merge_stats_t14c is not None:
    metrics["t14_arch"] = {
        "conn_identification": "26-conn",
        "bridge_voxels": int(n_bridge),
        "n_components_6conn_after_bridge": int(n_comp6),
        "n_components_26conn": int(n),
        "closing": bool(ARGS.closing),
        "note": "T14/L1: 26-conn identification + canonical-order "
                "HU<-300 filtered bridging -> single 6-conn domain "
                "(patient-C pharynx 2.77cm3 anatomy inclusion; "
                "DeepSeek round2 sec2.1/2.2/t19)",
    }
    # T14c：并合模式扩展（仅 facegrow/base engaged 时写入——pA/pB
    #       咽部识别为空不触发，metrics 逐字节回归铁闸）
    if merge_stats_t14c is not None:
        metrics["t14_arch"]["merge_mode"] = ARGS.merge_mode
        metrics["t14_arch"]["L1c_merge_mode"] = merge_stats_t14c
with open(os.path.join(OUT_DIR, METRICS_NAME), "w", encoding="utf-8") as f:
    json.dump(metrics, f, ensure_ascii=False, indent=2)
print(f"[7/7] 全部输出 -> {OUT_DIR}")
print(json.dumps(metrics, ensure_ascii=False, indent=2))
