#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T1 锁定测试：DICOM 头普查必须与 step1 读同一套切片（真患者 CT 假拒绝回归）。

覆盖（每条对应规格书 M 段的一个可验收断言）：
  1) 目录里"按文件名排序第一个 .dcm"是无像素/无几何的 CT 对象时，
     survey_dicom 不得抛 AttributeError，且行列/间距要来自真正被选中的轴位序列
     （实测复现形态：uploads/20261015-174400、-190829、-204748）
  2) 多序列混合目录：普查计数 = 被选中序列的去重后层数，不是文件数
  3) 同 z 重复层：计数按 Z_DEDUP_TOL_MM 去重（与 read_ct_series 同规则）
  4) 整目录都是非图像对象：干净 die(2) + 固定话术"无有效轴位切片"，
     不得留下 AttributeError 裸 traceback，也不得说成"几何不可重建"
  5) 回归护栏：干净单序列（pA/pB/pN 形态）下 selected == file_count，
     下游 NZ / QC_NLAYER 模板变量不得因此改动而漂移
  6) 同一次普查内 n_slices_selected 必须逐字节等于 len(read_ct_series(files))
     —— 这条是本缺陷的定义性不变量（两处实现必然再次分叉）
  7) 换读法后 slice_gap_measured 仍有效（server.case_slice_dz 消费该字段）

测试不碰真实患者数据：全部用 tmp_path 现造最小 DICOM。
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.dirname(HERE)
if PIPELINE not in sys.path:
    sys.path.insert(0, PIPELINE)

# run_all 模块级把 sys.stdout 换成 UTF-8 wrapper（run_all.py:73）；不立刻还原会让
# pytest 的 capture 临时文件在 wrapper 析构时关闭（session 收尾 ValueError: I/O operation
# on closed file）。处置约定沿用本仓 tests/test_optional_layer_cli_args.py:28-36。
_ORIG_STDOUT = sys.stdout
import run_all as RA                      # noqa: E402
_RA_STDOUT = sys.stdout                   # 故意保留引用，防 wrapper 提前析构
sys.stdout = _ORIG_STDOUT

from airway_geom import read_ct_series, Z_DEDUP_TOL_MM  # noqa: E402

SERIES_AXIAL = "1.2.840.10008.5.1.4.1.1.2.1.2"   # 轴位（要留下的那套）
SERIES_SCOUT = "1.2.840.10008.5.1.4.1.1.2.1.1"   # 另一套（层数少，应被忽略）
STUDY_UID = "1.2.840.10008.5.1.4.1.1.2.1.0"
ROWS = COLS = 4


def _write_ct(path, z, series_uid=SERIES_AXIAL, with_pixels=True, with_geometry=True):
    """写一张最小 CT 对象。

    with_geometry=False → 有 Modality=CT 与 SOP UID，但没有 PixelSpacing /
    Rows / Columns / SliceThickness / PixelData，也没有 IPP。
    这是真实导出目录里"字典序第一个文件"的实测形态（uploads/20261015-174400 等）。
    """
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
    ds.StudyInstanceUID = STUDY_UID
    ds.SeriesInstanceUID = series_uid
    ds.Modality = "CT"
    if with_geometry:
        ds.Rows, ds.Columns = ROWS, COLS
        ds.PixelSpacing = [0.7, 0.7]
        ds.SliceThickness = 1.0
        ds.ImagePositionPatient = [0.0, 0.0, float(z)]
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.BitsAllocated, ds.BitsStored, ds.HighBit = 16, 12, 11
        ds.PixelRepresentation = 0
        ds.RescaleSlope = 1
        ds.RescaleIntercept = -1024
        if with_pixels:
            ds.PixelData = np.full((ROWS, COLS), 100, dtype=np.uint16).tobytes()
    ds.save_as(str(path), enforce_file_format=True)


def _list_dcm(d):
    return sorted(os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith(".dcm"))


# ---------------------------------------------------------------- 1
def test_survey_survives_leading_geometryless_ct(tmp_path, capsys):
    """真实假拒绝形态：files[0] 无几何 ⇒ 不得崩，几何字段来自被选中的轴位序列。"""
    _write_ct(tmp_path / "000000.dcm", 0.0, with_geometry=False)
    for z in range(8):
        _write_ct(tmp_path / ("%06d.dcm" % (z + 1)), float(z))
    rec = RA.survey_dicom(str(tmp_path))          # 现状会抛 AttributeError
    assert rec["rows"] == ROWS and rec["columns"] == COLS
    assert [round(float(x), 6) for x in rec["pixel_spacing"]] == [0.7, 0.7]
    assert rec["file_count"] == 9
    assert rec["n_slices_selected"] == 8


# ---------------------------------------------------------------- 2
def test_survey_counts_selected_series_not_files(tmp_path):
    """多序列混合：计数取层数最多的那一组，不取文件总数。"""
    for z in range(5):
        _write_ct(tmp_path / ("A_%04d.dcm" % z), float(z), series_uid=SERIES_SCOUT)
    for z in range(12):
        _write_ct(tmp_path / ("B_%04d.dcm" % z), float(z), series_uid=SERIES_AXIAL)
    rec = RA.survey_dicom(str(tmp_path))
    assert rec["file_count"] == 17
    assert rec["n_slices_selected"] == 12
    assert rec["series_uid"] == SERIES_AXIAL


# ---------------------------------------------------------------- 3
def test_survey_dedups_same_z_layers(tmp_path):
    """同 z 重复层按容差去重（与 read_ct_series 同规则）。"""
    zs = [0.0, 0.0, 1.0, 1.0, 2.0, 3.0]
    for i, z in enumerate(zs):
        _write_ct(tmp_path / ("%04d.dcm" % i), z)
    rec = RA.survey_dicom(str(tmp_path))
    assert rec["file_count"] == 6
    assert rec["n_slices_selected"] == 4
    assert Z_DEDUP_TOL_MM == 1e-3     # 钉住判据来源，防日后改容差让本测试静默失真


# ---------------------------------------------------------------- 4
def test_survey_all_non_image_exits_2_with_actionable_message(tmp_path, capsys):
    """整目录都是非图像对象 ⇒ die(2) + 固定话术；禁止 AttributeError，禁止说"几何不可重建"。"""
    for i in range(3):
        _write_ct(tmp_path / ("%04d.dcm" % i), float(i), with_geometry=False)
    with pytest.raises(SystemExit) as ei:
        RA.survey_dicom(str(tmp_path))
    assert ei.value.code == 2
    out = capsys.readouterr().out
    assert "无有效轴位切片" in out
    assert "AttributeError" not in out
    assert "几何不可重建" not in out


# ---------------------------------------------------------------- 5
def test_survey_clean_series_selected_equals_file_count(tmp_path):
    """回归护栏：干净单序列下 selected == file_count ⇒ NZ/QC_NLAYER 不漂移。"""
    for z in range(10):
        _write_ct(tmp_path / ("%04d.dcm" % z), float(z))
    rec = RA.survey_dicom(str(tmp_path))
    assert rec["n_slices_selected"] == rec["file_count"] == 10


# ---------------------------------------------------------------- 6
def test_survey_selected_matches_read_ct_series(tmp_path):
    """定义性不变量：普查计数必须逐字节等于 step1 实际读入层数。"""
    _write_ct(tmp_path / "000000.dcm", 0.0, with_geometry=False)
    for z in range(5):
        _write_ct(tmp_path / ("S_%04d.dcm" % z), float(z), series_uid=SERIES_SCOUT)
    for z in range(9):
        _write_ct(tmp_path / ("B_%04d.dcm" % z), float(z))
    _write_ct(tmp_path / "B_dup.dcm", 3.0)      # 与 B_0003 同 z
    rec = RA.survey_dicom(str(tmp_path))
    slices, _report = read_ct_series(_list_dcm(str(tmp_path)))
    assert rec["n_slices_selected"] == len(slices) == 9


# ---------------------------------------------------------------- 7
def test_survey_slice_gap_still_usable(tmp_path):
    """换读法后 server.case_slice_dz 依赖的 slice_gap_measured 仍为正实测间距。"""
    for z in range(10):
        _write_ct(tmp_path / ("%04d.dcm" % z), float(z))
    rec = RA.survey_dicom(str(tmp_path))
    assert rec["slice_gap_measured"] == pytest.approx(1.0, abs=1e-6)
    assert rec["z_distinct_count"] == 10


# ---------------------------------------------------------------- 8
def test_survey_skip_accounting(tmp_path):
    """换源后 z_missing_ipp 必须等于 read_ct_series 报出的"被跳过总数"（含非图像对象），
    并新增 survey_skip_reasons 把原因字典带进 manifest——本轮缺陷的一半是
    "诊断信息算了但没人消费"。
    注意：_read_slice 先验 PixelData，故"Modality=CT 但无像素"的对象落"非图像"，
    不是"缺几何"（airway_geom.py:120-132），所以这里断言总数而非某个原因键。"""
    for i in range(2):
        _write_ct(tmp_path / ("NG_%04d.dcm" % i), float(i), with_geometry=False)
    for z in range(8):
        _write_ct(tmp_path / ("%04d.dcm" % z), float(z))
    rec = RA.survey_dicom(str(tmp_path))
    assert rec["z_missing_ipp"] == 2
    assert sum(rec["survey_skip_reasons"].values()) == 2
    assert rec["file_count"] == 10
    assert rec["n_slices_selected"] == 8
    # 上限 = max(1, int(0.05*10)) = 1 < 2 ⇒ 本例必须被层序结构判据判为不合格
    assert rec["z_structurally_ok"] is False


# ---------------------------------------------------------------- 9
def test_survey_first_file_names_the_geometry_source(tmp_path):
    """first_file 必须是"几何字段真正来自哪一张"，不得是字典序第一个文件。
    本条同时钉住实现依赖：slices[0].filename 必须由 pydicom 保留来源路径；
    若日后该属性丢失，本测试直接红，不允许静默退回 files[0] 那种假代表。"""
    _write_ct(tmp_path / "000000.dcm", 0.0, with_geometry=False)
    for z in range(1, 7):
        _write_ct(tmp_path / ("%06d.dcm" % z), float(z - 1))
    rec = RA.survey_dicom(str(tmp_path))
    assert rec["first_file"] == "000001.dcm"
    assert rec["first_file"] in os.listdir(str(tmp_path))
    assert rec["first_file"] != "000000.dcm"


# ---------------------------------------------------------------- 10
def test_survey_filename_order_still_discriminating(tmp_path):
    """M5 判据：换源后 filename_order_matches_physical 不得变成恒真。
    构造"文件名序下的 z 非单调（0,2,1,3）"的目录：物理 z 良构，但按文件名字典序读
    到的层序是乱序 ⇒ 该键必须为 False。naive 地拿 read_ct_series 已升序的 zs 去算
    会得到恒 True，本条就是抓那种实现。"""
    z_by_name = {"0000.dcm": 0.0, "0001.dcm": 2.0, "0002.dcm": 1.0, "0003.dcm": 3.0}
    for name, z in z_by_name.items():
        _write_ct(tmp_path / name, z)
    rec = RA.survey_dicom(str(tmp_path))
    assert rec["n_slices_selected"] == 4
    assert rec["z_monotonic_increasing"] is True          # 物理层序确实升序
    assert rec["filename_order_matches_physical"] is False  # 但文件名序是乱的


# ---------------------------------------------------------------- 11
def test_survey_empty_dir_exits_2_not_indexerror(tmp_path, capsys):
    """G3 裁决落盘：目录内无 .dcm 时不得抛 IndexError 裸 traceback，
    必须与其它不可用情形走同一条门：die(2) + "无有效轴位切片" + 文件数 0。"""
    assert os.listdir(str(tmp_path)) == []
    with pytest.raises(SystemExit) as ei:
        RA.survey_dicom(str(tmp_path))
    assert ei.value.code == 2
    out = capsys.readouterr().out
    assert "无有效轴位切片" in out
    assert "IndexError" not in out



