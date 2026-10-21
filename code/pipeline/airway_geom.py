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
#   2) 按 SeriesInstanceUID 分组，只保留层数最多的一组；缺 UID 的（老设备/自制）
#      归到同一组参与比较；被忽略的组各记一条警告（组号/层数/SeriesDescription）；
#   3) 同 z 去重（容差 Z_DEDUP_TOL_MM），保留先出现的那一层，去重数打印；
#   4) 有效层 < 2 → 打印"未找到有效 CT 轴位序列（找到 N 个 .dcm，其中有效 M 层）"
#      并 SystemExit(1)。
# 干净输入（单一序列、无杂质、无重复 z）走的是同一条主路径，过滤/分组/去重都是
# 恒等变换，体数据逐体素不变。
Z_DEDUP_TOL_MM = 1e-3          # 同 z 判定容差（mm）
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


def read_ct_series(files):
    """把一堆 *.dcm 读成**一套** CT 轴位序列（规则见本文件顶部注释）。

    files: 文件路径列表。调用方按文件名 sorted 传入，这里保持该次序——
          分组并列时先出现的组胜出、同 z 去重时先出现的层胜出，结果确定。

    返回 (slices, report)：
        slices —— 已选定单序列、已按 z 升序、已同 z 去重的 dataset 列表
        report —— {"n_files", "n_valid", "n_skipped", "skip_reasons",
                   "series_uid", "n_picked", "ignored", "dedup"}
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

    # ---- 2. 按序列分组，只留层数最多的一组 ----
    groups = {}
    for ds in slices:
        groups.setdefault(_series_key(ds), []).append(ds)
    picked, n_picked = None, -1
    for key, grp in groups.items():        # dict 保序：并列时先出现的组胜出
        if len(grp) > n_picked:
            picked, n_picked = key, len(grp)
    kept = groups.get(picked, [])
    kept.sort(key=lambda s: float(s.ImagePositionPatient[2]))

    # ---- 3. 同 z 去重（容差 Z_DEDUP_TOL_MM，保留先出现的层）----
    uniq, dedup, last_z = [], 0, None
    for ds in kept:
        z = float(ds.ImagePositionPatient[2])
        if last_z is not None and abs(z - last_z) < Z_DEDUP_TOL_MM:
            dedup += 1
            continue
        uniq.append(ds)
        last_z = z

    ignored = [{"series": k, "n": len(v), "desc": _series_label(v[0])}
               for k, v in groups.items() if k != picked]

    # ---- 摘要（两行）----
    reasons_txt = "、".join("%s %d" % (k, v) for k, v in skip_reasons.items()) or "无"
    print("[1/7] 读取 %d 层 DICOM ..."
          "（跳过 %d 个非图像/缺几何：%s；z 去重 %d 层）"
          % (len(uniq), n_skipped, reasons_txt, dedup))
    if not groups:
        print("序列选择：无可用的轴位序列")
    elif ignored:
        detail = "、".join("%s %d 层" % (g["desc"], g["n"]) for g in ignored)
        print("序列选择：保留 Series %s（%d 层），忽略 %d 组（%s）"
              % (picked, n_picked, len(ignored), detail))
    else:
        print("序列选择：保留 Series %s（%d 层），无其它序列"
              % (picked, n_picked))

    report = {
        "n_files": len(files),
        "n_valid": len(uniq),
        "n_skipped": n_skipped,
        "skip_reasons": dict(skip_reasons),
        "series_uid": None if picked == _NO_UID_LABEL else picked,
        "n_picked": n_picked,
        "ignored": ignored,
        "dedup": dedup,
    }

    # ---- 4. 有效层 < 2 -> 明确报错退出 ----
    if len(uniq) < 2:
        print("[错误] 未找到有效 CT 轴位序列（找到 %d 个 .dcm，其中有效 %d 层）"
              % (len(files), len(uniq)))
        raise SystemExit(1)
    return uniq, report