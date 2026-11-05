# -*- coding: utf-8 -*-
"""tests/conftest.py —— 干净克隆形态的 pA 查看器产物兜底（任务书 T1 / A2-Q4）。

为什么存在：`tests/test_api.py` 的 `test_cases_schema`（:102-118）与
`test_viewer_pA_iframe`（:145-150）对产物的判据只有文件存在性
（`server.py:3432-3433`），而该产物按隐私政策不入库（`.gitignore:58`）⇒
干净克隆后两条用例必红。本 fixture 在会话开始时补齐缺失产物，使两条用例
在**不放宽任何判据**的前提下真实通过。

为什么是 `scope="session", autouse=True`：F3 段 2 单独跑 `tests/test_api.py`
时兜底用例（`tests/test_clean_clone_artifact.py`）不被收集，autouse 是两条
目标用例可绿的前提；改为具名 fixture 即失效。

纪律：
  · 幂等——产物已在位（本机 15MB 冻结副本）则直接复用，绝不重生成、绝不覆盖；
  · 提交包优先——装有真产物的机器复制冻结资产，避免
    `test_frozen_pA_single_untouched`（:171-180）由 skip 翻成 md5 不符红；
  · 生成失败抛清晰异常 ⇒ 用例 ERROR（红），不允许静默 skip（机审兜底由
    `tests/test_clean_clone_artifact.py` 承担）。
"""
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import build_pa_placeholder as bpp  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def ensure_pa_viewer_artifact():
    """确保 pA 查看器单文件产物在位（缺失才生成，生成链见脚本 docstring）。"""
    try:
        info = bpp.ensure()
    except Exception as exc:  # 明确抛出让用例 ERROR，而非静默跳过
        raise RuntimeError(
            "pA 查看器产物缺失且自动生成失败：%s\n"
            "手动复现：python scripts/build_pa_placeholder.py" % exc
        ) from exc
    return info
