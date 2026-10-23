#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 1.5 单算例（快速档）viewer 部分导出回归（T-P1.5）。

钉住的契约：
  1) step5 单算例模式（--single-case）只放行"三档占位体"相关字段缺失；
     核心字段（ΔP/WSS/分流/阻力）缺失仍按红线中止（run_all 同口径常量钉住）。
  2) 导出数据里 meta.partial=true + meta.missing 列清缺失区块，且三档数字一个都不写
     （绝不写 0、不借用别的病例数字）。
  3) /api/metrics 把 partial/missing 透给前端；占位档完备病例的响应里**没有**这两个
     新增字段（老病例响应逐字节不变）。
  4) _viewer_available 按 mode 取本例产物根：quick 的 viewer_data.js 在
     <out_dir>/quick/step5/ 也算"查看器就绪"（单算例 partial 同样落这里）。
"""
import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.dirname(HERE)
if PIPELINE not in sys.path:
    sys.path.insert(0, PIPELINE)

import run_all  # noqa: E402
import server  # noqa: E402


# ---------------------------------------------------------------- 常量口径
def test_placeholder_only_fields_pinned():
    """run_all 与 step5 的单算例可缺项口径必须一致（6 项，全是三档占位体相关）。"""
    expect = {"dP_1mm_Pa", "dP_2mm_Pa", "dP_3mm_Pa", "volumes_cm3", "dP_Pa", "band_Pa"}
    assert set(run_all.PLACEHOLDER_ONLY_FIELDS) == expect
    # 核心字段绝不在放行集合里
    for core in ("dP_baseline_Pa", "split_L_pct", "split_R_pct",
                 "wss_mean_Pa", "wss_p95_Pa", "resistance_total", "dP_note"):
        assert core not in run_all.PLACEHOLDER_ONLY_FIELDS


# ------------------------------------------------- 子进程编码自洽（T3a F1 / 根因 R-A）
def _child_env_utf8():
    """给子进程注入 UTF-8 环境，让它按 utf-8 写 stdout/stderr。

    根因（本机实测）：默认环境（GBK 控制台）下子进程 sys.stdout.encoding=gbk，
    print 中文 → GBK 字节（如 '层' = 0xb2 0xe3）→ 父进程 encoding="utf-8" 解码在
    _readerthread 抛 UnicodeDecodeError → CompletedProcess.stdout/stderr 变成 None
    → 断言里 `'x' in None` 抛 TypeError，把真失败伪装成怪错误。
    只动 env/解码兜底，被测命令 argv、timeout、capture 语义一律不变。
    """
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def test_run_all_cli_exposes_allow_partial_viewer():
    out = subprocess.run([sys.executable, os.path.join(PIPELINE, "run_all.py"), "--help"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace",
                         env=_child_env_utf8(), timeout=120)
    assert out.returncode == 0, (out.stderr or "")[-800:]
    assert "--allow-partial-viewer" in (out.stdout or "")


def test_step5_cli_exposes_single_case_and_mask_override():
    out = subprocess.run([sys.executable,
                          os.path.join(PIPELINE, "step5_export_viewer_data.py"), "--help"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace",
                         env=_child_env_utf8(), timeout=120)
    assert out.returncode == 0, (out.stderr or "")[-800:]
    assert "--single-case" in (out.stdout or "")
    assert "--mask-npz" in (out.stdout or "")


# ---------------------------------------------------------------- API 层
def _mk_cfg(tmp_path):
    return server.ServerConfig(mode="m1-local", state_dir=str(tmp_path))


def _viewer_js(meta):
    return ("window.VIEWER_DATA = "
            + json.dumps({"meta": meta, "airwayMesh": {"positions": [], "indices": []},
                          "streamlines": [], "slices": [], "placeholders": [],
                          "curve": {}, "airwayCavity": {"positions": [], "indices": []},
                          "airwaySinus": {"positions": [], "indices": []}},
                         ensure_ascii=False, separators=(",", ":"))
            + ";\nconsole.log('VIEWER_DATA loaded', {});\n")


_PARTIAL_META = {
    "title": "患者测试 鼻腔气流仿真查看器", "caseBaseline": "v1 @15 L/min 层流",
    "units": "mm, m/s, Pa",
    "metrics": {"dP_baseline_Pa": 27.62, "dP_note": "层流下界估计",
                "split_L_pct": 61.6, "split_R_pct": 38.4,
                "wss_mean_Pa": 0.019, "wss_p95_Pa": 0.079,
                "resistance_total": "110.5 Pa/(L/s)"},
    "partial": True,
    "missing": ["dP_1mm_Pa", "dP_2mm_Pa", "dP_3mm_Pa",
                "volumes_cm3", "dP_Pa", "band_Pa",
                "placeholder_1mm", "placeholder_2mm", "placeholder_3mm"],
}

_COMPLETE_META = {
    "title": "患者A 鼻腔气流仿真查看器", "caseBaseline": "v5 @15 L/min 层流",
    "units": "mm, m/s, Pa",
    "metrics": {"dP_baseline_Pa": 18.45, "dP_1mm_Pa": 28.6, "dP_2mm_Pa": 47.3,
                "dP_3mm_Pa": 52.4, "dP_note": "层流下界估计",
                "split_L_pct": 51.9, "split_R_pct": 48.1,
                "wss_mean_Pa": 0.011, "wss_p95_Pa": 0.054,
                "resistance_total": "66.2 Pa/(L/s)"},
}


def _mk_case_with_viewer(cfg, case_id, meta, mode="standard"):
    """建一个上传病例，viewer_data.js 落在 mode 对应的产物根下。"""
    out_dir = os.path.join(cfg.state_dir, "cases", case_id)
    root = server.run_out_root({"out_dir": out_dir}, mode) or out_dir
    os.makedirs(os.path.join(root, "step5"), exist_ok=True)
    with open(os.path.join(root, "step5", "viewer_data.js"), "w", encoding="utf-8") as f:
        f.write(_viewer_js(meta))
    reg = server.load_registry(cfg)
    reg[case_id] = {
        "case_id": case_id, "kind": "upload", "prefix": "pQ", "case_name": "v1",
        "label": "测试病例", "dicom_dir": "", "out_dir": out_dir,
        "status": "done", "synthetic": False, "presenter_only": False,
        "created": server.now_iso(), "updated": server.now_iso(),
        "run": {"solve": "local", "mode": mode, "started": server.now_iso()},
    }
    server.save_registry(cfg, reg)
    return out_dir


def test_metrics_exposes_partial_and_missing(tmp_path):
    """partial 病例：/api/metrics 透出 partial + missing，数字照旧读本例产物。"""
    cfg = _mk_cfg(tmp_path)
    _mk_case_with_viewer(cfg, "pq_partial", _PARTIAL_META, mode="quick")
    c = server.build_app(cfg).test_client()
    b = c.get("/api/metrics/pq_partial").get_json()
    assert b["partial"] is True
    assert "placeholder_1mm" in b["missing"] and "dP_Pa" in b["missing"]
    assert b["dP"]["value"] == 27.62
    assert b["mode"] == "quick"
    # 三档数字一个都不许被编出来
    assert b["implant_scenarios"]["dP_1mm_Pa"] is None
    assert b["implant_scenarios"]["dP_2mm_Pa"] is None
    assert b["implant_scenarios"]["dP_3mm_Pa"] is None


def test_metrics_complete_case_has_no_partial_keys(tmp_path):
    """占位档完备病例：响应里没有新增的 partial/missing 字段（老病例响应不变）。"""
    cfg = _mk_cfg(tmp_path)
    _mk_case_with_viewer(cfg, "pq_full", _COMPLETE_META, mode="standard")
    c = server.build_app(cfg).test_client()
    b = c.get("/api/metrics/pq_full").get_json()
    assert "partial" not in b
    assert "missing" not in b
    assert b["dP"]["value"] == 18.45
    assert b["implant_scenarios"]["dP_1mm_Pa"] == 28.6


@pytest.mark.parametrize("mode", ["standard", "quick"])
def test_viewer_available_reads_mode_specific_root(tmp_path, mode):
    """viewer_available：产物落在 <out_dir>/[quick/]step5/viewer_data.js 就算就绪。"""
    cfg = _mk_cfg(tmp_path)
    _mk_case_with_viewer(cfg, "pqv" + mode, _PARTIAL_META, mode=mode)
    c = server.build_app(cfg).test_client()
    cards = c.get("/api/cases").get_json()["cases"]
    card = [x for x in cards if x["case_id"] == "pqv" + mode]
    assert card, "上传病例未出现在 /api/cases"
    assert card[0]["viewer_available"] is True


def test_viewer_unavailable_when_other_mode_root_only(tmp_path):
    """quick 病例只在 standard 根下有 viewer_data.js → 不算就绪（mode 不串台）。"""
    cfg = _mk_cfg(tmp_path)
    _mk_case_with_viewer(cfg, "pqmix", _PARTIAL_META, mode="standard")
    reg = server.load_registry(cfg)
    reg["pqmix"]["run"]["mode"] = "quick"      # 声明 quick，产物却只在 standard 根
    server.save_registry(cfg, reg)
    c = server.build_app(cfg).test_client()
    cards = c.get("/api/cases").get_json()["cases"]
    card = [x for x in cards if x["case_id"] == "pqmix"][0]
    assert card["viewer_available"] is False


# ---------------------------------------------------------------- 板④ 口径（裁决 2026-10-21）
def test_step5_board4_is_skip_not_pass_in_single_case():
    """单算例模式板④ 必须是 SKIP（pass=None），不允许"没做却 PASS"。

    源码级钉住（step5 是脚本、无法 import）：板④ 的 single-case 分支必须写成
    pass=None + skipped=True + 实测位移理由，且 meta 必须下发 smoothing_skipped /
    smoothing_displacement_mm。
    """
    src = open(os.path.join(PIPELINE, "step5_export_viewer_data.py"),
               encoding="utf-8").read()
    assert '"pass": None, "skipped": True, "reason": _reason4' in src, \
        "板④ 单算例分支必须记 SKIP（pass=None），不得记 PASS"
    assert "未执行：本模式不做视觉平滑（测得位移均值 %.2fmm/峰值 %.2fmm" in src, \
        "板④ SKIP 理由必须带实测位移（均值/峰值），不得硬编码"
    assert 'meta["smoothing_skipped"] = True' in src
    assert 'meta["smoothing_displacement_mm"] = {' in src
    # 位移必须来自实测探针，不能是常量
    assert "def taubin_probe_displacement(" in src
    assert "taubin_probe_displacement(air)" in src
    assert "taubin_probe_displacement(cavity_mesh)" in src
    # 口径一致性：放行日志不得把 SKIP 说成"全过"
    assert "门禁无 FAIL（%d 项未执行" in src
