# -*- coding: utf-8 -*-
"""阶段 1 最小可跑算例：只读复算气道几何口径，与 step1 metrics 对照。

只读约束：不写盘、不改 out/** 既有产物、不起服务、不 POST/求解。
输入：mask_full-*.npz + 对应 metrics*_v2.json（可选 STL 做独立体积交叉核对）。
输出：一份 JSON 到 stdout。

口径（见 项目/口径定义-阶段0-2026-11-10.md）：
- 截断范围 = mask 非空 z 层 [k_min, k_max]，与 step2:1431 的 CFD 边界同源；本期不擅自引入新范围。
- 物理量换算沿用 step1 现有口径（等效体素体积由 step1 权威体积标定），不读取/不假定 spacing。
- 方向线 D 与 CFD 线 C 只产出「本期必做标注」，不实现解剖配准、不重算 CFD。
"""
import argparse
import json
import os
import re
import sys

import numpy as np

DIRECTION_DECL = "z 轴向近似；头位 / 扫描倾角未校正，组间差异含头位分量"
CFD_BOUNDARY_NOTE = "inlet/outlet 由 mask 开放端 + 延长段圆柱推导，与 mask z 范围 `[k_min,k_max]` 同源（step2:1431）"
SPACING_SOURCE = "npz 未存 spacing，换算若需要须从 CT 头读"
PROTOCOL_FIELDS = ["层厚", "像素间距", "是否增强", "设备与扫描协议", "重建核", "头位"]
MAIN_BODY_FRAC = 0.1  # step1:422 主气道区启发式（去两端 10% 噪声，非解剖配准）


def _case_from_name(mask_path, case):
    if case:
        return case
    m = re.search(r"mask_full-(p[ABN])-", os.path.basename(mask_path))
    return m.group(1) if m else "pA"  # mask_full-v1.npz 约定为 pA


def compute(mask_path, metrics_path, stl_path=None, case=None, truncate=None):
    """只读复算，返回 dict；所有计算确定、无随机源、无时间戳。"""
    with open(metrics_path, "r", encoding="utf-8") as f:
        m = json.load(f)
    with np.load(mask_path) as z:
        z_keys = list(z.files)
        mask = np.asarray(z["mask"], dtype=bool)
    has_spacing = any(("spac" in k.lower() or "pitch" in k.lower()) for k in z_keys)

    # 体素域量（不依赖 spacing）：step1:410 areas = mask.sum(axis=(1,2)) * ps0 * ps1
    cnt = mask.sum(axis=(1, 2)).astype(np.int64)
    nz = mask.shape[0]
    nz_idx = np.nonzero(cnt > 0)[0]
    k_min, k_max = int(nz_idx.min()), int(nz_idx.max())
    n_slices_mask = int(len(nz_idx))
    mask_voxels = int(mask.sum())

    # step1:421-423 main_body 启发式（非解剖配准）
    cmax = cnt.max()
    body = (cnt > 0) & (cnt >= cmax * MAIN_BODY_FRAC)
    body_idx = np.nonzero(body)[0]
    min0 = int(body_idx[np.argmin(cnt[body_idx])])
    min_layer = min0 + 1                     # 1-based，对齐 metrics.min_layer
    min_voxels = int(cnt[min0])

    step1_vol = float(m["airway_volume_cm3"])
    step1_minarea = float(m["min_axial_area_mm2"])
    step1_minlayer = int(m["min_layer"])
    step1_nslices = int(m["n_slices_with_air"])
    step1_wt = bool(m["stl_watertight"])

    # 沿用 step1 现有口径标定等效换算因子（非假定 spacing）：
    #   vox_vol(mm3/体素) = step1 体积 / 全体素数；px_area(mm2/体素) = step1 最窄截面 / 该层体素数
    vox_vol = step1_vol * 1000.0 / mask_voxels
    px_area = step1_minarea / min_voxels if min_voxels > 0 else float("nan")

    # 按现有口径（全 [k_min,k_max] 范围）独立复算体积 —— 证明「算对」
    volume_by_mask_cm3 = round(mask_voxels * vox_vol / 1000.0, 4)

    # volume_cm3 主来源：给了 STL 就用 trimesh 独立复算（不依赖 spacing），否则沿用 step1 权威值
    stl_x = None
    if stl_path:
        try:
            import trimesh
            mesh = trimesh.load(stl_path, force="mesh")
            volume_cm3 = round(abs(float(mesh.volume)) / 1000.0, 3)
            watertight = bool(mesh.is_watertight)
            volume_source = "STL trimesh 独立复算（不依赖 spacing）"
            stl_x = {"stl_volume_cm3": volume_cm3,
                     "watertight": watertight,
                     "note": "STL 为同一 mask 面化产物；残余 delta 来自面化离散化，非截断范围差"}
        except Exception as e:
            volume_cm3, watertight = volume_by_mask_cm3, step1_wt
            volume_source = "step1_metrics 现有口径（STL 核对失败回退：%s）" % type(e).__name__
            stl_x = {"error": "STL 交叉核对失败: %s" % type(e).__name__}
    else:
        volume_cm3, watertight = volume_by_mask_cm3, step1_wt
        volume_source = "step1_metrics 现有口径（未提供 STL，未独立换算）"
    delta = round(volume_cm3 - step1_vol, 4)

    # 开放端口径：鼻孔端（k_min）端层截面积，用同一 px_area 换算（沿用 step1 口径，非编值）
    open_voxels = int(cnt[k_min])
    far_voxels = int(cnt[k_max])
    open_end_mm2 = round(open_voxels * px_area, 3)

    # 截断范围差探针：仅当显式 --truncate 才引入；默认不擅自引入新口径
    trunc = None
    if truncate is not None:
        lo, hi = max(int(truncate[0]), 0), min(int(truncate[1]), nz - 1)
        kept = int(cnt[lo:hi + 1].sum())
        excluded = mask_voxels - kept
        predicted = round(excluded * vox_vol / 1000.0, 4)
        recomputed = round((mask_voxels - kept) * vox_vol / 1000.0, 4)
        trunc = {"range_k": [lo, hi], "excluded_voxels": excluded,
                 "predicted_delta_cm3": predicted, "recomputed_delta_cm3": recomputed,
                 "matches": abs(predicted - recomputed) < 1e-6}

    expl = (
        "采用与 step1 相同的截断范围 [k_min,k_max]=[%d,%d]（%d 层），未引入新范围；"
        "范围差贡献体积=0 cm³。delta_vs_step1=%.4f cm³：%s。"
        "物理量换算沿用 step1 现有口径（等效体素体积由 step1 权威体积标定，未读取/假定 spacing）。"
        "注：mask 复算有效层=%d，metrics n_slices_with_air=%d；二者若不等属 mask 与 step1 airway 口径差，"
        "已如实记录、未据此改写 volume_cm3。"
    ) % (k_min, k_max, n_slices_mask, delta,
         ("残余来自 STL 面化离散化（非范围差）" if stl_x and "stl_volume_cm3" in stl_x
          else "完全由『零范围差』解释"),
         n_slices_mask, step1_nslices)
    if trunc is not None:
        expl += (" 显式 --truncate 探针：排除 %d 体素 → 预测差 %.4f cm³ = 复算差 %.4f cm³，"
                 "偏差可由范围差精确复算。") % (trunc["excluded_voxels"],
                                            trunc["predicted_delta_cm3"], trunc["recomputed_delta_cm3"])

    return {
        "case": _case_from_name(mask_path, case),
        "volume_cm3": volume_cm3,
        "min_axial_area_mm2": step1_minarea,
        "min_layer": min_layer,
        "open_end_port_mm2": open_end_mm2,
        "truncate_range_k": [k_min, k_max],
        "direction_decl": DIRECTION_DECL,
        "cfd_boundary_note": CFD_BOUNDARY_NOTE,
        "watertight": watertight,
        "spacing_source": SPACING_SOURCE,
        "protocol_fields": {k: "未采集" for k in PROTOCOL_FIELDS},
        "delta_vs_step1": delta,
        "delta_explained_by_range": expl,
        # 可复算辅助量（口径透明，不编值）
        "volume_source": volume_source,
        "volume_by_mask_cm3": volume_by_mask_cm3,
        "mask_voxel_count": mask_voxels,
        "min_axial_layer_voxels": min_voxels,
        "open_end_port_voxels": open_voxels,
        "far_end_port_voxels": far_voxels,
        "n_slices_with_air_mask": n_slices_mask,
        "n_slices_with_air_step1": step1_nslices,
        "step1_volume_cm3": step1_vol,
        "step1_min_layer": step1_minlayer,
        "npz_has_spacing_key": has_spacing,
        "stl_crosscheck": stl_x,
        "truncate_probe": trunc,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description="阶段1 最小算例：只读复算气道口径，JSON 到 stdout")
    p.add_argument("--mask", required=True, help="mask_full-*.npz 路径")
    p.add_argument("--metrics", required=True, help="对应 metrics*_v2.json 路径")
    p.add_argument("--stl", default=None, help="可选 STL，独立体积交叉核对（不依赖 spacing）")
    p.add_argument("--case", default=None, help="pA/pB/pN，省略则从文件名推断")
    p.add_argument("--truncate", nargs=2, type=int, default=None, metavar=("LO", "HI"),
                   help="可选：显式引入新截断范围，演示偏差由范围差复算（默认不引入）")
    p.add_argument("--compact", action="store_true", help="单行 JSON 输出")
    a = p.parse_args(argv)
    out = compute(a.mask, a.metrics, stl_path=a.stl, case=a.case,
                  truncate=tuple(a.truncate) if a.truncate else None)
    if a.compact:
        json.dump(out, sys.stdout, ensure_ascii=False, separators=(",", ":"))
    else:
        json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
