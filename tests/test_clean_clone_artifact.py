# -*- coding: utf-8 -*-
"""tests/test_clean_clone_artifact.py —— 干净克隆产物机审兜底（任务书 T1 / A2-Q4）。

三条用例的分工：
  1. 产物必须存在（**不允许 skip**）：`tests/conftest.py` 的 session autouse
     fixture 若生成失败，本用例给出一条明确红，而不是"看起来全绿"；
  2. 产物必须满足消费方判据：`server.extract_viewer_meta` 可解析 + 四个库内
     已公开聚合数在位（`tests/test_api.py:329-331` 的断言值；本机有 15MB 冻结
     副本时同样成立，因该副本内嵌的就是这四个数）；
  3. 合成占位形态的诚实声明在位：临时目录里真跑一次生成链，逐字节确认两行式
     声明与 metrics 覆盖（`gen_demo_data.py:205-216` 的 23.7/50.0/50.0/78.5
     不得残留）。

本文件不放宽任何判据，也不与 `tests/test_api.py` 的 CT 门控用例交叉引用作证据
（F3 钉死 `P0_CT_BASE`/`DATA_ROOT` 为空后它们是 skip）。
"""
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPE = os.path.join(REPO, "code", "pipeline")
SCRIPTS = os.path.join(REPO, "scripts")
for _p in (PIPE, SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import build_pa_placeholder as bpp  # noqa: E402

try:
    import server as SRV  # noqa: E402
except ImportError as exc:  # 与 tests/test_api.py:45-48 同口径：flask 缺失属环境未装齐
    SRV = None
    _SRV_IMPORT_ERROR = str(exc)
else:
    _SRV_IMPORT_ERROR = ""

requires_server = pytest.mark.skipif(
    SRV is None, reason="server/flask 不可用（%s）" % _SRV_IMPORT_ERROR)

ARTIFACT = bpp.DEFAULT_DST


def test_clean_clone_artifact_present():
    """干净克隆形态下 pA 查看器产物必须存在——本用例任何情况下都不 skip。"""
    assert os.path.isfile(ARTIFACT), (
        "pA 查看器产物缺失：%s\n"
        "该路径由 .gitignore:58 屏蔽不入库，应由 tests/conftest.py 的 "
        "ensure_pa_viewer_artifact（session autouse）经 scripts/build_pa_placeholder.py 补齐；"
        "手动复现：python scripts/build_pa_placeholder.py" % ARTIFACT)
    assert os.path.getsize(ARTIFACT) > 0, "产物为 0 字节（生成链未写完）"


@requires_server
def test_clean_clone_artifact_public_aggregates():
    """产物必须能被 extract_viewer_meta 解析，且内嵌四个库内已公开聚合数。"""
    meta = SRV.extract_viewer_meta(ARTIFACT)
    assert meta is not None, (
        "extract_viewer_meta 解析失败（缺 window.VIEWER_DATA 或 meta 键）：%s" % ARTIFACT)
    mm = SRV._metrics_block(meta)
    dP = mm.get("dP_baseline_Pa")
    split_l = mm.get("split_L_pct")
    split_r = mm.get("split_R_pct")
    R = SRV.parse_resistance(mm.get("resistance_total"))
    assert dP == 18.45, "dP_baseline_Pa=%r（期望 18.45，来源 tests/test_api.py:329）" % dP
    assert split_l == 51.9, "split_L_pct=%r（期望 51.9，来源 tests/test_api.py:330）" % split_l
    assert split_r == 48.1, "split_R_pct=%r（期望 48.1，来源 tests/test_api.py:330）" % split_r
    assert R == 66.2, ("resistance_total=%r → %r（期望 66.2，来源 tests/test_api.py:331）"
                       % (mm.get("resistance_total"), R))


@requires_server
def test_placeholder_declaration_and_metrics_override(tmp_path):
    """真跑一次生成链到临时目录：两行式诚实声明在位，合成演示 metrics 已被覆盖。"""
    dst = str(tmp_path / "viewer_single.html")
    n = bpp.synthesize(dst)
    assert os.path.isfile(dst) and os.path.getsize(dst) == n > 0

    txt = open(dst, encoding="utf-8", errors="replace").read()
    for line in bpp.DECLARATION_LINES:
        assert line in txt, "两行式诚实声明缺失：%s" % line
    # 生成链的构建器版本判据：volume/skin 缺席时删悬空引用（33a6c77 修复版行为）
    assert '<script src="volume_data.js"></script>' not in txt, (
        "构建器不是 33a6c77 修复版：悬空引用未删除")

    mm = SRV._metrics_block(SRV.extract_viewer_meta(dst))
    assert mm.get("dP_baseline_Pa") == 18.45 and mm.get("resistance_total") == "66.2 Pa/(L/s)"
    stale = {"dP_baseline_Pa": 23.7, "split_L_pct": 50.0, "split_R_pct": 50.0}
    for k, v in stale.items():
        assert mm.get(k) != v, "gen_demo_data.py:205-216 的合成 metrics 未被覆盖：%s=%s" % (k, v)
