#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 1 患者自助闭环（T-P1）回归：快速档口径 / 人话进度 / 目录隔离。

钉住的契约（用户 2026-10-20 裁定）：
  1) 决策 1 相对 z 口径：quick_voxel_z(dz) = max(2, round(3.0/dz)) * dz，
     结果必须是 dz 的**整数倍**（step2 的 --voxel-z 非整数倍即停工），
     dz 不可用 → None（调用方回退「只降步数」）。
  2) 决策 2 人话进度：/api/progress 新增 stage_zh/eta_hint_zh/mode 等字段，
     既有字段一个不改；「未收敛」在患者档不得读成「出错」。
  3) 决策 3 目录隔离：quick 产物在 <out_dir>/quick/，standard 读原路径；
     mode 缺省 = standard（老病例零影响）。
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


# ---------------------------------------------------------------- 决策 1：z 口径
@pytest.mark.parametrize("dz,expect", [
    (0.7, 2.8),      # synth 栅格化序列：3.0/0.7 = 4.29 → zf=4 → 2.8mm
    (0.35, 3.15),    # pA 真实 CT：3.0/0.35 = 8.57 → zf=9 → 3.15mm
    (1.0, 3.0),      # 患者C 类 1mm 序列：zf=3 → 3.0mm
    (0.5, 3.0),      # zf=6
    (3.0, 3.0),      # 已经等于目标：zf=1 但下限 2 → 6.0? 见下一条断言
])
def test_quick_voxel_z_is_integer_multiple(dz, expect):
    """快速档 z 必须是源层厚整数倍（否则 step2 停工上报）。"""
    qz = run_all.quick_voxel_z(dz)
    assert qz is not None
    zf = qz / dz
    assert abs(zf - round(zf)) < 1e-9, "voxel_z %r 不是层厚 %r 的整数倍" % (qz, dz)
    assert round(zf) >= 2, "下限 2：不做比默认更细的 z 向加密"
    if dz != 3.0:
        assert abs(qz - expect) < 1e-9
    else:
        # dz=3.0：round(3.0/3.0)=1 → 被下限抬到 2 → 6.0mm
        assert abs(qz - 6.0) < 1e-9


@pytest.mark.parametrize("bad", [None, 0, -0.7, "abc", float("nan")])
def test_quick_voxel_z_falls_back_on_unusable_dz(bad):
    """读不到/非法层厚 → None（调用方回退只降步数，绝不猜）。"""
    assert run_all.quick_voxel_z(bad) is None


def test_quick_defaults_pin():
    """常量口径钉住：300 步 / 目标 3.0mm（改这些值要有意识）。"""
    assert run_all.QUICK_MAX_ITER == 300
    assert run_all.QUICK_TARGET_VOXEL_Z_MM == 3.0


def test_run_all_cli_exposes_quick_flags():
    """CLI 真实暴露 --quick / --max-iter（默认 1500 = 现状）。"""
    out = subprocess.run([sys.executable, os.path.join(PIPELINE, "run_all.py"), "--help"],
                         capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert out.returncode == 0, out.stderr[-800:]
    assert "--quick" in out.stdout
    assert "--max-iter" in out.stdout
    assert "1500" in out.stdout


# ---------------------------------------------------------------- 决策 3：目录隔离
def test_run_out_root_quick_isolated():
    rec = {"out_dir": os.path.join("S", "cases", "c1")}
    assert server.run_out_root(rec, "quick") == os.path.join("S", "cases", "c1", "quick")
    assert server.run_out_root(rec, "standard") == os.path.join("S", "cases", "c1")
    assert server.run_out_root({}, "quick") == ""


@pytest.mark.parametrize("run,mode", [
    ({}, "standard"),
    (None, "standard"),
    ({"mode": "standard"}, "standard"),
    ({"mode": "quick"}, "quick"),
    ({"solve": "local"}, "standard"),     # 老记录没有 mode → 原路径
])
def test_case_run_mode_default_standard(run, mode):
    rec = {"run": run} if run is not None else {}
    assert server.case_run_mode(rec) == mode


def test_case_slice_dz_prefers_measured_then_header():
    """实测层间距优先；没有 survey 时读 DICOM 头；都没有 → None。"""
    assert server.case_slice_dz({"survey": {"slice_gap_measured": 0.7}}) == 0.7
    assert server.case_slice_dz({"survey": {"slice_gap_measured": 0},
                                 "dicom_dir": ""}) is None
    assert server.case_slice_dz({}) is None


# ---------------------------------------------------------------- 决策 2：人话进度
def test_human_progress_four_stages():
    """S0-S8 → 四阶段；阶段推进与完成态文案。"""
    p0 = server.human_progress(["S0"], "running", "quick", 10)
    assert p0["stage_zh"] == "识别气道" and p0["stage_index"] == 0
    assert p0["stage_count"] == 4
    assert "分钟" in p0["eta_hint_zh"]

    p2 = server.human_progress(["S0", "S1", "S2", "S3", "S4", "S5"], "running", "quick", 120)
    assert p2["stage_zh"] == "算气流" and p2["stage_index"] == 2
    assert p2["progress_pct"] > p0["progress_pct"]

    done = server.human_progress(["S0", "S8"], "done", "quick", 900)
    assert done["stage_zh"] == "分析完成" and done["eta_hint_zh"] == "已完成"
    assert done["progress_pct"] == 100


def test_human_progress_stopped_status_is_not_excited():
    """blocked/failed 不装正常，也不说「还要几分钟」。"""
    for st in ("blocked", "failed", "failed_env", "failed_solve_stalled"):
        p = server.human_progress(["S0", "S1", "S2", "S3"], st, "quick", 60)
        assert p["stage_zh"] == "建网格"
        assert "分钟" not in p["eta_hint_zh"]


def test_human_progress_over_budget_says_so():
    """超出预估时如实说「比预估久」，不编精确 ETA。"""
    p = server.human_progress(["S0", "S1", "S2", "S3", "S4", "S5"], "running",
                              "quick", 10 ** 6)
    assert "已接近预估时长" in p["eta_hint_zh"]


# ---------------------------------------------------------------- API 层（Flask test client）
def _mk_cfg(tmp_path):
    return server.ServerConfig(mode="m1-local", state_dir=str(tmp_path))


def _mk_case(cfg, case_id, mode, progress_lines_std, progress_lines_quick):
    out_dir = os.path.join(cfg.state_dir, "cases", case_id)
    for d, lines in ((out_dir, progress_lines_std),
                     (os.path.join(out_dir, "quick"), progress_lines_quick)):
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "manifest-progress.json"), "w", encoding="utf-8") as f:
            for ln in lines:
                f.write(json.dumps(ln, ensure_ascii=False) + "\n")
    reg = server.load_registry(cfg)
    reg[case_id] = {
        "case_id": case_id, "kind": "upload", "prefix": "pQ", "case_name": "v1",
        "label": "测试病例", "dicom_dir": "", "out_dir": out_dir,
        "status": "running", "synthetic": False, "presenter_only": False,
        "created": server.now_iso(), "updated": server.now_iso(),
        "run": {"solve": "local", "mode": mode, "started": server.now_iso()},
    }
    server.save_registry(cfg, reg)
    return out_dir


def test_api_progress_mode_aware_and_keeps_old_fields(tmp_path):
    """quick 读 quick 子目录进度；standard 读原路径；既有字段一个不少。"""
    cfg = _mk_cfg(tmp_path)
    t = 1700000000.0
    _mk_case(cfg, "ptq1", "quick",
             [{"ts": t, "msg": "[S0] standard-only-line"}],
             [{"ts": t, "msg": "[S0] quick-line"}, {"ts": t + 5, "msg": "[S1] quick-line2"}])
    app = server.build_app(cfg)
    c = app.test_client()

    b = c.get("/api/progress/ptq1").get_json()
    msgs = " ".join(x.get("msg", "") for x in b["lines"])
    assert "quick-line" in msgs and "standard-only-line" not in msgs
    assert b["mode"] == "quick"
    assert b["stage_zh"] in ("识别气道", "建网格", "算气流", "出结果")
    assert isinstance(b["eta_hint_zh"], str) and b["eta_hint_zh"]
    # 既有字段（brief §2：保留原字段不变）
    for k in ("case_id", "status", "exit_code", "gate", "gate_failures", "consent",
              "current_stage", "stages_seen", "n_lines", "full_chain", "updated", "lines"):
        assert k in b, "既有字段 %s 被弄丢了" % k
    assert b["case_id"] == "ptq1" and b["status"] == "running"

    # 切成 standard 后必须回到原路径（老病例/standard 行为不变）
    reg = server.load_registry(cfg)
    reg["ptq1"]["run"]["mode"] = "standard"
    server.save_registry(cfg, reg)
    b2 = c.get("/api/progress/ptq1").get_json()
    msgs2 = " ".join(x.get("msg", "") for x in b2["lines"])
    assert "standard-only-line" in msgs2 and "quick-line" not in msgs2
    assert b2["mode"] == "standard"


def test_api_run_rejects_unknown_mode(tmp_path):
    """mode 只认 quick|standard，其它一律 400（不启动线程）。"""
    cfg = _mk_cfg(tmp_path)
    _mk_case(cfg, "ptq2", "standard", [], [])
    app = server.build_app(cfg)
    c = app.test_client()
    r = c.post("/api/run/ptq2", json={"solve": "skip", "mode": "ultra"})
    assert r.status_code == 400
    assert "quick" in r.get_json()["error"] and "standard" in r.get_json()["error"]


def test_standard_progress_file_untouched_by_quick_reads(tmp_path):
    """读 quick 进度不得改动 standard 的 manifest-progress.json（逐字节）。"""
    cfg = _mk_cfg(tmp_path)
    out_dir = _mk_case(cfg, "ptq3", "quick",
                       [{"ts": 1.0, "msg": "[S0] std"}],
                       [{"ts": 2.0, "msg": "[S0] qk"}])
    p_std = os.path.join(out_dir, "manifest-progress.json")
    before = open(p_std, "rb").read()
    c = server.build_app(cfg).test_client()
    c.get("/api/progress/ptq3")
    assert open(p_std, "rb").read() == before
