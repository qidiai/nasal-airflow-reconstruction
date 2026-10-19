"""Build a single-file HTML report for one or more cases.

Examples
--------
Run from the repository's ``code/`` directory:

    ..\\.venv\\Scripts\\python.exe pipeline\\report\\build_report.py --cases pA demoA synth-001

    ..\\.venv\\Scripts\\python.exe pipeline\\report\\build_report.py ^
        --metrics path\\to\\metrics.json --label "我的病例" ^
        --area-csv path\\to\\area.csv --vtu path\\to\\internal.vtu ^
        --out-dir pipeline\\report\\out

Every generated report is checked for size (<5 MB), self-containment, patient
wording and per-card evidence before the command returns success.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import report.cases as cases  # noqa: E402
import report.engine as engine  # noqa: E402
import report.selfcheck as selfcheck  # noqa: E402


def _build_one(bundle: cases.CaseBundle, out_dir: Path, fig_root: Path) -> dict:
    fig_dir = fig_root / bundle.case_id
    cases.prepare_figures(bundle, fig_dir)
    out_path = out_dir / f"report-{bundle.case_id}.html"
    engine.render_html(bundle, out_path)
    result = selfcheck.check_report(out_path, bundle)
    result["case_id"] = bundle.case_id
    result["label"] = bundle.label
    result["data_source"] = bundle.data_source
    result["figures"] = sorted(bundle.figures)
    result["report"] = str(out_path)
    result["size_bytes"] = out_path.stat().st_size
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="M4 single-file HTML report builder")
    ap.add_argument("--cases", nargs="+", default=None, help=f"built-in cases: {', '.join(cases.BUILTIN_CASES)}")
    ap.add_argument("--metrics", default=None, help="generic metrics.json path (instead of --cases)")
    ap.add_argument("--label", default=None)
    ap.add_argument("--case-kind", default="patient", choices=["patient", "patient_demo", "synthetic"])
    ap.add_argument("--area-csv", default=None)
    ap.add_argument("--vtu", default=None)
    ap.add_argument("--outlet-vtp", default=None)
    ap.add_argument("--walls-vtp", default=None)
    ap.add_argument("--qc-image", default=None)
    ap.add_argument("--stl", default=None)
    ap.add_argument("--out-dir", default=str(HERE / "out"))
    ap.add_argument("--fig-dir", default=str(HERE / "figures"))
    ap.add_argument("--no-selfcheck", action="store_true")
    args = ap.parse_args(argv)

    out_dir = Path(args.out_dir)
    fig_root = Path(args.fig_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fig_root.mkdir(parents=True, exist_ok=True)

    bundles: list[cases.CaseBundle] = []
    if args.metrics:
        bundles.append(
            cases.load_generic(
                args.metrics,
                label=args.label,
                case_kind=args.case_kind,
                area_csv=args.area_csv,
                vtu=args.vtu,
                outlet_vtp=args.outlet_vtp,
                walls_vtp=args.walls_vtp,
                qc_image=args.qc_image,
                stl=args.stl,
            )
        )
    else:
        requested = args.cases or ["pA", "demoA", "synth-001"]
        for cid in requested:
            bundles.append(cases.load_builtin(cid))

    results = []
    for bundle in bundles:
        print(f"[report] building {bundle.case_id} ...")
        try:
            res = _build_one(bundle, out_dir, fig_root)
        except Exception as exc:  # noqa: BLE001 - report failures must be visible
            print(f"[report] FAILED {bundle.case_id}: {type(exc).__name__}: {exc}")
            results.append({"case_id": bundle.case_id, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
            continue
        results.append(res)
        print(
            f"[report] {bundle.case_id}: {res['size_bytes']/1024:.1f} KB, "
            f"{res['checks']['images']['count']} inline images, ok={res['ok']}"
        )
        if not res["ok"]:
            for key, value in res["checks"].items():
                if not value.get("ok", True):
                    print(f"    - {key}: {value}")

    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "out_dir": str(out_dir),
        "reports": results,
    }
    (out_dir / "build-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = all(r.get("ok") for r in results)
    print(f"[report] done; all_ok={ok}; manifest={out_dir / 'build-manifest.json'}")
    return 0 if ok or args.no_selfcheck else 1


if __name__ == "__main__":
    raise SystemExit(main())
