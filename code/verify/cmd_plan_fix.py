# -*- coding: utf-8 -*-
"""恢复被覆盖的 T8 记录行（插回审计链段落）"""
p = r"%QIDI_WORKSPACE%\contest3_workspace\P0项目计划.md"
t = open(p, encoding="utf-8").read()
anchor = "- 审计链：step-5 v2 全量审计（1项P0：F2颜色三张皮——已修复）"
insert = (
    "- **T8 一期视觉重构（09-30深夜，患者\u201c效果差\u201d反馈驱动，k3 方案审计4项融入）**："
    "绝对HU密度分档染色（骨白/琥珀/深蓝黑三带+smoothstep\u00b150HU）+临床站暗蓝渐变背景"
    "+ambient 0.7+DLight+默认CT开+骨骼写实+角常驻\u201c非诊断影像\u201d小字+CT口播新话术"
    "——48/48静态+94/95运行时+fps 60.2；公式裁决（指挥官转写笔误\u2192按注释/验收锚定HU=100）"
    "与色带越界命名零命中定性在 T8 验收处置记录"
)
if "T8 一期视觉重构" not in t:
    t = t.replace(anchor, insert + "\n" + anchor, 1)
    open(p, "w", encoding="utf-8", newline="").write(t)
    print("T8 行已恢复插入")
else:
    print("T8 已在")
