# -*- coding: utf-8 -*-
"""开箱冒烟测试套件（无需患者数据）。

运行：仓库根目录执行 `pytest`。
覆盖：全部源码可编译、依赖清单存在、README 占位说明、
查看器示例数据完整、step1/step2 裸跑友好报错（无 IndexError）。
"""
import os
import py_compile
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _py_files():
    for sub in ("code/pipeline", "code/verify", "code/viewer", "tests"):
        d = os.path.join(ROOT, sub)
        if not os.path.isdir(d):
            continue
        for n in sorted(os.listdir(d)):
            if n.endswith(".py"):
                yield os.path.join(d, n)


def test_all_sources_compile():
    for p in _py_files():
        py_compile.compile(p, doraise=True)


def test_requirements_exists():
    assert os.path.isfile(os.path.join(ROOT, "requirements.txt"))


def test_readme_documents_placeholders():
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
        readme = f.read()
    assert "QUICKSTART" in readme
    for token in ("QIDI_WORKSPACE", "DATA_ROOT", "P0_DICOM_DIR",
                  "requirements.txt", "pytest"):
        assert token in readme, f"README 缺少说明：{token}"


def test_viewer_demo_data_complete():
    p = os.path.join(ROOT, "code", "viewer", "viewer_data.js")
    assert os.path.isfile(p)
    with open(p, encoding="utf-8") as f:
        txt = f.read()
    for key in ("meta", "airwayMesh", "streamlines", "slices",
                "placeholders", "curve"):
        assert key in txt, f"viewer_data.js 缺少键：{key}"


def _run_script(rel):
    env = dict(os.environ)
    env.pop("P0_DICOM_DIR", None)
    return subprocess.run(
        [sys.executable, os.path.join(ROOT, rel)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, cwd=ROOT, timeout=180)


def test_step1_bare_run_friendly_error():
    r = _run_script(os.path.join("code", "pipeline", "step1_airway_segment.py"))
    assert r.returncode != 0
    combined = r.stdout + r.stderr
    assert "IndexError" not in combined
    assert "DICOM" in combined


def test_step2_bare_run_friendly_error():
    r = _run_script(os.path.join("code", "pipeline", "step2_make_ofcase.py"))
    assert r.returncode != 0
    combined = r.stdout + r.stderr
    assert "IndexError" not in combined
    assert "DICOM" in combined


def test_cli_capabilities_runs():
    code_dir = os.path.join(ROOT, "code")
    env = dict(os.environ)
    r = subprocess.run(
        [sys.executable, "-m", "pipeline.cli", "capabilities"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, cwd=code_dir, timeout=180)
    assert r.returncode == 0
    assert "capabilities" in r.stdout
