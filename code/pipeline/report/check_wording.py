"""Grep-style patient-wording self-check for generated reports.

Usage (from ``code/``):

    ..\\.venv\\Scripts\\python.exe pipeline\\report\\check_wording.py

Exit code 0 means every generated report is free of population-percentile and
population-comparison wording.  The script also prints the patient-card text so
a human can read the one-sentence conclusion without opening the HTML.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from report.wording import scan_text  # noqa: E402


def main() -> int:
    files = sorted((HERE / "out").glob("report-*.html"))
    if not files:
        print("no reports found in", HERE / "out")
        return 1
    failures = []
    for p in files:
        text = p.read_text(encoding="utf-8")
        hits = scan_text(text, patient_layer=False)
        match = re.search(r'<section class="patient-card">(.*?)</section>', text, re.DOTALL)
        patient = re.sub(r"<[^>]+>", "", match.group(1)).strip() if match else "(patient card missing)"
        print(f"== {p.name}")
        print(f"   patient: {patient}")
        if hits:
            failures.append((p.name, hits))
            for h in hits[:5]:
                print(f"   HIT [{h['label']}] {h['match']!r}")
        else:
            print("   population-percentile wording: 0 hits")
    if failures:
        print("\nFAILED:", ", ".join(name for name, _ in failures))
        return 1
    print("\nOK: 0 population-percentile / population-comparison hits in all reports")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
