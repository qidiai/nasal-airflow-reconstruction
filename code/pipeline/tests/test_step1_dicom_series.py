# -*- coding: utf-8 -*-
"""step1 读入段：真实上传目录的 DICOM 匹配规则（2026-10-21 服务器实测崩溃后新增）。

钉住的契约（顺序即优先级，实现 = airway_geom.read_ct_series，step1 直接调用）：
    1) 逐文件过滤：读不开 / 无 PixelData（非图像对象）/ 缺 ImagePositionPatient
       或 Rows,Columns -> 跳过并计数，绝不中断；
    2) 按 SeriesInstanceUID 只保留层数最多的一组；缺 UID 的归一组参与比较；
       被忽略的组各记一条警告（组号/层数/SeriesDescription）；
    3) 同 z 去重（容差 1e-3mm），保留先出现的那层，去重数打印；
    4) 有效层 < 2 -> 打印"未找到有效 CT 轴位序列（找到 N 个 .dcm，其中有效 M 层）"
       并 SystemExit(1)；
    5) 干净输入（单一序列、无杂质、无重复 z）行为不变：230 层照旧，
       metrics_v2.json 与改动前逐字节一致（sha256 钉住）。

测试不碰真实患者数据：1-4 用 tmp_path 现造 DICOM；第 5 条只用合成的 L1 序列
（synth-001，无任何患者信息），目录不在就 skip。
"""
import ast
import glob
import hashlib
import os
import subprocess
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.dirname(HERE)
if PIPELINE not in sys.path:
    sys.path.insert(0, PIPELINE)

from airway_geom import read_ct_series, Z_DEDUP_TOL_MM  # noqa: E402

STEP1 = os.path.join(PIPELINE, "step1_airway_segment.py")

SERIES_A = "1.2.840.10008.5.1.4.1.1.2.1.1"      # scout（定位像）
SERIES_B = "1.2.840.10008.5.1.4.1.1.2.1.2"      # 轴位（要留下的那套）
STUDY_UID = "1.2.840.10008.5.1.4.1.1.2.1.0"
ROWS = COLS = 4


# ---------------------------------------------------------------- 造 DICOM
def _write_ct(path, z, series_uid=SERIES_B, desc="Sinus  0.75  H40s",
              with_ipp=True, with_pixels=True):
    """写一张最小 CT 轴位切片（能过 dcmread，且几何/像素齐备）。"""
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, CTImageStorage, generate_uid

    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = CTImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = CTImageStorage
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = STUDY_UID
    ds.Modality = "CT"
    if series_uid:
        ds.SeriesInstanceUID = series_uid
    if desc is not None:
        ds.SeriesDescription = desc
    ds.Rows, ds.Columns = ROWS, COLS
    ds.PixelSpacing = [0.7, 0.7]
    ds.SliceThickness = 1.0
    if with_ipp:
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
    return str(path)


def _write_non_image(path, sop_class, modality, desc=""):
    """写一个非图像对象（结构化报告 / DICOMDIR / 剂量单之类）：无 PixelData。"""
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = sop_class
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = sop_class
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = STUDY_UID
    ds.Modality = modality
    if desc:
        ds.SeriesDescription = desc
    ds.save_as(str(path), enforce_file_format=True)
    return str(path)


def _files(d):
    """目录里的 *.dcm（与 step1 的 glob 同一口径，dicom_qc.json 之类不算候选）。"""
    return sorted(glob.glob(os.path.join(str(d), "*.dcm")))


# ------------------------------------------- 1) 混合目录：不崩 + 计数正确
def test_mixed_dir_skips_non_image_and_unreadable_without_crashing(tmp_path):
    """5 张有效 CT + 1 个无 IPP 的对象 + 1 个文本改名 .dcm -> 有效 5 层。

    旧实现此处 AttributeError: 'FileDataset' object has no attribute
    'ImagePositionPatient'（排序时第一张非图像就炸）。
    """
    for z in range(5):
        _write_ct(tmp_path / ("IMG_%04d.dcm" % z), z)
    _write_ct(tmp_path / "no_ipp.dcm", 9, with_ipp=False)          # 有像素、缺几何
    (tmp_path / "notes.dcm").write_bytes(b"this is a plain text file\n")  # 读不开

    slices, rep = read_ct_series(_files(tmp_path))

    assert len(slices) == 5                                   # 有效层 = 5
    assert [float(s.ImagePositionPatient[2]) for s in slices] == [0.0, 1.0, 2.0, 3.0, 4.0]
    assert rep["n_files"] == 7
    assert rep["n_valid"] == 5
    assert rep["n_skipped"] == 2
    assert rep["skip_reasons"] == {"缺几何": 1, "读取失败": 1}
    assert rep["dedup"] == 0 and rep["ignored"] == []


def test_summary_line_reports_skip_breakdown(tmp_path, capsys):
    """[1/7] 摘要行：层数 + 跳过数 + 分类计数 + z 去重数（一行说完）。"""
    from pydicom.uid import BasicTextSRStorage, CTImageStorage

    for z in range(3):
        _write_ct(tmp_path / ("IMG_%04d.dcm" % z), z)
    _write_non_image(tmp_path / "report.dcm", BasicTextSRStorage, "SR", "Report Data")
    _write_non_image(tmp_path / "dicomdir.dcm", "1.2.840.10008.1.3.10", "DICOMDIR")
    (tmp_path / "broken.dcm").write_bytes(b"not a dicom\n")

    slices, rep = read_ct_series(_files(tmp_path))
    out = capsys.readouterr().out

    assert len(slices) == 3
    assert rep["skip_reasons"] == {"报告": 1, "DICOMDIR": 1, "读取失败": 1}
    assert "[1/7] 读取 3 层 DICOM ..." in out
    assert "跳过 3 个非图像/缺几何" in out
    assert "报告 1" in out and "DICOMDIR 1" in out and "读取失败 1" in out
    assert "z 去重 0 层" in out
    assert CTImageStorage  # 用到了 CT 图像 SOP（避免 import 被判无用）


# --------------------------------------- 2) 双序列：只留层数最多的那组
def test_two_series_keeps_largest_and_warns_about_the_other(tmp_path, capsys):
    """3 张 scout（Series A）+ 6 张轴位（Series B）-> 选 B（6 层），警告含 A。"""
    scout_desc, axial_desc = "Topogram  0.6  T20f", "Sinus  0.75  H40s"
    for i, z in enumerate([0.0, 600.0, 1200.0]):        # 定位像：z 跨度极大
        _write_ct(tmp_path / ("A_%d.dcm" % i), z, SERIES_A, scout_desc)
    for z in range(6):
        _write_ct(tmp_path / ("B_%d.dcm" % z), float(z), SERIES_B, axial_desc)

    slices, rep = read_ct_series(_files(tmp_path))
    out = capsys.readouterr().out

    assert len(slices) == 6                                   # 选中 B
    assert {str(s.SeriesInstanceUID) for s in slices} == {SERIES_B}
    assert [float(s.ImagePositionPatient[2]) for s in slices] == [0.0, 1, 2, 3, 4, 5]
    assert rep["series_uid"] == SERIES_B
    assert rep["n_skipped"] == 0                              # scout 是合法图像，只按组丢弃
    assert len(rep["ignored"]) == 1
    assert rep["ignored"][0] == {"series": SERIES_A, "n": 3, "desc": scout_desc}
    assert "序列选择：保留 Series %s（6 层）" % SERIES_B in out
    assert "忽略 1 组（%s 3 层）" % scout_desc in out


def test_series_without_uid_participates_as_one_group(tmp_path):
    """缺 SeriesInstanceUID 的（老设备/自制）归一组参与比较，赢了也能选中。"""
    for z in range(4):
        _write_ct(tmp_path / ("n_%d.dcm" % z), z, series_uid=None, desc="")
    for z in range(2):
        _write_ct(tmp_path / ("u_%d.dcm" % z), z + 10, SERIES_A, "scout")

    slices, rep = read_ct_series(_files(tmp_path))

    assert len(slices) == 4                                   # 无 UID 组 4 层胜出
    assert rep["series_uid"] is None                          # 对外报"无 UID"
    assert [g["n"] for g in rep["ignored"]] == [2]


# ------------------------------------------------------ 3) 同 z 去重
def test_duplicate_z_is_deduped_keeping_the_first(tmp_path):
    """同 z 两张（容差内）-> 去重后 5 层，去重数 = 1。"""
    for z in range(4):
        _write_ct(tmp_path / ("IMG_%04d.dcm" % z), z)
    _write_ct(tmp_path / "dup.dcm", 2.0 + Z_DEDUP_TOL_MM / 2)   # 5e-4mm：算重复
    _write_ct(tmp_path / "far.dcm", 4.0 + 10 * Z_DEDUP_TOL_MM)  # 1e-2mm：算新层

    slices, rep = read_ct_series(_files(tmp_path))

    assert len(slices) == 5                                   # 4 + 重复 1（丢掉）+ 独立 1 = 5
    assert rep["dedup"] == 1
    zs = [float(s.ImagePositionPatient[2]) for s in slices]
    assert zs[:4] == [0.0, 1.0, 2.0, 3.0]                     # 同 z 保留先出现的那层
    assert abs(zs[-1] - 4.01) < 1e-9


def test_pure_duplicate_z_five_layers(tmp_path):
    """5 个 z + 其中 1 个重复 -> 去重后仍是 5 层（题面口径）。"""
    for z in range(5):
        _write_ct(tmp_path / ("IMG_%04d.dcm" % z), z)
    _write_ct(tmp_path / "IMG_0002_copy.dcm", 2.0)

    slices, rep = read_ct_series(_files(tmp_path))

    assert len(slices) == 5 and rep["dedup"] == 1


# ------------------------------------------- 4) 全无效 -> SystemExit(1)
def test_all_invalid_exits_with_reason(tmp_path, capsys):
    """只有无 IPP 的对象 -> SystemExit(1)，文案含"找到 N 个 .dcm ... 有效 M 层"。"""
    _write_ct(tmp_path / "no_ipp.dcm", 0.0, with_ipp=False)

    with pytest.raises(SystemExit) as ei:
        read_ct_series(_files(tmp_path))
    out = capsys.readouterr().out

    assert ei.value.code == 1
    assert "未找到有效 CT 轴位序列" in out
    assert "找到 1 个 .dcm，其中有效 0 层" in out


def test_single_valid_layer_is_also_rejected(tmp_path, capsys):
    """只有 1 层有效也算失败（z 方向无法建体数据）。"""
    _write_ct(tmp_path / "only.dcm", 0.0)

    with pytest.raises(SystemExit) as ei:
        read_ct_series(_files(tmp_path))
    assert ei.value.code == 1
    assert "其中有效 1 层" in capsys.readouterr().out


# ------------------------------------------------ 5) 接线：step1 必须用它
def _step1_tree():
    with open(STEP1, encoding="utf-8") as f:
        return ast.parse(f.read(), filename=STEP1)


def test_step1_calls_read_ct_series():
    """生产代码必须从 airway_geom 导入并调用 read_ct_series（防"测的是孤儿函数"）。"""
    tree = _step1_tree()
    assert any(
        isinstance(n, ast.ImportFrom) and n.module == "airway_geom"
        and any(a.name == "read_ct_series" for a in n.names)
        for n in tree.body), "step1 未从 airway_geom 导入 read_ct_series"

    called = [n for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
              and n.func.id == "read_ct_series"]
    assert len(called) == 1, "step1 应恰好调用一次 read_ct_series"
    assert [ast.unparse(a) for a in called[0].args] == ["files"]


def test_step1_has_no_blind_sort_on_ipp():
    """可执行代码里不得再有无过滤的 dcmread 列表推导 + 盲排序 IPP（旧崩溃点）。"""
    tree = _step1_tree()
    bad = [ast.unparse(n) for n in ast.walk(tree)
           if isinstance(n, ast.Call) and "slices.sort(key=lambda s: float(s.ImagePositionPatient[2]))"
           in ast.unparse(n)]
    assert bad == [], "step1 仍存在无过滤的 IPP 盲排序：%r" % (bad,)
    assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                   and n.func.attr == "dcmread" for n in ast.walk(tree)), \
        "step1 不应再自己 dcmread（读入规则统一在 airway_geom.read_ct_series）"


# ------------------------------------- 6) 干净输入回归：230 层 + 逐字节不变
CLEAN_DICOM_DIR = os.environ.get(
    "QIDI_STEP1_CLEAN_DICOM", r"C:\qidi-synth-work\dicom\synth-001")
# 改动前（旧读入段：无过滤 dcmread + IPP 盲排序）跑 synth-001 得到的
# metrics_v2.json sha256——新读入段必须逐字节一致。
GOLDEN_METRICS_SHA256 = "9c02a087e799d094a437148751e508c26b2f6719b804f28d35d4aef1c6e74f13"


def _clean_dir_or_skip():
    if not os.path.isdir(CLEAN_DICOM_DIR):
        pytest.skip("干净输入目录不存在：%s" % CLEAN_DICOM_DIR)
    return _files(CLEAN_DICOM_DIR)


def test_clean_dir_reads_all_230_layers_unchanged():
    """干净 230 层目录：一层不丢、一个不跳、不去重、无被忽略序列。"""
    slices, rep = read_ct_series(_clean_dir_or_skip())

    assert len(slices) == 230 and rep["n_valid"] == 230
    assert rep["n_skipped"] == 0 and rep["skip_reasons"] == {}
    assert rep["dedup"] == 0
    assert rep["ignored"] == []
    zs = [float(s.ImagePositionPatient[2]) for s in slices]
    assert zs == sorted(zs), "层序必须仍按 z 升序"


def test_clean_dir_metrics_byte_identical_to_pre_change(tmp_path):
    """端到端：step1 跑干净目录，metrics_v2.json 与改动前 sha256 一致。"""
    files = _clean_dir_or_skip()
    if not files:
        pytest.skip("干净输入目录为空")

    out = tmp_path / "step1_out"
    r = subprocess.run([sys.executable, STEP1, "--dicom-dir", CLEAN_DICOM_DIR,
                        "--out-dir", str(out)],
                       capture_output=True, text=True, encoding="utf-8", timeout=1800)
    assert r.returncode == 0, r.stderr[-2000:]
    assert "[1/7] 读取 230 层 DICOM ..." in r.stdout

    blob = (out / "metrics_v2.json").read_bytes()
    got = hashlib.sha256(blob).hexdigest()
    assert got == GOLDEN_METRICS_SHA256, (
        "干净输入的 metrics 变了（读入段不得影响下游数值）。若工具链"
        "（numpy/scipy/trimesh）升级导致合法漂移，请重新取基线并说明原因：%s" % got)