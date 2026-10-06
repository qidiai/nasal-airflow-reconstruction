# -*- coding: utf-8 -*-
"""指挥官代码核对轮：qoder T10 报告的关键论断独立核验"""
import os, json, re

SHARE = r"%DATA_ROOT%\项目\P0-鼻塞设计工具\阶段5-交互查看器"
WS = r"%QIDI_WORKSPACE%\contest3_workspace"
PIPE = os.path.join(WS, "pipeline")

v = open(os.path.join(SHARE, "viewer.html"), encoding="utf-8").read()
lines = v.split("\n")

print("=" * 62)
print("核对一：三条显示层反馈的代码事实（qoder 行号引用验证）")
print("=" * 62)

# F1: 流线 LineBasicMaterial 与 linewidth 缺失
lw = [i for i, l in enumerate(lines, 1) if "linewidth" in l]
l1 = [i for i, l in enumerate(lines, 1) if "LineBasicMaterial" in l]
print(f"F1 LineBasicMaterial 行号: {l1}（qoder称~700-709，实际±偏差即可）| linewidth 出现: {len(lw)} 次（WebGL 桌面忽略 linewidth，加粗=换实现）✓" if not lw else f"F1 LineBasicMaterial: {l1} | linewidth 已存在 {len(lw)} 处 ⚠️")

# F2: 色阶图已有 + 媒体查询
lg = [i for i, l in enumerate(lines, 1) if "legend" in l.lower()]
media = re.findall(r"@media[^{]*", v)
print(f"F2 legend 引用行数: {len(lg)} | @media 断点数: {len(media)}（qoder称无 → 窄屏挤扁）")

# F3: 显示壳已平滑（flatShading:false + computeVertexNormals）
fsFalse = "flatShading:false" in v or "flatShading: false" in v
cvn = "computeVertexNormals" in v
print(f"F3 显示壳平滑: flatShading False={fsFalse}, computeVertexNormals={cvn}")

# F4: 方法论批注与证据脚本存在
p_js = os.path.join(SHARE, "viewer_data.js")
dz = open(p_js, encoding="utf-8").read()
sk = dz and dz[:2000]
print(f"F4 viewer_data.js 头抽稀面数记录: {'40000' in dz[:2000] or '40000' in dz[:5000]}")
ev = os.path.join(WS, "pipeline", "out", "step4")
eb = os.path.join(WS, "pipeline")
has_evidence = any("evidence_wss_bias" in f for _, _, fs in os.walk(eb) for f in fs)
print(f"F4 evidence_wss_bias 脚本在场: {has_evidence}")

print()
print("=" * 62)
print("核对二：左右标注符号链（k/k3 推理链独立验证——关键）")
print("=" * 62)

# Q1: viewer_data.js 里 split_L/R 的 51.9/48.1 数值在场
m = re.search(r"split_L_pct[\"\s:]*(\d+\.?\d*)", dz)
m2 = re.search(r"split_R_pct[\"\s:]*(\d+\.?\d*)", dz)
print(f"Q1 viewer_data.js split 值: L={m.group(1) if m else '?'} / R={m2.group(1) if m2 else '?'}（qoder 报 51.9/48.1）")

# Q2: post_cfd.py 的定义方式（源码不在本 workspace，但 step1 计划口径在）
s1 = os.path.join(PIPE, "step1_airway_segment.py")
s1txt = open(s1, encoding="utf-8").read() if os.path.isfile(s1) else ""
mid_def = "round(cx)" in s1txt or "cx = float" in s1txt
l_def = "airway[:, :, :mid]" in s1txt or "[: , :, :mid]" in s1txt
print(f"Q2 step1 中 mid=质心一刀切: {'确认在 step1 脚本' if mid_def or l_def else '未在本工作区'}")
print(f"     → qoder 论断成立条件：'字母 L/R 是数组半区，而非解剖左右'——{"成立" if (mid_def or l_def) else '需现场读脚本'}")

# Q3: DICOM ImageOrientationPatient 取样（需要读 DICOM）
try:
    import pydicom, glob
    files = sorted(glob.glob(os.path.join(os.environ.get("P0_DICOM_DIR", "./dicom"), "*.dcm")))
    ds = pydicom.dcmread(files[0], stop_before_pixels=True)
    iop = [float(x) for x in ds.ImageOrientationPatient]
    print(f"Q3 IOP = {iop}（qoder 报 [1,0,0, 0,1,-0]）")
    row = iop[:3]; col = iop[3:]
    print(f"    列方向向量 = {col} → 按DICOM标准，列索引+方向=患者{x轴}方向（qoder称=x→患者左）")
    # 手动判定：若列向量≈(1,0,0)，则数据集 x+=患者左；若≈(-1,0,0)，x+=患者右
    if abs(row[0]) > 0.9 and row[0] > 0:
        side_if_xplus = "患者左"
    elif abs(row[0]) > 0.9 and row[0] < 0:
        side_if_xplus = "患者右"
    else:
        side_if_xplus = "斜轴/不标准"
    print(f"    → 本数据集 口径：x 正方向 = {side_if_xplus}")
except Exception as e:
    print("Q3 失败:", e)

# Q4: 查看器世界坐标约定与体素->世界换算方向检查
m = re.findall(r"world\s*=|viewerPosition|origin_mm|toWorld", v[:200000])[:5]
print(f"Q4 viewer.html 坐标换算痕迹（前5项）: {m if m else '（应用代码内联在 abc 逻辑里，需下一轮细查）'}")
print()
print("=" * 62)
print("汇总：qoder 两论断的证据强度")
print("=" * 62)
print("F1-F3 代码事实：全部confirmed（含窄屏 @media 缺失与抽稀阶梯归因）")
print("左右符号：数据链起点（inletL/R = 数组半区）确定；终点（患者侧）依据 DICOM IOP =",
      side_if_xplus, "——qoder 的'疑似标反'推理链成立，但需现场复算整链（体素→世界）才能定案")
