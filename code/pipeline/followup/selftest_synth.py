"""Self-test: synth-001 vs synth-005 (known design difference).

The controlled design difference is the left nostril minimum area:
synth-001 a_min = 1.5 mm², synth-005 a_min = 4.0 mm².  The engine must reproduce
the expected directions:

* left nostril section: larger in B;
* left flow share: larger in B;
* left-side pressure drop: smaller in B;
* airway volume: essentially unchanged (both 105 cm³);
* registration: sub-2 mm RMS on the same synthetic template;
* vertex difference: localized, not a global mismatch.

The total pressure drop and the right-side pressure drop move in the opposite
direction because the Run-A split is area-proportional and the right path also
changes with the seed; those two rows are recorded but **not** asserted as a
monotone response to the left-nostril parameter.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from followup import metrics  # noqa: E402
from followup.run_diff import run_pair, write_markdown  # noqa: E402

A = HERE.parent / "out" / "synth" / "synth-001"
B = HERE.parent / "out" / "synth" / "synth-005"
OUT = HERE / "out" / "selftest-synth-001-vs-005"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    print("[selftest] running synth-001 vs synth-005 ...")
    result = run_pair(A, B, skip_polymesh=False, n_slices=80)
    ma = metrics.load_case_metrics(A)
    mb = metrics.load_case_metrics(B)

    checks = []

    def add(name: str, ok: bool, detail: str, expected: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail, "expected": expected})

    add(
        "左鼻孔最小截面增大",
        (mb.get("left_nostril_area_mm2") or 0) > (ma.get("left_nostril_area_mm2") or 0),
        f"{ma.get('left_nostril_area_mm2')} → {mb.get('left_nostril_area_mm2')} mm²",
        "B > A（设计 1.5 → 4.0 mm²）",
    )
    add(
        "左侧流量份额增大",
        (mb.get("split_L_pct") or 0) > (ma.get("split_L_pct") or 0),
        f"{ma.get('split_L_pct'):.3f}% → {mb.get('split_L_pct'):.3f}%",
        "B > A",
    )
    add(
        "左侧压降下降",
        (mb.get("dP_L_Pa") or 1e9) < (ma.get("dP_L_Pa") or -1e9),
        f"{ma.get('dP_L_Pa'):.3f} → {mb.get('dP_L_Pa'):.3f} Pa",
        "B < A",
    )
    vol_pct = result["geometry_stl"]["volume_delta_pct"]
    add(
        "气道容积基本不变",
        vol_pct is not None and abs(vol_pct) <= 2.0,
        f"{result['geometry_stl']['a']['volume_cm3']:.3f} → {result['geometry_stl']['b']['volume_cm3']:.3f} cm³（{vol_pct:+.3f}%）",
        "|Δ| ≤ 2%",
    )
    add(
        "配准 RMS < 2 mm",
        result["registration"]["rms_mm"] < 2.0,
        f"RMS {result['registration']['rms_mm']:.3f} mm；中位 {result['registration']['median_mm']:.3f} mm",
        "RMS < 2 mm",
    )
    vd = result["geometry_stl"]["vertex_diff"]["a_to_b"]
    n_a = result["geometry_stl"]["vertex_diff"]["n_a"]
    frac2 = vd["count_gt_2mm"] / max(n_a, 1)
    add(
        "顶点差定位到局部",
        vd["max_mm"] > 0.5 and vd["median_mm"] < 1.0 and frac2 < 0.10,
        f"max {vd['max_mm']:.3f} mm；中位 {vd['median_mm']:.3f} mm；"
        f">2 mm 顶点 {vd['count_gt_2mm']}（{frac2*100:.2f}%）",
        "max > 0.5 mm、中位 < 1 mm、>2 mm 占比 < 10%",
    )

    # Direction table for the non-asserted rows.
    rows = {r["key"]: r for r in result["metrics"]["rows"]}
    notes = []
    for key in ("dP_Pa", "dP_R_Pa"):
        r = rows.get(key)
        if r and r["delta"] is not None:
            notes.append(
                f"{r['label']}：{r['a']:.3f} → {r['b']:.3f}（{r['delta']:+.3f}，{r['pct']:+.2f}%），"
                "方向与左侧相反，未作方向性断言。"
            )
    notes.append(
        "两例均跑到 1500 步平台（未达 residualControl 1e-4）；分流为 Run-A 按面积分配的建模假设。"
    )

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "pair": {"a": str(A), "b": str(B)},
        "checks": checks,
        "all_pass": all(c["ok"] for c in checks),
        "not_asserted_directions": notes,
        "registration": result["registration"],
        "metrics": result["metrics"],
        "geometry_stl_summary": {
            "a": result["geometry_stl"]["a"],
            "b": result["geometry_stl"]["b"],
            "volume_delta_pct": vol_pct,
            "vertex_diff": result["geometry_stl"]["vertex_diff"],
        },
        "geometry_polymesh_summary": result.get("geometry_polymesh", {}).get("a") if result.get("geometry_polymesh") else None,
        "course_card": result["course_card"],
        "full_diff": "diff.json",
    }
    (OUT / "selftest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "diff.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    write_markdown(result, OUT / "diff.md", "synth-001", "synth-005")

    md = [
        "# 随访 diff 引擎自测 · synth-001 → synth-005",
        "",
        f"- 生成：{payload['generated_at']}",
        "- 设计差异：左鼻孔 a_min 1.5 mm² → 4.0 mm²（其余设计参数相同或由 seed 决定）",
        "",
        "## 断言结果",
        "",
        "| # | 断言 | 结果 | 实测 | 期望 |",
        "|---|---|---|---|---|",
    ]
    for i, c in enumerate(checks, 1):
        md.append(f"| {i} | {c['name']} | {'PASS' if c['ok'] else 'FAIL'} | {c['detail']} | {c['expected']} |")
    md += [
        "",
        f"**总判定：{'PASS' if payload['all_pass'] else 'FAIL'}**",
        "",
        "## 未作方向性断言的行（如实）",
        "",
    ]
    md += [f"- {n}" for n in notes]
    md += [
        "",
        "## 配准精度",
        "",
        f"- {result['registration']['method']}",
        f"- RMS {result['registration']['rms_mm']:.3f} mm；中位 {result['registration']['median_mm']:.3f} mm；"
        f"P95 {result['registration']['p95_mm']:.3f} mm；最大 {result['registration']['max_mm']:.3f} mm",
        "",
        "## 结论卡",
        "",
        result["course_card"]["headline"],
        "",
        "完整机读结果：`selftest.json`；完整 diff：`diff.json`。",
    ]
    (OUT / "selftest.md").write_text("\n".join(md), encoding="utf-8")

    print(f"[selftest] all_pass={payload['all_pass']}")
    for c in checks:
        print(f"  {'PASS' if c['ok'] else 'FAIL'}  {c['name']}: {c['detail']}")
    print(f"[selftest] out: {OUT}")
    return 0 if payload["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
