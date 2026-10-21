# -*- coding: utf-8 -*-
"""step5 "零有效流线"退化路径回归（2026-10-21 服务器实测崩溃后新增）。

现场（真实 CT、快速档）：86 个种子候选全部 < 20 点 -> 打印「streamlines 有效 0 条」，
紧接着 line 501 直接引用只存在于「有有效流线」分支里的 z0/z1：

    NameError: name 'z0' is not defined. Did you mean: 'I0'?

钉住的契约：
  1) 0 条有效流线不得崩溃：跳过方向自检统计日志，并打一行明确警告
     「[W] 流线 0 条：跳过方向自检，viewer 仅显示气道网格」；
  2) 仍要走到导出：viewer_data.js 正常写出，且 streamlines 是 **空数组**（不伪造数据、
     不借别的病例的流线）；质检 A3_streamlines 如实记 FAIL（0 条不满 >=40 条口径）；
  3) 板⑥ 流线-壳间隙抽检无抽样点 -> 记 SKIP（pass=None + skipped=True + 理由），
     绝不记 PASS、不编造间隙数字；SKIP 不计入 all_gates_pass，故不触发停工 exit(3)。

构造 0 流线输入的方式：不 monkeypatch 流线函数，而是让合成速度场量级（1e-6 m/s）
远低于 step5 的 SPD_EPS=1e-4 m/s —— 每个种子在首步即判停（integrate 返回 None），
与现场「种子全灭」走同一条代码路径（build() 收集到 0 条）。
几何/场全部现场合成，不含任何患者数据。
"""
import json
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.dirname(HERE)
STEP5 = os.path.join(PIPELINE, "step5_export_viewer_data.py")

VOX_MM = 0.35          # 合成全分辨率体素间距（mm）
NK, NJ, NI = 40, 30, 30
U_TINY = 1e-6          # 远低于 step5 SPD_EPS=1e-4 m/s

WARN_LINE = "[W] 流线 0 条：跳过方向自检，viewer 仅显示气道网格"


# ---------------------------------------------------------------- 合成输入
def _write_dicom_series(root):
    """3 张最小 CT 轴位片（0.35mm 各向），只供 step5 读 PixelSpacing/层间距。"""
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
    """主腔（鼻腔本体）+ 独立小球（鼻窦）+ 两处头外空气（左右鼻孔开口）。"""
    mask = np.zeros((NK, NJ, NI), bool)
    mask[2:38, 8:22, 8:22] = True       # 主腔
    mask[30:36, 2:7, 2:7] = True        # 独立组分 -> sinus（保证两边都有 marching_cubes 面）
    cut = np.zeros((NK, NJ, NI), bool)
    cut[2:38, 8:22, 5:8] = True         # 左鼻孔开口外空气（与主腔相邻）
    cut[2:38, 8:22, 22:25] = True       # 右鼻孔开口外空气
    path = os.path.join(root, "mask.npz")
    np.savez(path, mask=mask, cut=cut)
    return path


def _write_vtu(root):
    """粗六面体网格（节点间距 = 0.7mm = step5 的 DS2，使体素速度网格密实充填）
    + 极小均匀速度场（1e-6 m/s，非零以避免 mean_inward 归一化除零）。"""
    import meshio

    ds2 = round(VOX_MM * 2.0, 4)
    nodes = np.arange(0, 21) * ds2                       # 0 .. 14mm
    gx, gy, gz = np.meshgrid(nodes, nodes, nodes, indexing="ij")
    pts = np.stack([gx.ravel(), gy.ravel(), gz.ravel()], axis=1) / 1000.0   # -> m
    n = len(nodes)
    idx = np.arange(n ** 3).reshape(n, n, n)
    hexes = []
    for i in range(n - 1):
        for j in range(n - 1):
            for k in range(n - 1):
                hexes.append([idx[i, j, k], idx[i + 1, j, k],
                              idx[i + 1, j + 1, k], idx[i, j + 1, k],
                              idx[i, j, k + 1], idx[i + 1, j, k + 1],
                              idx[i + 1, j + 1, k + 1], idx[i, j + 1, k + 1]])
    hexes = np.asarray(hexes)
    u = np.tile(np.array([U_TINY, 0.0, 0.0]), (len(hexes), 1))
    path = os.path.join(root, "internal.vtu")
    meshio.write(path, meshio.Mesh(pts, [("hexahedron", hexes)],
                                   cell_data={"U": [u]}))
    return path


def _write_contract(root):
    """单算例最小必需集（三档占位/曲线天然缺失 -> --single-case 放行）。"""
    contract = {
        "title": "合成回归病例 鼻腔气流仿真查看器",
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


def _read_viewer_data(js_path):
    with open(js_path, encoding="utf-8") as f:
        txt = f.read()
    assert txt.count("window.VIEWER_DATA = ") == 1
    body = txt.split("window.VIEWER_DATA = ", 1)[1].split(";\n", 1)[0]
    return json.loads(body)


# ---------------------------------------------------------------- 用例
def test_zero_streamlines_does_not_crash_and_exports_empty(tmp_path):
    root = str(tmp_path)
    dcm = _write_dicom_series(root)
    mask_npz = _write_mask(root)
    vtu = _write_vtu(root)
    contract = _write_contract(root)
    ph_dir = os.path.join(root, "ph")          # 空目录：三档占位体本次未做
    os.makedirs(ph_dir, exist_ok=True)
    out_dir = os.path.join(root, "out")

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run(
        [sys.executable, "-X", "utf8", STEP5,
         "--dicom-dir", dcm, "--case-prefix", "pZ", "--case", "v1",
         "--vtu", vtu, "--metrics-json", contract, "--ph-dir", ph_dir,
         "--mask-npz", mask_npz, "--out-dir", out_dir,
         "--write-mode", "full", "--single-case"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=600, env=env)

    # 1) 不崩溃：没有 NameError/Traceback，且退出码 0
    assert r.returncode == 0, (r.stdout[-3000:], r.stderr[-3000:])
    assert "NameError" not in r.stderr, r.stderr[-3000:]
    assert "Traceback" not in r.stderr, r.stderr[-3000:]

    # 2) 退化路径确实被走到：0 条有效流线 + 一行明确警告
    assert "streamlines 有效 0 条" in r.stdout, r.stdout[-3000:]
    assert WARN_LINE in r.stdout, r.stdout[-3000:]

    # 3) 走到导出：streamlines 是真的空数组，不是伪造数据
    js_path = os.path.join(out_dir, "viewer_data.js")
    assert os.path.isfile(js_path), "0 流线时必须仍写出 viewer_data.js"
    data = _read_viewer_data(js_path)
    assert data["streamlines"] == [], "0 条流线必须导出空数组，不得伪造流线"
    assert data["meta"]["partial"] is True        # 三档占位/曲线本次未做，如实标注

    # 4) 板⑥ 记 SKIP 而非 PASS，且不编造间隙数字
    boards_path = os.path.join(out_dir, "six_boards_pZ-v1.json")
    with open(boards_path, encoding="utf-8") as f:
        boards = json.load(f)
    b6 = boards["board6_streamline_shell_clearance"]
    assert b6["pass"] is None and b6["skipped"] is True
    assert b6["sampled_points"] == 0 and b6["streamlines"] == 0
    for k in ("min_clearance_mm", "mean_clearance_mm", "p95_clearance_mm",
              "max_clearance_mm"):
        assert k not in b6, "0 流线时不得编造 %s" % k
    gate6 = boards["gates"]["board6_v3_two_segment_ambiguity_exempt"]
    assert gate6["pass"] is None and gate6["skipped"] is True
    assert "未执行" in gate6["reason"]
    # SKIP 不计入 all_gates_pass -> 不触发停工，导出照常完成
    assert boards["all_gates_pass"] is True

    # 5) 质检如实记 FAIL（0 条不满足 A3 的 >=40 条口径），不掩盖
    with open(os.path.join(out_dir, "viewer_data_qc.json"), encoding="utf-8") as f:
        qc = json.load(f)
    assert qc["A3_streamlines"]["pass"] is False
    assert qc["A3_streamlines"]["count"] == 0