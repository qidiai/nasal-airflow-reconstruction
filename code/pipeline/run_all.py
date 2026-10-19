#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""run_all.py — P0 多患者通用化一键管线（T12 批，审计 #29/#30 闭环）

串联：PII 头扫描 → DICOM 头普查 → step1 气道分割 → step2 算例生成
     → 朝向几何断言（6 项）→ 求解（local / laptop / skip）
     → 后处理（metrics 契约汇编 + 字段完备性）→ step5 查看器数据导出

用法：
  python run_all.py --dicom-dir <CT 目录> --case-prefix pB [--case v1] [--solve local|laptop|skip]
  python run_all.py ... [--publish <共享目录>]        # T15A：所有步骤完成后自动回传交付物
                                                  # （逐件 Test-Path + md5；未指定则不回传）

求解模式：
  local   走求解后端抽象（--backend auto|custom|openfoam，默认 auto）：
          custom=自研 FlowScope（Run-A；无需 WSL/OpenFOAM）；
          openfoam=保留的对拍基准（WSL Allrun/simpleFoam）。
          已给出 --result-dir（含 后处理/metrics.json）则直接进入后处理+step5
  laptop  生成交接文档-笔记本执行-<prefix>-<case>.md + 算例包 zip（沿用 v5E-ext
          交接模式）；后处理/step5 标记"待解算后补导出"
  skip    只到算例+断言（自测/隔离比对用）

关键参数：
  --out-root <目录>        输出根目录（默认 pipeline/out；自测隔离用）
  --patient-label <str>    metrics patient 字段（默认按 前缀+面内间距 自动生成，
                           pA 默认值与原版逐字节兼容）
  --result-dir <目录>      已回传的 CFD 结果目录（P0-result-<prefix>-<case>，
                          含 VTK/ 与 后处理/metrics.json；local/laptop 回传后用）
  --ext / --iso / --ext-l-mm / --ext-r-factor   透传 step2
  --hu-air / --hu-head                          透传 step1（默认 -400 / -300，§5.3）
  --ph-dir / --skin-data-js                     透传 step5（占位体/皮肤层；新病例
                          无占位体时不传——step5 依契约完备性自动延期）

内置断言（不过即停工上报，exit 2）：
  PII 头扫描（逐头 10 字段白名单 + 核心 PII 任一非空即 FAIL）
  维度动态（mask 形状 == DICOM 层数×行×列）
  朝向几何（A1 左右分居 / A2 入口鼻端半区 / A3 出口咽端半区 /
            A4 前后分离度 / A5 入口面积比 / A6 入口高于出口）
  metrics 字段完备性（缺失字段即不导出 step5——严禁套用其他患者数字）

红线：
  患者A 冻结资产（viewer_data.js / v5 系算例 / 提交包）零接触；
  输出全部落在 --out-root 树下；非 pA 前缀文件名带前缀隔离。
"""
import argparse
import glob
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile

import numpy as np
import pydicom

import solver_backend as SB  # M3：求解后端抽象（custom / openfoam / auto）

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
STEP1 = os.path.join(HERE, "step1_airway_segment.py")
STEP2 = os.path.join(HERE, "step2_make_ofcase.py")
STEP5 = os.path.join(HERE, "step5_export_viewer_data.py")

# ---------------------------------------------------------------- PII 断言口径
# 沿用《匿名化核验记录-20261002》（患者A）与 anon_verify_T12.py（赛方CT）口径
PII_FIELDS = [
    "PatientName", "PatientID", "PatientBirthDate", "PatientSex",
    "InstitutionName", "InstitutionAddress", "ReferringPhysicianName",
    "AccessionNumber", "StudyID", "OtherPatientIDs",
]
CORE_PII = [
    "PatientBirthDate", "InstitutionName", "InstitutionAddress",
    "ReferringPhysicianName", "AccessionNumber", "OtherPatientIDs",
]
PID_ANON = re.compile(r"^\d{8}-\d{6}$")

T12_VERSION = "run_all.py T12 (2026-10-02)"


_PROGRESS_PATH = None  # T15 修订5：进度追加写目标（manifest-progress.json；None=不写）


def log(msg):
    print(f"[run_all] {msg}", flush=True)
    # T15 修订5：每步开始/结束向 manifest-progress.json 追加一行 JSONL
    # （Web 工作台轮询源；server.py GET /api/progress/<id> 读本文件）
    if _PROGRESS_PATH:
        try:
            with open(_PROGRESS_PATH, "a", encoding="utf-8") as _pf:
                _pf.write(json.dumps(
                    {"ts": round(time.time(), 3), "msg": msg},
                    ensure_ascii=False) + "\n")
        except OSError:
            pass  # 进度写失败不中断管线（尽力而为）


def md5_of(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def die(code, msg):
    log(f"!!! FATAL (exit {code}): {msg}")
    sys.exit(code)


# ---------------------------------------------------------------- S0 PII 头扫描
def scan_pii(dicom_dir):
    """逐头 PII 断言。任何核心 PII 非空即 FAIL（停工）。"""
    files = sorted(f for f in os.listdir(dicom_dir) if f.lower().endswith(".dcm"))
    if not files:
        die(2, f"PII 扫描：{dicom_dir} 无 .dcm 文件")
    fails = []
    pii_nonempty = {}
    pid_values, sex_values, studyid_values = set(), set(), set()
    for fn in files:
        ds = pydicom.dcmread(os.path.join(dicom_dir, fn), stop_before_pixels=True)
        for fld in PII_FIELDS:
            v = getattr(ds, fld, None)
            s = "" if v is None else str(v).strip()
            if s and s.upper() != "UNKNOWN":
                pii_nonempty.setdefault(fld, []).append((fn, s))
        pn = "" if getattr(ds, "PatientName", None) is None else str(ds.PatientName).strip()
        if pn and pn != "Anonymous":
            fails.append((fn, "PatientName", pn, "非空且非匿名占位值 'Anonymous'"))
        pid = "" if getattr(ds, "PatientID", None) is None else str(ds.PatientID).strip()
        if pid and not PID_ANON.match(pid):
            fails.append((fn, "PatientID", pid, "非空且不匹配合规匿名编号格式 ^\\d{8}-\\d{6}$"))
        for fld in CORE_PII:
            v = getattr(ds, fld, None)
            s = "" if v is None else str(v).strip()
            if s and s.upper() != "UNKNOWN":
                fails.append((fn, fld, s, "核心 PII 非空"))
        pid_values.add(pid)
        sex_values.add(str(getattr(ds, "PatientSex", "") or "").strip())
        studyid_values.add(str(getattr(ds, "StudyID", "") or "").strip())
    rec = {
        "files": len(files),
        "fail_count": len(fails),
        "fails": fails[:20],
        "pid_values": sorted(pid_values),
        "sex_values": sorted(sex_values),
        "studyid_values": sorted(studyid_values),
        "pii_nonempty_summary": {k: len(v) for k, v in pii_nonempty.items()},
    }
    rec["pass"] = len(fails) == 0
    return rec


# ---------------------------------------------------------------- S1 DICOM 头普查
def survey_dicom(dicom_dir):
    """层数/维度/间距/层序方向实测（不臆断层序）。"""
    files = sorted(f for f in os.listdir(dicom_dir) if f.lower().endswith(".dcm"))
    ds0 = pydicom.dcmread(os.path.join(dicom_dir, files[0]), stop_before_pixels=True)
    zs = []
    for fn in files:
        ds = pydicom.dcmread(os.path.join(dicom_dir, fn), stop_before_pixels=True)
        ipp = getattr(ds, "ImagePositionPatient", None)
        zs.append(float(ipp[2]) if ipp is not None else float("nan"))
    ps = [round(float(x), 6) for x in ds0.PixelSpacing]
    st = float(ds0.SliceThickness)
    gaps = [zs[i + 1] - zs[i] for i in range(len(zs) - 1)]
    gaps_sorted = sorted(gaps)
    # 中位数取绝对值：文件名序可与物理序相反（如 1mm 序列 z 单调降），
    # 层间距恒为正（T13 修复：此前负值使朝向断言 A6 的 z 物理坐标翻转、
    # 数值失真——患者C 实测 A6 out_z 报 -24.33，正确值 +24.33，
    # 结论虽碰巧一致但判别力被削弱，修复后重跑验证）
    sz_measured = abs(gaps_sorted[len(gaps_sorted) // 2])  # 中位数（重叠重建时≠SliceThickness）
    rec = {
        "file_count": len(files),
        "rows": int(ds0.Rows), "columns": int(ds0.Columns),
        "pixel_spacing": ps, "slice_thickness_header": st,
        "slice_gap_measured": round(sz_measured, 6),
        "z_first": zs[0], "z_last": zs[-1],
        "z_monotonic_increasing": all(zs[i] < zs[i + 1] for i in range(len(zs) - 1)),
        "z_monotonic_decreasing": all(zs[i] > zs[i + 1] for i in range(len(zs) - 1)),
        "modality": str(getattr(ds0, "Modality", "")),
        "convolution_kernel": str(getattr(ds0, "ConvolutionKernel", "")),
        "patient_position": str(getattr(ds0, "PatientPosition", "")),
        "iop": [str(x) for x in getattr(ds0, "ImageOrientationPatient", [])],
        "rescale_slope": str(getattr(ds0, "RescaleSlope", "")),
        "rescale_intercept": str(getattr(ds0, "RescaleIntercept", "")),
        "first_file": files[0],
    }
    # 文件名序与物理序关系（如实记录，断言不预设）
    rec["filename_order_matches_physical"] = (
        rec["z_monotonic_increasing"] or rec["z_monotonic_decreasing"]
    )
    return rec


# ---------------------------------------------------------------- S4 朝向几何断言
def orientation_assertions(case_stats, mask, sx, sy, sz,
                           merge_mode="largest"):
    """6 项几何断言（物理坐标 = 全分辨率索引 × 原始间距）。
    解剖先验：鼻腔长轴沿 y（前后轴），入口（鼻孔）在鼻端半区、
    出口（鼻咽截断）在咽端半区；左右分居中线两侧。
    T13b 朝向感知：鼻孔端在 z 小端（pC，case_stats
    nostril_at_low=True）时出口=掩码最高层平面、A6 判别
    方向反转（入口 z < 出口 z）；pA 系（鼻孔端在 z 大端）
    出口=最下层平面、入口 z > 出口 z（原口径不变）。
    T14c merge_mode 感知：base 模式（对照变体 X1）按实验设计
    咽部不并入——A3/A4 的"出口=咽部后置"前提被合法置空
    （出口=鼻腔顶端截面），标记 N/A+披露（变异几何性质，
    非层序异常），pass=True 不计入 orient_fail；层序方向核验
    由 A6 z 向分离覆盖。largest/facegrow 行为不变。
    任何一项不过即停工上报（不许默认层序正确）。
    """
    zs, ys, xs = np.where(mask)
    x_phys, y_phys, z_phys = xs * sx, ys * sy, zs * sz
    x_mid = (x_phys.min() + x_phys.max()) / 2.0
    y_mid = (y_phys.min() + y_phys.max()) / 2.0
    y_range = y_phys.max() - y_phys.min()
    k_min = int(zs.min())
    k_max = int(zs.max())
    # T13b：出口=鼻咽截断端平面，朝向感知选取
    #（pC 鼻咽端在 z 大端→最高层；pA 系在 z 小端→最下层）
    nostril_low = bool(case_stats.get("nostril_at_low", False))
    om = (zs >= k_max - 2) if nostril_low \
        else (zs <= k_min + 2)
    out_y = float(y_phys[om].mean())
    out_z = float(z_phys[om].mean())
    il = case_stats["inletL"]["centroid_mm"]
    ir = case_stats["inletR"]["centroid_mm"]
    al = float(case_stats["inletL"]["area_mm2"])
    ar = float(case_stats["inletR"]["area_mm2"])
    in_y_mean = (il[1] + ir[1]) / 2.0
    in_z_mean = (il[2] + ir[2]) / 2.0
    checks = [
        ("A1 左右分居（inletL.x < 中线 < inletR.x）",
         il[0] < x_mid < ir[0],
         f"inletL.x={il[0]:.2f} < x_mid={x_mid:.2f} < inletR.x={ir[0]:.2f}"),
        ("A2 入口鼻端半区（双侧入口 y < y_mid）",
         il[1] < y_mid and ir[1] < y_mid,
         f"inletL.y={il[1]:.2f}, inletR.y={ir[1]:.2f} < y_mid={y_mid:.2f}"),
        (f"A3 出口咽端半区（出口端层质心 y > y_mid）"
         + ("【N/A·base】" if merge_mode == "base" else ""),
         (True if merge_mode == "base" else out_y > y_mid),
         (f"N/A（base 模式：咽部按设计未并入，出口=鼻腔顶端截面，"
          f"'出口=咽部后置'预期前提置空——对照变体 X1 几何性质，"
          f"非层序异常；实测 outlet_y={out_y:.2f} vs "
          f"y_mid={y_mid:.2f}；层序方向由 A6 z 向分离覆盖核验）"
          if merge_mode == "base" else
          f"outlet_y={out_y:.2f} > y_mid={y_mid:.2f}")),
        (f"A4 前后分离度（out_y − in_y_mean > 0.3×y_range）"
         + ("【N/A·base】" if merge_mode == "base" else ""),
         (True if merge_mode == "base"
          else (out_y - in_y_mean) > 0.3 * y_range),
         (f"N/A（base 模式：同上，前后端解剖跨度预期前提置空——"
          f"对照变体 X1 几何性质，非层序异常；实测 "
          f"{out_y - in_y_mean:.2f} vs {0.3 * y_range:.2f} "
          f"(y_range={y_range:.2f})）"
          if merge_mode == "base" else
          f"{out_y - in_y_mean:.2f} > {0.3 * y_range:.2f} "
          f"(y_range={y_range:.2f})")),
        ("A5 入口面积比（0.3 < A_L/A_R < 3.3）",
         0.3 < al / ar < 3.3, f"A_L/A_R={al / ar:.3f} ({al:.1f}/{ar:.1f} mm2)"),
        ("A6 入口出口 z 向分离（pA 系 in>out / pC 朝向 in<out）",
         (in_z_mean < out_z) if nostril_low
         else (in_z_mean > out_z),
         (f"in_z_mean={in_z_mean:.2f} < out_z={out_z:.2f}"
          if nostril_low else
          f"in_z_mean={in_z_mean:.2f} > out_z={out_z:.2f}")),
    ]
    _om = {
        "x_mid": round(x_mid, 2), "y_mid": round(y_mid, 2),
        "y_range": round(y_range, 2), "outlet_y": round(out_y, 2),
        "outlet_z": round(out_z, 2), "k_min": k_min,
        "spacing_used": [sx, sy, sz],
        "merge_mode": merge_mode,
    }
    if merge_mode == "base":
        _om["na_disclosure"] = (
            "A3/A4 N/A：base 模式咽部按设计未并入（对照变体 X1），"
            "'出口=咽部后置'前提置空——对照实验几何性质，非层序异常；"
            "层序方向由 A6 z 向分离覆盖核验")
    return checks, _om


# ---------------------------------------------------------------- S6 后处理契约汇编
def assemble_contract(result_metrics, letter, case):
    """从本例后处理 metrics.json 汇编 step5 meta 契约。
    占位档字段（dP_1/2/3mm、curve）需占位算例——单算例缺失即标记，
    由完备性检查决定 step5 是否导出（绝不套用其他患者数字）。
    """
    totals = result_metrics["totals"]
    wss = result_metrics.get("wss", {})
    dP = float(totals["dP_Pa"])
    Q = float(totals["Q_inlet_total_L_min"])
    resistance = dP / (Q / 60.0)  # Pa/(L/s)，定流量口径
    contract = {
        "title": f"患者{letter} 鼻腔气流仿真查看器（黑客松概念验证）",
        "caseBaseline": f"{case} @15 L/min 层流",
        "units": "mm, m/s, Pa",
        "metrics": {
            "dP_baseline_Pa": round(dP, 2),
            "dP_note": "层流下界估计，不确定度±20-50%（占位档为仿真工况，非推荐）",
            "split_L_pct": round(float(totals["flow_share_L_pct"]), 1),
            "split_R_pct": round(float(totals["flow_share_R_pct"]), 1),
            "wss_mean_Pa": round(float(wss.get("mean_Pa", float("nan"))), 3),
            "wss_p95_Pa": round(float(wss.get("p95_Pa", float("nan"))), 3),
            "resistance_total": f"{round(resistance, 1)} Pa/(L/s)",
        },
        "curve": {},
        "_resistance_note": "定流量口径（Run-A dP/Q）；等压法自然分流口径需 Run-B 等压迭代",
        "_source": "本例后处理 metrics.json（run_all 汇编）",
    }
    # 完备性检查：step5 契约必需字段（_METRICS_REQ/_CURVE_REQ 口径）
    required_metrics = ["dP_baseline_Pa", "dP_1mm_Pa", "dP_2mm_Pa", "dP_3mm_Pa",
                        "dP_note", "split_L_pct", "split_R_pct",
                        "wss_mean_Pa", "wss_p95_Pa", "resistance_total"]
    required_curve = ["volumes_cm3", "dP_Pa", "band_Pa"]
    missing = [k for k in required_metrics if k not in contract["metrics"]]
    missing += [k for k in required_curve if k not in contract["curve"]]
    return contract, missing


# ---------------------------------------------------------------- S5 笔记本交接文档
HANDOVER_DOC = """# 交接文档：@CASE_NAME@ 算例（台式机 → 笔记本执行代理）

> **你是谁**：笔记本上的 AI 执行代理。
> **任务来源**：T12 多患者通用化批——患者@LETTER@ 试点（赛方 2026-09-30 发放 CT）。
> **一句话任务**：把共享文件夹里的 @CASE_NAME@ / @CASE_NAME_B@ 两个算例拷到本机 WSL → 各自跑通 simpleFoam → 把完整结果拷回共享文件夹并回报。
> **预计总耗时**：环境安装 5-10 分钟（一次性，已装 OpenFOAM 则跳过）+ 求解 2×15-30 分钟。

---

## 0. 背景与目的（30 秒读懂）

- 本算例系**多患者通用化验证试点**（V1.0 §效率/批量 非功能项）：患者@LETTER@ 与患者A 全系隔离（编号前缀 @PREFIX@），**不进演示基线**。
- 数据来源：赛方 2026-09-30 官方渠道发放（患者A 授权链模式之外的新渠道）；匿名化逐头核验 ALL_PASS（@PII_SUMMARY@）。
- 两包是否同一患者：**待赛方确认**（如实披露，不臆断）。
- 几何口径与 v5 基线同设计：无延长段（入口=鼻孔自然开口、出口=鼻咽截断面）、@SINUS_SCOPE@——与 v5 基线可比口径。
- 朝向已验证：run_all 几何断言 6 项全 PASS（@ORIENT_SUMMARY@），层序方向@ZDIR_DESC@。

## 0.5 分割 QC 披露（@SEQ_KIND@序列，如实记录保真度局限）

- 气道掩码：@QC_MASKVOX@ 体素 = @QC_VOL@ cm³；z 跨度 @QC_ZSPAN@ mm（@QC_NAIR@/@QC_NLAYER@ 层含气）；合并后连通域 **@QC_COMPONENTS@**（散在气腔未并入主组件）
- 入口面积 inletL @QC_INLET_L@ / inletR @QC_INLET_R@ mm²；最小截面积 @QC_MINAREA@ mm²（层 @QC_MINLAYER@/@QC_NLAYER@，z=@QC_MINZ@ mm）
- STL 水密性：**@QC_WATERTIGHT@**
- **体积回归比 @QC_VOLRATIO@**（step2 回归校验闸门 0.94–1.06，@QC_VOLREG_VERDICT@）——@QC_VOLREG_NOTE@
- **保真度局限（如实披露）**：@QC_FIDELITY_NOTE@
- 身份注记：本序列与患者B 主序列的 StudyInstanceUID / SeriesInstanceUID / FrameOfReferenceUID **三者全不同**（扫描会话实证不同：2024-01-17 vs 2025-12-10），是否同一患者**待赛方确认**（本批按"患者C（待确认）"口径处理，不臆断）。
@HANDOVER_NOTE@
@MERGE_MODE_BLOCK@

## 1. 算例清单与关键数字

| 算例 | 内容 | 单元 | 内部面 | outlet | walls | inletL | inletR | 域体积 |
|---|---|---|---|---|---|---|---|---|
| @CASE_NAME@ | 患者@LETTER@ 气道（Run-A 指定流量） | @CELLS@ | @IFACES@ | @OUTLET@ | @WALLS@ | @INLETL@ | @INLETR@ | @VOL@ cm³ |

- 入口边界条件（Run-A）：flowRateInletVelocity 总 @QTOT@ L/min，按端口面积分配（**建模假设**，与 v5 同口径）：
  - inletL @AL@ mm² → @QL@ L/min / inletR @AR@ mm² → @QR@ L/min
- 掩码：@MASKVOX@ 体素（@MASKVOL@ cm³，@NZ@ 层），网格体积回归比 @VOLRATIO@（网格体素 @VOXELMM@ mm）。
- Run-B（@CASE_NAME_B@）：双侧入口等压 80 (kinematic, 约 98 Pa) 压力驱动，输出真实自然分流比与鼻腔阻力 R=ΔP/Q。
- **求解器设置（笔记本侧对齐口径，T13b 起显式写明）**：simpleFoam laminar steady，**nu=1.8e-5 m²/s**——与算例 `constant/transportProperties` 一致（审计Y2：气道内空气~35C）；**post_cfd 脚本 --nu 1.8e-5 显式传入，勿用 pB 脚本默认 1.48e-5**（1.48e-5 对应 15C，压降会低估 22%）。
- mesh check 记录：笔记本侧 checkMesh 后回填（体素六面体直出网格；v5 系同法全 PASS 先例：重复面 0 / 退化面 0 / 非流形边 0）。
- **体积比双口径（T14b 起分别标注，笔记本建议④）**：①**交付网格口径**（算例级，台式机侧 step2 输出，case_stats 的 volume_regression_ratio）= ds2 单元数 × 体素体积 / step1 气道体积 = **@VOLRATIO@**（@VOLRATIO_VERDICT@）（本例 = ds2 单元 14,242 × 3.011mm³ / 掩码 40.29cm³）；笔记本 checkMesh 实测 Total volume 与之同口径（v3 先例：实测 42.63 / 40.07 = 1.064）；②**全分辨率口径**（DeepSeek 口径，round2 §5.3：ds2 守卫输出未截断体素口径）= v3 先例 1.1728（47.0 / 40.07）——本例同口径复算待笔记本侧确认（v4 守卫后 14,544 cells 在案，v3 为 14,468）。两口径差异原因：①为 L3 截断后实际交付网格（渐细尾巴已截），②为截断前全分辨率融合域，故②≥①；越 0.94–1.06 标准带时两口径按同一豁免带口径处理。

## 2. 台式机侧环境探测结论（本批）

本机 OpenFOAM 探测：**wsl 无发行版 / docker / foamExec / ifoam / simpleFoam / blockMesh 全 ABSENT**（@PROBE_DETAIL@）→ 算例停在待解态，按既有"笔记本执行"交接模式由笔记本执行代理求解。

## 3. 环境准备（只做一次）

```powershell
# Windows 侧：确认 WSL 有 Linux 发行版（需 Ubuntu 20.04+）
wsl -l -v
```

```bash
# WSL 内：检查/安装 OpenFOAM（openfoam.com 官方源，版本 2406）
which simpleFoam || ls /usr/lib/openfoam 2>/dev/null
# 未装则：
sudo sh -c "wget -O - https://dl.openfoam.com/add-debian-repo.sh | bash"
sudo apt-get update && sudo apt-get install -y openfoam2406-default
echo 'source /usr/lib/openfoam/openfoam2406/etc/bashrc' >> ~/.bashrc
source ~/.bashrc
simpleFoam -help   # 打印帮助 = 就绪
```

注意：算例按 **openfoam.com（ESI）经典格式**书写；openfoam.**org** v11/v12 文件名不兼容，请装 `.com` 版。

## 4. 拷贝算例到 WSL 本地（勿在网络共享/mnt 路径上直接运行）

```powershell
# Windows 侧：从共享目录拷到本地（无映射盘先 net use，方法同既有交接文档）
Copy-Item "\\<台式机>\\参加比赛\\...\\pipeline\\out\\step2\\@CASE_NAME@" C:\\temp\\ -Recurse
# @CASE_NAME_B@ 同理（或先解压同目录 .zip）
```

```bash
# WSL 侧：
cp -r /mnt/c/temp/@CASE_NAME@ ~/P0-case-@PREFIX@-@CASE@
cd ~/P0-case-@PREFIX@-@CASE@ && ls 0 constant system Allrun   # 四件齐全才继续
chmod +x Allrun
```

## 5. 运行与验收标准

```bash
cd ~/P0-case-@PREFIX@-@CASE@ && ./Allrun
```

`Allrun` 依次执行：`checkMesh` → `simpleFoam`（最多 1500 步，残差达标自动停）→ `foamToVTK -latestTime`。

**成功判据（三条全满足）**：
1. `log.checkMesh` 出现 `Mesh OK`（体素正交网格，正常必过；本例预期 Total volume ≈ @VOL@ cm³）
2. `log.simpleFoam` 出现 `SIMPLE solution converged`（p、U 初始残差 < 1e-4 自动停），或跑满 1500 步（汇报第 1500 步残差）
3. `VTK/` 含最新时间步的 `U`、`p` 场文件

**验收门槛（case_stats release_gates 逐条核对）**：
@RELEASE_GATES@

**Run-B（@CASE_NAME_B@）先例提示**：v4B/v5B 五连败结论——层流框架下压力驱动大概率不可解（Re~10⁴）。若发散，**不要硬跑**：沿用等压迭代法（以对应 Run-A 平衡场为链式初场，双侧入口等压迭代，二分至 |ΔP_L−ΔP_R|<0.2%）交付自然分流比，即 Run-B 交付物。

**异常处理**：运行超 90 分钟、残差不降反升、或 `Floating point exception` → Ctrl+C 终止，已自动保存时间步（500/1000）数据仍可用，回传并在回报中说明；回传前把 `log.simpleFoam` 最后 50 行贴进回报。

## 5.5 冒烟测试 SOP（T14d 起按诊断报告12 §六新基准——全量前先跑 10 步闸门）

诊断报告12 勘误：旧判据（首步 O(10×流量) 且即衰减）双向失准——健康例前 10 步振荡 98–482× 不衰减（旧判据假阳性）；pA-v1 首步仅 10.7× 却 step15 FPE（旧判据假阴性）。**有区分力的签名是第 2 步**：健康例第 2 步 84–118× 有界（sum local ~0.5–0.6）vs 发散例 pA-v1 第 2 步 4,528× 无界（sum local 9.37）。根因（补桥对角接触）已由 T14b 面连接修复，但**全量跑前必须先过 10 步冒烟闸门**：

```powershell
# Windows 侧：复制冒烟算例（不污染正式算例目录）
Copy-Item C:\\temp\\P0-case-@PREFIX@-@CASE@ C:\\temp\\P0-case-@PREFIX@-@CASE@-smoke -Recurse
```

```bash
# WSL 侧：endTime 改 10，先跑 10 步
cd ~/P0-case-@PREFIX@-@CASE@-smoke
sed -i 's/^endTime[ \\t]*.*/endTime         10;/' system/controlDict
simpleFoam > log.simpleFoam.smoke 2>&1
head -40 log.simpleFoam.smoke
```

**判据**（看 `log.simpleFoam.smoke` **第 2 步** `time step continuity errors` 的 `global` 值与 `sum local`）：
- **PASS 信号**：第 2 步 global continuity **≤~120× 流量且有界**（健康例先例 84–118×，`sum local` <~1）→ 把 `endTime` 恢复 1500，跑全量 `./Allrun`
- **FAIL（立即中止，不跑全程）**：第 2 步**数百倍（O(1000×)）无界**（`sum local` >~5；pA-v1 先例 4,528× / 9.37）→ Ctrl+C 终止；把 `log.simpleFoam.smoke` 首 50 行贴进回报，并把 `P0-case-@PREFIX@-@CASE@-smoke` 目录回传共享树，台式机侧诊断后再下发

## 6. 结果回传（必须完整）

```bash
cp -r ~/P0-case-@PREFIX@-@CASE@ /mnt/c/temp/P0-result-@PREFIX@-@CASE@
```

```powershell
Copy-Item C:\\temp\\P0-result-@PREFIX@-@CASE@ "\\台式机\\参加比赛\\...\\pipeline\\out\\结果\\" -Recurse
```

回传目录必须含：`log.checkMesh`、`log.simpleFoam`、`VTK/`、`constant/`、`system/`、`0/`、时间步目录。**另需笔记本侧后处理**：按患者A 既有后处理脚本口径生成 `后处理\\metrics.json`（patches/totals/wss 三段齐全），回传目录须含之——run_all 后处理环节直接读它汇编 meta 契约。

## 7. 回报格式

```
[CFD执行结果 @CASE_NAME@]
- Mesh OK: 是/否（总体积 cm³）
- 收敛: <步数> 步收敛 或 跑满1500步（最终残差 p=?, U=?）
- Δp = ? Pa
- 运行时长: <分钟>
- 结果位置: 结果\\P0-result-@PREFIX@-@CASE@\\
- 异常: <无 / log尾部摘录>
（@CASE_NAME_B@ 同格式；另报自然分流比 L%/R%）
```

## 8. 披露与注意事项（重要）

- **ν 口径**：`transportProperties` 的 `nu` 字段填 1.8e-5（与 v5 冻结基线同口径）。该字段量纲为运动黏度，1.8e-5 实为空气动力黏度数值——修正后雷诺数 R≈55，方向保守。披露详见《需求符合度自评-33条-终审版-20261002.md》ν 披露脚注。本算例沿用同口径以保证与基线可比。
- **跨患者对照**：本例与 v5 基线同几何口径（无延长段/鼻窦在域），Δp 可与 v5 基线对照解读（v5 基线数值属患者A 冻结资产，本批不引用、不移植）；但患者间解剖差异大，对照时须同时引用入口面积（本例 inletL @AL@ / inletR @AR@ mm²；v5 基线入口面积同属患者A 冻结资产）。
- **分流比口径**：Run-A 按面积分配流量是建模假设；真实自然分流比以 Run-B 等压迭代为准。
- **数据合规**：本例数据经逐头匿名化核验 ALL_PASS；两包是否同一患者待赛方确认；本算例不进演示基线。

## 9. 禁止事项

- **不修改** `0/`、`constant/`、`system/` 内任何文件
- **不改、不重跑** 患者A 系算例及其结果（v5/v5B/v5C 已冻结演示基线）
- 不运行 `blockMesh`/`snappyHexMesh`（网格已内置 `constant/polyMesh`）
- 不在共享目录或 `/mnt/` 路径上直接运行求解器
- **严禁把患者A 的 metrics 数字套用到本例查看器**（meta 契约必须由本例后处理 metrics.json 汇编）

## 10. 文件指针

- 算例（共享目录）：`pipeline\\out\\step2\\@CASE_NAME@{,B}\\` 及同名 `.zip`
- 统计：`pipeline\\out\\step2\\case_stats-@PREFIX@-@CASE@.json`（含 release_gates、t12_variant 记录）
- 掩码：`pipeline\\out\\step2\\mask_full-@PREFIX@-@CASE@.npz`
- 分割产物：`pipeline\\out\\step1\\airway_@PREFIX@_v2.stl`、`metrics_@PREFIX@_v2.json`、`qc_fig\\qc_@PREFIX@_mid.png`（中层切片 mask 叠加 CT，人工可读）
- 来源档案：`项目\\P0-鼻塞设计工具\\数据来源记录-赛方CT-20261002.md`
- 生成器：`pipeline\\run_all.py`（T12 总控）→ `step1_airway_segment.py` / `step2_make_ofcase.py`（T12 参数化版）

*文档生成：台式机代理 · @DATE@ · T12 多患者通用化批*
"""


def render_handover(doc, repl):
    for k, v in repl.items():
        doc = doc.replace(f"@{k}@", str(v))
    # 兜底：任何未替换令牌即报错（防模板令牌拼写不一致流出）
    leftover = re.findall(r"@[A-Z_]+@", doc)
    assert not leftover, f"handover 模板存在未替换令牌：{sorted(set(leftover))}"
    return doc


def zip_case_dir(case_dir, zip_path, extra_root_files=None):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        base = os.path.dirname(case_dir)
        for root, _dirs, files in os.walk(case_dir):
            for f in sorted(files):
                fp = os.path.join(root, f)
                zf.write(fp, os.path.relpath(fp, base))
        # T14b：case_stats + 掩码随包（zip 根目录，笔记本建议⑤）
        for fp in (extra_root_files or []):
            if os.path.isfile(fp):
                zf.write(fp, os.path.basename(fp))
    return zip_path


# ---------------------------------------------------------------- OpenFOAM 探测
def probe_openfoam():
    progs = ["simpleFoam", "blockMesh", "foamExec", "ifoam"]
    found = {p: (shutil.which(p) or "") for p in progs}
    wsl = ""
    try:
        # text=False + errors=replace：wsl 输出可能含非 UTF-8 字节
        #（读者线程 UnicodeDecodeError 噪音已如实处置）
        r = subprocess.run(["wsl", "-l", "-v"], capture_output=True, timeout=60)
        if r.returncode == 0:
            wsl = r.stdout.decode("utf-8", errors="replace").strip()
    except Exception:
        wsl = ""
    docker = shutil.which("docker") or ""
    rec = {"programs": found, "wsl": bool(wsl), "wsl_detail": wsl[:200], "docker": bool(docker)}
    rec["any_present"] = any(found.values()) or bool(wsl) or bool(docker)
    return rec


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser(
        description="P0 多患者通用化一键管线（T12）：step1→step2→[求解]→后处理→step5")
    ap.add_argument("--dicom-dir", required=True, help="DICOM 目录（本例 CT 序列）")
    ap.add_argument("--case-prefix", default="pA", help="病例前缀（默认 pA；pB 与患者A 全系隔离）")
    ap.add_argument("--case", default="v1", help="算例名（默认 v1；pA 回归基线用 v5）")
    ap.add_argument("--solve", choices=["local", "laptop", "skip"], default="skip",
                    help="求解模式（默认 skip：只到算例+断言）")
    ap.add_argument("--backend", choices=["auto", "custom", "openfoam"], default="auto",
                    help="求解后端（M3；默认 auto=custom 可用即用，否则 openfoam）。"
                         "custom=自研 FlowScope；openfoam=WSL 对拍基准")
    ap.add_argument("--out-root", default=None,
                    help="输出根目录（默认 pipeline/out；自测隔离用）")
    ap.add_argument("--patient-label", default=None,
                    help="metrics patient 字段（默认按 前缀+面内间距 自动生成）")
    ap.add_argument("--result-dir", default=None,
                    help="已回传的 CFD 结果目录（含 VTK/ 与 后处理/metrics.json）")
    ap.add_argument("--ext", action="store_true", help="透传 step2：入口+出口圆柱延长段")
    ap.add_argument("--ext-l-mm", type=float, default=15.0, help="透传 step2：延长段长度 mm")
    ap.add_argument("--ext-r-factor", type=float, default=1.05, help="透传 step2：延长段半径系数")
    ap.add_argument("--iso", action="store_true", help="透传 step2：去窦对照算例")
    # T14c 补丁（诊断决定轮·对照实验）：透传 step1+step2
    # --merge-mode（largest 现状默认/facegrow 6-conn 面连接
    # 生长并入咽部/base 仅最大 6-conn 连通域）。pA/pB 咽部
    # 识别为空 -> facegrow/base 与 largest 逐字节一致。
    ap.add_argument("--merge-mode", default="largest",
                    choices=["largest", "facegrow", "base"],
                    help="透传 step1/step2：T14c 并合模式"
                         "（largest 现状默认/facegrow 6-conn "
                         "面连接生长/base 仅最大连通域）")
    # T14d 补丁（E1 实验·z 降采样参数化）：透传 step2
    # --voxel-z（默认 2.0=现状 z 向 2 层多数表决，逐字节
    # 兼容；1.0=不降采样——pC 源序列层厚 1.0mm，E1 实验）。
    ap.add_argument("--voxel-z", type=float, default=2.0,
                    help="透传 step2：z 向体素尺寸 mm"
                         "（默认 2.0=现状 z 向 2 层多数表决；"
                         "1.0=不降采样，T14d/E1）")
    ap.add_argument("--hu-air", type=int, default=-400, help="透传 step1：空气阈值 HU（§5.3）")
    ap.add_argument("--hu-head", type=int, default=-300, help="透传 step1：头部组织阈值 HU")
    ap.add_argument("--ph-dir", default=None, help="透传 step5：占位体 STL 目录")
    ap.add_argument("--skin-data-js", default=None, help="透传 step5：皮肤层数据")
    ap.add_argument("--allow-anatomy-inclusion", action="store_true",
                    help="T14：允许真实解剖纳入（患者C 咽部 2.77cm3）——"
                         "体积回归比闸门上带 1.06->1.30（覆盖 pC 1.1728；"
                         "DeepSeek round2 §5.3-1 实验在案：咽部系真实解剖，"
                         "无实验可回避）；下带 <0.94 与 >1.30 照常硬停")
    # T15A：交付物回传（可选终步）——未指定则仅末尾打印回传提醒
    ap.add_argument("--publish", default=None, metavar="<共享目录>",
                    help="T15A：所有步骤完成后，把交付物（算例 zip / "
                         "case_stats / manifest&deferred JSON / "
                         "viewer_single.html / 交接文档）复制到指定共享"
                         "目录并逐件 Test-Path + md5（可选）")
    ARGS = ap.parse_args()

    t_start = time.time()
    DICOM_DIR = os.path.abspath(ARGS.dicom_dir)
    PREFIX = ARGS.case_prefix
    CASE = ARGS.case
    CASE_NAME = f"P0-OF-case-{PREFIX}-{CASE}"
    CASE_NAME_B = f"{CASE_NAME}B"
    SOLVE = ARGS.solve
    OUT_ROOT = os.path.abspath(ARGS.out_root) if ARGS.out_root else os.path.join(HERE, "out")
    os.makedirs(OUT_ROOT, exist_ok=True)
    # T15 修订5：进度文件=本例 out-root 下 manifest-progress.json（新一轮清空旧进度）
    global _PROGRESS_PATH
    _PROGRESS_PATH = os.path.join(OUT_ROOT, "manifest-progress.json")
    with open(_PROGRESS_PATH, "w", encoding="utf-8") as _pf:
        _pf.write("")

    letter = PREFIX[1].upper() if len(PREFIX) > 1 and PREFIX[0].lower() == "p" else PREFIX.upper()
    manifest = {
        "run_all_version": T12_VERSION,
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        # T15A：--publish 仅用于末尾 S9 回传，不入 args（保默认 manifest 逐字节同上一版）
        "args": {k: v for k, v in vars(ARGS).items() if k != "publish"},
        "out_root": OUT_ROOT,
        "stages": {},
        "assertions": {},
        "artifacts": {},
        "patient_a_isolation": {
            "frozen_assets_untouched": True,
            "note": "输出全部落在 out_root 树下；非 pA 前缀文件名带前缀隔离；"
                    "run_all 不写共享目录 viewer_data.js / six_boards.json（仅 step5 显式同步且仅 pA+默认 out-dir 模式）",
        },
    }

    log(f"=== P0 一键管线 T12 === 前缀={PREFIX} 算例={CASE} 求解={SOLVE}")
    log(f"DICOM: {DICOM_DIR}")
    log(f"输出根: {OUT_ROOT}")

    # ---- S0 PII 头扫描 ----
    log("[S0] PII 头扫描 ...")
    pii = scan_pii(DICOM_DIR)
    manifest["stages"]["S0_pii_scan"] = pii
    if not pii["pass"]:
        manifest["assertions"]["pii"] = "FAIL"
        die(2, f"PII 头扫描 FAIL ×{pii['fail_count']}（首条：{pii['fails'][0] if pii['fails'] else '?'}）——停工上报")
    manifest["assertions"]["pii"] = "PASS"
    log(f"  PASS：{pii['files']} 头全过；PatientID 值域={pii['pid_values']}；"
        f"非空字段={pii['pii_nonempty_summary'] or '无'}")

    # ---- S1 DICOM 头普查 ----
    log("[S1] DICOM 头普查 ...")
    survey = survey_dicom(DICOM_DIR)
    manifest["stages"]["S1_dicom_survey"] = survey
    n_layers, rows, cols = survey["file_count"], survey["rows"], survey["columns"]
    if n_layers < 1 or rows < 1 or cols < 1:
        die(2, f"维度动态断言 FAIL：层数/行/列 = {n_layers}/{rows}/{cols}")
    sx, sy = round(survey["pixel_spacing"][0], 4), round(survey["pixel_spacing"][1], 4)
    sz = round(survey["slice_gap_measured"], 4)
    log(f"  {n_layers} 层 {rows}x{cols}；面内间距 {sx}x{sy} mm；"
        f"实测层间距 {sz} mm（头值 {survey['slice_thickness_header']} mm）；"
        f"z 单调{'增' if survey['z_monotonic_increasing'] else '减' if survey['z_monotonic_decreasing'] else '？'}；"
        f"文件名序{'=' if survey['filename_order_matches_physical'] else '≠'}物理序")
    if not survey["filename_order_matches_physical"]:
        die(2, "层序方向断言 FAIL：z 序列非单调——层序混乱，停工上报")

    # patient-label 默认：前缀字母 + 面内间距（pA 与原版默认逐字节兼容）
    if ARGS.patient_label:
        patient_label = ARGS.patient_label
    else:
        patient_label = f"{letter} (soft tissue window, ISO {round(sx, 3)}mm)"
    log(f"  patient-label = {patient_label!r}")

    # ---- S2 step1 气道分割 ----
    log("[S2] step1 气道分割 ...")
    step1_out = os.path.join(OUT_ROOT, "step1")
    cmd1 = [sys.executable, STEP1,
            "--dicom-dir", DICOM_DIR,
            "--out-dir", step1_out,
            "--case-prefix", PREFIX,
            "--patient-label", patient_label,
            "--hu-air", str(ARGS.hu_air),
            "--hu-head", str(ARGS.hu_head),
            "--merge-mode", ARGS.merge_mode]
    log("  $ " + " ".join(cmd1))
    r = subprocess.run(cmd1)
    if r.returncode != 0:
        die(2, f"step1 失败（exit {r.returncode}）")
    suf = "" if PREFIX == "pA" else f"_{PREFIX}"
    step1_arts = {
        "stl": os.path.join(step1_out, f"airway_{PREFIX}_v2.stl"),
        "curve_png": os.path.join(step1_out, f"area_curve{suf}_v2.png"),
        "views_png": os.path.join(step1_out, f"mask_views{suf}_v2.png"),
        "csv": os.path.join(step1_out, f"area_per_slice{suf}_v2.csv"),
        "metrics": os.path.join(step1_out, f"metrics{suf}_v2.json"),
        "qc_fig": os.path.join(step1_out, "qc_fig", f"qc_{PREFIX}_mid.png"),
    }
    for k, p in step1_arts.items():
        if not os.path.isfile(p):
            die(2, f"step1 产物缺失：{p}")
    # 维度动态断言：CSV 行数 == DICOM 层数
    with open(step1_arts["csv"], encoding="utf-8") as f:
        csv_rows = sum(1 for _ in f) - 1  # 含表头
    if csv_rows != n_layers:
        die(2, f"维度动态断言 FAIL：截面积 CSV 行数 {csv_rows} ≠ DICOM 层数 {n_layers}")
    m1 = json.load(open(step1_arts["metrics"], encoding="utf-8"))
    manifest["stages"]["S2_step1"] = {
        "outputs": {k: os.path.relpath(p, OUT_ROOT) for k, p in step1_arts.items()},
        "md5": {k: md5_of(p) for k, p in step1_arts.items()},
        "airway_volume_cm3": m1["airway_volume_cm3"],
        "min_axial_area_mm2": m1["min_axial_area_mm2"],
        "n_slices_with_air": m1["n_slices_with_air"],
        "csv_rows": csv_rows,
        "dimension_assert": f"PASS（{csv_rows} == {n_layers}）",
    }
    log(f"  PASS：气道 {m1['airway_volume_cm3']} cm³；最小截面积 {m1['min_axial_area_mm2']} mm²；"
        f"维度断言 {csv_rows}=={n_layers}；QC 图 {os.path.basename(step1_arts['qc_fig'])}")

    # ---- S3 step2 算例生成 ----
    log("[S3] step2 算例生成 ...")
    cmd2 = [sys.executable, STEP2,
            "--dicom-dir", DICOM_DIR,
            "--case", CASE,
            "--case-prefix", PREFIX,
            "--out-root", OUT_ROOT]
    if ARGS.ext:
        cmd2.append("--ext")
    cmd2 += ["--ext-l-mm", str(ARGS.ext_l_mm), "--ext-r-factor", str(ARGS.ext_r_factor)]
    if ARGS.iso:
        cmd2.append("--iso")
    cmd2 += ["--merge-mode", ARGS.merge_mode]
    cmd2 += ["--voxel-z", str(ARGS.voxel_z)]     # T14d：z 降采样因子透传（默认 2.0 向后兼容）
    log("  $ " + " ".join(cmd2))
    r = subprocess.run(cmd2)
    if r.returncode != 0:
        die(2, f"step2 失败（exit {r.returncode}）")
    case_dir = os.path.join(OUT_ROOT, "step2", CASE_NAME)
    case_dir_b = os.path.join(OUT_ROOT, "step2", CASE_NAME_B)
    for d in (case_dir, case_dir_b):
        need = ["Allrun", os.path.join("0", "p"), os.path.join("0", "U"),
                os.path.join("constant", "transportProperties"),
                os.path.join("constant", "turbulenceProperties"),
                os.path.join("constant", "polyMesh", "boundary"),
                os.path.join("constant", "polyMesh", "faces"),
                os.path.join("constant", "polyMesh", "neighbour"),
                os.path.join("constant", "polyMesh", "owner"),
                os.path.join("constant", "polyMesh", "points"),
                os.path.join("system", "controlDict"),
                os.path.join("system", "fvSchemes"),
                os.path.join("system", "fvSolution")]
        for rel in need:
            if not os.path.isfile(os.path.join(d, rel)):
                die(2, f"step2 产物缺失：{os.path.join(d, rel)}")
    _mask_name = ("mask_full.npz" if (PREFIX == "pA" and CASE == "v5")
                  else (f"mask_full-{CASE}.npz" if PREFIX == "pA"
                        else f"mask_full-{PREFIX}-{CASE}.npz"))
    _stats_name = ("case_stats.json" if (PREFIX == "pA" and CASE == "v5")
                   else (f"case_stats-{CASE}.json" if PREFIX == "pA"
                         else f"case_stats-{PREFIX}-{CASE}.json"))
    mask_npz = os.path.join(OUT_ROOT, "step2", _mask_name)
    stats_json = os.path.join(OUT_ROOT, "step2", _stats_name)
    for p in (mask_npz, stats_json):
        if not os.path.isfile(p):
            die(2, f"step2 产物缺失：{p}")
    stats = json.load(open(stats_json, encoding="utf-8"))
    # ---- T13b 闸门升级（治理修复；诊断报告8 上层裁定①②） ----
    # 闸门 1：体积回归比硬停（警告→硬停）——越出 0.94–1.06 带即中止
    #           算例下发，输出 QC 证据链待指挥官裁决（pC-v1 回归比
    #           0.915 若有此闸，笔记本空跑一轮可免）。
    # T14：--allow-anatomy-inclusion 旗（患者C 咽部 2.77cm3 真实
    #           解剖纳入，体积比 1.1728，DeepSeek round2 §5.3-1 实验
    #           在案无回避方案）——闸门上带 1.06->1.30；下带 <0.94
    #           与其余漂移照常硬停。
    _allow_anat = bool(getattr(ARGS, "allow_anatomy_inclusion", False))
    _band_hi = 1.30 if _allow_anat else 1.06
    _rv = stats.get("volume_regression_ratio")
    _vx = stats.get("voxel_mm", [])
    _dsvol_cm3 = (stats.get("cells", 0) * _vx[0] * _vx[1] * _vx[2] / 1000.0) \
        if len(_vx) == 3 else float("nan")
    if _rv is None or not (0.94 <= _rv <= _band_hi):
        die(2, f"体积回归比闸门 FAIL：{_rv} 越出 0.94–{_band_hi:.2f} 带"
               f"（step2 多数表决降采样回归校验，T13b 起警告升硬停"
               + ("；T14 解剖纳入豁免旗生效，上带 1.30"
                  if _allow_anat else "")
               + f"）——中止算例下发，待指挥官裁决。QC 证据链：网格单元 "
               f"{stats.get('cells'):,} / 体素 "
               f"{'×'.join(str(v) for v in _vx)} mm → 网格体积 "
               f"{_dsvol_cm3:.1f} cm³ / 回归比 {_rv}"
               f"（对照 pC-v1 病灶：出口截断层多数表决塌缩，诊断报告8）")
    # 闸门 2：出口多面断言（step2 后、算例打包前）——outlet 面数 ≥50
    #           且面积 ≥ 掩码最小截面积 ×0.3（pC-v1 单面出口 1.5045mm²
    #           这类退化在台式机侧就地拦截，不下发笔记本）。
    out_faces = int(stats["patch_face_counts"]["outlet"])
    out_area = float(stats.get("outlet_area_mm2", 0.0))
    min_area = float(m1["min_axial_area_mm2"])
    if out_faces < 50 or out_area < 0.3 * min_area:
        die(2, f"出口多面断言 FAIL：outlet {out_faces} 面（需 ≥50）/ "
               f"面积 {out_area} mm²（需 ≥ 掩码最小截面积 {min_area} mm²"
               f" ×0.3 = {0.3 * min_area:.1f} mm²）——出口截面退化"
               f"（诊断报告8 病灶：多数表决半块结构性塌缩），中止算例下发。"
               f"QC 对照：inletL {stats['inletL']['area_mm2']} / "
               f"inletR {stats['inletR']['area_mm2']} mm²")
    manifest["stages"]["S3_step2"] = {
        "case_dir": os.path.relpath(case_dir, OUT_ROOT),
        "case_dir_b": os.path.relpath(case_dir_b, OUT_ROOT),
        "case_files": sum(len(fs) for _r, _d, fs in os.walk(case_dir)),
        "case_files_b": sum(len(fs) for _r, _d, fs in os.walk(case_dir_b)),
        "mask_npz": os.path.relpath(mask_npz, OUT_ROOT),
        "mask_md5": md5_of(mask_npz),
        "stats_json": os.path.relpath(stats_json, OUT_ROOT),
        "cells": stats["cells"], "internal_faces": stats["internal_faces"],
        "patch_face_counts": stats["patch_face_counts"],
        "inletL": stats["inletL"], "inletR": stats["inletR"],
        "runA_flux_Lmin": stats["runA_flux_Lmin"],
        "voxel_mm": stats["voxel_mm"],
        "volume_regression_ratio": stats["volume_regression_ratio"],
        "t12_variant": stats.get("t12_variant"),
    }
    log(f"  PASS：{CASE_NAME} 单元 {stats['cells']:,} / 内部面 {stats['internal_faces']:,}；"
        f"inletL {stats['inletL']['area_mm2']} mm² / inletR {stats['inletR']['area_mm2']} mm²；"
        f"Run-A 分流 {stats['runA_flux_Lmin']} L/min")

    # ---- S4 朝向几何断言 ----
    log("[S4] 朝向几何断言（6 项）...")
    mask = np.load(mask_npz)["mask"]
    if tuple(mask.shape) != (n_layers, rows, cols):
        die(2, f"维度动态断言 FAIL：mask 形状 {mask.shape} ≠ ({n_layers}, {rows}, {cols})")
    checks, orient_meta = orientation_assertions(
        stats, mask, sx, sy, sz, merge_mode=ARGS.merge_mode)
    orient_fail = [c for c in checks if not c[1]]
    manifest["assertions"]["orientation"] = {
        "all_pass": len(orient_fail) == 0,
        "checks": [{"name": c[0], "pass": bool(c[1]), "detail": c[2]} for c in checks],
        "meta": orient_meta,
    }
    for name, ok, detail in checks:
        log(f"  {'PASS' if ok else 'FAIL'}  {name}  [{detail}]")
    if orient_fail:
        die(2, "朝向几何断言 FAIL ×" + str(len(orient_fail))
            + "（层序方向未验证或数据异常）——停工上报，不许默认层序正确")
    zdir_desc = "与文件名序一致（z 单调增）" if survey["z_monotonic_increasing"] \
        else "与文件名序相反（z 单调降，step1 按物理 z 排序不受影响）"
    log(f"  全部 6 项 PASS；mask 形状 {mask.shape} == DICOM 维度（动态确认）")

    # ---- S5 求解分支 ----
    log(f"[S5] 求解模式 = {SOLVE} ...")
    if SOLVE == "skip":
        manifest["stages"]["S5_solve"] = {"mode": "skip", "note": "只到算例+断言（自测/隔离比对）"}
        log("  skip：跳过求解/后处理/step5")
    elif SOLVE == "local":
        # ---- M3：求解后端抽象（custom=自研 FlowScope / openfoam=对拍基准）----
        try:
            backend = SB.resolve_backend(ARGS.backend)
        except ValueError as e:
            die(2, str(e))
        status = SB.backend_status(ARGS.backend)
        manifest["stages"]["S5_solve"] = {
            "mode": "local", "backend": backend, "backend_status": status}
        log(f"  求解后端 = {backend}（requested={status['requested']}；"
            f"custom={'可用' if status['custom_available'] else '不可用'}；"
            f"openfoam={'可用' if status['openfoam_available'] else '不可用'}）")
        # Run-B 路由披露（行为边界：pA 满分辨率 Run-B 走 openfoam 真值）
        try:
            runb = SB.choose_run_b_backend(stats.get("cells", 0), ARGS.backend)
        except Exception:  # noqa: BLE001
            runb = backend
        manifest["stages"]["S5_solve"]["run_b_routing"] = {
            "cells": stats.get("cells"), "backend": runb,
            "rule": f"cells <= {SB.RUNB_CUSTOM_MAX_CELLS} -> custom; else openfoam",
        }
        log(f"  Run-B 路由：cells={stats.get('cells')} -> {runb}"
            f"（阈值 {SB.RUNB_CUSTOM_MAX_CELLS}；pA 满分辨率已知失稳，走 openfoam）")

        if backend == "custom":
            if not status["custom_available"]:
                die(3, "backend=custom 但 FlowScope 可执行文件不存在——请先 "
                        "cargo build --release（code/solver）或设 FLOWSCOPE_BIN，"
                        "或改 --backend openfoam/auto")
            result_dir = (os.path.abspath(ARGS.result_dir) if ARGS.result_dir
                          else os.path.join(OUT_ROOT, "结果",
                                            f"P0-result-{PREFIX}-{CASE}"))
            metrics_json = os.path.join(result_dir, "后处理", "metrics.json")
            if os.path.isfile(metrics_json):
                log(f"  复用已有 custom 结果目录：{result_dir}（不重跑求解）")
                manifest["stages"]["S5_solve"]["status"] = "reused"
            else:
                os.makedirs(result_dir, exist_ok=True)
                log(f"  custom 求解：{case_dir} -> {result_dir}（1500 步上限）")
                rc, metrics_path = SB.run_custom(
                    case_dir, result_dir, max_iter=1500,
                    progress=log, tag="custom " + CASE_NAME)
                manifest["stages"]["S5_solve"].update({
                    "status": "solved" if rc == 0 else "failed",
                    "rc": rc,
                    "metrics": metrics_path,
                    "result_dir": result_dir,
                })
                if rc != 0:
                    die(3 if rc in (-999, -998) else 2,
                        f"custom 求解失败（rc={rc}）；日志："
                        f"{os.path.join(result_dir, 'solver.log')}")
            run_postprocess_and_step5(manifest, result_dir, OUT_ROOT, PREFIX, CASE,
                                      letter, CASE_NAME, DICOM_DIR, sx, ARGS)
        else:
            probe = probe_openfoam()
            manifest["stages"]["S5_solve"]["probe"] = probe
            log(f"  OpenFOAM 探测：simpleFoam={'有' if probe['programs']['simpleFoam'] else '无'} "
                f"blockMesh={'有' if probe['programs']['blockMesh'] else '无'} "
                f"wsl={'有' if probe['wsl'] else '无'} docker={'有' if probe['docker'] else '无'}")
            if not probe["any_present"]:
                die(3, "本机 OpenFOAM 环境探测全 ABSENT——openfoam 后端不可用；"
                        "请改用 --solve laptop（交接文档+算例包）或 --backend custom")
            # 有环境：检查结果目录是否已回传
            result_dir = resolve_result_dir(ARGS.result_dir, OUT_ROOT, PREFIX, CASE)
            if result_dir is None:
                log("  本机 OpenFOAM 就绪，但未给出结果目录——请在 WSL 运行 Allrun 后，"
                    "以 --result-dir <结果目录> 重跑本脚本进入后处理+step5")
                manifest["stages"]["S5_solve"]["status"] = "awaiting_Allrun"
            else:
                run_postprocess_and_step5(manifest, result_dir, OUT_ROOT, PREFIX, CASE,
                                          letter, CASE_NAME, DICOM_DIR, sx, ARGS)
    else:  # laptop
        run_laptop_handover(manifest, OUT_ROOT, PREFIX, CASE, CASE_NAME, CASE_NAME_B,
                            letter, stats, survey, pii, mask, m1, sx, sy, sz,
                            zdir_desc, DICOM_DIR,
                            allow_anat=bool(getattr(
                                ARGS, "allow_anatomy_inclusion", False)),
                            merge_mode=ARGS.merge_mode)

    # ---- S8 manifest 落盘 ----
    manifest["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    manifest["elapsed_sec"] = round(time.time() - t_start, 1)
    manifest_path = os.path.join(OUT_ROOT, f"run_all_manifest-{PREFIX}-{CASE}.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    log(f"manifest -> {manifest_path}")
    log(f"=== run_all 完成（{manifest['elapsed_sec']} s）===")
    # ---- S9 交付物回传（T15A 可选终步）----
    if ARGS.publish:
        publish_deliverables(OUT_ROOT, PREFIX, CASE, CASE_NAME, CASE_NAME_B,
                             ARGS.publish)
    else:
        log("提醒：交付物在 pipeline\\out\\，请回传共享树"
            "（未指定 --publish，本轮不自动回传；本次输出根 = " + OUT_ROOT + "）")


def resolve_result_dir(result_dir_arg, out_root, prefix, case):
    if result_dir_arg:
        cand = os.path.abspath(result_dir_arg)
        return cand if os.path.isdir(cand) else None
    cand = os.path.join(out_root, "结果", f"P0-result-{prefix}-{case}")
    return cand if os.path.isdir(cand) else None


def find_vtu(result_dir):
    cands = sorted(glob.glob(os.path.join(result_dir, "VTK", "*", "internal.vtu")))
    return cands[-1] if cands else None


# ---------------------------------------------------------------- laptop 交接
def run_laptop_handover(manifest, OUT_ROOT, PREFIX, CASE, CASE_NAME, CASE_NAME_B,
                        letter, stats, survey, pii, mask, m1, sx, sy, sz,
                        zdir_desc, DICOM_DIR, allow_anat=False,
                        merge_mode="largest"):
    """--solve laptop：交接文档 + 算例包 zip；后处理/step5 标记待解算后补导出。"""
    cells = stats["cells"]
    voxel_vol = stats["voxel_mm"][0] * stats["voxel_mm"][1] * stats["voxel_mm"][2]  # mm³
    domain_vol_cm3 = round(cells * voxel_vol / 1000.0, 2)
    mask_vox = int(mask.sum())
    mask_vol_cm3 = round(mask_vox * sx * sy * sz / 1000.0, 2)
    al, ar = stats["inletL"]["area_mm2"], stats["inletR"]["area_mm2"]
    ql, qr = stats["runA_flux_Lmin"]
    gates = json.dumps(stats.get("release_gates", []), ensure_ascii=False)
    gates_md = "\n".join(f"   {i+1}. {g}" for i, g in enumerate(stats.get("release_gates", [])))
    orient = manifest["assertions"]["orientation"]
    orient_summary = "；".join(
        f"{c['name'].split('（')[0]} {'PASS' if c['pass'] else 'FAIL'}"
        for c in orient["checks"])
    pii_summary = f"{pii['files']} 头 ALL_PASS"
    # ---- 分割 QC 披露变量（T13 新增；定性表述，不写患者A/B 具体数字） ----
    seq_kind = (f"{survey.get('convolution_kernel') or 'B'} 核 / "
                f"{survey['slice_thickness_header']:g}mm 层厚")
    _zs = np.where(mask)[0]
    mask_zspan_mm = (int(_zs.max()) - int(_zs.min()) + 1) * sz
    _r = stats.get("volume_regression_ratio")
    if _r is None:
        volreg_verdict = "未计算"
        volreg_note = "step2 未输出回归比（case_stats 缺字段）"
    elif 0.94 <= _r <= 1.06:
        volreg_verdict = "闸内"
        volreg_note = "CFD 域体积与分割掩码体积之比落 0.94–1.06 闸内"
    elif allow_anat and 1.06 < _r <= 1.30:
        # T14：解剖纳入豁免带（咽部 2.77cm3 真实解剖，
        # DeepSeek round2 §5.3-1 实验在案无回避方案）
        volreg_verdict = "闸内（解剖纳入豁免）"
        volreg_note = ("CFD 域体积与分割掩码体积之比越出 "
                       "0.94–1.06 标准带、落 1.06–1.30 豁免带"
                       "——T14 --allow-anatomy-inclusion 旗："
                       "咽部 2.77cm3 系真实解剖纳入（DeepSeek "
                       "round2 §5.3-1 实验在案，无实验可回避）；"
                       "其余漂移照常硬停")
    else:
        # T13b：闸门 1 硬停在先——越带算例到不了本分支
        #（防御性文本，与闸门 1 口径一致）
        volreg_verdict = "超限（硬停级）"
        volreg_note = ("CFD 域体积与分割掩码体积之比越出 0.94–1.06——"
                       "T13b 起闸门 1 硬停：越带即中止算例下发，"
                       "QC 证据链随报错信息上报指挥官裁决")
    fidelity_note = (f"{seq_kind}：部分容积效应使狭窄处（鼻瓣区）HU 抬高可能越过 "
                     f"-400 空气阈值，最小截面积与体积被低估（本例最小截面积 "
                     f"{m1['min_axial_area_mm2']} mm²，约为细层厚软组织窗序列先例的"
                     f"二分之一）；CFD ΔP 绝对值预期系统性偏高，不可与细层厚序列结果"
                     f"直接对照。拓扑（连通域 {m1['n_components_merged']}、朝向 6 项、"
                     f"{'水密' if m1['stl_watertight'] else '非水密'}、入口面积 "
                     f"{al}/{ar} mm²）正常——可解算，保真度局限披露在案")
    _t14_arch = stats.get("t14_arch")
    # ---- 患者C 专项注记（T13b；其他病例为空串，渲染后留空行无碍） ----
    # T14d 修复（T14c 潜伏 bug）：merge_mode_block 仅在
    # X1/X2 分支内赋值——v2/v3/v4/E1 等路径未定义即被
    # 渲染字典引用 -> UnboundLocalError（E1 实跑触发）。
    # 非 X1/X2 算例初始化为空串（渲染后留空行无碍）。
    merge_mode_block = ""
    if PREFIX == "pC" and CASE == "v2":
        handover_note = (
            "- **患者C 专项注记（T13b 批）**：①笔记本侧 OpenFOAM 环境"
            "已实测就绪（WSL Ubuntu + OpenFOAM 2406.com；pC-v1 已实测 "
            "Mesh OK、checkMesh 0 errors）——本算例**免环境准备，直接"
            "求解**；②**P0-OF-case-pC-v1/-v1B 为 FPE 崩溃产物**"
            "（出口截面退化：outlet 1 面 1.5045mm² → 15L/min÷1.5mm²"
            "≈166m/s 射流 → GAMG FPE，Run-A Time=16 / Run-B Time=23 "
            "步崩溃），证据链保留于共享树 `结果\\P0-result-pC-v1\\`"
            "（allrun.log / log.simpleFoam / nonManifoldPoints 俱全）"
            "**作证据不动**；本 **v2 为 T13b 出口层修复版**（多数表决"
            "塌缩豁免——诊断报告8 病灶根治，见看板5 §12）；③求解器 "
            "nu=1.8e-5 m²/s（见上节求解器设置，post_cfd --nu 1.8e-5 "
            "显式传入）"
        )
    elif PREFIX == "pC" and CASE == "v3":
        handover_note = (
            "- **患者C 专项注记（T14 架构实现批）**：①**v3 为 T14 "
            "架构修复版**——L1' 分割 26-conn 识别 + 规范序 HU<-300 "
            "补桥（咽部 7,355 体素 = 2.77cm3 真实解剖纳入，补桥 "
            "210 体素 HU 全落 [-400,-300) 零软组织侵入）；L2' "
            "6-conn 最小走廊守卫（+66 cells → 6-conn 单域，咽部 "
            "993/993 保留——t28 口径）；L3 出口通用化（出口层 = "
            "咽部稳定性准则 k=10，594 体素 / 223.4mm² / 97.9%max / "
            "双侧 |dA/A| 0.021/0.049——替换 v1 退化出口 1.5mm² 与 "
            "v2 塌缩豁免出口）；②**体积回归比 1.1728 越出标准闸带 "
            "（0.94–1.06）**——`--allow-anatomy-inclusion` 旗豁免至上"
            "带 1.30（理由：咽部 2.77cm3 系真实解剖纳入，DeepSeek "
            "round2 §5.3-1 实验在案，无实验可回避；闸门对其余漂移"
            "照常硬停）；③v1/v2 产物（FPE 崩溃 / T13b 塌缩豁免版）"
            "**作证据不动**于共享树；④求解器 nu=1.8e-5 m²/s（见上节"
            "求解器设置，**post_cfd 脚本 --nu 1.8e-5 显式传入**，勿用"
            "默认 1.48e-5）；⑤**checkMesh 待笔记本侧实跑确认**"
            "（体素六面体直出网格；v5 系同法全 PASS 先例；补桥后对角"
            "接触面 120+52，DeepSeek t27 判 checkMesh 容忍）；⑥朝向"
            "经融合自动判对（T13b 降级 QC：咽部并入后气道 z 范围下延"
            "到 k=0，两端窗口 cut 邻接均=0 → 鼻孔不在低端 → 出口自动"
            "落 z 低端咽部，无需硬编码）"
        )
    elif PREFIX == "pC" and CASE == "v4":
        _fc = (_t14_arch or {}).get("L1b_face_connect") or {}
        _g = (_t14_arch or {}).get("L2_minimal_corridor_guard") or {}
        _seg = (_t14_arch or {}).get("L1_segmentation_26conn") or {}
        _cb = _fc.get("configs_before", {})
        _cf = _fc.get("configs_fixed", {})
        _ca = _fc.get("configs_after", {})
        _rv4 = stats.get("volume_regression_ratio")
        handover_note = (
            "- **患者C 专项注记（T14b 补桥面连接修复批）**：①**v4 为 "
            "T14b 面连接修复版**——L1 补桥 "
            f"{_seg.get('bridge_voxels', '?')} 体素不变（HU 全落 "
            "[-400,-300) 零软组织侵入，T13b 红线）；**T14b 新增面连接"
            "修复**：补桥体素与主域/咽部的对角接触（对角相邻无共面 → "
            "压力-速度耦合断裂，v3 首步连续性失衡 350×(Run-A)/"
            "156,000×(Run-B) 根因）改为面连接通路——对角配置补插正交"
            f"体素（修复 edge {_cf.get('edge', '?')} + corner "
            f"{_cf.get('corner', '?')} 配置，插 "
            f"{_fc.get('voxels_inserted', '?')} 体素，HU 全 <-300；"
            f"HU 阻断 {_fc.get('unfixable_hu_blocked_configs', '?')} "
            "配置为固有薄壁，候选体素 HU≥-300 软组织/骨壁不可越红线，"
            "披露在案）；修复前对角配置 edge "
            f"{_cb.get('edge_only', '?')} + corner "
            f"{_cb.get('corner_only', '?')}（完备体素级口径；t12 滑动"
            "窗口口径 120+52，两口径定义见看板7）→ 修复后 edge "
            f"{_ca.get('edge_only', '?')} + corner "
            f"{_ca.get('corner_only', '?')}（t12 口径 15+35；剩余全为 "
            "HU 阻断固有配置，域已 6-conn 面连通单域，剩余对角邻接为"
            "冗余通路非唯一连接）；②**DS2 级守卫**：z 向 2.0mm 多数表"
            "决降采样**之后**断言融合域 6-conn 面连通单域（走廊回写 "
            f"+{_g.get('corridor_cells_added', '?')} cells → "
            f"{_g.get('n_components_6conn_after', '?')} 单域；"
            "n_bridge>0 且守卫后仍非单域即停工上报）；咽部 t28 口径 "
            "997/997 全保留（v3 为 993/993）；③**冒烟测试 SOP（§5.5）"
            "强制**：全量前先跑 10 步——首步连续性 global 应 "
            "O(流量)~O(10×流量) 且即衰减（pB 先例 27× 即衰减）方跑全程；"
            "若 O(100×流量) 且增长 → 立即中止回报，不跑全程；④"
            "**nonManifoldPoints 空间分布三分类**（v3 实测 1019 点：桥区 "
            "122 点 12.0% / 薄壁区 386 点 37.9% / 其他 511 点 50.1%——"
            "补桥非主因，固有解剖薄壁为主；v4 面连接修复后预期下降，待"
            "笔记本 checkMesh 实测确认）；⑤**体积比双口径**（§1 已分别"
            "标注）：交付网格口径 = "
            f"{_rv4}（算例级实测；checkMesh 实测 Total volume 与之同"
            "口径，v3 先例 42.63/40.07=1.064）；全分辨率口径 = v3 先例"
            " 1.1728（DeepSeek 口径，ds2 守卫输出未截断，47.0/40.07），"
            "v4 同口径复算待笔记本侧（守卫后 14,544 cells 在案，v3 为"
            " 14,468）；⑥"
            "**case_stats 随包**（T14b 起 case_stats + 掩码 npz 一并"
            "打入算例 zip，笔记本建议⑤，§10 缺口堵上）；⑦v1/v2/v3 "
            "崩溃证据（FPE / 塌缩豁免 / 对角接触阻断）**原样保留**于"
            "共享树 `结果\\P0-result-pC-v1\\` 等；⑧求解器 nu=1.8e-5 "
            "m²/s（见上节求解器设置，**post_cfd 脚本 --nu 1.8e-5 显式"
            "传入**，勿用默认 1.48e-5）；⑨checkMesh 待笔记本侧实跑确认"
            "（体素六面体直出网格；v5 系同法全 PASS 先例）"
        )
    elif PREFIX == "pC" and CASE == "E1":
        # T14d E1 实验（无降采样重生成）：z=1.0mm 不降采样
        _zfd = (stats.get("t14_arch") or {}).get(
            "T14d_ds2_z_factor") or {}
        handover_note = (
            "- **患者C 专项注记（T14d E1 实验·z=1.0mm 不降采样"
            "重生成）**：①**E1 为 z 向不降采样算例**——z 向体素 "
            f"{_zfd.get('voxel_z_mm', 1.0)}mm（zf=1：源序列层厚 "
            f"{_zfd.get('source_slice_thickness_mm', 1.0)}mm 即"
            "全分辨率 z 向，156 层全保留；对照组 z=2.0mm 多数表决"
            "仅 78 层），xy 恒 2×2 多数表决不变；网格单元数较 "
            "z=2.0 约翻倍；②并合模式 facegrow 沿用（6-conn 面连接"
            "生长并入咽部，生长天然面连通零插入体素）+ "
            "`--allow-anatomy-inclusion` 开启（体积回归比闸门上带 "
            "1.30）；③**E1 实验背景（诊断报告12）**：pC 族网格密度"
            "（conflicting points/单元数）6.72–7.26% vs 健康例 "
            "0.24–0.82%；pA-v2/v3 翻盘先例（同型网格密度 10.38% "
            "仅加松弛因子 p0.3/U0.7 即收敛 1500 步）——pC 不可解"
            "性在求解器维度未穷尽，E1（网格密度）与 E5（松弛因子）"
            "双实验裁决；④**冒烟测试 SOP（§5.5 新基准，诊断报告12 "
            "§六）强制**：全量前先跑 10 步——**判定线=第 2 步** "
            "global continuity **≤~120× 流量且有界**（健康例先例 "
            "84–118×，sum local <~1）= PASS 信号方跑全程；第 2 步"
            "**数百倍无界**（sum local >~5，pA-v1 先例 4,528×/9.37）"
            "= FAIL 立即中止回报不跑全程（旧判据'首步 O(10×) 且衰减'"
            "已废弃——双向失准在案）；⑤**出口层重定义按 L3**（主轴"
            "端面条件触发）：z=1.0 下鼻咽截断层不再被多数表决合并"
            "（zf=2 时 2 层合 1），出口层/面数/面积以 case_stats "
            "实测为准（见上节）；⑥求解器 nu=1.8e-5 m²/s（见上节"
            "求解器设置，**post_cfd 脚本 --nu 1.8e-5 显式传入**，"
            "勿用默认 1.48e-5）；⑦case_stats 随包（voxel_mm 记录 "
            "z=1.0mm，t14_arch.T14d_ds2_z_factor 记录 zf=1）；"
            "⑧v1/v2/v3/v4/X1/X2 产物**原样保留**于共享树作对照组"
        )
    elif PREFIX == "pC" and CASE in ("X1", "X2"):
        # T14c 诊断决定轮（对照实验）：X1=pC-base /
        # X2=pC-facegrow 专项注记 + 冒烟矩阵 SOP
        _mm = (stats.get("t14_arch") or {}).get(
            "L1c_merge_mode") or {}
        _to = stats.get("t13b_outlet_layer_fix") or {}
        _l3 = _to.get("l3_outlet_generalization") or {}
        _seg = ((stats.get("t14_arch") or {}).get(
            "L1_segmentation_26conn") or {})
        _va = (stats["voxel_mm"][0] / 2) ** 2   # 全分辨率体素截面积 mm²
        _out_vox = _to.get("outlet_section_voxels", 0)
        _out_mm2 = round(_out_vox * _va, 1)
        _merge_mode_block = ""
        if CASE == "X1":
            _ex = _mm.get("excluded_pharynx_voxels", "?")
            _exk = _mm.get("excluded_pharynx_k_range") or ["?", "?"]
            _mcells = _mm.get("main_component_6conn_cells", "?")
            _mkr = _mm.get("main_component_k_range") or ["?", "?"]
            handover_note = (
                "- **患者C 专项注记（T14c 诊断决定轮·对照变体 "
                "X1=pC-base）**：①**本算例为对照实验变体**"
                "（--merge-mode base）：**仅最大 6-conn 连通域**"
                f"（主域 {_mcells} 体素，k[{_mkr[0]},{_mkr[1]}]），"
                f"**咽部 {_ex} 体素（k[{_exk[0]},{_exk[1]}]）未并入、"
                "无补桥、零插入体素**——验证假设“咽部 26-conn 并合界面"
                "是首步失衡源”（诊断报告10：v4 冒烟双 FAIL 推翻对角接触"
                "假设；v1 无并合时 Time=1-7 连续性正常下降）；②"
                "**出口层**：咽部不在域内 → L3 出口通用化不触发，出口层="
                f"自域末端向内首个实质截面 k={_to.get('k_full_res_outlet', '?')}"
                f"（{_out_vox} 体素/{_out_mm2}mm²），渐细尾巴截断，"
                "T13b 出口层多数表决塌缩豁免按常启用（指挥官令“出口层豁免”）；"
                "③**冒烟矩阵 SOP（§5.5 强化版，本轮一锤定音）**：X1/X2 "
                "各 10 步探针，**四格判定**：X1✓X2✓=facegrow 修复成立→"
                "全量跑 X2；X1✓X2✗=咽部并入本质不可解（该数据下）→pC "
                "归档（有尊严的）；X1✗=pC 主体本身不可解→pC 归档；"
                "X1✗X2✓ 组合不存在；④**桥区/并合界面体素坐标随包**"
                "（bridge_zone_coords-pC-X1.npz，诊断报告10 建议④——"
                "nonManifoldPoints 三分类可复算）；⑤**体积回归比越带驱动="
                "ds2 多数表决固有膨胀**（细气道，T13b 回归比病灶诊断在案："
                "主域口径 1.181 先例）——**非咽部纳入**（本变体咽部未并入），"
                "--allow-anatomy-inclusion 旗仅放宽闸带上限至 1.30；⑥v1-v4 "
                "证据原样保留于共享树；⑦求解器 nu=1.8e-5 m²/s（见上节求解器"
                "设置，**post_cfd 脚本 --nu 1.8e-5 显式传入**，勿用默认 "
                "1.48e-5）"
            )
            _merge_mode_block = (
                "- **T14c 诊断决定轮（对照实验，指挥官令 2026-10-05）**："
                "本算例 = **变体 X1（pC-base，--merge-mode base）**：仅最大 "
                "6-conn 连通域——咽部不并入、无补桥、零插入体素。对照矩阵："
                "X1=pC-base / X2=pC-facegrow / X3=pC-v4（现状参考组，笔记本"
                "已有冒烟数据免重跑）。**本轮一锤定音**：v4 冒烟双 FAIL 推翻"
                "对角接触假设（诊断报告10 证据链完整），假设收窄至“咽部 "
                "26-conn 并合界面本身是首步失衡源”（并合允许对角/点接触进域）。"
                "**冒烟矩阵 SOP（§5.5 强化）**：本算例先跑 10 步探针（同 §5.5 "
                "判据：首步 global continuity O(流量)~O(10×流量) 且即衰减=PASS；"
                "O(100×流量) 且增长=FAIL 立即中止不跑全程），结果按四格矩阵判定："
                "**X1✓X2✓** = facegrow 修复成立 → 全量跑 X2；**X1✓X2✗** = 咽部"
                "并入本质不可解（该数据下）→ pC 归档（有尊严的）；**X1✗** = pC "
                "主体本身不可解 → pC 归档；X1✗X2✓ 组合不存在。\n"
            )
        else:  # X2
            _cor = _mm.get("corridor_voxels", "?")
            _chr = _mm.get("corridor_hu_range") or ["?", "?"]
            _nm = len(_mm.get("merged_components") or [])
            _ph = _mm.get("pharynx_voxels", "?")
            _phm = _mm.get("pharynx_merged")
            _gr = _mm.get("grown_voxels", "?")
            _mc = _mm.get("main_component_6conn_cells", "?")
            _mb = _mm.get("mopup_bridge_voxels", 0)
            _nur = len(_mm.get("unreachable_components") or [])
            handover_note = (
                "- **患者C 专项注记（T14c 诊断决定轮·对照变体 "
                "X2=pC-facegrow）**：①**本算例为对照实验变体**"
                "（--merge-mode facegrow）：咽部以 **6-conn 面连接生长**"
                "方式并入主域——BFS 从主域边界出发只走 6-conn 面-邻接步，"
                "生长介质=头内部 HU<-300 体素（空气+部分容积体素），可达组件"
                "沿 BFS 前驱树路径逐体素并入后整组件并入——**生长天然面连通，"
                f"零插入体素**（主域 {_mc} 体素 + 走廊 {_cor} 介质体素 "
                f"HU[{_chr[0]},{_chr[1]}] + 并入 {_nm} 组件含咽部 {_ph} 体素"
                f"{'（已并入）' if _phm else '（未并入）'} → {_gr} 体素，"
                "6-conn 单域）；不可达组件 "
                f"{_nur} 个；mop-up 补桥 {_mb} 体素；②**与 v4 的唯一差异="
                "并合机制**（v4=26-conn 识别吸收+规范序补桥 "
                f"{_seg.get('bridge_voxels', '?')} 体素+T14b 面连接修复；"
                "X2=生长并入零插入）——**出口层处理与 v4 完全一致**"
                f"（L3 咽部稳定性准则 k={_to.get('k_full_res_outlet', '?')}，"
                f"{_l3.get('selected_section_voxels', _out_vox)} 体素/"
                f"{_l3.get('selected_section_mm2', _out_mm2)}mm²），对照变量"
                "隔离；③**冒烟矩阵 SOP（§5.5 强化版）**：X1/X2 各 10 步探针，"
                "四格判定（X1✓X2✓→全量跑 X2；X1✓X2✗→pC 归档；X1✗→pC 归档；"
                "X1✗X2✓ 不存在）；④**桥区/生长走廊/并合界面体素坐标随包**"
                "（bridge_zone_coords-pC-X2.npz，诊断报告10 建议④）；⑤"
                "**体积回归比越带驱动=咽部 2.77cm³ 真实解剖纳入+ds2 多数表决"
                "固有膨胀**（--allow-anatomy-inclusion 旗豁免带上限 1.30，DeepSeek "
                "round2 §5.3-1 实验在案）；⑥v1-v4 证据原样保留于共享树；⑦求解器 "
                "nu=1.8e-5 m²/s（见上节求解器设置，**post_cfd 脚本 --nu 1.8e-5 "
                "显式传入**，勿用默认 1.48e-5）"
            )
            _merge_mode_block = (
                "- **T14c 诊断决定轮（对照实验，指挥官令 2026-10-05）**："
                "本算例 = **变体 X2（pC-facegrow，--merge-mode facegrow）**："
                "咽部以 6-conn 面连接生长方式并入主域（BFS 从主域边界出发只走 "
                "6-conn 面-邻接步，生长介质=头内部 HU<-300 体素；可达即并入、"
                "不可达即不并入——生长天然面连通，零插入体素）。对照矩阵：X1=pC-base"
                " / X2=pC-facegrow / X3=pC-v4（现状参考组，26-conn 吸收+规范序补桥"
                "+T14b 面连接修复，笔记本已有冒烟数据免重跑）。X2 与 v4 的唯一差异="
                "并合机制（出口层处理与 v4 完全一致，对照变量隔离）。**冒烟矩阵 SOP"
                "（§5.5 强化）**：同 X1（10 步探针 + 四格判定矩阵：X1✓X2✓→全量跑 "
                "X2；X1✓X2✗→pC 归档；X1✗→pC 归档；X1✗X2✓ 不存在）。\n"
            )
        merge_mode_block = _merge_mode_block
    else:
        handover_note = ""
    # ---- 鼻窦口径披露（T13b：pC 鼻窦经细窦口断离被过滤，
    #       与 pA/pB 鼻窦在域口径不一致——回归比病灶之一；
    #       T14：26-conn 架构下鼻窦未并入主域（距离判据）） ----
    _t13b_reg = stats.get("t13b_regression_diagnosis", {})
    _second_cells = int(_t13b_reg.get("second_cells", 0))
    _t14_arch = stats.get("t14_arch")
    if (_t14_arch is not None
            and _t14_arch.get("pharynx", {}).get("identified")):
        # T14/L1'：26-conn 识别未并入鼻窦（距离判据）
        sinus_scope = (
            "鼻窦经 26-conn 识别未并入主域（与主域距离 "
            ">=3.76mm > 对角接触半径 1.73mm，DeepSeek "
            "t4/t8 实测）→ 不在域（与 pA/pB 鼻窦在域口径"
            "不一致——pC 数据结构性特征，T14 披露在案）")
    elif _second_cells >= 500:
        sinus_scope = (
            "鼻窦气腔经细窦口在多数表决降采样后断离、被连通域"
            "过滤剔除（与 pA/pB 鼻窦在域口径不一致——体积回归"
            "比病灶之一，详见 case_stats t13b_regression_diagnosis）")
    else:
        sinus_scope = "鼻窦在域"
    repl = {
        "CASE_NAME": CASE_NAME, "CASE_NAME_B": CASE_NAME_B,
        "PREFIX": PREFIX, "LETTER": letter, "CASE": CASE,
        "CELLS": f"{cells:,}", "IFACES": f"{stats['internal_faces']:,}",
        "OUTLET": f"{stats['patch_face_counts']['outlet']:,}",
        "WALLS": f"{stats['patch_face_counts']['walls']:,}",
        "INLETL": str(stats['patch_face_counts']['inletL']),
        "INLETR": str(stats['patch_face_counts']['inletR']),
        "VOL": str(domain_vol_cm3),
        "QTOT": str(stats.get("Q_total_Lmin", 15.0)),
        "AL": str(al), "AR": str(ar), "QL": str(ql), "QR": str(qr),
        "MASKVOX": f"{mask_vox:,}", "MASKVOL": str(mask_vol_cm3),
        "NZ": str(survey["file_count"]),
        "VOLRATIO": str(stats.get("volume_regression_ratio")),
        "VOLRATIO_VERDICT": volreg_verdict,
        "VOXELMM": "×".join(str(v) for v in stats["voxel_mm"]),
        "RELEASE_GATES": gates_md,
        "ORIENT_SUMMARY": orient_summary,
        "ZDIR_DESC": zdir_desc,
        "PII_SUMMARY": pii_summary,
        "PROBE_DETAIL": "2026-10-02 实测",
        "DATE": time.strftime("%Y-%m-%d"),
        # ---- 分割 QC 披露（T13 新增） ----
        "SEQ_KIND": seq_kind,
        "QC_MASKVOX": f"{mask_vox:,}",
        "QC_VOL": str(mask_vol_cm3),
        "QC_ZSPAN": str(round(mask_zspan_mm, 1)),
        "QC_NAIR": str(m1["n_slices_with_air"]),
        "QC_NLAYER": str(survey["file_count"]),
        "QC_COMPONENTS": str(m1["n_components_merged"]),
        "QC_INLET_L": str(al),
        "QC_INLET_R": str(ar),
        "QC_MINAREA": str(m1["min_axial_area_mm2"]),
        "QC_MINLAYER": str(m1["min_layer"]),
        "QC_MINZ": str(m1["min_z_mm"]),
        "QC_WATERTIGHT": ("水密" if m1["stl_watertight"] else "非水密"),
        "QC_VOLRATIO": str(stats.get("volume_regression_ratio")),
        "QC_VOLREG_VERDICT": volreg_verdict,
        "QC_VOLREG_NOTE": volreg_note,
        "QC_FIDELITY_NOTE": fidelity_note,
        "SINUS_SCOPE": sinus_scope,
        "HANDOVER_NOTE": handover_note,
        "MERGE_MODE_BLOCK": merge_mode_block,
    }
    doc = render_handover(HANDOVER_DOC, repl)
    doc_path = os.path.join(OUT_ROOT, f"交接文档-笔记本执行-{PREFIX}-{CASE}.md")
    with open(doc_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(doc)
    zips = []
    # T14b：case_stats + 掩码随包（笔记本建议⑤——此前只在共享树
    #       step2/ 下、未进 zip；§10 指针文件现随 zip 一并交付）
    _stats_name = ("case_stats.json" if (PREFIX == "pA" and CASE == "v5")
                   else (f"case_stats-{CASE}.json" if PREFIX == "pA"
                         else f"case_stats-{PREFIX}-{CASE}.json"))
    _mask_name = ("mask_full.npz" if (PREFIX == "pA" and CASE == "v5")
                  else (f"mask_full-{CASE}.npz" if PREFIX == "pA"
                        else f"mask_full-{PREFIX}-{CASE}.npz"))
    _extra_root = [os.path.join(OUT_ROOT, "step2", _stats_name),
                   os.path.join(OUT_ROOT, "step2", _mask_name)]
    # T14c：桥区/并合界面体素坐标随包（诊断报告10 建议④）
    _bz = os.path.join(OUT_ROOT, "step2",
                       f"bridge_zone_coords-{PREFIX}-{CASE}.npz")
    if os.path.isfile(_bz):
        _extra_root.append(_bz)
    for cd in (os.path.join(OUT_ROOT, "step2", CASE_NAME),
               os.path.join(OUT_ROOT, "step2", CASE_NAME_B)):
        zp = os.path.join(OUT_ROOT, os.path.basename(cd) + ".zip")
        zip_case_dir(cd, zp, _extra_root)
        zips.append({"zip": os.path.relpath(zp, OUT_ROOT),
                     "bytes": os.path.getsize(zp), "md5": md5_of(zp)})
    manifest["stages"]["S5_solve"] = {
        "mode": "laptop",
        "handover_doc": os.path.relpath(doc_path, OUT_ROOT),
        "handover_doc_bytes": os.path.getsize(doc_path),
        "zips": zips,
        "probe": probe_openfoam(),
        "status": "case_packed_awaiting_laptop",
    }
    log(f"  交接文档 -> {os.path.basename(doc_path)}（{os.path.getsize(doc_path)} B）")
    for z in zips:
        log(f"  算例包 zip -> {z['zip']}（{z['bytes']:,} B）")

    # 后处理/step5 延期记录（严禁用患者A metrics 顶替）
    defer = {
        "status": "deferred_awaiting_laptop_results",
        "reason": "本机无 OpenFOAM（探测全 ABSENT）——CFD 求解与后处理由笔记本侧执行；"
                  "step5 依赖本例 VTU + 本例后处理 metrics.json 契约 + 占位体，"
                  "三者均待笔记本侧解算回传。严禁用患者A metrics 顶替（硬红线）。",
        "next_step": "笔记本回传 结果\\P0-result-" + PREFIX + "-" + CASE
                     + "\\（含 VTK/ 与 后处理\\metrics.json）后，重跑："
                     "python run_all.py --dicom-dir <同前> --case-prefix " + PREFIX
                     + " --case " + CASE + " --solve local --result-dir <结果目录>",
        "deferred_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(os.path.join(OUT_ROOT, f"postprocess_deferred-{PREFIX}-{CASE}.json"),
              "w", encoding="utf-8") as f:
        json.dump(defer, f, ensure_ascii=False, indent=1)
    with open(os.path.join(OUT_ROOT, f"step5_deferred-{PREFIX}-{CASE}.json"),
              "w", encoding="utf-8") as f:
        json.dump({**defer, "step5_mode_when_resumed": "full"}, f, ensure_ascii=False, indent=1)
    log("  后处理/step5 已标记「待解算后补导出」（严禁患者A metrics 顶替）")


# ---------------------------------------------------------------- 后处理 + step5
def run_postprocess_and_step5(manifest, result_dir, OUT_ROOT, PREFIX, CASE,
                              letter, CASE_NAME, DICOM_DIR, sx, ARGS):
    """S6 后处理（契约汇编+完备性）→ S7 step5 条件导出。"""
    log("[S6] 后处理：读本例 metrics.json ...")
    metrics_json = os.path.join(result_dir, "后处理", "metrics.json")
    if not os.path.isfile(metrics_json):
        manifest["stages"]["S6_postprocess"] = {
            "status": "deferred", "reason": f"结果目录存在但 后处理/metrics.json 缺失：{result_dir}"}
        log(f"  结果目录存在但 后处理/metrics.json 缺失——待笔记本侧后处理：{result_dir}")
        return
    result_metrics = json.load(open(metrics_json, encoding="utf-8"))
    contract, missing = assemble_contract(result_metrics, letter, CASE)
    contract_path = os.path.join(OUT_ROOT, "postprocess", f"contract-{PREFIX}-{CASE}.json")
    os.makedirs(os.path.dirname(contract_path), exist_ok=True)
    with open(contract_path, "w", encoding="utf-8") as f:
        json.dump(contract, f, ensure_ascii=False, indent=1)
    manifest["stages"]["S6_postprocess"] = {
        "source_metrics": os.path.abspath(metrics_json),
        "contract": os.path.relpath(contract_path, OUT_ROOT),
        "dP_baseline_Pa": contract["metrics"]["dP_baseline_Pa"],
        "split_L_pct": contract["metrics"]["split_L_pct"],
        "split_R_pct": contract["metrics"]["split_R_pct"],
        "resistance_total": contract["metrics"]["resistance_total"],
        "missing_fields": missing,
        "completeness": "COMPLETE" if not missing else "INCOMPLETE",
    }
    log(f"  契约汇编 -> {os.path.relpath(contract_path, OUT_ROOT)}；"
        f"ΔP={contract['metrics']['dP_baseline_Pa']} Pa，"
        f"分流 L/R={contract['metrics']['split_L_pct']}/{contract['metrics']['split_R_pct']}%，"
        f"R={contract['metrics']['resistance_total']}")
    if missing:
        log(f"  契约不完备（缺 {missing}——占位档需占位算例，单算例无法提供）"
            "——step5 按红线中止导出（不套用其他患者数字）")
        with open(os.path.join(OUT_ROOT, f"step5_deferred-{PREFIX}-{CASE}.json"),
                  "w", encoding="utf-8") as f:
            json.dump({
                "status": "deferred_contract_incomplete",
                "missing_fields": missing,
                "reason": "meta 契约字段缺失——占位档（dP_1/2/3mm、pressure-flow curve）"
                          "需占位算例（虚拟扩张+占位体仿真），本例尚无占位体设计；"
                          "字段补齐前严禁导出 step5（红线：字段缺失即中止导出并报错）",
                "next_step": "完成本例占位算例（step3/step4 同法）→ 重跑 run_all --result-dir <结果目录>",
            }, f, ensure_ascii=False, indent=1)
        manifest["stages"]["S7_step5"] = {"status": "deferred_contract_incomplete",
                                          "missing_fields": missing}
        return

    # ---- S7 step5 条件导出 ----
    log("[S7] step5 查看器数据导出（full 模式）...")
    vtu = find_vtu(result_dir)
    if vtu is None:
        die(2, f"契约完备但 VTU 缺失：{result_dir}/VTK/*/internal.vtu")
    cmd5 = [sys.executable, STEP5,
            "--dicom-dir", DICOM_DIR,
            "--case-prefix", PREFIX,
            "--case", CASE,
            "--vtu", vtu,
            "--metrics-json", contract_path,
            "--out-dir", os.path.join(OUT_ROOT, "step5"),
            "--write-mode", "full"]
    if ARGS.ph_dir:
        cmd5 += ["--ph-dir", ARGS.ph_dir]
    if ARGS.skin_data_js:
        cmd5 += ["--skin-data-js", ARGS.skin_data_js]
    log("  $ " + " ".join(cmd5))
    r = subprocess.run(cmd5)
    if r.returncode != 0:
        die(2, f"step5 失败（exit {r.returncode}）")
    manifest["stages"]["S7_step5"] = {
        "status": "exported", "vtu": vtu,
        "out_dir": os.path.relpath(os.path.join(OUT_ROOT, "step5"), OUT_ROOT),
    }
    log("  PASS：step5 导出完成（full 模式）")


# ---------------------------------------------------------------- S9 交付物回传
def _is_within(path, root):
    """path 是否位于 root 目录树内（用于保留相对目录结构）。"""
    try:
        return os.path.commonpath([os.path.abspath(path),
                                   os.path.abspath(root)]) == os.path.abspath(root)
    except ValueError:            # 跨盘符不可比
        return False


def _collect_deliverables(out_root, prefix, case, case_name, case_name_b):
    """收集本轮交付物 -> [(类别, 源路径)]，仅含实际存在的文件。

    类别：算例包 zip / case_stats / manifest&deferred JSON /
    viewer_single.html / 交接文档。只认本轮 prefix-case 命名，
    不扫无关病例的文件（共享树多病例共存安全）。
    """
    found, seen = [], set()

    def add(cat, path):
        if path and os.path.isfile(path):
            _ap = os.path.abspath(path)
            if _ap not in seen:
                seen.add(_ap)
                found.append((cat, path))

    # 1) 算例包 zip（本算例 A/B 两包）
    add("算例包 zip", os.path.join(out_root, case_name + ".zip"))
    add("算例包 zip", os.path.join(out_root, case_name_b + ".zip"))
    # 2) case_stats（step2/；pA-v5 回归基线沿用无前缀名）
    if prefix == "pA" and case == "v5":
        add("case_stats", os.path.join(out_root, "step2", "case_stats.json"))
    add("case_stats", os.path.join(out_root, "step2",
                                   f"case_stats-{case}.json" if prefix == "pA"
                                   else f"case_stats-{prefix}-{case}.json"))
    # 3) manifest / deferred / progress JSON
    add("manifest", os.path.join(out_root,
                                 f"run_all_manifest-{prefix}-{case}.json"))
    add("deferred", os.path.join(out_root,
                                 f"postprocess_deferred-{prefix}-{case}.json"))
    add("deferred", os.path.join(out_root,
                                 f"step5_deferred-{prefix}-{case}.json"))
    # 4) 交接文档
    add("交接文档", os.path.join(out_root,
                                 f"交接文档-笔记本执行-{prefix}-{case}.md"))
    # 5) viewer_single.html（本轮 out 树优先；回退既有按前缀单文件副本）
    for _dp, _dn, _fn in os.walk(out_root):
        if "viewer_single.html" in _fn:
            add("viewer_single.html", os.path.join(_dp, "viewer_single.html"))
    add("viewer_single.html",
        os.path.join(HERE, "webapp", "cases", prefix, "viewer_single.html"))
    return found


def publish_deliverables(out_root, prefix, case, case_name, case_name_b,
                         publish_dir):
    """T15A S9：把交付物复制到共享目录，逐件 Test-Path + md5，并写回执。

    冻结资产零接触：源文件只读；只写 --publish 目录。缺件如实登记，不臆造。
    """
    publish_dir = os.path.abspath(publish_dir)
    os.makedirs(publish_dir, exist_ok=True)
    log(f"[S9] 交付物回传共享目录：{publish_dir}")
    items = _collect_deliverables(out_root, prefix, case, case_name, case_name_b)
    receipt = {"published_at": time.strftime("%Y-%m-%d %H:%M:%S"),
               "out_root": out_root, "publish_dir": publish_dir,
               "files": [], "missing": [], "n_ok": 0, "n_total": len(items)}
    n_ok = 0
    for cat, src in items:
        rel = os.path.relpath(src, out_root) if _is_within(src, out_root) \
            else os.path.basename(src)
        dst = os.path.join(publish_dir, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        m_src = md5_of(src)
        existed = os.path.isfile(dst)
        m_old = md5_of(dst) if existed else ""
        if not (existed and m_old == m_src):
            shutil.copyfile(src, dst)
        m_dst = md5_of(dst)
        exists = os.path.isfile(dst)                 # Test-Path 等价判定
        ok = bool(exists and m_src == m_dst)
        n_ok += 1 if ok else 0
        _act = ("覆盖" if (existed and m_old != m_src)
                else ("已存在同内容" if existed else "新建"))
        log(f"    {'PASS' if ok else 'FAIL'} [{cat}] {rel.replace(os.sep, '/')}："
            f"Test-Path={exists}，md5={m_dst}（{_act}）")
        receipt["files"].append({
            "category": cat, "src": src, "dst": dst,
            "rel": rel.replace(os.sep, "/"), "bytes": os.path.getsize(dst),
            "md5": m_dst, "test_path": bool(exists),
            "md5_match": bool(m_src == m_dst), "action": _act,
        })
    got = {c for c, _ in items}
    for c in ("算例包 zip", "case_stats", "manifest", "deferred",
              "viewer_single.html", "交接文档"):
        if c not in got:
            receipt["missing"].append(c)
            log(f"    SKIP [{c}]：本轮 out 树无此交付物（如实登记，不臆造）")
    receipt["n_ok"] = n_ok
    receipt_path = os.path.join(out_root,
                                f"publish_receipt-{prefix}-{case}.json")
    with open(receipt_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, ensure_ascii=False, indent=1)
    r_dst = os.path.join(publish_dir, os.path.basename(receipt_path))
    shutil.copyfile(receipt_path, r_dst)
    log(f"    PASS [回执] {os.path.basename(receipt_path)}："
        f"Test-Path={os.path.isfile(r_dst)}，md5={md5_of(r_dst)}")
    log(f"[S9] 回传完成：{n_ok}/{len(items)} 件 Test-Path + md5 通过；"
        f"缺件={receipt['missing'] or '无'}")
    return receipt


if __name__ == "__main__":
    main()
