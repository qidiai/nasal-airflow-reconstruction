#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-DP：dP 稳定早停「停车三元组」日志契约测试（2026-10-20）。

被测对象 = ``code/pipeline/solver_backend.py`` 的日志契约解析（solver 侧只作为
日志格式的提供方，本文件**不做源码字符串 grep**）。

守的契约（对应任务书「输出要求」）：
  1. 机器行 ``stop_reason : dp_stable``（下划线）与人读行 ``stop reason : ...``
     （空格）**互不覆盖**——旧字段逐字节不变，新字段纯新增（新增字段，不动旧字段）。
  2. ``dp_band_pct`` 为 ``NaN``（residualControl 停车 / dP 判据不适用）时归一成
     ``None``，不把 NaN 写进 JSON。
  3. 旧日志（无新行）解析行为零变化：三项缺失，旧四件套照常。
  4. 停车**判据行为**不在本文件：三道门（带 / 最少步数 / 连续性）、confirm 重置、
     端到端 ``dp_stable`` 与 ``--no-dp-stop`` 兜底，由 Rust 行为测试
     ``code/solver/src/simple.rs::dp_stop_tests``（t0-t4）覆盖，判据参数
     20/5/0.002/100/1e-2/2 由 ``t0_criterion_params_pinned`` 语义化钉住。
     （2026-10-21 审计 [16][17] 整改：原两例源码 grep 用例已删除，不计入覆盖声明。）

运行：``py -X utf8 -m pytest tests/test_dp_stop.py -v``（仓库根目录）
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "code", "pipeline"))

import solver_backend as SB  # noqa: E402

# 求解器实际输出的日志片段（dp_stable 早停：L3-019 实测）
LOG_DP_STABLE = """\
---- 契约 §11 口径指标 ----
run mode            : Run-A(定流量)
iterations          : 140
stop reason         : dP 稳定早停：iter 140，dP = 458.631651 Pa，band = 0.0535%（0.2% 带 / 5 样本 / 最少 100 步；residualControl 未双达标）
stop_reason         : dp_stable
stop_iter           : 140
dp_band_pct         : 0.053491
patch inletL   : sum(phi) = -9.750341e-5 m3/s   A = 9.534208e-5 m2   p_mean(kin) = 1.162067e1
dP (rho*p_in - p_out) = 458.631651 Pa
continuity (1/s)    : local 2.293e-3 global 5.085e-7
"""

# residualControl 停车（带宽从未评估 → NaN）
LOG_RESIDUAL = """\
run mode            : Run-A(定流量)
iterations          : 89
stop reason         : SIMPLE solution converged：iter 89，p 初残差 9.1e-5 < 0.0001，U 初残差 1e-5/1e-5/1e-5 < 0.0001（residualControl 双口径达标）
stop_reason         : residual
stop_iter           : 89
dp_band_pct         : NaN
dP (rho*p_in - p_out) = 12.345678 Pa
"""

# 旧版求解器日志（无三元组）
LOG_LEGACY = """\
run mode            : Run-A(定流量)
iterations          : 1500
stop reason         : endTime 硬停：跑满 1500 步，residualControl 未双达标（末步 p 初残差 8.407e-2，U 1.078e-2/4.565e-3/4.542e-3）
dP (rho*p_in - p_out) = 18.378877 Pa
"""


@pytest.fixture()
def parse(tmp_path):
    def _parse(text):
        p = tmp_path / "solver.log"
        p.write_text(text, encoding="utf-8")
        return SB.parse_contract_metrics(str(p))

    return _parse


def test_dp_stable_triplet_parsed_and_legacy_fields_intact(parse):
    d = parse(LOG_DP_STABLE)
    assert d["stop_reason_code"] == "dp_stable"
    assert d["stop_iter"] == 140
    assert d["dp_band_pct"] == pytest.approx(0.053491, rel=0, abs=1e-9)
    # 旧字段逐字节不变：人读 stop reason 仍是完整中文句（未被下划线行覆盖）
    assert d["stop_reason"].startswith("dP 稳定早停：iter 140，dP = 458.631651 Pa")
    assert d["iterations"] == 140
    assert d["dP_Pa"] == pytest.approx(458.631651)
    assert d["run_mode"] == "Run-A(定流量)"
    assert d["continuity_global"] == pytest.approx(5.085e-7)


def test_residual_stop_nan_band_becomes_none(parse):
    d = parse(LOG_RESIDUAL)
    assert d["stop_reason_code"] == "residual"
    assert d["stop_iter"] == 89
    assert d["dp_band_pct"] is None          # NaN → None（不写进 JSON）
    assert d["stop_reason"].startswith("SIMPLE solution converged：iter 89")


def test_legacy_log_unchanged(parse):
    d = parse(LOG_LEGACY)
    assert "stop_reason_code" not in d
    assert "stop_iter" not in d
    assert "dp_band_pct" not in d
    assert d["iterations"] == 1500
    assert d["stop_reason"].startswith("endTime 硬停：跑满 1500 步")
    assert d["dP_Pa"] == pytest.approx(18.378877)


# 「判据关闭」日志（--no-dp-stop → endTime 硬停）：三元组照常输出，带未评估为 NaN
LOG_DP_OFF = """\
run mode            : Run-A(定流量)
iterations          : 1500
stop reason         : endTime 硬停：跑满 1500 步，residualControl 未双达标（末次 p 初残差 8.407e-2，U 1.078e-2/4.565e-3/4.542e-3）
stop_reason         : endtime
stop_iter           : 1500
dp_band_pct         : NaN
dP (rho*p_in - p_out) = 18.378877 Pa
"""


def test_criterion_disabled_still_parses_triplet(parse):
    """--no-dp-stop：endTime 硬停走同一三元组契约（code=endtime / NaN → None）。"""
    d = parse(LOG_DP_OFF)
    assert d["stop_reason_code"] == "endtime"
    assert d["stop_iter"] == 1500
    assert d["dp_band_pct"] is None
    assert d["stop_reason"].startswith("endTime 硬停：跑满 1500 步")


def test_dp_band_pct_is_percent_number_not_fraction(parse):
    """单位契约：dp_band_pct 是**百分数数值**（0.1896 表示 0.19%），解析层不得再缩放。"""
    d = parse(LOG_DP_STABLE.replace("0.053491", "0.1896"))
    assert d["dp_band_pct"] == pytest.approx(0.1896, rel=0, abs=0)
    assert d["stop_reason_code"] == "dp_stable"
