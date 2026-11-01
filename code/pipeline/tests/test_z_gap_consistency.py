# -*- coding: utf-8 -*-
"""T2（#76）逐层间隙一致性门 —— 指挥官亲笔锁定测试，编码手禁止修改。

缺陷本体
--------
step1_airway_segment.py:89 的 dz 只取**最底两层**的 IPP z 差；而重建与体积换算
全程用这一个标量（vox_vol=ps0*ps1*dz :95、marching_cubes spacing :419）。
一旦层链里有一处间隙异常（首层间隙翻倍 = 导出时漏了一层，或中间被跳一层），
dz 就成了错值：指挥官实测 0.13 cm³ → 0.26 cm³ 恰好 2.0 倍，且预检
`z_structurally_ok=True` 一路放行、step1 exit 0（§23-3）。

门设计（阈值来源：§23-6 真数据实测）
------------------------------------
- 16 个真实目录、去重后间隙链的**最大相对偏差 = 2.033e-04（0.02%）**，
  最大绝对偏差 = 1.2e-04 mm；任何 ≥0.5% 的门限下"会被新判停的目录数 = 0/16"。
- 16 个真实目录里 dz_now（最底两层）与 dz_new（中位间隙）**逐目录相等**
  （最大相对差 3.248e-13，属浮点末位）⇒ 统一口径不挪动任何已交付病例的数字。
- 因此门限取 `tol_mm = max(Z_GAP_REL_TOL * gap_median, Z_GAP_ABS_FLOOR_MM)`，
  Z_GAP_REL_TOL=0.01、Z_GAP_ABS_FLOOR_MM=0.005：对真实数据留 ~49× 余量，
  对"少一层"这类 100% 偏差零漏。绝对下限只在极薄层（med<0.5mm）时兜浮点噪声。

反例（本文件必须拦住的东西，L14）
--------------------------------
正例来自实跑：首层间隙翻倍（§23-3 probe8 A/C 臂）、中间被跳一层（§23-3 probe14 E 臂，
(nz-1)*dz=18.0mm vs CSV 跨距 19.0mm）。阴性对照：均匀层链 + 0.02% 量级的真实抖动。

只用 tmp_path 现造体模，不碰真实患者数据。
"""
import os
import re
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.dirname(HERE)
if PIPELINE not in sys.path:
    sys.path.insert(0, PIPELINE)

# run_all 模块级把 sys.stdout 换成 UTF-8 wrapper（run_all.py:73）；不立刻还原会让
# pytest 的 capture 临时文件在 wrapper 析构时关闭。处置沿用 tests/test_survey_series_select.py:31-37。
_ORIG_STDOUT = sys.stdout
import run_all as RA                       # noqa: E402
_RA_STDOUT = sys.stdout                    # 保留引用，防 wrapper 提前析构
sys.stdout = _ORIG_STDOUT

import airway_geom as AG                   # noqa: E402

STEP1 = os.path.join(PIPELINE, "step1_airway_segment.py")
SERIES_AXIAL = "1.2.840.10008.5.1.4.1.1.2.1.2"
STUDY_UID = "1.2.840.10008.5.1.4.1.1.2.1.0"
ROWS = COLS = 8
PS = 0.75                                  # mm，面内
STEP_MM = 0.5                              # 体模的健康层间距

STOP_WORDS = ("层间距不一致", "停工上报")


def _child_env_utf8():
    import copy
    env = copy.deepcopy(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _metrics_json(out_dir):
    """step1 的 metrics 文件名随 --case-prefix 变（step1_airway_segment.py:65-70），
    按前缀无关的方式取回，顺带断言它确实产出了数值。"""
    import glob as _glob
    import json as _json
    hits = _glob.glob(os.path.join(str(out_dir), "metrics*_v2.json"))
    assert len(hits) == 1, "metrics 文件数=%d %s" % (len(hits), hits)
    return _json.loads(open(hits[0], encoding="utf-8").read())


def _write_ct(path, z):
    """8x8 体模：外圈 400HU 头组织包一个半径 2 的空气柱（-1000HU）。
    与指挥官实测 probe8/probe14 同款，step1 可正常跑完（exit 0）。"""
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
    ds.SeriesInstanceUID = SERIES_AXIAL
    ds.Modality = "CT"
    ds.Rows, ds.Columns = ROWS, COLS
    ds.PixelSpacing = [PS, PS]
    ds.SliceThickness = STEP_MM
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated, ds.BitsStored, ds.HighBit = 16, 12, 11
    ds.PixelRepresentation = 0
    ds.RescaleSlope = 1
    ds.RescaleIntercept = -1024
    ds.ImagePositionPatient = [0.0, 0.0, float(z)]
    yy, xx = np.mgrid[0:ROWS, 0:COLS]
    air = ((yy - 3.5) ** 2 + (xx - 3.5) ** 2) <= 4
    ds.PixelData = np.where(air, 24, 1424).astype(np.uint16).tobytes()
    ds.save_as(str(path), enforce_file_format=True)


def _make_stack(d, zs):
    os.makedirs(str(d), exist_ok=True)
    for i, z in enumerate(zs):
        _write_ct(os.path.join(str(d), "%06d.dcm" % i), float(z))
    return str(d)


def _zs_uniform(n=20, dz=STEP_MM):
    return [round(i * dz, 6) for i in range(n)]


def _zs_doubled_first(n=20, dz=STEP_MM):
    """首层间隙翻倍（漏一层的实测形态），其余均匀。"""
    return [0.0, dz * 2.0] + [round(dz * 2.0 + dz * i, 6) for i in range(1, n - 1)]


def _zs_mid_hole(n=20, dz=STEP_MM, at=9):
    """中间少一层：第 at 对间隙变成 2*dz，其余均匀。"""
    zs, z = [], 0.0
    for i in range(n):
        zs.append(round(z, 6))
        z += dz * (2.0 if i == at else 1.0)
    return zs


def _zs_sub_tol(n=20):
    """首间隙 0.504、其余 0.5：相对偏差 0.8% < 1% 门限 ⇒ 门放行，
    但 dz_now(0.504) != dz_new(0.5)：专测 step1 的 dz 是否已换成中位口径。"""
    return [0.0] + [round(0.504 + STEP_MM * i, 6) for i in range(n - 1)]


# ---------------------------------------------------------------- 门限常量（规格钉死）
def test_gate_constants_match_measured_basis():
    """门限是 §23-6 真数据实测推出来的，钉死值：改数必须回规格走 SPEC GAP。"""
    assert AG.Z_GAP_REL_TOL == 0.01
    assert AG.Z_GAP_ABS_FLOOR_MM == 0.005


# ---------------------------------------------------------------- z_gap_report 本体
def test_gap_report_accepts_uniform_stack():
    """阴性对照：均匀层链必须放行（门不得把合格数据判停——#76 的原罪就是假拒绝）。"""
    rep = AG.z_gap_report(_zs_uniform())
    assert rep["uniform"] is True
    assert rep["bad_pairs"] == []
    assert abs(rep["gap_median"] - STEP_MM) < 1e-9
    assert rep["max_abs_dev_mm"] <= rep["tol_mm"]
    assert rep["n_gaps"] == 19


def test_gap_report_accepts_real_export_jitter_magnitude():
    """真实导出的浮点抖动量级（实测最大相对偏差 2.033e-04）必须放行。"""
    zs, acc = [0.0], 0.0
    for i in range(200):
        acc += STEP_MM + (2.033e-04 * STEP_MM if i % 2 else 0.0)
        zs.append(round(acc, 6))
    rep = AG.z_gap_report(zs)
    assert rep["uniform"] is True, rep
    assert rep["max_rel_dev"] < AG.Z_GAP_REL_TOL


def test_gap_report_flags_doubled_first_gap():
    """§23-3 正例一：首层间隙翻倍 → 不放行，异常对索引必须指出是第 0 对。"""
    rep = AG.z_gap_report(_zs_doubled_first())
    assert rep["uniform"] is False
    assert 0 in rep["bad_pairs"]
    assert abs(rep["gap_median"] - STEP_MM) < 1e-9
    assert rep["max_rel_dev"] > 0.9


def test_gap_report_flags_mid_stack_hole():
    """§23-3 正例二：中间被跳一层（probe14 E 臂）→ 不放行，且索引就是被跳的那一对。"""
    rep = AG.z_gap_report(_zs_mid_hole(at=9))
    assert rep["uniform"] is False
    assert 9 in rep["bad_pairs"]
    assert rep["max_abs_dev_mm"] > 0.4


def test_gap_report_rejects_short_input():
    """不足两个 z 无法构成间隙：必须显式抛 ValueError，不得静默给 uniform=True。"""
    with pytest.raises(ValueError):
        AG.z_gap_report([0.0])
    with pytest.raises(ValueError):
        AG.z_gap_report([])


def test_gap_report_median_is_upper_median_abs():
    """中位口径必须与 run_all.py:394 现有口径一致（升序后的上中位、取绝对值），
    否则预检与重建各拿一个 dz，#76 只是换了个地方。"""
    rep = AG.z_gap_report([3.0, 2.0, 0.0, 1.0])   # 乱序输入也不得影响结果口径
    assert rep["gap_median"] == 1.0
    rep2 = AG.z_gap_report([0.0, 1.0, 2.0, 3.0])
    assert rep2["gap_median"] == rep["gap_median"]


# ---------------------------------------------------------------- 预检停工（survey_dicom）
def test_survey_stops_work_on_doubled_first_gap(tmp_path, capsys):
    """预检必须拦住首层间隙翻倍：die(2) + 措辞含"层间距不一致"与"停工上报"。
    修前这条路是 z_structurally_ok=True 一路放行（§23-3 实测 exit 0）。
    断言形态沿用本仓既有约定（tests/test_survey_series_select.py:131-137）：
    `run_all.py#die` 是 log(msg) + sys.exit(code)，消息只进 stdout 不进异常对象
    （指挥官实测 `str(SystemExit(2))` = '2'，2026-11-01 11:26:42.025436900），
    所以话术一律从 capsys 取，异常对象只核 code。"""
    d = _make_stack(tmp_path / "doubled", _zs_doubled_first())
    with pytest.raises(SystemExit) as ei:
        RA.survey_dicom(d)
    assert ei.value.code == 2
    out = capsys.readouterr().out
    for w in STOP_WORDS:
        assert w in out, out[-1500:]
    assert "AttributeError" not in out, out[-1500:]


def test_survey_stops_work_on_mid_stack_hole(tmp_path, capsys):
    """中间跳层同样停工：这类数据 (nz-1)*dz 与真实 z 跨距不符（实测差 1.0mm）。"""
    d = _make_stack(tmp_path / "hole", _zs_mid_hole(at=9))
    with pytest.raises(SystemExit) as ei:
        RA.survey_dicom(d)
    assert ei.value.code == 2
    out = capsys.readouterr().out
    for w in STOP_WORDS:
        assert w in out, out[-1500:]


def test_survey_records_gap_magnitudes_when_passing(tmp_path):
    """放行时也必须把偏差量级落进 manifest：无量化字段 = 门不可审计、不可回溯。
    不得新增"构造性恒真的布尔门"（§21-5 教训），所以断言的是数值键。"""
    d = _make_stack(tmp_path / "ok", _zs_uniform())
    rec = RA.survey_dicom(d)
    for k in ("z_gap_max_abs_dev_mm", "z_gap_max_rel_dev", "z_gap_tol_mm", "z_gap_bad_pairs"):
        assert k in rec, "缺键 %s；已有键=%s" % (k, sorted(rec))
    assert rec["z_gap_bad_pairs"] == []
    assert rec["z_gap_max_abs_dev_mm"] <= rec["z_gap_tol_mm"]
    # 预检回报的层间距必须与门用的中位口径同一个数（单一来源）
    assert abs(rec["slice_gap_measured"] - STEP_MM) < 1e-9


# ---------------------------------------------------------------- step1 执行者侧
def test_step1_standalone_stops_on_non_uniform_gap(tmp_path):
    """step1 可被单独调用（用户上传/手工重跑）：它自己不经过预检，必须自带同一道门。
    否则"预检停工、step1 照跑"分叉，患者数值仍是错的。"""
    d = _make_stack(tmp_path / "bad", _zs_doubled_first())
    out = tmp_path / "out"
    r = subprocess.run([sys.executable, STEP1, "--dicom-dir", d, "--out-dir", str(out),
                        "--case-prefix", "pT"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=_child_env_utf8(), timeout=1800)
    assert r.returncode == 2, "rc=%s\nstdout=%s\nstderr=%s" % (
        r.returncode, (r.stdout or "")[-1500:], (r.stderr or "")[-1500:])
    blob = (r.stdout or "") + (r.stderr or "")
    for w in STOP_WORDS:
        assert w in blob, blob[-1500:]
    # 停工 = 不得留下患者数值产物（半套结果比不产出更危险）
    produced = [f for f in os.listdir(str(out)) if f.startswith("metrics")] if out.exists() else []
    assert produced == [], produced


def test_step1_control_uniform_runs_clean(tmp_path):
    """阴性对照：均匀体模必须跑通（门不得假拒绝），且层厚报 0.5mm。"""
    d = _make_stack(tmp_path / "ok", _zs_uniform())
    out = tmp_path / "out"
    r = subprocess.run([sys.executable, STEP1, "--dicom-dir", d, "--out-dir", str(out),
                        "--case-prefix", "pT"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=_child_env_utf8(), timeout=1800)
    assert r.returncode == 0, (r.stdout or "")[-1500:] + (r.stderr or "")[-1500:]
    assert "层厚 0.5mm" in (r.stdout or ""), (r.stdout or "")[-1500:]
    metrics = _metrics_json(out)
    assert float(metrics["airway_volume_cm3"]) > 0.0


def test_step1_dz_is_median_not_first_pair(tmp_path):
    """核心口径统一：首间隙 0.504（偏差 0.8%，门内放行）、其余 0.5。
    修前 step1:89 取最底两层 → 层厚 0.504mm（体积随之偏 0.8%）；
    修后必须报中位 0.5mm，与预检 slice_gap_measured 同一个数。"""
    d = _make_stack(tmp_path / "sub", _zs_sub_tol())
    out = tmp_path / "out"
    r = subprocess.run([sys.executable, STEP1, "--dicom-dir", d, "--out-dir", str(out),
                        "--case-prefix", "pT"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=_child_env_utf8(), timeout=1800)
    assert r.returncode == 0, (r.stdout or "")[-1500:] + (r.stderr or "")[-1500:]
    so = r.stdout or ""
    assert "层厚 0.5mm" in so, so[-1500:]
    assert "层厚 0.504mm" not in so, so[-1500:]
    m = re.search(r"层厚\s*([0-9.]+)mm", so)
    assert m and abs(float(m.group(1)) - STEP_MM) < 1e-9, so[-1500:]
    # 门在这一例必须保持沉默（0.8% < 1%），否则本例变成停工
    assert "层间距不一致" not in so, so[-1500:]
    metrics = _metrics_json(out)
    assert float(metrics["airway_volume_cm3"]) > 0.0
