#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T4 门禁话术诚实化：钉住 F1-F5 的措辞 / 白名单 / 日志 / die 机制。

只测本任务新增或修改的行为，不重复既有门的判定用例：
  F3  DieExit 数字退出码 + str(e) 带消息 + 非 DieExit 的 SystemExit 原行为；
  F4  FATAL 行同行写 stderr（stdout 既有内容不变）；
  F1  层序停工文案只宣称实际失败条件、恒真项标为非判据、「缺IPP层数」消失；
  F2  恒真键 z_monotonic_increasing 移出 web 白名单；F5 四个 z_gap_* 进白名单；
  B10 日志停打印恒真 z 单调、保留有信息量的 filename_order_matches_physical；
  验收 门判定式（z_structurally_ok 三条件 / 5% 容差 / 间隙一致性门）逐字未动。

不碰真实患者数据：survey 用 tmp_path 现造最小 DICOM / 空目录，源码类断言只读文件。
"""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.dirname(HERE)
if PIPELINE not in sys.path:
    sys.path.insert(0, PIPELINE)

# 沿用本仓 tests/test_survey_series_select.py:31-37 的处置约定：run_all 模块级
# 把 sys.stdout 换成 UTF-8 wrapper，不立刻还原会让 pytest 的 capture 临时文件在
# wrapper 析构时关闭（session 收尾 ValueError: I/O operation on closed file）。
_ORIG_STDOUT = sys.stdout
import run_all as RA                      # noqa: E402
_RA_STDOUT = sys.stdout                   # 故意保留引用，防 wrapper 提前析构
sys.stdout = _ORIG_STDOUT

RUN_ALL_SRC = os.path.join(PIPELINE, "run_all.py")
SERVER_SRC = os.path.join(PIPELINE, "server.py")

STOP_GATE_PREFIX = "层序结构（读层完整性）门 FAIL：实际失败条件="
SKIP_LABEL = "跳过文件数（非图像/缺几何/读取失败）"
FOUR_ZGAP = ("z_gap_max_abs_dev_mm", "z_gap_max_rel_dev",
             "z_gap_tol_mm", "z_gap_bad_pairs")


def _src(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _write_ct(path, z):
    """最小轴位 CT（几何+像素齐全）；造一个均匀的 4 层栈给 survey_dicom 用。"""
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, CTImageStorage, generate_uid
    import numpy as np

    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = CTImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = CTImageStorage
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = "1.2.840.10008.5.1.4.1.1.2.1.0"
    ds.SeriesInstanceUID = "1.2.840.10008.5.1.4.1.1.2.1.2"
    ds.Modality = "CT"
    ds.Rows, ds.Columns = 4, 4
    ds.PixelSpacing = [0.7, 0.7]
    ds.SliceThickness = 1.0
    ds.ImagePositionPatient = [0.0, 0.0, float(z)]
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated, ds.BitsStored, ds.HighBit = 16, 12, 11
    ds.PixelRepresentation = 0
    ds.RescaleSlope = 1
    ds.RescaleIntercept = -1024
    ds.PixelData = np.full((4, 4), 100, dtype=np.uint16).tobytes()
    ds.save_as(str(path), enforce_file_format=True)


# ---------------------------------------------------------------- F3 DieExit
def test_die_exit_carries_numeric_code_and_message():
    """退出码保持数字（既有断言依赖），str(e)/msg 带可读停工原因。"""
    with pytest.raises(RA.DieExit) as ei:
        RA.die(2, "探针停工原因")
    e = ei.value
    assert isinstance(e, SystemExit)
    assert e.code == 2
    assert e.msg == "探针停工原因"
    assert str(e) == "探针停工原因"


def test_die_exit_keeps_code_3():
    """die(3) 路径（backend=custom）退出码仍为 3，不被 __str__ 改动。"""
    with pytest.raises(RA.DieExit) as ei:
        RA.die(3, "backend 不可用")
    assert ei.value.code == 3
    assert str(ei.value) == "backend 不可用"


def test_non_dieexit_systemexit_str_unchanged():
    """对非 DieExit 的 SystemExit 保持 str(e) 原行为（server.py else 分支依赖）。"""
    assert str(SystemExit(2)) == "2"
    assert str(SystemExit(3)) == "3"


def test_survey_die_error_readable_not_bare_2(tmp_path):
    """CF7/#84：空目录 → die(2) → DieExit；str(e) 不再裸 "2"，web survey_error 可读。"""
    with pytest.raises(SystemExit) as ei:
        RA.survey_dicom(str(tmp_path))
    e = ei.value
    assert e.code == 2
    assert isinstance(e, RA.DieExit)
    assert str(e) != "2"
    assert "无有效轴位切片" in str(e)


# ---------------------------------------------------------------- F4 stderr
def test_fatal_line_written_to_stderr_and_stdout_unchanged(capsys):
    """B11：FATAL 行除 stdout/manifest-progress 外同行写 stderr，stdout 内容不变。"""
    with pytest.raises(RA.DieExit):
        RA.die(2, "FATALPROBE")
    cap = capsys.readouterr()
    line = "!!! FATAL (exit 2): FATALPROBE"
    assert line in cap.out                 # stdout 既有内容不变
    assert line in cap.err                 # 同行进 stderr
    assert "[run_all]" in cap.err


# ---------------------------------------------------------------- F1 停工文案
def test_structural_message_only_claims_real_condition():
    """恒真项不再被宣称为失败判据；只报实际失败条件；「缺IPP层数」消失；钉住具体串。"""
    rec = {"z_distinct_count": 8, "z_distinct_gap_median": 1.0,
           "z_missing_ipp": 2, "file_count": 10}
    msg = RA.structurally_ok_failure_message(rec)
    assert "缺IPP层数" not in msg
    assert "缺IPP" not in msg
    assert "层序结构断言 FAIL" not in msg
    assert "非判据" in msg
    assert STOP_GATE_PREFIX in msg
    assert "跳过文件数（非图像/缺几何/读取失败）超过 5% 容差上限" in msg
    assert SKIP_LABEL in msg
    assert "几何不可重建，停工上报" in msg


def test_structural_message_lists_context_numbers():
    """其余数值作上下文列出，且恒真两项显式标注「构造性/非判据」。"""
    rec = {"z_distinct_count": 8, "z_distinct_gap_median": 1.0,
           "z_missing_ipp": 2, "file_count": 10}
    msg = RA.structurally_ok_failure_message(rec)
    assert "有效不同层数=8" in msg
    assert "层间距中位=1.0mm" in msg
    assert SKIP_LABEL + "=2" in msg
    assert "文件总数=10" in msg
    assert "（构造性≥2，非判据）" in msg
    assert "（构造性>0，非判据）" in msg


def test_work_stop_callsites_share_helper_and_old_wording_gone():
    """F1 问题定性：两处停工文案统一经一个小函数；旧误导话术与裸 "2" 机制消失。"""
    ra = _src(RUN_ALL_SRC)
    sv = _src(SERVER_SRC)
    assert "die(2, structurally_ok_failure_message(survey))" in ra
    assert "RA.structurally_ok_failure_message(survey)" in sv
    assert "缺IPP层数" not in ra
    assert "缺IPP" not in sv
    assert "层序结构断言 FAIL" not in ra
    assert "层序结构断言 FAIL" not in sv
    # F1 gate 名裁决（写台账：改为「DICOM 头普查（读层完整性）」）
    assert 'gate="DICOM 头普查（读层完整性）"' in sv
    assert 'gate="DICOM 头普查（层序结构断言）"' not in sv
    # F3 server.py：DieExit 取 msg，非 DieExit 保持 str(e)
    assert "e.msg if isinstance(e, RA.DieExit) else str(e)" in sv


# ---------------------------------------------------------------- F2 / F5 白名单
def test_web_whitelist_has_four_zgap_and_drops_monotonic():
    """F2 恒真键移出 web 白名单；F5 四个 z_gap_* 进入白名单；既有排版风格保留。"""
    sv = _src(SERVER_SRC)
    i = sv.index('rec["survey"] = {k: survey.get(k) for k in')
    j = sv.index("    except SystemExit as e:", i)
    block = sv[i:j]
    for k in FOUR_ZGAP:
        assert ('"%s"' % k) in block, "白名单缺键 %s" % k
    assert "z_monotonic_increasing" not in block
    assert '"z_distinct_count", "z_duplicate_count"' in block


def test_zgap_keys_in_real_survey_json_serializable(tmp_path):
    """F5/#81：四键在源 rec 中真实存在，且白名单投影 JSON 可序列化（bad_pairs 为 list）。"""
    for z in range(4):
        _write_ct(tmp_path / ("%04d.dcm" % z), float(z))
    survey = RA.survey_dicom(str(tmp_path))
    for k in FOUR_ZGAP:
        assert k in survey, "源 rec 缺键 %s" % k
    projected = {k: survey.get(k) for k in FOUR_ZGAP}
    assert isinstance(projected["z_gap_bad_pairs"], list)
    json.dumps(projected)                 # 不抛 = 投影可 JSON 序列化
    assert survey["z_structurally_ok"] is True


# ---------------------------------------------------------------- B10 日志
def test_run_all_log_drops_constant_monotonic():
    """B10/CF3：停打印恒真 z 单调，保留有信息量的 filename_order_matches_physical。"""
    ra = _src(RUN_ALL_SRC)
    assert 'f"z 单调' not in ra
    assert "B10/CF3：z_monotonic_increasing 构造性恒真" in ra
    assert 'f"文件名序' in ra


# ---------------------------------------------------------------- 验收：判定逻辑零改动
def test_gate_judgment_expressions_byte_unchanged():
    """门判定片段逐字仍在：本任务只改措辞 / 白名单 / 日志 / die 机制。"""
    ra = _src(RUN_ALL_SRC)
    for frag in (
        'len(zs_phys) >= 2',
        'rec["z_distinct_gap_median"] > 0.0',
        'rec["z_missing_ipp"] <= max(1, int(0.05 * len(files)))',
        'if not greport["uniform"]:',
        'die(2, f"层间距不一致：中位间隙',
    ):
        assert frag in ra, "门判定片段被改：%s" % frag
