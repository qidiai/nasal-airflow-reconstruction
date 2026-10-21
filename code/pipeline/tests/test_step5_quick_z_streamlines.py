# -*- coding: utf-8 -*-
"""step5 快速档"看不到流线"回归（2026-10-21 根因修复）。

根因（上一轮审计定位、本轮修复）：step5 曾把体素速度网格 VG 的 z 间距**硬绑**
DS2_Z（= 2×全分辨率层厚 = 0.7mm），而快速档 CFD 单元 z 尺寸 = dz×zf
（0.35×9 = 3.15mm）→ 只有 0.7/3.15 = 22% 的 z 层有速度样本 → trilinear 权重
不足（wsum<0.25）→ sample_vel 返 None → 流线走不到 20 点 → 输出 0 条
（viewer 只看得到网格、看不到流线）。对照实验：均匀速度场、只改 z 单元尺寸时
快速档 0 条 / 标准档全部有效。

修复：VG 间距改为从 internal.vtu 单元几何**实测**（逐单元 bbox 跨度中位数），
取 max(名义 DS2, 实测) —— 只粗不细；索引换算（kk_c / gk / ck）同步；再加
KD-tree 最近单元兜底（距离 ≤1.5×单元对角线 且 点落在最近单元盒内）。

本文件的合成算例是自造数据（不是任何患者数据），只用于验证"z 单元变粗"这一
单一变量：同一套 mask/DICOM，只改 vtu 的 z 单元尺寸。

覆盖四条：
  1) 快速档（z=3.15mm）流线数 > 0，且 z 向有速度层 = 全部层（不再 22%）；
  2) 阶梯/残层（最后一片 z 单元变薄）同样不为 0；
  3) 标准档（z=0.7mm）VG 间距**不被粗化**、流线条数不倒退（实测 90 条）；
  4) 节点序陷阱：真实 foamToVTK 产物的 hexahedron 节点序并不按 x/y/z 排列
     （患者A 实测 (0,1) 棱是 z 向 0.7mm、(0,4) 棱是 x/y 向 0.6992mm）。
     本用例故意把节点序写成"0-1 棱沿 z"，VG 间距仍须按 z 实测出 3.15mm——
     按节点序号取棱长会张冠李戴；
  5) `--voxel-z` 只作回退：实测成功时不得覆盖实测值。
"""
import json
import os
import re
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.dirname(HERE)
STEP5 = os.path.join(PIPELINE, "step5_export_viewer_data.py")

VOX_MM = 0.35                 # 全分辨率体素间距（源层厚）→ DS2 = 0.7mm
NI = NJ = 70                  # 24.5mm
NK = 60                       # 21.0mm
PITCH_XY = 0.7                # CFD 单元 x/y 尺寸（= DS2）
Z_QUICK = 3.15                # 快速档 z 单元 = 0.35×9（≈4.5× DS2_Z）
U_MAG = 0.5                   # 合成流速 m/s

RE_PITCH = re.compile(r"\[诊断\] VG 网格间距 (\S+)/(\S+)/(\S+) mm")
RE_ZLAYER = re.compile(r"z 向有速度层 (\d+)/(\d+)（(\d+)%）")
RE_SEC = re.compile(r"streamlines 有效 (\d+) 条")


# ---------------------------------------------------------------- 合成算例
def _write_dicom_series(root):
    """3 张仅含头的空片：step5 只读 PixelSpacing / 层间距。"""
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid

    dcm = os.path.join(root, "dcm")
    os.makedirs(dcm, exist_ok=True)
    study = "1.2.840.10008.5.1.4.1.1.2.1.9"
    series = "1.2.840.10008.5.1.4.1.1.2.1.8"
    for n, z in enumerate((0.0, VOX_MM, 2 * VOX_MM)):
        meta = FileMetaDataset()
        meta.MediaStorageSOPClassUID = CTImageStorage
        meta.MediaStorageSOPInstanceUID = generate_uid()
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        path = os.path.join(dcm, "s%02d.dcm" % n)
        ds = FileDataset(path, {}, file_meta=meta, preamble=b"\0" * 128)
        ds.SOPClassUID = CTImageStorage
        ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
        ds.StudyInstanceUID = study
        ds.SeriesInstanceUID = series
        ds.Modality = "CT"
        ds.Rows, ds.Columns = NJ, NI
        ds.PixelSpacing = [VOX_MM, VOX_MM]
        ds.SliceThickness = VOX_MM
        ds.ImagePositionPatient = [0.0, 0.0, float(z)]
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.BitsAllocated, ds.BitsStored, ds.HighBit = 16, 12, 11
        ds.PixelRepresentation = 0
        ds.RescaleSlope, ds.RescaleIntercept = 1, -1024
        ds.PixelData = np.full((NJ, NI), 100, dtype=np.uint16).tobytes()
        ds.save_as(path, enforce_file_format=True)
    return dcm


def _write_mask(root):
    """气道长方体 + 两端鼻孔开口（cut 与 mask 相邻才判为开口）。"""
    mask = np.zeros((NK, NJ, NI), bool)
    mask[4:56, 10:60, 10:60] = True
    cut = np.zeros((NK, NJ, NI), bool)
    cut[4:56, 10:60, 6:10] = True       # 左鼻孔
    cut[4:56, 10:60, 60:64] = True      # 右鼻孔
    path = os.path.join(root, "mask.npz")
    np.savez(path, mask=mask, cut=cut)
    return path


def _write_contract(root):
    """单算例最小必需集（本测试不校验数字，只要通过契约门）。"""
    contract = {
        "title": "合成回归病例 · 快速档 z 粗化",
        "caseBaseline": "合成 @ 快速档口径",
        "units": "mm, m/s, Pa",
        "metrics": {
            "dP_baseline_Pa": 12.3, "dP_note": "合成数据（非患者）",
            "split_L_pct": 50.0, "split_R_pct": 50.0,
            "wss_mean_Pa": 0.01, "wss_p95_Pa": 0.05,
            "resistance_total": "100.0 Pa/(L/s)",
        },
    }
    path = os.path.join(root, "contract.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(contract, f, ensure_ascii=False, indent=1)
    return path


def _z_nodes(zcell, zmax, ragged):
    n = int(np.floor(zmax / zcell + 1e-9))
    zs = [round(i * zcell, 6) for i in range(n + 1)]
    if ragged and zs[-1] < zmax - 1e-9:
        zs.append(round(zmax, 6))      # 最后一片残层（非均匀 z）
    return np.asarray(zs, dtype=float)


def _write_vtu(root, zcell, ragged):
    """结构化六面体速度场；节点序故意写成"0-1 棱沿 z"（真实产物同款陷阱）。

    常规写法是 0-1 棱沿 x、0-4 棱沿 z；这里把底层四边形放在 x-z 平面、上层沿 +y
    平移，于是 (0,1) 棱 = z 向（长度 zcell）、(0,4) 棱 = y 向（PITCH_XY）。
    仍是合法 VTK hexahedron，但"按节点序号取棱长"会把 z 尺寸当成 x 尺寸。
    """
    import meshio

    xs = np.arange(0.0, (NI - 1) * VOX_MM + 1e-9, PITCH_XY)
    ys = np.arange(0.0, (NJ - 1) * VOX_MM + 1e-9, PITCH_XY)
    zs = _z_nodes(zcell, (NK - 1) * VOX_MM, ragged)
    nx, ny, nz = len(xs), len(ys), len(zs)
    gx, gy, gz = np.meshgrid(xs, ys, zs, indexing="ij")
    pts = np.stack([gx.ravel(), gy.ravel(), gz.ravel()], axis=1) / 1000.0   # -> m
    idx = np.arange(nx * ny * nz).reshape(nx, ny, nz)
    cells = []
    for i in range(nx - 1):
        for j in range(ny - 1):
            for k in range(nz - 1):
                A = idx[i, j, k]; B = idx[i, j, k + 1]
                C = idx[i + 1, j, k + 1]; D = idx[i + 1, j, k]
                E = idx[i, j + 1, k]; F = idx[i, j + 1, k + 1]
                G = idx[i + 1, j + 1, k + 1]; H = idx[i + 1, j + 1, k]
                cells.append([A, B, C, D, E, F, G, H])
    cells = np.asarray(cells)
    xc_, yc_, zc_ = (xs[:-1] + xs[1:]) / 2, (ys[:-1] + ys[1:]) / 2, (zs[:-1] + zs[1:]) / 2
    CX, CY, CZ = np.meshgrid(xc_, yc_, zc_, indexing="ij")
    ccx, ccy = CX.ravel(), CY.ravel()
    xmid = (xs[0] + xs[-1]) / 2.0
    vx = 0.6 * np.tanh((xmid - ccx) / 3.0)      # 两侧向中线入流
    vz = -0.3 * np.ones(len(ccx))               # 轻微向下（鼻咽方向）
    U = np.stack([vx, np.zeros(len(ccx)), vz], axis=1)
    U = U / np.linalg.norm(U, axis=1, keepdims=True) * U_MAG
    path = os.path.join(root, "internal.vtu")
    meshio.write(path, meshio.Mesh(pts, [("hexahedron", cells)],
                                   cell_data={"U": [U]}))
    return path


def _run_step5(root, zcell, ragged=False, voxel_z=None, tag="run"):
    """跑一次 step5；返回 (stdout, 输出目录)。"""
    from pathlib import Path

    dcm = _write_dicom_series(root)
    mask_npz = _write_mask(root)
    vtu = _write_vtu(root, zcell, ragged)
    contract = _write_contract(root)
    ph_dir = os.path.join(root, "ph")
    os.makedirs(ph_dir, exist_ok=True)
    out_dir = os.path.join(root, "out_%s" % tag)

    cmd = [sys.executable, "-X", "utf8", STEP5,
           "--dicom-dir", dcm, "--case-prefix", "pZ", "--case", "v1",
           "--vtu", vtu, "--metrics-json", contract, "--ph-dir", ph_dir,
           "--mask-npz", mask_npz, "--out-dir", out_dir,
           "--write-mode", "full", "--single-case"]
    if voxel_z is not None:
        cmd += ["--voxel-z", str(voxel_z)]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=1800, env=env)
    assert r.returncode == 0, (r.stdout[-4000:], r.stderr[-4000:])
    assert "Traceback" not in r.stderr, r.stderr[-4000:]
    return r.stdout, out_dir


def _read_viewer_streamlines(js_path):
    with open(js_path, encoding="utf-8") as f:
        txt = f.read()
    body = txt.split("window.VIEWER_DATA = ", 1)[1].split(";\n", 1)[0]
    return json.loads(body)["streamlines"]


def _pitch(stdout):
    m = RE_PITCH.search(stdout)
    assert m, "缺少 VG 网格间距诊断行:\n" + stdout[-3000:]
    return tuple(float(m.group(i)) for i in (1, 2, 3))


def _z_layers(stdout):
    m = RE_ZLAYER.search(stdout)
    assert m, "缺少 z 向有速度层诊断行:\n" + stdout[-3000:]
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def _n_streamlines(stdout):
    m = RE_SEC.search(stdout)
    assert m, "缺少流线条数日志:\n" + stdout[-3000:]
    return int(m.group(1))


# ---------------------------------------------------------------- 用例
def test_quick_mode_coarse_z_yields_streamlines(tmp_path):
    """[核心回归] 快速档 z 单元粗 4.5×：VG 层不再稀疏，流线数必须 > 0。"""
    for ragged, tag in ((False, "quick_uniform"), (True, "quick_ragged")):
        root = os.path.join(str(tmp_path), tag)
        os.makedirs(root, exist_ok=True)
        out, out_dir = _run_step5(root, Z_QUICK, ragged=ragged, tag=tag)

        # 1) VG z 间距对齐到实测单元尺寸（不是名义 DS2=0.7），xy 不动
        px, py, pz = _pitch(out)
        assert (px, py) == (PITCH_XY, PITCH_XY), (px, py)
        assert abs(pz - Z_QUICK) < 1e-6, "VG z 间距未对齐实测单元: %r" % (pz,)

        # 2) z 向不再"只有 22% 的层有速度"
        n_fill, n_k, pct = _z_layers(out)
        assert n_fill == n_k and pct == 100, (n_fill, n_k, pct)

        # 3) 流线条数 > 0（修复前恒为 0），且都 ≥20 点
        n = _n_streamlines(out)
        assert n > 0, "快速档流线仍为 0（根因未修）:\n" + out[-3000:]
        sl = _read_viewer_streamlines(os.path.join(out_dir, "viewer_data.js"))
        assert len(sl) == n, (len(sl), n)
        assert min(len(s["points"]) // 3 for s in sl) >= 20


def test_standard_z_pitch_unchanged_and_not_worse(tmp_path):
    """[回归] 标准档 z=0.7mm：VG 间距不得被粗化，流线条数不倒退。

    实测（修复前后同算例）：90 条 / z 层 100% / 最短 20 点。这里守住
    "≥60 条"的地板，而不是钉死 90——足够发现"标准档被修坏"，又不必为良性
    微调反复改测试。
    """
    root = str(tmp_path)
    out, out_dir = _run_step5(root, PITCH_XY, tag="std")
    assert _pitch(out) == (PITCH_XY, PITCH_XY, PITCH_XY), _pitch(out)
    n_fill, n_k, _ = _z_layers(out)
    assert n_fill == n_k
    n = _n_streamlines(out)
    assert n >= 60, "标准档流线数倒退: %d" % n
    sl = _read_viewer_streamlines(os.path.join(out_dir, "viewer_data.js"))
    assert len(sl) == n
    assert min(len(s["points"]) // 3 for s in sl) >= 20


def test_voxel_z_is_fallback_only(tmp_path):
    """`--voxel-z` 只作回退：单元几何实测成功时不得覆盖实测值。"""
    root = str(tmp_path)
    out, _ = _run_step5(root, PITCH_XY, voxel_z=Z_QUICK, tag="fallback")
    assert _pitch(out) == (PITCH_XY, PITCH_XY, PITCH_XY), (
        "--voxel-z 覆盖了实测单元尺寸", _pitch(out))

def test_ragged_thin_last_layer_does_not_break_index_bounds(tmp_path):
    """末层是残层（快速档 zf=9 的真实情形）：体心索引可能高于"节点 bbox 推出的
    上界"，网格范围必须按**体心索引**定界，否则 kk_c 越界断言直接崩。

    取 zcell=2.45mm（=7×0.35）使 zmax/zcell 小数部分 <0.5——这正是旧式
    `floor(pmax/pitch − 0.5)` 会低估上界的组合（zmax=20.65 → K1=7，而末层残层
    体心 20.125 → k=8）。
    """
    root = str(tmp_path)
    out, out_dir = _run_step5(root, 2.45, ragged=True, tag="ragged_thin")
    n_fill, n_k, pct = _z_layers(out)
    assert (n_fill, pct) == (n_k, 100), (n_fill, n_k, pct)
    n = _n_streamlines(out)
    assert n > 0, out[-3000:]
    assert len(_read_viewer_streamlines(os.path.join(out_dir, "viewer_data.js"))) == n
