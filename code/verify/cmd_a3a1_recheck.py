# -*- coding: utf-8 -*-
"""A3/A1 失败项定性复核"""
import os, re, hashlib

SHARE = r"%DATA_ROOT%\项目\P0-鼻塞设计工具\阶段5-交互查看器"
WSRC = r"G:\程序开发\qidicode\qidicode-portable-windows-x64\qidicode-portable\contest3_workspace"

v = open(os.path.join(SHARE, "viewer.html"), encoding="utf-8").read()
n_raw = v.count("推荐")
n_neg = v.count("非推荐")
print("A3 定性: 推荐 出现 %d 次, 其中 非推荐(否定式免责) %d 次" % (n_raw, n_neg))
ok3 = (n_raw == n_neg)
print("  判定:", "全部为否定式免责内容（dP_note 契约原文），合规 ✅" if ok3 else "存在独立出现 ⚠️")
for m in re.finditer("推荐", v):
    ctx = v[max(0, m.start() - 14):m.end() + 4].replace("\n", " ")
    print("   语境:", repr(ctx))

p_share = os.path.join(SHARE, "README-使用说明.md")
p_src = os.path.join(WSRC, "查看器使用说明.md")
h1 = hashlib.md5(open(p_share, "rb").read()).hexdigest()
h2 = hashlib.md5(open(p_src, "rb").read()).hexdigest()
same = (h1 == h2)
print()
print("A1 定性: README 共享哈希 %s vs workspace源 %s → %s" % (h1[:8], h2[:8], "一致 ✅" if same else "不一致 ❌"))
