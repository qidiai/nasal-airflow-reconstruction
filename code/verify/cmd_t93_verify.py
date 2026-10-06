# -*- coding: utf-8 -*-
"""T9-3 幽灵alpha终态核验（共享文件夹当前版）"""
import os

SHARE = r"%DATA_ROOT%\项目\P0-鼻塞设计工具\阶段5-交互查看器"
WORK = r"%QIDI_WORKSPACE%\contest3_workspace\pipeline\out\step5"

v = open(os.path.join(SHARE, "viewer.html"), encoding="utf-8").read()
w = open(os.path.join(WORK, "viewer.html"), encoding="utf-8").read()
s = open(os.path.join(SHARE, "viewer_single.html"), encoding="utf-8").read()

print("=== T9-3 幽灵alpha 终态核验 ===")
print("SKIN_GHOST_RATIO 常量在场:", "SKIN_GHOST_RATIO" in v or "uGhostRatio" in v)
print("幽灵alpha注入(mix+smoothstep 0/0.8):",
      ("mix(1.0, uGhostRatio, smoothstep(0.0,0.8" in v) or ("uGhostRatio, smoothstep(0.0, 0.8" in v) or ("uGhostRatio, smoothstep(0.0,0.8" in v))
print("SKIN_FREE_OP=0.45:", "0.45" in v)
print("共享与工作区同步:", len(v.encode("utf-8")), "vs", len(w.encode("utf-8")),
      "| 相同" if len(v) == len(w) else "漂移 ⚠️")
print()
print("单文件:", len(s.encode("utf-8")), "B | 含 uGhostRatio:", "uGhostRatio" in s,
      "| 无G盘符:", ("G:" + chr(92)) not in s)
