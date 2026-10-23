#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T56：可选数据层（CT 体渲染 / 皮肤壳）缺位 + 内联 favicon 的防回归。

钉住的契约：
  1) 舞台化落地时按实体文件裁剪 <script src>：病例目录里没有 volume_data.js /
     skin_data.js 就不留标签 —— 浏览器不会请求不存在的文件（控制台无 404 红字）。
  2) 单文件构建同理：内联不了就换成说明注释，不留悬空引用（此前 warn 后标签照留，
     单文件页因此对 /static/cases/<cid>/volume_data.js 发请求 → 404）。
  3) /static/cases/<cid>/{volume_data.js,skin_data.js} 缺位返回 204（不是 404），
     且新路由不得截走同级真实静态文件（viewer_single.html 仍 200）。
  4) 每个整页文档都带内联 favicon：没有 <link rel="icon"> 时浏览器实测会探测
     /favicon.ico → 404（headless Edge 复现）。
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.dirname(HERE)
if PIPELINE not in sys.path:
    sys.path.insert(0, PIPELINE)

import server  # noqa: E402

WEBAPP = os.path.join(PIPELINE, "webapp")
TEMPLATE = os.path.join(WEBAPP, "viewer_template", "viewer.html")
BUILD_SINGLE = os.path.join(WEBAPP, "tools", "build_single_file.py")
CHECK_17 = os.path.join(WEBAPP, "tools", "_check_17features.py")

VOL_STUB = "window.VOLUME_DATA = {meta:{source:'stub'}};\n"
SKIN_STUB = "window.SKIN_DATA = {positions:[], indices:[]};\n"
VIEWER_STUB = ("window.VIEWER_DATA = {meta:{title:'t',caseBaseline:'b',units:'mm',"
               "metrics:{}},airwayMesh:{positions:[],indices:[]},streamlines:[],"
               "slices:[],placeholders:[],curve:{}};\n")


# ------------------------------------------------- 子进程编码自洽（T3a F1 / 根因 R-A）
def _child_env_utf8():
    """给子进程注入 UTF-8 环境，让它按 utf-8 写 stdout/stderr。

    根因（本机实测）：默认环境（GBK 控制台）下子进程 sys.stdout.encoding=gbk，
    print 中文 → GBK 字节（如 '层' = 0xb2 0xe3）→ 父进程 encoding="utf-8" 解码在
    _readerthread 抛 UnicodeDecodeError → CompletedProcess.stdout/stderr 变成 None
    → 断言里 `'x' in None` 抛 TypeError，把真失败伪装成怪错误。
    只动 env/解码兜底，被测命令 argv、timeout、capture 语义一律不变。
    """
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _write(path, text):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def _mk_web(tmp_path, with_layers=False, case_id=None):
    """临时 webapp 根（含模板），避免测试写进仓库的 webapp/cases/**。

    层文件落点（T3b F2 / 根因 R-B 夹具侧）：实现查的是 `case_web = WEBAPP_DIR/cases/<cid>`
    （server.py 的 stage_viewer_if_exported → strip_absent_layer_tags(html, case_web)），
    同一个目录也是 _optional_case_layer 路由与 build_single_file.py 的 base。旧夹具把层
    写在 **webapp 根**，那是第三个没人读的位置 ⇒ 实现侧的缺陷与夹具侧的错位互相掩盖，
    这条测试只能红。给了 case_id 就写到 cases/<cid>/（真正被查的目录）；不给则留在
    webapp 根 —— 该分支只服务于路由测试（test_optional_layer_routes_*），那组断言查的是
    cases/<cid>/ 里有没有文件，webapp 根的这两份对它完全惰性，行为逐字节不变。
    """
    web = os.path.join(str(tmp_path), "web")
    _write(os.path.join(web, "viewer_template", "viewer.html"),
           open(TEMPLATE, encoding="utf-8").read())
    if with_layers:
        layer_dir = os.path.join(web, "cases", case_id) if case_id else web
        _write(os.path.join(layer_dir, "volume_data.js"), VOL_STUB)
        _write(os.path.join(layer_dir, "skin_data.js"), SKIN_STUB)
    return web


def _mk_case(state_dir, case_id, viewer_js=VIEWER_STUB):
    out_dir = os.path.join(state_dir, "cases", case_id)
    _write(os.path.join(out_dir, "step5", "viewer_data.js"), viewer_js)
    return out_dir


def _pin_shared_layer_roots(monkeypatch, tmp_path):
    """把可选层兜底根钉进本用例的临时目录（T3d F1 / hermetic）。

    server.py:120-121 的 SHARED_STEP6/7 是 **模块级** 默认值，指向仓库真实工作树
    `code/pipeline/out/step6|7`；stage_viewer_if_exported 的部署循环
    （server.py:1356-1374）在 `out_dir/step6|7` 未命中后会回落到这两个根。
    不钉住的话，任何人真跑过 step6/7、在 out/step6 留下 volume_data.js，
    测试就会把那份**生产产物**拷进用例目录 ⇒ 结果随工作树状态漂移（假绿）。
    这里只改测试进程内的模块属性，server.py 的默认值与落点口径一字未动。
    返回 (shared6, shared7)，正例用例可在其中显式造假层文件。
    """
    shared6 = os.path.join(str(tmp_path), "shared_step6")
    shared7 = os.path.join(str(tmp_path), "shared_step7")
    monkeypatch.setattr(server, "SHARED_STEP6", shared6)
    monkeypatch.setattr(server, "SHARED_STEP7", shared7)
    return shared6, shared7


# ---------------------------------------------------------------- 1) 标签裁剪
def test_strip_absent_layer_tags_removes_only_missing(tmp_path):
    html = ('<script src="viewer_data.js"></script>\n'
            '<script src="volume_data.js"></script>\n'
            '<script src="skin_data.js"></script>\n')
    _write(os.path.join(str(tmp_path), "volume_data.js"), VOL_STUB)
    out, dropped = server.strip_absent_layer_tags(html, str(tmp_path))
    assert dropped == ["skin_data.js"], "只应剔除未部署的层，实际 %r" % (dropped,)
    assert '<script src="volume_data.js"></script>' in out, "已部署层的标签必须保留"
    assert '<script src="skin_data.js">' not in out, "未部署层的标签必须删除"
    assert '<script src="viewer_data.js"></script>' in out, "必需数据标签不得被动"


def test_strip_absent_layer_tags_keeps_everything_when_deployed(tmp_path):
    html = ('<script src="volume_data.js"></script>\n'
            '<script src="skin_data.js"></script>\n')
    _write(os.path.join(str(tmp_path), "volume_data.js"), VOL_STUB)
    _write(os.path.join(str(tmp_path), "skin_data.js"), SKIN_STUB)
    out, dropped = server.strip_absent_layer_tags(html, str(tmp_path))
    assert dropped == [], "两层都在时不应剔除任何标签，实际 %r" % (dropped,)
    assert out == html, "两层都在时必须逐字节原样返回"


# ---------------------------------------------------------------- 2) 舞台化
def test_stage_strips_absent_layers_and_logs(tmp_path, monkeypatch):
    web = _mk_web(tmp_path)
    monkeypatch.setattr(server, "WEBAPP_DIR", web)
    monkeypatch.setattr(server, "VIEWER_TEMPLATE",
                        os.path.join(web, "viewer_template", "viewer.html"))
    _pin_shared_layer_roots(monkeypatch, tmp_path)
    state = os.path.join(str(tmp_path), "state")
    out_dir = _mk_case(state, "pq1")
    cfg = server.ServerConfig(mode="m1-local", state_dir=state)
    rec = {"case_id": "pq1", "out_dir": out_dir}
    assert server.stage_viewer_if_exported(cfg, rec) is True, "有 viewer_data.js 时必须舞台化成功"

    case_web = os.path.join(web, "cases", "pq1")
    html = open(os.path.join(case_web, "viewer.html"), encoding="utf-8").read()
    single = open(os.path.join(case_web, "viewer_single.html"), encoding="utf-8").read()
    assert '<script src="volume_data.js">' not in html, "loose viewer.html 不得留 volume 标签"
    assert '<script src="skin_data.js">' not in html, "loose viewer.html 不得留 skin 标签"
    assert '<script src="viewer_data.js"></script>' in html, "viewer_data 标签必须保留"
    assert '<script src="volume_data.js">' not in single, "单文件版不得留 volume 标签"
    assert '<script src="skin_data.js">' not in single, "单文件版不得留 skin 标签"
    prog = open(os.path.join(out_dir, "manifest-progress.json"), encoding="utf-8").read()
    assert "已移除其 <script> 引用" in prog, "剔除动作必须进进度日志（best-effort 不得静默）"


def test_stage_keeps_tags_when_layers_deployed(tmp_path, monkeypatch):
    web = _mk_web(tmp_path, with_layers=True, case_id="pq2")
    monkeypatch.setattr(server, "WEBAPP_DIR", web)
    monkeypatch.setattr(server, "VIEWER_TEMPLATE",
                        os.path.join(web, "viewer_template", "viewer.html"))
    _pin_shared_layer_roots(monkeypatch, tmp_path)
    state = os.path.join(str(tmp_path), "state")
    out_dir = _mk_case(state, "pq2")
    cfg = server.ServerConfig(mode="m1-local", state_dir=state)
    server.stage_viewer_if_exported(cfg, {"case_id": "pq2", "out_dir": out_dir})
    html = open(os.path.join(web, "cases", "pq2", "viewer.html"), encoding="utf-8").read()
    assert '<script src="volume_data.js"></script>' in html, "已部署的层必须保留标签（行为不得回退）"
    assert '<script src="skin_data.js"></script>' in html, "已部署的层必须保留标签（行为不得回退）"


def test_stage_no_layer_files_when_absent_everywhere(tmp_path, monkeypatch):
    """防回归（T3d F1）：out_dir 与两个兜底根都没有层文件时，裁剪逻辑必须仍然生效。

    断言的是"什么都没部署"，而不是"没部署因为工作树恰好干净"——兜底根已钉进
    tmp_path，本用例对仓库 code/pipeline/out/step6|7 的存在与否免疫。
    """
    web = _mk_web(tmp_path)
    monkeypatch.setattr(server, "WEBAPP_DIR", web)
    monkeypatch.setattr(server, "VIEWER_TEMPLATE",
                        os.path.join(web, "viewer_template", "viewer.html"))
    shared6, shared7 = _pin_shared_layer_roots(monkeypatch, tmp_path)
    state = os.path.join(str(tmp_path), "state")
    out_dir = _mk_case(state, "pq4")
    cfg = server.ServerConfig(mode="m1-local", state_dir=state)
    assert server.stage_viewer_if_exported(cfg, {"case_id": "pq4", "out_dir": out_dir}) is True, \
        "有 viewer_data.js 时必须舞台化成功"

    case_web = os.path.join(web, "cases", "pq4")
    assert not os.path.exists(os.path.join(case_web, "volume_data.js")), \
        "无源可部署时不得凭空出现 volume_data.js（兜底根必须受控）"
    assert not os.path.exists(os.path.join(case_web, "skin_data.js")), \
        "无源可部署时不得凭空出现 skin_data.js（兜底根必须受控）"
    assert not os.path.isdir(shared6), "兜底根未被写：测试不得在临时根里回写"
    assert not os.path.isdir(shared7), "兜底根未被写：测试不得在临时根里回写"
    html = open(os.path.join(case_web, "viewer.html"), encoding="utf-8").read()
    assert '<script src="volume_data.js">' not in html, "缺位层标签必须剔除（裁剪逻辑仍在）"
    assert '<script src="skin_data.js">' not in html, "缺位层标签必须剔除（裁剪逻辑仍在）"
    assert '<script src="viewer_data.js"></script>' in html, "必需数据标签不得被动"
    single = open(os.path.join(case_web, "viewer_single.html"), encoding="utf-8").read()
    assert '<script src="volume_data.js">' not in single, "单文件版同样不得留悬空引用"
    assert '<script src="skin_data.js">' not in single, "单文件版同样不得留悬空引用"


def test_stage_deploys_layers_from_shared_fallback_roots(tmp_path, monkeypatch):
    """兜底根命中的正例（T3d F1-1 后半句）：把"兜底生效"钉成受控断言。

    兜底根已 pin 到 tmp_path，这里显式造 shared_step6/volume_data.js、
    shared_step7/skin_data.js —— 验证 server.py:1356-1374 的回落部署链
    本身没有被 F1 的 hermetic 化改坏（否则"解耦"可以靠删掉兜底分支达成）。
    """
    web = _mk_web(tmp_path)
    monkeypatch.setattr(server, "WEBAPP_DIR", web)
    monkeypatch.setattr(server, "VIEWER_TEMPLATE",
                        os.path.join(web, "viewer_template", "viewer.html"))
    shared6, shared7 = _pin_shared_layer_roots(monkeypatch, tmp_path)
    _write(os.path.join(shared6, "volume_data.js"), VOL_STUB)
    _write(os.path.join(shared7, "skin_data.js"), SKIN_STUB)
    state = os.path.join(str(tmp_path), "state")
    out_dir = _mk_case(state, "pq5")
    cfg = server.ServerConfig(mode="m1-local", state_dir=state)
    server.stage_viewer_if_exported(cfg, {"case_id": "pq5", "out_dir": out_dir})

    case_web = os.path.join(web, "cases", "pq5")
    assert open(os.path.join(case_web, "volume_data.js"), encoding="utf-8").read() == VOL_STUB, \
        "兜底根 step6 的层文件必须被部署到 cases/<cid>/"
    assert open(os.path.join(case_web, "skin_data.js"), encoding="utf-8").read() == SKIN_STUB, \
        "兜底根 step7 的层文件必须被部署到 cases/<cid>/"
    html = open(os.path.join(case_web, "viewer.html"), encoding="utf-8").read()
    assert '<script src="volume_data.js"></script>' in html, "兜底部署成功后标签必须保留"
    assert '<script src="skin_data.js"></script>' in html, "兜底部署成功后标签必须保留"


# ---------------------------------------------------------------- 3) 204 兜底路由
def test_optional_layer_routes_return_204_and_do_not_shadow(tmp_path, monkeypatch):
    web = _mk_web(tmp_path, with_layers=True)
    monkeypatch.setattr(server, "WEBAPP_DIR", web)
    state = os.path.join(str(tmp_path), "state")
    cfg = server.ServerConfig(mode="m1-local", state_dir=state)
    app = server.build_app(cfg)
    c = app.test_client()

    r = c.get("/static/cases/pX3/volume_data.js")
    assert r.status_code == 204, "缺位 volume_data.js 必须 204（实际 %d）" % r.status_code
    r = c.get("/static/cases/pX3/skin_data.js")
    assert r.status_code == 204, "缺位 skin_data.js 必须 204（实际 %d）" % r.status_code

    _write(os.path.join(web, "cases", "pA", "viewer_single.html"),
           "<!doctype html><title>pA stub</title>" + "x" * 4096)
    r = c.get("/static/cases/pA/viewer_single.html")
    assert r.status_code == 200, "同级静态文件被新路由截胡了（实际 %d）" % r.status_code
    assert b"pA stub" in r.data, "静态文件内容被替换"

    _write(os.path.join(web, "cases", "pA", "volume_data.js"), VOL_STUB)
    r = c.get("/static/cases/pA/volume_data.js")
    assert r.status_code == 200, "已部署的层必须 200（实际 %d）" % r.status_code
    assert b"VOLUME_DATA" in r.data, "已部署层的内容必须原样送出"


# ---------------------------------------------------------------- 4) 单文件构建
_MIN_HTML = ('<!doctype html><html><head><meta charset="utf-8"></head><body>'
             '<script src="viewer_data.js"></script>\n'
             '<script src="volume_data.js"></script>\n'
             '<script src="skin_data.js"></script>\n'
             '</body></html>\n')


def _build_single(dirpath):
    r = subprocess.run([sys.executable, BUILD_SINGLE,
                        os.path.join(dirpath, "viewer.html"),
                        os.path.join(dirpath, "viewer_data.js"),
                        os.path.join(dirpath, "viewer_single.html")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=_child_env_utf8(), timeout=300)
    assert r.returncode == 0, "build_single_file 失败: %s" % (r.stdout or "")[-800:]
    return open(os.path.join(dirpath, "viewer_single.html"), encoding="utf-8").read(), (r.stdout or "")


def test_build_single_drops_dangling_layer_refs(tmp_path):
    d = str(tmp_path)
    _write(os.path.join(d, "viewer.html"), _MIN_HTML)
    _write(os.path.join(d, "viewer_data.js"), VIEWER_STUB)
    single, out = _build_single(d)
    assert '<script src="volume_data.js">' not in single, "单文件版不得留 volume 悬空引用"
    assert '<script src="skin_data.js">' not in single, "单文件版不得留 skin 悬空引用"
    assert "CT 体渲染层未部署（无 volume_data.js）" in single, "缺失层须留说明注释"
    assert "皮肤壳层未部署（无 skin_data.js）" in single, "缺失层须留说明注释"
    assert "window.VIEWER_DATA" in single, "viewer_data.js 必须内联"
    assert "已移除悬空引用" in out, "构建日志须如实说明（不得静默）"


def test_build_single_inlines_layers_when_present(tmp_path):
    d = str(tmp_path)
    _write(os.path.join(d, "viewer.html"), _MIN_HTML)
    _write(os.path.join(d, "viewer_data.js"), VIEWER_STUB)
    _write(os.path.join(d, "volume_data.js"), VOL_STUB)
    _write(os.path.join(d, "skin_data.js"), SKIN_STUB)
    single, out = _build_single(d)
    assert '<script src="volume_data.js">' not in single, "标签应被内联替换"
    assert "window.VOLUME_DATA" in single, "volume_data.js 必须内联（演示/plus 场景不得回退）"
    assert "window.SKIN_DATA" in single, "skin_data.js 必须内联（演示/plus 场景不得回退）"


# ---------------------------------------------------------------- 5) favicon / 17 项检查
def test_full_page_documents_declare_inline_favicon(tmp_path, monkeypatch):
    index_html = open(os.path.join(WEBAPP, "index.html"), encoding="utf-8").read()
    assert '<link rel="icon" href="data:image/svg+xml,' in index_html, \
        "工作台首页缺内联 favicon（无 icon 时浏览器会探测 /favicon.ico → 404）"
    tpl = open(TEMPLATE, encoding="utf-8").read()
    assert 'rel="icon"' in tpl, "查看器模板缺 inner favicon 声明"

    web = _mk_web(tmp_path)
    monkeypatch.setattr(server, "WEBAPP_DIR", web)
    state = os.path.join(str(tmp_path), "state")
    out_dir = _mk_case(state, "pq3")
    cfg = server.ServerConfig(mode="m1-local", state_dir=state)
    server.save_registry(cfg, {
        "pq3": {"case_id": "pq3", "kind": "upload", "prefix": "pQ", "case_name": "v1",
                "label": "测试病例", "dicom_dir": "", "out_dir": out_dir,
                "status": "done", "synthetic": False, "presenter_only": False,
                "created": server.now_iso(), "updated": server.now_iso(),
                "run": {"solve": "local", "mode": "standard"}}})
    app = server.build_app(cfg)
    html = app.test_client().get("/viewer/pq3").data.decode("utf-8")
    assert '<link rel="icon" href="data:image/svg+xml,' in html, \
        "/viewer/<case> 包装页缺内联 favicon"


def test_check_17features_is_green():
    r = subprocess.run([sys.executable, CHECK_17], capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       env=_child_env_utf8(), timeout=120)
    assert r.returncode == 0, "17 项静态断言红了：\n%s\n%s" % ((r.stdout or "")[-800:], (r.stderr or "")[-800:])
    assert "PASS: T50 assertions" in (r.stdout or ""), "断言脚本未跑到 PASS 行：%s" % (r.stdout or "")[-400:]


# ============================================================ [T3g] 以下为 B2 追加用例
# 只追加、不改上面任何既有断言。钉住三件事：
#   ② 兜底来源可观测：走 SHARED_STEP6/7 兜底必须写明"来源=共享兜底根…"；
#   ④ out_dir/step6|7 优先分支：本例根与兜底根同时有不同内容时取本例根，且不写兜底警告；
#   ③ 受控端到端：临时 out 根造 step6/step7 → 部署 → cases/<cid>/ 落地 + 标签保留 + 路由 200。
_CASE_VOL = "window.VOLUME_DATA = {meta:{source:'case-root'}};\n"
_CASE_SKIN = "window.SKIN_DATA = {source:'case-root'};\n"
_SHARED_VOL = "window.VOLUME_DATA = {meta:{source:'shared-root'}};\n"
_SHARED_SKIN = "window.SKIN_DATA = {source:'shared-root'};\n"
_FALLBACK_TAG = "来源=共享兜底根（跨病例共用同一份层文件，非本例产物）"


def _pin_web(monkeypatch, tmp_path):
    web = _mk_web(tmp_path)
    monkeypatch.setattr(server, "WEBAPP_DIR", web)
    monkeypatch.setattr(server, "VIEWER_TEMPLATE",
                        os.path.join(web, "viewer_template", "viewer.html"))
    return web


def _pin_shared_layer_roots_step_named(monkeypatch, tmp_path):
    """把兜底根钉进 <tmp>/shared-root/step6|step7（目录名保持 step6/step7）。

    部署循环用 `os.path.basename(SHARED_STEP6|7)` 反推"本例 out 根下的子目录名"
    （server.py:1358 `_layer_step`），所以要在 out_dir/step6 里放文件、并区分"本例根命中"
    与"兜底根命中"，兜底根的**末级目录名**必须与原默认值（out/step6、out/step7）一致。
    """
    shared_root = os.path.join(str(tmp_path), "shared-root")
    shared6 = os.path.join(shared_root, "step6")
    shared7 = os.path.join(shared_root, "step7")
    monkeypatch.setattr(server, "SHARED_STEP6", shared6)
    monkeypatch.setattr(server, "SHARED_STEP7", shared7)
    return shared6, shared7


def test_stage_fallback_deploy_is_logged_as_shared_source(tmp_path, monkeypatch):
    """② 兜底命中必须留痕：进度日志里出现"来源=共享兜底根（…非本例产物）"。"""
    web = _pin_web(monkeypatch, tmp_path)
    shared6, shared7 = _pin_shared_layer_roots_step_named(monkeypatch, tmp_path)
    _write(os.path.join(shared6, "volume_data.js"), _SHARED_VOL)
    _write(os.path.join(shared7, "skin_data.js"), _SHARED_SKIN)
    state = os.path.join(str(tmp_path), "state")
    out_dir = _mk_case(state, "pq7")
    cfg = server.ServerConfig(mode="m1-local", state_dir=state)
    assert server.stage_viewer_if_exported(cfg, {"case_id": "pq7", "out_dir": out_dir}) is True

    case_web = os.path.join(web, "cases", "pq7")
    assert open(os.path.join(case_web, "volume_data.js"), encoding="utf-8").read() == _SHARED_VOL
    assert open(os.path.join(case_web, "skin_data.js"), encoding="utf-8").read() == _SHARED_SKIN
    prog = open(os.path.join(out_dir, "manifest-progress.json"), encoding="utf-8").read()
    assert prog.count(_FALLBACK_TAG) == 2, \
        "两个层都必须写明共享兜底来源（实际命中 %d 次）" % prog.count(_FALLBACK_TAG)
    assert "volume_data.js" in prog and "skin_data.js" in prog, "兜底部署动作不得静默"


def test_stage_prefers_out_dir_layers_over_shared_fallback(tmp_path, monkeypatch):
    """④ T5 缺口：out_dir/step6|7 与 SHARED_STEP6/7 同时有**不同内容**时，取 out_dir 那份。

    并断言此时不出现 ② 的共享兜底警告（本例根命中 ≠ 串味）。
    """
    web = _pin_web(monkeypatch, tmp_path)
    shared6, shared7 = _pin_shared_layer_roots_step_named(monkeypatch, tmp_path)
    _write(os.path.join(shared6, "volume_data.js"), _SHARED_VOL)
    _write(os.path.join(shared7, "skin_data.js"), _SHARED_SKIN)
    state = os.path.join(str(tmp_path), "state")
    out_dir = _mk_case(state, "pq8")
    _write(os.path.join(out_dir, "step6", "volume_data.js"), _CASE_VOL)
    _write(os.path.join(out_dir, "step7", "skin_data.js"), _CASE_SKIN)
    cfg = server.ServerConfig(mode="m1-local", state_dir=state)
    assert server.stage_viewer_if_exported(cfg, {"case_id": "pq8", "out_dir": out_dir}) is True

    case_web = os.path.join(web, "cases", "pq8")
    got_vol = open(os.path.join(case_web, "volume_data.js"), encoding="utf-8").read()
    got_skin = open(os.path.join(case_web, "skin_data.js"), encoding="utf-8").read()
    assert got_vol == _CASE_VOL, "优先级错：应取 out_dir/step6 的层文件，实际 %r" % got_vol
    assert got_skin == _CASE_SKIN, "优先级错：应取 out_dir/step7 的层文件，实际 %r" % got_skin
    prog = open(os.path.join(out_dir, "manifest-progress.json"), encoding="utf-8").read()
    assert _FALLBACK_TAG not in prog, "本例根命中时不得写共享兜底警告（实际日志：%s）" % prog[-400:]
    assert "可选层已部署（volume_data.js" in prog, "本例根部署仍须留痕"


def test_stage_controlled_e2e_layers_deploy_and_route_200(tmp_path, monkeypatch):
    """③ 受控端到端（临时 out 根 + 临时 case 目录；不碰在用 webapp/cases、webapp/plus）。

    造 <tmp out>/step6/volume_data.js、<tmp out>/step7/skin_data.js → 触发部署 →
    ① 两文件进 cases/<cid>/；② viewer.html 两条 <script src> 保留；
    ③ /static/cases/<cid>/volume_data.js 路由 200 且内容原样。
    """
    web = _pin_web(monkeypatch, tmp_path)
    shared6, shared7 = _pin_shared_layer_roots_step_named(monkeypatch, tmp_path)  # 空兜底根 → 强制走本例根
    state = os.path.join(str(tmp_path), "state")
    out_dir = _mk_case(state, "pq9")
    _write(os.path.join(out_dir, "step6", "volume_data.js"), VOL_STUB)
    _write(os.path.join(out_dir, "step7", "skin_data.js"), SKIN_STUB)
    cfg = server.ServerConfig(mode="m1-local", state_dir=state)
    assert server.stage_viewer_if_exported(cfg, {"case_id": "pq9", "out_dir": out_dir}) is True

    case_web = os.path.join(web, "cases", "pq9")
    assert open(os.path.join(case_web, "volume_data.js"), encoding="utf-8").read() == VOL_STUB
    assert open(os.path.join(case_web, "skin_data.js"), encoding="utf-8").read() == SKIN_STUB
    html = open(os.path.join(case_web, "viewer.html"), encoding="utf-8").read()
    assert '<script src="volume_data.js"></script>' in html, "受控端到端：volume 标签必须保留"
    assert '<script src="skin_data.js"></script>' in html, "受控端到端：skin 标签必须保留"
    assert '<script src="viewer_data.js"></script>' in html, "viewer_data 标签必须保留"
    assert not os.path.isdir(shared6) or not os.path.isfile(
        os.path.join(shared6, "volume_data.js")), "兜底根不得被部署写回"
    assert not os.path.isdir(shared7) or not os.path.isfile(
        os.path.join(shared7, "skin_data.js")), "兜底根不得被部署写回"

    c = server.build_app(cfg).test_client()
    r = c.get("/static/cases/pq9/volume_data.js")
    assert r.status_code == 200, "部署后的层必须 200（实际 %d）" % r.status_code
    assert b"VOLUME_DATA" in r.data, "路由送出的内容必须原样"
    r = c.get("/static/cases/pq9/skin_data.js")
    assert r.status_code == 200, "部署后的层必须 200（实际 %d）" % r.status_code


def test_run_chain_appends_optional_layers_only_when_enabled(tmp_path, monkeypatch):
    """③ 下传链路：cfg.optional_layers 开 → run_all argv 追加 --optional-layers；默认关不追加。

    只替换 server 模块内的 subprocess 句柄（argv 捕获后立刻失败退出），不真的跑 run_all。
    """
    import types

    for _k in ("P0_OPTIONAL_LAYERS", "P0_PRESENTER"):
        monkeypatch.delenv(_k, raising=False)
    state = os.path.join(str(tmp_path), "state")
    seen = []

    class _Proc:
        returncode = 1
        stdout = stderr = ""

    def fake_run(cmd, **kw):
        seen.append(list(cmd))
        return _Proc()

    monkeypatch.setattr(server, "subprocess", types.SimpleNamespace(run=fake_run))
    off = server.ServerConfig(mode="m1-local", state_dir=state)
    on = server.ServerConfig(mode="m1-local", state_dir=state, optional_layers=True)
    assert off.optional_layers is False, "默认必须关"
    assert on.optional_layers is True, "--optional-layers 必须打开 cfg.optional_layers"

    for cid, cfg in (("pqA", on), ("pqB", off)):
        rec = {"case_id": cid, "kind": "upload", "prefix": "pQ", "case_name": "v1",
               "dicom_dir": "", "out_dir": _mk_case(state, cid), "status": "done"}
        server.save_registry(cfg, dict(server.load_registry(cfg), **{cid: rec}))
        server.run_chain_thread(cfg, cid, "skip", "", "standard")

    assert "--optional-layers" in seen[0], "开启时 run_all argv 必须带 --optional-layers：%r" % (seen[0],)
    assert "--optional-layers" not in seen[1], "默认关闭时不得追加：%r" % (seen[1],)
    prog = open(os.path.join(state, "cases", "pqA", "manifest-progress.json"),
                encoding="utf-8").read()
    assert "可选展示层生成已启用" in prog, "开启动作必须进进度日志"