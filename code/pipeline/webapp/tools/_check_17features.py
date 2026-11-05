#!/usr/bin/env python3
"""T50 D1 static assertion set for the workbench and viewer sources.

Checkbox census (2026-10-21 复核 DOM，实测值):
  workbench 11 = 视图图层 5（hero-ly-*）+ 工作台控制 6（pg-auto / pt-consent /
                ops-env / ops-manifest / ops-page / ops-rawlog）
  viewer    10 = 模板查看器十个图层开关
  审计请求里的 "20" 仍是跨源目标，不做盲数 DOM。

为什么不再写死 workbench=6：T50 时点是 6（hero-ly-* ×5 + pg-auto），之后 T17
患者授权（pt-consent）与运维报告导出（ops-* ×4）落地，计数一直是红的——那是
**既有差异，与本次改动无关**。此处把「视图图层」与「流程/运维开关」分开断言：
图层面一少就立即失败（真回归），流程面只做存在性 + 总数对账（新增开关时改一行常量）。
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WORKBENCH = ROOT / "index.html"
VIEWER = ROOT / "viewer_template" / "viewer.html"
PLUS = ROOT / "plus" / "viewer_plus.html"

# 视图图层开关（本脚本关心的功能面）：少一个即为真回归
WORKBENCH_LAYER_CHECKBOXES = ["hero-ly-cfd", "hero-ly-model", "hero-ly-flow",
                             "hero-ly-slice", "hero-ly-wire"]
# 流程/运维开关：与 17 功能面无关，只做存在性 + 总数对账（新增时改这一行）
WORKBENCH_CONTROL_CHECKBOXES = ["pg-auto", "pt-consent", "ops-env",
                                "ops-manifest", "ops-page", "ops-rawlog"]
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
    for ident in WORKBENCH_LAYER_CHECKBOXES + WORKBENCH_CONTROL_CHECKBOXES:
        require(workbench, f'id="{ident}"', f"workbench checkbox #{ident}")
    for ident in VIEWER_CHECKBOXES:
        require(viewer, f'id="{ident}"', f"viewer checkbox #{ident}")
    wb_expect = len(WORKBENCH_LAYER_CHECKBOXES) + len(WORKBENCH_CONTROL_CHECKBOXES)
    if checkbox_count(workbench) != wb_expect:
        raise AssertionError(
            "workbench checkbox 总数变了: %d（期望 %d = 图层 %d + 控制/流程 %d）"
            % (checkbox_count(workbench), wb_expect,
               len(WORKBENCH_LAYER_CHECKBOXES),
               len(WORKBENCH_CONTROL_CHECKBOXES)))
    if checkbox_count(viewer) != len(VIEWER_CHECKBOXES):
        raise AssertionError(
            "viewer checkbox 总数变了: %d（期望 %d）"
            % (checkbox_count(viewer), len(VIEWER_CHECKBOXES)))
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
    print("  workbench checkboxes: %d = 图层 %d + 控制/流程 %d"
          % (checkbox_count(workbench), len(WORKBENCH_LAYER_CHECKBOXES),
             len(WORKBENCH_CONTROL_CHECKBOXES)))
    print(f"  viewer checkboxes: {checkbox_count(viewer)}"
          f" (已知跨源差异：workbench {checkbox_count(workbench)} + viewer "
          f"{checkbox_count(viewer)} = {checkbox_count(workbench) + checkbox_count(viewer)}，"
          "T50 时为 16；多出的是 T17 授权 + 运维导出开关)")
    print("  plus forbidden postprocessing: 0")
    print("  plus MeshPhongMaterial: 0")


if __name__ == "__main__":
    main()
