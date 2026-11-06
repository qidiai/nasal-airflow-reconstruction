# -*- coding: utf-8 -*-
"""T6：硬编码几何锚定批修（B1 step4 spacing / B8 step5 CENTER）防回归。

钉住的契约：
  F1/B1：step4 的 spacing 必须来自本例 DICOM 头（PixelSpacing + 实测层间距 dz），
         不得残留写死体素常量；头不可读/缺字段 fail-closed；输入 mask 必须有
         「已归一化到头读 spacing」的显式断言（次选方案）；合成例 STL 尺寸随头变化。
  F2/B8：step5 的 v1 种子 CENTER 必须显式标注「仅参考数据集有效」，非参考病例
         必须有 QC/日志的显式降级（不留静默错位路径）——次选方案。

测试策略：step4/step5 都是模块级有重副作用的脚本，不能 import。故：
  - 用 ast 从 step4 源码提取三个纯函数（read_case_spacing / assert_mask_normalized /
    export_mask），在隔离命名空间注入依赖后**真跑**（真实 marching_cubes + 真实 STL
    落盘），与仓内 test_step1_dicom_series.py 的源码断言同风格；
  - 用 AST 断言接线（防「测的是孤儿函数」）：step4 模块级确实调用头读函数、
    marching_cubes 确实收到 spacing=spacing；
  - step5 侧用源码断言（本机无患者A 真数据/VTU/工作区，无法真跑全流程）。
"""
import ast
import glob
import os
import sys

import numpy as np
import pytest
import trimesh
import trimesh.smoothing
from scipy import ndimage
from skimage.measure import marching_cubes

HERE = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.dirname(HERE)
if PIPELINE not in sys.path:
    sys.path.insert(0, PIPELINE)

STEP4 = os.path.join(PIPELINE, "step4_export_implant.py")
STEP5 = os.path.join(PIPELINE, "step5_export_viewer_data.py")

_STEP4_FNS = {"read_case_spacing", "assert_mask_normalized", "export_mask"}


# ---------------------------------------------------------------- 工具
def _s4():
    with open(STEP4, encoding="utf-8") as f:
        return f.read()


def _s5():
    with open(STEP5, encoding="utf-8") as f:
        return f.read()


def _tree(src):
    return ast.parse(src, filename=STEP4)


def _step4_ns():
    """从 step4 真实源码提取三个纯函数，注入依赖后返回可执行名字表。

    不 import step4（模块级会 np.load/全流程导出 STL），但执行的是**生产源码里
    的函数对象本身**，不是复刻实现；接线另由 AST 断言钉住（见下）。
    """
    tree = _tree(_s4())
    fns = [n for n in tree.body
           if isinstance(n, ast.FunctionDef) and n.name in _STEP4_FNS]
    assert {f.name for f in fns} == _STEP4_FNS, \
        "step4 缺少 T6 纯函数：%r" % (_STEP4_FNS - {f.name for f in fns})
    mod = ast.Module(body=fns, type_ignores=[])
    ast.fix_missing_locations(mod)
    ns = {"os": os, "np": np, "glob": glob, "ndimage": ndimage,
          "marching_cubes": marching_cubes, "trimesh": trimesh}
    exec(compile(mod, STEP4, "exec"), ns)
    return ns


def _write_ct(path, z, ps=(0.7, 0.7), dz=1.0, rows=24, cols=24,
              with_ps=True, with_ipp=True):
    """写一张最小 CT 轴位切片（几何字段齐备；面内尺寸可配）。"""
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, CTImageStorage, generate_uid

    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = CTImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = CTImageStorage
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.Modality = "CT"
    ds.Rows, ds.Columns = int(rows), int(cols)
    if with_ps:
        ds.PixelSpacing = [float(ps[0]), float(ps[1])]
    ds.SliceThickness = float(dz)
    if with_ipp:
        ds.ImagePositionPatient = [0.0, 0.0, float(z)]
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated, ds.BitsStored, ds.HighBit = 16, 12, 11
    ds.PixelRepresentation = 0
    ds.RescaleSlope = 1
    ds.RescaleIntercept = -1024
    ds.PixelData = np.full((int(rows), int(cols)), 100, dtype=np.uint16).tobytes()
    ds.save_as(str(path), enforce_file_format=True)
    return str(path)


def _write_series(d, ps=(0.7, 0.7), dz=1.0, n=3, rows=24,
                  with_ps=True, with_ipp=True):
    os.makedirs(str(d), exist_ok=True)
    for k in range(n):
        _write_ct(os.path.join(str(d), "IMG_%04d.dcm" % k), k * dz,
                  ps=ps, dz=dz, rows=rows, with_ps=with_ps, with_ipp=with_ipp)
    return str(d)


def _ball_mask(n=24, r=8):
    z, y, x = np.ogrid[:n, :n, :n]
    c = (n - 1) / 2.0
    return ((x - c) ** 2 + (y - c) ** 2 + (z - c) ** 2) <= r * r


# ================================================================ F1 / B1
def test_step4_has_no_hardcoded_voxel_constants():
    """验收：无写死体素常量残留（源码字面量 + AST 浮点常量双查）。"""
    src = _s4()
    assert "0.3496" not in src, "step4 仍残留参考例写死 PixelSpacing 字面量"
    assert "0.35, 0.3496" not in src, "step4 仍残留写死 spacing 元组"
    floats = [n.value for n in ast.walk(_tree(src))
              if isinstance(n, ast.Constant) and isinstance(n.value, float)]
    assert 0.3496 not in floats and 0.35 not in floats, \
        "step4 仍有体素尺度浮点常量：%r" % floats


def test_step4_wires_header_spacing_into_marching_cubes():
    """接线：模块级真调头读函数与归一化断言；两次 marching_cubes 都吃 spacing。"""
    tree = _tree(_s4())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]

    def called(name):
        return any(isinstance(c.func, ast.Name) and c.func.id == name for c in calls)

    assert called("read_case_spacing"), "step4 未从本例 DICOM 头推导 spacing"
    assert called("assert_mask_normalized"), "step4 未落地次选方案的 mask 归一化断言"
    mc = [c for c in calls
          if isinstance(c.func, ast.Name) and c.func.id == "marching_cubes"]
    assert len(mc) >= 2, "step4 应有两处 marching_cubes（三档 + 置入后气域）"
    for c in mc:
        assert any(k.arg == "spacing" and isinstance(k.value, ast.Name)
                   and k.value.id == "spacing" for k in c.keywords), \
            "marching_cubes 未使用头推导的 spacing"
    vox = [n for n in tree.body if isinstance(n, ast.Assign)
           and any(isinstance(t, ast.Name) and t.id == "VOX" for t in n.targets)]
    assert vox and isinstance(vox[0].value, ast.BinOp), \
        "VOX 必须由 spacing 分量推导，不得是写死常量"


def test_read_case_spacing_tracks_pixel_spacing(tmp_path):
    """PixelSpacing != 0.3496 的输入，spacing 必须随头变化（不是旧常量）。"""
    ns = _step4_ns()
    ref = _write_series(tmp_path / "ref", ps=(0.3496, 0.3496), dz=0.35)
    alt = _write_series(tmp_path / "alt", ps=(0.5, 0.5), dz=0.7)
    sp_ref, _ = ns["read_case_spacing"](ref)
    sp_alt, _ = ns["read_case_spacing"](alt)
    assert sp_ref == (0.35, 0.3496, 0.3496)   # 参考例头读值与旧常量同（回归保护）
    assert sp_alt == (0.7, 0.5, 0.5)
    assert sp_alt != sp_ref


@pytest.mark.parametrize("ps,dz,want_z", [
    ((0.3496, 0.3496), 0.35, 0.35),
    ((0.3496, 0.3496), 0.8, 0.8),
    ((0.6, 0.6), 0.35, 0.35),
])
def test_read_case_spacing_uses_measured_slice_gap(tmp_path, ps, dz, want_z):
    """z 分量必须来自实测 IPP 层间距，不写死 0.35。"""
    ns = _step4_ns()
    d = _write_series(tmp_path / ("d_%s_%s" % (ps[0], dz)), ps=ps, dz=dz)
    spacing, _ = ns["read_case_spacing"](d)
    assert spacing[0] == want_z
    assert spacing[1] == round(ps[0], 4) and spacing[2] == round(ps[1], 4)


def test_read_case_spacing_fails_closed_without_two_slices(tmp_path):
    """0/1 层：fail-closed 明确报错，不退到写死常量。"""
    ns = _step4_ns()
    for tag, n in (("empty", 0), ("one", 1)):
        d = _write_series(tmp_path / tag, n=n) if n else str(tmp_path / tag)
        if not n:
            os.makedirs(d, exist_ok=True)
        with pytest.raises(SystemExit) as ei:
            ns["read_case_spacing"](d)
        assert "不回退写死常量" in str(ei.value)
        assert "0.3496" not in str(ei.value), "报错文案不得暗示回退旧常量"


@pytest.mark.parametrize("missing", ["no_ps", "no_ipp"])
def test_read_case_spacing_fails_closed_on_missing_header_fields(tmp_path, missing):
    """缺 PixelSpacing / 缺 IPP：fail-closed，不静默回退。"""
    ns = _step4_ns()
    kw = {"with_ps": False} if missing == "no_ps" else {"with_ipp": False}
    d = _write_series(tmp_path / missing, **kw)
    with pytest.raises(SystemExit) as ei:
        ns["read_case_spacing"](d)
    assert "不回退写死常量" in str(ei.value)


def test_assert_mask_normalized_rejects_mismatched_grid(tmp_path):
    """次选断言：面内网格与头不一致（或 2D）→ 明确报错，不导出错尺寸 STL。"""
    ns = _step4_ns()
    d = _write_series(tmp_path / "dcm", rows=24)
    _, ds_a = ns["read_case_spacing"](d)
    assert ns["assert_mask_normalized"](_ball_mask(24, 8), ds_a) is True
    with pytest.raises(SystemExit) as ei:
        ns["assert_mask_normalized"](_ball_mask(16, 6), ds_a)
    assert "归一化" in str(ei.value) and "不导出错尺寸 STL" in str(ei.value)
    with pytest.raises(SystemExit) as ei2:
        ns["assert_mask_normalized"](np.zeros((24, 24), dtype=bool), ds_a)
    assert "三维体素网格" in str(ei2.value)


def test_exported_stl_extents_track_header_spacing(tmp_path, monkeypatch):
    """合成例（验收核心）：PixelSpacing≠0.3496 的输入，STL 尺寸随头变化。

    用 step4 生产源码里的 export_mask 真导出 STL；平滑与本判据无关（会非线性
    扰动顶点），用 monkeypatch 隔离成 no-op，只留 spacing → 几何尺寸的线性关系。
    本机 trimesh 的 smoothing 模块无 smooth_laplacian（生产 try/except 本就跳过
    平滑），故 raising=False 兼容「有/无该函数」两种环境。
    """
    monkeypatch.setattr(trimesh.smoothing, "smooth_laplacian",
                        lambda *a, **k: None, raising=False)
    ns = _step4_ns()
    mask = _ball_mask(24, 8)
    out = []
    for tag, ps, dz in (("ref", (0.3496, 0.3496), 0.35),
                        ("alt", (0.5, 0.5), 0.7)):
        d = _write_series(tmp_path / ("dcm_" + tag), ps=ps, dz=dz, rows=24)
        spacing, ds_a = ns["read_case_spacing"](d)
        assert ns["assert_mask_normalized"](mask, ds_a) is True
        ns["spacing"] = spacing
        stl = str(tmp_path / ("implant_%s.stl" % tag))
        exported, _ = ns["export_mask"](mask, stl)
        assert len(exported) == 1 and os.path.isfile(stl), "必须真导出一份 STL"
        m = trimesh.load(stl)
        out.append((np.asarray(spacing, dtype=float),
                    np.asarray(m.extents, dtype=float), abs(float(m.volume))))
    (sp_a, ext_a, vol_a), (sp_b, ext_b, vol_b) = out
    # marching_cubes 顶点 = 索引 × spacing：各轴 extents 之比 == spacing 之比
    assert np.allclose(ext_a / ext_b, sp_a / sp_b, rtol=2e-3), (ext_a, ext_b, sp_a, sp_b)
    # 体积 ∝ 三个 spacing 分量之积
    want = (sp_a[0] * sp_a[1] * sp_a[2]) / (sp_b[0] * sp_b[1] * sp_b[2])
    assert abs(vol_a / vol_b - want) < 2e-3, (vol_a, vol_b, want)


# ================================================================ F2 / B8
def test_step5_contract_declares_seed_center_reference_only():
    """契约/文档头：v1 种子 CENTER 显式标注「仅参考数据集有效」。"""
    src = _s5()
    assert "T6/B8 次选" in src
    assert "仅对参考数据集" in src
    assert "患者A 冻结基线" in src
    assert "CENTER 沿用 v1（[79.22,71.87,56.98]）" not in src, \
        "无限定地宣称「沿用 v1」= 静默锚定，必须改为参考数据集限定"


def test_step5_doc_header_drops_hardcoded_voxel_mm():
    """文档头坐标行不再写死参考例体素间距，改指逐例头读常量。"""
    src = _s5()
    assert "x=i*0.3496" not in src
    assert "z=k*0.35 mm" not in src
    assert "x=i*SX_FULL, y=j*SY_FULL, z=k*SZ_FULL" in src


def test_step5_keeps_seed_anchor_for_reference_byte_identity():
    """次选：保留种子值 ⇒ 参考例 CENTER 数值分支零变化（逐字节不变的凭据）。"""
    src = _s5()
    assert "_SEED_CENTER_CACHE = {" in src
    assert "[79.224894, 71.872321, 56.979602]" in src
    assert '"center_matches_v1": [round(float(x), 2) for x in CENTER] == [79.22, 71.87, 56.98],' in src


def test_step5_non_reference_center_is_explicitly_degraded():
    """非参考病例：QC 标注 + 日志告警 + 误导性「沿用 v1，不重算」注释消失。"""
    src = _s5()
    assert "_CENTER_IS_REFERENCE = _fp_key in _SEED_CENTER_CACHE" in src
    assert "if not _CENTER_IS_REFERENCE:" in src
    assert '"reference_seed_applies"' in src
    assert '"degraded_notice"' in src
    assert "[T6/B8] 告警" in src
    assert "# 同一 CENTER 居中（沿用 v1，不重算）" not in src


def test_step5_still_recomputes_center_for_non_reference():
    """非参考病例仍走本例质心重算（不得静默套用参考例种子值）。"""
    src = _s5()
    assert "_center_pre = np.asarray(air.vertices.mean(axis=0), dtype=np.float64)" in src
    assert "CENTER = _center_pre" in src
