#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""split_validity 侧车自测（R-10 / 裁定3 §2 第 1–2 项）。

只读在用产物，本测试不写任何文件。
新增本文件会使 W2 测试基线计数 **+N**（当前 5 个用例），交回时需声明。
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import split_validity as sv  # noqa: E402

OUT_EXISTS = os.path.isdir(os.path.join(sv.OUT_ROOT, "step1"))
needs_out = pytest.mark.skipif(
    not OUT_EXISTS,
    reason="干净克隆下 out/ 被 .gitignore:23（**/out/）屏蔽，侧车以已提交的那份为准",
)


@needs_out
def test_rebuild_is_byte_deterministic():
    """门⑨：同一输入两次生成必须逐字节相同（所以件内不放时间戳）。"""
    assert sv.render(sv.build()) == sv.render(sv.build())


@needs_out
def test_committed_sidecar_matches_rebuild():
    assert os.path.isfile(sv.DEFAULT_TARGET), "先跑 python code/pipeline/split_validity.py"
    with open(sv.DEFAULT_TARGET, encoding="utf-8") as fh:
        assert fh.read() == sv.render(sv.build())


def test_reason_enum_is_closed():
    assert sv.build()["reason_enum"] == sorted(sv.REASONS)
    assert set(sv.REASONS) == {"imposed_by_area_BC", "septum_grouping_failed"}


def test_committed_sidecar_is_well_formed():
    with open(sv.DEFAULT_TARGET, encoding="utf-8") as fh:
        doc = json.load(fh)
    assert doc["schema"] == "split_validity/v1"
    assert doc["entries_count"] == len(doc["entries"])
    assert all(e["valid"] is False for e in doc["entries"]), "侧车只登记作废，不得混入 valid=true"
    assert {e["reason"] for e in doc["entries"]} <= set(sv.REASONS)
    for bad in ("F:/", "f:/", "F:\\"):
        assert bad not in json.dumps(doc, ensure_ascii=False), bad


def test_area_bc_ref_is_pinned_to_code_line():
    assert "step2_make_ofcase.py:1548" in sv.REASONS["imposed_by_area_BC"]["ref_template"]


def test_each_entry_ref_points_to_its_own_source():
    """2026-10-22 自审新增：原先 septum 的 ref 硬编码 pA 的 `metrics_v2.json`，
    导致 pB/pN 两条出处指错文件——这条断言就是当时缺的那一条。"""
    with open(sv.DEFAULT_TARGET, encoding="utf-8") as fh:
        doc = json.load(fh)
    for e in doc["entries"]:
        assert e["source_file"] in e["ref"], (e["key"], e["ref"], e["source_file"])
        assert "{src}" not in e["ref"]


def test_case_keys_are_never_empty():
    with open(sv.DEFAULT_TARGET, encoding="utf-8") as fh:
        doc = json.load(fh)
    assert all(e["case"].strip() for e in doc["entries"])
    assert "" not in doc["index"]
    for name, expect in (("metrics_v2.json", "pA"), ("metrics_pB_v2.json", "pB"),
                         ("metrics_pN_v2.json", "pN"), ("metrics.json", "metrics")):
        assert sv.case_from_step1_name(name) == expect, name


@needs_out
def test_every_case_with_left_zero_is_flagged():
    """R-10 范围：left_* 恒 0 的算例一个都不能漏（只标 pA 会让别的 case 被读成真实分流）。"""
    doc = sv.build()
    flagged = {e["case"] for e in doc["entries"] if e["field"] == "left_min_mm2"}
    expect = set()
    for path, fn in sv.iter_step1_metrics():
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("left_min_mm2") == 0.0:
            expect.add(sv.case_from_step1_name(fn))
    assert expect and expect <= flagged


# ---------------- 2026-10-23 追加（GAP-7：侧车机器中立 + --replica-check） ----------------
import re  # noqa: E402
import subprocess  # noqa: E402


def test_sidecar_has_no_absolute_drive_letter():
    """侧车必须机器中立：任何形式的盘符路径都不得出现（C:/、D:/ 等一律禁止）。"""
    with open(sv.DEFAULT_TARGET, encoding="utf-8") as fh:
        text = fh.read()
    hits = re.findall(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]", text)
    assert hits == [], hits


def test_replica_check_policy_is_machine_neutral():
    """侧车只放期望值与算法出处，且无时间戳——否则字节重放会随本机状态漂移。"""
    with open(sv.DEFAULT_TARGET, encoding="utf-8") as fh:
        doc = json.load(fh)
    pol = doc["replica_check_policy"]
    assert set(pol) == {"in_repo_ref", "external_ref", "expected_md5", "expected_bytes",
                        "evaluated_by", "note"}
    assert pol["in_repo_ref"] == "code/pipeline/out/step1/metrics_v2.json"
    assert pol["external_ref"] == "阶段1-三维重建/metrics_v2.json"
    assert pol["expected_md5"] == "c5759af68d72b5fc6274bc38016de93a"
    assert pol["expected_bytes"] == 668
    assert "--replica-check" in pol["evaluated_by"]
    assert "不入本文件" in pol["note"]
    blob = json.dumps(pol, ensure_ascii=False)
    assert not re.search(r"\d{4}-\d{2}-\d{2}", blob), "不得含日期"
    assert not re.search(r"\d{2}:\d{2}:\d{2}", blob), "不得含时刻"
    for k in ("generated_at", "checked_at", "timestamp", "identical", "divergent"):
        assert k not in pol, k


def test_replica_check_reports_unknown_when_root_unreachable(tmp_path):
    """ROOT 不可达 ⇒ 只打印 unknown，退出码 0，且不得创建/写入任何文件。"""
    target = tmp_path / "no_such_root"
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run(
        [sys.executable, os.path.abspath(sv.__file__), "--replica-check", "--root", str(target)],
        capture_output=True, text=True, encoding="utf-8", env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "result: unknown" in proc.stdout
    assert not target.exists(), "不得为了比对去创建 ROOT"
