# -*- coding: utf-8 -*-
"""单文件内联终验（FND-1 闭环）"""
D = r"G:\程序开发\qidicode\qidicode-portable-windows-x64\qidicode-portable\contest3_workspace\pipeline\out\step5"
s = open(D + r"\viewer_single.html", encoding="utf-8").read()
checks = {
    "window.VOLUME_DATA 内联": "window.VOLUME_DATA" in s,
    "hu_map 字段内联": '"hu_map"' in s,
    "window_presets 内联": '"window_presets"' in s,
    "缩略图 b64 内联": '"thumbs"' in s or "iVBOR" in s,
    "占位标签残留 = 0": s.count('<script src="volume_data.js"') == 0 and s.count('<script src="viewer_data.js"') == 0,
    "无盘符路径残留": ("G:" + chr(92)) not in s,
    "FND-2 HU÷255 修复在场（3处）": open(D + r"\viewer.html", encoding="utf-8").read().count("hu.scale / 255") == 3,
    "免责条在场": "概念验证 · 非医疗器械" in s,
}
allok = all(checks.values())
for k, v in checks.items():
    print(("✅" if v else "❌"), k)
print("终验:", "全部通过 ✅" if allok else "存在失败 ❌")
