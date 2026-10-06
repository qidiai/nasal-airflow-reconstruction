# -*- coding: utf-8 -*-
"""修复 fix_lf.py 的误伤：把 newline="<真换行>") 还原为 newline="\n")"""
F = r"%QIDI_WORKSPACE%\contest3_workspace\pipeline\step2_make_ofcase.py"
t = open(F, encoding="utf-8").read()
broken = 'newline="' + '\n")'          # 误伤形态：串内含真实换行
fixed = 'newline="' + chr(92) + 'n")'  # 正确形态：\n 为两个字符（反斜杠+n）
n = t.count(broken)
t2 = t.replace(broken, fixed)
open(F, "w", encoding="utf-8", newline="\n").write(t2)
print("修复处数:", n)
