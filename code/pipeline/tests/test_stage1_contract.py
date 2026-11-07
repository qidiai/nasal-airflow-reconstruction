#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三步契约分层 v1（2026-11-07）回归。

钉住的契约：第一步 step5 只要求「本例几何 + 本例流场」；三档占位 / pressure-flow
curve 属第二步可选增强，缺失不拦截导出，只如实标注。核心字段缺失仍是红线。
依据：项目文档目录《规格-三步契约分层-v1-2026-11-07.md》。
"""
import importlib.util
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.dirname(HERE)
if PIPELINE not in sys.path:
    sys.path.insert(0, PIPELINE)

import run_all as RA  # noqa: E402

_CORE = ("dP_baseline_Pa", "dP_note", "split_L_pct", "split_R_pct",
         "wss_mean_Pa", "wss_p95_Pa", "resistance_total")
_STAGE2 = {"dP_1mm_Pa", "dP_2mm_Pa", "dP_3mm_Pa",
           "volumes_cm3", "dP_Pa", "band_Pa"}


def _metrics():
    return {"totals": {"dP_Pa": 27.646, "Q_inlet_total_L_min": 15.0,
                       "flow_share_L_pct": 61.58, "flow_share_R_pct": 38.42},
            "wss": {"mean_Pa": 0.012, "p95_Pa": 0.05}}


def test_assemble_contract_splits_core_and_stage2():
    """第一步：核心齐全、第二步占位档缺失 → 不判「契约不完备」。"""
    c, core, stage2 = RA.assemble_contract(_metrics(), "X", "v1")
    assert core == [], "第一步核心字段必须齐全，不得因第二步占位档缺失判不完备"
    assert set(stage2) == _STAGE2, "缺失的只应是第二步可选增强字段"
    assert abs(c["metrics"]["dP_baseline_Pa"] - 27.65) < 0.01


def test_core_fields_never_in_stage2_optional_set():
    """核心字段绝不在可选集合里（红线不被削弱）。"""
    assert set(RA.PLACEHOLDER_ONLY_FIELDS) == _STAGE2
    for k in _CORE:
        assert k not in RA.PLACEHOLDER_ONLY_FIELDS


def test_first_stage_required_sets_pinned():
    """第一步必需集口径钉住（与 step5 的 _CORE_METRICS_REQ 同口径）。"""
    assert set(RA.CORE_METRICS_REQ) == set(_CORE)
    assert set(RA.CORE_META_REQ) == {"title", "caseBaseline", "units", "metrics"}


def test_metrics_req_order_pinned_for_pA_bytecode():
    """占位档完备病例逐字节不变：_METRICS_REQ 必须沿用原实现原序（10 项，
    全量写盘无 sort_keys），闸门拆分用的 _CORE/_STAGE2 集不得改变组装顺序。
    """
    src = open(os.path.join(PIPELINE, "step5_export_viewer_data.py"),
               encoding="utf-8").read()
    assert ('_METRICS_REQ = ["dP_baseline_Pa", "dP_1mm_Pa", "dP_2mm_Pa", '
            '"dP_3mm_Pa", "dP_note",' in src)
    assert "_METRICS_REQ = _CORE_METRICS_REQ + _STAGE2_METRICS_REQ" not in src


def test_step5_source_only_gates_core():
    """源码级：step5 闸门只看 _missing_core，旧「非单算例即中止」条件已移除；
    --ph-dir 默认不再指向其他患者目录（杜绝跨患者占位体几何）。
    """
    src = open(os.path.join(PIPELINE, "step5_export_viewer_data.py"),
               encoding="utf-8").read()
    assert "if _missing_core:" in src
    assert "if _hard or (_missing and not ARGS5.single_case):" not in src
    assert "_CORE_METRICS_REQ" in src and "_STAGE2_METRICS_REQ" in src
    assert '_META_REQ = ["title", "caseBaseline", "units", "metrics"]' in src
    assert '阶段4-模型输出")' not in src, "--ph-dir 不得默认指向患者A 阶段4 输出"
    assert '"--ph-dir", default=None' in src


def test_run_all_source_no_placeholder_gate():
    """源码级：run_all 的 S7 闸门只看 core_missing，不再用 allow_partial_viewer
    作导出闸门（该开关现仅控制 quick 档的 Taubin 平滑跳过）。
    """
    src = open(os.path.join(PIPELINE, "run_all.py"), encoding="utf-8").read()
    assert "if core_missing:" in src
    assert "if missing and not _partial:" not in src
    assert "contract, core_missing, stage2_missing = assemble_contract" in src
    assert "stage2_optional_missing_fields" in src


# ---------------------------------------------------------------- 行为级（真跑 step5）
def _zero_streamline_helpers():
    """复用同目录既有合成输入构造（全合成，不含任何患者数据）。"""
    p = os.path.join(HERE, "test_step5_zero_streamlines.py")
    spec = importlib.util.spec_from_file_location("_zs_helpers", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _run_step5(root, contract_path, single_case):
    h = _zero_streamline_helpers()
    dcm = h._write_dicom_series(root)
    mask_npz = h._write_mask(root)
    vtu = h._write_vtu(root)
    ph_dir = os.path.join(root, "ph")
    os.makedirs(ph_dir, exist_ok=True)
    out_dir = os.path.join(root, "out")
    cmd = [sys.executable, "-X", "utf8",
           os.path.join(PIPELINE, "step5_export_viewer_data.py"),
           "--dicom-dir", dcm, "--case-prefix", "pZ", "--case", "v1",
           "--vtu", vtu, "--metrics-json", contract_path,
           "--ph-dir", ph_dir, "--mask-npz", mask_npz,
           "--out-dir", out_dir, "--write-mode", "full"]
    if single_case:
        cmd.append("--single-case")
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=600, env=env)
    return r, out_dir


def test_standard_without_single_case_is_not_blocked_by_contract(tmp_path):
    """规格「契约闸门解耦」行为级钉子：standard 档（不带 --single-case）、契约只有
    第一步核心字段时，**不得**再被「字段缺失即中止」旧闸门拦下。

    诚实边界：当前 standard 档仍可能因 F3 六板门禁（板④ Taubin 平滑左右比）
    sys.exit(3) 停工（规格 §8 未达成项，属下一层阻断）。本用例只钉契约层放行，
    不把 F3 门禁失败算作契约回归，也不谎称 3D 已导出。
    """
    h = _zero_streamline_helpers()
    root = str(tmp_path)
    contract = h._write_contract(root)
    r, out_dir = _run_step5(root, contract, single_case=False)
    out = (r.stdout or "") + (r.stderr or "")
    assert "meta 契约字段缺失" not in out, "旧闸门不得再拦第一步"
    assert "第一步核心契约字段缺失" not in out, "核心齐全时不得误报"
    if r.returncode != 0:
        # 只允许已知的下一层 F3 门禁停工，不允许任何契约层中止
        assert "门禁越限" in out, (r.stdout[-2000:], r.stderr[-2000:])
        assert not os.path.isfile(os.path.join(out_dir, "viewer_data.js"))


def test_stage2_missing_exports_and_pinned_order(tmp_path):
    """缺第二步占位/曲线时仍导出：meta.metrics 只写核心 7 项且顺序沿用原
    _METRICS_REQ 原序（pA 逐字节不变的前提）；placeholders 为空、partial 如实标注。
    """
    h = _zero_streamline_helpers()
    root = str(tmp_path)
    contract = h._write_contract(root)
    r, out_dir = _run_step5(root, contract, single_case=True)
    assert r.returncode == 0, (r.stdout[-2500:], r.stderr[-2500:])
    js_path = os.path.join(out_dir, "viewer_data.js")
    assert os.path.isfile(js_path)
    data = h._read_viewer_data(js_path)
    assert list(data["meta"]["metrics"].keys()) == [
        "dP_baseline_Pa", "dP_note", "split_L_pct", "split_R_pct",
        "wss_mean_Pa", "wss_p95_Pa", "resistance_total"]
    assert data["meta"]["partial"] is True   # 如实标注，不伪造三档数字
    assert data["placeholders"] == []        # 第一步不拼占位体几何


def test_core_field_missing_still_aborts(tmp_path):
    """红线：第一步核心字段缺失 → 中止导出、不写 viewer_data.js。"""
    h = _zero_streamline_helpers()
    root = str(tmp_path)
    contract = h._write_contract(root)
    c = json.load(open(contract, encoding="utf-8"))
    del c["metrics"]["wss_mean_Pa"]
    with open(contract, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=1)
    # 用 --single-case 让 F3 板④记 SKIP，确保能走到契约检查（红线本身不依赖该开关）
    r, out_dir = _run_step5(root, contract, single_case=True)
    out = (r.stdout or "") + (r.stderr or "")
    assert r.returncode != 0
    assert "第一步核心契约字段缺失" in out, out[-2500:]
    assert not os.path.isfile(os.path.join(out_dir, "viewer_data.js"))
