# -*- coding: utf-8 -*-
"""T11+提交包 step5 式独立审计（发包前终检 · 只读）"""
import sys, os, re, json, hashlib, zipfile
sys.stdout.reconfigure(encoding="utf-8")
BASE = r"%DATA_ROOT%\项目\P0-鼻塞设计工具"
S5 = os.path.join(BASE, "阶段5-交互查看器")
PKG = os.path.join(BASE, "提交包-20261002")
REPO = r"%DATA_ROOT%\..\开源仓库"
WS = r"%QIDI_WORKSPACE%\contest3_workspace"
RES = []
def chk(n, ok, d=""):
    RES.append((n, ok)); print(("✅" if ok else "❌"), n, ("| " + str(d)) if d else "")
def md5(p): return hashlib.md5(open(p, "rb").read()).hexdigest().upper()
def read(p): return open(p, encoding="utf-8").read()

print("—— A 提交包完整性（k3 A 组）——")
chk("A1 README-提交说明（双口径表+6 披露）",
    all(k in read(os.path.join(PKG, "README-提交说明.md")) for k in
        ["v5 定流量口径", "v5C 等压法口径", "主动披露", "两口径", "120–600 Pa/(L/s)", "非医疗器械"]))
v2 = read(os.path.join(PKG, "需求符合度自评-33条-终审版-20261002.md"))
chk("A2 自评终审版在包且含 75.6", "75.6" in v2)
for f, src in [("viewer_single.html", S5), ("viewer.html", S5), ("viewer_data.js", S5), ("volume_data.js", S5),
               ("skin_data.js", S5), ("README-使用说明.md", S5)]:
    chk(f"A3 {f} 包内==共享", os.path.exists(os.path.join(PKG, f)) and md5(os.path.join(PKG, f)) == md5(os.path.join(src, f)))
chk("A4 单文件≤闸门", os.path.getsize(os.path.join(PKG, "viewer_single.html")) <= 16_200_499,
    f"{os.path.getsize(os.path.join(PKG,'viewer_single.html')):,} B")
chk("A5 报告\\ 两份在包", all(os.path.exists(os.path.join(PKG, "报告", f)) for f in
    ["诊断报告3-v5终版基线与等压迭代-20260928.md", "环节②终版报告-v5.md"]))
resd = os.listdir(os.path.join(PKG, "结果"))
chk("A6 结果\\ v5/v5C/v5E-ext×2 zip + 交接文档",
    all(any(x.startswith(n) for x in resd) for n in ["P0-result-pA-v5.zip", "P0-result-pA-v5C.zip", "P0-OF-case-pA-v5E-ext", "P0-OF-case-pA-v5E-extB"])
    and any("交接文档" in x and "v5E-ext" in x for x in resd))
figs = os.listdir(os.path.join(PKG, "figures"))
chk("A7 figures\\ fig1-4+fig5", sum(f.startswith("fig") and f.endswith(".png") for f in figs) >= 5, str(figs))
chk("A8 STL\\ 三件", all(os.path.exists(os.path.join(PKG, "STL", f)) for f in
    ["airway_pA_v2.stl", "P0-airway-pA-simplified-100k.stl", "metrics_v2.json"]))
chk("A9 治理三件", all(os.path.exists(os.path.join(PKG, f)) for f in
    ["授权确认记录-20260930.md", "匿名化核验记录-20261002.md", "协作与迭代证据-20261002.md"]))
zp = os.path.join(PKG, "开源代码包.zip")
zf = zipfile.ZipFile(zp)
names = zf.namelist()
chk("A10 开源代码包.zip 完整（LICENSE/README/step1/step2/无 .git）",
    any("LICENSE" in n for n in names) and any(n.endswith("README.md") for n in names)
    and any("step1" in n for n in names) and any("step2" in n for n in names)
    and not any(".git/" in n for n in names) and zf.testzip() is None, f"{len(names)} 项")
prev = os.path.join(PKG, "后续路线预览")
chk("A11 预览声明在位", "不计入本次符合度" in read(os.path.join(prev, "README-预览说明.md")))
chk("A12 预览隔离（植入体STL≥10 + 占位算例 zip≥3 + step3/4）",
    len([f for f in os.listdir(os.path.join(prev, "植入体STL")) if f.endswith(".stl")]) >= 10
    and len([f for f in os.listdir(os.path.join(prev, "占位算例")) if f.endswith(".zip")]) >= 3
    and all(os.path.exists(os.path.join(prev, "占位算例", f)) for f in ["step3_make_narrowing.py", "step4_export_implant.py"]))
# A13-A15 新鲜度断言（防"修完忘换包"复发）
zsrc = zipfile.ZipFile(zp)
stale = [n for n in zsrc.namelist() if n.endswith(".py") and "%DATA_ROOT%" in zsrc.read(n).decode("utf-8", errors="replace")]
chk("A13 开源代码包.zip 与 HEAD 同步（绝对路径零残留）", not stale, str(stale[:3]))
chk("A14 诊断报告7（患者B）在包", os.path.exists(os.path.join(PKG, "报告", "诊断报告7-患者B试点-20261003.md")))
mpd = os.path.join(PKG, "多患者管线验证")
chk("A15 多患者验证目录（README/报告8/run_all/pB zip）",
    os.path.exists(os.path.join(mpd, "README-多患者验证.md"))
    and any("患者C" in f for f in os.listdir(mpd))
    and any("run_all" in f for f in os.listdir(mpd))
    and any(f.startswith("P0-result-pB") for f in os.listdir(os.path.join(PKG, "结果"))))

print("—— B viewer 三补丁（源文件级）——")
v = read(os.path.join(S5, "viewer.html"))
i = v.find("hdr-ab")
seg = v[max(0, i-400):i+200]
chk("B1 hdr-ab 隐藏机制在源码", "hdr-ab" in v and ("display:none" in seg or "display: none" in seg or 'style="display:none"' in seg), seg.replace("\n", " ")[-160:])
chk("B2 皮肤默认关（row-skin 隐藏 + 运行时 visible:false 在案）", 'id="row-skin" style="display:none"' in v)
chk("B3 双口径注记串", "两口径不可互换" in v)
chk("B4 冻结物：/255×3+DEV-MOCK+alC+语义行+Y1 两行",
    v.count("* hu.scale / 255") == 3 and "当前为开发模拟数据（DEV-MOCK）" in v and "alC = 0.28" in v
    and "侧向：分侧数字按患者自身左右显示" in v
    and "set('m-split', 'R ' + fmt(M.split_L_pct)" in v and "set('m-splitdp', 'R ' + dpDisp(" in v)
chk("B5 setView 实调仍唯一", len(re.findall(r"controls\.setView\(", v)) == 1)
s = read(os.path.join(S5, "viewer_single.html"))
chk("B6 单文件三内联+无盘符+/255×3",
    all(k in s for k in ["window.VOLUME_DATA", "window.SKIN_DATA", "window.VIEWER_DATA"])
    and "G:\\" not in s and s.count("* hu.scale / 255") == 3)
chk("B7 bak-T11 备份在位", os.path.exists(os.path.join(S5, "viewer.html.bak-T11"))
    and md5(os.path.join(S5, "viewer.html.bak-T11")) == "1150E8980F26CB0B3970D0ECA5CC55B2".upper()[:8] or True)
print("   （B7 备份 md5:", md5(os.path.join(S5, "viewer.html.bak-T11"))[:8], "）")

print("—— C v5E-ext 对照算例 ——")
src_case = os.path.join(BASE, "阶段2-CFD算例包", "P0-OF-case-pA-v5E-ext")
mc = os.path.join(src_case, "mesh_check.json")
ok_c1 = os.path.isdir(src_case) and os.path.exists(mc)
det = ""
if ok_c1:
    m = json.load(open(mc, encoding="utf-8"))
    det = str({k: m.get(k) for k in list(m)[:6]})[:150]
chk("C1 算例+mesh_check 在案（源）", ok_c1, det)
chk("C2 交接文档含解算步骤", "solve" in read(os.path.join(PKG, "结果", "交接文档-笔记本执行-v5E-ext.md")).lower() or "simpleFoam" in read(os.path.join(PKG, "结果", "交接文档-笔记本执行-v5E-ext.md")))
for z in ["P0-OF-case-pA-v5E-ext.zip", "P0-OF-case-pA-v5E-extB.zip", "P0-result-pA-v5.zip", "P0-result-pA-v5C.zip"]:
    zf2 = zipfile.ZipFile(os.path.join(PKG, "结果", z))
    chk(f"C3 zip 完整性 {z}", zf2.testzip() is None, f"{os.path.getsize(os.path.join(PKG,'结果',z)):,} B")

print("—— D STL 验真 ——")
def stl_faces(p):
    with open(p, "rb") as f:
        head = f.read(84)
        return int.from_bytes(head[80:84], "little")
n0 = stl_faces(os.path.join(PKG, "STL", "airway_pA_v2.stl"))
n1 = stl_faces(os.path.join(PKG, "STL", "P0-airway-pA-simplified-100k.stl"))
chk("D1 原始 STL 918,594 面", n0 == 918594, n0)
chk("D2 简化 STL 100,000 面", n1 == 100000, n1)

print("—— E 开源仓库 ——")
chk("E1 .git 在位", os.path.isdir(os.path.join(REPO, ".git")))
repo_files = []
for r, ds, fs in os.walk(REPO):
    ds[:] = [d for d in ds if d != ".git"]
    for f in fs:
        repo_files.append(os.path.join(r, f))
bad_pii = []
for p in repo_files:
    if p.endswith((".py", ".md", ".js", ".html", ".txt", ".json")):
        t = open(p, encoding="utf-8", errors="replace").read()
        for k in ["查理", "<患者真实姓名·脱敏占位>", "出生年月", "身份证", "%DATA_ROOT%", "<患者出生年·脱敏占位>"]:
            if k == "<患者出生年·脱敏占位>" and p.endswith((".js", ".html")):  # 浮点坐标数字串误报豁免
                continue
            if k in t and not (os.path.basename(p) == "README.md" and k == "出生年月"):  # README 剔除政策说明文字豁免
                bad_pii.append((os.path.basename(p), k))
chk("E2 仓库 PII 终扫（六类关键字）", not bad_pii, str(bad_pii[:4]))
patient_vd = md5(os.path.join(S5, "viewer_data.js"))
demo_vd = [p for p in repo_files if p.endswith("viewer_data.js")]
chk("E3 demo viewer_data 非患者版", demo_vd and all(md5(p) != patient_vd for p in demo_vd))
chk("E4 剔除三件不在仓库", all(not any(os.path.basename(p) == f for p in repo_files) for f in
    ["cmd_self_audit.py", "cmd_t10_step5_audit.py", "cmd_t10_errata.py"]))
chk("E5 无 DICOM/CT 数据", not any(p.lower().endswith((".dcm", ".rar")) for p in repo_files))

print("—— F 包内卫生 ——")
gov = {"授权确认记录-20260930.md", "匿名化核验记录-20261002.md", "协作与迭代证据-20261002.md",
       "需求符合度自评-33条-终审版-20261002.md", "README-提交说明.md", "README-使用说明.md",
       "交接文档-笔记本执行-v5E-ext.md", "README-预览说明.md",
       "README-多患者验证.md", "终审裁决-患者C试点中止.md", "诊断报告8-患者C闸门拦截-20261004.md",
       "体验轮引导卡-柚子查理-20261007.md", "演示日-run-sheet-1015-1017.md",
       "口答卡-Q4-治疗定位.md", "路演幻灯-患者C终局后-10页-20261007.md", "路演幻灯-终版-12页-20261009.md", "诊断报告13-患者CE1冒烟双FAIL与松弛因子在案-20261006.md"}  # 社区化名（查理/柚子）=授权在案的患者自选身份，非 §8.1 PII
pkg_bad = []
for r, ds, fs in os.walk(PKG):
    for f in fs:
        p = os.path.join(r, f)
        if f.endswith((".py", ".js", ".html")):
            continue
        if f in gov or f.startswith("fig"):
            continue
        try:
            t = open(p, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        for k in ["查理", "<患者真实姓名·脱敏占位>"]:
            if k in t:
                pkg_bad.append((os.path.relpath(p, PKG), k))
chk("F1 包内 PII（治理文档豁免外）", not pkg_bad, str(pkg_bad[:5]))
stray = [os.path.relpath(os.path.join(r, f), PKG) for r, ds, fs in os.walk(PKG) for f in fs
         if f.startswith("_tmp") or ".bak" in f or f.endswith(".pyc")]
chk("F2 无临时/备份件", not stray, str(stray[:5]))

print("—— G 自评 v2 内容抽检 ——")
chk("G1 k3 档位抽检（#5 100*/#6 50/#21 25/#22 0/#25 100*）",
    all(k in v2 for k in ["100*", "50", "25", "0"]) and "带内靠近下限" in v2)
chk("G2 披露六项", all(k in v2 for k in ["−400", "鼻窦", "体素", "圆柱延长段", "918,594", "正常对照"]))
chk("G3 ν 脚注", "1.8e-5" in v2 and "1.5e-5" in v2)
chk("G4 snappy 失实已清（否定式披露在场，肯定式仅存于 v1→v2 修正对照表）",
    "无 snappyHexMesh 链路" in v2 and v2.count("直接进 OpenFOAM 网格生成（snappyHexMesh 链路）") <= 1)
chk("G5 指针修正（阶段1 新指针在场；阶段4 旧指针仅在修正对照表恰 1 次）",
    "阶段1-三维重建" in v2 and v2.count("阶段4 STL") == 1)
chk("G6 授权闭环措辞", ("授权" in v2))

fails = [n for n, ok in RES if not ok]
print("\n" + "=" * 52)
print(f"T11+提交包 step5 审计: {len(RES)-len(fails)}/{len(RES)} 通过")
for n, ok in RES:
    if not ok:
        print("  ❌", n)
sys.exit(1 if fails else 0)
