# -*- coding: utf-8 -*-
"""T2（A2-Q1）：选序列「重建适用性」准入（F1）+ 适用性断言（F2）锁定测试。

缺陷本体
--------
`read_ct_series` 的"取层数最多的一组"整条链上没有任何判据识别"被选中的序列
是否适合重建"：多帧动态序列、定位像、另一套层数更多的非重建序列，只要文件数
更多就会被选中，预检跟着 step1 一起选错而不报错。

每条用例对应任务书 T2 验收标准的一条：
  1) 层数更多的**非轴位**序列（IOP 矢状 [0,1,0, 0,0,-1]）不得胜出，进
     `rejected_series` 并带 reason；
  2) 层数更多的**非 CT 模态**组同理；
  3) IOP 缺失（老设备导出形态）准予入围，报告条目打 `iop_missing`；
  4) 组间层数比较用**去重后**层数（10 层含 5 个同 z 重复 vs 6 层无重复 -> 选后者，#77）；
  5) `ignored` 条目 schema 不变（`{"series","n","desc"}` 精确相等）；
  6) 全部组被准入判定拒绝 -> 仍 SystemExit(1)，文案补原因统计；
  7) 判定表 `ADMISSION_CHECKS` 是唯一判据来源（边界 0.9 放行 / 0.8999 拒绝）；
  8) `suitability_failures` 纯函数：PS=2.4mm 报失败、gap 上界 5.0 与**下界 0.01** 都报失败、
     演示几何 96×96/0.7/1.0 放行、区间端点闭合、矩阵/层数绝对门不存在（已否决的两条）；
  9) 停工门**不在** `survey_dicom` 内部（4×4 体模照常返回 rec，门在消费点）；
 10) run_all 主流程真实子进程：PS=2.4 的合成序列 exit 2 且文案含「重建适用性断言 FAIL」；
 11) server.py web 路径消费同一函数、落 `gate="重建适用性断言"` blocked 卡且挡在 step1 之前；
 12) 本机实有数据回归：`out/synthetic-ct`、`out/e2e-state-*/uploads/*` 逐个放行（目录不在则 skip）。
 13) R1 补测：IOP 含 NaN/±inf/非数值 ⇒ fail-closed 不准入（旧 `abs(n_z)<0.9` 对 NaN 恒 False
     的静默放行路径）、`rejected_series` 条目 `n` = 去重后层数、gap 下界反例。

测试不碰真实患者数据：DICOM 一律 tmp_path 现造。
"""
import glob
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(PIPELINE))
if PIPELINE not in sys.path:
    sys.path.insert(0, PIPELINE)

# run_all 模块级把 sys.stdout 换成 UTF-8 wrapper（run_all.py:73）；不立刻还原会让
# pytest 的 capture 临时文件在 wrapper 析构时关闭。处置沿用 tests/test_survey_series_select.py:31-37。
_ORIG_STDOUT = sys.stdout
import run_all as RA                       # noqa: E402
_RA_STDOUT = sys.stdout                    # 保留引用，防 wrapper 提前析构
sys.stdout = _ORIG_STDOUT

import airway_geom as AG                   # noqa: E402
from airway_geom import read_ct_series     # noqa: E402

RUN_ALL = os.path.join(PIPELINE, "run_all.py")
SERVER = os.path.join(PIPELINE, "server.py")

SERIES_AXIAL = "1.2.840.10008.5.1.4.1.1.2.1.2"    # 真轴位（要留下的那套）
SERIES_AXIAL2 = "1.2.840.10008.5.1.4.1.1.2.1.3"   # 另一套轴位（层数少，应被忽略）
SERIES_SAG = "1.2.840.10008.5.1.4.1.1.2.1.4"      # 矢状重建（层数多，不准入）
SERIES_MR = "1.2.840.10008.5.1.4.1.1.2.1.5"       # MR 序列（层数多，不准入）
SERIES_DUP = "1.2.840.10008.5.1.4.1.1.2.1.6"      # 同 z 重复层多的组
SERIES_BADIOP = "1.2.840.10008.5.1.4.1.1.2.1.7"   # IOP 含 NaN/inf 的损坏组
STUDY_UID = "1.2.840.10008.5.1.4.1.1.2.1.0"
ROWS = COLS = 4
IOP_AXIAL = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)        # 正轴位：n = row × col = (0,0,1)
IOP_SAGITTAL = (0.0, 1.0, 0.0, 0.0, 0.0, -1.0)    # 矢状：n_z = 0*0 - 1*0 = 0
DESC = "CT  1.0  H40s"


def _write_ct(path, z, series_uid=SERIES_AXIAL, modality="CT", iop=IOP_AXIAL,
              pixel_spacing=(0.7, 0.7), slice_thickness=1.0, desc=DESC):
    """写一张最小 CT 对象；iop=None -> 不写 ImageOrientationPatient（老设备形态）。"""
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
    ds.Modality = modality
    if desc is not None:
        ds.SeriesDescription = desc
    ds.Rows, ds.Columns = ROWS, COLS
    ds.PixelSpacing = [float(pixel_spacing[0]), float(pixel_spacing[1])]
    ds.SliceThickness = float(slice_thickness)
    ds.ImagePositionPatient = [0.0, 0.0, float(z)]
    if iop is not None:
        ds.ImageOrientationPatient = [float(x) for x in iop]
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated, ds.BitsStored, ds.HighBit = 16, 12, 11
    ds.PixelRepresentation = 0
    ds.RescaleSlope = 1
    ds.RescaleIntercept = -1024
    ds.PixelData = np.full((ROWS, COLS), 100, dtype=np.uint16).tobytes()
    ds.save_as(str(path), enforce_file_format=True)
    return str(path)


def _files(d):
    return sorted(glob.glob(os.path.join(str(d), "*.dcm")))

# ================================================== F1 准入：三类不合格序列
def test_sagittal_series_with_more_layers_loses(tmp_path, capsys):
    """验收①：矢状序列 12 层 > 轴位 6 层 —— 但矢状不准入，轴位胜出并如实披露。"""
    for z in range(12):
        _write_ct(tmp_path / ("SAG_%02d.dcm" % z), float(z),
                  series_uid=SERIES_SAG, iop=IOP_SAGITTAL)
    for z in range(6):
        _write_ct(tmp_path / ("AX_%02d.dcm" % z), float(z), series_uid=SERIES_AXIAL)

    slices, rep = read_ct_series(_files(tmp_path))

    assert {str(s.SeriesInstanceUID) for s in slices} == {SERIES_AXIAL}
    assert len(slices) == 6 and rep["n_valid"] == 6
    assert rep["series_uid"] == SERIES_AXIAL
    assert rep["ignored"] == []                       # 不准入的组不进 ignored
    assert len(rep["rejected_series"]) == 1
    rej = rep["rejected_series"][0]
    assert rej["series"] == SERIES_SAG and rej["n"] == 12 and rej["desc"] == DESC
    assert "非轴位" in rej["reason"] and "|n_z|" in rej["reason"]
    assert "准入拒绝 1 组（非轴位 1 组）" in capsys.readouterr().out


def test_non_ct_modality_with_more_layers_loses(tmp_path, capsys):
    """验收②：MR 序列 14 层 > CT 5 层 —— 模态门拦下，CT 胜出。"""
    for z in range(14):
        _write_ct(tmp_path / ("MR_%02d.dcm" % z), float(z),
                  series_uid=SERIES_MR, modality="MR", desc="t1_mprage")
    for z in range(5):
        _write_ct(tmp_path / ("CT_%02d.dcm" % z), float(z), series_uid=SERIES_AXIAL)

    slices, rep = read_ct_series(_files(tmp_path))

    assert {str(s.SeriesInstanceUID) for s in slices} == {SERIES_AXIAL}
    assert len(slices) == 5
    assert [r["series"] for r in rep["rejected_series"]] == [SERIES_MR]
    assert "非CT模态" in rep["rejected_series"][0]["reason"]
    assert "MR" in rep["rejected_series"][0]["reason"]
    assert "准入拒绝 1 组（非CT模态 1 组）" in capsys.readouterr().out


def test_missing_iop_is_admitted_and_disclosed(tmp_path, capsys):
    """验收③：IOP 缺失（老设备导出）准予入围，报告条目打 iop_missing=true。"""
    for z in range(8):
        _write_ct(tmp_path / ("%04d.dcm" % z), float(z), iop=None)

    slices, rep = read_ct_series(_files(tmp_path))

    assert len(slices) == 8
    assert rep["rejected_series"] == []
    assert rep["admitted_series"] == [
        {"series": SERIES_AXIAL, "n": 8, "desc": DESC, "iop_missing": True}]
    out = capsys.readouterr().out
    assert "iop_missing" in out                       # 披露，不是静默放行


def test_group_count_uses_deduped_layers(tmp_path):
    """验收④（#77）：A 组 10 层含 5 个同 z 重复（去重后 5）vs B 组 6 层 -> 选 B。"""
    for i, z in enumerate([0.0, 0.0, 1.0, 1.0, 2.0, 2.0, 3.0, 3.0, 4.0, 4.0]):
        _write_ct(tmp_path / ("DUP_%02d.dcm" % i), z, series_uid=SERIES_DUP)
    for z in range(6):
        _write_ct(tmp_path / ("B_%02d.dcm" % z), float(z), series_uid=SERIES_AXIAL)

    slices, rep = read_ct_series(_files(tmp_path))

    assert rep["series_uid"] == SERIES_AXIAL          # 6（去重后）> 5，不是 10 > 6
    assert len(slices) == 6
    assert rep["ignored"] == [{"series": SERIES_DUP, "n": 5, "desc": DESC}]
    assert rep["dedup"] == 0                          # 计数只算被选中组自己的重复层


def test_ignored_and_rejected_entry_schemas(tmp_path):
    """验收⑤：ignored 条目仍是 {"series","n","desc"}（一字节不变）；rejected 多 reason。"""
    for z in range(8):
        _write_ct(tmp_path / ("A_%02d.dcm" % z), float(z), series_uid=SERIES_AXIAL)
    for z in range(4):
        _write_ct(tmp_path / ("B_%02d.dcm" % z), float(z),
                  series_uid=SERIES_AXIAL2, desc="Sinus  0.75  H40s")
    for z in range(3):
        _write_ct(tmp_path / ("S_%02d.dcm" % z), float(z),
                  series_uid=SERIES_SAG, iop=IOP_SAGITTAL)
    for z in range(2):
        _write_ct(tmp_path / ("M_%02d.dcm" % z), float(z),
                  series_uid=SERIES_MR, modality="MR")

    _slices, rep = read_ct_series(_files(tmp_path))

    assert rep["ignored"] == [
        {"series": SERIES_AXIAL2, "n": 4, "desc": "Sinus  0.75  H40s"}]
    assert set(rep["ignored"][0]) == {"series", "n", "desc"}
    assert {r["series"] for r in rep["rejected_series"]} == {SERIES_SAG, SERIES_MR}
    assert len(rep["rejected_series"]) == 2           # 顺序随文件名分组序，不钉
    for r in rep["rejected_series"]:
        assert set(r) == {"series", "n", "desc", "reason"}


def test_all_groups_rejected_exits_with_reason_stats(tmp_path, capsys):
    """验收⑥：全部组不准入 -> 仍 SystemExit(1)，文案补原因统计（不静默）。"""
    for z in range(4):
        _write_ct(tmp_path / ("S1_%02d.dcm" % z), float(z),
                  series_uid=SERIES_SAG, iop=IOP_SAGITTAL)
    for z in range(3):
        _write_ct(tmp_path / ("S2_%02d.dcm" % z), float(z),
                  series_uid=SERIES_AXIAL2, iop=(1.0, 0.0, 0.0, 0.0, 0.0, -1.0))

    with pytest.raises(SystemExit) as ei:
        read_ct_series(_files(tmp_path))
    assert ei.value.code == 1
    out = capsys.readouterr().out
    assert "未找到有效 CT 轴位序列" in out
    assert "其中 2 组因非轴位被拒" in out


# ================================================== 判定表（数据驱动，非流程硬编码）
def test_admission_table_is_the_single_source_of_truth():
    """判定表就是判据来源：新增同类约束只加表项，不改 read_ct_series 流程。"""
    assert [label for label, _fn in AG.ADMISSION_CHECKS] == [
        "非CT模态", "IOP不可解析", "非轴位"]
    assert AG.MODALITY_FOR_REBUILD == "CT"
    assert AG.AXIAL_NZ_MIN == 0.9


def test_admission_boundary_and_orientation_math():
    """|n_z| 边界：0.9 放行、0.8999 拒绝；矢状/冠状都拒绝；缺 IOP 放行、缺 Modality 拒。"""
    from types import SimpleNamespace
    ok = SimpleNamespace(Modality="CT",
                         ImageOrientationPatient=[0.9, 0.0, 0.4358898943540674, 0.0, 1.0, 0.0])
    bad = SimpleNamespace(Modality="CT",
                          ImageOrientationPatient=[0.8999, 0.0, 0.43, 0.0, 1.0, 0.0])
    assert AG.admission_rejection(ok) == (None, None)
    why, kind = AG.admission_rejection(bad)
    assert kind == "非轴位" and "|n_z|" in why
    for iop in (IOP_SAGITTAL, (1.0, 0.0, 0.0, 0.0, 0.0, -1.0)):      # 矢状 / 冠状
        assert AG.admission_rejection(
            SimpleNamespace(Modality="CT", ImageOrientationPatient=list(iop)))[1] == "非轴位"
    assert AG.admission_rejection(SimpleNamespace(Modality="CT")) == (None, None)
    assert AG.admission_rejection(SimpleNamespace())[1] == "非CT模态"


def test_modality_check_is_case_insensitive():
    from types import SimpleNamespace
    assert AG.admission_rejection(
        SimpleNamespace(Modality="ct", ImageOrientationPatient=list(IOP_AXIAL))) == (None, None)


def test_iop_unparseable_is_rejected_fail_closed():
    """R1②：IOP 六分量非全有限（NaN/±inf/非数值）⇒ 不准入（fail-closed），不是静默放行。

    旧实现 `abs(n_z) < 0.9` 对 NaN 恒 False ⇒ 损坏 IOP 的组会被**静默准入**且
    `iop_missing=False`（无任何披露）——本用例钉死那条 fail-open 路径。"""
    from types import SimpleNamespace
    for bad in ([1.0, 0.0, 0.0, 0.0, float("nan"), 0.0],
                [1.0, 0.0, 0.0, 0.0, float("inf"), 0.0],
                [1.0, 0.0, 0.0, 0.0, float("-inf"), 0.0],
                [1.0, 0.0, 0.0, 0.0, "abc", 0.0]):
        why, kind = AG.admission_rejection(
            SimpleNamespace(Modality="CT", ImageOrientationPatient=bad))
        assert kind == "IOP不可解析", (bad, why, kind)
        assert "不可解析" in why
    # 缺失仍是"披露放行"（老设备形态），不是拒绝；分量不足 6 个同按缺失处理
    assert AG.admission_rejection(SimpleNamespace(Modality="CT")) == (None, None)
    assert AG._iop_values(SimpleNamespace(ImageOrientationPatient=[1.0, 0.0, 0.0]))[0] == "missing"
    assert AG._iop_values(SimpleNamespace(ImageOrientationPatient=list(IOP_AXIAL)))[0] == "ok"


def test_nan_iop_series_with_more_layers_is_rejected(tmp_path, capsys):
    """R1②：IOP 含 NaN 的 14 层组不得靠层数胜出；进 rejected_series 且 reason 含「不可解析」。"""
    iop_nan = (1.0, 0.0, 0.0, 0.0, float("nan"), 0.0)
    for z in range(14):
        _write_ct(tmp_path / ("BAD_%02d.dcm" % z), float(z),
                  series_uid=SERIES_BADIOP, iop=iop_nan)
    for z in range(6):
        _write_ct(tmp_path / ("GOOD_%02d.dcm" % z), float(z), series_uid=SERIES_AXIAL)

    slices, rep = read_ct_series(_files(tmp_path))

    assert {str(s.SeriesInstanceUID) for s in slices} == {SERIES_AXIAL}
    assert len(slices) == 6
    rej = [r for r in rep["rejected_series"] if r["series"] == SERIES_BADIOP]
    assert len(rej) == 1 and rej[0]["n"] == 14
    assert "不可解析" in rej[0]["reason"]
    # 也不得出现在 admitted_series（否则等于带着 iop_missing=False 被静默放行）
    assert all(a["series"] != SERIES_BADIOP for a in rep["admitted_series"])
    assert "IOP不可解析 1 组" in capsys.readouterr().out


def test_rejected_entry_n_uses_deduped_layers(tmp_path):
    """rejected 条目的 `n` 与 ignored 同口径 = 组内同 z **去重后**层数（6 文件 → 3）。"""
    for i, z in enumerate([0.0, 0.0, 1.0, 1.0, 2.0, 2.0]):
        _write_ct(tmp_path / ("SEG_%02d.dcm" % i), z,
                  series_uid=SERIES_SAG, iop=IOP_SAGITTAL)
    for z in range(4):
        _write_ct(tmp_path / ("AX_%02d.dcm" % z), float(z), series_uid=SERIES_AXIAL)

    slices, rep = read_ct_series(_files(tmp_path))

    assert len(slices) == 4
    rej = rep["rejected_series"][0]
    assert rej["series"] == SERIES_SAG and rej["n"] == 3
    assert "非轴位" in rej["reason"]


# ================================================== F2 适用性断言（纯函数）
def _rec(ps=(0.7, 0.7), gap=1.0, **kw):
    r = {"pixel_spacing": list(ps), "slice_gap_measured": gap}
    r.update(kw)
    return r


def test_suitability_flags_out_of_range_pixel_spacing():
    """验收⑥a：面内间距 2.4mm 必须报失败，且文案是人话（含数值与区间）。"""
    fails = RA.suitability_failures(_rec(ps=(2.4, 2.4)))
    assert len(fails) == 2
    assert all("超出 CT 合理范围" in f and "被选中的序列可能不是诊断轴位 CT" in f
               for f in fails)
    assert "面内像素间距 2.40mm" in fails[0]
    assert "[0.05, 1.50]mm" in fails[0]


def test_suitability_flags_slice_gap():
    fails = RA.suitability_failures(_rec(gap=5.0))
    assert len(fails) == 1 and "实测层间距 5.000mm" in fails[0]
    assert "[0.05, 3.00]mm" in fails[0]


def test_suitability_flags_slice_gap_below_lower_bound():
    """R1：下界也要有反例（上轮只钉了上界 5.0mm）。0.01mm 低于 [0.05, 3.00] 下界。"""
    fails = RA.suitability_failures(_rec(gap=0.01))
    assert len(fails) == 1
    assert "实测层间距 0.010mm" in fails[0]
    assert "[0.05, 3.00]mm" in fails[0]


def test_suitability_accepts_demo_geometry_and_closed_bounds():
    """验收⑥b：演示几何 0.7/1.0 放行；区间端点闭合（不该拦掉贴边值）。"""
    assert RA.suitability_failures(_rec()) == []
    assert RA.suitability_failures(_rec(ps=(0.05, 1.5), gap=3.0)) == []
    assert RA.suitability_failures(_rec(ps=(1.5, 0.05), gap=0.05)) == []


def test_suitability_has_no_matrix_or_layer_count_gate():
    """被否的两条绝对门不得偷偷回来：4×4 / 19 层照样放行（只看物理尺度）。"""
    rec = _rec(rows=4, columns=4, n_slices_selected=19)
    assert RA.suitability_failures(rec) == []


def test_suitability_fails_closed_on_missing_fields():
    """缺字段必须报失败，不能 fail-open。"""
    assert RA.suitability_failures({}) != []
    assert RA.suitability_failures({"pixel_spacing": [0.7], "slice_gap_measured": None}) != []


# ================================================== 消费点 1：survey_dicom 不 die，门在主流程
def test_survey_dicom_does_not_die_on_4x4_bad_spacing(tmp_path):
    """门必须在消费点。理由三条（**不是**"放进 survey 会打坏锁定测试"——锁定 fixture
    的 0.7/1.0 本来就在门区间内，台账「被否方案③」已按此更正）：
    ① 规格「被否方案」明确否掉 survey 内 die，门放消费点是规格决定；
    ② survey_dicom 是 run_all/server 共用的测量原语，其 SystemExit 在 web 侧会落进
       通用「DICOM 头普查（层序结构断言）」卡（server.py:2150-2152 → :2157-2163），
       丢掉「重建适用性」专有话术；③ S1 要求 die 位于维度动态断言之后、带 exit 2。"""
    for z in range(10):
        _write_ct(tmp_path / ("%04d.dcm" % z), float(z), pixel_spacing=(2.4, 2.4))
    rec = RA.survey_dicom(str(tmp_path))              # 不抛 SystemExit
    assert (rec["rows"], rec["columns"]) == (ROWS, COLS)
    assert rec["pixel_spacing"] == [2.4, 2.4]
    assert RA.suitability_failures(rec) != []         # 但适用性门看得见


def _child_env_utf8():
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def test_run_all_main_dies_with_suitability_gate(tmp_path):
    """验收⑥a 主流程：PS=2.4 的序列让 run_all S1 直接 die(2)，文案含固定话术。"""
    d = tmp_path / "dicom"
    d.mkdir()
    for z in range(10):
        _write_ct(d / ("%04d.dcm" % z), float(z), pixel_spacing=(2.4, 2.4))
    out_root = tmp_path / "out"
    r = subprocess.run([sys.executable, RUN_ALL, "--dicom-dir", str(d),
                        "--out-root", str(out_root), "--solve", "skip"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=_child_env_utf8(), timeout=600)
    txt = r.stdout or ""
    assert r.returncode == 2, (txt + (r.stderr or ""))[-2000:]
    assert "重建适用性断言 FAIL：" in txt
    assert "面内像素间距 2.40mm" in txt
    assert "几何不可重建，停工上报" in txt


# ================================================== 消费点 2：server web 路径
def test_server_web_path_uses_same_suitability_function():
    """web 路径消费**同一个**纯函数，落 blocked 卡，且挡在 step1 之前。"""
    assert RA.suitability_failures.__module__ == "run_all"
    with open(SERVER, encoding="utf-8") as f:
        src = f.read()
    assert "RA.suitability_failures(survey)" in src
    assert 'gate="重建适用性断言"' in src
    assert "gate_failures=list(suit_fails)" in src
    assert "exit_code=2" in src
    i_gate = src.index("RA.suitability_failures(survey)")
    i_step1 = src.index("cmd1 = [sys.executable, STEP1")
    assert i_gate < i_step1, "适用性门必须挡在 step1 之前"
    # survey 键白名单不动（server.py:2144-2149 口径）
    assert '"z_distinct_count", "z_duplicate_count"' in src


def test_server_gate_web_path_blocks_with_card(tmp_path):
    """web 上传路径**真跑一遍**（不是源码 grep）：PS=2.4 的序列落 ⛔ blocked 卡，
    且 `survey` 键白名单（server.py:2144-2149，12 个键）一字未增、step1 未被启动。"""
    pytest.importorskip("flask")
    import server as S

    d = tmp_path / "dicom"
    d.mkdir()
    for z in range(10):
        _write_ct(d / ("%04d.dcm" % z), float(z), pixel_spacing=(2.4, 2.4))
    cfg = S.ServerConfig(mode="m1-local", state_dir=str(tmp_path / "state"))
    app = S.build_app(cfg)
    with app.app_context():
        resp = S._register_case(cfg, str(d), "pB", "v1", "t2 probe", "upload", "t2-probe")

    body = resp.get_json()
    assert resp.status_code == 200
    assert body["status"] == "blocked"
    assert body["gate"] == "重建适用性断言"
    assert "重建适用性断言" in body["message"]
    assert any("面内像素间距 2.40mm" in f for f in body["gate_failures"])

    rec = S.load_registry(cfg)["t2-probe"]
    assert rec["status"] == "blocked"
    assert rec["gate"] == "重建适用性断言"
    assert rec["exit_code"] == 2
    assert sorted(rec["survey"]) == sorted([
        "file_count", "rows", "columns", "pixel_spacing", "slice_gap_measured",
        "z_monotonic_increasing", "filename_order_matches_physical",
        "z_structurally_ok", "z_distinct_count", "z_duplicate_count",
        "z_distinct_gap_median", "z_missing_ipp"])
    # 门挡在 step1 之前：没有 preview 目录（step1 只在门之后启动）
    assert not os.path.isdir(str(tmp_path / "state" / "cases" / "t2-probe" / "preview"))


# ================================================== 本机实有数据回归
DEMO_SYNTHETIC = os.path.join(REPO, "out", "synthetic-ct")
UPLOAD_DIRS = sorted(glob.glob(os.path.join(REPO, "out", "e2e-state-*", "uploads", "*")))


@pytest.mark.skipif(not os.path.isdir(DEMO_SYNTHETIC), reason="演示数据 out/synthetic-ct 不在")
def test_demo_synthetic_dir_passes_suitability_gate():
    """验收⑥b 实测：96×96 / PS 0.7 / ST 1.0 的合成演示数据不被新门拦。"""
    rec = RA.survey_dicom(DEMO_SYNTHETIC)
    assert (rec["rows"], rec["columns"]) == (96, 96)
    assert rec["pixel_spacing"] == [0.7, 0.7]
    assert rec["slice_gap_measured"] == pytest.approx(1.0, abs=1e-6)
    assert RA.suitability_failures(rec) == []


@pytest.mark.skipif(not UPLOAD_DIRS, reason="out/e2e-state-*/uploads/* 不在")
@pytest.mark.parametrize("dicom_dir", UPLOAD_DIRS, ids=[os.path.basename(d) for d in UPLOAD_DIRS])
def test_local_upload_dirs_pass_suitability_gate(dicom_dir):
    """本机 e2e 上传目录逐个实测放行（门本身有上面 6 条反例，不是恒真断言）。"""
    rec = RA.survey_dicom(dicom_dir)
    assert RA.suitability_failures(rec) == []
