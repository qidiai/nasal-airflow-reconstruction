#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T15 Web 工作台后端（Flask）——多患者一键管线的浏览器外壳。

设计纪律：
- R-14 路径纪律：本文件不含任何硬编码绝对路径。内置病例 CT 目录经
  --base-dir（或环境变量 P0_CT_BASE）定位"参赛群资料"根；状态目录经
  --state-dir（默认 pipeline/out/webapp-state）；端口经 --port。
- 只包装既有管线（run_all.py / step1_airway_segment.py），不重写管线；
  PII 扫描/DICOM 头普查直接 import run_all 同款函数（scan_pii/survey_dicom）。
- 冻结资产零接触：pA viewer_single.html 等为只读复用副本（webapp/cases/pA/）。

部署形态（数据边界硬闸 · 修订1）：
- m1-local（默认；M1 笔记本=服务器）：ONLY_SYNTHETIC=false，真实患者数据
  可展示（pA/pB 演示展示在案；R-01 授权分级机制保留——对 presenter_only 病例生效）
- m2-cloud（M2/M3 云形态）：ONLY_SYNTHETIC=true，仅合成 demo；
  POST /api/case 代码级禁用（501，R-03）；非合成病例访问一律 403 + 中文提示

上传/建病例接口（两条路共用同一条链）：
- POST /api/case（source=builtin|path|demo）与 POST /api/upload
  （multipart/form-data，字段 files，多个 .dcm）都汇入 _register_case：
  注册表登记 → PII 闸门（run_all 同款 scan_pii）→ DICOM 头普查 → step1 气道分割。
- /api/upload 落盘 <state_dir>/uploads/<YYYYmmdd-HHMMSS>（文件名只取 basename）；
  云形态 503（R-03）；R-11：仅 .dcm / ≥2 个（否则 400）/ ≤2048 MiB（413 并清理
  已写文件）/ 扫描超时 900 s / 建病例失败保留上传目录不清理。

退出码契约（run_all）：
- 0 完成；2 断言停工（⛔ 门禁拦截卡）；3 环境缺失（OpenFOAM/WSL 不可用）

用法：
  python server.py                          # M1 本地服务器形态（端口 8080）
  python server.py --mode m2-cloud          # 云形态（仅合成数据）
  python server.py --presenter              # presenter 定向演示模式（解锁 presenter_only 病例详情，R-01 机制）
"""
import argparse
import glob
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import run_all as RA  # noqa: E402  # 复用同款闸门（scan_pii / survey_dicom / probe_openfoam）

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from flask import Flask, jsonify, request, send_file, abort  # noqa: E402

# ---------------------------------------------------------------- 路径（全部相对 HERE，R-14）
WEBAPP_DIR = os.path.join(HERE, "webapp")
STEP1 = os.path.join(HERE, "step1_airway_segment.py")
RUN_ALL = os.path.join(HERE, "run_all.py")
VIEWER_TEMPLATE = os.path.join(WEBAPP_DIR, "viewer_template", "viewer.html")
BUILD_SINGLE = os.path.join(WEBAPP_DIR, "tools", "build_single_file.py")

# 本例真实结果目录（只读导出源）：out/结果/P0-result-<case_id>-v1/后处理/
RESULTS_ROOT = os.path.join(HERE, "out", "结果")
# 只读结果导出白名单（ASCII 文件名 → MIME）；目录名按 case_id 硬编码（中文路径不进 URL）
RESULTS_WHITELIST = {
    "metrics.json": "application/json",
    "report.md": "text/markdown",
    "fig1_velocity_slice.png": "image/png",
    "fig2_pressure_slice.png": "image/png",
    "fig3_streamlines.png": "image/png",
    "fig4_wss_histogram.png": "image/png",
}


def case_results_dir(case_id):
    """真实结果目录 out/结果/P0-result-<case_id>-v1/后处理/（仅 pA/pB 有结果）。"""
    if case_id not in ("pA", "pB"):
        return ""
    return os.path.join(RESULTS_ROOT, f"P0-result-{case_id}-v1", "后处理")


def case_results_metrics_path(case_id):
    """本例真实 metrics.json 路径（不存在时返回空串）。"""
    d = case_results_dir(case_id)
    p = os.path.join(d, "metrics.json") if d else ""
    return p if os.path.isfile(p) else ""

# ---------------------------------------------------------------- 内置病例定义（相对 CT 根，R-14）
BUILTIN_DEFS = {
    "pA": {
        "label": "患者A · 基线（演示展示在案）",
        "prefix": "pA", "case": "v5",
        "dicom_rel": ["患者A", "脱敏后图像数据", "ISO_Soft_0.35mm_合并"],
        "badge": "✅", "badge_text": "封板",
        "preset_status": "done",
        "note": "授权在案（演示展示）；查看器=已导出单文件版（冻结资产只读复用）",
        "evidence": ["提交包-20261002/viewer_single.html（15,069,209 B 自包含）"],
    },
    "pB": {
        "label": "患者B · 对照（演示展示在案）",
        "prefix": "pB", "case": "v1",
        "dicom_rel": ["赛方CT", "ISO_Soft_0.468mm"],
        "badge": "✅", "badge_text": "演示展示在案",
        "preset_status": "done",
        "note": "赛方提供匿名 CT（PatientID 20260521-103609/Anonymous，逐头匿名化断言 PASS）；"
                "演示展示确认在案（R-01 授权事实更新：由'确认在办'改为'在案'）",
        "viewer_block_reason": "查看器导出受阻（T15 修订3 试跑实测，双闸门任一即足拦截）："
                               "①F3 六板门禁——airwayCavity 壳平滑后 L/R 比率漂移 0.111%＞0.1% 容差"
                               "（board4；airwayMesh 0.027% 通过），seg1 负 x 顶点 15→16（board6）；"
                               "②meta 契约缺 dP_1/2/3mm 占位档 6 字段（需本例占位算例 step3/step4/求解）。"
                               "严禁套用其他患者数字；记录 pipeline/out/step5-pB-v1/deploy-record-pB-viewer.md",
        "evidence": ["pipeline/out/step2/case_stats-pB-v1.json",
                     "pipeline/out/run_all_manifest-pB-v1.json",
                     "pipeline/out/step5_deferred-pB-v1.json"],
    },
    "pC": {
        "label": "患者C · 拦截修复实证",
        "prefix": "pC", "case": "v4",
        "dicom_rel": ["赛方CT", "ISO_1mm_0.613mm"],
        "badge": "⛔", "badge_text": "拦截修复",
        "preset_status": "awaiting_return",
        "anatomy_inclusion": True,
        "note": "四轮门禁修复实证（T13–T14b：桥面连接修复 553+20 体素）；"
                "CFD 已在笔记本侧解算（1500 步），查看器导出待结果回传（VTU 在笔记本侧）",
        "viewer_block_reason": "CFD 结果（VTK/internal.vtu）在笔记本侧 WSL 文件系统，"
                               "尚未回传共享树——查看器导出待回传后执行 step5",
        "evidence": ["解剖结构验证/case_stats-pC-v4.json",
                     "解剖结构验证/P0-OF-case-pC-v4.zip",
                     "交接文档-笔记本执行-pC-v4.md",
                     "看板7-T14b报告.md"],
    },
}

DEMO_DEF = {
    "case_id": "demo",
    "label": "合成 demo · 一键体验",
    "badge": "🧪", "badge_text": "合成示例",
    "preset_status": "done",
    "note": "100% 合成参数化管腔（开源仓库 gen_demo_data.py 产物）："
            "无 CT、无患者数据；demo 病例的气道（R-09 口径）",
}

# 常人对照带（文献量级对照；口径出处：升级施工-T10/_staging_自评终审版.md）
BAND_DP = {"lo": 30.0, "hi": 50.0, "unit": "Pa",
           "label": "文献常人压降带 30–50 Pa（量级对照，非同机制对照）"}
BAND_R = {"lo": 120.0, "hi": 600.0, "unit": "Pa/(L/s)",
          "label": "文献常人阻力带 120–600 Pa/(L/s)（量级对照）"}

DISCLOSURE = ("层流下界估计，不确定度±20-50%；概念验证 · 非医疗器械 · "
              "仿真几何禁止人体使用；温湿度交换未建模（质传递未实现）")


# ---------------------------------------------------------------- 配置
class ServerConfig:
    def __init__(self, mode="m1-local", base_dir=None, state_dir=None,
                 solve="skip", presenter=False, host="0.0.0.0", port=8080):
        self.mode = mode
        self.only_synthetic = (mode == "m2-cloud")
        self.presenter = bool(presenter) or os.environ.get("P0_PRESENTER") == "1"
        self.solve_default = solve if solve in ("skip", "laptop") else "skip"
        self.host = host
        self.port = int(port)
        self.ct_base = base_dir or os.environ.get("P0_CT_BASE") or ""
        self.state_dir = state_dir or os.path.join(HERE, "out", "webapp-state")
        os.makedirs(self.state_dir, exist_ok=True)
        self.cases_file = os.path.join(self.state_dir, "cases.json")
        self.results_dir = os.path.join(self.state_dir, "results")
        os.makedirs(self.results_dir, exist_ok=True)


REGISTRY_LOCK = threading.Lock()
RUNNING = {}  # case_id -> thread


# ---------------------------------------------------------------- 注册表
def load_registry(cfg):
    with REGISTRY_LOCK:
        if os.path.isfile(cfg.cases_file):
            try:
                with open(cfg.cases_file, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}


def save_registry(cfg, reg):
    with REGISTRY_LOCK:
        tmp = cfg.cases_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(reg, f, ensure_ascii=False, indent=1)
        os.replace(tmp, cfg.cases_file)


def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- 进度追加写（与 run_all 同格式 JSONL）
def append_progress(out_dir, msg):
    if not out_dir:
        return
    os.makedirs(out_dir, exist_ok=True)
    p = os.path.join(out_dir, "manifest-progress.json")
    try:
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(
                {"ts": round(time.time(), 3), "msg": msg},
                ensure_ascii=False) + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------- 病例记录解析
def builtin_dicom_dir(cfg, cid):
    d = BUILTIN_DEFS[cid]
    if not cfg.ct_base:
        return ""
    return os.path.join(cfg.ct_base, *d["dicom_rel"])


def get_case_record(cfg, case_id):
    """返回病例记录（上传病例读注册表；内置/合成组装预置记录）。"""
    reg = load_registry(cfg)
    rec = reg.get(case_id)
    if rec:
        return rec
    if case_id in BUILTIN_DEFS:
        d = BUILTIN_DEFS[case_id]
        return {
            "case_id": case_id, "kind": "builtin",
            "prefix": d["prefix"], "case_name": d["case"],
            "label": d["label"], "badge": d["badge"], "badge_text": d["badge_text"],
            "dicom_dir": builtin_dicom_dir(cfg, case_id),
            "out_dir": os.path.join(cfg.state_dir, "cases", case_id),
            "status": d["preset_status"], "synthetic": False,
            "presenter_only": bool(d.get("presenter_only")),
            "anatomy_inclusion": bool(d.get("anatomy_inclusion")),
            "note": d["note"], "preset": True,
            "created": "（预置内置病例）", "updated": now_iso(),
        }
    if case_id == "demo":
        return {
            "case_id": "demo", "kind": "synthetic",
            "prefix": None, "case_name": None,
            "label": DEMO_DEF["label"], "badge": DEMO_DEF["badge"],
            "badge_text": DEMO_DEF["badge_text"],
            "dicom_dir": "", "out_dir": "",
            "status": DEMO_DEF["preset_status"], "synthetic": True,
            "presenter_only": False, "anatomy_inclusion": False,
            "note": DEMO_DEF["note"], "preset": True,
            "created": "（预置合成示例）", "updated": now_iso(),
        }
    return None


def allocate_prefix(reg):
    """上传病例前缀分配：pX, pX2, pX3...（避开内置 pA/pB/pC）。"""
    used = set(reg.keys()) | {"pA", "pB", "pC", "demo"}
    if "pX" not in used:
        return "pX"
    n = 2
    while f"pX{n}" in used:
        n += 1
    return f"pX{n}"


# ---------------------------------------------------------------- 数据边界硬闸（修订1 / R-03）
def gate_case_access(cfg, rec):
    """返回 (ok, http_status, message)。"""
    if cfg.only_synthetic and not rec.get("synthetic"):
        return (False, 403,
                "数据边界硬闸（修订1）：本形态为云形态（M2/M3），仅合成 demo 数据可访问；"
                f"病例 {rec.get('case_id')} 含真实患者数据，仅限本地模式（M1 笔记本=服务器）")
    if rec.get("presenter_only") and not cfg.presenter:
        return (False, 403,
                "授权确认中（R-01）：该病例数据来源方演示展示确认在办；"
                "确认前详情仅 presenter 定向演示模式可见（服务器启动加 --presenter）")
    return (True, None, "")


# ---------------------------------------------------------------- viewer 数据 meta 提取
def _json_object_end(body):
    """字符串感知的 JSON 对象平衡扫描（返回对象结束的偏移+1；失败 None）。"""
    depth = 0
    in_str = False
    q = ""
    esc = False
    for k, ch in enumerate(body):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == q:
                in_str = False
            continue
        if ch in "\"'":
            in_str = True
            q = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return k + 1
    return None


def extract_viewer_meta(path):
    """从 viewer_data.js 或 viewer_single.html 提取 window.VIEWER_DATA.meta。
    遍历全部赋值语句：跳过 DEV-MOCK IIFE 赋值（'(' 开头），
    取第一个可解析且含 meta 的 JSON 对象赋值（viewer_single.html
    内嵌 DEV-MOCK 块在前、正式数据在后——审计 FND-1 布局）。"""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            txt = f.read()
    except OSError:
        return None
    for m in re.finditer(r"window\.VIEWER_DATA\s*=", txt):
        body = txt[m.end():].strip()
        if not body.startswith("{"):
            continue  # DEV-MOCK IIFE 等非 JSON 赋值
        end = _json_object_end(body)
        if end is None:
            continue
        try:
            data = json.loads(body[:end])
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and "meta" in data:
            return data.get("meta")
    return None


def parse_resistance(resist_str):
    """'66.2 Pa/(L/s)' -> 66.2；'合成示例' 文案容错。"""
    if not resist_str:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", str(resist_str))
    return float(m.group(0)) if m else None


# ---------------------------------------------------------------- 指标卡（双口径标签，R-10）
def _metrics_block(meta):
    """meta 契约的指标块：metrics 子对象（缺失时退回 meta 自身）。"""
    mm = meta.get("metrics") if isinstance(meta, dict) else None
    return mm if isinstance(mm, dict) else (meta or {})


def metrics_from_viewer_meta(case_id, meta, source_label):
    mm = _metrics_block(meta)
    dP = mm.get("dP_baseline_Pa")
    R = parse_resistance(mm.get("resistance_total"))
    is_synthetic_demo = case_id == "demo"
    return {
        "case_id": case_id,
        "source": source_label,
        "dP": {
            "value": dP, "unit": "Pa",
            "口径": "合成示例口径（参数化模型估计）" if is_synthetic_demo
            else "定流量口径（Run-A dP/Q，15 L/min 固定流量）",
            "band": BAND_DP,
        },
        "resistance": {
            "value": R, "unit": "Pa/(L/s)",
            "口径": "合成示例口径（参数化模型估计）" if is_synthetic_demo
            else "等压口径（Run-B 等压迭代自然分流）",
            "band": BAND_R,
        },
        "split": {
            "L": mm.get("split_L_pct"), "R": mm.get("split_R_pct"),
            "unit": "%", "basis": "15 L/min 层流（demo 为参数化 50/50）",
        },
        "wss": {
            "mean": mm.get("wss_mean_Pa"), "p95": mm.get("wss_p95_Pa"),
            "unit": "Pa",
        },
        "implant_scenarios": {
            "dP_1mm_Pa": mm.get("dP_1mm_Pa"),
            "dP_2mm_Pa": mm.get("dP_2mm_Pa"),
            "dP_3mm_Pa": mm.get("dP_3mm_Pa"),
            "note": mm.get("dP_note"),
        },
        "口径_note": "ΔP 与 R 口径不同（定流量 vs 等压），数值不可互换（R-10 双口径标签）；"
                     "常人对照带为文献量级对照，非同机制对照",
        "disclaimer": DISCLOSURE,
    }


def metrics_from_postcfd_json(case_id, metrics_path, source_label):
    """pB 路径：读后处理 metrics.json（Run-A 指定流量），R 按定流量口径复算。"""
    with open(metrics_path, encoding="utf-8") as f:
        m = json.load(f)
    totals = m.get("totals", {})
    dP = float(totals.get("dP_Pa", float("nan")))
    Q = float(totals.get("Q_inlet_total_L_min", float("nan")))
    R = dP / (Q / 60.0) if Q else None
    fl = totals.get("flow_share_L_pct")
    fr = totals.get("flow_share_R_pct")
    if fl is not None:
        fl = round(float(fl), 1)
    if fr is not None:
        fr = round(float(fr), 1)
    wss = m.get("wss", {})
    return {
        "case_id": case_id,
        "source": source_label,
        "dP": {"value": round(dP, 2), "unit": "Pa",
               "口径": "定流量口径（Run-A dP/Q，15 L/min 固定流量）",
               "band": BAND_DP},
        "resistance": {"value": round(R, 1) if R else None, "unit": "Pa/(L/s)",
                       "口径": "定流量口径（Run-A dP/Q，由本例 metrics.json 复算）；"
                               "等压口径需 Run-B 等压迭代（本例 Run-B 结果未回传）",
                       "band": BAND_R},
        "split": {"L": fl, "R": fr, "unit": "%", "basis": "Run-A 指定流量 15 L/min"},
        "wss": {"mean": wss.get("mean_Pa"), "p95": wss.get("p95_Pa"), "unit": "Pa"},
        "implant_scenarios": {
            "dP_1mm_Pa": None, "dP_2mm_Pa": None, "dP_3mm_Pa": None,
            "note": "占位档缺失（需本例占位算例）——这也是 step5 查看器导出被契约闸门"
                    "如实拦截的原因（严禁套用其他患者数字）",
        },
        "口径_note": "ΔP 与 R 同为定流量口径（本例）；等压口径需 Run-B 等压迭代，"
                     "两口径数值不可互换（R-10 双口径标签）",
        "disclaimer": DISCLOSURE,
    }


def metrics_from_case_stats(case_id, stats_path, source_label):
    """pC 路径：解剖指标在案（case_stats），CFD 指标待结果回传。"""
    with open(stats_path, encoding="utf-8") as f:
        s = json.load(f)
    return {
        "case_id": case_id,
        "source": source_label,
        "anatomy": {
            "cells": s.get("cells"),
            "internal_faces": s.get("internal_faces"),
            "inletL_area_mm2": s.get("inletL", {}).get("area_mm2"),
            "inletR_area_mm2": s.get("inletR", {}).get("area_mm2"),
            "outlet_area_mm2": s.get("outlet_area_mm2"),
            "volume_regression_ratio": s.get("volume_regression_ratio"),
        },
        "cfd_status": "待结果回传",
        "cfd_note": "CFD 已在笔记本侧解算（Run-A 1500 步 + Run-B 等压迭代），"
                    "VTK/postProcessing 结果在笔记本侧 WSL 文件系统——"
                    "回传后经 run_all --result-dir 进入后处理+step5，CFD 指标与查看器即就绪",
        "口径_note": "解剖指标无口径问题；CFD 指标回传后按双口径标签呈现（R-10）",
        "disclaimer": DISCLOSURE,
    }


# ---------------------------------------------------------------- QC 三平面（R-02：仅掩膜/掩膜叠加态）
def _mid_index(mask, axis):
    """该轴含气道体素的中间索引。"""
    any_along = mask.any(axis=tuple(a for a in (0, 1, 2) if a != axis))
    idx = np.where(any_along)[0]
    return int(np.median(idx)) if len(idx) else 0


def gen_plane_png(mask, plane, out_png, letter):
    """由降采样 mask 生成单平面掩膜 PNG（冠/矢；轴位 CT 叠加图用 step1 产物）。"""
    if plane == "coronal":
        col = _mid_index(mask, 2)
        img = mask[:, :, col]
        title = f"coronal @col {col} (mask only)"
    elif plane == "sagittal":
        row = _mid_index(mask, 1)
        img = mask[:, row, :]
        title = f"sagittal @row {row} (mask only)"
    else:
        raise ValueError(plane)
    fig, ax = plt.subplots(figsize=(4, 5))
    ax.imshow(img, cmap="Reds", interpolation="nearest")
    # 标题纯 ASCII（matplotlib 默认字体无 CJK 字形，中文会缺字报警）
    ax.set_title(f"Patient {letter} {title}")
    ax.axis("off")
    fig.savefig(out_png, dpi=110, bbox_inches="tight")
    plt.close(fig)


def resolve_step1_artifacts(cfg, rec):
    """定位 step1 产物目录：①本例 out_dir/preview ②本例 out_dir/step1 ③内置预置 pipeline/out/step1。"""
    cands = []
    out_dir = rec.get("out_dir") or ""
    if out_dir:
        cands.append(os.path.join(out_dir, "preview"))
        cands.append(os.path.join(out_dir, "step1"))
    if rec.get("kind") == "builtin":
        cands.append(os.path.join(HERE, "out", "step1"))
    for d in cands:
        if os.path.isdir(d):
            return d
    return cands[0] if cands else ""


def resolve_mask_npz(cfg, rec):
    """定位 mask_full npz：①本例 out_dir/step2 ②内置预置 pipeline/out/step2。"""
    prefix, case = rec.get("prefix"), rec.get("case_name")
    if not prefix:
        return ""
    if prefix == "pA" and case == "v5":
        mask_name = "mask_full.npz"
    else:
        mask_name = f"mask_full-{prefix}-{case}.npz"
    out_dir = rec.get("out_dir") or ""
    cands = []
    if out_dir:
        cands.append(os.path.join(out_dir, "step2", mask_name))
    if rec.get("kind") == "builtin":
        cands.append(os.path.join(HERE, "out", "step2", mask_name))
    for p in cands:
        if os.path.isfile(p):
            return p
    return ""


def qc_views_for_case(cfg, rec):
    """组装三平面 QC 视图列表（PNG 路径解析+按需生成）。"""
    case_id = rec["case_id"]
    prefix = rec.get("prefix") or ""
    letter = prefix[1].upper() if len(prefix) > 1 else "?"
    step1_dir = resolve_step1_artifacts(cfg, rec)
    mask_npz = resolve_mask_npz(cfg, rec)
    views = []

    def add(view, title, kind, path):
        if path and os.path.isfile(path):
            views.append({"view": view, "title": title, "kind": kind,
                          "url": f"/api/qc/{case_id}/png/{view}"})

    # 轴位：mask 叠加 CT（step1 T12 QC 图，R-02 允许的掩膜叠加态）
    qc_mid = os.path.join(step1_dir, "qc_fig", f"qc_{prefix}_mid.png")
    add("axial_ct_overlay", f"轴位 · 气道掩膜(红)叠加 CT（中层切片）", "ct_overlay", qc_mid)
    # 冠/矢：掩膜态（由 mask npz 生成，缓存于本例 out_dir/qc）
    if mask_npz and out_dir_ok(rec):
        qc_dir = os.path.join(rec["out_dir"], "qc")
        os.makedirs(qc_dir, exist_ok=True)
        for plane in ("coronal", "sagittal"):
            cache = os.path.join(qc_dir, f"{plane}_mask.png")
            if not os.path.isfile(cache):
                try:
                    mask = np.load(mask_npz)["mask"]
                    gen_plane_png(mask, plane, cache, letter)
                except Exception:
                    cache = ""
            add(plane + "_mask", f"{'冠状' if plane == 'coronal' else '矢状'}位 · 气道掩膜",
                "mask", cache)
    # 三平面总览（step1 mask_views）
    suf = "" if prefix == "pA" else f"_{prefix}"
    views_png = os.path.join(step1_dir, f"mask_views{suf}_v2.png")
    add("threes_panel", "三平面总览（轴/冠/矢，掩膜态）", "mask", views_png)
    return views


def out_dir_ok(rec):
    return bool(rec.get("out_dir"))


# ---------------------------------------------------------------- 后台链（run_all 包装）
def map_exit_code(rc):
    """run_all 退出码 → 病例状态（R-10 映射契约：
    0=done / 2=blocked(⛔ 门禁拦截卡) / 3=failed_env(环境缺失) / 其他=failed）。"""
    if rc == 0:
        return "done"
    if rc == 2:
        return "blocked"
    if rc == 3:
        return "failed_env"
    return "failed"


def extract_fatal_reason(out_dir):
    p = os.path.join(out_dir, "manifest-progress.json")
    reason = ""
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                if "!!! FATAL" in line:
                    try:
                        reason = json.loads(line).get("msg", "")
                    except json.JSONDecodeError:
                        reason = line.strip()
    except OSError:
        pass
    return reason


def stage_viewer_if_exported(cfg, rec):
    """run_all 链完成后：step5 导出就绪 → 舞台化 viewer（模板+数据+单文件构建）。"""
    out_dir = rec.get("out_dir") or ""
    vd = os.path.join(out_dir, "step5", "viewer_data.js")
    if not os.path.isfile(vd):
        return False
    case_web = os.path.join(WEBAPP_DIR, "cases", rec["case_id"])
    os.makedirs(case_web, exist_ok=True)
    shutil.copy2(vd, os.path.join(case_web, "viewer_data.js"))
    if os.path.isfile(VIEWER_TEMPLATE):
        shutil.copy2(VIEWER_TEMPLATE, os.path.join(case_web, "viewer.html"))
        if os.path.isfile(BUILD_SINGLE):
            try:
                subprocess.run(
                    [sys.executable, BUILD_SINGLE,
                     os.path.join(case_web, "viewer.html"),
                     os.path.join(case_web, "viewer_data.js"),
                     os.path.join(case_web, "viewer_single.html")],
                    capture_output=True, timeout=900)
            except Exception:
                pass
    return True


def run_chain_thread(cfg, case_id, solve, result_dir):
    rec = get_case_record(cfg, case_id)
    out_dir = rec.get("out_dir") or ""
    append_progress(out_dir, f"[W] server：后台链启动（run_all --solve {solve}）")
    cmd = [sys.executable, RUN_ALL,
           "--dicom-dir", rec.get("dicom_dir") or "",
           "--case-prefix", rec.get("prefix") or "",
           "--case", rec.get("case_name") or "v1",
           "--solve", solve,
           "--out-root", out_dir]
    if result_dir:
        cmd += ["--result-dir", result_dir]
    if rec.get("anatomy_inclusion"):
        cmd += ["--allow-anatomy-inclusion"]
    append_progress(out_dir, "[W] $ " + " ".join(cmd))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
        rc = proc.returncode
    except Exception as e:  # noqa: BLE001
        rc = -999
        append_progress(out_dir, f"[W] !!! 后台链异常：{e!r}")
    reg = load_registry(cfg)
    r = reg.get(case_id)
    if r is None:
        r = rec
    r["exit_code"] = rc
    r["updated"] = now_iso()
    mapped = map_exit_code(rc)
    if rc == 0 and solve == "laptop":
        # 交接模式：算例包+交接文档就绪，等笔记本侧 WSL 求解
        mapped = "handover"
        append_progress(out_dir,
                        "[W] 交接文档已生成（run_all --solve laptop）："
                        "算例包+交接文档就绪，待笔记本侧 WSL 求解（POST /api/solve 启动）")
    elif rc == 0:
        append_progress(out_dir, "[W] run_all 完成（exit 0）")
        if stage_viewer_if_exported(cfg, r):
            append_progress(out_dir, "[W] 查看器数据已舞台化（webapp/cases/"
                                       + case_id + "/viewer_single.html）")
    elif mapped == "blocked":
        r["gate"] = "run_all 断言闸门"
        r["gate_failures"] = [extract_fatal_reason(out_dir) or "断言停工（exit 2），详见进度日志"]
        append_progress(out_dir, f"[W] ⛔ 门禁拦截（exit 2）：{r['gate_failures'][0]}")
    elif mapped == "failed_env":
        r["gate_failures"] = ["本机 OpenFOAM/WSL 环境探测 ABSENT（exit 3）："
                              "local 模式不可用；可改 --solve laptop 生成交接文档"]
        append_progress(out_dir, "[W] 环境缺失（exit 3）：" + r["gate_failures"][0])
    else:
        r["gate_failures"] = [f"后台链失败（exit {rc}），详见进度日志"]
        append_progress(out_dir, r["gate_failures"][0])
    r["status"] = mapped
    reg[case_id] = r
    save_registry(cfg, reg)
    RUNNING.pop(case_id, None)


def to_wsl_path(win_path):
    win_path = os.path.abspath(win_path)
    drive = win_path[0].lower()
    rest = win_path[2:].replace("\\", "/")
    return f"/mnt/{drive}/{rest}"


def parse_last_time(log_path):
    """解析 log.simpleFoam 最后一个 'Time = N'（求解步数心跳）。"""
    try:
        size = os.path.getsize(log_path)
        with open(log_path, "rb") as f:
            f.seek(max(0, size - 262144))
            tail = f.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    steps = re.findall(r"Time\s*=\s*([\d.eE+-]+)", tail)
    return float(steps[-1]) if steps else None


def solve_thread(cfg, case_id):
    rec = get_case_record(cfg, case_id)
    out_dir = rec.get("out_dir") or ""
    case_dir = os.path.join(out_dir, "step2",
                            f"P0-OF-case-{rec.get('prefix')}-{rec.get('case_name')}")
    append_progress(out_dir, "[W] WSL Allrun 启动：" + to_wsl_path(case_dir))
    log_path = os.path.join(case_dir, "log.simpleFoam")
    cmd = f"cd {shlex.quote(to_wsl_path(case_dir))} && ./Allrun"
    try:
        proc = subprocess.Popen(["wsl", "bash", "-lc", cmd],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
    except Exception as e:  # noqa: BLE001
        append_progress(out_dir, f"[W] !!! WSL 启动异常：{e!r}")
        _mark_solve_status(cfg, case_id, "failed", [f"WSL 启动异常：{e!r}"])
        return
    last_step = -1.0
    stall = 0
    STALL_LIMIT = 1200  # 20 分钟无步数增长 → 看护终止（审计③⑤）
    while proc.poll() is None:
        time.sleep(30)
        step = parse_last_time(log_path)
        if step is not None and step > last_step:
            last_step = step
            stall = 0
            append_progress(out_dir, f"[W] 求解进行：Time = {step:g}")
        else:
            stall += 30
            if stall >= STALL_LIMIT:
                proc.kill()
                proc.wait()
                archive = os.path.join(out_dir, "allrun_stalled_archive.log")
                if os.path.isfile(log_path):
                    shutil.copy2(log_path, archive)
                append_progress(out_dir,
                              f"[W] !!! 求解看护触发：{STALL_LIMIT}s 无步数增长"
                              "——已终止并归档日志（allrun_stalled_archive.log）")
                _mark_solve_status(
                    cfg, case_id, "failed_solve_stalled",
                    [f"求解停滞：{STALL_LIMIT}s 无步数增长（WSL Allrun 崩溃或死锁），"
                     "已终止并归档日志"])
                return
    rc = proc.poll()
    if rc == 0:
        append_progress(out_dir, "[W] Allrun 完成（exit 0）——进入后处理+step5")
        result_dir = case_dir
        reg = load_registry(cfg)
        r = reg.get(case_id) or rec
        r["status"] = "running"
        r["updated"] = now_iso()
        reg[case_id] = r
        save_registry(cfg, reg)
        run_chain_thread(cfg, case_id, "local", result_dir)
    else:
        append_progress(out_dir, f"[W] Allrun 失败（exit {rc}）")
        _mark_solve_status(cfg, case_id, "failed",
                           [f"WSL Allrun 失败（exit {rc}）；日志：{log_path}"])


def _mark_solve_status(cfg, case_id, status, failures):
    reg = load_registry(cfg)
    r = reg.get(case_id)
    if r:
        r["status"] = status
        r["gate_failures"] = failures
        r["updated"] = now_iso()
        reg[case_id] = r
        save_registry(cfg, reg)
    RUNNING.pop(case_id, None)


# ---------------------------------------------------------------- 建病例（目录导入 / 网页上传 共用链）
MAX_UPLOAD_MIB = 2048  # R-11 上传契约：单份 CT 体积上限 2 GiB（2048 MiB）


def _safe_upload_name(filename):
    """上传文件名安全化：只取 basename（绝对路径/子路径穿越一律降级为纯文件名）。"""
    return os.path.basename(str(filename or "").replace("\\", "/").strip())


def _register_case(cfg, dicom_dir, prefix, case_name, label, kind, case_id_val,
                   anatomy_inclusion=False):
    """建病例公共链（POST /api/case 与 POST /api/upload 共用）：
    注册表登记 → PII 闸门（run_all 同款 scan_pii）→ DICOM 头普查 → step1 气道分割。
    返回 (flask_response, status_code)；与既有 POST /api/case 行为一致（逐条同码）。
    """
    reg = load_registry(cfg)
    out_dir = os.path.join(cfg.state_dir, "cases", case_id_val)
    rec = {
        "case_id": case_id_val,
        "kind": kind, "prefix": prefix, "case_name": case_name,
        "label": label, "dicom_dir": dicom_dir, "out_dir": out_dir,
        "status": "registered", "synthetic": False,
        "presenter_only": False,
        "anatomy_inclusion": bool(anatomy_inclusion),
        "created": now_iso(), "updated": now_iso(),
    }
    os.makedirs(out_dir, exist_ok=True)
    append_progress(out_dir, f"[W] server：病例登记 {label}")

    # ---- PII 闸门（run_all 同款 scan_pii） ----
    try:
        pii = RA.scan_pii(dicom_dir)
    except SystemExit as e:
        pii = {"pass": False, "fail_count": 1, "files": 0,
               "fails": [["-", "PII", str(e), "scan_pii 停工（目录无可扫描头）"]]}
    except Exception as e:  # noqa: BLE001
        pii = {"pass": False, "fail_count": 1, "files": 0,
               "fails": [["-", "PII", repr(e), "PII 扫描异常"]]}
    rec["pii"] = pii
    append_progress(out_dir,
                    f"[W] PII 头扫描：{'PASS' if pii['pass'] else 'FAIL'}"
                    f" ×{pii.get('fail_count', 0)}（{pii.get('files', 0)} 头）")
    if not pii["pass"]:
        rec.update(status="blocked", gate="PII 头扫描（run_all 同款闸门）",
                   gate_failures=[list(map(str, f)) for f in pii.get("fails", [])][:10],
                   exit_code=2)
        reg[rec["case_id"]] = rec
        save_registry(cfg, reg)
        append_progress(out_dir, "[W] ⛔ 门禁拦截：PII 头扫描 FAIL——停工上报")
        return jsonify({"case_id": rec["case_id"], "status": "blocked",
                        "gate": rec["gate"],
                        "gate_failures": rec["gate_failures"],
                        "message": "数据未通过质量闸门（PII 头扫描）——已生成 ⛔ 拦截卡"})

    # ---- DICOM 头普查（同款 survey_dicom：层序方向断言） ----
    try:
        survey = RA.survey_dicom(dicom_dir)
        rec["survey"] = {k: survey.get(k) for k in
                         ("file_count", "rows", "columns", "pixel_spacing",
                          "slice_gap_measured", "z_monotonic_increasing",
                          "filename_order_matches_physical")}
    except SystemExit as e:
        survey = None
        rec["survey_error"] = str(e)
    except Exception as e:  # noqa: BLE001
        survey = None
        rec["survey_error"] = repr(e)
    if rec.get("survey_error") or (survey and not survey["filename_order_matches_physical"]):
        reason = rec.get("survey_error") or "层序方向断言 FAIL：z 序列非单调——层序混乱"
        rec.update(status="blocked", gate="DICOM 头普查（层序方向断言）",
                   gate_failures=[reason], exit_code=2)
        reg[rec["case_id"]] = rec
        save_registry(cfg, reg)
        append_progress(out_dir, f"[W] ⛔ 门禁拦截：{reason}")
        return jsonify({"case_id": rec["case_id"], "status": "blocked",
                        "gate": rec["gate"],
                        "gate_failures": rec["gate_failures"],
                        "message": "数据未通过质量闸门（DICOM 头普查）——已生成 ⛔ 拦截卡"})

    # ---- step1 气道分割（子进程，隔离 out-dir） ----
    preview_dir = os.path.join(out_dir, "preview")
    sx = (survey or {}).get("pixel_spacing") or [None, None]
    patient_label = f"{prefix[1].upper() if len(prefix) > 1 else 'X'} " \
                    f"(soft tissue window, ISO {round(sx[0], 3) if sx[0] else '?'}mm)"
    cmd1 = [sys.executable, STEP1,
            "--dicom-dir", dicom_dir,
            "--out-dir", preview_dir,
            "--case-prefix", prefix,
            "--patient-label", patient_label]
    append_progress(out_dir, "[W] $ " + " ".join(cmd1))
    try:
        proc = subprocess.run(cmd1, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=900)
        rc1 = proc.returncode
        tail = (proc.stdout or "")[-2000:]
    except subprocess.TimeoutExpired:
        rc1 = -1
        tail = "step1 超时（>900 s，R-11 上传契约）"
    if rc1 != 0:
        rec.update(status="blocked", gate="step1 气道分割",
                   gate_failures=[tail.strip()[-1500:]], exit_code=rc1)
        reg[rec["case_id"]] = rec
        save_registry(cfg, reg)
        append_progress(out_dir, f"[W] ⛔ 门禁拦截：step1 失败（exit {rc1}）")
        return jsonify({"case_id": rec["case_id"], "status": "blocked",
                        "gate": rec["gate"],
                        "gate_failures": rec["gate_failures"],
                        "message": "数据未通过质量闸门（step1 分割）——已生成 ⛔ 拦截卡"})
    rec.update(status="segmented",
               qc_note="step1 完成：三平面 QC 已在 /api/qc/" + rec["case_id"])
    reg[rec["case_id"]] = rec
    save_registry(cfg, reg)
    append_progress(out_dir, "[W] step1 完成（气道分割+QC 产物就绪）")
    return jsonify({"case_id": rec["case_id"], "status": "segmented",
                    "kind": kind, "prefix": prefix,
                    "label": label,
                    "pii": {"files": pii.get("files", 0), "pass": True},
                    "survey": rec.get("survey"),
                    "message": "PII 扫描 PASS + step1 完成；可 POST /api/run 启动全链"})


def _register_path_case(cfg, dicom_dir, source_label="服务器目录导入"):
    """按 CT 目录建病例：R-11 契约校验（≥2 个 .dcm / ≤2048 MiB）→ 分配前缀 → _register_case。
    供 POST /api/case（source=path）与 POST /api/upload（网页直接上传）共用。
    """
    dcm_files = glob.glob(os.path.join(dicom_dir, "*.dcm"))
    dcm_count = len(dcm_files)
    if dcm_count < 2:
        return jsonify({"error":
                        f"CT 目录内 .dcm 文件不足 2 个（实测 {dcm_count} 个）："
                        "请选择包含完整 DICOM 序列的目录"}), 400
    # R-11 上传契约：大小上限 2 GiB / 超时 900 s / 失败保留证据不清理
    total_mb = sum(os.path.getsize(p) for p in dcm_files) / 1048576.0
    if total_mb > MAX_UPLOAD_MIB:
        return jsonify({"error":
                        f"CT 目录体积 {total_mb:.0f} MiB 超上限 {MAX_UPLOAD_MIB} MiB"
                        "（R-11 上传契约）"}), 413
    reg = load_registry(cfg)
    prefix = allocate_prefix(reg)
    return _register_case(cfg, dicom_dir, prefix, "v1",
                          f"上传病例 {prefix}（{source_label}）", "upload", prefix)


# ---------------------------------------------------------------- Flask app
def build_app(cfg):
    app = Flask(__name__, static_folder=WEBAPP_DIR, static_url_path="/static")
    app.config["SERVER_CONFIG"] = cfg

    @app.route("/")
    def index():
        return send_file(os.path.join(WEBAPP_DIR, "index.html"))

    @app.route("/api/results/<case_id>/<fn>")
    def api_results(case_id, fn):
        """只读导出本例真实分析结果（out/结果/.../后处理/ 白名单文件）。
        目录名按 case_id 硬编码（中文路径不进 URL），仅白名单 ASCII 文件名。"""
        if cfg.only_synthetic:
            return jsonify({"error":
                            "数据边界硬闸（修订1/R-03）：云形态仅合成数据，"
                            "真实患者分析结果不开放（HTTP 403）"}), 403
        d = case_results_dir(case_id)
        if not d or fn not in RESULTS_WHITELIST:
            abort(404)
        p = os.path.join(d, fn)
        if not os.path.isfile(p):
            abort(404)
        resp = send_file(p, mimetype=RESULTS_WHITELIST[fn], as_attachment=False,
                         download_name=fn)
        if fn.endswith(".md"):
            resp.headers["Content-Type"] = "text/markdown; charset=utf-8"
        return resp

    @app.route("/api/health")
    def api_health():
        return jsonify({
            "status": "ok", "mode": cfg.mode,
            "only_synthetic": cfg.only_synthetic,
            "presenter": cfg.presenter,
            "ct_base_configured": bool(cfg.ct_base),
            "server": "T15 Web 工作台（Flask 包装既有管线）",
        })

    @app.route("/api/cases")
    def api_cases():
        reg = load_registry(cfg)
        cards = []
        for cid in ("pA", "pB", "pC"):
            rec = get_case_record(cfg, cid)
            d = BUILTIN_DEFS[cid]
            dicom_ok = bool(rec["dicom_dir"]) and os.path.isdir(rec["dicom_dir"])
            # 指标摘要（只读复用已导出产物）
            summary = _builtin_metrics_summary(cfg, cid)
            cards.append({
                "case_id": cid, "label": rec["label"], "kind": "builtin",
                "synthetic": False,
                "badge": d["badge"], "badge_text": d["badge_text"],
                "status": rec["status"],
                "dicom_configured": dicom_ok,
                "presenter_only": bool(rec.get("presenter_only")) and not cfg.presenter,
                "viewer_available": _viewer_available(cfg, rec),
                "viewer_block_reason": _viewer_block_reason(cfg, rec),
                "metrics_summary": summary,
                "qc_available": bool(qc_views_for_case(cfg, rec)),
                "note": rec.get("note") or d["note"],
                "evidence": d.get("evidence", []),
                "anatomy_inclusion": bool(rec.get("anatomy_inclusion")),
            })
        # 合成 demo
        rec = get_case_record(cfg, "demo")
        cards.append({
            "case_id": "demo", "label": rec["label"], "kind": "synthetic",
            "synthetic": True, "badge": rec["badge"], "badge_text": rec["badge_text"],
            "status": rec["status"], "dicom_configured": True,
            "presenter_only": False,
            "viewer_available": True, "viewer_block_reason": "",
            "metrics_summary": _builtin_metrics_summary(cfg, "demo"),
            "qc_available": False,
            "note": rec["note"], "evidence": [
                "开源仓库 code/viewer/viewer_data.js（gen_demo_data.py 产物）"],
            "anatomy_inclusion": False,
        })
        # 上传病例（pX 系）
        for cid, r in sorted(reg.items()):
            if r.get("kind") != "upload":
                continue
            cards.append({
                "case_id": cid, "label": r.get("label") or f"上传病例 {cid}",
                "kind": "upload", "synthetic": False,
                "badge": {"blocked": "⛔", "failed_env": "⚠️",
                          "failed": "❌", "done": "✅", "handover": "📦",
                          "running": "🔄", "segmented": "🔬",
                          "registered": "📝"}.get(r.get("status"), "❓"),
                "badge_text": r.get("status"),
                "status": r.get("status"),
                "dicom_configured": bool(r.get("dicom_dir")),
                "presenter_only": False,
                "viewer_available": _viewer_available(cfg, r),
                "viewer_block_reason": _viewer_block_reason(cfg, r),
                "metrics_summary": _upload_metrics_summary(cfg, r),
                "qc_available": bool(qc_views_for_case(cfg, r)),
                "note": r.get("note") or "",
                "evidence": [],
                "anatomy_inclusion": bool(r.get("anatomy_inclusion")),
                "exit_code": r.get("exit_code"),
                "gate": r.get("gate"),
                "gate_failures": r.get("gate_failures") or [],
            })
        return jsonify({"mode": cfg.mode, "only_synthetic": cfg.only_synthetic,
                        "presenter": cfg.presenter, "cases": cards})

    @app.route("/api/case", methods=["POST"])
    def api_case():
        # R-03：云形态代码级禁用（不是 UI 隐藏）
        if cfg.only_synthetic:
            return jsonify({
                "error": "云形态数据边界（修订1/R-03）：本形态（M2/M3）仅合成 demo 数据，"
                         "上传/选择真实 CT 已在代码级禁用（HTTP 501）"}), 501
        form = request.form
        source = form.get("source", "")
        if source == "demo":
            rec = get_case_record(cfg, "demo")
            return jsonify({"case_id": "demo", "status": "done",
                            "kind": "synthetic",
                            "note": "合成 demo 一键体验：无需 CT，直接查看结果"})
        if source == "builtin":
            cid = form.get("case_id", "")
            d = BUILTIN_DEFS.get(cid)
            if not d:
                return jsonify({"error": f"未知内置病例：{cid}"}), 400
            rec = get_case_record(cfg, cid)
            ok, code, msg = gate_case_access(cfg, rec)
            if not ok:
                return jsonify({"error": msg}), code
            dicom_dir = rec["dicom_dir"]
            if not dicom_dir or not os.path.isdir(dicom_dir):
                return jsonify({"error":
                                "内置病例 CT 目录未配置：服务器启动需加 --base-dir "
                                "指向 参赛群资料 根目录（当前未检测到 "
                                + (cid) + " 序列）"}), 400
            return _register_case(cfg, dicom_dir, d["prefix"], d["case"],
                                  d["label"], "builtin", cid,
                                  anatomy_inclusion=bool(d.get("anatomy_inclusion")))
        elif source == "path":
            dicom_dir = form.get("dicom_path", "").strip().strip('"')
            if not dicom_dir or not os.path.isdir(dicom_dir):
                return jsonify({"error": f"CT 目录不存在或不是目录：{dicom_dir}"}), 400
            return _register_path_case(cfg, dicom_dir, source_label="服务器目录导入")
        else:
            return jsonify({"error": "source 须为 builtin|path|demo"}), 400

    @app.route("/api/upload", methods=["POST"])
    def api_upload():
        """网页直接上传 CT（multipart/form-data，字段名 files，可多文件）→ 自动建病例。
        R-03：云形态代码级禁用（503，非 UI 隐藏）；R-11：仅 .dcm / ≤2048 MiB /
        900 s / 失败保留证据。落盘到 <state_dir>/uploads/<YYYYmmdd-HHMMSS>，
        随后复用 source=path 建病例链（_register_path_case）。"""
        if cfg.only_synthetic:
            return jsonify({
                "error": "云形态数据边界（修订1/R-03）：本形态（M2/M3）仅合成 demo 数据，"
                         "网页上传真实 CT 已在代码级禁用（HTTP 503）"}), 503
        files = [f for f in request.files.getlist("files") if f and f.filename]
        if not files:
            return jsonify({"error":
                            "未收到文件：请以 multipart/form-data 上传字段 files"
                            "（一个或多个 .dcm 文件）"}), 400
        # 扩展名硬闸：只收 .dcm（不区分大小写），其余一律 400
        for f in files:
            if not f.filename.lower().endswith(".dcm"):
                return jsonify({"error":
                                "仅接受 .dcm 文件（收到："
                                + os.path.basename(f.filename.replace("\\", "/"))
                                + "）；请重新选择 CT 序列目录（非 .dcm 文件请先剔除）"}), 400
        stamp = time.strftime("%Y%m%d-%H%M%S")
        up_dir = os.path.join(cfg.state_dir, "uploads", stamp)
        n = 1
        while os.path.exists(up_dir):  # 同一秒内重复上传时的防撞
            up_dir = os.path.join(cfg.state_dir, "uploads", f"{stamp}-{n}")
            n += 1
        os.makedirs(up_dir, exist_ok=True)
        max_bytes = MAX_UPLOAD_MIB * 1048576
        total = 0
        saved = 0
        for f in files:
            name = _safe_upload_name(f.filename) or "unnamed.dcm"
            dest = os.path.join(up_dir, name)
            base, ext = os.path.splitext(name)
            k = 2
            while os.path.exists(dest):  # 重名去撞（仅取 basename 后可能重名）
                dest = os.path.join(up_dir, f"{base}_{k}{ext}")
                k += 1
            try:
                f.save(dest)
            except OSError as e:  # noqa: BLE001
                shutil.rmtree(up_dir, ignore_errors=True)
                return jsonify({"error": f"上传写盘失败：{e!r}（本次已写文件已清理）"}), 500
            saved += 1
            total += os.path.getsize(dest)
            if total > max_bytes:  # R-11：超限 413 并清理已写文件
                shutil.rmtree(up_dir, ignore_errors=True)
                return jsonify({"error":
                                f"上传体积超上限 {MAX_UPLOAD_MIB} MiB（R-11 上传契约）："
                                "已清理本次已写文件——请缩减 CT 序列后重传"}), 413
        if saved < 2:
            # R-11 失败保留证据：落盘目录保留在 uploads/ 供排查，不清理
            return jsonify({"error":
                            f".dcm 文件不足 2 个（实测 {saved} 个；已保留于 "
                            + os.path.relpath(up_dir, HERE).replace("\\", "/")
                            + "）：请选择包含完整 DICOM 序列的文件夹"}), 400
        # 复用 source=path 建病例链（PII 闸门 → DICOM 头普查 → step1）
        return _register_path_case(cfg, up_dir, source_label="网页上传")

    @app.route("/api/qc/<case_id>")
    def api_qc(case_id):
        rec = get_case_record(cfg, case_id)
        if rec is None:
            abort(404)
        ok, code, msg = gate_case_access(cfg, rec)
        if not ok:
            return jsonify({"error": msg}), code
        if rec.get("synthetic"):
            return jsonify({
                "case_id": case_id, "views": [],
                "r02_note": "合成 demo 为参数化管腔，无 CT 序列——三平面 QC 不适用"
                            "（生成器内几何自检已在案）；CT 原图切片本形态不开放（R-02）"}), 200
        views = qc_views_for_case(cfg, rec)
        return jsonify({
            "case_id": case_id, "views": views,
            "r02_note": "QC 三平面仅掩膜/掩膜叠加态（R-02）：纯 CT 影像切片未开放"
                        "（待查理确认观众自助浏览范围）；皮肤层默认关（viewer 默认关，T11 补丁②）",
            "ct_overlay_available": any(v["kind"] == "ct_overlay" for v in views),
        })

    @app.route("/api/qc/<case_id>/png/<view_name>")
    def api_qc_png(case_id, view_name):
        rec = get_case_record(cfg, case_id)
        if rec is None:
            abort(404)
        ok, code, msg = gate_case_access(cfg, rec)
        if not ok:
            return jsonify({"error": msg}), code
        # 防路径穿越：仅允许已登记视图名
        allowed = {v["view"] for v in qc_views_for_case(cfg, rec)}
        if view_name not in allowed:
            abort(404)
        step1_dir = resolve_step1_artifacts(cfg, rec)
        prefix = rec.get("prefix") or ""
        path = ""
        if view_name == "axial_ct_overlay":
            path = os.path.join(step1_dir, "qc_fig", f"qc_{prefix}_mid.png")
        elif view_name == "threes_panel":
            suf = "" if prefix == "pA" else f"_{prefix}"
            path = os.path.join(step1_dir, f"mask_views{suf}_v2.png")
        elif view_name in ("coronal_mask", "sagittal_mask"):
            path = os.path.join(rec["out_dir"], "qc", f"{view_name.replace('_mask', '')}_mask.png")
        if not path or not os.path.isfile(path):
            abort(404)
        return send_file(path, mimetype="image/png")

    @app.route("/api/run/<case_id>", methods=["POST"])
    def api_run(case_id):
        rec = get_case_record(cfg, case_id)
        if rec is None:
            abort(404)
        ok, code, msg = gate_case_access(cfg, rec)
        if not ok:
            return jsonify({"error": msg}), code
        if rec.get("kind") == "synthetic":
            return jsonify({"error": "合成 demo 无需解算——结果已预置（预置回放模式，修订4）"}), 400
        if case_id in RUNNING:
            return jsonify({"error": f"病例 {case_id} 正在运行中"}), 409
        body = request.get_json(silent=True) or {}
        solve = body.get("solve", cfg.solve_default)
        if solve not in ("skip", "laptop", "local"):
            return jsonify({"error": "solve 须为 skip|laptop|local"
                                    "（skip=只到算例+断言；laptop=交接文档待 WSL 求解；"
                                    "local=本机求解/后处理，需 WSL+OpenFOAM 环境）"}), 400
        # 结果回传区：操作员把已回传结果放到 <state>/results/P0-result-<prefix>-<case>/
        result_dir = os.path.join(
            cfg.results_dir,
            f"P0-result-{rec.get('prefix')}-{rec.get('case_name')}")
        if not os.path.isdir(result_dir):
            result_dir = None
        if solve == "local" and result_dir is None:
            # 无已回传结果 → 本机需求解：先探测环境（run_all exit 3 契约前置化）
            try:
                probe = RA.probe_openfoam()
            except Exception:  # noqa: BLE001
                probe = {"any_present": False}
            if not probe.get("any_present"):
                return jsonify({
                    "error": "环境缺失（exit 3 前置检查）：本机未检测到 "
                             "OpenFOAM/WSL/Docker——local 求解不可用；"
                             "可改 solve=laptop 生成交接文档（待 WSL 笔记本求解）"
                             }), 409
        reg = load_registry(cfg)
        r = reg.get(case_id) or rec
        r.update(status="running", updated=now_iso(),
                 run={"solve": solve, "started": now_iso(),
                      "result_dir": result_dir or ""})
        reg[case_id] = r
        save_registry(cfg, reg)
        t = threading.Thread(target=run_chain_thread,
                             args=(cfg, case_id, solve, result_dir), daemon=True)
        RUNNING[case_id] = t
        t.start()
        return jsonify({"case_id": case_id, "status": "running",
                        "solve": solve,
                        "message": "后台链已启动：轮询 GET /api/progress/" + case_id}), 202

    @app.route("/api/progress/<case_id>")
    def api_progress(case_id):
        rec = get_case_record(cfg, case_id)
        if rec is None:
            abort(404)
        ok, code, msg = gate_case_access(cfg, rec)
        if not ok:
            return jsonify({"error": msg}), code
        out_dir = rec.get("out_dir") or ""
        p = os.path.join(out_dir, "manifest-progress.json")
        lines = []
        if os.path.isfile(p):
            try:
                with open(p, encoding="utf-8") as f:
                    for ln in f:
                        ln = ln.strip()
                        if not ln:
                            continue
                        try:
                            lines.append(json.loads(ln))
                        except json.JSONDecodeError:
                            pass
            except OSError:
                pass
        stages = []
        for l in lines:
            m = re.match(r"\[(S\d)\]", l.get("msg", ""))
            if m and m.group(1) not in stages:
                stages.append(m.group(1))
        current = stages[-1] if stages else "—"
        return jsonify({
            "case_id": case_id, "status": rec.get("status"),
            "exit_code": rec.get("exit_code"),
            "gate": rec.get("gate"),
            "gate_failures": rec.get("gate_failures") or [],
            "current_stage": current, "stages_seen": stages,
            "n_lines": len(lines),
            "updated": now_iso(),
            "lines": lines[-100:],
        })

    @app.route("/api/solve/<case_id>", methods=["POST"])
    def api_solve(case_id):
        rec = get_case_record(cfg, case_id)
        if rec is None:
            abort(404)
        ok, code, msg = gate_case_access(cfg, rec)
        if not ok:
            return jsonify({"error": msg}), code
        reg = load_registry(cfg)
        r = reg.get(case_id) or rec
        if r.get("status") != "handover":
            return jsonify({"error":
                            f"仅'交接待解算'状态可启动 WSL 求解（当前：{r.get('status')}）"}), 409
        if case_id in RUNNING:
            return jsonify({"error": "求解已在进行中"}), 409
        # WSL 探测
        try:
            probe = subprocess.run(["wsl", "-l", "-v"], capture_output=True, timeout=60)
            wsl_ok = probe.returncode == 0
        except Exception:  # noqa: BLE001
            wsl_ok = False
        if not wsl_ok:
            return jsonify({"error":
                            "环境缺失：本机未检测到 WSL（wsl -l -v 失败）——"
                            "笔记本侧求解不可用；请在已装 WSL+OpenFOAM 的笔记本上执行"}), 409
        t = threading.Thread(target=solve_thread, args=(cfg, case_id), daemon=True)
        RUNNING[case_id] = t
        t.start()
        return jsonify({"case_id": case_id, "status": "solving",
                        "message": "WSL Allrun 已启动（20 分钟心跳看护）"}), 202

    @app.route("/api/metrics/<case_id>")
    def api_metrics(case_id):
        rec = get_case_record(cfg, case_id)
        if rec is None:
            abort(404)
        ok, code, msg = gate_case_access(cfg, rec)
        if not ok:
            return jsonify({"error": msg}), code
        # pA：冻结单文件版 meta（只读解析 served 产物自身）
        if case_id == "pA":
            single = os.path.join(WEBAPP_DIR, "cases", "pA", "viewer_single.html")
            meta = extract_viewer_meta(single)
            if meta:
                return jsonify(metrics_from_viewer_meta(
                    "pA", meta, "webapp/cases/pA/viewer_single.html（冻结资产只读解析）"))
            rp = case_results_metrics_path("pA")
            if rp:
                return jsonify(metrics_from_postcfd_json(
                    "pA", rp,
                    "out/结果/P0-result-pA-v1/后处理/metrics.json（本例真实结果，只读复用）"))
            return jsonify({"error": "pA 冻结查看器副本缺失"}), 500
        if case_id == "demo":
            meta = extract_viewer_meta(os.path.join(WEBAPP_DIR, "demo", "viewer_data.js"))
            if meta:
                return jsonify(metrics_from_viewer_meta(
                    "demo", meta, "开源仓库 code/viewer/viewer_data.js（合成示例）"))
            return jsonify({"error": "demo viewer_data.js 缺失"}), 500
        if case_id == "pB":
            mp = os.path.join(WEBAPP_DIR, "cases", "pB", "metrics.json")
            if not os.path.isfile(mp):
                mp = case_results_metrics_path("pB")  # 回退本例真实结果
            if mp and os.path.isfile(mp):
                src = ("P0-result-pB-v1/后处理/metrics.json（只读复用副本）"
                       if "webapp" in mp
                       else "out/结果/P0-result-pB-v1/后处理/metrics.json（本例真实结果，只读复用）")
                return jsonify(metrics_from_postcfd_json("pB", mp, src))
            return jsonify({"error": "pB metrics 副本缺失（部署件未执行）"}), 500
        if case_id == "pC":
            sp = os.path.join(WEBAPP_DIR, "cases", "pC", "case_stats-pC-v4.json")
            if os.path.isfile(sp):
                return jsonify(metrics_from_case_stats(
                    "pC", sp, "解剖结构验证/case_stats-pC-v4.json（只读复用副本）"))
            return jsonify({"error": "pC case_stats 副本缺失（部署件未执行）"}), 500
        # 上传病例：优先 step5 导出 meta，其次后处理契约
        out_dir = rec.get("out_dir") or ""
        vd = os.path.join(out_dir, "step5", "viewer_data.js")
        meta = extract_viewer_meta(vd)
        if meta:
            return jsonify(metrics_from_viewer_meta(
                case_id, meta, os.path.join(out_dir, "step5", "viewer_data.js")))
        contract = os.path.join(out_dir, "postprocess",
                                f"contract-{rec.get('prefix')}-{rec.get('case_name')}.json")
        if os.path.isfile(contract):
            with open(contract, encoding="utf-8") as f:
                c = json.load(f)
            return jsonify(metrics_from_viewer_meta(
                case_id, c, os.path.relpath(contract, HERE)))
        return jsonify({"error": "指标未就绪：需先完成 run_all 链（含后处理契约汇编）"}), 404

    @app.route("/viewer/<case_id>")
    def viewer_page(case_id):
        rec = get_case_record(cfg, case_id)
        if rec is None:
            abort(404)
        ok, code, msg = gate_case_access(cfg, rec)
        if not ok:
            return _gate_html(msg, code)
        available = _viewer_available(cfg, rec)
        if not available:
            return _pending_html(cfg, rec)
        if case_id == "demo":
            iframe_src = "/static/demo/viewer.html"
            title = "合成 demo 查看器（参数化管腔 · 100% 合成示例）"
        else:
            single = os.path.join(WEBAPP_DIR, "cases", case_id, "viewer_single.html")
            loose = os.path.join(WEBAPP_DIR, "cases", case_id, "viewer.html")
            if os.path.isfile(single):
                iframe_src = f"/static/cases/{case_id}/viewer_single.html"
            else:
                iframe_src = f"/static/cases/{case_id}/viewer.html"
            title = rec.get("label") or case_id
        html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · 查看器</title>
<style>
body{{margin:0;background:#0d1117;color:#c9d1d9;font-family:system-ui,sans-serif}}
iframe{{width:100vw;height:100vh;border:0}}
</style></head>
<body><iframe src="{iframe_src}" title="{title}"></iframe></body></html>"""
        return html, 200, {"Content-Type": "text/html; charset=utf-8"}

    def _gate_html(msg, code):
        return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>访问受限 · 数据边界</title>
<style>
body{{margin:0;background:#0d1117;color:#c9d1d9;font-family:system-ui,sans-serif;
display:flex;align-items:center;justify-content:center;min-height:100vh}}
.card{{max-width:560px;padding:32px;border:1px solid #f8514966;border-radius:12px;
background:#161b22}}
h1{{color:#f85149;font-size:20px;margin:0 0 12px}}
p{{line-height:1.7}}
</style></head>
<body><div class="card">
<h1>🔒 访问受限（HTTP {code}）</h1>
<p>{msg}</p>
<p>数据边界说明：真实患者数据仅限 M1 本地形态（局域网内，不外传）；
云形态（M2/M3）仅合成 demo 数据（修订1/R-03）。</p>
</div></body></html>""", code, {"Content-Type": "text/html; charset=utf-8"}

    def _pending_html(cfg, rec):
        reason = _viewer_block_reason(cfg, rec)
        ev = ""
        for e in (BUILTIN_DEFS.get(rec["case_id"], {}) or {}).get("evidence", []):
            ev += f"<li><code>{e}</code></li>"
        return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>查看器待解算 · {rec.get('case_id')}</title>
<style>
body{{margin:0;background:#0d1117;color:#c9d1d9;font-family:system-ui,sans-serif;
display:flex;align-items:center;justify-content:center;min-height:100vh}}
.card{{max-width:620px;padding:32px;border:1px solid #d2992266;border-radius:12px;
background:#161b22}}
h1{{color:#d29922;font-size:20px;margin:0 0 12px}}
p,li{{line-height:1.7}}
code{{background:#0d1117;padding:2px 6px;border-radius:4px;font-size:12px}}
</style></head>
<body><div class="card">
<h1>⏳ 查看器待解算 / 待结果回传</h1>
<p><b>{rec.get('label', '')}</b></p>
<p>{reason}</p>
<p>诚实披露：本卡如实展示管线状态——查看器数据（step5 导出）未就绪前不提供查看器入口，
不套用其他患者数字（契约完备性红线）。</p>
<ul>{ev}</ul>
</div></body></html>""", 200, {"Content-Type": "text/html; charset=utf-8"}

    def _viewer_available(cfg, rec):
        cid = rec["case_id"]
        if cid == "demo":
            return os.path.isfile(os.path.join(WEBAPP_DIR, "demo", "viewer_data.js"))
        if cid == "pA":
            return os.path.isfile(os.path.join(WEBAPP_DIR, "cases", "pA", "viewer_single.html"))
        if cid == "pB":
            return False  # 契约完备性闸门：缺占位档（修订3 试跑如实记录）
        if cid == "pC":
            return False  # CFD 结果待笔记本侧回传
        vd = os.path.join(rec.get("out_dir") or "", "step5", "viewer_data.js")
        single = os.path.join(WEBAPP_DIR, "cases", cid, "viewer_single.html")
        return os.path.isfile(vd) or os.path.isfile(single)

    def _viewer_block_reason(cfg, rec):
        cid = rec["case_id"]
        if cid in BUILTIN_DEFS and BUILTIN_DEFS[cid].get("viewer_block_reason"):
            return BUILTIN_DEFS[cid]["viewer_block_reason"]
        if rec.get("status") == "blocked":
            fails = rec.get("gate_failures") or []
            # gate_failures 既有字符串列表，也有 PII 闸门的行列表（[["-","PII",...], ...]）
            # ——统一转成可读字符串，避免 join 抛 TypeError 把整个 /api/cases 打成 500
            return "门禁拦截（⛔）：" + "; ".join(
                " | ".join(map(str, f)) if isinstance(f, (list, tuple)) else str(f)
                for f in fails)[:300]
        if rec.get("status") in ("running", "segmented", "registered", "handover"):
            return "管线进行中/待解算——查看器导出（step5）尚未就绪"
        return ""

    def _builtin_metrics_summary(cfg, cid):
        try:
            if cid == "pA":
                single = os.path.join(WEBAPP_DIR, "cases", "pA", "viewer_single.html")
                meta = extract_viewer_meta(single)
                if meta:
                    mm = _metrics_block(meta)
                    return {"dP_Pa": mm.get("dP_baseline_Pa"),
                            "split_L_pct": mm.get("split_L_pct"),
                            "split_R_pct": mm.get("split_R_pct"),
                            "resistance": mm.get("resistance_total"),
                            "口径": "ΔP 定流量 / R 等压（双口径标签，R-10）"}
            if cid == "pB":
                mp = os.path.join(WEBAPP_DIR, "cases", "pB", "metrics.json")
                if os.path.isfile(mp):
                    m = json.load(open(mp, encoding="utf-8"))
                    t = m.get("totals", {})
                    return {"dP_Pa": round(float(t.get("dP_Pa", 0)), 2),
                            "split_L_pct": round(float(t.get("flow_share_L_pct", 0)), 1),
                            "split_R_pct": round(float(t.get("flow_share_R_pct", 0)), 1),
                            "口径": "定流量口径（Run-A dP/Q）"}
            if cid in ("pA", "pB"):
                # 部署副本缺失时回退本例真实结果 out/结果/.../后处理/metrics.json
                mp = case_results_metrics_path(cid)
                if mp:
                    m = json.load(open(mp, encoding="utf-8"))
                    t = m.get("totals", {})
                    dP = float(t.get("dP_Pa", 0))
                    Q = float(t.get("Q_inlet_total_L_min", 0))
                    R = dP / (Q / 60.0) if Q else None
                    return {"dP_Pa": round(dP, 2),
                            "split_L_pct": round(float(t.get("flow_share_L_pct", 0)), 1),
                            "split_R_pct": round(float(t.get("flow_share_R_pct", 0)), 1),
                            "resistance": round(R, 1) if R else None,
                            "口径": "定流量口径（Run-A dP/Q）"}
            if cid == "pC":
                sp = os.path.join(WEBAPP_DIR, "cases", "pC", "case_stats-pC-v4.json")
                if os.path.isfile(sp):
                    s = json.load(open(sp, encoding="utf-8"))
                    return {"cells": s.get("cells"),
                            "inletL_mm2": s.get("inletL", {}).get("area_mm2"),
                            "inletR_mm2": s.get("inletR", {}).get("area_mm2"),
                            "cfd": "待结果回传"}
            if cid == "demo":
                meta = extract_viewer_meta(
                    os.path.join(WEBAPP_DIR, "demo", "viewer_data.js"))
                if meta:
                    mm = _metrics_block(meta)
                    return {"dP_Pa": mm.get("dP_baseline_Pa"),
                            "split_L_pct": mm.get("split_L_pct"),
                            "split_R_pct": mm.get("split_R_pct"),
                            "resistance": mm.get("resistance_total"),
                            "口径": "合成示例口径（参数化模型）"}
        except Exception:  # noqa: BLE001
            return None
        return None

    def _upload_metrics_summary(cfg, rec):
        out_dir = rec.get("out_dir") or ""
        vd = os.path.join(out_dir, "step5", "viewer_data.js")
        meta = extract_viewer_meta(vd)
        if meta:
            mm = _metrics_block(meta)
            return {"dP_Pa": mm.get("dP_baseline_Pa"),
                    "split_L_pct": mm.get("split_L_pct"),
                    "split_R_pct": mm.get("split_R_pct"),
                    "resistance": mm.get("resistance_total")}
        contract = os.path.join(out_dir, "postprocess",
                                f"contract-{rec.get('prefix')}-{rec.get('case_name')}.json")
        if os.path.isfile(contract):
            try:
                with open(contract, encoding="utf-8") as f:
                    c = json.load(f)
                mm = c.get("metrics", {})
                return {"dP_Pa": mm.get("dP_baseline_Pa"),
                        "split_L_pct": mm.get("split_L_pct"),
                        "split_R_pct": mm.get("split_R_pct"),
                        "resistance": mm.get("resistance_total")}
            except Exception:  # noqa: BLE001
                return None
        return None

    return app


def main():
    ap = argparse.ArgumentParser(description="T15 Web 工作台后端（Flask）")
    ap.add_argument("--mode", choices=["m1-local", "m2-cloud"], default="m1-local",
                    help="部署形态：m1-local=笔记本服务器（真实数据可展示）；"
                         "m2-cloud=云形态（仅合成数据，R-03 代码级禁用上传）")
    ap.add_argument("--base-dir", default=None,
                    help="参赛群资料 根目录（内置病例 CT 源；默认读环境变量 P0_CT_BASE）")
    ap.add_argument("--state-dir", default=None,
                    help="状态目录（病例注册表/运行时产物；默认 pipeline/out/webapp-state）")
    ap.add_argument("--solve", choices=["skip", "laptop"], default="skip",
                    help="POST /api/run 默认求解模式（默认 skip：只到算例+断言）")
    ap.add_argument("--presenter", action="store_true",
                    help="presenter 定向演示模式（解锁 pB 详情，R-01 授权分级）")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    cfg = ServerConfig(mode=args.mode, base_dir=args.base_dir,
                       state_dir=args.state_dir, solve=args.solve,
                       presenter=args.presenter, host=args.host, port=args.port)
    app = build_app(cfg)
    print(f"[T15 server] 形态={cfg.mode} ONLY_SYNTHETIC={cfg.only_synthetic} "
          f"presenter={cfg.presenter} 端口={cfg.port}")
    print(f"[T15 server] CT 根目录：{cfg.ct_base or '（未配置 --base-dir，内置病例 CT 不可用）'}")
    print(f"[T15 server] 状态目录：{cfg.state_dir}")
    app.run(host=cfg.host, port=cfg.port, threaded=True)


if __name__ == "__main__":
    main()
