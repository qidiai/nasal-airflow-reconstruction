"""Patient-facing wording rules for the M4 single-file report.

Authority chain
---------------
The M4 task book points at a "患者措辞节" in ``docs/contracts/``.  That section
does not exist in this repository at the time of writing (the contracts folder
only contains the numerical contract, the validation baselines and the M1-track-A
board).  ``docs/contracts/`` is outside the M4 file domain, so this module does
not invent or edit it.  Instead it implements the rules that are already frozen
in the planning/audit documents:

* ``规划-v2.3.2`` §2.2: a one-sentence patient conclusion, **no population
  percentile wording**; the percentile feature stays disabled until a baseline
  exists.
* ``审计-规划v2.1-GLM53`` A2: the patient copy must be educational/descriptive;
  the forbidden list is 偏窄 / 狭窄 / 正常 / 异常 / 健康人群分位对比 / 诊断 /
  手术指征.
* ``审计-规划v2.1-KIMI27`` F-12: no P85/P92-style comparison in any external
  material before a norm is built.

The whitelist below is deliberately conservative: it is better to say less than
to slide into a diagnostic or population-comparison claim.
"""

from __future__ import annotations

import re
from typing import Iterable

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Population percentile / norm wording.  These are forbidden in *every* layer of
# the report, not just the patient card, because the acceptance check greps the
# generated HTML for them.
PERCENTILE_PATTERNS = [
    (re.compile(r"分位|百分位|percentile", re.IGNORECASE), "人群分位/百分位表述"),
    (re.compile(r"\bP(?:[5-9]\d|100)\b", re.IGNORECASE), "P85/P92/P95 类分位标记"),
    (re.compile(r"第\s*\d+\s*百分位"), "百分位表述"),
    (re.compile(r"人群常模|常模带|健康人群分位"), "人群常模表述"),
]

# Population comparison wording.  Also forbidden everywhere: the 27-case set is
# not a healthy-population norm (0 normal controls; audit v2.1-F-02).
POPULATION_PATTERNS = [
    (re.compile(r"健康人群|正常人群|健康人|正常人|常人带|正常带"), "人群对照表述"),
    (re.compile(r"人群参考区间|人群参考范围"), "人群参考区间表述"),
]

# Diagnostic / treatment claims.  Forbidden in the patient card.  The fixed
# disclaimer is allowed to say "不是诊断结论" (a negation), so the patterns below
# target positive claims only.
DIAGNOSTIC_PATTERNS = [
    (re.compile(r"确诊|诊断为|病情为|患有"), "诊断性表述"),
    (re.compile(r"手术指征|需要手术|建议手术|可以手术|应考虑手术"), "治疗建议/手术指征"),
]

# Disease/narrowing labels.  The audit A2 list explicitly removes 偏窄 and 狭窄
# from patient copy; the technical section may still say "最窄截面" because it
# is a geometric definition, not a diagnosis.
NARROWING_PATTERNS = [
    (re.compile(r"偏窄|狭窄"), "疾病化狭窄表述"),
]

PATIENT_BANNED = PERCENTILE_PATTERNS + POPULATION_PATTERNS + DIAGNOSTIC_PATTERNS + NARROWING_PATTERNS
REPORT_BANNED = PERCENTILE_PATTERNS + POPULATION_PATTERNS

# Phrases that are explicitly allowed in the patient layer.  This is a positive
# whitelist used by the self-check to prove that the conclusion card contains
# descriptive language rather than a diagnosis.
PATIENT_WHITELIST = [
    "影像与气流模拟显示",
    "本次模拟结果",
    "本次报告只描述",
    "不是诊断结论",
    "请咨询医生",
    "与参考范围相比",
    "两侧气流分配不完全对称",
    "截面相对较小",
    "气流更多从另一侧通过",
    "合成数据示例",
    "非真人",
]


def _hits(text: str, patterns: Iterable[tuple[re.Pattern, str]]) -> list[dict]:
    out = []
    for pattern, label in patterns:
        for m in pattern.finditer(text):
            out.append({"label": label, "match": m.group(0), "start": m.start()})
    return out


def assert_patient_safe(text: str) -> None:
    """Raise ``ValueError`` if patient-facing text breaks the whitelist."""
    hits = _hits(text, PATIENT_BANNED)
    if hits:
        raise ValueError(
            "患者措辞白名单违规: "
            + "; ".join(f"{h['label']} -> {h['match']!r}" for h in hits[:5])
        )


def assert_report_safe(html: str) -> None:
    """Raise ``ValueError`` if the report contains population-percentile text."""
    # Base64 image payloads can accidentally contain "P61"-like substrings;
    # only the visible document text is subject to the wording rules.
    visible = re.sub(r"data:image/[^\"']+", "DATA_URI", html)
    hits = _hits(visible, REPORT_BANNED)
    if hits:
        raise ValueError(
            "报告含人群分位/人群对照表述: "
            + "; ".join(f"{h['label']} -> {h['match']!r}" for h in hits[:5])
        )


def scan_text(text: str, patient_layer: bool = False) -> list[dict]:
    """Return all whitelist violations (used by the self-check scripts)."""
    patterns = PATIENT_BANNED if patient_layer else REPORT_BANNED
    return _hits(text, patterns)


# ---------------------------------------------------------------------------
# One-sentence conclusion
# ---------------------------------------------------------------------------


def _fmt(x: float | None, digits: int = 1) -> str:
    if x is None:
        return "—"
    return f"{x:.{digits}f}"


def _split_sentence(split_l: float | None, split_r: float | None, synthetic: bool = False) -> str:
    if split_l is None or split_r is None:
        return "本次报告未提供左右两侧的气流分配数值。"
    subject = "模型两侧通道" if synthetic else "您两侧鼻腔"
    return (
        f"{subject}都有气流通过，左侧约 {_fmt(split_l)}%，"
        f"右侧约 {_fmt(split_r)}%。"
    )


def _pressure_sentence(dp: float | None) -> str:
    if dp is None:
        return "本次报告未提供压力差数值。"
    return f"两侧入口的平均压力差约为 {_fmt(dp, 1)} Pa。"


def _section_sentence(area: float | None, scope: str | None) -> str:
    if area is None:
        return ""
    if scope == "left_nostril":
        return (
            f"模型设计为一侧鼻孔的通道截面相对较小（约 {_fmt(area, 2)} mm²），"
            "气流更多从另一侧通过。"
        )
    if scope == "axial_total":
        return (
            f"沿气道轴向，最窄处的总截面约为 {_fmt(area, 1)} mm²；"
            "气流经过这段截面较小的位置时速度会升高。"
        )
    return (
        f"本次记录的主气道最小截面约为 {_fmt(area, 1)} mm²；"
        "气流经过截面较小的位置时速度会升高。"
    )


def _convergence_sentence(converged: bool | None, iterations: int | None) -> str:
    if converged is True:
        return "本次计算已满足设定的收敛判据。"
    if converged is False:
        n = f"{iterations} 步" if iterations else "设定的步数上限"
        return (
            f"本次计算在 {n}达到平台，尚未满足严格收敛判据；"
            "数值用于描述趋势，不作为精确测量。"
        )
    return "本次计算未记录收敛判据。"


def compose_patient_conclusion(
    *,
    case_kind: str,
    split_l: float | None,
    split_r: float | None,
    dp_pa: float | None,
    min_area_mm2: float | None,
    min_area_scope: str | None,
    converged: bool | None,
    iterations: int | None,
    has_reference_range: bool = False,
) -> str:
    """Compose the one-sentence patient conclusion.

    The text is deliberately descriptive: it states what the simulation shows,
    never what the patient has, and never compares to a population percentile.
    """
    if case_kind == "synthetic":
        head = (
            "这是一份合成数据示例（非真人），用于验证报告引擎："
        )
    else:
        head = "影像与气流模拟显示："

    parts = [
        head + _split_sentence(split_l, split_r, synthetic=(case_kind == "synthetic")),
        _pressure_sentence(dp_pa),
    ]
    section = _section_sentence(min_area_mm2, min_area_scope)
    if section:
        parts.append(section)
    parts.append(_convergence_sentence(converged, iterations))

    if has_reference_range:
        parts.append(
            "与参考范围相比，本次结果需要结合医生对影像的判断；"
            "本次报告只描述模拟结果，不是诊断结论，请咨询医生。"
        )
    elif case_kind == "synthetic":
        parts.append(
            "本次未使用人群对照，报告只描述这个合成模型的模拟结果；"
            "这不是诊断结论，仅用于技术验证。"
        )
    else:
        parts.append(
            "本次未使用人群对照，报告只描述本例自身的模拟结果；"
            "这不是诊断结论，请咨询医生结合影像判断。"
        )

    text = "".join(parts)
    # A final guard: the composed sentence must itself pass the strict layer.
    assert_patient_safe(text)
    return text
