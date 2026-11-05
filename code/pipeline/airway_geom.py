# -*- coding: utf-8 -*-
"""气道几何小工具（step1 生产代码与回归测试共用）。

抽出来的目的：step1 是顶层脚本（模块级 argparse + 读 DICOM），测试无法 import，
所以把"x 向质心算左右分界"这段几何逻辑放到本模块，step1 与测试**调用同一份实现**
——测的就是生产代码，不会出现"测试复现一份假实现"。

体数据轴约定（step1 全链路一致，改动前先看这里）：
    airway.shape == (nz, ny, nx)
    axis 0 = z 层号，axis 1 = y 行号，axis 2 = x 列号
    "左右"沿 x 轴切：airway[:, :, :mid] = 左，airway[:, :, mid:] = 右
"""
import math

import numpy as np


def centroid_split_x(airway):
    """返回 (cx, mid)：x 向质心列号（float）与左右分界列号（int）。

    cx  = Σ(x_profile * x) / Σ(airway)，其中 x_profile = airway.sum(axis=(0, 1))，
          长度 = nx（**先沿 z、y 两轴求和**得到的 x 边缘分布）。
    mid = int(round(cx))，供 `airway[:, :, :mid]` / `airway[:, :, mid:]` 切左右。

    2026-10-21 修复（服务器实测崩溃，体数据 (230, 308, 360)）：
    旧实现 `airway.sum(axis=2).sum(axis=0)` 是**先沿 x 求和、再沿 z 求和**，
    得到的是长度 ny 的 **y 边缘分布**，再与长度 nx 的 xs 相乘：
      * 非方形视野（ny=308 != nx=360）→ ValueError: shapes (308,) (360,)；
      * 方形视野虽不报错，但拿 y 的分布去乘 x 的坐标，cx 语义错 → 左右分界错位。
    正确口径是沿 z 与 y 求和，见上文 x_profile。

    零气道（全 False）→ (0.0, 0)，不抛 ZeroDivisionError（与原 max(..., 1) 口径一致）。
    mid 的理论范围是 [0, nx]：取 0 或 nx 时一侧为空切片（下游面积全 0），
    与原实现的边界行为一致，本函数不做额外钳制。
    """
    arr = np.asarray(airway)
    if arr.ndim != 3:
        raise ValueError(
            "airway 必须是 3 维 (nz, ny, nx)，实际 shape=%r" % (arr.shape,))
    nx = int(arr.shape[2])
    x_profile = arr.sum(axis=(0, 1))          # 长度 nx：沿 z、y 求和
    total = float(arr.sum())
    xs = np.arange(nx, dtype=np.float64)
    cx = float((x_profile * xs).sum() / max(total, 1.0))
    mid = int(round(cx))
    return cx, mid

# ================================================================
# DICOM 读入：真实上传目录的"轴位序列匹配规则"（step1 与回归测试共用同一份实现）
# ================================================================
# 背景（真实用户上传目录实测）：目录里除了要用的 CT 轴位序列，还常混着——
#   ① 非图像 DICOM 对象：DICOMDIR、结构化报告（SR）、剂量单（RT Dose）、
#      Patient Protocol / Evidence Documents / Reading Protocol 之类的单层对象；
#   ② 另一套序列：定位像 scout（Topogram，2-3 层）+ 轴位（上百层），或同一次
#      扫描的多个重建（骨窗 / 软组织窗 / 3D_Sinus 各一套）。
# 旧读入段 `slices.sort(key=lambda s: float(s.ImagePositionPatient[2]))` 碰到 ①
# 立即 AttributeError（'FileDataset' object has no attribute
# 'ImagePositionPatient'）整条链停摆；碰到 ② 会把 scout 与轴位混成一套体数据
# （z 跨度覆盖整个躯干、层厚失真）——静默算错，比崩更难发现。
#
# 规则（顺序即优先级，实现在 read_ct_series）：
#   1) 逐文件过滤：读不开 / 无 PixelData（非图像对象）/ 缺 ImagePositionPatient
#      或 Rows,Columns → 跳过并计数，绝不中断；
#   2) 按 SeriesInstanceUID 分组；缺 UID 的（老设备/自制）归到同一组参与比较。
#      组内先同 z 去重（容差 Z_DEDUP_TOL_MM，保留先出现的那一层），
#      **组间层数比较一律用去重后层数**（#77：旧实现用去重前 len(grp)，重复层多的
#      序列会凭虚高文件数胜出）；
#   3) 重建适用性准入（A2-Q1，判定表见 ADMISSION_CHECKS）：Modality 必须为 CT；
#      ImageOrientationPatient 存在时必须是轴位（法向 z 分量 |n_z| >= AXIAL_NZ_MIN）；
#      IOP 存在但不可解析（含 NaN/±inf/非数值）按 fail-closed **拒绝**（轴向性未知）。
#      不准入的组进 report["rejected_series"] 并附 reason；IOP 缺失（老设备导出）
#      准予入围，在 report["admitted_series"] 条目里打 iop_missing 披露；
#      准入且去重后层数最多的组胜出，其余准入组进 report["ignored"]；
#   4) 有效层 < 2 → 打印"未找到有效 CT 轴位序列（找到 N 个 .dcm，其中有效 M 层）"
#      并 SystemExit(1)（有组被准入判定拒绝时补一行原因统计）。
# 干净输入（单一序列、无杂质、无重复 z）走的是同一条主路径，过滤/分组/去重都是
# 恒等变换，体数据逐体素不变。
Z_DEDUP_TOL_MM = 1e-3          # 同 z 判定容差（mm）
Z_GAP_REL_TOL = 0.01          # 逐层间隙相对容差；真数据 16 目录实测最大相对偏差 2.033e-04（§23-6）
Z_GAP_ABS_FLOOR_MM = 0.005    # 极薄层时的绝对下限 mm；真数据实测最大绝对偏差 1.2e-04（§23-6）
_NO_UID_LABEL = "(无 SeriesInstanceUID)"

# 非图像 DICOM 对象的常见 SOP Class -> 跳过原因（用于摘要里的分类计数）
_REASON_BY_SOP = {
    "1.2.840.10008.1.3.10": "DICOMDIR",               # Media Storage Directory
    "1.2.840.10008.5.1.4.1.1.481.2": "剂量单",         # RT Dose Storage
    "1.2.840.10008.5.1.4.1.1.88.11": "报告",           # Basic Text SR
    "1.2.840.10008.5.1.4.1.1.88.22": "报告",           # Enhanced SR
    "1.2.840.10008.5.1.4.1.1.88.33": "报告",           # Comprehensive SR
    "1.2.840.10008.5.1.4.1.1.88.34": "报告",           # Comprehensive SR Storage
    "1.2.840.10008.5.1.4.1.1.88.40": "报告",           # Procedure Log Storage
    "1.2.840.10008.5.1.4.1.1.88.67": "报告",           # X-Ray Radiation Dose SR
}
_REASON_BY_MODALITY = {"DICOMDIR": "DICOMDIR", "SR": "报告", "RTDOSE": "剂量单"}


def _non_image_reason(ds):
    """非图像对象的跳过原因（认不出就说"非图像"，不猜）。"""
    sop = str(getattr(ds, "SOPClassUID", "") or "")
    mod = str(getattr(ds, "Modality", "") or "").upper()
    return _REASON_BY_SOP.get(sop) or _REASON_BY_MODALITY.get(mod) or "非图像"


def _has_image_geometry(ds):
    """能不能当轴位切片用：要有像素 + 完整图像几何（IPP / Rows / Columns）。"""
    if not hasattr(ds, "PixelData"):
        return False
    for tag in ("ImagePositionPatient", "Rows", "Columns"):
        if not hasattr(ds, tag):
            return False
    ipp = ds.ImagePositionPatient
    return ipp is not None and len(ipp) >= 3


def _classify_unreadable(path):
    """读不开时用 force **只读头做判断**（只用来给原因分类，绝不当图像用）。

    取不到 SOP Class / Modality 就认 "读取失败"——force 会把任意字节读成空壳
    Dataset，空壳必须落回"读取失败"，不能算成"非图像"。
    """
    import pydicom
    try:
        ds = pydicom.dcmread(path, force=True, stop_before_pixels=True)
    except Exception:
        return "读取失败"
    sop = str(getattr(ds, "SOPClassUID", "") or "")
    mod = str(getattr(ds, "Modality", "") or "").upper()
    return _REASON_BY_SOP.get(sop) or _REASON_BY_MODALITY.get(mod) or "读取失败"


def _read_slice(path):
    """读一个候选文件 -> (dataset, None) 表示可用；(None, 跳过原因) 表示跳过。"""
    import pydicom
    try:
        ds = pydicom.dcmread(path)
    except Exception:
        return None, _classify_unreadable(path)
    if not hasattr(ds, "PixelData"):
        return None, _non_image_reason(ds)
    if not _has_image_geometry(ds):
        return None, "缺几何"
    return ds, None


def _series_key(ds):
    """分组键：SeriesInstanceUID；缺失的归到同一组（老设备/自制序列）。"""
    uid = getattr(ds, "SeriesInstanceUID", None)
    uid = str(uid).strip() if uid is not None else ""
    return uid or _NO_UID_LABEL


def _series_label(ds):
    """警告里怎么称呼一个序列：优先 SeriesDescription，退化到组号。"""
    desc = getattr(ds, "SeriesDescription", None)
    desc = str(desc).strip() if desc is not None else ""
    return desc or _series_key(ds)
def z_gap_report(zs):
    """升序 z 链（mm）的逐层间隙体检 → dict。"""
    if len(zs) < 2:
        raise ValueError("z_gap_report：不足两个 z，无法构成层间隙")
    zs_sorted = sorted(float(z) for z in zs)          # 内部自排序，不假设调用方已升序
    gaps = [zs_sorted[i + 1] - zs_sorted[i] for i in range(len(zs_sorted) - 1)]
    n_gaps = len(gaps)
    # 上中位 + 取绝对值：与 run_all.py survey_dicom 的 slice_gap_measured 逐字同式，
    # 预检与重建共用同一个数（层间距恒为正，T13 教训）
    gap_median = abs(sorted(gaps)[len(gaps) // 2])
    tol_mm = max(Z_GAP_REL_TOL * gap_median, Z_GAP_ABS_FLOOR_MM)
    bad_pairs = [i for i, g in enumerate(gaps) if abs(g - gap_median) > tol_mm]
    max_abs_dev_mm = max(abs(g - gap_median) for g in gaps)
    max_rel_dev = (max_abs_dev_mm / gap_median) if gap_median > 0 else float("inf")
    uniform = not bad_pairs
    gap_min = min(gaps)
    gap_max = max(gaps)
    return {
        "n_gaps": n_gaps,
        "gap_median": gap_median,
        "gap_min": gap_min,
        "gap_max": gap_max,
        "max_abs_dev_mm": max_abs_dev_mm,
        "max_rel_dev": max_rel_dev,
        "tol_mm": tol_mm,
        "bad_pairs": bad_pairs,
        "uniform": uniform,
    }


# ================================================================
# 重建适用性准入（A2-Q1）：被选中的序列必须"能用来重建"
# ================================================================
# 背景：旧实现只按"层数最多"选组。多帧动态序列 / 定位像 / 另一套层数更多的
# 非重建序列，只要文件数更多就会被选中，预检跟着 step1 一起选错而不报错。
# 判据收敛为数据驱动的**判定表**（ADMISSION_CHECKS）：将来新增同类约束只往表里
# 加一行 (类别标签, 判定函数)，read_ct_series 的流程一行不用改。
MODALITY_FOR_REBUILD = "CT"    # 只有 CT 能拿来重建气道几何
AXIAL_NZ_MIN = 0.9             # 轴位判定：IOP 法向 z 分量 |n_z| 下限（0=矢状/冠状，1=正轴位）


def _iop_values(ds):
    """ImageOrientationPatient 的 6 个分量 -> (状态, 值)。

    状态（判据见调用方，本函数只分类）：
      "missing"     —— 标签不存在，或分量不足 6 个（老设备导出确有此种）；
      "unparseable" —— 分量转不成 float，或含 NaN / ±inf。注意 `float('nan')`
                       **不会抛异常**，所以"非数值即异常"不成立，必须显式判有限性；
      "ok"          —— 6 个有限分量。
    损坏的 IOP 是"轴向性未知"，与"缺失"不同：缺失按披露放行，损坏按 fail-closed 拒绝
    （放进选优竞争正是本任务要消灭的静默错选）。
    """
    iop = getattr(ds, "ImageOrientationPatient", None)
    if iop is None or len(iop) < 6:
        return "missing", None
    try:
        vals = [float(x) for x in iop[:6]]
    except (TypeError, ValueError):
        return "unparseable", None
    if not all(math.isfinite(v) for v in vals):
        return "unparseable", None
    return "ok", vals


def _admit_modality(ds):
    """准入①：Modality 必须是 CT（缺 Modality 也算不准入）。"""
    mod = str(getattr(ds, "Modality", "") or "").strip().upper()
    if mod != MODALITY_FOR_REBUILD:
        return "非CT模态（Modality=%s）" % (mod or "缺失")
    return None


def _admit_iop_parseable(ds):
    """准入②：IOP 若有，必须可解析（6 个有限分量）——损坏即不准入（fail-closed）。"""
    state, _vals = _iop_values(ds)
    if state == "unparseable":
        return "IOP 不可解析（分量非有限或非数值）——轴向性未知，不准入"
    return None


def _admit_axial(ds):
    """准入③：轴位。IOP = [row_x,row_y,row_z, col_x,col_y,col_z]，
    n = row × col，n_z = iop[0]*iop[4] - iop[1]*iop[3]。
    IOP 缺失（老设备导出确有此种）准予入围 —— 缺失即拒绝会误杀真实病例，
    由调用方用 iop_missing 披露；损坏的 IOP 已由准入② 拦下，走不到这里。"""
    state, vals = _iop_values(ds)
    if state != "ok":
        return None
    n_z = vals[0] * vals[4] - vals[1] * vals[3]
    if abs(n_z) < AXIAL_NZ_MIN:
        return "非轴位（IOP 法向 z 分量 |n_z|=%.3f < %.2f）" % (abs(n_z), AXIAL_NZ_MIN)
    return None


# 判定表：(类别标签, 判定函数)。任一判定返回非空原因 -> 该组不准入。
ADMISSION_CHECKS = (
    ("非CT模态", _admit_modality),
    ("IOP不可解析", _admit_iop_parseable),
    ("非轴位", _admit_axial),
)


def admission_rejection(ds):
    """准入判定：返回 (拒绝原因 or None, 类别标签 or None)；None = 准入。"""
    for label, check in ADMISSION_CHECKS:
        why = check(ds)
        if why:
            return why, label
    return None, None


def _dedup_by_z(layers):
    """组内同 z 去重 -> (uniq_layers, 去重掉的层数)。

    先按 IPP z **稳定**升序排序，再在 Z_DEDUP_TOL_MM 容差内只留先出现的一层
    —— 稳定排序保证同 z 并列时先读入的那层留下（与旧实现逐层同口径）。
    """
    ordered = sorted(layers, key=lambda s: float(s.ImagePositionPatient[2]))
    uniq, n_dup, last_z = [], 0, None
    for ds in ordered:
        z = float(ds.ImagePositionPatient[2])
        if last_z is not None and abs(z - last_z) < Z_DEDUP_TOL_MM:
            n_dup += 1
            continue
        uniq.append(ds)
        last_z = z
    return uniq, n_dup


def read_ct_series(files):
    """把一堆 *.dcm 读成**一套** CT 轴位序列（规则见本文件顶部注释）。

    files: 文件路径列表。调用方按文件名 sorted 传入，这里保持该次序——
          分组并列时先出现的组胜出、同 z 去重时先出现的层胜出，结果确定。

    返回 (slices, report)：
        slices —— 已选定单序列、已按 z 升序、已同 z 去重的 dataset 列表
        report —— {"n_files", "n_valid", "n_skipped", "skip_reasons",
                   "series_uid", "n_picked", "ignored", "dedup",
                   "rejected_series", "admitted_series"}
            ignored        [{"series","n","desc"}]            —— 准入但未胜出的组
            rejected_series[{"series","n","desc","reason"}]   —— 准入判定拒绝的组
            admitted_series[{"series","n","desc","iop_missing"}] —— 全部准入组（含胜出组）
            **n 的口径（T2 变更）**：三处 `n` 一律是**组内同 z 去重后**的层数
            （旧口径 = 去重前 len(grp)，重复层多的组会凭虚高文件数胜出）；
            `n_picked` / `n_valid` 同口径。`dedup` 只计**被选中组**去重掉的层数。
            `iop_missing`（T2 新增键）：该组 IOP 缺失（老设备导出）——已准予入围
            并在 stdout 披露；IOP 损坏（NaN/inf/非数值）走拒绝，不进本列表。
    打两行摘要（[1/7] 读入 + 序列选择）；有效层 < 2 打印原因后 SystemExit(1)。
    """
    slices, skip_reasons = [], {}
    for f in files:
        ds, why = _read_slice(f)
        if ds is None:
            skip_reasons[why] = skip_reasons.get(why, 0) + 1
        else:
            slices.append(ds)
    n_skipped = sum(skip_reasons.values())

    # ---- 2. 按序列分组 ----
    groups = {}
    for ds in slices:
        groups.setdefault(_series_key(ds), []).append(ds)

    # ---- 3. 组内同 z 去重 + 重建适用性准入（准入判在选优之前）----
    admitted, rejected, reject_counts = [], [], {}
    for key, grp in groups.items():
        uniq_g, n_dup = _dedup_by_z(grp)
        desc = _series_label(grp[0])
        # 判定取样点 = 组内**按文件名序第一层**（grp[0]，不是去重/排序后的首层）：
        # 同一 SeriesInstanceUID 内混模态/朝向属 DICOM 非法形态，坏转换器确会产出
        # ——那种情况由既有的层间距一致性门（z_gap_report）与 S2 后面的朝向几何
        # 断言（A1-A6）兜底，这里不为此再造一套逐层判定。
        why, kind = admission_rejection(grp[0])
        if why:
            rejected.append({"series": key, "n": len(uniq_g),
                             "desc": desc, "reason": why})
            reject_counts[kind] = reject_counts.get(kind, 0) + 1
            continue
        admitted.append({"series": key, "n": len(uniq_g), "desc": desc,
                         "layers": uniq_g, "n_dedup": n_dup,
                         "iop_missing": _iop_values(grp[0])[0] == "missing"})

    # 只在**准入**组里选层数最多的（组间比较用去重后层数；dict 保序：并列时先出现的组胜出）
    picked_rec, n_picked = None, -1
    for rec_g in admitted:
        if rec_g["n"] > n_picked:
            picked_rec, n_picked = rec_g, rec_g["n"]
    if picked_rec is None:
        picked, uniq, dedup, n_picked = None, [], 0, 0
    else:
        picked, uniq = picked_rec["series"], picked_rec["layers"]
        dedup, n_picked = picked_rec["n_dedup"], picked_rec["n"]

    ignored = [{"series": r["series"], "n": r["n"], "desc": r["desc"]}
               for r in admitted if r is not picked_rec]

    # ---- 摘要（两行）----
    reasons_txt = "、".join("%s %d" % (k, v) for k, v in skip_reasons.items()) or "无"
    print("[1/7] 读取 %d 层 DICOM ..."
          "（跳过 %d 个非图像/缺几何：%s；z 去重 %d 层）"
          % (len(uniq), n_skipped, reasons_txt, dedup))
    rej_txt = ""
    if rejected:
        rej_txt = "；准入拒绝 %d 组（%s）" % (
            len(rejected),
            "、".join("%s %d 组" % (k, v) for k, v in reject_counts.items()))
    if picked_rec is None:
        print("序列选择：无可用的轴位序列" + rej_txt)
    elif ignored:
        detail = "、".join("%s %d 层" % (g["desc"], g["n"]) for g in ignored)
        print("序列选择：保留 Series %s（%d 层），忽略 %d 组（%s）%s"
              % (picked, n_picked, len(ignored), detail, rej_txt))
    else:
        print("序列选择：保留 Series %s（%d 层），无其它序列%s"
              % (picked, n_picked, rej_txt))
    if picked_rec is not None and picked_rec["iop_missing"]:
        print("序列选择：被选中序列缺 ImageOrientationPatient（老设备导出形态）"
              "——按轴位准予入围，已按 iop_missing 披露")

    report = {
        "n_files": len(files),
        "n_valid": len(uniq),
        "n_skipped": n_skipped,
        "skip_reasons": dict(skip_reasons),
        "series_uid": None if picked == _NO_UID_LABEL else picked,
        "n_picked": n_picked,
        "ignored": ignored,
        "dedup": dedup,
        "rejected_series": rejected,
        "admitted_series": [{"series": r["series"], "n": r["n"], "desc": r["desc"],
                             "iop_missing": r["iop_missing"]} for r in admitted],
    }

    # ---- 4. 有效层 < 2 -> 明确报错退出 ----
    if len(uniq) < 2:
        print("[错误] 未找到有效 CT 轴位序列（找到 %d 个 .dcm，其中有效 %d 层）"
              % (len(files), len(uniq)))
        if rejected:
            print("（其中 %d 组因%s被拒：%s）"
                  % (len(rejected), "/".join(reject_counts),
                     "、".join("%s %d 组" % (k, v) for k, v in reject_counts.items())))
        raise SystemExit(1)
    return uniq, report