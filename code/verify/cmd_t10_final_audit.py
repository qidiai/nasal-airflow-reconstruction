# -*- coding: utf-8 -*-
"""T10 完工态审计（常驻回归工具）——完工态断言 + 双份同步 + 记录在案检查"""
import sys, os, re, json, hashlib
sys.stdout.reconfigure(encoding="utf-8")
PROJ = r"%DATA_ROOT%\项目"
S5 = os.path.join(PROJ, "P0-鼻塞设计工具", "阶段5-交互查看器")
T10 = os.path.join(S5, "升级施工-T10")
PIPE = r"%QIDI_WORKSPACE%\contest3_workspace\pipeline"
WSOUT = os.path.join(PIPE, "out", "step5")
RES = []
def chk(n, ok, d=""):
    RES.append((n, ok, d)); print(("✅" if ok else "❌"), n, ("| " + d) if d else "")
def md5(p): return hashlib.md5(open(p, "rb").read()).hexdigest().upper()

print("—— A 双份同步（共享=事实源 → 工作区回灌态）——")
for f in ["viewer.html", "viewer_single.html", "README-使用说明.md", "viewer_data.js", "volume_data.js", "skin_data.js", "build_single_file.py"]:
    p1, p2 = os.path.join(S5, f), os.path.join(WSOUT, f)
    ok = os.path.isfile(p1) and os.path.isfile(p2) and md5(p1) == md5(p2)
    chk("A0 同步:" + f, ok, md5(p1)[:8] if os.path.isfile(p1) else "缺")

print("—— B viewer.html 完工态 ——")
v = open(os.path.join(S5, "viewer.html"), encoding="utf-8").read()
chk("B1 Y1 m-split 翻转串", "set('m-split', 'R ' + fmt(M.split_L_pct) + '% / L ' + fmt(M.split_R_pct) + '%');" in v)
chk("B2 Y1 m-splitdp 翻转串", "set('m-splitdp', 'R ' + dpDisp(VOL.metrics_deltaP.dP_L_Pa) + ' / L ' + dpDisp(VOL.metrics_deltaP.dP_R_Pa) + ' Pa');" in v)
chk("B3 旧式未翻转串绝迹", v.count("set('m-split', 'L ' + fmt(M.split_L_pct)") == 0 and v.count("set('m-splitdp', 'L ' + dpDisp(") == 0)
chk("B4 语义行冻结串", "侧向：分侧数字按患者自身左右显示（面对患者判读，患者左=画面右）" in v and "「患者左/患者右」按钮" in v)
chk("B5 F1 Line2 三件套已内联", all(v.count(k) > 0 for k in ["LineSegments2", "LineSegmentsGeometry", "LineMaterial"]))
chk("B6 setView 实调仅初始取景", len(re.findall(r"controls\.setView\(", v)) == 1 and "flyTo" in v)
chk("B7 Y3 按钮", 'id="btn-side-l"' in v and 'id="btn-side-r"' in v)
chk("B8 勘误2号 dpDisp", "return (n * flowK).toFixed(2);" in v and "String(v) : (n * flowK)" not in v)
chk("B9 冻结物: /255×3 + DEV-MOCK + alC=0.28 + 勘误1号正确性", v.count("* hu.scale / 255") == 3
    and "当前为开发模拟数据（DEV-MOCK）" in v and "alC = 0.28" in v)
chk("B10 hu_map 滑杆量程耦合（内容定位）", v.count("hu.offset + hu.scale") >= 2)
chk("B11 viewer 硬禁词=0", not [w for w in ["植入体", "最佳", "安全余量", "疗效", "诊断级", "医院级", "媲美临床"] if w in v])

print("—— C 单文件 ——")
sp = os.path.join(S5, "viewer_single.html")
s = open(sp, encoding="utf-8").read()
chk("C1 三内联", all(k in s for k in ["window.VOLUME_DATA", "window.SKIN_DATA", "window.VIEWER_DATA"]))
chk("C2 无盘符", ("G:" + chr(92)) not in s)
chk("C3 字节数≤16,200,499", os.path.getsize(sp) <= 16_200_499, f"{os.path.getsize(sp):,} B")
chk("C4 /255×3 同步", s.count("* hu.scale / 255") == 3)

print("—— D README 完工态 ——")
r = open(os.path.join(S5, "README-使用说明.md"), encoding="utf-8").read()
chk("D1 演示纪律#1 冻结串", "3D 画面内不挂左右文字标签" in r and "R 51.9% / L 48.1%" in r)
chk("D2 分侧口径条", "51.9/48.1 为等压法（Run-B）实测通气分配" in r and "13.99/21.30 为 Run-A 分侧压降" in r)
chk("D3 禁词（植入体=0，治疗仅否定语境）", "植入体" not in r and not re.search(r"(?<!不构成)治疗建议", r) and "疗效" not in r)

print("—— E 记录与凭据在案 ——")
g = open(os.path.join(T10, "out_gate", "gate_final_20261002.txt"), encoding="utf-8").read()
chk("E1 门禁终验 EXIT=0", "EXIT=0" in g and g.count("[PASS]") == 8)
j = json.load(open(os.path.join(T10, "out_f3", "six_boards.json"), encoding="utf-8"))
chk("E2 六板 v3 all_gates_pass=true", j.get("all_gates_pass") is True, j.get("generated"))
chk("E3 看板② v3 报告在案", os.path.isfile(os.path.join(T10, "看板2-F3Y1施工报告-v3.md")))
chk("E4 放行令/鉴定/勘误记录在案", all(os.path.isfile(p) for p in [
    os.path.join(S5, "放行令-看板①-F3Y1-20261002.md"),
    os.path.join(T10, "编码手能力鉴定-Ling-20261002.md"),
    os.path.join(PROJ, "勘误记录-侧向口径-20261001.md")]))
chk("E5 flip_points 档案（7 条）", isinstance(j.get("board6_streamline_shell_clearance", {}).get("flip_points"), list)
    and len(j["board6_streamline_shell_clearance"]["flip_points"]) == 7)
chk("E6 鼻窦豁免在案", j["shells"]["airwaySinus"].get("exempted") is True)

print("—— F 工单与门禁 ——")
p12 = os.path.join(PIPE, "方案-T10施工方案-v1.2.1.md")
t12 = open(p12, encoding="utf-8").read()
chk("F1 v1.2.1 双份一致", md5(p12) == md5(os.path.join(PROJ, "方案-T10施工方案-v1.2.1.md")))
chk("F2 勘误1号（alC）在工单", "alC = 0.28" in t12 and t12.count("alphaBand = 0.28") == 1)  # 旧串仅允许在勘误注记引用中出现恰 1 次
src_gate = open(os.path.join(PIPE, "cmd_t10_lr_chain2.py"), encoding="utf-8").read()
chk("F3 门禁 8 断言", len(re.findall(r"(?m)^check\(", src_gate)) == 8)
chk("F4 pipeline 平滑版+备份在案", os.path.isfile(os.path.join(PIPE, "step5_export_viewer_data.py"))
    and os.path.isfile(os.path.join(PIPE, "step5_export_viewer_data.py.bak-T10")))

fails = [x for x in RES if not x[1]]
print("\n" + "=" * 52)
print(f"T10 完工态审计: {len(RES)-len(fails)}/{len(RES)} 通过")
for n, ok, d in fails:
    print("  ❌", n, "|", d)
sys.exit(1 if fails else 0)
