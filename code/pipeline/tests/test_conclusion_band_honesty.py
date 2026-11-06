# -*- coding: utf-8 -*-
"""T10-a 结论层口径批修锁死用例（演示值路线）。

钉住：
  F1 单一演示带口径 —— 三文件 DEMO_BAND / TIER_* / classify_demo_band 同口径，
      pA 基线演示值 18.45 在临床卡与 v6 图得同一档位结论（DF1）；
  F2 输入溯源 / 外推标注 —— load_curve_points 读文件附 md5/路径 或 显式硬编码演示标注，
      v6 图外推段虚线 + 「外推」标注 + 「仿真估计·示例值（合成演示数据）」（DF4）；
  F3 禁词清理 —— v6 输出与三文件源码不再出现人群对照/承诺义表述/旧冠名（DF5）；
  F4 动态叙事 —— 推荐括号由 v30 与档位表动态生成、v30 is None 不抛 TypeError（DF6）；
  F5 演示值路线 —— 演示/合成/示例值标注在场，「非归档真值」显式声明。

不直接 import 三个源模块（避免 matplotlib / QIDI_WORKSPACE / stdout.reconfigure 等导入副作用）：
带口径用 AST 抽取后执行；v6_curve_fit 仅经 importlib 导入其纯函数（已加 main guard）。
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.dirname(HERE)
MEDICAL = os.path.join(PIPELINE, "medical_extract")
FIT = os.path.join(PIPELINE, "v6_curve_fit.py")
FIG = os.path.join(PIPELINE, "v6_curve_fig.py")
CLI = os.path.join(MEDICAL, "extract_clinical.py")
ALL_SOURCES = {"v6_curve_fit.py": FIT, "v6_curve_fig.py": FIG,
               "extract_clinical.py": CLI}

# report/wording.py:47 REPORT_BANNED 的人群对照词 + F3 点名的承诺义表述 + 图侧旧冠名
BANNED_WORDS = [
    "健康人群", "正常人群", "健康人", "正常人", "常人带", "正常带",
    "常人带中部", "安全余量", "工程推荐",
    "Normal literature band", "Patient A", "CFD simulation points",
]
CONST_NAMES = {"DEMO_BAND", "TIER_BELOW", "TIER_GREEN", "TIER_YELLOW", "TIER_RED"}


def _src(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _caliber_nodes(tree):
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if names & CONST_NAMES:
                nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name == "classify_demo_band":
            nodes.append(node)
    return nodes


def _caliber_ns(path):
    """从源码 AST 抽取演示带口径常量与 classify_demo_band 并执行，返回命名空间。"""
    nodes = _caliber_nodes(ast.parse(_src(path), filename=path))
    assert len(nodes) == 6, "%s: 期望 5 常量 + classify_demo_band，实得 %d" % (path, len(nodes))
    ns = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), path, "exec"), ns)
    return ns


def _array_literal(path, varname):
    """取模块级 ``X = [...]`` 或 ``X = np.array([...])`` 的字面量列表。"""
    for node in ast.parse(_src(path)).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == varname for t in node.targets):
            val = node.value
            if isinstance(val, ast.Call):
                val = val.args[0]
            return ast.literal_eval(val)
    raise AssertionError("%s 无模块级 %s" % (path, varname))


def _import_fit():
    spec = importlib.util.spec_from_file_location("_t10a_v6_curve_fit", FIT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def calibers():
    return {name: _caliber_ns(path) for name, path in ALL_SOURCES.items()}


# ---------------------------------------------------------------- F1 / DF1
def test_single_band_caliber_identical_across_three_files(calibers):
    bands = [ns["DEMO_BAND"] for ns in calibers.values()]
    assert bands[0] == bands[1] == bands[2], "三文件 DEMO_BAND 必须完全同一份"
    b = bands[0]
    assert b["green_max_Pa"] == 50.0 and b["yellow_max_Pa"] == 80.0
    assert b["demo_lower_ref_Pa"] == 30.0
    assert b["demo"] is True
    assert "内部工程/演示阈值" in b["caliber"] and "非文献参考带" in b["caliber"]
    assert "@15 L/min" in b["flow_caliber"]        # 工况对齐（选 @15 L/min 单口径）


def test_tier_constants_identical_across_three_files(calibers):
    for key in ("TIER_BELOW", "TIER_GREEN", "TIER_YELLOW", "TIER_RED"):
        vals = [ns[key] for ns in calibers.values()]
        assert vals[0] == vals[1] == vals[2], "%s 三文件不一致" % key


@pytest.mark.parametrize("dp", [None, 18.45, 28.55, 30.0, 47.32, 52.40,
                                50.0, 50.01, 80.0, 80.01, 150.0])
def test_same_tier_conclusion_everywhere(calibers, dp):
    """F1 测试钉住：同一 pA/ΔP 演示值在任何口径源得同一档位结论。"""
    results = [ns["classify_demo_band"](dp) for ns in calibers.values()]
    assert results[0] == results[1] == results[2], \
        "同一数值在任何口径源档位必须一致: %r -> %r" % (dp, results)


def test_pa_baseline_18_45_agrees_in_clinical_card_and_v6_fig(calibers):
    """DF1 核心：18.45 在临床卡与 v6 图同档位，且不得被判成人群/文献正常带内。"""
    clinical = calibers["extract_clinical.py"]
    fig = calibers["v6_curve_fig.py"]
    c = clinical["classify_demo_band"](18.45)
    f = fig["classify_demo_band"](18.45)
    assert c == f == clinical["TIER_BELOW"]
    assert "演示" in c and "非临床判读" in c
    for bad in BANNED_WORDS:
        assert bad not in c


def test_classify_none_does_not_raise(calibers):
    for ns in calibers.values():
        assert "无 ΔP 数值" in ns["classify_demo_band"](None)


# ---------------------------------------------------------------- F3 / F5 源码
@pytest.mark.parametrize("name,path", list(ALL_SOURCES.items()))
def test_no_banned_wording_in_source(name, path):
    src = _src(path)
    for bad in BANNED_WORDS:
        assert bad not in src, "%s 仍含禁词/旧冠名 %r" % (name, bad)


@pytest.mark.parametrize("name,path", list(ALL_SOURCES.items()))
def test_demo_value_route_declared_in_source(name, path):
    src = _src(path)
    assert "演示" in src, "%s 缺演示值标注" % name
    assert "非归档真值" in src, "%s 缺『非归档真值』显式声明" % name
    assert "非文献参考带" in src, "%s 缺『非文献参考带』声明" % name


def test_clinical_ref_band_uses_unified_caliber_and_dual_flow_label():
    src = _src(CLI)
    assert "DEMO_BAND['green_max_Pa']" in src
    assert "green_label': TIER_GREEN" in src
    assert "classify_demo_band(DP_CAL)" in src
    assert "显式双标" in src                       # 工况对齐/双标裁决
    assert "flow_caliber" in src


def test_v6_curve_fit_has_file_provenance_in_source():
    src = _src(FIT)
    assert "hashlib.md5" in src
    assert "def load_curve_points" in src
    assert "V6_CURVE_INPUT_JSON" in src
    assert "narrowing_qc.json" in src
    assert "if __name__ == '__main__':" in src    # main guard（import-safe）


def test_v6_fig_has_extrapolation_example_caption_and_main_guard():
    src = _src(FIG)
    assert "外推" in src                          # DF4 外推显式标注
    assert "Vs_ext" in src and '"b--"' in src     # 外推段虚线
    assert "V_MAX" in src
    assert "仿真估计·示例值（合成演示数据）" in src
    assert "参考病例演示" in src                 # 删除病例冠名
    assert "def main():" in src and "if __name__ == '__main__':" in src
    assert src.find("QIDI_WORKSPACE") > src.find("def main():")   # env 检查在 main 内


def test_fig_and_fit_share_same_demo_samples():
    assert _array_literal(FIG, "DEMO_V") == _array_literal(FIT, "DEMO_V")
    assert _array_literal(FIG, "DEMO_P") == _array_literal(FIT, "DEMO_P")
    assert _array_literal(FIG, "V_MAX") == _array_literal(FIT, "V_MAX")


# ---------------------------------------------------------------- F2 / DF4 溯源
def test_load_curve_points_from_file_prints_md5_and_path(tmp_path, monkeypatch, capsys):
    fit = _import_fit()
    payload = {"V_cm3": [0.0, 4.366, 8.239, 10.415],
               "P_Pa": [18.45, 28.55, 47.32, 52.40],
               "note": "合成演示数据（探针）"}
    jp = tmp_path / "narrowing_qc.json"
    jp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("V6_CURVE_INPUT_JSON", str(jp))
    V, P, prov = fit.load_curve_points()
    captured = capsys.readouterr().out
    assert prov["source"] == "file"
    assert prov["path"] == str(jp)
    assert len(prov["md5"]) == 32
    assert prov["demo"] is False
    assert "输入溯源" in captured and "md5" in captured and str(jp) in captured
    assert list(V) == payload["V_cm3"] and list(P) == payload["P_Pa"]


def test_load_curve_points_falls_back_to_labeled_hardcoded_demo(monkeypatch, capsys):
    fit = _import_fit()
    monkeypatch.setattr(fit, "_candidate_inputs", lambda: [])   # 强制输入不在场
    V, P, prov = fit.load_curve_points()
    captured = capsys.readouterr().out
    assert prov["source"] == "hardcoded_demo"
    assert prov["demo"] is True and prov["md5"] is None
    assert "硬编码演示值" in captured and "非归档真值" in captured
    assert list(V) == fit.DEMO_V and list(P) == fit.DEMO_P


def test_v6_curve_fit_import_is_side_effect_free(capsys):
    _import_fit()
    assert capsys.readouterr().out == "", "main guard 失效：import 即产生输出"


# ---------------------------------------------------------------- F4 / DF6 动态叙事
def test_recommendation_lines_are_dynamic_and_honest():
    fit = _import_fit()
    V, P = np.asarray(fit.DEMO_V, dtype=float), np.asarray(fit.DEMO_P, dtype=float)
    c = np.polyfit(V, P, 2)
    v30 = fit.solve_v30(c, 30.0)
    lines = fit.build_recommendation_lines(v30, V, P)
    text = "\n".join(lines)
    for bad in BANNED_WORDS:
        assert bad not in text
    assert "非临床建议" in text
    assert "反解占位" in text                    # 由 v30 动态生成
    assert "介于" not in text                    # 不再写死区间
    assert "1.2mm" not in text                   # 不再写死壳厚
    assert "4.238" not in text                   # 不再写死反解值
    # 括号说明必须等于纯函数的计算值（确实动态，非拼接写死）
    assert fit.describe_v30(v30, fit.build_tiers(V, P)) in text
    # 每个档位结论走统一 classify_demo_band
    for t in fit.build_tiers(V, P):
        assert fit.classify_demo_band(t["P_Pa"]) in text


def test_v30_none_branch_no_typeerror_and_no_format_of_none():
    fit = _import_fit()
    V, P = np.asarray(fit.DEMO_V, dtype=float), np.asarray(fit.DEMO_P, dtype=float)
    lines = fit.build_recommendation_lines(None, V, P)
    text = "\n".join(lines)
    assert "无正根" in text                     # None 分支
    assert "V ≈" not in text                    # 不对 None 用 :.1f
    assert "无正根" in fit.describe_v30(None, fit.build_tiers(V, P))
    assert fit.classify_demo_band(None) == "无 ΔP 数值（内部演示值缺失）"
    # solve_v30 在无正根时返回 None 而非抛错
    assert fit.solve_v30(np.array([1.0, 0.0, 100.0]), 30.0) is None


def test_build_tiers_is_data_driven_not_hardcoded():
    fit = _import_fit()
    V = np.array([0.0, 1.0, 2.0, 3.0])
    P = np.array([10.0, 20.0, 30.0, 40.0])
    tiers = fit.build_tiers(V, P)
    assert [t["V_cm3"] for t in tiers] == [1.0, 2.0, 3.0]
    assert [t["P_Pa"] for t in tiers] == [20.0, 30.0, 40.0]
    assert [t["label"] for t in tiers] == ["演示档位1", "演示档位2", "演示档位3"]


# ---------------------------------------------------------------- F3/F5 真实运行输出
def test_v6_curve_fit_stdout_is_honest_and_runs():
    env = dict(os.environ)
    for k in ("V6_CURVE_INPUT_JSON", "DATA_ROOT", "QIDI_WORKSPACE"):
        env.pop(k, None)
    env["PYTHONIOENCODING"] = "utf-8"
    out = subprocess.run([sys.executable, FIT], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", env=env, timeout=120)
    assert out.returncode == 0, "stderr:\n" + out.stderr
    txt = out.stdout
    for bad in BANNED_WORDS:
        assert bad not in txt, "v6 输出仍含 %r" % bad
    assert "演示" in txt
    assert "仿真探索结论，非临床建议" in txt     # DF5 承诺义表述已清除
    assert "输入溯源" in txt                     # DF4 溯源打印在场
    assert "无正根" in txt or "V ≈" in txt       # DF6 动态叙事在场
