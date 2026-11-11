# -*- coding: utf-8 -*-
"""阶段 1 最小算例的三条自验测试（只跑本文件，不跑全量套件）。

真 CT 铁律：输入一律用 out/ 下真 CT 派生的 mask/metrics，不用合成体模。
"""
import hashlib
import json
import os
import sys

import pytest

_PIPE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PIPE)
import airway_compare as ac  # noqa: E402

_OUT = os.path.join(_PIPE, "out")
CASES = [
    ("pA", os.path.join(_OUT, "step2", "mask_full-v1.npz"),
     os.path.join(_OUT, "step1", "metrics_v2.json")),
    ("pB", os.path.join(_OUT, "step2", "mask_full-pB-v1.npz"),
     os.path.join(_OUT, "step1", "metrics_pB_v2.json")),
    ("pN", os.path.join(_OUT, "step2", "mask_full-pN-v1.npz"),
     os.path.join(_OUT, "step1", "metrics_pN_v2.json")),
]


def test_three_cases_volume_vs_metrics():
    """V1：三例 volume_cm3 与 metrics 的 airway_volume_cm3 偏差 ≤0.15 cm³。"""
    for case, mask, metrics in CASES:
        d = ac.compute(mask, metrics, case=case)
        with open(metrics, "r", encoding="utf-8") as f:
            ref = float(json.load(f)["airway_volume_cm3"])
        assert abs(d["volume_cm3"] - ref) <= 0.15, case
        assert abs(d["delta_vs_step1"]) <= 0.15, case
        assert d["truncate_range_k"][0] == 0, case
        assert d["min_layer"] >= 1, case
        assert d["spacing_source"] == "npz 未存 spacing，换算若需要须从 CT 头读"
        assert set(d["protocol_fields"].values()) == {"未采集"}, case
        assert d["npz_has_spacing_key"] is False, case
        assert "z 轴向近似" in d["direction_decl"]
        assert "step2:1431" in d["cfd_boundary_note"]


def test_repeat_numeric_tolerance():
    """V2：同一例重复跑两次，数值容差一致（容积 ≤0.01、截面积 ≤0.1），非字节一致。

    验收标准是数值容差，不要求两次 JSON 字节相同（浮点末位 / 时间戳会变）。
    """
    mask, metrics = CASES[0][1], CASES[0][2]
    d1 = ac.compute(mask, metrics, case="pA")
    d2 = ac.compute(mask, metrics, case="pA")
    assert abs(d1["volume_cm3"] - d2["volume_cm3"]) <= 0.01
    assert abs(d1["min_axial_area_mm2"] - d2["min_axial_area_mm2"]) <= 0.1
    assert abs(d1["open_end_port_mm2"] - d2["open_end_port_mm2"]) <= 0.1
    assert d1["truncate_range_k"] == d2["truncate_range_k"]


def _fingerprint(paths):
    out = {}
    for p in paths:
        st = os.stat(p)
        h = hashlib.md5()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        out[p] = (st.st_size, st.st_mtime_ns, h.hexdigest())
    return out


def test_readonly_no_disk_write():
    """V3/V4：compute 不写盘、不改既有输入文件（size/mtime/md5 前后一致）。"""
    watched = [m for _, m, _ in CASES] + [j for _, _, j in CASES]
    before = _fingerprint(watched)
    for case, mask, metrics in CASES:
        ac.compute(mask, metrics, case=case)
    after = _fingerprint(watched)
    assert before == after
