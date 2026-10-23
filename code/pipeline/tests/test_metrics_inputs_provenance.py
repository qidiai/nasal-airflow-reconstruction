# -*- coding: utf-8 -*-
"""裁定（五）锁死用例：metrics.inputs 的 nu/rho/mu 必须从 case 文件回读。

缺陷原型（本轮扫描定位）
------------------------
1. ``code/pipeline/solver_backend.py::build_metrics`` 曾硬编码
   ``"nu_m2_s": 1.8e-05`` / ``"mu_Pa_s": MU_AIR``——与 case 文件无任何关联，
   case 一改（或换成别的 case）声明就与物理输入脱钩。
2. 仓外 P0 后处理脚本 ``post_cfd.py`` 的 ``--nu`` 默认 1.48e-5 被直接写进
   inputs（``mu = rho*nu`` 派生），历史 metrics 里 14 条与 case 文件的
   1.800e-05 冲突——这正是"默认值回落"造成的记录缺陷。

本用例的要求
------------
- 假 case 里 nu 写成非默认值 2.5e-05，跑产出 inputs 的函数，必须原样读到 2.5e-05；
- case 文件读不到 nu 时必须写 ``null`` + ``warnings``，**不许**回落到
  1.8e-05 / 1.48e-5 / 2.16e-5 之类的硬编码值；
- 用源码断言（inspect）+ 端到端（monkeypatch 掉 VTK/日志解析）两条腿锁死，
  防止今后有人把默认值塞回来。

临时件一律写 pytest 的 tmp_path（= 系统 %TEMP% 下）。
"""
from __future__ import annotations

import inspect
import json
import os
import re
import sys
import tempfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.dirname(HERE)
if PIPELINE not in sys.path:
    sys.path.insert(0, PIPELINE)

import solver_backend as sb  # noqa: E402

TP_TMPL = """FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      transportProperties;
}}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

transportModel  Newtonian;

{body}

// ************************************************************************* //
"""

FAKE_NU = 2.500e-05          # 刻意不等于任何历史默认值（1.8e-5 / 1.48e-5）
FORBIDDEN = (1.8e-05, 1.48e-05, 2.16e-05)


def _write_case(root, nu_text="2.500e-05", with_nu=True, rho_text=None):
    """在 tmp_path 下造一个假 OpenFOAM case（只有 constant/transportProperties）。"""
    case = os.path.join(root, "P0-OF-case-fake")
    os.makedirs(os.path.join(case, "constant"), exist_ok=True)
    body = []
    if with_nu:
        body.append("nu              [0 2 -1 0 0 0 0] %s;" % nu_text)
    if rho_text is not None:
        body.append("rho             %s;" % rho_text)
    tp = os.path.join(case, "constant", "transportProperties")
    with open(tp, "w", encoding="utf-8", newline="\n") as f:
        f.write(TP_TMPL.format(body="\n".join(body)))
    return case


def test_tmp_case_lives_in_temp_dir(tmp_path):
    """本用例所有产物都在系统临时目录，不碰任何在用产物目录。"""
    assert str(tmp_path).lower().startswith(tempfile.gettempdir().lower())


def test_inputs_nu_is_read_back_from_case_file(tmp_path):
    """核心断言：case 写 2.5e-05，inputs.nu_m2_s 必须就是 2.5e-05。"""
    case = _write_case(str(tmp_path))
    inputs, warnings = sb.build_inputs_provenance(
        case, vtk_dir=os.path.join(str(tmp_path), "out"))

    assert inputs["nu_m2_s"] == pytest.approx(FAKE_NU, rel=0, abs=0)
    for bad in FORBIDDEN:
        assert inputs["nu_m2_s"] != bad, "回落到硬编码默认值 %r" % bad
    # mu = rho * nu，且 rho 来源写清楚（case 不声明 rho -> 契约常量）
    assert inputs["rho_kg_m3"] == pytest.approx(1.2, rel=0, abs=0)
    assert inputs["mu_Pa_s"] == pytest.approx(1.2 * FAKE_NU, rel=0, abs=1e-18)
    assert inputs["rho_source"].startswith("contract_constant")
    assert inputs["nu_source"].lower().endswith("transportproperties")
    assert warnings == []


def test_case_declared_rho_wins(tmp_path):
    """case 里若真声明了 rho，就用 case 的（不伪装成读回）。"""
    case = _write_case(str(tmp_path), rho_text="1.050e+00")
    inputs, _ = sb.build_inputs_provenance(case, vtk_dir=str(tmp_path))
    assert inputs["rho_kg_m3"] == pytest.approx(1.05, rel=0, abs=0)
    assert inputs["mu_Pa_s"] == pytest.approx(1.05 * FAKE_NU, rel=0, abs=1e-18)
    assert inputs["rho_source"].lower().startswith("case:")


def test_unparsable_nu_is_null_and_warns(tmp_path):
    """case 文件没有 nu 行 -> nu/mu 写 null + warnings，绝不猜。"""
    case = _write_case(str(tmp_path), with_nu=False)
    inputs, warnings = sb.build_inputs_provenance(case, vtk_dir=str(tmp_path))
    assert inputs["nu_m2_s"] is None
    assert inputs["mu_Pa_s"] is None
    assert warnings, "解析失败必须在 warnings 里留一条"
    assert any("null" in w for w in warnings)


def test_missing_case_dir_is_null_and_warns(tmp_path):
    """case 目录根本不存在 -> 同样 null + warning（含路径/原因）。"""
    inputs, warnings = sb.build_inputs_provenance(None, vtk_dir=str(tmp_path))
    assert inputs["nu_m2_s"] is None
    assert inputs["mu_Pa_s"] is None
    assert any("null" in w for w in warnings)


def test_solver_backend_label_is_not_hardcoded(tmp_path):
    """后端名同样不能写死：OpenFOAM 跑的 case 不许标成 custom。"""
    case = _write_case(str(tmp_path))
    inputs, _ = sb.build_inputs_provenance(case, vtk_dir=str(tmp_path),
                                          solver_backend="openfoam")
    assert inputs["solver_backend"] == "openfoam"
    assert "flowscope" not in inputs


def test_no_hardcoded_nu_default_in_code_path(tmp_path):
    """源码级断言：产出 inputs 的代码路径里没有 nu 默认值回落。"""
    src = inspect.getsource(sb.build_inputs_provenance)
    src += inspect.getsource(sb.read_case_transport_properties)
    for pat in (r"1\.?80*e-?0*5", r"1\.48e-?0*5", r"2\.16e-?0*5"):
        assert not re.search(pat, src), "inputs 代码路径里出现 nu 硬编码 %s" % pat
    assert "read_case_transport_properties" in inspect.getsource(
        sb.build_inputs_provenance)

    bm_src = inspect.getsource(sb.build_metrics)
    assert "build_inputs_provenance(" in bm_src, "build_metrics 必须走回读函数"
    assert '"nu_m2_s"' not in bm_src, "build_metrics 里不许再出现写死的 nu 字段"
    assert '"mu_Pa_s"' not in bm_src, "build_metrics 里不许再出现写死的 mu 字段"


def _stub_solver_io(monkeypatch, tmp_path):
    """把 VTK/日志解析打桩，只测 inputs 段的来源行为。"""
    import numpy as np

    def fake_read_vtk(path):
        return (np.zeros((1, 3)), np.zeros((1, 4), dtype=int),
                np.ones((1, 3)), np.zeros((1, 1)))

    monkeypatch.setattr(sb, "parse_contract_metrics", lambda p: {"patches": {}})
    monkeypatch.setattr(sb, "_read_flowscope_vtk", fake_read_vtk)
    monkeypatch.setattr(sb, "_wss_stats", lambda *a, **k: {})
    monkeypatch.setattr(sb, "vtk_to_vtu", lambda *a, **k: None)

    out_dir = os.path.join(str(tmp_path), "out")
    os.makedirs(out_dir, exist_ok=True)
    vtk = os.path.join(out_dir, "fields_1500.vtk")
    with open(vtk, "w", encoding="utf-8", newline="\n") as f:
        f.write("# fake\n")
    log = os.path.join(out_dir, "solver.log")
    with open(log, "w", encoding="utf-8", newline="\n") as f:
        f.write("---- 契约 §11 ----\nfake\n")
    return out_dir, vtk, log


def test_build_metrics_end_to_end_writes_case_nu(tmp_path, monkeypatch):
    """端到端：build_metrics 落盘的 metrics.json 的 inputs.nu_m2_s == 2.5e-05。"""
    case = _write_case(str(tmp_path))
    out_dir, _vtk, log = _stub_solver_io(monkeypatch, tmp_path)

    metrics = sb.build_metrics(case, out_dir, log, case="fake")
    assert metrics["inputs"]["nu_m2_s"] == pytest.approx(FAKE_NU, rel=0, abs=0)
    assert metrics["inputs"]["mu_Pa_s"] == pytest.approx(1.2 * FAKE_NU, rel=0, abs=1e-18)
    assert metrics["warnings"] == []

    written = json.load(open(os.path.join(out_dir, "后处理", "metrics.json"),
                            encoding="utf-8"))
    assert written["inputs"]["nu_m2_s"] == pytest.approx(FAKE_NU, rel=0, abs=0)
    for bad in FORBIDDEN:
        assert written["inputs"]["nu_m2_s"] != bad


def test_build_metrics_end_to_end_null_when_case_unreadable(tmp_path, monkeypatch):
    """端到端：case 读不到 nu -> 落盘 null + warnings 有一条。"""
    case = _write_case(str(tmp_path), with_nu=False)
    out_dir, _vtk, log = _stub_solver_io(monkeypatch, tmp_path)

    metrics = sb.build_metrics(case, out_dir, log, case="fake")
    assert metrics["inputs"]["nu_m2_s"] is None
    assert metrics["inputs"]["mu_Pa_s"] is None
    assert len(metrics["warnings"]) >= 1

    written = json.load(open(os.path.join(out_dir, "后处理", "metrics.json"),
                            encoding="utf-8"))
    assert written["inputs"]["nu_m2_s"] is None
    assert written["warnings"]
