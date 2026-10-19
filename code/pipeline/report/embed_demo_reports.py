"""Embed pre-built R1 reports into ``pipeline/webapp/demo.html``.

Why embed instead of serving a file?
------------------------------------
``server.py`` serves only ``pipeline/webapp`` as ``/static`` and M4 is not
allowed to add a route or new webapp files.  The demo page therefore carries the
four pre-built single-file reports as base64 payloads and turns them into Blob
downloads in the browser.  The logic change in ``demo.html`` is the small
"下载报告" entry; the payload is data produced by the R1 engine.

The committed payload is the synthetic case only (``synth-001``).  Patient
cases (``demoA``/``demoB``/``pA``/``pN-*``) derive from patient imaging and are
therefore only embedded for local, authorised demonstration; pass ``--cases``
to opt in explicitly.

Usage (from ``code/``):

    # committed state: synth-001 only
    ..\\.venv\\Scripts\\python.exe pipeline\\report\\embed_demo_reports.py

    # local, authorised demo payload (patient-derived cases included)
    ..\\.venv\\Scripts\\python.exe pipeline\\report\\embed_demo_reports.py ^
        --cases demoA,demoB,pA,pN-Lat,pN-Med
"""

from __future__ import annotations

import argparse
import base64
import json
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
CODE = HERE.parents[1]
DEFAULT_DEMO = CODE / "pipeline" / "webapp" / "demo.html"
DEFAULT_CASES = ["synth-001"]
START = "/* M4-REPORTS-START */"
END = "/* M4-REPORTS-END */"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="embed R1 reports into demo.html")
    ap.add_argument("--reports-dir", default=str(HERE / "out"))
    ap.add_argument("--demo", default=str(DEFAULT_DEMO))
    ap.add_argument(
        "--cases",
        default=",".join(DEFAULT_CASES),
        help=(
            "comma-separated case ids to embed (default: %(default)s). "
            "Patient-derived cases are only for local authorised demos, "
            "e.g. --cases demoA,demoB,pA,pN-Lat,pN-Med"
        ),
    )
    args = ap.parse_args(argv)

    cases = [c.strip() for c in args.cases.split(",") if c.strip()]
    if not cases:
        raise SystemExit("--cases is empty")

    reports_dir = Path(args.reports_dir)
    demo = Path(args.demo)
    if not demo.is_file():
        raise SystemExit(f"demo.html not found: {demo}")
    text = demo.read_text(encoding="utf-8")
    if START not in text or END not in text:
        raise SystemExit("demo.html is missing the M4-REPORTS markers")

    entries = {}
    sizes = {}
    missing = []
    for cid in cases:
        p = reports_dir / f"report-{cid}.html"
        if not p.is_file():
            missing.append(cid)
            continue
        raw = p.read_bytes()
        entries[cid] = base64.b64encode(raw).decode("ascii")
        sizes[cid] = len(raw)

    if not entries:
        raise SystemExit(f"no reports found in {reports_dir}")

    lines = ["const REPORTS={"]
    for cid in cases:
        if cid in entries:
            lines.append(f'  {json.dumps(cid, ensure_ascii=False)}:"{entries[cid]}",')
    lines.append("};")
    payload = "\n".join(lines)

    prefix, rest = text.split(START, 1)
    _, suffix = rest.split(END, 1)
    new_text = prefix + START + "\n" + payload + "\n" + END + suffix
    demo.write_text(new_text, encoding="utf-8")

    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "demo": str(demo),
        "demo_size_bytes": demo.stat().st_size,
        "embedded": {cid: {"report_bytes": sizes[cid], "base64_chars": len(entries[cid])} for cid in entries},
        "missing": missing,
    }
    (reports_dir / "embed-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[embed] demo.html: {demo.stat().st_size/1024:.1f} KB")
    for cid in entries:
        print(f"  {cid}: report {sizes[cid]/1024:.1f} KB -> base64 {len(entries[cid])/1024:.1f} KB")
    if missing:
        print(f"  missing (button will show '报告待生成'): {', '.join(missing)}")
    print(f"[embed] manifest: {reports_dir / 'embed-manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
