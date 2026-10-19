"""Self-checks for the single-file report.

The checks are intentionally mechanical: size, self-containment, inline images,
per-card evidence, presence of the headline numbers, and patient wording.
Run directly on generated files:

    python pipeline/report/selfcheck.py pipeline/report/out/report-pA.html
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from report.wording import scan_text  # noqa: E402

MAX_BYTES = 5 * 1024 * 1024
PERCENTILE_HINT = re.compile(r"分位|百分位|percentile|P(?:[5-9]\d|100)", re.IGNORECASE)


def _token_check(text: str, token: str) -> bool:
    return token in text


def check_report(path: str | Path, bundle=None) -> dict:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    size = p.stat().st_size
    # Base64 image payloads are random-looking and can contain strings such as
    # "P61"; scan a copy with data URIs replaced so wording checks only see the
    # visible document text.
    clean = re.sub(r"data:image/[^\"']+", "DATA_URI", text)
    checks: dict[str, dict] = {}

    checks["size"] = {
        "ok": size < MAX_BYTES,
        "bytes": size,
        "limit": MAX_BYTES,
        "human": f"{size/1024:.1f} KB",
    }
    checks["doctype"] = {"ok": text.lstrip().lower().startswith("<!doctype html>")}
    checks["charset"] = {"ok": '<meta charset="utf-8">' in text.lower()}

    # Self-containment: no remote scripts/styles/images and no @import.
    remote = re.findall(r"(?:src|href)\s*=\s*[\"'](https?://[^\"']+)", text, re.IGNORECASE)
    remote += re.findall(r"@import\s+url\(", text, re.IGNORECASE)
    checks["no_remote"] = {"ok": not remote, "hits": remote[:5]}
    checks["no_external_script"] = {"ok": not re.search(r"<script[^>]+src\s*=", text, re.IGNORECASE)}
    checks["no_external_css"] = {"ok": not re.search(r"<link[^>]+rel\s*=\s*[\"']stylesheet", text, re.IGNORECASE)}

    images = re.findall(r"<img[^>]+src=\"data:image/", text, re.IGNORECASE)
    checks["images"] = {"ok": len(images) >= 3, "count": len(images)}

    cards = re.findall(r'<article class="metric-card">(.*?)</article>', text, re.DOTALL)
    card_evidence = []
    for card in cards:
        has_fig = 'class="evidence"' in card and "data:image/" in card
        has_gap = 'class="gap"' in card
        card_evidence.append(has_fig or has_gap)
    checks["metric_cards"] = {
        "ok": bool(cards) and all(card_evidence),
        "count": len(cards),
        "with_evidence": sum(1 for v in card_evidence if v),
    }

    # Headline numbers.  The bundle is optional so the CLI can also check a
    # hand-built report without a data model.
    number_checks = {}
    if bundle is not None:
        m = bundle.metrics
        tokens = {
            "dP_Pa": None if m.get("dP_Pa") is None else f"{float(m['dP_Pa']):.1f}",
            "split_L_pct": None if m.get("split_L_pct") is None else f"{float(m['split_L_pct']):.1f}%",
            "split_R_pct": None if m.get("split_R_pct") is None else f"{float(m['split_R_pct']):.1f}%",
            "min_area_mm2": None if m.get("min_area_mm2") is None else f"{float(m['min_area_mm2']):.2f}",
            "volume_cm3": None if m.get("volume_cm3") is None else f"{float(m['volume_cm3']):.1f}",
            "U_max_m_s": None if m.get("U_max_m_s") is None else f"{float(m['U_max_m_s']):.2f}",
            "wss_mean_Pa": None if m.get("wss_mean_Pa") is None else f"{float(m['wss_mean_Pa']):.4f}",
        }
        for key, token in tokens.items():
            if token is not None:
                number_checks[key] = {"ok": _token_check(text, token), "token": token}
    checks["numbers"] = {
        "ok": all(v["ok"] for v in number_checks.values()) if number_checks else True,
        "items": number_checks,
    }

    word_hits = scan_text(clean, patient_layer=False)
    checks["percentile_free"] = {"ok": not word_hits, "hits": word_hits[:5]}
    if PERCENTILE_HINT.search(clean):
        checks["percentile_free"]["ok"] = False
        checks["percentile_free"].setdefault("regex_hits", PERCENTILE_HINT.findall(clean)[:10])

    patient_match = re.search(r'<section class="patient-card">(.*?)</section>', clean, re.DOTALL)
    patient_text = patient_match.group(1) if patient_match else ""
    patient_hits = scan_text(patient_text, patient_layer=True)
    checks["patient_layer"] = {
        "ok": bool(patient_match) and not patient_hits,
        "hits": patient_hits[:5],
        "has_conclusion": bool(patient_text),
    }

    checks["print_ready"] = {
        "ok": "@media print" in text and "window.print()" in text,
    }

    ok = all(v.get("ok", True) for v in checks.values())
    return {"ok": ok, "path": str(p), "checks": checks}


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    if not argv:
        argv = [str(p) for p in sorted((HERE / "out").glob("*.html"))]
    results = [check_report(p) for p in argv]
    print(json.dumps({"ok": all(r["ok"] for r in results), "reports": results}, ensure_ascii=False, indent=1))
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
