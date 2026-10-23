#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T3f：step6/step7 输入输出参数化 + run_all 可选层调用点（默认行为逐字节不变）。

钉住的契约（规格书 T3f-B1）：
  1) 不传新参数时，step6/step7 的路径常量解析结果 == 旧字面量（默认逐字节不变）；
  2) 传 --out-dir 后所有产物落点都从该目录派生（volume_data.js / volume_qc.json /
     skin_data.js / skin_qc.json / skin_preview.png），源码里没有第二处写死落点；
  3) run_all 的 S7b/S7c：未带 --optional-layers 时 manifest 写
     disabled_by_default + 理由（不许静默跳过）；step6 失败 ⇒ step7 记
     skipped_dependency_step6；失败不 abort（只记 manifest）。

证明方式（不允许真跑重计算）：把脚本源码截到"argparse + 重绑定块"末尾再 exec，
既有 argparse 的真实解析结果，又不触发 DICOM/网格计算。run_all 侧注入 fake runner。
"""
import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.dirname(HERE)
if PIPELINE not in sys.path:
    sys.path.insert(0, PIPELINE)

_ORIG_STDOUT = sys.stdout
import run_all  # noqa: E402

# run_all 模块级把 sys.stdout 换成 UTF-8 wrapper（run_all.py:73）。若让 wrapper 一直占着
# sys.stdout，pytest 的 capture 临时文件会在 wrapper 析构时被关闭（session 收尾
# "ValueError: I/O operation on closed file"）。这里立刻还原 stdout，并保留 wrapper 引用
# 防止其被 GC 提前关闭底层文件——被测对象的 argv/落点口径一字未动。
_RA_STDOUT = sys.stdout
sys.stdout = _ORIG_STDOUT

STEP6 = os.path.join(PIPELINE, "step6_build_volume_data.py")
STEP7 = os.path.join(PIPELINE, "step7_build_skin_data.py")
RUN_ALL = os.path.join(PIPELINE, "run_all.py")

# 重绑定块的**最后一行**：exec 到这里为止（既不提前漏断言，也不进入重计算）
_STOP_LINE = {
    STEP6: '    META["patient"] = args.meta_patient',
    STEP7: 'DATA_DIR = args.dicom_dir or DATA_DIR',
}


def _child_env_utf8():
    """子进程按 utf-8 出流（本机默认控制台 GBK；同 test_viewer_optional_layers 口径）。"""
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _exec_cli_prefix(script, argv):
    """exec 脚本源码到"CLI + 重绑定块"末尾，返回模块级名字表（真实 argparse 结果）。"""
    with open(script, encoding="utf-8") as f:
        lines = f.read().splitlines(True)
    stop = _STOP_LINE[script]
    cut = None
    for i, ln in enumerate(lines):
        if ln.rstrip("\n") == stop:
            cut = i + 1
    assert cut is not None, "未找到 T3f 重绑定块结束行：%r（测试与实现结构失配）" % stop
    src = "".join(lines[:cut])
    old_argv = sys.argv
    sys.argv = [script] + list(argv)
    ns = {"__name__": "__t3f_cli_probe__", "__file__": script}
    try:
        exec(compile(src, script, "exec"), ns)
    finally:
        sys.argv = old_argv
    return ns


# ---------------------------------------------------------------- 1) 默认逐字节不变
def test_step6_defaults_equal_legacy_constants():
    ns = _exec_cli_prefix(STEP6, [])
    assert ns["OUT_STEP6"] == os.path.join(PIPELINE, "out", "step6")
    assert ns["MASK_NPZ"] == os.path.join(PIPELINE, "out", "step2", "mask_full.npz")
    assert ns["VIEWER_JS"] == os.path.join(PIPELINE, "out", "step5", "viewer_data.js")
    assert ns["DATA_DIR"] == os.path.expandvars(
        r"%DATA_ROOT%\参赛群资料\患者A\脱敏后图像数据\ISO_Soft_0.35mm_合并")
    assert ns["META"]["patient"] == "A（数据捐献者授权）"


def test_step7_defaults_equal_legacy_constants():
    ns = _exec_cli_prefix(STEP7, [])
    assert ns["OUT_STEP7"] == os.path.join(PIPELINE, "out", "step7")
    assert ns["MASK_NPZ"] == os.path.join(PIPELINE, "out", "step2", "mask_full.npz")
    assert ns["VIEWER_JS"] == os.path.join(PIPELINE, "out", "step5", "viewer_data.js")
    assert ns["VOLUME_JS"] == os.path.join(PIPELINE, "out", "step6", "volume_data.js")
    assert ns["DATA_DIR"] == os.path.expandvars(
        r"%DATA_ROOT%\参赛群资料\患者A\脱敏后图像数据\ISO_Soft_0.35mm_合并")
    assert ns["META"]["patient"] == "A（数据捐献者授权）"


def test_step6_cli_overrides_all_paths(tmp_path):
    out = str(tmp_path / "s6")
    ns = _exec_cli_prefix(STEP6, [
        "--out-dir", out, "--mask-npz", "M.npz", "--viewer-js", "V.js",
        "--dicom-dir", "D", "--meta-patient", "演示病例"])
    assert ns["OUT_STEP6"] == out
    assert ns["MASK_NPZ"] == "M.npz"
    assert ns["VIEWER_JS"] == "V.js"
    assert ns["DATA_DIR"] == "D"
    assert ns["META"]["patient"] == "演示病例"


def test_step7_cli_overrides_all_paths(tmp_path):
    out = str(tmp_path / "s7")
    ns = _exec_cli_prefix(STEP7, [
        "--out-dir", out, "--mask-npz", "M.npz", "--viewer-js", "V.js",
        "--volume-js", "VOL.js", "--dicom-dir", "D"])
    assert ns["OUT_STEP7"] == out
    assert ns["MASK_NPZ"] == "M.npz"
    assert ns["VIEWER_JS"] == "V.js"
    assert ns["VOLUME_JS"] == "VOL.js"
    assert ns["DATA_DIR"] == "D"


# ------------------------------------------------- 2) 没有第二处写死落点（半参数化防线）
@pytest.mark.parametrize("script,const,legacy_literals,joins", [
    (STEP6, "OUT_STEP6",
     ['os.path.join(HERE, "out", "step6")',
      'os.path.join(HERE, "out", "step2", "mask_full.npz")',
      'os.path.join(HERE, "out", "step5", "viewer_data.js")'],
     ["volume_data.js", "volume_qc.json"]),
    (STEP7, "OUT_STEP7",
     ['os.path.join(HERE, "out", "step7")',
      'os.path.join(HERE, "out", "step2", "mask_full.npz")',
      'os.path.join(HERE, "out", "step5", "viewer_data.js")',
      'os.path.join(HERE, "out", "step6", "volume_data.js")'],
     ["skin_data.js", "skin_qc.json", "skin_preview.png"]),
])
def test_all_path_literals_exist_only_in_constant_defs(script, const, legacy_literals, joins):
    """每个写死落点在全文件只出现一次（= 常量定义），产物一律 join(常量, 名字)。"""
    with open(script, encoding="utf-8") as f:
        src = f.read()
    for lit in legacy_literals:
        assert src.count(lit) == 1, "%s 出现 %d 次（应仅常量定义处 1 次）" % (lit, src.count(lit))
    for name in joins:
        assert 'os.path.join(%s, "%s")' % (const, name) in src, \
            "%s 未从 %s 派生" % (name, const)


# ---------------------------------------------------------------- 3) --help 暴露参数
@pytest.mark.parametrize("script,flags", [
    (STEP6, ["--out-dir", "--mask-npz", "--viewer-js", "--dicom-dir", "--meta-patient"]),
    (STEP7, ["--out-dir", "--mask-npz", "--viewer-js", "--volume-js", "--dicom-dir"]),
])
def test_help_lists_new_path_args(script, flags):
    r = subprocess.run([sys.executable, "-X", "utf8", script, "--help"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=_child_env_utf8(), timeout=120)
    assert r.returncode == 0, r.stderr
    for fl in flags:
        assert fl in r.stdout, "--help 缺参数 %s" % fl


# ---------------------------------------------------------- 4) run_all S7b/S7c 接线
def test_optional_layer_cmds_share_out_root(tmp_path):
    root = str(tmp_path / "case-out")
    cmds = run_all.optional_layer_cmds(root, "DICOM", "MASK.npz")
    assert [c["stage"] for c in cmds] == ["S7b_step6", "S7c_step7"]
    c6, c7 = cmds[0]["cmd"], cmds[1]["cmd"]
    assert c6[c6.index("--out-dir") + 1] == os.path.join(root, "step6")
    assert c7[c7.index("--out-dir") + 1] == os.path.join(root, "step7")
    # step7 必须读同一 out 根下 step6 的产物（依赖链不可交换）
    assert c7[c7.index("--volume-js") + 1] == os.path.join(root, "step6", "volume_data.js")
    for c in (c6, c7):
        assert c[c.index("--viewer-js") + 1] == os.path.join(root, "step5", "viewer_data.js")
        assert c[c.index("--dicom-dir") + 1] == "DICOM"
        assert c[c.index("--mask-npz") + 1] == "MASK.npz"
    assert cmds[0]["qc"] == os.path.join(root, "step6", "volume_qc.json")
    assert cmds[1]["qc"] == os.path.join(root, "step7", "skin_qc.json")


def test_disabled_by_default_is_explicit_in_manifest():
    manifest = {"stages": {}}
    run_all.run_optional_layers(manifest, False, "R", "D", "M")
    assert manifest["stages"]["S7b_step6"] == {
        "status": "disabled_by_default",
        "reason": "geometry_constants_are_case_specific",
    }, "未启用时必须显式留痕（不许静默跳过）"
    assert "S7c_step7" not in manifest["stages"]


class _R:
    def __init__(self, rc):
        self.returncode = rc
        self.stdout, self.stderr = "out", ("boom" if rc else "")


def test_step6_failure_skips_step7_not_abort(tmp_path):
    manifest = {"stages": {}}
    calls = []

    def fake(cmd, **kw):
        calls.append(cmd)
        return _R(1)

    run_all.run_optional_layers(manifest, True, str(tmp_path), "D", "M", runner=fake)
    assert len(calls) == 1, "step6 失败后不得再跑 step7"
    assert manifest["stages"]["S7b_step6"]["status"] == "failed"
    assert manifest["stages"]["S7b_step6"]["returncode"] == 1
    assert "elapsed_sec" in manifest["stages"]["S7b_step6"]
    assert manifest["stages"]["S7c_step7"]["status"] == "skipped_dependency_step6"


def test_step6_exception_skips_step7_not_abort(tmp_path):
    manifest = {"stages": {}}

    def boom(cmd, **kw):
        raise RuntimeError("spawn failed")

    run_all.run_optional_layers(manifest, True, str(tmp_path), "D", "M", runner=boom)
    assert manifest["stages"]["S7b_step6"]["status"] == "failed"
    assert "spawn failed" in manifest["stages"]["S7b_step6"]["error"]
    assert manifest["stages"]["S7c_step7"]["status"] == "skipped_dependency_step6"


def test_success_records_elapsed_and_qc(tmp_path):
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "step6"))
    os.makedirs(os.path.join(root, "step7"))
    with open(os.path.join(root, "step6", "volume_qc.json"), "w", encoding="utf-8") as f:
        json.dump({"all_pass": True}, f)
    with open(os.path.join(root, "step7", "skin_qc.json"), "w", encoding="utf-8") as f:
        json.dump({"all_pass": False}, f)
    manifest = {"stages": {}}
    calls = []

    def fake(cmd, **kw):
        calls.append(cmd)
        return _R(0)

    run_all.run_optional_layers(manifest, True, root, "D", "M", runner=fake)
    assert len(calls) == 2
    s6, s7 = manifest["stages"]["S7b_step6"], manifest["stages"]["S7c_step7"]
    assert s6["status"] == "exported" and s6["qc_all_pass"] is True
    assert s7["status"] == "exported" and s7["qc_all_pass"] is False
    for e in (s6, s7):
        assert e["returncode"] == 0
        assert isinstance(e["elapsed_sec"], float) and e["elapsed_sec"] >= 0
    assert s6["out_dir"] == "step6" and s7["out_dir"] == "step7"


def test_run_all_help_has_optional_layers_flag():
    r = subprocess.run([sys.executable, "-X", "utf8", RUN_ALL, "--help"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=_child_env_utf8(), timeout=180)
    assert r.returncode == 0, r.stderr
    assert "--optional-layers" in r.stdout
    assert "--optional-layers-timeout" not in r.stdout, "本轮不实现超时旋钮"
