# -*- coding: utf-8 -*-
"""README 演示纪律追加 10-12 条"""
p = r"%QIDI_WORKSPACE%\contest3_workspace\查看器使用说明.md"
t = open(p, encoding="utf-8").read()
add = (
    "10. **皮肤壳透明度随视角变化（轮廓浓/正面淡）是展示特性，不是诊断依据**；"
    "头皮\u201c薄雾幽灵\u201d不是缺皮；三条直边=CT 扫描视野截断（方法学面板已注明）\n"
    "11. **别把相机怼到三断面跟前**——推近正对断面=切面纸观感；近景一律斜 3/4 视角\n"
    "12. **CT 层亮度定版 uKappa=0.055（薄雾叠加不抢流线）**；屏幕偏暗时切含气窗预设替代调参\n"
)
anchor = "9. **A/B 对比角标带\u201c线性外推\u201d字样，勿拆解**"
if anchor not in t:
    anchor2 = "9. **A/B 对比角标带\"线性外推\"字样，勿拆解**"
    if anchor2 not in t:
        raise SystemExit("锚点未找到，中止")
    t = t.replace(anchor2, anchor2 + "\n" + add.rstrip(), 1)
else:
    t = t.replace(anchor, anchor + "\n" + add.rstrip(), 1)
t = t.replace("演示纪律（三轮审计裁定汇总", "演示纪律（多轮审计裁定汇总")
open(p, "w", encoding="utf-8", newline="").write(t)
ok = all(s in t for s in ["皮肤壳透明度", "切面纸观感", "uKappa=0.055"])
print("追加 10-12 三条:", ok)
