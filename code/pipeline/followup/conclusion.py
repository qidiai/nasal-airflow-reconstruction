"""Course conclusion card for the follow-up diff."""

from __future__ import annotations


# 合成体模标注（DF7）：case_kind == "synthetic" 时注入 headline / caveats / 患者语言句三处。
SYNTHETIC_MARK = "本轮为合成体模、非真实患者、非临床结论"


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


def _case_convergence(p: dict | None) -> tuple[str, int | None]:
    """把单例的 converged / iterations 归为四态，供据实生成 caveat（DF2）。

    converged=True -> "converged"；converged=False 且步数=1500 -> "plateau"；
    converged=False 且步数≠1500 -> "other"；判据缺失 -> "unknown"。
    """
    if not isinstance(p, dict):
        return ("unknown", None)
    conv = p.get("converged")
    steps = p.get("iterations")
    if conv is True:
        return ("converged", int(steps) if isinstance(steps, (int, float)) else None)
    if conv is False:
        if isinstance(steps, (int, float)):
            return ("plateau" if steps == 1500 else "other", int(steps))
        return ("unknown", None)
    return ("unknown", None)


def _steps_text(n: int | None) -> str:
    return f"{n} 步" if n is not None else "步数未记录"


def _convergence_caveat(params_a: dict | None, params_b: dict | None) -> str:
    """DF2：收敛 caveat 由两例 converged / iterations 生成，不再无条件写死 1500 步平台。

    三态：已收敛 → 「已达 residualControl」；未收敛 → 按实际步数（含非 1500 步）；
    任一判据缺失 → 「收敛状态未知」。
    """
    sa = _case_convergence(params_a)
    sb = _case_convergence(params_b)
    if sa[0] == "unknown" or sb[0] == "unknown":
        return "收敛状态未知：两例 converged/迭代步记录缺失，指标差异不作收敛性结论。"
    if sa[0] == "converged" and sb[0] == "converged":
        return (
            f"两例均已达 residualControl 1e-4（A {_steps_text(sa[1])}、B {_steps_text(sb[1])}，"
            "提前收敛）；指标差异按收敛结果解读，不含平台收敛噪声。"
        )
    parts = []
    for label, (state, steps) in (("A", sa), ("B", sb)):
        if state == "converged":
            parts.append(f"{label} {_steps_text(steps)}已达 residualControl 1e-4")
        else:
            parts.append(f"{label} 跑至 {_steps_text(steps)}未达 residualControl 1e-4")
    return "；".join(parts) + "；指标差异含收敛噪声，未收敛平台值不作收敛性结论。"


def course_card(
    diff: dict,
    registration: dict | None = None,
    params_a: dict | None = None,
    params_b: dict | None = None,
    case_kind: str | None = None,
) -> dict:
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
    # DF3：逐行判定「与左侧压降方向相反」，只把实际触发的行写进 caveat——
    # 总压降与右侧压降各自独立参与，注释/正文与实际判定一致，不承诺未触发的检查。
    if r_dpl and r_dpl["delta"] is not None:
        left = r_dpl["delta"]
        opposite = []
        for row, label in ((r_dp, "总压降"), (r_dpr, "右侧压降")):
            if row is not None and row["delta"] is not None and left * row["delta"] < 0:
                opposite.append((label, row))
        if opposite:
            detail = "；".join(
                f"{label} {_fmt_row(row, 'Pa')} 与左侧压降方向相反" for label, row in opposite
            )
            joined = "/".join(label for label, _ in opposite)
            caveats.append(
                f"{detail}。{joined}不构成对左鼻孔参数的单向响应，不能据此做剂量-反应结论。"
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
    caveats.append(_convergence_caveat(params_a, params_b))
    caveats.append("Run-A 定流量按面积分配；分流份额是建模假设，不是患者真实分流测量。")
    caveats.append("STL 体积（marching-cubes 表面）与 polyMesh 体积（单元体积和）口径不同，分别报告。")
    caveats.append("轴向截面积不垂直于中心线；最小截面为轴向切片口径。")

    synthetic = case_kind == "synthetic"
    if synthetic:
        lead = f"【{SYNTHETIC_MARK}】{lead}"
        caveats.append(
            f"{SYNTHETIC_MARK}（合成演示数据）：涉及数值/比较均为内部演示值，"
            "非归档真值，不作临床判读（T12 定稿后由 T11 对账）。"
        )

    return {
        "headline": lead,
        "caveats": caveats,
        "rows_used": [r["key"] for r in (r_area, r_share, r_dpl, r_vol) if r],
    }


def patient_followup_sentence(diff: dict, case_kind: str | None = None) -> str:
    """Descriptive sentence suitable for a patient-facing follow-up card.

    case_kind == "synthetic" 时整句标注合成体模（DF7），与 headline / caveats 同源。
    """
    r_area = _row(diff, "left_nostril_area_mm2")
    r_share = _row(diff, "split_L_pct")
    r_dpl = _row(diff, "dP_L_Pa")
    parts = []
    if case_kind == "synthetic":
        parts.append(f"【{SYNTHETIC_MARK}】")
    parts.append("与上次检查相比：")
    if r_area and r_area["pct"] is not None:
        parts.append(f"左鼻孔最窄处的截面变化约 {r_area['pct']:+.1f}%；")
    if r_share and r_share["delta"] is not None:
        parts.append(f"左侧气流分配的份额变化约 {r_share['delta']:+.1f} 个百分点；")
    if r_dpl and r_dpl["pct"] is not None:
        parts.append(f"左侧的压力差变化约 {r_dpl['pct']:+.1f}%。")
    if case_kind == "synthetic":
        parts.append("以上为合成演示数据的描述性结果，不是诊断结论，也不对应任何真实患者的两次影像。")
    else:
        parts.append("这些是本次模拟的描述性结果，不是诊断结论；请结合医生对两次影像的判断。")
    return "".join(parts)
