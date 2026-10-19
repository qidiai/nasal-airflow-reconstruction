"""Follow-up diff CLI: registration → geometry diff → metric diff → course card.

Example (synthetic pair):

    ..\\.venv\\Scripts\\python.exe pipeline\\followup\\run_diff.py ^
        --a pipeline\\out\\synth\\synth-001 ^
        --b pipeline\\out\\synth\\synth-005 ^
        --label-a synth-001 --label-b synth-005 ^
        --out pipeline\\followup\\out\\synth-001-vs-005
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from followup import conclusion, geometry, metrics, registration  # noqa: E402


def find_stl(case_dir: str | Path) -> Path | None:
    base = Path(case_dir)
    candidates = [base / "geometry.stl"]
    candidates += sorted((base / "step1").glob("airway_*.stl")) if (base / "step1").is_dir() else []
    for p in candidates:
        if p.is_file():
            return p
    return None


def find_mesh(case_dir: str | Path) -> Path | None:
    base = Path(case_dir)
    candidates = [base / "case" / "constant" / "polyMesh", base / "constant" / "polyMesh"]
    candidates += sorted((base / "step2").glob("P0-OF-case-*-v1/constant/polyMesh")) if (base / "step2").is_dir() else []
    for p in candidates:
        if (p / "points").is_file() and (p / "faces").is_file():
            return p
    return None


def run_pair(
    case_a: str | Path,
    case_b: str | Path,
    *,
    stl_a: str | Path | None = None,
    stl_b: str | Path | None = None,
    mesh_a: str | Path | None = None,
    mesh_b: str | Path | None = None,
    n_slices: int = 80,
    skip_polymesh: bool = False,
    max_points: int = 40000,
) -> dict:
    a, b = Path(case_a), Path(case_b)
    sa = Path(stl_a) if stl_a else find_stl(a)
    sb = Path(stl_b) if stl_b else find_stl(b)
    if sa is None or sb is None:
        raise FileNotFoundError(f"STL not found: a={sa}, b={sb}")
    ma = Path(mesh_a) if mesh_a else find_mesh(a)
    mb = Path(mesh_b) if mesh_b else find_mesh(b)

    mesh_a_obj = geometry.load_stl(sa)
    mesh_b_obj = geometry.load_stl(sb)
    reg = registration.register(mesh_a_obj.vertices, mesh_b_obj.vertices, max_points=max_points)
    T = np.asarray(reg["matrix"], dtype=float)

    g_stl = geometry.compare_stl(sa, sb, T, n_slices=n_slices)
    g_mesh = None
    if not skip_polymesh and ma and mb:
        g_mesh = geometry.compare_polymesh(ma, mb, T, n_bins=n_slices)

    ma_metrics = metrics.load_case_metrics(a)
    mb_metrics = metrics.load_case_metrics(b)
    mdiff = metrics.diff_metrics(ma_metrics, mb_metrics)
    card = conclusion.course_card(mdiff, registration=reg)

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "pair": {"a": str(a), "b": str(b), "stl_a": str(sa), "stl_b": str(sb), "mesh_a": str(ma), "mesh_b": str(mb)},
        "registration": reg,
        "geometry_stl": g_stl,
        "geometry_polymesh": g_mesh,
        "metrics": mdiff,
        "course_card": card,
        "patient_followup_sentence": conclusion.patient_followup_sentence(mdiff),
    }


def _fmt(x, digits=2):
    if x is None:
        return "—"
    try:
        return f"{float(x):.{digits}f}"
    except (TypeError, ValueError):
        return str(x)


def write_markdown(result: dict, out_path: Path, label_a: str, label_b: str) -> None:
    reg = result["registration"]
    stl = result["geometry_stl"]
    mesh = result.get("geometry_polymesh")
    card = result["course_card"]
    lines = [
        f"# 随访差异报告 · {label_a} → {label_b}",
        "",
        f"- 生成：{result['generated_at']}",
        f"- A：`{result['pair']['a']}`",
        f"- B：`{result['pair']['b']}`",
        "",
        "## 1. 病程结论卡",
        "",
        card["headline"],
        "",
        "### 需要注意",
        "",
    ]
    lines += [f"- {c}" for c in card["caveats"]]
    lines += [
        "",
        "## 2. 配准精度",
        "",
        f"- 方法：{reg['method']}",
        f"- RMS {_fmt(reg['rms_mm'], 3)} mm；中位 {_fmt(reg['median_mm'], 3)} mm；"
        f"P95 {_fmt(reg['p95_mm'], 3)} mm；最大 {_fmt(reg['max_mm'], 3)} mm",
        f"- 1 mm 内点比例 {_fmt(reg['inlier_ratio_1mm']*100, 1)}%；2 mm 内点比例 {_fmt(reg['inlier_ratio_2mm']*100, 1)}%",
        f"- 迭代 {reg['n_iter']}；抽样 {reg['n_src_sampled']} / {reg['n_dst_sampled']} 点",
        "",
        "## 3. 指标差",
        "",
        metrics.format_markdown_rows(result["metrics"]),
        "",
        "## 4. 几何差（STL 级）",
        "",
        "| 项 | A | B | 变化 |",
        "|---|---:|---:|---:|",
        f"| STL 体积（cm³） | {_fmt(stl['a']['volume_cm3'], 3)} | {_fmt(stl['b']['volume_cm3'], 3)} | {_fmt(stl['volume_delta_cm3'], 3)}（{_fmt(stl['volume_delta_pct'], 2)}%） |",
        f"| STL 表面积（mm²） | {_fmt(stl['a']['area_mm2'], 1)} | {_fmt(stl['b']['area_mm2'], 1)} | {_fmt(stl['area_delta_mm2'], 1)} |",
        f"| 水密 | {stl['watertight']['a']} | {stl['watertight']['b']} | — |",
        f"| 顶点数 | {stl['a']['vertices']} | {stl['b']['vertices']} | {stl['b']['vertices']-stl['a']['vertices']:+d} |",
        f"| 面数 | {stl['a']['faces']} | {stl['b']['faces']} | {stl['b']['faces']-stl['a']['faces']:+d} |",
        "",
        "顶点集差（A 配准到 B 后，cKDTree 最近邻）：",
        "",
        "| 方向 | 中位 | P95 | 最大 | >1 mm 顶点 |",
        "|---|---:|---:|---:|---:|",
        f"| A→B | {_fmt(stl['vertex_diff']['a_to_b']['median_mm'], 3)} | {_fmt(stl['vertex_diff']['a_to_b']['p95_mm'], 3)} | "
        f"{_fmt(stl['vertex_diff']['a_to_b']['max_mm'], 3)} | {stl['vertex_diff']['a_to_b']['count_gt_1mm']} "
        f"（{_fmt(stl['vertex_diff']['a_to_b']['fraction_gt_1mm']*100, 1)}%） |",
        f"| B→A | {_fmt(stl['vertex_diff']['b_to_a']['median_mm'], 3)} | {_fmt(stl['vertex_diff']['b_to_a']['p95_mm'], 3)} | "
        f"{_fmt(stl['vertex_diff']['b_to_a']['max_mm'], 3)} | {stl['vertex_diff']['b_to_a']['count_gt_1mm']} "
        f"（{_fmt(stl['vertex_diff']['b_to_a']['fraction_gt_1mm']*100, 1)}%） |",
        "",
        f"切片最小截面（中央 80% 区间）：A "
        f"{_fmt(stl['slice_curve']['min_central_80pct']['a']['area_mm2'], 2)} mm² @ "
        f"{_fmt(stl['slice_curve']['min_central_80pct']['a']['z_mm'], 1)} mm；B "
        f"{_fmt(stl['slice_curve']['min_central_80pct']['b']['area_mm2'], 2)} mm² @ "
        f"{_fmt(stl['slice_curve']['min_central_80pct']['b']['z_mm'], 1)} mm。",
        f"全局最小截面：A {_fmt(stl['slice_curve']['min_global']['a']['area_mm2'], 2)} mm² @ "
        f"{_fmt(stl['slice_curve']['min_global']['a']['z_mm'], 1)} mm；B "
        f"{_fmt(stl['slice_curve']['min_global']['b']['area_mm2'], 2)} mm² @ "
        f"{_fmt(stl['slice_curve']['min_global']['b']['z_mm'], 1)} mm（两端开口收敛段会把全局最小值拉到 0，需与中央口径一起看）。",
        "",
        "## 5. 几何差（polyMesh 级）",
        "",
    ]
    if mesh:
        lines += [
            "| 项 | A | B | 变化 |",
            "|---|---:|---:|---:|",
            f"| 单元数 | {mesh['a']['cells']} | {mesh['b']['cells']} | {mesh['cells_delta']:+d} |",
            f"| 点数 | {mesh['a']['points']} | {mesh['b']['points']} | {mesh['points_delta']:+d} |",
            f"| 面数 | {mesh['a']['faces']} | {mesh['b']['faces']} | {mesh['faces_delta']:+d} |",
            f"| 体积（cm³） | {_fmt(mesh['a']['volume_cm3'], 3)} | {_fmt(mesh['b']['volume_cm3'], 3)} | "
            f"{_fmt(mesh['volume_delta_cm3'], 3)}（{_fmt(mesh['volume_delta_pct'], 2)}%） |",
            "",
            f"层均截面积曲线：{mesh['note']}",
        ]
    else:
        lines.append("（本次未运行 polyMesh 级差异。）")
    lines += [
        "",
        "## 6. 患者语言层（供随访卡片使用）",
        "",
        result["patient_followup_sentence"],
        "",
        "## 7. 方法与边界",
        "",
        "- 方法论继承 F-15：先配准，再做几何差（体积/截面/顶点集），最后才看指标差。",
        "- 配准只估计刚体运动（cKDTree + 截尾 ICP + SVD），不估计缩放/形变。",
        "- 水密判决使用 trimesh（MIT）；未引入 GPL/NC 依赖。",
        "- 两例若使用不同重建网格或不同体素，顶点差与层均曲线只作定位线索。",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="M4 follow-up diff engine")
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--stl-a", default=None)
    ap.add_argument("--stl-b", default=None)
    ap.add_argument("--mesh-a", default=None)
    ap.add_argument("--mesh-b", default=None)
    ap.add_argument("--label-a", default=None)
    ap.add_argument("--label-b", default=None)
    ap.add_argument("--out", default=str(HERE / "out" / "diff"))
    ap.add_argument("--slices", type=int, default=80)
    ap.add_argument("--skip-polymesh", action="store_true")
    ap.add_argument("--max-points", type=int, default=40000)
    args = ap.parse_args(argv)

    label_a = args.label_a or Path(args.a).name
    label_b = args.label_b or Path(args.b).name
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    result = run_pair(
        args.a,
        args.b,
        stl_a=args.stl_a,
        stl_b=args.stl_b,
        mesh_a=args.mesh_a,
        mesh_b=args.mesh_b,
        n_slices=args.slices,
        skip_polymesh=args.skip_polymesh,
        max_points=args.max_points,
    )
    result["labels"] = {"a": label_a, "b": label_b}
    (out_dir / "diff.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    write_markdown(result, out_dir / "diff.md", label_a, label_b)

    print(f"[followup] {label_a} -> {label_b}")
    print(f"  registration: RMS {result['registration']['rms_mm']:.3f} mm, "
          f"median {result['registration']['median_mm']:.3f} mm, "
          f"p95 {result['registration']['p95_mm']:.3f} mm")
    print(f"  STL volume: {result['geometry_stl']['a']['volume_cm3']:.3f} -> "
          f"{result['geometry_stl']['b']['volume_cm3']:.3f} cm³ "
          f"({result['geometry_stl']['volume_delta_pct']:+.2f}%)")
    if result.get("geometry_polymesh"):
        g = result["geometry_polymesh"]
        print(f"  polyMesh: {g['a']['cells']} -> {g['b']['cells']} cells; "
              f"volume {g['a']['volume_cm3']:.3f} -> {g['b']['volume_cm3']:.3f} cm³")
    print(f"  {result['course_card']['headline']}")
    print(f"  out: {out_dir / 'diff.json'}, {out_dir / 'diff.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
