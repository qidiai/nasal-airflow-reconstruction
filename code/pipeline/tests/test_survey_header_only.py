# -*- coding: utf-8 -*-
"""T3：`survey_dicom` 只读头（A2-Q2）——等价性第一约束 + 透传契约。

基线一律取 a0fe149 的 `run_all.py`（`git show a0fe149:code/pipeline/run_all.py`
写成临时副本，在**子进程**里 import 成 run_all 跑同一目录），不动工作树、不污染
本进程的 stdout/module 状态。

钉住的契约：
  1) 干净/混合目录：rec **逐键**等于基线（夹具 = 纯 CT + 非图像 DICOM +
     缺几何 CT + 改名的非 DICOM 垃圾文件）；
  2) 截断像素的文件：两侧**都收下**（n_slices_selected 含它、skip_reasons 不变、
     键集差为空）——pydicom 3.0.2 实测：截断像素值不抛错不告警，返回短 PixelData；
  3) FloatPixelData-only：两侧**都跳过**（_read_slice 只认 PixelData，注入别家 tag
     就会制造分叉）；
  4) 压缩传输语法：原样整读透传（像素不是空占位），rec 与基线一致；
  5) 显式只读 kwarg 透传、作用域退出即恢复、其它线程行为不变（thread-local）；
  6) 读失败不被吞（损坏文件在两侧按"读取失败"同类跳过）。
"""
import json
import os
import subprocess
import sys
import threading

import numpy as np
import pydicom
import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.encaps import encapsulate
from pydicom.uid import (CTImageStorage, ExplicitVRLittleEndian, JPEGBaseline8Bit,
                         generate_uid)

HERE = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(PIPELINE))
if PIPELINE not in sys.path:
    sys.path.insert(0, PIPELINE)

_ORIG_STDOUT = sys.stdout
import run_all as RA                                  # noqa: E402
_RA_STDOUT = sys.stdout
sys.stdout = _ORIG_STDOUT

# run_all 模块级把 sys.stdout 换成 UTF-8 wrapper（run_all.py:73）；不立刻还原会让
# pytest 的 capture 临时文件在 wrapper 析构时关闭（收尾 ValueError: I/O operation on
# closed file）。处置沿用本仓 test_survey_series_select.py:31-36 同一约定。

BASE_REV = "a0fe149"          # T3 基线：改动前的 HEAD（run_all.py 原版）
ROWS = COLS = 4
STUDY_UID = "1.2.840.10008.5.1.4.1.1.2.1.0"
SERIES_UID = "1.2.840.10008.5.1.4.1.1.2.1.2"
SR_SOP = "1.2.840.10008.5.1.4.1.1.88.33"       # Comprehensive SR（非图像对象）


# ---------------------------------------------------------------- 夹具构造
def _new_ds(path, ts=ExplicitVRLittleEndian, sop=CTImageStorage):
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = sop
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ts
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = sop
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = STUDY_UID
    ds.SeriesInstanceUID = SERIES_UID
    ds.Modality = "CT"
    return ds


def _write_ct(path, z, with_geometry=True, with_pixels=True, truncate=0):
    ds = _new_ds(path)
    ds.Rows, ds.Columns = ROWS, COLS
    ds.PixelSpacing = [0.7, 0.7]
    ds.SliceThickness = 1.0
    if with_geometry:
        ds.ImagePositionPatient = [0.0, 0.0, float(z)]
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated, ds.BitsStored, ds.HighBit = 16, 12, 11
    ds.PixelRepresentation = 0
    ds.RescaleSlope, ds.RescaleIntercept = 1, -1024
    if with_pixels:
        ds.PixelData = np.full((ROWS, COLS), 100 + int(z), dtype=np.uint16).tobytes()
    ds.save_as(str(path), enforce_file_format=True)
    if truncate:                       # 截掉像素值尾部若干字节（元素头完好）
        size = os.path.getsize(str(path))
        with open(str(path), "r+b") as fh:
            fh.truncate(size - truncate)
    return str(path)


def _write_float_pixel_ct(path, z):
    """FloatPixelData-only 的 CT 切片（无 PixelData）：今天的读层器必然跳过。"""
    ds = _new_ds(path)
    ds.Rows, ds.Columns = ROWS, COLS
    ds.PixelSpacing = [0.7, 0.7]
    ds.SliceThickness = 1.0
    ds.ImagePositionPatient = [0.0, 0.0, float(z)]
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated, ds.BitsStored, ds.HighBit = 32, 32, 31
    ds.PixelRepresentation = 3          # 浮点
    ds.FloatPixelData = np.zeros((ROWS, COLS), dtype=np.float32).tobytes()
    ds.save_as(str(path), enforce_file_format=True)
    return str(path)


def _write_encapsulated_ct(path, z):
    """压缩传输语法（JPEG Baseline）样本：像素为封装式，元素长度语义不可裸信。"""
    ds = _new_ds(path, ts=JPEGBaseline8Bit)
    ds.Rows, ds.Columns = ROWS, COLS
    ds.PixelSpacing = [0.7, 0.7]
    ds.SliceThickness = 1.0
    ds.ImagePositionPatient = [0.0, 0.0, float(z)]
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated, ds.BitsStored, ds.HighBit = 16, 12, 11
    ds.PixelRepresentation = 0
    frame = b"\xff\xd8" + b"\x00" * 60 + b"\xff\xd9"
    ds.PixelData = encapsulate([frame], has_bot=True)
    ds["PixelData"].VR = "OB"
    ds.save_as(str(path), enforce_file_format=True)
    return str(path)


def _write_non_image(path):
    ds = _new_ds(path, sop=SR_SOP)
    ds.SpecificCharacterSet = "ISO_IR 192"      # 免去 GBK 编码告警（不影响跳过分类）
    ds.Modality = "SR"
    ds.SeriesDescription = "报告"
    ds.save_as(str(path), enforce_file_format=True)
    return str(path)


# ---------------------------------------------------------------- 基线（子进程）
def _baseline_rec(tmp_path, dicom_dir):
    """a0fe149 的 survey_dicom 在同一目录上的 rec（子进程隔离，JSON 往返）。"""
    src = subprocess.run(["git", "-C", REPO, "show",
                          "%s:code/pipeline/run_all.py" % BASE_REV],
                         capture_output=True, check=True).stdout
    base_dir = tmp_path / "_baseline"
    base_dir.mkdir(exist_ok=True)
    (base_dir / "run_all.py").write_bytes(src)
    driver = ("import json,sys,run_all;"
              "print('@@' + json.dumps(run_all.survey_dicom(sys.argv[1]),"
              " ensure_ascii=False, sort_keys=True, default=str))")
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = os.pathsep.join([str(base_dir), PIPELINE])
    out = subprocess.run([sys.executable, "-c", driver, str(dicom_dir)],
                         capture_output=True, text=True, encoding="utf-8",
                         env=env, cwd=str(tmp_path))
    assert out.returncode == 0, out.stdout[-1500:] + out.stderr[-2000:]
    line = [ln for ln in out.stdout.splitlines() if ln.startswith("@@")][-1]
    return json.loads(line[2:])


def _assert_rec_equal(rec, base):
    """逐键比对：键集相同、逐键值相同（报告差异键，便于定位）。"""
    assert set(rec) == set(base), "键集不同：%r" % (set(rec) ^ set(base))
    diff = {k: (base[k], rec[k]) for k in base if rec[k] != base[k]}
    assert diff == {}, "逐键差异：%r" % diff


# ------------------------------------------------- 1) 混合目录：rec 逐键等于基线
def test_clean_dir_rec_matches_baseline_key_by_key(tmp_path):
    d = tmp_path / "dcm"
    d.mkdir()
    for z in range(4):
        _write_ct(d / ("ct_%02d.dcm" % z), float(z))
    _write_non_image(d / "report.dcm")                       # 非图像 DICOM
    _write_ct(d / "nogeom.dcm", 9.0, with_geometry=False)    # 缺几何 CT
    (d / "garbage.dcm").write_text("not a dicom at all\n", encoding="utf-8")  # 读不开

    rec = RA.survey_dicom(str(d))
    base = _baseline_rec(tmp_path, d)

    _assert_rec_equal(rec, base)
    assert rec["n_slices_selected"] == 4
    assert rec["file_count"] == 7
    assert rec["survey_skip_reasons"] == {"报告": 1, "缺几何": 1, "读取失败": 1}


# ------------------------------------- 2) 截断像素：两侧都收下、skip_reasons 不变
def test_truncated_pixel_file_included_on_both_sides(tmp_path):
    d = tmp_path / "dcm"
    d.mkdir()
    for z in range(4):
        _write_ct(d / ("ct_%02d.dcm" % z), float(z))
    _write_ct(d / "trunc.dcm", 4.0, truncate=10)             # 32 字节像素值砍掉 10
    _write_non_image(d / "report.dcm")

    rec = RA.survey_dicom(str(d))
    base = _baseline_rec(tmp_path, d)

    _assert_rec_equal(rec, base)
    assert rec["n_slices_selected"] == 5      # 截断层两侧都在
    assert rec["survey_skip_reasons"] == {"报告": 1}


# ------------------------------- 3) FloatPixelData-only：两侧都跳过，不得注入 PixelData
def test_float_pixel_only_file_skipped_on_both_sides(tmp_path):
    d = tmp_path / "dcm"
    d.mkdir()
    for z in range(3):
        _write_ct(d / ("ct_%02d.dcm" % z), float(z))
    fp = _write_float_pixel_ct(d / "float_only.dcm", 3.0)

    # 拦截器本身不得给只读头结果凭空造 PixelData（那会把今天跳过的东西变成层）
    with RA._DicomHeaderOnly():
        ds = pydicom.dcmread(fp)
    assert not hasattr(ds, "PixelData")
    assert hasattr(ds, "FloatPixelData")
    # 强断言：拦截器必须按文件里实际存在的 tag 注入，而非一律注入 PixelData。
    # 行为级锁定：注入的是**空占位**——若干预器退化成 no-op 透传，这里会拿到真实
    # （非空）FloatPixelData 值；同时 PixelData 必须依然缺席（今天两侧都跳过它）。
    with RA._DicomHeaderOnly():
        ds = pydicom.dcmread(fp)
    assert ds.FloatPixelData == b""
    assert not hasattr(ds, "PixelData")

    rec = RA.survey_dicom(str(d))
    base = _baseline_rec(tmp_path, d)

    _assert_rec_equal(rec, base)
    assert rec["n_slices_selected"] == 3
    assert rec["survey_skip_reasons"] == {"非图像": 1}


# ------------------------------------------- 4) 压缩传输语法：原样整读透传（不注入空占位）
def test_compressed_transfer_syntax_passes_through(tmp_path):
    d = tmp_path / "dcm"
    d.mkdir()
    for z in range(3):
        _write_ct(d / ("ct_%02d.dcm" % z), float(z))
    enc = _write_encapsulated_ct(d / "encap.dcm", 3.0)

    outside = pydicom.dcmread(enc)
    assert len(outside.PixelData) > 0
    with RA._DicomHeaderOnly():
        inside = pydicom.dcmread(enc)
    assert inside.PixelData == outside.PixelData      # 透传：不是 b"" 占位
    assert inside.Rows == outside.Rows

    rec = RA.survey_dicom(str(d))
    base = _baseline_rec(tmp_path, d)
    _assert_rec_equal(rec, base)
    assert rec["n_slices_selected"] == 4              # 压缩层在被选序列里，两侧同


# --------------------------- 5) 显式只读 kwarg 透传 / 退出即恢复 / 其它线程不变
def test_explicit_kwargs_passthrough_and_scope_restore(tmp_path):
    d = tmp_path / "dcm"
    d.mkdir()
    p = _write_ct(d / "one.dcm", 0.0)
    orig = pydicom.dcmread

    with RA._DicomHeaderOnly():
        ds = pydicom.dcmread(p, stop_before_pixels=True)      # 显式只读语义：原样透传
        assert not hasattr(ds, "PixelData")
        ds2 = pydicom.dcmread(p, force=True)                  # force：原样整读透传
        assert len(ds2.PixelData) == ROWS * COLS * 2
        # 其它线程不在作用域内 -> 行为与改动前一致（thread-local）
        seen = {}

        def worker():
            seen["len"] = len(pydicom.dcmread(p).PixelData)

        t = threading.Thread(target=worker)
        t.start()
        t.join()
        assert seen["len"] == ROWS * COLS * 2
    assert pydicom.dcmread is orig                            # try/finally 恢复


# ------------------------------------------------- 6) 读失败不被吞（原路径分类不变）
def test_unreadable_file_keeps_read_failure_reason(tmp_path):
    d = tmp_path / "dcm"
    d.mkdir()
    for z in range(3):
        _write_ct(d / ("ct_%02d.dcm" % z), float(z))
    (d / "broken.dcm").write_bytes(b"\x00\x01\x02\x03" * 8)   # 无 preamble/元信息

    rec = RA.survey_dicom(str(d))
    base = _baseline_rec(tmp_path, d)

    _assert_rec_equal(rec, base)
    assert rec["survey_skip_reasons"] == {"读取失败": 1}
    assert rec["n_slices_selected"] == 3


# ---------------------------------- 7) 并发二次进入：orig 采集必须在锁内（回归钉）
def test_concurrent_scope_entry_no_recursion(tmp_path):
    d = tmp_path / "dcm"
    d.mkdir()
    for z in range(3):
        _write_ct(d / ("ct_%02d.dcm" % z), float(z))
    p = str(d / "ct_00.dcm")
    orig = pydicom.dcmread
    lens, errs = [], []

    def worker():
        try:
            with RA._DicomHeaderOnly():
                lens.append(len(pydicom.dcmread(p).PixelData))
        except BaseException as exc:            # RecursionError 不是 Exception 子类
            errs.append(repr(exc))

    ts = [threading.Thread(target=worker) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert errs == [], errs
    assert sorted(lens) == [0, 0]   # 作用域内默认读 = 空占位注入（见用例 3），两线程同
    assert pydicom.dcmread is orig


# ------------------------ 8) Deflated：is_compressed=False 但非裸长度，须整读透传
def _write_deflated_ct(path, z):
    plain = _write_ct(str(path) + ".plain.dcm", float(z))
    ds = pydicom.dcmread(plain)
    ds.file_meta.TransferSyntaxUID = pydicom.uid.DeflatedExplicitVRLittleEndian
    ds.save_as(str(path), enforce_file_format=True)
    os.remove(plain)
    return str(path)


def test_deflated_transfer_syntax_matches_baseline(tmp_path):
    d = tmp_path / "dcm"
    d.mkdir()
    for z in range(3):
        _write_ct(d / ("ct_%02d.dcm" % z), float(z))
    dfl = _write_deflated_ct(d / "defl.dcm", 3.0)

    with RA._DicomHeaderOnly():
        ds = pydicom.dcmread(dfl)
    assert len(ds.PixelData) == ROWS * COLS * 2        # 解压后整读透传，不是空占位
    assert not ds.file_meta.TransferSyntaxUID.is_compressed

    rec = RA.survey_dicom(str(d))
    base = _baseline_rec(tmp_path, d)
    _assert_rec_equal(rec, base)
    assert rec["n_slices_selected"] == 4              # deflated 层被当有效层
    assert rec["survey_skip_reasons"] == {}


# ------------------------------- 9) 垃圾 / 空 TransferSyntaxUID：不得抛 ValueError
def test_bogus_transfer_syntax_matches_baseline(tmp_path):
    d = tmp_path / "dcm"
    d.mkdir()
    for z in range(4):
        _write_ct(d / ("ct_%02d.dcm" % z), float(z))
    bad = _write_ct(d / "bad_ts.dcm", 4.0)
    ds = pydicom.dcmread(bad)
    ds.file_meta.TransferSyntaxUID = "not-a-uid"     # 垃圾 UID：属性判定会抛 ValueError
    ds.save_as(bad, enforce_file_format=True)
    empty = _write_ct(d / "empty_ts.dcm", 5.0)
    ds = pydicom.dcmread(empty)
    ds.file_meta.TransferSyntaxUID = ""             # 空 UID
    ds.save_as(empty)                               # enforce 校验拒写空 UID，故不加
                                                    # （ds 带 preamble，file_meta 仍会写盘）

    rec = RA.survey_dicom(str(d))                   # 旧实现此处 ValueError
    base = _baseline_rec(tmp_path, d)
    _assert_rec_equal(rec, base)
    assert rec["n_slices_selected"] == 6
    assert rec["survey_skip_reasons"] == {}


# ------------------------------ 10) Implicit VR LE：8 字节元素头账路径（小端/隐式）
def _write_implicit_ct(path, z):
    plain = _write_ct(str(path) + ".plain.dcm", float(z))
    ds = pydicom.dcmread(plain)
    ds.file_meta.TransferSyntaxUID = pydicom.uid.ImplicitVRLittleEndian
    ds.save_as(str(path), enforce_file_format=True)
    os.remove(plain)
    return str(path)


def test_implicit_vr_little_endian_matches_baseline(tmp_path):
    d = tmp_path / "dcm"
    d.mkdir()
    for z in range(3):
        _write_ct(d / ("ct_%02d.dcm" % z), float(z))
    imp = _write_implicit_ct(d / "implicit.dcm", 3.0)

    with RA._DicomHeaderOnly():
        ds = pydicom.dcmread(imp)
    # implicit 属 plain 白名单（非压缩非 deflated）-> 8 字节元素头账定位像素族后
    # 注入空占位（行为同用例 3）；整读一致性由下方 rec 与基线逐键相等兜底。
    assert len(ds.PixelData) == 0
    assert ds.file_meta.TransferSyntaxUID.is_implicit_VR
    assert ds.file_meta.TransferSyntaxUID.is_little_endian

    rec = RA.survey_dicom(str(d))
    base = _baseline_rec(tmp_path, d)
    _assert_rec_equal(rec, base)
    assert rec["n_slices_selected"] == 4              # implicit 层被当有效层
    assert rec["survey_skip_reasons"] == {}