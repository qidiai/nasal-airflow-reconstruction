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

部署形态（数据边界硬闸 · 修订1 · T17 弹窗授权升级）：
- m1-local（默认；M1 笔记本=服务器）：ONLY_SYNTHETIC=false，真实患者数据
  可展示（pA/pB 演示展示在案；R-01 授权分级机制保留——对 presenter_only 病例生效）
- m2-cloud（M2/M3 云形态）：ONLY_SYNTHETIC=true，仅合成 demo；
  POST /api/case 代码级禁用（501，R-03）；非合成病例访问一律 403 + 中文提示
- T17 弹窗授权工作流：上传真实数据前三问（数据主体/处理位置/数据保留）→
  consent_record.json 落档 → 路由矩阵分级放行。云形态真实病例须带合法 consent
  （本人/已授权 + 云端 opt-in；他人数据须有 authorization_ref）才放行，记录缺失
  一律 fail-closed 拦截（旧硬闸语义保留）。PII 扫描与质量闸门判定逻辑一行未改。

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
import io
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
import solver_backend as SB  # noqa: E402  # M3：custom / openfoam / auto

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from flask import Flask, jsonify, request, send_file, abort  # noqa: E402

# ---------------------------------------------------------------- 路径（全部相对 HERE，R-14）
WEBAPP_DIR = os.path.join(HERE, "webapp")
STEP1 = os.path.join(HERE, "step1_airway_segment.py")
RUN_ALL = os.path.join(HERE, "run_all.py")
STEP3 = os.path.join(HERE, "step3_make_narrowing.py")
STEP5 = os.path.join(HERE, "step5_export_viewer_data.py")
VIEWER_TEMPLATE = os.path.join(WEBAPP_DIR, "viewer_template", "viewer.html")
BUILD_SINGLE = os.path.join(WEBAPP_DIR, "tools", "build_single_file.py")
# 共享几何产物落点（内置病例历史 run_all OUT_ROOT=HERE/out；上传病例在 state cases/<cid>）
SHARED_STEP2 = os.path.join(HERE, "out", "step2")


def post_cfd_path(cfg=None):
    """post_cfd.py 定位（仓库外数据盘资产，R-14：不硬编码绝对路径）：
    环境变量 P0_POST_CFD 优先；否则按 ct_base 相对推导
    <ct_base 上级>/项目/P0-鼻塞设计工具/阶段2-CFD后处理/post_cfd.py。
    找不到返回 None（调用方按环境缺失上报）。"""
    env = os.environ.get("P0_POST_CFD")
    if env and os.path.isfile(env):
        return env
    base = ""
    if cfg is not None:
        base = cfg.ct_base or ""
    base = base or os.environ.get("P0_CT_BASE") or ""
    if base:
        p = os.path.join(os.path.dirname(os.path.abspath(base)),
                         "项目", "P0-鼻塞设计工具",
                         "阶段2-CFD后处理", "post_cfd.py")
        if os.path.isfile(p):
            return p
    return None


def _pipeline_python():
    """管线子进程解释器（T16 全自动链）：仓库 .venv 优先
    （pyvista/skimage/trimesh/pydicom 等管线依赖全齐）;无 venv 部署则回退当前解释器
    （此时要求运行 server 的解释器已装齐管线依赖）。R-14：相对推导,零硬编码。"""
    venv_py = os.path.join(os.path.dirname(os.path.dirname(HERE)),
                           ".venv", "Scripts", "python.exe")
    return venv_py if os.path.isfile(venv_py) else sys.executable

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
    """真实结果目录 out/结果/P0-result-<case_id>-v1/后处理/（通用拼路径 + 存在性判定）。

    去 RESULT_CASES 硬编码（原先只认 pA/pB）：改按 case_id 通用拼路径，
    目录存在才返回（上传病例跑完管线并回填结果后自动命中）。
    case_id 仅接受安全令牌（字母/数字/下划线/连字符）——防 URL 路径穿越。
    """
    if not case_id or not re.match(r"^[A-Za-z0-9_-]+$", str(case_id)):
        return ""
    d = os.path.join(RESULTS_ROOT, f"P0-result-{case_id}-v1", "后处理")
    return d if os.path.isdir(d) else ""


# LT-8：结果档案"必需文件"白名单子集（RESULTS_WHITELIST 的文件名 + metrics.json 为契约锚点）。
# 只做"档案在不在"的存在性判断——不解析内容，不改任何导出闸门。
REQUIRED_RESULT_FILES = ("metrics.json",)


def case_results_status(case_id):
    """结果档案就绪度：(ok, 缺失文件清单)。

    ok = 结果目录存在且必需文件齐全。上传病例 status=done 但 ok=False 即"陈旧病例"
    （badge 该显示 ⚠️ 而不是 ✅）——只标记，不删数据、不改导出。
    """
    files = [fn for fn in REQUIRED_RESULT_FILES if fn in RESULTS_WHITELIST]
    d = case_results_dir(case_id)
    if not d:
        return False, list(files)
    missing = [fn for fn in files if not os.path.isfile(os.path.join(d, fn))]
    return (not missing), missing


def scan_stale_cases(cfg):
    """启动自检（LT-8）：扫描注册表，统计"结果缺失的陈旧病例"，打印 [W] 日志。

    只标记不删数据：不写注册表、不动任何目录，仅把事实暴露在启动日志里，
    便于操作员发现 pX 这类"badge=done 但结果目录为空"的历史记录。
    """
    try:
        reg = load_registry(cfg)
    except Exception as e:  # noqa: BLE001
        print("[W] 陈旧病例扫描跳过（注册表读取失败：%r）" % (e,), flush=True)
        return 0
    stale = []
    for cid, r in sorted(reg.items()):
        if not isinstance(r, dict):
            continue
        if r.get("kind") != "upload" or r.get("status") != "done":
            continue
        ok, missing = case_results_status(cid)
        if not ok:
            stale.append((cid, missing))
    for cid, missing in stale:
        print("[W] 陈旧病例 %s：status=done 但结果档案缺失（缺 %s）——仅标记 stale，不删数据"
              % (cid, ",".join(missing) or "结果目录"), flush=True)
    if stale:
        print("[W] 陈旧病例扫描：%d 个上传病例标记为结果缺失（stale）——前端显示 ⚠️（结果缺失）"
              % len(stale), flush=True)
    return len(stale)


# ---------------------------------------------------------------- 真实鼻腔 3D 模型（GLB）  [MODEL-ROUTE]
# 白名单（case_id → 文件名）。2026-10-16 裁决：pN/pN2 正常对照前端下架
# （鼻阻力经文献对比未达标准），GLB 数据文件保留不删、仅不再 serve。
MODEL_FILES = {
    "pA": "airway_pA.glb",
    "pB": "airway_pB.glb",
}


def case_model_path(case_id):
    """真实气道 GLB 路径（白名单 pA/pB；不存在返回空串）。"""
    fn = MODEL_FILES.get(case_id)
    if not fn:
        return ""
    p = os.path.join(WEBAPP_DIR, "models", fn)
    return p if os.path.isfile(p) else ""


def digest_pii_fail(f):
    """PII 闸门失败记录脱敏：保留字段名与判定语，值字段（第 3 个元素）摘要化。

    run_all.scan_pii 的 fails 元素形如 (文件名, 字段名, 原始值, 判定语)——
    原始值为患者标识（姓名/编号等），落库与前端展示前必须摘要化（安全底线）。
    """
    try:
        parts = list(map(str, f))
    except Exception:  # noqa: BLE001
        return str(f)
    if len(parts) >= 3:
        raw = parts[2]
        parts[2] = "<值已隐藏,长度%d>" % len(raw)
    return parts


# run_all 的 FATAL 行把 scan_pii 的 fails 元组 repr 原样带出（含原始值）。
# 前端"拦截原因"卡片要展示该行，因此展示前把元组第 3 个元素（值字段）摘要化。
_PII_TUPLE_RE = re.compile(
    r"(\(\s*'(?:[^'\\]|\\.)*'\s*,\s*'(?:[^'\\]|\\.)*'\s*,\s*)('[^']*'|\"[^\"]*\")")


def mask_fatal_pii_values(text):
    """把 FATAL 行里 PII 元组的"值"字段摘要化（只影响展示，不动日志/数据）。"""
    s = str(text or "")
    if "PatientName" not in s and "PatientID" not in s and "AccessionNumber" not in s \
            and "InstitutionName" not in s:
        return s
    try:
        return _PII_TUPLE_RE.sub(lambda m: m.group(1) + "'<值已隐藏>'", s)
    except Exception:  # noqa: BLE001
        return s


def case_results_metrics_path(case_id):
    """本例真实 metrics.json 路径（不存在时返回空串）。"""
    d = case_results_dir(case_id)
    p = os.path.join(d, "metrics.json") if d else ""
    return p if os.path.isfile(p) else ""


def case_results_available(cfg, case_id):
    """本例"导出结果"是否就绪（判定 = out/结果/P0-result-<cid>-v1/后处理/metrics.json 存在）。

    上传病例跑完管线并回填结果后自动 true（去 RESULT_CASES 硬编码）。
    云形态（only_synthetic）下恒 False——与 /api/results 的 403 数据边界硬闸一致。
    """
    if cfg.only_synthetic:
        return False
    return bool(case_results_metrics_path(case_id))


# ---------------------------------------------------------------- 两例对比（患者/家属友好聚合）  [COMPARE]
# 路演核心演示：一屏并排“患者 A / 患者 B”约 8 项指标 + 文献正常范围参考带。
# 数据全部只读自既有产物——不新增计算、不改动任何管线/契约：
#   指标（ΔP/分流/WSS/Re…）：out/结果/P0-result-<cid>-v1/后处理/metrics.json
#   气道体积（cm³）        ：run_all 清单 run_all_manifest-<cid>-v1.json
#                            （stages.S2_step1.airway_volume_cm3；回退 step1 指标）
# 两例路径白名单硬编码（cid 不外泄为路径）；缺失/解析失败该例标记 ready=False，绝不抛异常。
# 2026-10-16 裁决：pN/pN2 两例官方“正常对照”CT 经权威文献对比未达标准
# （rhinomanometry @150Pa 正常鼻阻力 0.15-0.5 Pa·s/cm³；实测 0.111 / 0.595，
# 601 例综述 2026 + 共识）——前端下架（数据文件保留不删），
# 正常对照改用文献正常范围参考带做权威对照（领域公开缺口如实标注）。
COMPARE_ORDER = ("pA", "pB")
COMPARE_LABELS = {
    "pA": "患者A（空鼻症）",
    "pB": "患者B（赛方 CT）",
}
# 文献正常范围参考带：对比表顶部静态灰色说明行（/api/compare 响应 ref_band 字段）
COMPARE_REF_BAND = {
    "label": "文献正常鼻阻力范围 0.15-0.5 Pa·s/cm³（rhinomanometry @150Pa）",
    "lo_Pa_s_cm3": 0.15,
    "hi_Pa_s_cm3": 0.5,
    "unit": "Pa·s/cm³",
    "source": "601 例综述 2026 + 共识",
}
COMPARE_NOTES = {
    "口径": "同管线同参数（voxel-z 2.0）口径对比",
    "volume_source": "气道体积只读自本例 step1 指标"
                     "（run_all 清单 stages.S2_step1.airway_volume_cm3）",
    "wss_note": "内壁摩擦感（WSS）为一次守恒体素估计，"
                "见本例后处理 report.md「局限」一节",
    "resistance_calc": "鼻阻力 R = ΔP ÷ (Q_inlet_total ÷ 60)（定流量口径）",
}


def _compare_volume_cm3(cid):
    """气道体积（cm³，只读）：run_all 清单优先，step1 指标回退。
    返回 (volume_or_None, 相对来源路径)。所有路径由 cid 白名单拼出，只读。"""
    cands = [
        (os.path.join(HERE, "out", f"run_all_manifest-{cid}-v1.json"),
         ("stages", "S2_step1", "airway_volume_cm3")),
        (os.path.join(HERE, "out", "step1", f"metrics_{cid}_v2.json"),
         ("airway_volume_cm3",)),
    ]
    for path, keys in cands:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:  # UTF-8 硬编码（中文路径/字段）
                node = json.load(f)
            for k in keys:
                if not isinstance(node, dict):
                    node = None
                    break
                node = node.get(k)
            if node is not None:
                return float(node), os.path.relpath(path, HERE).replace("\\", "/")
        except (OSError, ValueError, TypeError):
            continue
    return None, ""


def _compare_fnum(node):
    """安全转 float；None/空/不可转 → None。"""
    if node is None:
        return None
    try:
        return float(node)
    except (ValueError, TypeError):
        return None


def compare_case_metrics(cid):
    """单例对比指标聚合。文件缺失/解析失败 → ready=False（不抛异常，不炸整端）。"""
    out = {"cid": cid, "label": COMPARE_LABELS.get(cid, cid),
           "ready": False, "metrics": {}, "source": "", "volume_source": ""}
    mp = case_results_metrics_path(cid)
    if not mp:
        return out
    try:
        with open(mp, encoding="utf-8") as f:  # UTF-8 硬编码
            m = json.load(f)
        t = m.get("totals", {}) or {}
        wss = m.get("wss", {}) or {}
        dP = _compare_fnum(t.get("dP_Pa"))
        Q = _compare_fnum(t.get("Q_inlet_total_L_min"))
        fl = _compare_fnum(t.get("flow_share_L_pct"))
        fr = _compare_fnum(t.get("flow_share_R_pct"))
        re_eq = _compare_fnum(t.get("Re_eq"))
        wm = _compare_fnum(wss.get("mean_Pa"))
        w95 = _compare_fnum(wss.get("p95_Pa"))
    except (OSError, ValueError, TypeError):
        return out
    vol, vsrc = _compare_volume_cm3(cid)
    R = round(dP / (Q / 60.0), 1) if (dP is not None and Q) else None
    out["metrics"] = {
        "dP_Pa": round(dP, 2) if dP is not None else None,
        "resistance_Pa_per_Ls": R,
        "split_L_pct": round(fl, 1) if fl is not None else None,
        "split_R_pct": round(fr, 1) if fr is not None else None,
        "wss_mean_Pa": round(wm, 4) if wm is not None else None,
        "wss_p95_Pa": round(w95, 4) if w95 is not None else None,
        "Re": round(re_eq, 0) if re_eq is not None else None,
        "volume_cm3": round(vol, 1) if vol is not None else None,
        "Q_inlet_L_min": round(Q, 3) if Q is not None else None,
    }
    out["ready"] = True
    out["source"] = os.path.relpath(mp, HERE).replace("\\", "/")
    out["volume_source"] = vsrc
    return out


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
                 solve="skip", presenter=False, host="127.0.0.1", port=8080):
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
    used = set(reg.keys()) | {"pA", "pB", "pC", "pN", "pN2", "demo"}  # pN/pN2 保留防撞号（下架病例的结果档案仍在盘上）
    if "pX" not in used:
        return "pX"
    n = 2
    while f"pX{n}" in used:
        n += 1
    return f"pX{n}"


# ---------------------------------------------------------------- T17 弹窗授权工作流
# 背景：原"合成数据硬闸"（only_synthetic）一刀切拦真实数据——患者自助用不了。
# T17 升级为**分级弹窗授权工作流**：
#   ① 上传真实数据前弹三问（数据主体/处理位置/数据保留）→
#   ② consent_record.json 落档（与产物同目录，随 manifest 可追溯）→
#   ③ 路由矩阵分级放行（m1-local 本地直跑；m2-cloud 仅"本人/已授权 + 云端 opt-in"放行）。
# 红线（改动纪律）：PII 头扫描与质量闸门（run_all exit 2/3）的判定逻辑一行未改——
# 本模块只是其上的"放行层"；且 consent 记录缺失时一律按拦截处理（fail-closed，
# 旧硬闸语义完整保留）。弹窗文案中性、不诱导、不夸大。
CONSENT_SCHEMA = "consent_record/v1"
CONSENT_PROMPT_VERSION = "T17-v1"
CONSENT_FILENAME = "consent_record.json"
CONSENT_DISCLAIMER = "分析结果仅供科研与康复参考，非诊断依据，非医疗器械。"
DATA_SUBJECTS = ("self", "authorized_third_party", "demo")
PROCESSING_SCOPES = ("local_only", "cloud_optin")
RETENTION_DAYS = (1, 7, 30)
# 弹窗三问的中文选项文案 ↔ 规范枚举（前端文案与落档字段解耦；两种写法都收）
_DATA_SUBJECT_ALIASES = {
    "self": "self", "本人ct": "self", "本人": "self", "自身": "self",
    "authorized_third_party": "authorized_third_party",
    "已获授权的他人ct": "authorized_third_party", "他人ct": "authorized_third_party",
    "已获授权": "authorized_third_party",
    "demo": "demo", "演示数据": "demo",
}
_PROCESSING_ALIASES = {
    "local_only": "local_only", "仅本机处理": "local_only",
    "cloud_optin": "cloud_optin", "允许云端处理": "cloud_optin",
}
_DATA_SUBJECT_LABELS = {"self": "本人CT", "authorized_third_party": "已获授权的他人CT",
                        "demo": "演示数据"}
_PROCESSING_LABELS = {"local_only": "仅本机处理", "cloud_optin": "允许云端处理"}


def _rel_to_here(path):
    """相对仓库根的展示路径；跨盘（状态目录在 C:\\ 等）时回退绝对路径，绝不抛错。"""
    try:
        return os.path.relpath(path, HERE).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def consent_record_path(rec):
    """consent 记录路径：<病例输出目录>/consent_record.json（与管线产物同目录）。"""
    out_dir = (rec or {}).get("out_dir") or ""
    return os.path.join(out_dir, CONSENT_FILENAME) if out_dir else ""


def _parse_retention(v):
    """数据保留 → 规范值（session_only | days:N，N∈{1,7,30}）；非法返回 None。"""
    s = str(v if v is not None else "").strip()
    if not s:
        return None
    if s.lower() == "session_only" or s.startswith("仅本次会话"):
        return "session_only"
    m = re.match(r"^days:\s*(\d+)$", s.lower()) or re.match(r"^保留\s*(\d+)\s*天$", s)
    if m and int(m.group(1)) in RETENTION_DAYS:
        return "days:%d" % int(m.group(1))
    return None


def parse_consent_fields(src):
    """弹窗三问 → 规范 consent 字段；校验失败返回 (None, 中文错误串, 出错字段名)。

    三问校验（顺序即报错顺序）：
      ① 数据主体 ∈ 本人CT / 已获授权的他人CT / 演示数据
      ② 处理位置 ∈ 仅本机处理 / 允许云端处理
      ③ 数据保留 ∈ 仅本次会话 / 保留1天 / 保留7天 / 保留30天（不提供永久保留）
    附加：非演示数据必填"来源一句话"；authorization_ref 由放行层判定
    （见 evaluate_consent——缺凭证时如实拦截而非此处 400，便于落档留证）。

    第 3 个返回值是字段名（data_subject / processing_scope / retention /
    source_declaration / authorization_ref），供前端把 400 定位到具体控件。
    成功时返回 (fields, "", "")。
    """
    src = src if isinstance(src, dict) else {}
    ds_raw = str(src.get("data_subject") or "").strip()
    ds = _DATA_SUBJECT_ALIASES.get(ds_raw.lower())
    if not ds:
        return None, ("数据主体须为 本人CT / 已获授权的他人CT / 演示数据（收到："
                      + (ds_raw or "（空）") + "）"), "data_subject"
    ps_raw = str(src.get("processing_scope") or "").strip()
    ps = _PROCESSING_ALIASES.get(ps_raw.lower())
    if not ps:
        return None, ("处理位置须为 仅本机处理 / 允许云端处理（收到："
                      + (ps_raw or "（空）") + "）"), "processing_scope"
    ret = _parse_retention(src.get("retention"))
    if not ret:
        return None, ("数据保留须为 仅本次会话 / 保留1天 / 保留7天 / 保留30天（收到："
                      + str(src.get("retention") or "（空）") + "）"), "retention"
    decl = str(src.get("source_declaration") or "").strip()
    if ds != "demo" and not decl:
        return None, "来源声明必填（演示数据可空）：请用一句话说明数据来源", "source_declaration"
    return {"data_subject": ds,
            "source_declaration": decl,
            "authorization_ref": str(src.get("authorization_ref") or "").strip(),
            "processing_scope": ps,
            "retention": ret}, "", ""


def build_consent_record(case_id, fields, pii_scan="pass"):
    """构造 consent_record.json（T17-v1 契约字段；键序对齐任务书 §②）。"""
    return {
        "schema": CONSENT_SCHEMA,
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "prompt_version": CONSENT_PROMPT_VERSION,
        "case_id": case_id,
        "data_subject": fields.get("data_subject"),
        "source_declaration": fields.get("source_declaration") or "",
        "authorization_ref": fields.get("authorization_ref") or "",
        "processing_scope": fields.get("processing_scope"),
        "retention": fields.get("retention"),
        "pii_scan": pii_scan,
        "ui_lang": "zh-CN",
    }


def save_consent_record(rec, record):
    """consent 记录落档（原子替换写；返回落盘路径，失败抛 OSError）。"""
    p = consent_record_path(rec)
    if not p:
        return ""
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)
    return p


def load_consent_record(rec):
    """读病例 consent 记录；缺失/损坏 → None（调用方一律按 fail-closed 处理）。"""
    p = consent_record_path(rec)
    if not p or not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return d if isinstance(d, dict) else None


def consent_summary(rec):
    """注册表/接口用 consent 摘要（字段级，不含患者标识）。"""
    c = load_consent_record(rec)
    if not c:
        return None
    return {
        "schema": c.get("schema"), "timestamp": c.get("timestamp"),
        "prompt_version": c.get("prompt_version"),
        "data_subject": c.get("data_subject"),
        "data_subject_label": _DATA_SUBJECT_LABELS.get(c.get("data_subject"), "?"),
        "processing_scope": c.get("processing_scope"),
        "processing_scope_label": _PROCESSING_LABELS.get(c.get("processing_scope"), "?"),
        "retention": c.get("retention"),
        "authorization_ref": c.get("authorization_ref") or "",
        "pii_scan": c.get("pii_scan"),
    }


def evaluate_consent(cfg, rec, consent):
    """路由矩阵判定（fail-closed 兜底）。返回 dict：
    {"release": bool, "basis": 判定依据, "reason": 拦截理由(放行时空串), "code": 拦截码|None}

    矩阵（任务书 §③）：
      m1-local  本人/已授权/演示  —— 放行（本地形态现状语义保留；consent 仅作知情记录）
      m1-local  PII FAIL         —— ⛔（上游 _register_case 已拦，本层不放行 PII）
      m2-cloud  demo(合成)       —— 放行（rec.synthetic 直通，现状不变）
      m2-cloud  本人 + 云端 opt-in —— 放行
      m2-cloud  他人数据无凭证    —— ⛔ 缺少授权凭证
      m2-cloud  consent 缺失      —— ⛔ fail-closed（旧硬闸语义）
      任何       质量闸 fail       —— propagate（run_all exit 2 → blocked，本层不覆盖）
    """
    case_id = rec.get("case_id")
    if rec.get("synthetic"):
        return {"release": True, "basis": "synthetic", "reason": "", "code": None}
    if not cfg.only_synthetic:
        # m1-local（M1 笔记本=服务器）：真实数据本形态即允许（现状语义一行未收紧）。
        # PII 头扫描与质量闸门在其上游独立把关，弹窗不参与放行判定。
        return {"release": True, "basis": "local", "reason": "", "code": None}
    # ---------------- m2-cloud：分级放行 ----------------
    if not consent:
        return {"release": False, "basis": "fail_closed", "code": 403,
                "reason": "consent 授权记录缺失——未通过弹窗授权"
                          "（fail-closed：旧硬闸语义保留，一律按拦截处理）"}
    if consent.get("case_id") and str(consent.get("case_id")) != str(case_id):
        return {"release": False, "basis": "record_mismatch", "code": 403,
                "reason": "consent 记录与本病例不匹配（记录 %s ≠ 病例 %s）"
                          % (consent.get("case_id"), case_id)}
    if (rec.get("pii") or {}).get("pass") is False or consent.get("pii_scan") == "fail":
        return {"release": False, "basis": "pii_fail", "code": 403,
                "reason": "PII 头扫描 FAIL——弹窗授权不能放行 PII 拦截（如实拦截）"}
    subj = consent.get("data_subject")
    if subj == "demo":
        return {"release": False, "basis": "subject_mismatch", "code": 403,
                "reason": "声明为『演示数据』但本病例含真实患者数据——声明与数据不符"}
    if subj not in DATA_SUBJECTS:
        return {"release": False, "basis": "bad_subject", "code": 403,
                "reason": "consent 记录数据主体字段非法：" + str(subj)}
    if consent.get("processing_scope") != "cloud_optin":
        return {"release": False, "basis": "scope_not_optin", "code": 403,
                "reason": "处理位置为『仅本机处理』——未授权云端处理，云形态不可访问"}
    if subj == "authorized_third_party" and not str(
            consent.get("authorization_ref") or "").strip():
        return {"release": False, "basis": "missing_ref", "code": 403,
                "reason": "缺少授权凭证，上传方需提供数据来源授权"}
    if consent.get("pii_scan") != "pass":
        return {"release": False, "basis": "pii_not_scanned", "code": 403,
                "reason": "consent 记录未载明 PII 扫描 PASS（当前：%s）"
                          % (consent.get("pii_scan") or "（空）")}
    return {"release": True, "basis": "cloud_optin", "reason": "", "code": None}


def _consent_audit(cfg, event):
    """consent 事件审计流水（JSONL，落 state_dir；不进病例目录，不随病例删除而消失）。"""
    try:
        p = os.path.join(cfg.state_dir, "consent-audit.jsonl")
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _consent_from_form(form):
    """从表单解析弹窗三问（字段 consent=JSON 串）。返回 (fields|None, err|None, field|None)。

    缺省即"未弹窗"（向后兼容：不带 consent 的调用行为与 T16 完全一致）；
    带字段但非法 → (None, 错误串, 字段名)，调用方 400 并把字段名回给前端定位控件。
    """
    raw = form.get("consent") if form is not None else None
    if not raw:
        return None, None, None
    try:
        src = json.loads(raw)
    except (ValueError, TypeError):
        return None, "consent 字段须为 JSON 对象（弹窗三问）", "consent"
    return parse_consent_fields(src)


def _session_purge(cfg, case_id):
    """『仅本次会话（跑完即删）』：分析链结束后删除本例数据（上传副本+输出目录+注册表条目）。

    仅对 kind==upload 且 consent.retention==session_only 的病例生效；路径包含性校验
    与 DELETE /api/case 同口径（realpath 必须落在 state_dir 内，否则不删）。
    内置/合成病例、未声明 session_only 的病例一律不动。返回是否执行了清理。
    """
    try:
        rec = get_case_record(cfg, case_id)
        if not rec or rec.get("kind") != "upload":
            return False
        consent = load_consent_record(rec)
        if not consent or consent.get("retention") != "session_only":
            return False
        state = os.path.realpath(cfg.state_dir)
        targets = []
        out_dir = rec.get("out_dir") or ""
        if out_dir and os.path.realpath(out_dir).startswith(state + os.sep):
            targets.append(out_dir)
        up_root = os.path.realpath(os.path.join(cfg.state_dir, "uploads"))
        for p in (rec.get("dicom_dir"), rec.get("upload_source_dir")):
            if not p:
                continue
            real = os.path.realpath(p)
            if real == up_root or real.startswith(up_root + os.sep):
                targets.append(real)
        removed = []
        for t in targets:
            if os.path.isdir(t):
                shutil.rmtree(t, ignore_errors=True)
                removed.append(_rel_to_here(t))
        reg = load_registry(cfg)
        reg.pop(case_id, None)
        save_registry(cfg, reg)
        _consent_audit(cfg, {"ts": now_iso(), "event": "session_only_purge",
                             "case_id": case_id, "removed": removed,
                             "retention": "session_only"})
        return True
    except Exception as e:  # noqa: BLE001
        # 清理失败绝不反噬管线；但如实留痕（不许静默吞）
        _consent_audit(cfg, {"ts": now_iso(), "event": "session_only_purge_error",
                             "case_id": case_id, "error": repr(e)})
        return False


# ---------------------------------------------------------------- 数据边界硬闸（修订1 / R-03）
def gate_case_access(cfg, rec):
    """返回 (ok, http_status, message)。

    T17：云形态的"仅合成数据"硬闸升级为**分级放行层**——真实病例带合法
    consent_record.json（本人/已授权 + 云端 opt-in）才放行；记录缺失或不足
    一律拦截（fail-closed，旧硬闸语义保留）。m1-local 行为与 T16 一致。
    """
    if cfg.only_synthetic and not rec.get("synthetic"):
        ev = evaluate_consent(cfg, rec, load_consent_record(rec))
        if not ev["release"]:
            return (False, ev["code"] or 403,
                    "数据边界（T17 弹窗授权分级放行）：" + ev["reason"]
                    + f"；本形态为云形态（M2/M3），病例 {rec.get('case_id')} 未获放行")
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
        r["gate_failures"] = [mask_fatal_pii_values(extract_fatal_reason(out_dir))
                              or "断言停工（exit 2），详见进度日志"]
        append_progress(out_dir, f"[W] ⛔ 门禁拦截（exit 2）：{r['gate_failures'][0]}")
    elif mapped == "failed_env":
        r["gate_failures"] = [f"求解环境缺失（exit 3，backend={SB.resolve_backend()}）："
                              "local 模式不可用；可改 --solve laptop 生成交接文档，"
                              "或 --backend custom/openfoam"]
        append_progress(out_dir, "[W] 环境缺失（exit 3）：" + r["gate_failures"][0])
    else:
        r["gate_failures"] = [f"后台链失败（exit {rc}），详见进度日志"]
        append_progress(out_dir, r["gate_failures"][0])
    r["status"] = mapped
    reg[case_id] = r
    save_registry(cfg, reg)
    RUNNING.pop(case_id, None)
    _session_purge(cfg, case_id)  # T17：consent『仅本次会话（跑完即删）』


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
    # ---- M3：后端分派（custom 无需 WSL；openfoam 保留对拍路径）----
    backend = SB.resolve_backend()
    if backend == "custom":
        if not SB.custom_available():
            _mark_solve_status(cfg, case_id, "failed",
                               ["custom 后端不可用：FlowScope 可执行文件不存在"])
            return
        append_progress(out_dir, "[W] 自研 FlowScope 求解启动：" + case_dir)
        rc = SB.run_custom_monitored(
            case_dir, case_dir, tag="custom", stall_limit=7200,
            progress=lambda m: append_progress(out_dir, "[W] " + m))
        if rc == 0:
            append_progress(out_dir, "[W] FlowScope 完成（exit 0）——进入后处理+step5")
            reg = load_registry(cfg)
            r = reg.get(case_id) or rec
            r["status"] = "running"
            r["updated"] = now_iso()
            reg[case_id] = r
            save_registry(cfg, reg)
            run_chain_thread(cfg, case_id, "local", case_dir)
        else:
            append_progress(out_dir, f"[W] FlowScope 失败（exit {rc}）")
            _mark_solve_status(cfg, case_id, "failed",
                               [f"自研 FlowScope 求解失败（exit {rc}）；日志："
                                + os.path.join(case_dir, "solver.log")])
        return
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
    _session_purge(cfg, case_id)  # T17：consent『仅本次会话（跑完即删）』


# ---------------------------------------------------------------- T16 全自动链编排（占位算例接线）
def _mark_full_chain(cfg, case_id, **fields):
    """full_chain 进度字段写注册表（cases_total/cases_done/stage 等；不动 status）。"""
    reg = load_registry(cfg)
    r = reg.get(case_id)
    if r is None:
        return
    fc = r.get("full_chain") or {}
    fc.update(fields)
    fc["updated"] = now_iso()
    r["full_chain"] = fc
    r["updated"] = now_iso()
    reg[case_id] = r
    save_registry(cfg, reg)


def _full_chain_finish(cfg, case_id, status, failures=None, exit_code=None):
    """链终点统一收口:status/exit_code 落注册表 + RUNNING 释放。"""
    rec = get_case_record(cfg, case_id)
    reg = load_registry(cfg)
    r = reg.get(case_id) or rec
    r["status"] = status
    r["updated"] = now_iso()
    if failures is not None:
        r["gate_failures"] = failures
    if exit_code is not None:
        r["exit_code"] = exit_code
    reg[case_id] = r
    save_registry(cfg, reg)
    RUNNING.pop(case_id, None)
    _session_purge(cfg, case_id)  # T17：consent『仅本次会话（跑完即删）』


def _mask_npz_name(prefix, case):
    """run_all 命名规则（run_all.py L743-745 同款）：pA+v5 无后缀；pA 其他 mask_full-<case>；
    其他前缀 mask_full-<prefix>-<case>。"""
    if prefix == "pA":
        return "mask_full.npz" if case == "v5" else f"mask_full-{case}.npz"
    return f"mask_full-{prefix}-{case}.npz"


def _step2_mask_npz(rec):
    """本例 mask npz：state out_dir/step2 优先，共享 out/step2 兜底（内置病例历史落点）。"""
    name = _mask_npz_name(rec.get("prefix"), rec.get("case_name"))
    for root in (os.path.join(rec.get("out_dir") or "", "step2"), SHARED_STEP2):
        p = os.path.join(root, name)
        if os.path.isfile(p):
            return p
    return ""


def _step2_case_dir(rec):
    """本例主算例目录（constant/ 存在才认）：state 优先,共享 out/step2 兜底。"""
    cn = f"P0-OF-case-{rec.get('prefix')}-{rec.get('case_name')}"
    for root in (os.path.join(rec.get("out_dir") or "", "step2"), SHARED_STEP2):
        d = os.path.join(root, cn)
        if os.path.isdir(os.path.join(d, "constant")):
            return d
    return ""


def _auto_zwin(mask_npz, main_metrics=None, dicom_dir=""):
    """占位档层位窗口(T16 接线口径,规格书 pA 实证复现):
    zwin 起点 = 本例入口层(主算例 metrics 的 inlet 面质心 z / DICOM 全分辨率层距),
    长度 21mm(pA:0.35mm×60 层;zwin=[100,160] 起点恰为入口层 96-102,逐位吻合)。
    pB 入口 z=24.6mm → zwin=[82,152](入口上方的鼻瓣-下鼻甲区,气流必经)。
    回退:metrics/DICOM 不可用时退 35%-55% 有效带启发(如实记录,不臆断)。"""
    import glob as _glob
    import numpy as np
    try:
        _pm = json.load(open(main_metrics, encoding="utf-8")) \
            if main_metrics and os.path.isfile(main_metrics) else None
        _pp = (_pm or {}).get("patches") or {}
        zs = [float(_pp[s]["face_centre_mm"][2])
              for s in ("inletL", "inletR") if _pp.get(s)]
        import pydicom as _pydicom
        _dcm = sorted(_glob.glob(os.path.join(dicom_dir, "*.dcm")))
        _dz = 0.0
        if len(_dcm) >= 2:
            _a = _pydicom.dcmread(_dcm[0], stop_before_pixels=True)
            _b = _pydicom.dcmread(_dcm[1], stop_before_pixels=True)
            _dz = abs(float(_b.ImagePositionPatient[2])
                      - float(_a.ImagePositionPatient[2]))
        if zs and _dz > 0:
            z_in = sum(zs) / len(zs)
            zlo = int(round(z_in / _dz))
            zhi = zlo + int(round(21.0 / _dz))
            _note = ("入口层驱动:z_in=%.2fmm dz=%.3fmm -> [%d,%d]"
                     % (z_in, _dz, zlo, zhi))
            return zlo, zhi, _note
    except Exception:  # noqa: BLE001
        pass
    d = np.load(mask_npz)
    area = np.asarray(d["mask"]).sum(axis=(1, 2))
    nz = int(np.nonzero(area > 0)[0][-1]) + 1
    return int(round(nz * 0.35)), int(round(nz * 0.55)), "回退:35%-55% 有效带启发"


def _run_wsl_allrun_monitored(case_dir, out_dir, tag, stall_limit=1200):
    """WSL Allrun + 步数心跳看护（与 solve_thread 同口径 20 分钟）。
    返回 (rc, last_time)。"""
    wsl_case = to_wsl_path(case_dir)
    append_progress(out_dir, f"[W] {tag} WSL Allrun 启动：{wsl_case}")
    log_path = os.path.join(case_dir, "log.simpleFoam")
    cmd = f"cd {shlex.quote(wsl_case)} && ./Allrun"
    try:
        proc = subprocess.Popen(["wsl", "bash", "-lc", cmd],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
    except Exception as e:  # noqa: BLE001
        append_progress(out_dir, f"[W] !!! {tag} WSL 启动异常：{e!r}")
        return (-999, None)
    last_step, stall = -1.0, 0
    while proc.poll() is None:
        time.sleep(30)
        step = parse_last_time(log_path)
        if step is not None and step > last_step:
            last_step = step
            stall = 0
            append_progress(out_dir, f"[W] {tag} 求解进行：Time = {step:g}")
        else:
            stall += 30
            if stall >= stall_limit:
                proc.kill()
                proc.wait()
                if os.path.isfile(log_path):
                    shutil.copy2(log_path,
                                 os.path.join(out_dir, "allrun_stalled_archive.log"))
                append_progress(out_dir, f"[W] !!! {tag} 看护触发：{stall_limit}s 无步数"
                                "增长——已终止并归档日志")
                return (-998, parse_last_time(log_path))
    rc = proc.poll()
    append_progress(out_dir, f"[W] {tag} Allrun 结束（exit {rc}）")
    return (rc, parse_last_time(log_path))


def _run_backend_monitored(case_dir, out_dir, tag, stall_limit=1200):
    """M3 后端分派：custom=FlowScope 心跳看护；openfoam=WSL Allrun。"""
    if SB.resolve_backend() == "custom":
        return SB.run_custom_monitored(
            case_dir, case_dir, tag=tag, stall_limit=max(stall_limit, 7200),
            progress=lambda m: append_progress(out_dir, "[W] " + m))
    rc, _t = _run_wsl_allrun_monitored(case_dir, out_dir, tag,
                                       stall_limit=stall_limit)
    return rc


def _solve_and_post(cfg, case_dir, out_dir, tag):
    """求解 + 后处理（custom 后端由适配层直接产出 metrics.json）。
    返回 ``(rc, metrics_path)``。"""
    backend = SB.resolve_backend()
    rc = _run_backend_monitored(case_dir, out_dir, tag)
    if rc != 0:
        return rc, ""
    if backend == "custom":
        mp = os.path.join(case_dir, "后处理", "metrics.json")
        return (0, mp) if os.path.isfile(mp) else (-996, "")
    return _run_postcfd(cfg, os.path.join(case_dir, "VTK"),
                        os.path.join(case_dir, "后处理"), tag + " post_cfd",
                        out_dir)


def _run_postcfd(cfg, vtk_dir, post_dir, tag, out_dir, timeout=1800):
    """post_cfd 后处理（nu=1.8e-5 审计 Y2 口径显式传入;几何单位 m）。
    返回 (rc, metrics_path)。"""
    pc = post_cfd_path(cfg)
    if not pc:
        append_progress(out_dir, f"[W] !!! {tag} post_cfd.py 未定位"
                        "（P0_POST_CFD 或 ct_base 推导）——环境缺失")
        return (-997, "")
    os.makedirs(post_dir, exist_ok=True)
    cmd = [_pipeline_python(), "-X", "utf8", pc, vtk_dir, "--out", post_dir,
           "--rho", "1.2", "--nu", "1.8e-5", "--geom-units", "m"]
    append_progress(out_dir, "[W] $ " + " ".join(cmd))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        rc = r.returncode
    except Exception as e:  # noqa: BLE001
        append_progress(out_dir, f"[W] !!! {tag} post_cfd 异常：{e!r}")
        return (-999, "")
    mp = os.path.join(post_dir, "metrics.json")
    if rc == 0 and os.path.isfile(mp):
        append_progress(out_dir, f"[W] {tag} post_cfd 完成——metrics.json 就绪")
        return (0, mp)
    append_progress(out_dir, f"[W] !!! {tag} post_cfd 失败（exit {rc}）")
    return (rc, "")


def full_chain_thread(cfg, case_id, zlo=None, zhi=None):
    """T16 全自动链（后台线程）：
    主算例（结果就绪则复用；否则几何补齐→后端求解→后处理）
    → step3 占位算例×3（含占位体 STL）→ 逐个后端求解→后处理×3
    → 契约占位档汇编（run_all assemble_contract + 占位 metrics）
    → step5 导出（F3 六板门禁照常把关）→ 舞台化。
    红线：run_all/step5 的契约与门禁逻辑一行不动——档案齐了闸门自然放行。"""
    rec = get_case_record(cfg, case_id)
    out_dir = rec.get("out_dir") or ""
    try:
        _full_chain_impl(cfg, case_id, rec, out_dir, zlo, zhi)
    except Exception as e:  # noqa: BLE001
        append_progress(out_dir, f"[W] !!! 全自动链异常：{e!r}")
        _full_chain_finish(cfg, case_id, "failed",
                           [f"全自动链异常：{e!r}"], exit_code=-999)


def _full_chain_impl(cfg, case_id, rec, out_dir, zlo, zhi):
    prefix, case = rec.get("prefix"), rec.get("case_name")
    letter = (prefix or "X")[-1].upper()
    main_case = f"P0-OF-case-{prefix}-{case}"
    res_dir = os.path.join(RESULTS_ROOT, f"P0-result-{case_id}-v1")
    append_progress(out_dir, "[W] T16 全自动链启动：主算例（复用/求解）→ step3 占位×3"
                    " → WSL 求解×3 → post_cfd×3 → 契约汇编 → step5 导出")
    _mark_full_chain(cfg, case_id, stage="S5_main", cases_total=4, cases_done=0)

    def _fail(status, failures, exit_code):
        append_progress(out_dir, "[W] !!! 全自动链中止：" + failures[0])
        _full_chain_finish(cfg, case_id, status, failures, exit_code)
        raise SystemExit(0)

    # ---- S5 主算例：结果就绪则复用（pB 路径）；否则几何补齐→Allrun→post_cfd ----
    main_vtu = RA.find_vtu(res_dir) if os.path.isdir(res_dir) else None
    main_metrics = os.path.join(res_dir, "后处理", "metrics.json")
    if main_vtu and os.path.isfile(main_metrics):
        append_progress(out_dir, f"[W] 主算例结果复用：{res_dir}"
                        "（VTK/internal.vtu + 后处理/metrics.json 就绪,不重跑）")
        _mark_full_chain(cfg, case_id, cases_done=1)
    else:
        case_dir = _step2_case_dir(rec)
        if not case_dir:
            append_progress(out_dir, "[W] 几何缺失——run_all --solve skip 补齐 S0-S3 ...")
            cmd = [_pipeline_python(), "-X", "utf8", RUN_ALL,
                   "--dicom-dir", rec.get("dicom_dir") or "",
                   "--case-prefix", prefix, "--case", case,
                   "--solve", "skip", "--out-root", out_dir]
            if rec.get("anatomy_inclusion"):
                cmd += ["--allow-anatomy-inclusion"]
            append_progress(out_dir, "[W] $ " + " ".join(cmd))
            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            if r.returncode != 0:
                _fail("blocked", [f"几何生成失败（run_all exit {r.returncode}），"
                                  "详见进度日志"], r.returncode)
            case_dir = _step2_case_dir(rec)
        if not case_dir:
            _fail("failed", ["主算例目录缺失（run_all 后仍未找到 constant/）"], 2)
        # 拷贝到结果目录后原地求解（产物与档案同构落位）
        if os.path.isdir(res_dir):
            shutil.rmtree(res_dir)
        shutil.copytree(case_dir, res_dir)
        rc2, main_metrics = _solve_and_post(cfg, res_dir, out_dir,
                                             "算例 1/4 " + main_case)
        if rc2 != 0:
            _fail("failed", [f"主算例求解/后处理失败（backend="
                             f"{SB.resolve_backend()}，exit {rc2}）；"
                             f"日志：{os.path.join(res_dir, 'solver.log')}"], rc2)
        main_vtu = RA.find_vtu(res_dir)
        if not main_vtu:
            _fail("failed", ["主算例求解完成但 VTK/internal.vtu 缺失"], 2)
        _mark_full_chain(cfg, case_id, cases_done=1)

    # ---- S7 step3 占位算例生成（幂等：QC json 在则跳过） ----
    _mark_full_chain(cfg, case_id, stage="S7_step3")
    mask_npz = _step2_mask_npz(rec)
    if not mask_npz:
        _fail("failed", [f"mask npz 缺失（step2 未产出 {_mask_npz_name(prefix, case)}）"], 2)
    # step5 的 mask 定位固定在 HERE/out/step2——上传病例 npz 在 state 目录时同步一份
    shared_npz = os.path.join(SHARED_STEP2, os.path.basename(mask_npz))
    if os.path.abspath(mask_npz) != os.path.abspath(shared_npz) and not os.path.isfile(shared_npz):
        os.makedirs(SHARED_STEP2, exist_ok=True)
        shutil.copy2(mask_npz, shared_npz)
        append_progress(out_dir, f"[W] mask npz 已同步至 step5 定位目录：{shared_npz}")
    step3_out = os.path.join(out_dir, "step3")
    qc_name = "narrowing_qc.json" if prefix == "pA" else f"narrowing_qc-{prefix}.json"
    nqc_path = os.path.join(step3_out, qc_name)
    if os.path.isfile(nqc_path):
        append_progress(out_dir, f"[W] step3 QC 已存在,跳过生成：{nqc_path}")
    else:
        _zwin_note = ""
        if zlo is None or zhi is None:
            zlo, zhi, _zwin_note = _auto_zwin(mask_npz, main_metrics,
                                              rec.get("dicom_dir") or "")
        append_progress(out_dir, "[W] zwin口径：" + _zwin_note)
        # A2 参考入口面积：本例主算例实测（case_stats 优先,主算例 metrics 兜底）
        ref_l = ref_r = None
        _cs_p = ""
        for _root in (os.path.join(rec.get("out_dir") or "", "step2"), SHARED_STEP2):
            _p = os.path.join(_root, f"case_stats-{prefix}-{case}.json")
            if os.path.isfile(_p):
                _cs_p = _p
                break
        if _cs_p:
            _cs = json.load(open(_cs_p, encoding="utf-8"))
            ref_l = _cs.get("inletL", {}).get("area_mm2")
            ref_r = _cs.get("inletR", {}).get("area_mm2")
        if not (ref_l and ref_r):
            _pm = json.load(open(main_metrics, encoding="utf-8")) \
                if os.path.isfile(main_metrics) else {}
            _pp = _pm.get("patches") or {}
            ref_l = _pp.get("inletL", {}).get("area_mm2")
            ref_r = _pp.get("inletR", {}).get("area_mm2")
        append_progress(out_dir, f"[W] step3 占位算例生成（zlo={zlo}, zhi={zhi}, "
                        f"npz={mask_npz}, A2参考={ref_l}/{ref_r} mm2）...")
        cmd3 = [_pipeline_python(), "-X", "utf8", STEP3,
                "--npz", mask_npz,
                "--dicom-dir", rec.get("dicom_dir") or "",
                "--case-prefix", prefix,
                "--out", step3_out,
                "--zlo", str(int(zlo)), "--zhi", str(int(zhi)),
                "--export-implant-stl"]
        if ref_l and ref_r:
            cmd3 += ["--ref-inlet-l", str(ref_l), "--ref-inlet-r", str(ref_r)]
        append_progress(out_dir, "[W] $ " + " ".join(cmd3))
        r = subprocess.run(cmd3, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=3600)
        if r.returncode != 0 or not os.path.isfile(nqc_path):
            _fail("failed", [f"step3 占位算例生成失败（exit {r.returncode}）——"
                              "D1/D2/D3 断言或 QC 未全过,详见进度日志"], r.returncode)
        append_progress(out_dir, "[W] step3 占位算例×3 生成完成（P0-OF-case-"
                        + prefix + "-v6n1/2/3）")

    # ---- S8 占位算例逐个求解 + post_cfd（幂等：结果目录后处理 metrics 在则跳过） ----
    import json as _json
    nqc = _json.load(open(nqc_path, encoding="utf-8"))
    if not nqc.get("all_required_true"):
        _fail("blocked", ["step3 QC 未全过（all_required_true=false）——占位几何存在"
                          "断言级问题,按红线停工"], 2)
    ph_dirs = []
    for n in (1, 2, 3):
        _mark_full_chain(cfg, case_id, stage=f"S8_solve_{n}_of_3")
        ph_name = f"P0-OF-case-{prefix}-v6n{n}"
        ph_src = os.path.join(step3_out, ph_name)
        ph_res = os.path.join(RESULTS_ROOT, f"P0-result-{case_id}-v6n{n}")
        ph_metrics = os.path.join(ph_res, "后处理", "metrics.json")
        if os.path.isfile(ph_metrics):
            append_progress(out_dir, f"[W] 占位算例 {n}/3 已有结果,复用：{ph_res}")
        else:
            if not os.path.isdir(os.path.join(ph_src, "constant")):
                _fail("failed", [f"占位算例目录缺失：{ph_src}"], 2)
            if os.path.isdir(ph_res):
                shutil.rmtree(ph_res)
            shutil.copytree(ph_src, ph_res)
            rc2, ph_metrics = _solve_and_post(cfg, ph_res, out_dir,
                                              f"算例 {n+1}/4 {ph_name}")
            if rc2 != 0:
                _fail("failed", [f"占位算例 {ph_name} 求解/后处理失败"
                                 f"（backend={SB.resolve_backend()}，exit {rc2}）"], rc2)
            append_progress(out_dir, f"[W] 占位算例 {n}/3 求解+后处理完成（{ph_name}）")
        ph_dirs.append((ph_name, ph_metrics, nqc["levels"][n - 1]))
        _mark_full_chain(cfg, case_id, cases_done=1 + n)

    # ---- S9 契约占位档汇编 + step5 导出（幂等：viewer_data.js 在则跳过） ----
    _mark_full_chain(cfg, case_id, stage="S9_contract_step5")
    vd_path = os.path.join(out_dir, "step5", "viewer_data.js")
    if os.path.isfile(vd_path):
        append_progress(out_dir, f"[W] step5 导出已存在,跳过：{vd_path}")
    else:
        contract, missing = RA.assemble_contract(
            _json.load(open(main_metrics, encoding="utf-8")), letter, case)
        dps_meta = [round(float(contract["metrics"]["dP_baseline_Pa"]), 2)]
        vols_curve = [0.0]
        for n in (1, 2, 3):
            ph_name, ph_metrics, level = ph_dirs[n - 1]
            t = _json.load(open(ph_metrics, encoding="utf-8"))["totals"]
            dp = float(t["dP_Pa"])
            contract["metrics"][f"dP_{n}mm_Pa"] = round(dp, 1)
            dps_meta.append(round(dp, 2))
            vols_curve.append(round(float(level["implant_vol_cm3"]), 3))
        contract["curve"] = {"volumes_cm3": vols_curve, "dP_Pa": dps_meta,
                             "band_Pa": [BAND_DP["lo"], BAND_DP["hi"]]}
        contract["_source"] = ("本例后处理 metrics.json（主+占位×3；"
                               "run_all 汇编 + T16 占位档接线）")
        contract_pp = os.path.join(out_dir, "postprocess")
        os.makedirs(contract_pp, exist_ok=True)
        contract_path = os.path.join(contract_pp, f"contract-{prefix}-{case}.json")
        with open(contract_path, "w", encoding="utf-8") as f:
            _json.dump(contract, f, ensure_ascii=False, indent=1)
        append_progress(out_dir, f"[W] 契约占位档汇编完成 → {contract_path}"
                        f"（dP_Pa={dps_meta}, volumes_cm3={vols_curve}）")
        cmd5 = [_pipeline_python(), "-X", "utf8", STEP5,
                "--dicom-dir", rec.get("dicom_dir") or "",
                "--case-prefix", prefix, "--case", case,
                "--vtu", main_vtu,
                "--metrics-json", contract_path,
                "--out-dir", os.path.join(out_dir, "step5"),
                "--write-mode", "full",
                "--ph-dir", step3_out]
        append_progress(out_dir, "[W] step5 查看器数据导出（full 模式,F3 六板门禁把关）...")
        append_progress(out_dir, "[W] $ " + " ".join(cmd5))
        r = subprocess.run(cmd5, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=3600)
        if r.returncode != 0 or not os.path.isfile(vd_path):
            boards = os.path.join(out_dir, "step5",
                                 f"six_boards_{prefix}-{case}.json")
            detail = ""
            if os.path.isfile(boards):
                b = _json.load(open(boards, encoding="utf-8"))
                bad = {k: v for k, v in (b.get("gates") or {}).items()
                       if v.get("pass") is False}
                if bad:
                    detail = "；F3 门禁 FAIL：" + ", ".join(bad)
            _fail("blocked", [f"step5 导出中止（exit {r.returncode}）{detail}"
                              "——六板报表：" + boards + "（闸门红线,如实上报）"], 2)

    # ---- S10 舞台化 + 完成 ----
    _mark_full_chain(cfg, case_id, stage="S10_stage")
    reg = load_registry(cfg)
    r = reg.get(case_id) or rec
    staged = stage_viewer_if_exported(cfg, r)
    if staged:
        append_progress(out_dir, "[W] 查看器数据已舞台化（webapp/cases/"
                        + case_id + "/viewer_single.html）")
    append_progress(out_dir, "[W] 全自动链完成：结果档案完整"
                    "——契约闸门按文件判据自然放行" + ("" if staged else "（注意：舞台化未命中）"))
    _full_chain_finish(cfg, case_id, "done", exit_code=0)


# ---------------------------------------------------------------- 建病例（目录导入 / 网页上传 共用链）
MAX_UPLOAD_MIB = 2048  # R-11 上传契约：单份 CT 体积上限 2 GiB（2048 MiB）


def _safe_upload_name(filename):
    """上传文件名安全化：只取 basename（绝对路径/子路径穿越一律降级为纯文件名）。"""
    return os.path.basename(str(filename or "").replace("\\", "/").strip())


def _register_case(cfg, dicom_dir, prefix, case_name, label, kind, case_id_val,
                   anatomy_inclusion=False, extra_rec=None, consent=None):
    """建病例公共链（POST /api/case 与 POST /api/upload 共用）：
    注册表登记 → PII 闸门（run_all 同款 scan_pii）→ DICOM 头普查 → step1 气道分割。
    返回 (flask_response, status_code)；与既有 POST /api/case 行为一致（逐条同码）。

    consent（T17，可选）：弹窗三问的规范字段（parse_consent_fields 产物）——
    提供即落 consent_record.json 到本例输出目录；缺省行为与 T16 完全一致
    （不落记录 → 云形态按 fail-closed 拦截，本地形态不受影响）。
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
    if extra_rec:
        rec.update(extra_rec)  # K3-M4：多序列病例登记原始上传目录，供 DELETE 一并清理
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

    # ---- ② T17 弹窗授权记录落档（consent_record.json，与产物同目录） ----
    # 落档先于 PII 判定分支：PII FAIL 的病例同样留证（pii_scan=fail），
    # 由 evaluate_consent 在云形态如实拦截——弹窗授权不得放行 PII 拦截。
    if consent:
        try:
            crec = build_consent_record(rec["case_id"], consent,
                                        pii_scan="pass" if pii["pass"] else "fail")
            cp = save_consent_record(rec, crec)
            rec["consent"] = consent_summary(rec)
            _consent_audit(cfg, {"ts": now_iso(), "event": "consent_recorded",
                                 "case_id": rec["case_id"],
                                 "data_subject": crec["data_subject"],
                                 "processing_scope": crec["processing_scope"],
                                 "retention": crec["retention"],
                                 "pii_scan": crec["pii_scan"]})
            append_progress(out_dir, "[W] consent_record.json 落档：" + cp +
                            "（数据主体=%s 处理位置=%s 保留=%s）"
                            % (crec["data_subject"], crec["processing_scope"],
                               crec["retention"]))
        except OSError as e:  # noqa: BLE001
            append_progress(out_dir, "[W] !!! consent_record.json 落档失败：%r"
                            "（授权记录缺失 → 云形态将按 fail-closed 拦截）" % (e,))

    if not pii["pass"]:
        rec.update(status="blocked", gate="PII 头扫描（run_all 同款闸门）",
                   gate_failures=[digest_pii_fail(f) for f in pii.get("fails", [])][:10],
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


# ---------------------------------------------------------------- 上传序列自动识别  [SERIES-AUTOSELECT]
# 用户常选中含多个序列的父目录 → basename 拍平后多序列混叠 → z 非单调被层序断言拦。
# 这里按 SeriesInstanceUID 分组，自动挑"软组织窗/标准核 > 层厚薄 > z 覆盖长 > 文件多"的序列，
# 只把该序列文件移入独立病例目录，其余留在 uploads 原处作证据；单序列目录行为不变（分组=1 直通）。
_SERIES_RANK = {"soft": 2, "unknown": 1, "bone": 0}
_IMG_Z_RE = re.compile(r"^b([5-9]\d|100)", re.I)


def _classify_series_window(desc, kernel):
    """序列窗口分类：软组织窗/标准核 -> 'soft'；骨/锐算法 -> 'bone'；其余 -> 'unknown'。"""
    d = (desc or "").lower()
    k = (kernel or "").strip().lower()
    soft = bone = False
    if any(t in d for t in ("soft", "sft", "软组织", "平滑", "标准")):
        soft = True
    if any(t in d for t in ("bone", "骨", "sharp", "锐", "detail", "edge", "high res")):
        bone = True
    if "c-" in d:
        bone = True
    if k:
        if any(t in k for t in ("soft", "sft", "smooth", "stnd", "std", "standard",
                                "fc0", "fc1", "fc2", "fc3", "b31", "b30", "b40", "b45")):
            soft = True
        if (k in ("b", "bone", "c", "c-", "cd") or "bone" in k
                or k.startswith("c-") or bool(_IMG_Z_RE.match(k))):
            bone = True
    if soft:
        return "soft"
    if bone:
        return "bone"
    return "unknown"


def _scan_series_groups(dicom_dir):
    """按 SeriesInstanceUID 分组扫描 dicom_dir 下的 .dcm（stop_before_pixels）。
    任一文件无法解析 -> 返回 None（交回原 PII/头抽检流程，保持既有闸门行为）。"""
    try:
        names = sorted(f for f in os.listdir(dicom_dir) if f.lower().endswith(".dcm"))
    except OSError:
        return None
    if len(names) < 2:
        return None
    groups = {}
    for fn in names:
        fp = os.path.join(dicom_dir, fn)
        try:
            ds = RA.pydicom.dcmread(fp, stop_before_pixels=True, force=True)
        except Exception:  # noqa: BLE001
            return None
        uid = str(getattr(ds, "SeriesInstanceUID", "") or "").strip() or "(no-series-uid)"
        g = groups.get(uid)
        if g is None:
            g = {"series_uid": uid, "files": [], "modalities": set(),
                 "descriptions": set(), "kernels": set(), "thicknesses": [], "zs": []}
            groups[uid] = g
        g["files"].append(fp)
        g["modalities"].add(str(getattr(ds, "Modality", "") or "").strip())
        g["descriptions"].add(str(getattr(ds, "SeriesDescription", "") or "").strip())
        g["kernels"].add(str(getattr(ds, "ConvolutionKernel", "") or "").strip())
        st = getattr(ds, "SliceThickness", None)
        if st is not None:
            try:
                g["thicknesses"].append(float(st))
            except (TypeError, ValueError):
                pass
        ipp = getattr(ds, "ImagePositionPatient", None)
        if ipp is not None and len(ipp) >= 3:
            try:
                g["zs"].append(float(ipp[2]))
            except (TypeError, ValueError):
                pass
    out = []
    for uid, g in groups.items():
        th = min(g["thicknesses"]) if g["thicknesses"] else None
        zs = sorted(g["zs"]) if g["zs"] else []
        zmin = zs[0] if zs else None
        zmax = zs[-1] if zs else None
        mono = all(zs[i] < zs[i + 1] for i in range(len(zs) - 1)) if len(zs) >= 2 else False
        desc = next((s for s in sorted(g["descriptions"]) if s), "") or ""
        kern = next((s for s in sorted(g["kernels"]) if s), "") or ""
        cov = (zmax - zmin) if (zmin is not None and zmax is not None) else 0.0
        out.append({
            "series_uid": uid,
            "files": g["files"],
            "file_count": len(g["files"]),
            "modality": next((s for s in sorted(g["modalities"]) if s), "") or "",
            "description": desc,
            "kernel": kern,
            "thickness": th,
            "z_min": zmin, "z_max": zmax,
            "z_coverage": cov,
            "z_monotonic": mono,
            "window": _classify_series_window(desc, kern),
        })
    return out


def _series_sort_key(g):
    """评分：软组织窗/标准核 > 层厚薄 > z 覆盖长 > 文件多（> z 单调为末位微调）。"""
    th = g["thickness"] if g["thickness"] is not None else 1e9  # 未知层厚排最后
    return (_SERIES_RANK.get(g["window"], 1), -th, g["z_coverage"],
            g["file_count"], 1 if g["z_monotonic"] else 0)


def _autoselect_upload_series(up_dir):
    """扫描上传目录；多序列 -> 自动挑最优序列，移入独立病例目录。
    返回 (case_dir, message, series_list) 或 None（单序列/不可解析/最优不足 2 张 -> 走原流程）。"""
    groups = _scan_series_groups(up_dir)
    if not groups or len(groups) <= 1:
        return None
    # K3-M1：评分只考虑 CT 序列（多模态混传时防非 CT 序列胜出）；
    # 全部非 CT -> 回退原评分行为（不过滤），并在 message 说明"未发现 CT 序列"。
    ct_groups = [g for g in groups if g["modality"] == "CT"]
    scored = ct_groups if ct_groups else groups
    best = max(scored, key=_series_sort_key)
    if best["file_count"] < 2:  # 最优序列也要够建病例（>=2 张），否则交回原流程
        return None
    # 移动最优序列文件到独立目录（其余留在 up_dir 作证据）
    sel_dir = up_dir + "-sel"
    n = 2
    while os.path.exists(sel_dir):
        sel_dir = f"{up_dir}-sel{n}"
        n += 1
    os.makedirs(sel_dir, exist_ok=True)
    for fp in best["files"]:
        shutil.move(fp, os.path.join(sel_dir, os.path.basename(fp)))
    series_list = sorted(groups, key=_series_sort_key, reverse=True)
    lines = []
    for g in series_list:
        th = f"{g['thickness']:g}" if g["thickness"] is not None else "?"
        win = {"soft": "软组织窗", "bone": "骨窗", "unknown": "窗口未知"}[g["window"]]
        lines.append(f"{g['description'] or '(无序列描述)'}（层厚 {th} mm，{g['file_count']} 张，{win}）")
    bth = f"{best['thickness']:g}" if best["thickness"] is not None else "?"
    message = (f"发现 {len(groups)} 个序列：" + "；".join(lines) +
               f"。已自动选用：{best['description'] or best['kernel'] or '(无描述)'}"
               f"（层厚 {bth} mm，{best['file_count']} 张）")
    if not ct_groups:  # K3-M1：全部非 CT 的回退说明（评分未过滤）
        message += "。⚠️ 未发现 CT 序列（各序列 Modality 均非 CT），已按原评分规则回退选用"
    info = [{
        "description": g["description"], "kernel": g["kernel"],
        "thickness": g["thickness"], "file_count": g["file_count"],
        "window": g["window"], "modality": g["modality"], "chosen": g is best,
    } for g in series_list]
    return sel_dir, message, info


def _attach_series_note(resp, series_msg, series_list):
    """把序列识别结论注入注册响应（message 前缀 + series_selection 结构化字段）。"""
    try:
        data = resp.get_json()
    except Exception:  # noqa: BLE001
        data = None
    if isinstance(data, dict):
        data["series_selection"] = {"message": series_msg, "series": series_list}
        base = data.get("message") or ""
        data["message"] = series_msg + ("  " + base if base else "")
        resp.set_data(json.dumps(data, ensure_ascii=False))
        resp.mimetype = "application/json"
    return resp


def _register_path_case(cfg, dicom_dir, source_label="服务器目录导入", extra_rec=None,
                        consent=None):
    """按 CT 目录建病例：R-11 契约校验（≥2 个 .dcm / ≤2048 MiB）→ 分配前缀 → _register_case。
    供 POST /api/case（source=path）与 POST /api/upload（网页直接上传）共用。
    consent（T17）：弹窗三问规范字段，透传给 _register_case 落档。
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
                          f"上传病例 {prefix}（{source_label}）", "upload", prefix,
                          extra_rec=extra_rec, consent=consent)


# ---------------------------------------------------------------- Flask app
# ---------- 操作日记 oplog + 一键报障（三角色前端批 R5，2026-10-19） ----------
# 边界：actor 是客户端声称（actor_source=client-claim），永不做鉴权——
# 界面角色只是观看方式，真正的数据边界是服务端硬闸（见关于本项目边界声明卡）。
_PATH_RE = re.compile(r'[A-Za-z]:\\[^\s"\',;)}\]\[]+|[A-Za-z]:/[^\s"\',;)}\]\[]+')

def mask_fatal_pii_values(text):
    """oplog/bugreport 写盘前必过：把本机绝对路径替换为 <path>。返回 (masked, n_hits)。
    只掩码路径——不猜姓名；患者数据宪法下宁少掩不多猜。"""
    s = str(text or "")
    out, n = _PATH_RE.subn("<path>", s)
    return out, n

def _state_subdir(cfg, name):
    d = os.path.join(cfg.state_dir, name)
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d

def _read_manifest_tail(cfg, n=200):
    """manifest 尾部 n 行（本机运行时日志；不含病例内容）。找不到返回 None。"""
    sd = getattr(cfg, "state_dir", "") or ""
    cand = os.path.join(sd, "manifest-progress.json")
    if not os.path.exists(cand):
        alts = sorted(glob.glob(os.path.join(sd, "manifest*.json")), key=os.path.getmtime, reverse=True)
        cand = alts[0] if alts else None
    if not cand or not os.path.exists(cand):
        return None
    try:
        with io.open(cand, encoding="utf-8") as f:
            return "\n".join(f.read().splitlines()[-n:])
    except OSError:
        return None

def purge_oplog_bugreports(cfg, days, dry_run=True):
    """按 consent days:N 语义清理超期 oplog/bugreports。
    默认 dry_run=True（只计数打印，不删）——自动删除患者本机数据须显式接线。"""
    import time as _t
    cutoff = _t.time() - float(days) * 86400.0
    n_del = n_keep = 0
    for sub in ("oplog", "bugreports"):
        d = _state_subdir(cfg, sub)
        for fn in os.listdir(d):
            p = os.path.join(d, fn)
            try:
                if os.path.getmtime(p) < cutoff:
                    n_del += 1
                    if not dry_run:
                        os.remove(p)
                else:
                    n_keep += 1
            except OSError:
                continue
    return {"would_delete": n_del, "keep": n_keep, "dry_run": dry_run}

def build_app(cfg):
    app = Flask(__name__, static_folder=WEBAPP_DIR, static_url_path="/static")
    app.config["SERVER_CONFIG"] = cfg

    # LT-8 启动自检：登记表里 status=done 但结果档案缺失的"陈旧病例"打 [W] 日志
    # （只标记不删数据；/api/cases 每次请求按需重算，不会因为标记而误伤后来补回的结果）
    scan_stale_cases(cfg)

    @app.before_request
    def static_patient_gate():
        """云形态（only_synthetic）下，患者衍生静态数据直通一律 403（step5 审计 Medium 修复）"""
        from flask import request as _rq, current_app as _ca
        p = _rq.path or ""
        sc = (_ca.config.get("SERVER_CONFIG") if _ca else None)
        if sc is not None and getattr(sc, "only_synthetic", False) and (p.startswith("/static/cases/") or p.startswith("/static/models/") or p.startswith("/static/plus/")):
            return jsonify({"error": "云形态不提供患者衍生数据文件"}), 403
        return None

    

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

    @app.route("/api/compare")
    def api_compare():
        """两例对比聚合（pA 患者 / pB 患者 + 文献正常范围参考带）——前端一屏并排对比用。

        两例路径白名单硬编码（见模块级 COMPARE_ORDER）；每例只读既有产物，
        缺失/解析失败该例 ready=False（不炸整端）。云形态（only_synthetic）503——
        与其它真实患者数据端点同款数据边界硬闸（修订1/R-03）。
        """
        if cfg.only_synthetic:
            return jsonify({"error":
                            "数据边界硬闸（修订1/R-03）：云形态仅合成 demo 数据，"
                            "真实患者两例对比不开放（HTTP 503）"}), 503
        return jsonify({
            "mode": cfg.mode,
            "only_synthetic": cfg.only_synthetic,
            "order": list(COMPARE_ORDER),
            "ref_band": dict(COMPARE_REF_BAND),
            "cases": [compare_case_metrics(cid) for cid in COMPARE_ORDER],
            "notes": dict(COMPARE_NOTES, disclaimer=DISCLOSURE),
        })

    @app.route("/models/<case_id>")
    def models_file(case_id):
        """只读 serve 真实鼻腔气道 GLB（白名单 pA/pB；云形态 403，与 /api/results 同款闸）。"""
        if cfg.only_synthetic:
            return jsonify({"error":
                            "数据边界硬闸（限定1/R-03）：云形态仅合成数据，"
                            "真实气道路由在云形态不可访问（HTTP 403）。"}), 403
        p = case_model_path(case_id)
        if not p:
            abort(404)
        return send_file(p, mimetype="model/gltf-binary", as_attachment=False,
                         download_name=f"airway_{case_id}.glb")

    @app.route("/api/health")
    def api_health():
        return jsonify({
            "status": "ok", "mode": cfg.mode,
            "only_synthetic": cfg.only_synthetic,
            "presenter": cfg.presenter,
            "ct_base_configured": bool(cfg.ct_base),
            "consent_workflow": CONSENT_PROMPT_VERSION,
            "consent_disclaimer": CONSENT_DISCLAIMER,
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
                "stale": False,
                "dicom_label": d.get("dicom_label", ""),
                "presenter_only": bool(rec.get("presenter_only")) and not cfg.presenter,
                "viewer_available": _viewer_available(cfg, rec),
                "model_available": (not cfg.only_synthetic) and bool(case_model_path(cid)),
                "viewer_block_reason": _viewer_block_reason(cfg, rec),
                "results_available": case_results_available(cfg, cid),
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
            "stale": False,
            "presenter_only": False,
            "viewer_available": True, "viewer_block_reason": "",
            "results_available": case_results_available(cfg, "demo"),
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
            # LT-8 陈旧病例懒校验：status=done 但结果档案缺失 → 不显示绿勾
            # （badge 降级为 pending + stale 标记；只改展示态，不删数据、不动结果）
            results_ok, missing = case_results_status(cid)
            stale = bool(r.get("status") == "done" and not results_ok)
            badge = {"blocked": "⛔", "failed_env": "⚠️",
                     "failed": "❌", "done": "✅", "handover": "📦",
                     "running": "🔄", "segmented": "🔬",
                     "registered": "📝"}.get(r.get("status"), "❓")
            if stale:
                badge = "pending"
            cards.append({
                "case_id": cid, "label": r.get("label") or f"上传病例 {cid}",
                "kind": "upload", "synthetic": False,
                "badge": badge,
                "badge_text": r.get("status"),
                "status": r.get("status"),
                "results_ok": results_ok,
                "stale": stale,
                "stale_reason": "results_missing" if stale else "",
                "missing_results": missing if stale else [],
                "dicom_configured": bool(r.get("dicom_dir")),
                "presenter_only": False,
                "viewer_available": _viewer_available(cfg, r),
                "viewer_block_reason": _viewer_block_reason(cfg, r),
                "results_available": case_results_available(cfg, cid),
                "metrics_summary": _upload_metrics_summary(cfg, r),
                "qc_available": bool(qc_views_for_case(cfg, r)),
                "note": r.get("note") or "",
                "evidence": [],
                "anatomy_inclusion": bool(r.get("anatomy_inclusion")),
                "consent": r.get("consent") or consent_summary(r),
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
            consent, cerr, cfield = _consent_from_form(form)  # T17 弹窗三问（可与上传同送）
            if cerr:
                return jsonify({"error": "弹窗授权字段校验失败：" + cerr,
                                "field": cfield or ""}), 400
            if not dicom_dir or not os.path.isdir(dicom_dir):
                return jsonify({"error": f"CT 目录不存在或不是目录：{dicom_dir}"}), 400
            return _register_path_case(cfg, dicom_dir, source_label="服务器目录导入",
                                       consent=consent)
        else:
            return jsonify({"error": "source 须为 builtin|path|demo"}), 400

    @app.route("/api/case/<case_id>", methods=["DELETE"])
    def api_case_delete(case_id):
        """删除上传病例（仅 kind==upload）：registry 条目 + cases/<cid>/ + uploads 源目录。

        内置/合成病例（pA/pB/pC/demo 等）一律 403——保护赛方与预置数据。
        云形态与其它写端点同款闸（503，代码级禁用）。删除不可恢复。
        """
        if cfg.only_synthetic:
            return jsonify({
                "error": "云形态数据边界（修订1/R-03）：本形态（M2/M3）仅合成 demo 数据，"
                         "删除操作已在代码级禁用（HTTP 503）"}), 503
        if not re.match(r"^[A-Za-z0-9_-]+$", str(case_id)):  # 防路径穿越（防御性）
            return jsonify({"error": f"非法病例标识：{case_id}"}), 400
        reg = load_registry(cfg)
        rec = reg.get(case_id)
        if rec is None or rec.get("kind") != "upload":
            # 非上传病例（内置/合成 pA/pB/pC/demo）一律 403；未知 id → 404
            if get_case_record(cfg, case_id) is not None:
                return jsonify({"error": "内置病例不可删除"}), 403
            return jsonify({"error": f"病例不存在：{case_id}"}), 404
        if case_id in RUNNING:
            return jsonify({"error": f"病例 {case_id} 正在运行中，暂不可删除"}), 409
        removed = []
        rmtree_failed = False

        def _rm_honest(path):
            """K3-M3：rmtree 失败不静默——失败项标注进 removed 并整体 500（R-004 计数诚实）。"""
            nonlocal rmtree_failed
            try:
                rel = os.path.relpath(path, HERE).replace("\\", "/")
            except ValueError:  # 跨盘 relpath 退化用原路径
                rel = path
            try:
                shutil.rmtree(path)
            except OSError as e:
                rmtree_failed = True
                removed.append(f"{rel} (删除失败: {getattr(e, 'strerror', None) or e})")
                return
            removed.append(rel)

        def _rm_under_uploads(path):
            """K3-M4：uploads 源目录清理——realpath 落在 state_dir/uploads 内才删。"""
            if not path:
                return
            try:
                real = os.path.realpath(path)
                up_root = os.path.realpath(os.path.join(cfg.state_dir, "uploads"))
            except OSError:
                return
            if not os.path.isdir(real):
                return
            if not (real == up_root or real.startswith(up_root + os.sep)):
                return  # 越界（registry 异常或服务器目录导入来源）——一律不删
            _rm_honest(real)

        # ① 本例 out_dir（state_dir/cases/<cid>/）
        # K3-M2：先 realpath 包含性校验（registry 被篡改/损坏时防逃逸 state_dir）——不满足 400
        out_dir = rec.get("out_dir") or os.path.join(cfg.state_dir, "cases", case_id)
        if out_dir and not os.path.realpath(out_dir).startswith(
                os.path.realpath(cfg.state_dir) + os.sep):
            return jsonify({"error": "病例目录越界（不在 state_dir 内），拒绝删除："
                            + str(out_dir)}), 400
        if out_dir and os.path.isdir(out_dir):
            _rm_honest(out_dir)
        # ② uploads 源目录（病例记录里存了来源路径才删；限定在 state_dir/uploads 内）
        # K3-M4：多序列病例的原始上传目录 upload_source_dir（含未选中序列/PII 拦截文件）一并清理
        _rm_under_uploads(rec.get("dicom_dir") or "")
        _rm_under_uploads(rec.get("upload_source_dir") or "")
        # ③ registry 条目
        reg.pop(case_id, None)
        save_registry(cfg, reg)
        removed.append("cases.json[" + str(case_id) + "]")
        if rmtree_failed:
            return jsonify({"deleted": case_id, "removed": removed,
                            "error": "部分目录删除失败（Windows 文件锁最常见），"
                                     "详见 removed 列表标注项"}), 500
        return jsonify({"deleted": case_id, "removed": removed})

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
        # T17 弹窗三问：真实数据上传即校验（非法 400 且不落盘；缺省=未弹窗，行为同 T16）
        consent, cerr, cfield = _consent_from_form(request.form)
        if cerr:
            return jsonify({"error": "弹窗授权字段校验失败：" + cerr,
                            "field": cfield or ""}), 400
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
        # ---- 上传序列自动识别（多序列父目录 → 自动挑选最优序列）----  [SERIES-AUTOSELECT]
        sel = None
        try:
            sel = _autoselect_upload_series(up_dir)
        except Exception:  # noqa: BLE001
            sel = None
        if sel:
            case_dir, series_msg, series_list = sel
            # K3-M4：登记原始上传目录（含未选中序列文件），供 DELETE 时一并清理（PII 收口）
            resp = _register_path_case(cfg, case_dir, source_label="网页上传（自动选序列）",
                                       extra_rec={"upload_source_dir": up_dir},
                                       consent=consent)
            return _attach_series_note(resp, series_msg, series_list)
        # 走 source=path 同一条链（PII 闸门 → DICOM 头抽检 → step1）
        return _register_path_case(cfg, up_dir, source_label="网页上传",
                                   consent=consent)

    @app.route("/api/consent", methods=["POST"])
    def api_consent():
        """T17 弹窗授权落档（三问 → consent_record.json 写入病例输出目录）。

        body(JSON)：{case_id, data_subject, source_declaration, authorization_ref,
                     processing_scope, retention}
        用途：① 上传时随表单提交（字段 consent）；② 病例已登记后补录授权。
        云形态不禁用（本端点是授权**元数据**，不是数据上传口——upload/case 仍 501/503）。
        响应含 release 判定（与访问闸门同一函数 evaluate_consent，单一事实源）。
        """
        body = request.get_json(silent=True) or {}
        # 先校验三问（fail-fast），再定位病例——与 /api/upload 的校验次序一致
        fields, err, fld = parse_consent_fields(body)
        if err:
            return jsonify({"error": "弹窗授权字段校验失败：" + err,
                            "field": fld or ""}), 400
        case_id = str(body.get("case_id") or "").strip()
        rec = get_case_record(cfg, case_id) if case_id else None
        if rec is None:
            return jsonify({"error": "病例不存在：" + (case_id or "（空）")}), 404
        if not rec.get("out_dir"):
            return jsonify({"error": "病例无输出目录（合成示例不落授权档）"}), 400
        pii_pass = (rec.get("pii") or {}).get("pass")
        crec = build_consent_record(
            rec["case_id"], fields,
            pii_scan="pass" if pii_pass else ("fail" if pii_pass is False else "pending"))
        try:
            cp = save_consent_record(rec, crec)
        except OSError as e:  # noqa: BLE001
            return jsonify({"error": "consent 记录落档失败：%r（未落档 → 云形态按 "
                                     "fail-closed 拦截）" % (e,)}), 500
        if rec.get("kind") == "upload":  # 仅上传病例进注册表（内置病例不虚增条目）
            reg = load_registry(cfg)
            r = reg.get(rec["case_id"]) or rec
            r["consent"] = consent_summary(rec)
            r["updated"] = now_iso()
            reg[rec["case_id"]] = r
            save_registry(cfg, reg)
        _consent_audit(cfg, {"ts": now_iso(), "event": "consent_recorded",
                             "case_id": rec["case_id"],
                             "data_subject": crec["data_subject"],
                             "processing_scope": crec["processing_scope"],
                             "retention": crec["retention"],
                             "pii_scan": crec["pii_scan"]})
        append_progress(rec.get("out_dir") or "",
                        "[W] consent_record.json 落档（/api/consent）：" + cp)
        ev = evaluate_consent(cfg, rec, crec)
        if ev["basis"] == "local":
            msg = "授权记录已落档（本地形态：真实数据仅本机处理）"
        elif ev["release"]:
            msg = "授权记录已落档：云端处理已获授权（opt-in）——云形态可放行"
        else:
            msg = "授权记录已落档，但本次声明未获放行：" + ev["reason"]
        return jsonify({
            "case_id": rec["case_id"], "schema": CONSENT_SCHEMA,
            "prompt_version": CONSENT_PROMPT_VERSION,
            "record_path": _rel_to_here(cp),
            "record": crec,
            "release": {"ok": ev["release"], "basis": ev["basis"], "reason": ev["reason"]},
            "disclaimer": CONSENT_DISCLAIMER, "message": msg,
        })

    @app.route("/api/consent/<case_id>")
    def api_consent_get(case_id):
        """读本例授权记录 + 放行判定（如实回显；未落档 → has_record=false）。"""
        rec = get_case_record(cfg, case_id)
        if rec is None:
            abort(404)
        crec = load_consent_record(rec)
        ev = evaluate_consent(cfg, rec, crec)
        return jsonify({
            "case_id": case_id, "has_record": crec is not None,
            "record": crec,
            "release": {"ok": ev["release"], "basis": ev["basis"], "reason": ev["reason"]},
            "disclaimer": CONSENT_DISCLAIMER,
        })

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
            # 无已回传结果 → 本机需求解：先探测后端（run_all exit 3 契约前置化）
            backend = SB.resolve_backend()
            if backend == "custom":
                if not SB.custom_available():
                    return jsonify({
                        "error": "环境缺失（exit 3 前置检查）：custom 后端不可用——"
                                 "FlowScope 可执行文件不存在；请构建 code/solver "
                                 "或改 --backend openfoam/laptop"
                        }), 409
            else:
                try:
                    probe = RA.probe_openfoam()
                except Exception:  # noqa: BLE001
                    probe = {"any_present": False}
                if not probe.get("any_present"):
                    return jsonify({
                        "error": "环境缺失（exit 3 前置检查）：本机未检测到 "
                                 "OpenFOAM/WSL/Docker——openfoam 后端不可用；"
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
            "consent": rec.get("consent") or consent_summary(rec),
            "current_stage": current, "stages_seen": stages,
            "n_lines": len(lines),
            "full_chain": rec.get("full_chain"),  # T16：占位链进度（cases_done/total、stage）
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
        # 后端探测（M3：custom 无需 WSL；openfoam 仍要求 WSL+OpenFOAM）
        backend = SB.resolve_backend()
        if backend == "custom":
            if not SB.custom_available():
                return jsonify({"error":
                                "环境缺失：custom 后端不可用——FlowScope 可执行文件"
                                "不存在；请构建 code/solver 后重试"}), 409
        else:
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
        msg = ("FlowScope 求解已启动（custom 后端，心跳看护）"
               if backend == "custom"
               else "WSL Allrun 已启动（20 分钟心跳看护）")
        return jsonify({"case_id": case_id, "status": "solving",
                        "message": msg}), 202

    @app.route("/api/full/<case_id>", methods=["POST"])
    def api_full(case_id):
        """T16 全自动链：几何→主算例→step3 占位×3→WSL 求解×3→post_cfd×3→契约汇编
        →step5 导出→舞台化（档案完整后契约闸门自然放行,不绕闸门）。
        幂等：已有产物自动复用（主算例结果/step3 QC/占位结果/step5 导出）。"""
        rec = get_case_record(cfg, case_id)
        if rec is None:
            abort(404)
        ok, code, msg = gate_case_access(cfg, rec)
        if not ok:
            return jsonify({"error": msg}), code
        if rec.get("kind") == "synthetic":
            return jsonify({"error": "合成 demo 无需解算——结果已预置（预置回放模式）"}), 400
        if case_id in RUNNING:
            return jsonify({"error": f"病例 {case_id} 正在运行中"}), 409
        body = request.get_json(silent=True) or {}
        try:
            zlo = int(body["zlo"]) if body.get("zlo") is not None else None
            zhi = int(body["zhi"]) if body.get("zhi") is not None else None
        except (TypeError, ValueError):
            return jsonify({"error": "zlo/zhi 须为整数（占位档层位窗口）"}), 400
        # 环境前置探测（缺环境直接 409,不空转；M3 后端分派）
        backend = SB.resolve_backend()
        if backend == "custom":
            if not SB.custom_available():
                return jsonify({"error": "环境缺失：custom 后端不可用——"
                                "FlowScope 可执行文件不存在；请构建 code/solver"}), 409
        else:
            try:
                probe = subprocess.run(["wsl", "-l", "-v"], capture_output=True, timeout=60)
                wsl_ok = probe.returncode == 0
            except Exception:  # noqa: BLE001
                wsl_ok = False
            if not wsl_ok:
                return jsonify({"error": "环境缺失：wsl -l -v 失败——全自动求解不可用"}), 409
            if not post_cfd_path(cfg):
                return jsonify({"error": "环境缺失：post_cfd.py 未定位"
                                "（环境变量 P0_POST_CFD 或 ct_base 相对推导）"}), 409
        if not (os.path.isfile(STEP3) and os.path.isfile(STEP5)):
            return jsonify({"error": "环境缺失：step3/step5 管线脚本不存在"}), 409
        reg = load_registry(cfg)
        r = reg.get(case_id) or rec
        r.update(status="running", updated=now_iso(),
                 run={"full": True, "started": now_iso()})
        reg[case_id] = r
        save_registry(cfg, reg)
        t = threading.Thread(target=full_chain_thread,
                            args=(cfg, case_id, zlo, zhi), daemon=True)
        RUNNING[case_id] = t
        t.start()
        return jsonify({"case_id": case_id, "status": "running",
                        "message": "全自动链已启动（主算例复用或求解→step3 占位×3→"
                        "WSL 求解×3→post_cfd×3→契约汇编→step5;预计 ~60-90 分钟）"
                        "——轮询 GET /api/progress/" + case_id}), 202

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
            # T16（2026-10-16）：占位档接线补齐后,本分支退役为档案驱动判据——
            # 与上传病例同一闸门（step5 viewer_data.js / 舞台化单文件存在才 True）。
            # 档案不齐 → 文件不存在 → False；run_all/step5 契约红线一行未动。
            vd = os.path.join(rec.get("out_dir") or "", "step5", "viewer_data.js")
            single = os.path.join(WEBAPP_DIR, "cases", cid, "viewer_single.html")
            return os.path.isfile(vd) or os.path.isfile(single)
        if cid == "pC":
            return False  # CFD 结果待笔记本侧回传
        vd = os.path.join(rec.get("out_dir") or "", "step5", "viewer_data.js")
        single = os.path.join(WEBAPP_DIR, "cases", cid, "viewer_single.html")
        return os.path.isfile(vd) or os.path.isfile(single)

    def _viewer_block_reason(cfg, rec):
        cid = rec["case_id"]
        # T16（2026-10-16）：档案齐（=闸门文件判据通过）→ 无拦截理由。
        # BUILTIN_DEFS 的 viewer_block_reason 是修订3 试跑时点"缺占位档"的事实快照,
        # 占位档补齐后按实际档案状态呈现（不绕过任何 run_all/step5 契约红线）。
        if _viewer_available(cfg, rec):
            return ""
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

    # ---------- oplog / 报障端点（R5） ----------
    @app.route("/api/oplog", methods=["POST"])
    def api_oplog():
        import uuid as _uuid
        body = request.get_json(silent=True) or {}
        action = str(body.get("action") or "")[:64]
        if not action:
            return jsonify({"ok": False, "error": "missing action"}), 400
        detail, n_mask = mask_fatal_pii_values(body.get("detail") or "")
        rec = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "actor": str(body.get("actor") or "?")[:32],
            "actor_source": "client-claim",
            "action": action,
            "case_id": (str(body.get("case_id"))[:64] if body.get("case_id") else None),
            "result": str(body.get("result") or "ok")[:32],
            "detail": detail[:500],
            "masked_paths": n_mask,
            "client": str(body.get("client") or "")[:200],
        }
        d = _state_subdir(cfg, "oplog")
        with io.open(os.path.join(d, datetime.now().strftime("%Y-%m-%d") + ".jsonl"),
                     "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return jsonify({"ok": True})

    @app.route("/api/bugreports", methods=["POST"])
    def api_bugreports_post():
        import uuid as _uuid
        body = request.get_json(silent=True) or {}
        what = str(body.get("what") or "").strip()
        if not what:
            return jsonify({"ok": False, "error": "missing what"}), 400
        what_m, n1 = mask_fatal_pii_values(what)
        exp_m, n2 = mask_fatal_pii_values(body.get("expected") or "")
        rid = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + _uuid.uuid4().hex[:6]
        rec = {
            "id": rid,
            "ts": datetime.now().isoformat(timespec="seconds"),
            "role": str(body.get("role") or "?")[:32],
            "what": what_m[:2000],
            "expected": exp_m[:1000],
            "case_id": (str(body.get("case_id"))[:64] if body.get("case_id") else None),
            "page_url": str(body.get("page_url") or "")[:200],
            "attach": {
                "env": bool(body.get("attach_env")),
                "manifest": bool(body.get("attach_manifest")),
                "page": bool(body.get("attach_page")),
                "rawlog": bool(body.get("attach_log")),
            },
            "masked_paths": n1 + n2,
        }
        if rec["attach"]["manifest"]:
            rec["manifest_tail"] = _read_manifest_tail(cfg, 200)
        d = _state_subdir(cfg, "bugreports")
        with io.open(os.path.join(d, rid + ".json"), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=1)
        return jsonify({"ok": True, "id": rid})

    @app.route("/api/bugreports", methods=["GET"])
    def api_bugreports_get():
        d = _state_subdir(cfg, "bugreports")
        items = []
        for fn in sorted(os.listdir(d), reverse=True)[:100]:
            if not fn.endswith(".json"):
                continue
            try:
                with io.open(os.path.join(d, fn), encoding="utf-8") as f:
                    r = json.load(f)
                items.append({"id": r.get("id"), "ts": r.get("ts"),
                              "role": r.get("role"), "what": (r.get("what") or "")[:80]})
            except (OSError, ValueError):
                continue
        return jsonify({"ok": True, "items": items})

    @app.route("/api/bugreports/export.zip")
    def api_bugreports_export():
        import zipfile
        d = _state_subdir(cfg, "bugreports")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for fn in sorted(os.listdir(d)):
                if fn.endswith(".json"):
                    z.write(os.path.join(d, fn), arcname=fn)
        buf.seek(0)
        return send_file(buf, mimetype="application/zip", as_attachment=True,
                         download_name="bugreports.zip")

    @app.route("/api/oplog/export.jsonl")
    def api_oplog_export():
        d = _state_subdir(cfg, "oplog")
        parts = []
        for fn in sorted(os.listdir(d)):
            if fn.endswith(".jsonl"):
                try:
                    with io.open(os.path.join(d, fn), encoding="utf-8") as f:
                        parts.append(f.read())
                except OSError:
                    pass
        buf = io.BytesIO("".join(parts).encode("utf-8"))
        buf.seek(0)
        return send_file(buf, mimetype="application/x-ndjson", as_attachment=True,
                         download_name="oplog.jsonl")

    # 启动时 dry-run 打印（不自动删——患者本机数据的自动清理须显式接线）
    try:
        _purge_info = purge_oplog_bugreports(cfg, 30, dry_run=True)
        if _purge_info["would_delete"]:
            print("[W] oplog/bugreports 超 30 天条目 %d 个（dry-run，未删除；"
                  "接入保留期策略后自动清理）" % _purge_info["would_delete"], flush=True)
    except Exception as _e:
        print("[W] purge dry-run 跳过：%s" % _e, flush=True)

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
    ap.add_argument("--host", default="127.0.0.1")
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
