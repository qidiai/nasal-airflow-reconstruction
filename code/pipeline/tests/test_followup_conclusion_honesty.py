# -*- coding: utf-8 -*-
"""T10-b 结论层口径批修·followup 侧锁死用例（DF2/DF3/DF7/DF18）。

钉住：
  F1 收敛 caveat 据实生成 —— converged/iterations 三态（已收敛 / 非 1500 步按实际步数 /
     数据缺失「收敛状态未知」）各有正确文案；旧写死串「两例均为 1500 步平台…」零残留；
  F2 方向相反守卫补右侧 —— 总压降/右侧压降逐行独立判定，只输出实际触发行，
     右侧假阴性（R-009 对称检验）不再漏判，注释/正文/实际一致；
  F3 合成体模标注链 —— course_card / patient_followup_sentence 有 case_kind 入参，
     run_diff 透传；case_kind == "synthetic" 时 headline/caveats/患者语言句三处均有
     「本轮为合成体模、非真实患者、非临床结论」标注；
  DF18/DF7 examples/diff.md —— 真跑重生成后三处标注在位、格式与当前 HEAD 输出一致
     （中央 80% 区间 + 全局最小截面口径），旧写死串与旧「切片最小截面（全局）」消失；
  F4 演示值路线 —— 合成标注 caveat 显式「内部演示值 / 非归档真值」，不引归档真值。

不 import run_diff（其 geometry/registration 依赖 scipy/trimesh，且带 sys.path 副作用）：
对 run_diff.py / conclusion.py 的透传与写死串一律用源码级断言，行为侧只 import 纯 Python 的
followup.conclusion。examples/diff.md 为随库分发副本，按文本段落钉三处标注与格式。
"""
from __future__ import annotations

import inspect
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.dirname(HERE)
FOLLOWUP = os.path.join(PIPELINE, "followup")
CONCLUSION_SRC = os.path.join(FOLLOWUP, "conclusion.py")
RUN_DIFF_SRC = os.path.join(FOLLOWUP, "run_diff.py")
DIFF_MD = os.path.join(FOLLOWUP, "examples", "diff.md")

if PIPELINE not in sys.path:
    sys.path.insert(0, PIPELINE)

import followup.conclusion as conclusion  # noqa: E402

MARK = conclusion.SYNTHETIC_MARK
OLD_PLATEAU = "两例均为 1500 步平台（未达 residualControl 1e-4）；指标差异含收敛噪声。"


def _src(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _row(key, delta, pct=None, digits=2):
    return {"key": key, "delta": delta, "pct": pct, "digits": digits,
            "label": key, "unit": "", "a": 0.0, "b": 0.0, "direction": "→"}


def _mk_diff(dp, dpl, dpr):
    """构造含方向判定所需 6 行的最小 diff（其余键取固定演示值）。"""
    return {
        "rows": [
            _row("left_nostril_area_mm2", 1.534, 102.9),
            _row("split_L_pct", 6.65, 184.6),
            _row("dP_L_Pa", dpl, -34.6),
            _row("dP_Pa", dp, 72.0),
            _row("dP_R_Pa", dpr, 81.5),
            _row("volume_cm3", 0.0, 0.0),
        ],
        "a": {}, "b": {},
    }


def _caveats_text(diff, **kw):
    return "\n".join(conclusion.course_card(diff, **kw)["caveats"])


def _section(text, start, end=None):
    i = text.index(start)
    j = text.index(end, i) if end else len(text)
    return text[i:j]


# ---------------------------------------------------------------- F1 / DF2 收敛 caveat
def test_converged_caveat_says_reached_residualcontrol():
    cav = _caveats_text(_mk_diff(44.65, -105.02, 43.20),
                        params_a={"converged": True, "iterations": 812},
                        params_b={"converged": True, "iterations": 870})
    assert "已达 residualControl 1e-4" in cav
    assert "812" in cav and "870" in cav          # 按实际步数
    assert "收敛状态未知" not in cav
    assert OLD_PLATEAU not in cav


def test_non_1500_steps_caveat_uses_actual_counts():
    cav = _caveats_text(_mk_diff(44.65, -105.02, 43.20),
                        params_a={"converged": False, "iterations": 970},
                        params_b={"converged": False, "iterations": 1234})
    assert "970" in cav and "1234" in cav        # 非 1500 步按实际步数
    assert "1500 步平台" not in cav             # 不写死 1500 步平台
    assert "未达 residualControl 1e-4" in cav
    assert OLD_PLATEAU not in cav


def test_plateau_1500_caveat_is_data_driven_not_hardcoded():
    cav = _caveats_text(_mk_diff(44.65, -105.02, 43.20),
                        params_a={"converged": False, "iterations": 1500},
                        params_b={"converged": False, "iterations": 1500})
    assert "1500" in cav                         # 由数据带来的 1500
    assert OLD_PLATEAU not in cav                # 但旧写死串已消失
    assert "未收敛平台值不作收敛性结论" in cav


@pytest.mark.parametrize("pa,pb", [
    (None, None),
    (None, {"converged": True, "iterations": 870}),
    ({"converged": False}, {"converged": True, "iterations": 870}),  # 缺 iterations
    ({}, {}),                                                          # 两例判据全缺
])
def test_missing_data_caveat_is_unknown(pa, pb):
    cav = _caveats_text(_mk_diff(44.65, -105.02, 43.20), params_a=pa, params_b=pb)
    assert "收敛状态未知" in cav
    assert "已达 residualControl" not in cav
    assert OLD_PLATEAU not in cav


def test_mixed_convergence_states_are_reported_per_case():
    cav = _caveats_text(_mk_diff(44.65, -105.02, 43.20),
                        params_a={"converged": True, "iterations": 812},
                        params_b={"converged": False, "iterations": 1500})
    assert "已达 residualControl 1e-4" in cav   # A 已收敛
    assert "跑至 1500 步未达" in cav            # B 未收敛（按实际步数）
    assert "收敛状态未知" not in cav


def test_caveat_changes_with_input_data():
    a = _caveats_text(_mk_diff(1, -1, 1), params_a={"converged": True, "iterations": 100},
                      params_b={"converged": True, "iterations": 200})
    b = _caveats_text(_mk_diff(1, -1, 1), params_a={"converged": False, "iterations": 700},
                      params_b={"converged": False, "iterations": 800})
    assert a != b, "caveat 必须由数据生成，不能是对所有输入恒等的写死串"


def test_old_plateau_literal_absent_from_source():
    assert OLD_PLATEAU not in _src(CONCLUSION_SRC)
    assert "caveats.append(\"两例均为 1500 步平台" not in _src(CONCLUSION_SRC)


def test_convergence_caveat_built_from_params_not_unconditional():
    src = _src(CONCLUSION_SRC)
    assert "_convergence_caveat(params_a, params_b)" in src
    assert "_case_convergence" in src
    assert "converged" in src and "iterations" in src


# ---------------------------------------------------------------- F2 / DF3 方向相反守卫
def test_right_only_opposite_is_caught_no_false_negative():
    # 左侧 -5；总压降 -3（同向，不触发）；右侧 +8（反向，触发）。
    cav = _caveats_text(_mk_diff(dp=-3.0, dpl=-5.0, dpr=8.0))
    assert "右侧压降" in cav and "方向相反" in cav
    assert "总压降" not in cav, "只触发右侧时不得承诺总压降方向相反"


def test_total_only_opposite_reports_only_total():
    # 左侧 -5；总压降 +3（反向，触发）；右侧 -8（同向，不触发）。
    cav = _caveats_text(_mk_diff(dp=3.0, dpl=-5.0, dpr=-8.0))
    assert "总压降" in cav and "方向相反" in cav
    assert "右侧压降" not in cav, "只触发总压降时不得承诺右侧压降方向相反"


def test_both_opposite_reports_both_rows():
    cav = _caveats_text(_mk_diff(dp=3.0, dpl=-5.0, dpr=8.0))
    assert "总压降" in cav and "右侧压降" in cav
    assert "/".join(["总压降", "右侧压降"]) in cav


def test_symmetry_under_sign_flip_r009():
    # 全量反号：对称性要求两侧仍都触发（不能只对某一种朝向生效）。
    cav = _caveats_text(_mk_diff(dp=-3.0, dpl=5.0, dpr=-8.0))
    assert "总压降" in cav and "右侧压降" in cav


def test_no_opposite_row_produces_no_direction_caveat():
    cav = _caveats_text(_mk_diff(dp=-3.0, dpl=-5.0, dpr=-8.0))
    assert "方向相反" not in cav
    assert "不构成对左鼻孔参数的单向响应" not in cav


def test_direction_guard_comment_matches_per_row_logic():
    src = _src(CONCLUSION_SRC)
    assert "只把实际触发的行写进 caveat" in src
    assert 'for row, label in ((r_dp, "总压降"), (r_dpr, "右侧压降"))' in src
    assert 'left * row["delta"] < 0' in src


# ---------------------------------------------------------------- F3 / DF7 合成标注链
def test_synthetic_marks_all_three_places():
    d = _mk_diff(44.65, -105.02, 43.20)
    card = conclusion.course_card(d, case_kind="synthetic")
    sentence = conclusion.patient_followup_sentence(d, case_kind="synthetic")
    assert MARK in card["headline"]                       # ① headline
    assert any(MARK in c for c in card["caveats"])         # ② caveats
    assert MARK in sentence                               # ③ 患者语言句


@pytest.mark.parametrize("kind", [None, "patient", "patient_demo", "unknown"])
def test_non_synthetic_has_no_mark(kind):
    d = _mk_diff(44.65, -105.02, 43.20)
    card = conclusion.course_card(d, case_kind=kind)
    sentence = conclusion.patient_followup_sentence(d, case_kind=kind)
    assert MARK not in card["headline"]
    assert not any(MARK in c for c in card["caveats"])
    assert MARK not in sentence


def test_case_kind_is_in_both_signatures():
    for fn in (conclusion.course_card, conclusion.patient_followup_sentence):
        params = inspect.signature(fn).parameters
        assert "case_kind" in params
        assert params["case_kind"].default is None


def test_synthetic_caveat_declares_demo_value_route_f4():
    cav = _caveats_text(_mk_diff(44.65, -105.02, 43.20), case_kind="synthetic")
    assert "内部演示值" in cav and "非归档真值" in cav
    assert "不作临床判读" in cav


def test_run_diff_passes_case_kind_and_real_params():
    src = _src(RUN_DIFF_SRC)
    # DF7 透传
    assert "case_kind: str | None = None" in src
    assert "case_kind=case_kind" in src                       # → course_card
    assert "patient_followup_sentence(mdiff, case_kind=case_kind)" in src
    assert '"case_kind": case_kind' in src                    # 结果留痕
    assert "--case-kind" in src and "case_kind=args.case_kind" in src
    # DF2 据实传参
    assert "params_a=params_a, params_b=params_b" in src
    assert "def _solve_params" in src
    assert "conclusion.course_card(mdiff, registration=reg)" not in src  # 旧无参调用已删
    # 标注链回填（provenance.json）
    assert "def _case_kind_from_provenance" in src
    assert "data_class" in src and '"synthetic"' in src


def test_case_kind_marker_constant_is_shared():
    src = _src(CONCLUSION_SRC)
    assert 'SYNTHETIC_MARK = "本轮为合成体模、非真实患者、非临床结论"' in src
    # 三处注入点（headline / caveats / 患者语言句）都引用同一常量
    assert src.count("SYNTHETIC_MARK") >= 4


# ---------------------------------------------------------------- DF7 / DF18 examples/diff.md
def test_examples_diff_md_three_marks_in_three_sections():
    text = _src(DIFF_MD)
    headline = _section(text, "## 1. 病程结论卡", "### 需要注意")
    caveats = _section(text, "### 需要注意", "## 2. 配准精度")
    patient = _section(text, "## 6. 患者语言层", "## 7. 方法与边界")
    assert MARK in headline, "headline 缺合成标注"
    assert MARK in caveats, "caveats 缺合成标注"
    assert MARK in patient, "患者语言层缺合成标注"
    assert text.count(MARK) >= 3


def test_examples_diff_md_no_hardcoded_plateau_and_no_real_patient_instruction():
    text = _src(DIFF_MD)
    assert OLD_PLATEAU not in text
    assert "请结合医生对两次影像的判断" not in text       # 合成副本不得留真实随访话术
    assert "非真实患者" in text


def test_examples_diff_md_format_synced_to_current_output_df18():
    text = _src(DIFF_MD)
    # 当前 HEAD write_markdown 的中央 80% + 全局最小截面口径（旧副本只有「（全局）」）
    assert "切片最小截面（中央 80% 区间）" in text
    assert "全局最小截面：" in text
    assert "切片最小截面（全局）" not in text
    assert "## 7. 方法与边界" in text
    # 数据驱动的收敛 caveat 在位
    assert "跑至 1500 步未达 residualControl 1e-4" in text
    # 真跑重生成后数值与旧副本一致（指标差表逐位不变）
    assert "| 总压降 ΔP | 62.04 Pa | 106.69 Pa | +44.65 | +71.97% |" in text
    assert "| 左鼻孔最小截面 | 1.491 mm² | 3.025 mm² | +1.534 | +102.88% |" in text
