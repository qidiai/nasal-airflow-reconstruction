#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_single_file.py — 把 viewer_data.js / volume_data.js / skin_data.js 内联进 viewer.html，生成 viewer_single.html。

用法:
    python build_single_file.py                         # 默认: 本脚本目录下
    python build_single_file.py <html> <data.js> <out>  # 显式指定路径（volume/skin 取同目录）

实现（k3 审计 FND-1 修复版）:
    纯文本替换三个占位标签：
      '<script src="viewer_data.js"></script>'   -> '<script>' + viewer_data.js 全文 + '</script>'
      '<script src="volume_data.js"></script>'   -> '<script>' + volume_data.js 全文 + '</script>'
      '<script src="skin_data.js"></script>'     -> '<script>' + skin_data.js 全文 + '</script>'  （T9-2 补：漏掉即离线单文件静默丢皮肤层）
    三个数据文件均做：
      - '</script' / '<!--' 注入防护（命中即拒绝生成）
      - 头部源码路径注释剥离（避免外发泄露作者目录结构与项目路径）
"""
import os
import sys

TAG = '<script src="viewer_data.js"></script>'
TAG2 = '<script src="volume_data.js"></script>'
TAG3 = '<script src="skin_data.js"></script>'


def strip_path_comments(data):
    """剥离 '// ...' 且含盘符路径（'X:\\'）或 >=3 个反斜杠的注释行（审计D1）。"""
    cleaned_lines = []
    for _ln in data.splitlines():
        _s = _ln.strip()
        if _s.startswith('//') and (':' + chr(92) in _s or _s.count(chr(92)) >= 3):
            continue
        cleaned_lines.append(_ln)
    return '\n'.join(cleaned_lines).lstrip('\n')


def guard(data, label):
    if '</script' in data.lower():
        print('ERROR: %s 含 "</script"，直接内联会截断脚本，拒绝生成' % label)
        return False
    if '<!--' in data:
        print('ERROR: %s 含 "<!--"（HTML 注释逃逸风险），拒绝生成' % label)
        return False
    return True


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    argv = sys.argv[1:]
    html_path = argv[0] if len(argv) > 0 else os.path.join(base, 'viewer.html')
    data_path = argv[1] if len(argv) > 1 else os.path.join(base, 'viewer_data.js')
    out_path = argv[2] if len(argv) > 2 else os.path.join(base, 'viewer_single.html')
    vol_path = os.path.join(base, 'volume_data.js')
    skin_path = os.path.join(base, 'skin_data.js')

    for p in (html_path, data_path):
        if not os.path.isfile(p):
            print('ERROR: 文件不存在: %s' % p)
            return 1

    with open(html_path, 'r', encoding='utf-8') as f:
        html = f.read()
    with open(data_path, 'r', encoding='utf-8') as f:
        data = f.read()

    if TAG not in html:
        print('ERROR: viewer.html 中未找到占位标签 %r' % TAG)
        return 1
    if not guard(data, 'viewer_data.js'):
        return 2
    data = strip_path_comments(data)

    single = html.replace(TAG, '<script>\n' + data + '\n</script>', 1)
    # GLM复审G-6：单文件页眉如实标注数据已内联（不再是外部 viewer_data.js）
    single = single.replace("var dataSource = 'viewer_data.js';",
                            "var dataSource = '已内联（本文件自带数据）';", 1)

    # k3 审计 FND-1：内联 volume_data.js（CT 体渲染层）——单文件演示不得静默丢失 v3 功能
    if TAG2 in single:
        if os.path.isfile(vol_path):
            with open(vol_path, 'r', encoding='utf-8') as f:
                vdata = f.read()
            if not guard(vdata, 'volume_data.js'):
                return 4
            vdata = strip_path_comments(vdata)
            single = single.replace(TAG2, '<script>\n' + vdata + '\n</script>', 1)
            print('OK: volume_data.js 已内联（CT 体渲染层可用）')
        else:
            print('WARN: 未找到 volume_data.js，单文件版将不含 CT 层（V0 门控会隐藏该卡片）')

    # T9-2：内联 skin_data.js（头部外形皮肤壳）——不内联则离线单文件残留外部引用、皮肤层静默丢失
    if TAG3 in single:
        if os.path.isfile(skin_path):
            with open(skin_path, 'r', encoding='utf-8') as f:
                sdata = f.read()
            if not guard(sdata, 'skin_data.js'):
                return 5
            sdata = strip_path_comments(sdata)
            single = single.replace(TAG3, '<script>\n' + sdata + '\n</script>', 1)
            print('OK: skin_data.js 已内联（头部外形皮肤壳层可用）')
        else:
            print('WARN: 未找到 skin_data.js，单文件版将不含皮肤壳层（T9-2 门控会隐藏该图层）')

    with open(out_path, 'w', encoding='utf-8', newline='') as f:
        f.write(single)

    print('OK: 已生成 %s' % out_path)
    print('    viewer_single.html = %d bytes (viewer.html %d + viewer_data.js %d)'
          % (len(single.encode('utf-8')), len(html.encode('utf-8')), len(data.encode('utf-8'))))
    return 0


if __name__ == '__main__':
    sys.exit(main())
