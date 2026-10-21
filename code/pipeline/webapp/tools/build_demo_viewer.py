# -*- coding: utf-8 -*-
"""build_demo_viewer.py —— demo 查看器重建（模板 + demo 数据 → 自包含 demo/viewer.html）

    python webapp/tools/build_demo_viewer.py

口径与 build_single_file.py 一致（guard / strip_path_comments 直接 import，不复制一份），
差异仅三处，均因 demo 是合成病例：

  1) viewer_data.js 内联（同 build_single_file 的做法）；
  2) volume_data.js / skin_data.js 两个外链标签整条移除：demo 目录没有这两份数据
     （合成病例无 CT 体数据、无皮肤壳）。留着外链只会让 /static/demo/ 两个 404
     （控制台红字）而拿不到任何东西——模板自带 DEV-MOCK 兜底，且 null 路径有守卫：
     `var VOL = window.VOLUME_DATA || null` → initCT() 首行 return；`window.SKIN_DATA || null`。
  3) 末尾注入 URL 参数兼容层（工作台 iframe 是 /static/demo/viewer.html?breath=1&ct=0，
     模板本身不解析这两个参数——旧 demo 页解析，故保留同一契约）。

模板文件本身零改动。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_single_file as bsf  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
WEBAPP = os.path.dirname(HERE)
TEMPLATE = os.path.join(WEBAPP, "viewer_template", "viewer.html")
DATA = os.path.join(WEBAPP, "demo", "viewer_data.js")
OUT = os.path.join(WEBAPP, "demo", "viewer.html")

TAG_DATA = '<script src="viewer_data.js"></script>'
TAG_VOL = '<script src="volume_data.js"></script>'
TAG_SKIN = '<script src="skin_data.js"></script>'

COMPAT = """<script>
/* demo 页 URL 参数兼容（工作台 iframe：/static/demo/viewer.html?breath=1&ct=0）——
   与旧 demo 页同一契约：breath=1 开呼吸动画；ct=0 关 CT 体绘制（保帧率）。
   模板默认已是「呼吸开 / CT 关」，故常态下本段幂等空转，仅在状态被改动时校正。 */
(function () {
  try {
    var qp = new URLSearchParams(location.search), applied = [];
    var b = document.getElementById('cb-breath-anim');
    if (qp.get('breath') === '1' && b && !b.disabled && !b.checked) {
      b.checked = true; b.dispatchEvent(new Event('change')); applied.push('breath=1');
    }
    var c = document.getElementById('cb-ct');
    if (qp.get('ct') === '0' && c && c.checked) {
      c.checked = false; c.dispatchEvent(new Event('change')); applied.push('ct=0');
    }
    if (applied.length) { console.info('[viewer] URL params applied: ' + applied.join(' ')); }
  } catch (e) { console.warn('[viewer] URL param parse:', e); }
})();
</script>
"""


def main():
    for p in (TEMPLATE, DATA):
        if not os.path.isfile(p):
            print("ERROR: 文件不存在: %s" % p)
            return 1
    with open(TEMPLATE, "r", encoding="utf-8") as f:
        html = f.read()
    with open(DATA, "r", encoding="utf-8") as f:
        data = f.read()

    if TAG_DATA not in html:
        print("ERROR: 模板中未找到占位标签 %r" % TAG_DATA)
        return 2
    if not bsf.guard(data, "demo/viewer_data.js"):
        return 3
    data = bsf.strip_path_comments(data)

    single = html.replace(TAG_DATA, "<script>\n" + data + "\n</script>", 1)
    single = single.replace("var dataSource = 'viewer_data.js';",
                            "var dataSource = '内联数据包（demo/viewer_data.js 构建期内联）';", 1)

    for tag in (TAG_VOL, TAG_SKIN):
        if tag not in single:
            print("ERROR: 模板中未找到占位标签 %r（模板结构已变，先核对再改本脚本）" % tag)
            return 4
        single = single.replace(tag, "", 1)

    if "</body>" not in single:
        print("ERROR: 模板缺 </body>，无法注入 URL 参数兼容层")
        return 5
    single = single.replace("</body>", COMPAT + "</body>", 1)

    with open(OUT, "w", encoding="utf-8", newline="") as f:
        f.write(single)

    print("OK: 已生成 %s" % OUT)
    print("    demo/viewer.html = %d bytes (模板 %d + 数据 %d)"
          % (len(single.encode("utf-8")), len(html.encode("utf-8")), len(data.encode("utf-8"))))
    print("    外链残留检查: viewer_data.js=%s volume_data.js=%s skin_data.js=%s"
          % (TAG_DATA in single, TAG_VOL in single, TAG_SKIN in single))
    return 0


if __name__ == "__main__":
    sys.exit(main())
