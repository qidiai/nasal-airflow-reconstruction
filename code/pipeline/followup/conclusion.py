"""Course conclusion card for the follow-up diff."""

from __future__ import annotations


def _row(diff: dict, key: str) -> dict | None:
    return next((r for r in diff["rows"] if r["key"] == key), None)


def _fmt_row(r: dict | None, unit: str = "", signed: bool = True) -> str:
    if r is None or r["delta"] is None:
        return "—"
    d = r["digits"]
    val = r["delta"]
    txt = f"{val:+,.{d}f}" if signed else f"{val:.{d}f}"
    if unit:
        txt += f" {unit}"
    if r["pct"] is not None:
        txt += f"（{r['pct']:+.1f}%）"
    return txt


def course_card(diff: dict, registration: dict | None = None, params_a: dict | None = None, params_b: dict | None = None) -> dict:
    """Build the one-card course conclusion and its explicit caveats."""
    r_area = _row(diff, "left_nostril_area_mm2")
    r_share = _row(diff, "split_L_pct")
    r_dpl = _row(diff, "dP_L_Pa")
    r_dp = _row(diff, "dP_Pa")
    r_dpr = _row(diff, "dP_R_Pa")
    r_vol = _row(diff, "volume_cm3")

    sentences = []
    if r_area and r_area["delta"] is not None:
        sentences.append(f"左鼻孔最小截面 {_fmt_row(r_area, 'mm²')}")
    if r_share and r_share["delta"] is not None:
        sentences.append(f"左侧流量份额 {r_share['delta']:+.2f} 个百分点（{r_share['pct']:+.1f}%）")
    if r_dpl and r_dpl["delta"] is not None:
        sentences.append(f"左侧压降 {_fmt_row(r_dpl, 'Pa')}")
    if r_vol and r_vol["delta"] is not None:
        sentences.append(f"气道容积 {_fmt_row(r_vol, 'cm³')}")

    lead = "较上次（A → B）：" + "；".join(sentences) + "。" if sentences else "本次差异不足以形成病程结论。"

    caveats = []
    if r_dp and r_dpr and r_dpl:
        # If total / right pressure move opposite to the controlled side, say so.
        signs = {
            "总压降": r_dp["delta"],
            "右侧压降": r_dpr["delta"],
            "左侧压降": r_dpl["delta"],
        }
        if (signs["左侧压降"] is not None and signs["总压降"] is not None
                and signs["左侧压降"] * signs["总压降"] < 0):
            caveats.append(
                f"总压降 {_fmt_row(r_dp, 'Pa')} 与左侧压降方向相反；"
                f"右侧压降 {_fmt_row(r_dpr, 'Pa')}。总压降/右侧压降不构成对左鼻孔参数的单向响应，"
                "不能据此做剂量-反应结论。"
            )
    if registration:
        caveats.append(
            f"配准：{registration.get('method', 'cKDTree + ICP')}；"
            f"RMS {registration.get('rms_mm', float('nan')):.3f} mm，"
            f"中位 {registration.get('median_mm', float('nan')):.3f} mm，"
            f"P95 {registration.get('p95_mm', float('nan')):.3f} mm，"
            f"最大 {registration.get('max_mm', float('nan')):.3f} mm。"
        )
        if registration.get("rms_mm", 0) > 2.0:
            caveats.append("配准 RMS > 2 mm：几何差只作定位线索，不能作为毫米级病程结论。")
    caveats.append("两例均为 1500 步平台（未达 residualControl 1e-4）；指标差异含收敛噪声。")
    caveats.append("Run-A 定流量按面积分配；分流份额是建模假设，不是患者真实分流测量。")
    caveats.append("STL 体积（marching-cubes 表面）与 polyMesh 体积（单元体积和）口径不同，分别报告。")
    caveats.append("轴向截面积不垂直于中心线；最小截面为轴向切片口径。")

    return {
        "headline": lead,
        "caveats": caveats,
        "rows_used": [r["key"] for r in (r_area, r_share, r_dpl, r_vol) if r],
    }


def patient_followup_sentence(diff: dict) -> str:
    """Descriptive sentence suitable for a patient-facing follow-up card."""
    r_area = _row(diff, "left_nostril_area_mm2")
    r_share = _row(diff, "split_L_pct")
    r_dpl = _row(diff, "dP_L_Pa")
    parts = ["与上次检查相比："]
    if r_area and r_area["pct"] is not None:
        parts.append(f"左鼻孔最窄处的截面变化约 {r_area['pct']:+.1f}%；")
    if r_share and r_share["delta"] is not None:
        parts.append(f"左侧气流分配的份额变化约 {r_share['delta']:+.1f} 个百分点；")
    if r_dpl and r_dpl["pct"] is not None:
        parts.append(f"左侧的压力差变化约 {r_dpl['pct']:+.1f}%。")
    parts.append("这些是本次模拟的描述性结果，不是诊断结论；请结合医生对两次影像的判断。")
    return "".join(parts)
