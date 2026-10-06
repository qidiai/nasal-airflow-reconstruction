# -*- coding: utf-8 -*-
"""指挥官独立核验 T2/T3 交付物"""
import os, re, json

D = r"%QIDI_WORKSPACE%\contest3_workspace\pipeline\out\step5"

print("===== 文件清单 =====")
for f in sorted(os.listdir(D)):
    p = os.path.join(D, f)
    if os.path.isfile(p):
        print(f"  {f:30s} {os.path.getsize(p):>10,} B")

print()
print("===== viewer_data.js 结构核验（T2） =====")
txt = open(os.path.join(D, "viewer_data.js"), encoding="utf-8").read()
print("  大小:", len(txt.encode("utf-8")), "B")
print("  window.VIEWER_DATA:", "window.VIEWER_DATA" in txt)
for key in ["meta", "airwayMesh", "streamlines", "slices", "placeholders", "curve"]:
    print(f"  {key}:", f"{key}:" in txt or f"{key} :" in txt)
qc = json.load(open(os.path.join(D, "viewer_data_qc.json"), encoding="utf-8"))
print("  QC all_pass:", qc.get("all_pass"))

print()
print("===== viewer.html 核验（T3） =====")
h = open(os.path.join(D, "viewer.html"), encoding="utf-8").read()
print("  大小:", len(h.encode("utf-8")), "B")
print("  内嵌three.js特征(应用引用):", h.count("REVISION"))
print("  外链script(src=http)数:", len(re.findall(r"<script[^>]+src=.https?://", h)))
print("  禁用词:", [w for w in ["最佳", "安全余量", "治疗", "试戴", "植入体"] if w in h] or "无 ✅")
print("  免责条:", "概念验证 · 非医疗器械" in h)
print("  数据加载:", 'src="viewer_data.js"' in h)
print("  DEV-MOCK 回退:", "DEV-MOCK" in h)

print()
print("===== viewer_single.html 核验（集成产物） =====")
s = open(os.path.join(D, "viewer_single.html"), encoding="utf-8", errors="replace").read()
print("  大小:", len(s.encode("utf-8")), "B")
print("  内联数据:", "VIEWER_DATA" in s)
print("  无外链script:", len(re.findall(r"<script[^>]+src=.https?://", s)) == 0)
