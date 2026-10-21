#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0 修复回归：server.mask_fatal_pii_values / mask_text 语义钉住。

覆盖：
  1) 路径掩码 → <path>
  2) FATAL 行 PII 元组"值"字段掩码 → '<值已隐藏>'
  3) 路径 + PII 同时命中时 n_hits 计数正确
  4) gate_failures 语义（server.py:1221）：结果为 list[str]，元素不得是 tuple/list
  5) 幂等：对已掩码文本再跑一次内容不变
  6) 取向钉住：只在可识别的 PII 元组结构上掩值，不猜姓名（宁可少掩不多猜）

不需要起 Flask 服务，直接 import server 的函数。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.dirname(HERE)
if PIPELINE not in sys.path:
    sys.path.insert(0, PIPELINE)

import server  # noqa: E402

# run_all.py:642 的真实 FATAL 形态：die(2, f"PII 头扫描 FAIL ×{n}（首条：{fails[0]}）——停工上报")
FATAL_ONE = (
    "PII 头扫描 FAIL ×1（首条：('case001.dcm', 'PatientName', 'ZHANG SAN', "
    "\"非空且非匿名占位值 'Anonymous'\")）——停工上报"
)


def test_path_masked():
    """本机绝对路径 → <path>，命中数 1。"""
    out, n = server.mask_fatal_pii_values(r"读取 C:\a\b\c.txt 失败")
    assert "<path>" in out
    assert "c.txt" not in out
    assert n == 1


def test_pii_tuple_value_masked():
    """FATAL 行含 PII 元组 → 第 3 个元素（原始值）被替换为 '<值已隐藏>'。"""
    out, n = server.mask_fatal_pii_values(FATAL_ONE)
    assert "'<值已隐藏>'" in out
    assert "ZHANG SAN" not in out
    # 字段名与判定语保留（前端"拦截原因"卡片要能读懂是哪一项）
    assert "PatientName" in out
    assert "非空且非匿名占位值" in out
    assert n == 1


def test_path_and_pii_both_masked_hits_counted():
    """同时含路径与 PII → 两者都掩，n_hits = 路径命中数 + PII 值命中数。"""
    text = ("[E] 输出目录 C:\\work\\out\\case1 与 D:/tmp/x.log 不可写；"
            + FATAL_ONE + "；另一条：('case002.dcm', 'PatientID', '12345678', '核心 PII 非空')")
    out, n = server.mask_fatal_pii_values(text)
    assert out.count("<path>") == 2
    assert "'<值已隐藏>'" in out
    assert "12345678" not in out
    assert n == 2 + 2  # 2 条路径 + 2 个 PII 值


def test_gate_failures_element_is_str():
    """server.py:1221 语义：gate_failures 必须是 list[str]，不能是 [("...", 2)]。"""
    gf = [server.mask_text(FATAL_ONE) or "断言停工（exit 2），详见进度日志"]
    assert isinstance(gf[0], str)
    assert not isinstance(gf[0], (tuple, list))
    assert "ZHANG SAN" not in gf[0]
    # 空输入走 or 兜底，仍是 str
    assert isinstance(server.mask_text("") or "断言停工（exit 2），详见进度日志", str)


def test_idempotent():
    """对已掩码文本再跑一次，内容不变。"""
    once, _ = server.mask_fatal_pii_values(
        r"文件 C:\a\b\c.txt " + FATAL_ONE)
    twice, n2 = server.mask_fatal_pii_values(once)
    assert twice == once
    assert n2 == 0


def test_no_overmask_without_tuple_structure():
    """取向：非元组结构的裸"PatientName: 值"不掩（不猜姓名，宁少掩不多猜）。"""
    text = "PatientName: 'ZHANG SAN' (0x8005, VR=PN)"
    out, n = server.mask_fatal_pii_values(text)
    assert out == text
    assert n == 0


# ------------------------------------------------------------------ 审计整改回归
def test_double_quoted_tuple_value_masked():
    """N1①：三个元素全用双引号时（scan_pii repr 的另一形态）值字段同样被掩。"""
    text = ('PII 头扫描 FAIL ×1（首条：("case001.dcm", "PatientName", "ZHANG SAN", '
            "\"非空且非匿名占位值 'Anonymous'\")）——停工上报")
    out, n = server.mask_fatal_pii_values(text)
    assert "ZHANG SAN" not in out
    assert "'<值已隐藏>'" in out
    assert "PatientName" in out          # 字段名是定位用上下文，保留
    assert n == 1


def test_escaped_quote_in_value_no_residue():
    """N1②：值含转义引号（O\\'BRIEN）时整段被掩，不得留尾部残片。"""
    text = ("PII 头扫描 FAIL ×1（首条：('case003.dcm', 'PatientName', 'O\\'BRIEN', "
            "'非空且非匿名占位值')）——停工上报")
    assert "O\\'BRIEN" in text          # 构造正确性自检（确实是转义形态）
    out, n = server.mask_fatal_pii_values(text)
    assert "O\\'BRIEN" not in out
    assert "BRIEN" not in out            # 尾部残片零容忍（旧实现会漏出 'BRIEN'）
    assert out.count("<值已隐藏>") == 1
    assert "'<值已隐藏>'" in out
    assert n == 1


def test_step1_tail_absolute_path_masked():
    """B1：step1 子进程 stdout 尾部（含本机绝对路径）经 mask_text 后不再泄路径。"""
    tail = ("Traceback (most recent call last):\r\n"
            '  File "C:\\work\\case7\\preview\\qc.py", line 88, in main\r\n'
            "RuntimeError: 输入 D:/data/case7/series 下 DICOM 读取失败")
    out = server.mask_text(tail) or "step1 失败（无输出）"
    assert "C:\\work\\case7" not in out
    assert "D:/data/case7" not in out
    assert out.count("<path>") == 2
    assert "RuntimeError" in out         # 有用信息（失败原因）必须保留
    # 空尾 → 落 "step1 失败（无输出）" 兜底（mask_text("") == ""）
    assert (server.mask_text("") or "step1 失败（无输出）") == "step1 失败（无输出）"


def test_manifest_tail_masked_before_disk():
    """B2：报障附带的 manifest 尾部落盘前必须过掩码（盘符路径不得原样落盘）。"""
    tail = ('{"step": "step2", "cwd": "C:\\work\\case9\\out", "exit": 0}\n'
            '{"step": "step3", "log": "D:/tmp/manifest.log", "exit": 1}')
    masked = server.mask_text(tail or "")
    assert "C:\\work\\case9" not in masked
    assert "D:/tmp/manifest.log" not in masked
    assert masked.count("<path>") == 2
    assert "step3" in masked             # 结构信息保留（排障要用）
    assert server.mask_text(None or "") == ""
