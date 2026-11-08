#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三步契约分层 v2（2026-11-07）行为级回归。

钉住的是**真实 `run_chain_thread` 组装出的 run_all 命令**，不是源码子串：
- 上传病例 standard 档必须拿到「跳过 Taubin 视觉平滑」的现成开关，但**不得**降精度。
- pA / 内置 / 合成病例不得拿到该开关（保 viewer_data.js / six_boards 逐字节不变）。
- quick 档仍降精度 + 产物根切 /quick，且开关只追加一次。
- 舞台化清旧仅对 kind=="upload" 生效，冻结只读副本一律不动（复审 BLOCKING A）。

依据：`方案-第一步档位解耦与验收判据修复-v2-2026-11-07.md` §2.1 / §2.2 / §4。
"""
import os
import sys
import types

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.dirname(HERE)
if PIPELINE not in sys.path:
    sys.path.insert(0, PIPELINE)

import server as SRV  # noqa: E402


def _rec(kind, case_id="pT"):
    return {"case_id": case_id, "kind": kind, "out_dir": "/tmp/e2e/pT",
            "dicom_dir": "/tmp/e2e/dcm", "prefix": "pT", "case_name": "v1",
            "status": "registered"}


def _drive(monkeypatch, rec, mode):
    """同步跑一次 run_chain_thread，拦住 subprocess.run 捕获真实 argv。"""
    cid = rec["case_id"]
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(SRV, "subprocess", types.SimpleNamespace(run=fake_run))
    monkeypatch.setattr(SRV, "get_case_record", lambda cfg, c: dict(rec))
    monkeypatch.setattr(SRV, "_clear_stale_staged_viewer", lambda r: None)
    monkeypatch.setattr(SRV, "append_progress", lambda *a, **k: None)
    monkeypatch.setattr(SRV, "load_registry", lambda cfg: {cid: dict(rec)})
    monkeypatch.setattr(SRV, "save_registry", lambda cfg, reg: None)
    monkeypatch.setattr(SRV, "stage_viewer_if_exported", lambda *a, **k: False)
    monkeypatch.setattr(SRV, "_session_purge", lambda *a, **k: None)
    monkeypatch.setattr(SRV, "case_slice_dz", lambda r: None)

    SRV.run_chain_thread(types.SimpleNamespace(), cid, "local", None, mode=mode)
    return seen["cmd"]


def _arg(cmd, flag):
    return cmd[cmd.index(flag) + 1] if flag in cmd else None


# ---------------------------------------------------------------- §2.1 档位解耦
def test_upload_standard_gets_geometry_switch_without_downgrade(monkeypatch):
    """第一步主路径：全精度 + 跳过平滑，不降精度、不切 /quick 产物根。"""
    cmd = _drive(monkeypatch, _rec("upload"), "standard")
    assert "--allow-partial-viewer" in cmd
    assert "--quick" not in cmd
    assert "--voxel-z" not in cmd
    assert not _arg(cmd, "--out-root").replace("\\", "/").rstrip("/").endswith("/quick")


@pytest.mark.parametrize("kind", ["builtin", "synthetic", "demo"])
def test_non_upload_standard_keeps_smoothing_and_bytecode(monkeypatch, kind):
    """pA / 内置 / 合成病例不拿开关 ⇒ 仍做平滑 ⇒ 逐字节不变。"""
    cmd = _drive(monkeypatch, _rec(kind), "standard")
    assert "--allow-partial-viewer" not in cmd
    assert "--quick" not in cmd


@pytest.mark.parametrize("kind", ["upload", "builtin", "synthetic"])
def test_quick_still_downgrades_and_appends_switch_once(monkeypatch, kind):
    """quick 档零影响：仍降精度、产物根切 /quick，开关只追加一次。"""
    cmd = _drive(monkeypatch, _rec(kind), "quick")
    assert "--quick" in cmd
    assert cmd.count("--allow-partial-viewer") == 1
    assert _arg(cmd, "--out-root").replace("\\", "/").rstrip("/").endswith("/quick")


# ---------------------------------------------------------------- §2.2 清理射程
def test_clear_stale_only_for_upload(monkeypatch, tmp_path):
    """复审 BLOCKING A：pA / 内置 / demo 的冻结只读副本一律不动。"""
    web = tmp_path / "webapp"
    case = web / "cases" / "pT"
    case.mkdir(parents=True)
    names = ("viewer_data.js", "viewer_single.html", "viewer.html")
    for n in names:
        (case / n).write_text("stale", encoding="utf-8")
    monkeypatch.setattr(SRV, "WEBAPP_DIR", str(web))

    SRV._clear_stale_staged_viewer(_rec("upload"))
    assert not any((case / n).exists() for n in names), "上传病例旧舞台化文件应被清掉"

    for n in names:
        (case / n).write_text("frozen", encoding="utf-8")
    for kind in ("builtin", "synthetic", "demo"):
        SRV._clear_stale_staged_viewer(_rec(kind))
        assert all((case / n).read_text(encoding="utf-8") == "frozen" for n in names), \
            f"{kind} 的冻结副本不得被清理"


def test_quick_emits_voxel_z_when_slice_dz_available(monkeypatch):
    """复核第 7 项：quick 档读到有效源层厚 ⇒ cmd 带 --voxel-z（= quick_voxel_z(dz)
    的 %g 值）、仍带 --quick，且 --allow-partial-viewer 只追加一次。"""
    rec = _rec("upload")
    cid = rec["case_id"]
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(SRV, "subprocess", types.SimpleNamespace(run=fake_run))
    monkeypatch.setattr(SRV, "get_case_record", lambda cfg, c: dict(rec))
    monkeypatch.setattr(SRV, "_clear_stale_staged_viewer", lambda r: None)
    monkeypatch.setattr(SRV, "append_progress", lambda *a, **k: None)
    monkeypatch.setattr(SRV, "load_registry", lambda cfg: {cid: dict(rec)})
    monkeypatch.setattr(SRV, "save_registry", lambda cfg, reg: None)
    monkeypatch.setattr(SRV, "stage_viewer_if_exported", lambda *a, **k: False)
    monkeypatch.setattr(SRV, "_session_purge", lambda *a, **k: None)
    monkeypatch.setattr(SRV, "case_slice_dz", lambda r: 0.35)
    monkeypatch.setattr(SRV.RA, "quick_voxel_z", lambda dz: 3.15)

    SRV.run_chain_thread(types.SimpleNamespace(), cid, "local", None, mode="quick")
    cmd = seen["cmd"]

    assert "--quick" in cmd
    assert _arg(cmd, "--voxel-z") == "3.15"
    assert cmd.count("--allow-partial-viewer") == 1
