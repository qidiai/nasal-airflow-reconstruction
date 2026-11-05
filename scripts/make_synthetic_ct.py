#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合成鼻腔 CT 生成器（冒烟验证专用）。

============================================================
合成数据，仅用于冒烟验证，不代表真实病例。
============================================================

生成一组完全匿名化、几何受控的最小 DICOM CT 序列，用于：
  - bootstrap 一条命令自检（scripts/bootstrap.ps1 / scripts/bootstrap.sh）
  - run_all.py 全链路冒烟（--solve skip / --solve local）
  - server.py POST /api/upload 端到端上传链路验证

几何（仿鼻腔长轴；口径对齐 run_all.py 的 A1-A6 朝向断言与
code/pipeline/step2_make_ofcase.py 的默认朝向 nostril_at_high）：
  - z 轴：z 小端 = 咽/出口端（单根粗管，底端被组织包裹封闭）；
          z 大端 = 鼻/入口端（左右两根并排的细管 = 双鼻腔）。
  - 鼻孔开口按真实前庭方式建模：每侧鼻腔前端带一个前庭囊袋
    （z=36..39 开向组织前缘 → 与外部空气连通，step2 的 cut 判据）；
    z=35 为顶盖层（组织完整，囊袋经此层连回鼻腔）——囊袋顶盖的
    +z 面即「气道贴头外空气」的入口面（step2 把掩码最高层 +z 面
    恒归为 walls，故入口面必须在掩码 z 范围内部）。
  - y 轴：小端 = 鼻端（入口半区），大端 = 咽端（出口半区）。
  - x 轴：左右（A1 左右分居：inletL.x < 中线 < inletR.x）。

HU：空气管腔/外部空气 -1000，软组织背景 +40
（阈值口径：step1 默认 --hu-air -400 / --hu-head -300）。

PII：10 个 PII 字段全部显式置空（run_all.py scan_pii 口径：空或
UNKNOWN 即放行；PatientID 空即不触发 ^\\d{8}-\\d{6}$ 校验）。

用法：
  python scripts/make_synthetic_ct.py --out out/synthetic-ct
退出码：0 成功；非 0 失败（缺依赖等）。
"""

import argparse
import json
import os
import sys
import time

import numpy as np

try:
    import pydicom
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid
except ImportError as e:  # noqa: BLE001
    print(f"[make_synthetic_ct] 缺依赖：{e}——请先 pip install -r requirements.txt",
          file=sys.stderr)
    sys.exit(3)


# ---------------------------------------------------------------- 几何与成像参数
ROWS = COLS = 96          # 行列数（小体量，跑得快）
NSL = 48                  # 层数
SPACING_XY = 0.7          # mm（PixelSpacing 行/列同值）
SPACING_Z = 1.0           # mm（SliceThickness）
HU_AIR = -1000.0          # 空气（管腔 + 外部背景）
HU_TISSUE = 40.0          # 软组织背景
RESCALE_INTERCEPT = -1024.0
RESCALE_SLOPE = 1.0

# 组织包（"头部"）：z=0..45 的矩形块，包住全部气道并留出四周外部空气
PH_X0, PH_X1 = 24, 72     # 列方向 [闭区间]
PH_Y0, PH_Y1 = 26, 72     # 行方向 [闭区间]（前缘前移，给前庭囊袋留位置）
PH_Z0, PH_Z1 = 0, 45      # 层方向 [闭区间]

# 气道全部为轴对齐矩形、偶数体素尺寸、z 层成对对齐——step2 的 2x2x2
# 多数表决降采样在轴对齐边界上体积比 = 1.00（体积回归比闸门 0.94–1.06）。
# 咽段（单根粗管，z 低 = 出口端；底端 z=2，之下 z=0,1 为组织 → 出口被包裹）
PHARYNX_Z0, PHARYNX_Z1 = 2, 29      # 28 层（偶，配 zf=2）
PHARYNX_Y0, PHARYNX_Y1 = 48, 69     # 22 体素 ≈ 15.4mm
PHARYNX_X0, PHARYNX_X1 = 38, 59     # 22 体素

# 过渡段（咽 → 双鼻腔；后段+桥+双管相互交叠 → 6-conn 单连通）
TRANS_Z0, TRANS_Z1 = 30, 33         # 4 层（偶）
BACK_Y0, BACK_Y1 = 50, 67           # 后段 18×18
BACK_X0, BACK_X1 = 40, 57
BRIDGE_Y0, BRIDGE_Y1 = 42, 53       # 桥 12×18
BRIDGE_X0, BRIDGE_X1 = 40, 57

# 双管段（左右鼻腔，z 高 = 入口端；全程被组织包裹封闭）
TUBE_Z0, TUBE_Z1 = 34, 45           # 12 层（偶）
TUBE_Y0, TUBE_Y1 = 38, 51           # 14 体素 ≈ 9.8mm
TUBEL_X0, TUBEL_X1 = 28, 41         # 左管 14 体素
TUBER_X0, TUBER_X1 = 56, 69         # 右管 14 体素（鼻中隔间隙 42..55）

# 前庭囊袋（鼻孔开口）：z=36..39 开向组织前缘 → cut；z=35 顶盖层封闭
VEST_Z0, VEST_Z1 = 36, 39           # 4 层（偶）
VEST_Y0, VEST_Y1 = 26, 36           # 囊袋 y 范围（y=26 组织前缘开口；y=37 为隔壁）
VESTL_X0, VESTL_X1 = 26, 43         # 左囊袋 18 体素
VESTR_X0, VESTR_X1 = 54, 71         # 右囊袋 18 体素
CEIL_Z = 35                         # 顶盖层（与 z=34 配对；组织完整）
CEIL_Y0, CEIL_Y1 = 27, 51           # 顶盖 y 范围（前缘 y=26 留组织 → 层内封闭）


def build_hu_volume():
    """返回 (NSL, ROWS, COLS) float32 HU 体数据。轴序 [z, y, x]。"""
    hu = np.full((NSL, ROWS, COLS), HU_AIR, dtype=np.float32)
    yy, xx = np.mgrid[0:ROWS, 0:COLS]

    # 1) 组织包
    box = ((xx >= PH_X0) & (xx <= PH_X1)
           & (yy >= PH_Y0) & (yy <= PH_Y1))
    for z in range(PH_Z0, PH_Z1 + 1):
        hu[z][box] = HU_TISSUE

    # 2) 气道（在组织包内雕空；轴对齐矩形 → 多数表决降采样体积比 1.00）
    def rect(y0, y1, x0, x1):
        return (yy >= y0) & (yy <= y1) & (xx >= x0) & (xx <= x1)

    for z in range(PHARYNX_Z0, PHARYNX_Z1 + 1):          # 咽段
        hu[z][rect(PHARYNX_Y0, PHARYNX_Y1, PHARYNX_X0, PHARYNX_X1)] = HU_AIR

    for z in range(TRANS_Z0, TRANS_Z1 + 1):              # 过渡段
        hu[z][rect(BACK_Y0, BACK_Y1, BACK_X0, BACK_X1)] = HU_AIR
        hu[z][rect(BRIDGE_Y0, BRIDGE_Y1, BRIDGE_X0, BRIDGE_X1)] = HU_AIR
        hu[z][rect(TUBE_Y0, TUBE_Y1, TUBEL_X0, TUBEL_X1)] = HU_AIR
        hu[z][rect(TUBE_Y0, TUBE_Y1, TUBER_X0, TUBER_X1)] = HU_AIR

    for z in range(TUBE_Z0, TUBE_Z1 + 1):                # 双管段
        hu[z][rect(TUBE_Y0, TUBE_Y1, TUBEL_X0, TUBEL_X1)] = HU_AIR
        hu[z][rect(TUBE_Y0, TUBE_Y1, TUBER_X0, TUBER_X1)] = HU_AIR

    # 3) 前庭囊袋（鼻孔开口）：z=36..39 开向组织前缘（y=26）→ 与外部
    #    空气连通 → step1 的 2D 填洞不含它 → step2 判为 cut；与双管
    #    在层内被 y=37 隔壁分开（不触碰），只经顶盖层 z=35 连回气道。
    for z in range(VEST_Z0, VEST_Z1 + 1):
        hu[z][rect(VEST_Y0, VEST_Y1, VESTL_X0, VESTL_X1)] = HU_AIR
        hu[z][rect(VEST_Y0, VEST_Y1, VESTR_X0, VESTR_X1)] = HU_AIR
    # 4) 顶盖层 z=35：组织完整的一整层；每侧一片导管把囊袋顶面
    #    （+z 面 → 入口面）与双管连成一体（层内封闭，填洞后属气道）。
    hu[CEIL_Z][rect(CEIL_Y0, CEIL_Y1, VESTL_X0, VESTL_X1)] = HU_AIR
    hu[CEIL_Z][rect(CEIL_Y0, CEIL_Y1, VESTR_X0, VESTR_X1)] = HU_AIR

    # 5) z=46..47：无组织（头外空气背景，保持默认即可）
    return hu


def write_series(hu, out_dir):
    """把 HU 体数据写成 48 个匿名化 DICOM 切片。返回写出的文件清单。"""
    os.makedirs(out_dir, exist_ok=True)
    study_uid = generate_uid()
    series_uid = generate_uid()
    frame_uid = generate_uid()
    raw_all = np.clip(hu - RESCALE_INTERCEPT / RESCALE_SLOPE, 0, 65535).astype(np.uint16)

    files = []
    for z in range(NSL):
        sop_uid = generate_uid()
        meta = FileMetaDataset()
        meta.MediaStorageSOPClassUID = CTImageStorage
        meta.MediaStorageSOPInstanceUID = sop_uid
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        meta.ImplementationClassUID = pydicom.uid.PYDICOM_IMPLEMENTATION_UID

        path = os.path.join(out_dir, f"slice_{z:03d}.dcm")
        ds = FileDataset(path, {}, file_meta=meta, preamble=b"\0" * 128)
        ds.is_little_endian = True
        ds.is_implicit_VR = False
        ds.SOPClassUID = CTImageStorage
        ds.SOPInstanceUID = sop_uid
        ds.StudyInstanceUID = study_uid
        ds.SeriesInstanceUID = series_uid
        ds.FrameOfReferenceUID = frame_uid
        ds.Modality = "CT"
        ds.SeriesNumber = 1
        ds.InstanceNumber = z + 1
        ds.SeriesDescription = "Synthetic CT smoke phantom (not a real patient)"
        # ---- PII 字段全部显式置空（scan_pii 放行口径）----
        ds.PatientName = ""
        ds.PatientID = ""
        ds.PatientBirthDate = ""
        ds.PatientSex = ""
        ds.InstitutionName = ""
        ds.InstitutionAddress = ""
        ds.ReferringPhysicianName = ""
        ds.AccessionNumber = ""
        ds.StudyID = ""
        ds.OtherPatientIDs = ""
        # ---- 像块 ----
        ds.Rows = ROWS
        ds.Columns = COLS
        ds.BitsAllocated = 16
        ds.BitsStored = 16
        ds.HighBit = 15
        ds.PixelRepresentation = 0
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.PixelData = raw_all[z].tobytes()
        # ---- 几何与 HU 标定 ----
        ds.PixelSpacing = [str(SPACING_XY), str(SPACING_XY)]
        ds.SliceThickness = str(SPACING_Z)
        ds.ImagePositionPatient = ["0", "0", str(float(z) * SPACING_Z)]
        ds.ImageOrientationPatient = ["1", "0", "0", "0", "1", "0"]
        ds.SliceLocation = float(z) * SPACING_Z
        ds.RescaleIntercept = str(RESCALE_INTERCEPT)
        ds.RescaleSlope = str(RESCALE_SLOPE)
        ds.RescaleType = "HU"
        ds.WindowCenter = "40"
        ds.WindowWidth = "350"
        ds.save_as(path, write_like_original=False)
        files.append(path)
    return files


def main():
    ap = argparse.ArgumentParser(
        description="合成鼻腔 CT 生成器（冒烟验证专用；合成数据，不代表真实病例）")
    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    ap.add_argument("--out", default=os.path.join(repo, "out", "synthetic-ct"),
                    help="输出目录（默认 <repo>/out/synthetic-ct）")
    args = ap.parse_args()

    t0 = time.time()
    hu = build_hu_volume()
    files = write_series(hu, args.out)

    # 气道体素 = 组织包内的空气孔洞（z 2..45 段）
    box = np.zeros((ROWS, COLS), bool)
    box[PH_Y0:PH_Y1 + 1, PH_X0:PH_X1 + 1] = True
    airway = int(sum(int(((hu[z] == HU_AIR) & box).sum())
                     for z in range(PHARYNX_Z0, TUBE_Z1 + 1)))
    summary = {
        "out_dir": os.path.abspath(args.out),
        "files": len(files),
        "shape": [NSL, ROWS, COLS],
        "spacing_mm": [SPACING_Z, SPACING_XY, SPACING_XY],
        "hu_air": HU_AIR, "hu_tissue": HU_TISSUE,
        "airway_voxels": airway,
        "airway_volume_ml": round(airway * SPACING_XY * SPACING_XY * SPACING_Z / 1000.0, 2),
        "pii_fields": "all empty (10 fields)",
        "note": "合成数据，仅用于冒烟验证，不代表真实病例",
        "elapsed_sec": round(time.time() - t0, 2),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"[make_synthetic_ct] OK：{len(files)} 个切片 -> {os.path.abspath(args.out)}"
          f"（合成数据，仅用于冒烟验证，不代表真实病例）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
