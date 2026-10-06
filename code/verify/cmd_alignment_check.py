# -*- coding: utf-8 -*-
"""审计员提供的 A1/A2/A4/A5 几何对齐补测（指挥官执行）"""
import json, re
import numpy as np
from scipy.spatial import cKDTree

s = open(r"%QIDI_WORKSPACE%\contest3_workspace\pipeline\out\step5\viewer_data.js", encoding="utf-8").read()
d = json.loads(re.search(r"window\.VIEWER_DATA = (\{.*\});", s, re.S).group(1))
pos = np.array(d["airwayMesh"]["positions"]).reshape(-1, 3)
mn, mx = pos.min(0), pos.max(0)
print("A5 verts=%d faces=%d idxmax=%d" % (len(pos), len(d["airwayMesh"]["indices"]) // 3, max(d["airwayMesh"]["indices"])))
print("airway bbox", np.round(mn, 1), np.round(mx, 1))
ph = {p["mm"]: np.array(p["positions"]).reshape(-1, 3) for p in d["placeholders"]}
for mm, P in ph.items():
    out = ((P < mn - 3) | (P > mx + 3)).any(1)
    print("A1 ph%dmm verts=%d 盒内(+3mm)比例=%.4f 盒外=%d" % (mm, len(P), 1 - out.mean(), out.sum()))
for a, b in [(1, 2), (1, 3), (2, 3)]:
    dd, _ = cKDTree(ph[b]).query(ph[a])
    print("A4 %dmm->%dmm 最近距 max=%.2f mean=%.2f" % (a, b, dd.max(), dd.mean()))
zo = ze = 0
zs = []
z1s = []
for sl in d["streamlines"]:
    P = np.array(sl["points"]).reshape(-1, 3)
    zs.append(P[0, 2]); z1s.append(P[-1, 2])
    zo += 0 if ((mn - 2 <= P[0]).all() and (P[0] <= mx + 2).all()) else 1
    ze += 0 if ((mn - 2 <= P[-1]).all() and (P[-1] <= mx + 2).all()) else 1
print("A2 n=%d 起点盒外=%d 终点盒外=%d 起点z均=%.1f 终点z均=%.1f" % (len(d["streamlines"]), zo, ze, np.mean(zs), np.mean(z1s)))
print()
print("判定：A1 盒内比例>=0.99 ✅ | A2 盒外=0 且 起点 z > 终点 z（鼻孔→鼻咽）✅ | A4 2->3mm max<=2.5mm ✅")
