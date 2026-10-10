# -*- coding: utf-8 -*-
"""T14 患者C 架构实现批 · GLM-5.3 独立审计（只读）"""
import sys, os, re, json, hashlib, glob, zipfile
sys.stdout.reconfigure(encoding="utf-8")
BASE = r"%DATA_ROOT%\项目\P0-鼻塞设计工具"
CALC = os.path.join(BASE, "阶段2-CFD算例包")
S5 = os.path.join(BASE, "阶段5-交互查看器")
PIPE = r"%QIDI_WORKSPACE%\contest3_workspace\pipeline"
R = []
def chk(n, ok, d=""):
    R.append((n, ok)); print(("✅" if ok else "❌"), n, ("| " + str(d)) if d else "")
def md5(p): return hashlib.md5(open(p, "rb").read()).hexdigest().upper()

print("—— A 冻结资产零接触 ——")
chk("A1 viewer_data.js F274FBDD", md5(os.path.join(S5, "viewer_data.js")).startswith("F274FBDD"))
chk("A2 viewer.html 7E6CF25A", md5(os.path.join(S5, "viewer.html")).startswith("7E6CF25A"))
chk("A3 pA 结果树 metrics 原值（51.867/39.001 并存；v5C 算例本体系笔记本侧历史业态，结果 zip 含已解算算例）",
    abs(json.load(open(os.path.join(CALC, "结果", "P0-result-pA-v5C", "后处理", "metrics.json"), encoding="utf-8"))["totals"]["flow_share_L_pct"] - 51.867) < 0.01
    and abs(json.load(open(os.path.join(CALC, "结果", "P0-result-pA-v5", "后处理", "metrics.json"), encoding="utf-8"))["totals"]["flow_share_L_pct"] - 39.001) < 0.01)

print("—— B L1 实现（step1）——")
s1 = open(os.path.join(PIPE, "step1_airway_segment.py"), encoding="utf-8").read()
chk("B1 26-conn 识别在码", "structure=ones((3,3,3))" in s1 or "ones((3, 3, 3))" in s1 or "ndimage.label" in s1)
chk("B2 补桥 HU<−300 过滤在码", bool(re.search(r"-3\d\d", s1)) and ("补桥" in s1 or "bridge" in s1.lower()))
chk("B3 规范字典序遍历（防顺序依赖）", "sort" in s1.lower() and ("lexicograph" in s1.lower() or "字典序" in s1 or "sorted(" in s1))
chk("B4 患者A 路径向后兼容（CLI 默认）", "--dicom-dir" in s1)

print("—— C L2' 实现（step2）——")
s2 = open(os.path.join(PIPE, "step2_make_ofcase.py"), encoding="utf-8").read()
chk("C1 6-conn 最小走廊守卫在码（迭代 OR 残留检查）", ("走廊" in s2 or "corridor" in s2.lower() or "guard" in s2.lower()) and "6-conn" in s2 or "6邻接" in s2 or "6-conn" in s2)
chk("C2 出口层豁免/守卫并存（T13b+T14 叠加不冲突）", "outlet" in s2.lower() and ("exempt" in s2.lower() or "豁免" in s2 or "守卫" in s2))
ra_t = open(os.path.join(PIPE, "run_all.py"), encoding="utf-8", errors="replace").read()
chk("C3 --allow-anatomy-inclusion 旗在 run_all（CLI+闸门上带 1.30+豁免 verdict）",
    "--allow-anatomy-inclusion" in ra_t and "解剖纳入豁免" in ra_t and "1.30" in ra_t)

print("—— D L3 出口通用化 ——")
chk("D1 z 端面 <30mm² 条件触发在码", bool(re.search(r"30\s*(mm)?\^?2|<\s*30", s2)) and ("PCA" in s2 or "主轴" in s2 or "principal" in s2.lower()))
chk("D2 稳定性准则 A≥0.8·A_max/双侧对称在码或文档", ("0.8" in s2 and "A_max" in s2) or ("0.8" in s2 and "对称" in s2))

print("—— E pC-v3 算例实物（共享树直读）——")
z3 = os.path.join(CALC, "P0-OF-case-pC-v3.zip")
chk("E1 v3 zip 在案且完整", os.path.exists(z3) and zipfile.ZipFile(z3).testzip() is None, f"{os.path.getsize(z3):,} B")
zf = zipfile.ZipFile(z3)
bnd = [n for n in zf.namelist() if n.endswith("constant/polyMesh/boundary") or n.endswith("constant\\polyMesh\\boundary")]
chk("E2 polyMesh boundary 可读", bool(bnd))
if bnd:
    btxt = zf.read(bnd[0]).decode("utf-8", errors="replace")
    blocks = re.findall(r"(\w+)\s*\{([^}]+)\}", btxt)
    out_nf = [int(re.search(r"nFaces\s+(\d+)", b).group(1)) for name, b in blocks if name == "outlet" and re.search(r"nFaces\s+(\d+)", b)]
    chk("E3 outlet 面数实测（≥50）", out_nf and out_nf[0] >= 50, f"outlet nFaces={out_nf}")
    inl = [int(re.search(r"nFaces\s+(\d+)", b).group(1)) for name, b in blocks if name in ("inletL", "inletR") and re.search(r"nFaces\s+(\d+)", b)]
    chk("E4 双入口面数在案", len(inl) >= 2, str(inl))
hd = os.path.join(CALC, "交接文档-笔记本执行-pC-v3.md")
def read(p): return open(p, encoding="utf-8", errors="replace").read()
hd_t = read(hd) if os.path.exists(hd) else ""
chk("E5 交接文档：nu 对齐显式写明", "1.8e-5" in hd_t and ("1.48e-5" in hd_t or "对齐" in hd_t))
chk("E6 交接文档：checkMesh 待笔记本（+nu 对齐警示）", "checkmesh" in hd_t.lower() and "1.48e-5" in hd_t)

print("—— F 回归证据复核（看板6 声明 vs 工件）——")
kb6 = read(os.path.join(S5, "升级施工-T10", "看板6-T14报告.md"))
chk("F1 看板6 声明患者A step2 28/28 逐字节", "28/28" in kb6 or ("28" in kb6 and "逐字节" in kb6))
chk("F2 看板6 声明 outlet 150 面/225.7mm²", ("150" in kb6 and "225.7" in kb6) or "225.7" in kb6)
chk("F3 看板6 含 8 项披露（双口径/陈旧产物等）", "披露" in kb6 and ("1.1728" in kb6 or "1.064" in kb6))
chk("F4 pB 视图对比图（T11 遗留复核）在案", bool(glob.glob(os.path.join(CALC, "pB_mask_views_T14_vs_preT14.png"))))

fails = [n for n, ok in R if not ok]
print("\n" + "=" * 52)
print(f"T14 GLM-5.3 审计: {len(R)-len(fails)}/{len(R)} 通过")
for n, ok in R:
    if not ok:
        print("  ❌", n)
sys.exit(1 if fails else 0)
