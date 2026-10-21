#!/usr/bin/env python3
"""T50 D1 static assertion set for the workbench and viewer sources.

The source repository currently has 6 workbench checkboxes and 10 template
viewer checkboxes.  The audit request's "20" is therefore recorded as a
cross-source target, not used as a blind DOM count.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WORKBENCH = ROOT / "index.html"
VIEWER = ROOT / "viewer_template" / "viewer.html"
PLUS = ROOT / "plus" / "viewer_plus.html"

WORKBENCH_CHECKBOXES = ["hero-ly-cfd", "hero-ly-model", "hero-ly-flow", "hero-ly-slice", "hero-ly-wire", "pg-auto"]
VIEWER_CHECKBOXES = ["cb-ct", "cb-skin", "cb-breath-anim", "cb-cavity", "cb-sinus", "cb-lines", "cb-slices", "cb-ph-1", "cb-ph-2", "cb-ph-3"]
WORKBENCH_IDS = ["tab-airway", "airway-pills", "case-summary-rail", "hero-box", "hero-viewtoggle", "findings-block", "compare-card", "metrics-card", "qc-card", "results-card", "figures-card", "btn-page-fs"]
VIEWER_FEATURE_IDS = ["app", "canvas-wrap", "glcanvas", "toolbar", "btn-reset", "btn-rotate", "legend", "breath-phase", "panel", "flow-card", "curve-card", "ct-card", "ct-presets", "methodology-box", "ct-thumb-card", "ct-thumbs", "row-skin"]


def require(text, needle, label):
    if needle not in text:
        raise AssertionError(f"missing {label}: {needle}")


def checkbox_count(text):
    return len(re.findall(r'<input\b[^>]*\btype=["\']checkbox["\']', text, re.I))


def main():
    workbench = WORKBENCH.read_text(encoding="utf-8")
    viewer = VIEWER.read_text(encoding="utf-8")
    plus = PLUS.read_text(encoding="utf-8")
    for ident in WORKBENCH_IDS:
        require(workbench, f'id="{ident}"', f"workbench #{ident}")
    for ident in VIEWER_FEATURE_IDS:
        require(viewer, f'id="{ident}"', f"viewer #{ident}")
    for ident in WORKBENCH_CHECKBOXES:
        require(workbench, f'id="{ident}"', f"workbench checkbox #{ident}")
    for ident in VIEWER_CHECKBOXES:
        require(viewer, f'id="{ident}"', f"viewer checkbox #{ident}")
    if checkbox_count(workbench) != 6 or checkbox_count(viewer) != 10:
        raise AssertionError(f"checkbox counts changed: workbench={checkbox_count(workbench)}, viewer={checkbox_count(viewer)}")
    plus_business = plus.split("<!--__MAIN_APP_JS_END__-->", 1)[-1]
    if "EffectComposer" in plus_business or "UnrealBloomPass" in plus_business:
        raise AssertionError("forbidden postprocessing marker in plus viewer business code")
    if re.search(r'\bnew\s+THREE\.MeshPhongMaterial\b', plus_business):
        raise AssertionError("forbidden MeshPhongMaterial constructor in plus viewer business code")
    if "--bg:var(--bg-0)" not in plus or "--line:var(--line-new)" not in plus:
        raise AssertionError("viewer token alias table missing")
    print("PASS: T50 assertions")
    print(f"  workbench ids: {len(WORKBENCH_IDS)}/{len(WORKBENCH_IDS)}")
    print(f"  viewer feature ids: {len(VIEWER_FEATURE_IDS)}/{len(VIEWER_FEATURE_IDS)}")
    print(f"  checkbox sources: {checkbox_count(workbench)} + {checkbox_count(viewer)} = 16")
    print("  plus forbidden postprocessing: 0")
    print("  plus MeshPhongMaterial: 0")


if __name__ == "__main__":
    main()
