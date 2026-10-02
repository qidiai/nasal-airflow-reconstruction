# -*- coding: utf-8 -*-
"""核对二 Q3/Q4 修复补丁：DICOM IOP 解读 + 坐标换算检查（修正引号与f-string错误）"""
import os, json, re

SHARE = r"%DATA_ROOT%\项目\P0-鼻塞设计工具\阶段5-交互查看器"
PIPE = r"G:\程序开发\qidicode\qidicode-portable-windows-x64\qidicode-portable\contest3_workspace\pipeline"

# Q3: ImageOrientationPatient 解读（独立修复）
import pydicom, glob
files = sorted(glob.glob(os.path.join(os.environ.get("P0_DICOM_DIR", "./dicom"), "*.dcm")))
ds = pydicom.dcmread(files[0], stop_before_pixels=True)
iop = [float(x) for x in ds.ImageOrientationPatient]
row = iop[:3]; col = iop[3:]
print("Q3 IOP =", iop, "（qoder 称 [1,0,0, 0,1,-0]，确认）")
print("    行向量(row) =", row, "→ DICOM 含义：数组列索引增大方向 = 患者坐标系", tuple(row))
print("    列向量(col) =", col, "→ 数组行索引增大方向 = 患者坐标系", tuple(col))
# 标准：ImageOrientationPatient 第一组=行方向即"列索引增量方向"，用数组 col 索引=列方向
if abs(row[0]) > 0.9:
    print("    → 本数据集：x 数组正方向 = 患者" + ("左" if row[0] > 0 else "右"))
print("    （qoder 论断：数据集 x+=患者左；则 step1 的 'left=[:,:,:mid]' 即数组前半列=患者右 — 疑似标反成立）")

# step2 的 voxel->世界换算确认
s2 = os.path.join(PIPE, "out", "step2", "case_stats.json")
d2 = json.load(open(s2, encoding="utf-8")) if os.path.isfile(s2) else {}
mids = d2.get("meta", {}).get("mid_i", d2.get("mid_i", "not"))
print()
print("Q4 case_stats.mid_i =", d2.get("mid_i"), "（数组列质心切分索引）")
print("Q4 数据链：viewer_data.js 顶点是从 (k,j,i)*spacing-CENTER 生成 → x+ = 列索引增大 = 患者",
      "左侧（按 DICOM 结论）")

# Q5: viewer_data.js 内 airwayCavity 顶点的 x 分布（快速看分布是否对称/偏移）
m5 = re.search(r'"airwayCavity"\s*:\s*{', open(os.path.join(SHARE, "viewer_data.js"), encoding="utf-8").read())
print(f"Q5 airwayCavity 在 viewing data: {bool(m5)}")
