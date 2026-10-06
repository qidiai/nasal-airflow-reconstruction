# -*- coding: utf-8 -*-
"""T9-1 受理核验（第二批）：skin_data.js 路径剥离防泄漏预演 + 单文件预算终核"""
import os, json

BASE = r"%QIDI_WORKSPACE%\contest3_workspace\pipeline\out\step5"
S7 = r"%QIDI_WORKSPACE%\contest3_workspace\pipeline\out\step7"

# ===== T0 复演：皮肤数据路径剥离预演（build 脚本管不到，这里先把"进单文件前"的产物算出） =====
sd = open(os.path.join(S7, "skin_data.js"), encoding="utf-8").read()
n_paths = sum(1 for l in sd.splitlines() if l.strip().startswith("//") and (":" + chr(92) in l or l.count(chr(92)) >= 3))
stripped = chr(10).join(l for l in sd.splitlines()
                        if not (l.strip().startswith("//") and (":" + chr(92) in l or l.count(chr(92)) >= 3))).lstrip(chr(10))
print("路径注释行数（进单文件前将剥离）:", n_paths)
print("剥离后体积:", len(stripped.encode("utf-8")), "B")

# ===== 单文件预算（4.1万→合并后体积） =====
v = open(os.path.join(BASE, "viewer.html"), encoding="utf-8").read()
d1 = open(os.path.join(BASE, "viewer_data.js"), encoding="utf-8").read()
d2 = open(os.path.join(BASE, "volume_data.js"), encoding="utf-8").read()
bond = len(v.encode()) - 2 * len('<script src="viewer_data.js"></script>') - len('<script src="volume_data.js"></script>')
est = len(v.encode()) + len(d1.encode()) + len(d2.encode()) + len(stripped.encode()) + 4000
print(f"单文件合并后预估: {est:,} B = {est/1e6:.2f} MB（上限 16MB）")

# ===== 气道网格 vs 皮肤壳 重合带（双壁渲染预判输入：用 step7 自带 near_airway 数据） =====
vc = os.path.join(S7, "skin_qc.json")
q = json.load(open(vc, encoding="utf-8"))
nad = q.get("near_airway_diagnostic", q.get("near_airway"))
print()
print("near_airway诊断:", json.dumps(nad, ensure_ascii=False)[:300] if nad else "未找到")
