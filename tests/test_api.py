#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T15 API 基础测试（pytest 四类 · GLM 审计 R-10 带条件放行项）。

四类：
  1. TestAPIContract        —— API 契约（/api/health、/api/cases、/api/qc、
                              /api/progress、/viewer、静态页）
  2. TestDataBoundary       —— 数据边界拒绝（修订1/R-03：云形态 POST /api/case
                              501、非合成病例 403；R-01：pB 授权在案，presenter 分级机制保留）
  3. TestGateMapping        —— exit 2/3 → ⛔/⚠️ 状态映射契约 + PII 闸门
                              （run_all 同款 scan_pii 真机契约测试）
  4. TestMetricsConsistency —— 指标卡与 manifest+metrics 一致性 +
                              双口径标签断言（ΔP 定流量 vs R 等压不可互换）

运行（pipeline 目录内）：
  py -X utf8 -m pytest test_api.py -v
依赖：flask、pytest（pipeline 环境已装）；内置病例测试经 P0_CT_BASE
定位参赛群资料（缺省回退本机交付路径；无该路径时内置用例跳过）。
"""
import json
import os
import sys
import zipfile

import pytest

PIPE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "code", "pipeline"))
if PIPE not in sys.path:
    sys.path.insert(0, PIPE)

# R-14：CT 根目录经环境变量注入（部署参数，非代码硬编码）
CT_BASE = os.environ.get(
    "P0_CT_BASE",
    os.path.expandvars(r"%DATA_ROOT%\参赛群资料"))
CT_BASE_OK = os.path.isdir(CT_BASE)

try:
    import server as SRV  # noqa: E402
except ImportError:
    pytest.skip("server/flask 不可用（可选 Web 控制台后端未安装），跳过 API 契约测试",
                allow_module_level=True)

STATE_M1 = os.path.join(PIPE, "out", "webapp-state-test-m1")
STATE_CLOUD = os.path.join(PIPE, "out", "webapp-state-test-cloud")
STATE_PRES = os.path.join(PIPE, "out", "webapp-state-test-pres")


def _mk(mode="m1-local", presenter=False):
    return SRV.ServerConfig(
        mode=mode, presenter=presenter,
        base_dir=CT_BASE if CT_BASE_OK else "",
        state_dir={"m1-local": STATE_M1, "m2-cloud": STATE_CLOUD}.get(mode, STATE_M1)
        if not presenter else STATE_PRES)


@pytest.fixture(scope="module")
def client():
    app = SRV.build_app(_mk("m1-local"))
    return app.test_client()


@pytest.fixture(scope="module")
def cloud_client():
    app = SRV.build_app(_mk("m2-cloud"))
    return app.test_client()


@pytest.fixture(scope="module")
def pres_client():
    app = SRV.build_app(_mk("m1-local", presenter=True))
    return app.test_client()


# ================================================================ 类 1：API 契约
class TestAPIContract:
    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        j = r.get_json()
        assert j["status"] == "ok"
        assert j["mode"] == "m1-local"
        assert j["only_synthetic"] is False

    def test_index_page(self, client):
        r = client.get("/")
        assert r.status_code == 200
        t = r.get_data(as_text=True)
        assert "P0 鼻腔气流分析工作台" in t
        assert "边界与已知局限" in t  # 了解 ENS 页签内 h3 保留
        for tab in ("查看气道", "了解 ENS", "上传分析", "关于本项目"):
            assert tab in t

    def test_cases_schema(self, client):
        r = client.get("/api/cases")
        assert r.status_code == 200
        j = r.get_json()
        ids = {c["case_id"] for c in j["cases"]}
        assert {"pA", "pB", "pC", "demo"} <= ids
        for c in j["cases"]:
            for k in ("case_id", "label", "kind", "synthetic", "badge",
                      "badge_text", "status", "viewer_available",
                      "qc_available", "note"):
                assert k in c, f"卡片缺字段 {k}"
        pA = [c for c in j["cases"] if c["case_id"] == "pA"][0]
        assert pA["viewer_available"] is True
        assert pA["badge"] == "✅"
        pC = [c for c in j["cases"] if c["case_id"] == "pC"][0]
        assert pC["badge"] == "⛔"
        assert pC["viewer_available"] is False  # 待结果回传

    @pytest.mark.skipif(not CT_BASE_OK, reason="P0_CT_BASE 未配置")
    def test_qc_pA_three_planes(self, client):
        r = client.get("/api/qc/pA")
        assert r.status_code == 200
        j = r.get_json()
        views = j["views"]
        assert len(views) >= 3, "三平面 QC 应 >= 3 视图"
        kinds = {v["kind"] for v in views}
        assert "ct_overlay" in kinds  # 轴位掩膜叠加 CT（R-02 允许态）
        assert "mask" in kinds
        for v in views:
            r2 = client.get(v["url"])
            assert r2.status_code == 200
            assert r2.get_data()[:8] == b"\x89PNG\r\n\x1a\n"
        # R-02 披露在场
        assert "R-02" in j["r02_note"]

    def test_progress_schema(self, client):
        r = client.get("/api/progress/pA")
        assert r.status_code == 200
        j = r.get_json()
        for k in ("case_id", "status", "current_stage", "stages_seen",
                  "n_lines", "lines"):
            assert k in j

    def test_viewer_pA_iframe(self, client):
        r = client.get("/viewer/pA")
        assert r.status_code == 200
        t = r.get_data(as_text=True)
        assert "<iframe" in t
        assert "/static/cases/pA/viewer_single.html" in t

    def test_viewer_pC_pending_card(self, client):
        r = client.get("/viewer/pC")
        assert r.status_code == 200
        t = r.get_data(as_text=True)
        assert "待解算" in t or "待结果回传" in t

    def test_demo_viewer_and_static(self, client):
        r = client.get("/viewer/demo")
        assert r.status_code == 200
        assert "<iframe" in r.get_data(as_text=True)
        r2 = client.get("/static/demo/viewer_data.js")
        assert r2.status_code == 200
        assert len(r2.get_data()) > 1_000_000  # 合成 demo 数据包

    def test_post_case_demo(self, client):
        r = client.post("/api/case", data={"source": "demo"})
        assert r.status_code == 200
        assert r.get_json()["case_id"] == "demo"

    def test_frozen_pA_single_untouched(self, client):
        """冻结资产零接触：webapp 内 pA 单文件版与提交包逐字节一致。"""
        src = (os.path.expandvars(r"%DATA_ROOT%\项目")
               + r"\P0-鼻塞设计工具\提交包-20261002\viewer_single.html")
        dst = os.path.join(PIPE, "webapp", "cases", "pA", "viewer_single.html")
        if not (os.path.isfile(src) and os.path.isfile(dst)):
            pytest.skip("冻结资产副本不在位")
        import hashlib
        h = lambda p: hashlib.md5(open(p, "rb").read()).hexdigest()
        assert h(src) == h(dst), "pA viewer_single.html 副本与提交包不一致"


# ================================================================ 类 2：数据边界拒绝
class TestDataBoundary:
    def test_cloud_post_case_codelevel_501(self, cloud_client):
        """R-03：云形态 POST /api/case 代码级禁用（501，非 UI 隐藏）。"""
        r = cloud_client.post("/api/case",
                              data={"source": "path", "dicom_path": "C:\\x"})
        assert r.status_code == 501
        assert "代码级禁用" in r.get_json()["error"]

    def test_cloud_builtin_case_501(self, cloud_client):
        r = cloud_client.post("/api/case",
                              data={"source": "builtin", "case_id": "pA"})
        assert r.status_code == 501

    def test_cloud_real_case_access_403(self, cloud_client):
        """修订1：云形态非合成病例访问一律 403 + 中文提示。"""
        for path in ("/viewer/pA", "/api/metrics/pA", "/api/qc/pA",
                     "/api/progress/pA"):
            r = cloud_client.get(path)
            assert r.status_code == 403, f"{path} 应 403，实得 {r.status_code}"
            body = r.get_data(as_text=True)
            j = r.get_json(silent=True) or {}
            assert "数据边界" in j.get("error", "") or "数据边界" in body, \
                f"{path} 403 响应缺数据边界提示：{body[:200]}"

    def test_cloud_demo_accessible(self, cloud_client):
        """云形态唯一数据：合成 demo 可访问。"""
        assert cloud_client.get("/viewer/demo").status_code == 200
        assert cloud_client.get("/api/metrics/demo").status_code == 200
        r = cloud_client.get("/api/cases")
        demo = [c for c in r.get_json()["cases"] if c["case_id"] == "demo"][0]
        assert demo["synthetic"] is True
        assert demo["viewer_available"] is True

    def test_pB_authorized_in_register(self, client):
        """R-01 授权事实更新：患者B（赛方提供匿名 CT）演示展示确认为"在案"——
        非 presenter 模式即可读取指标；3D 查看器仍受契约完备性闸门拦截。"""
        r = client.get("/api/metrics/pB")
        assert r.status_code == 200
        assert r.get_json()["dP"]["value"] is not None
        cards = client.get("/api/cases").get_json()["cases"]
        pB = [c for c in cards if c["case_id"] == "pB"][0]
        assert pB["badge"] == "✅"
        assert pB["presenter_only"] is False
        assert pB["viewer_available"] is False  # 3D 查看器仍待契约完备

    def test_pB_presenter_unlocks_metrics(self, pres_client):
        """pB 授权在案后，presenter 模式同样可读指标（授权分级机制保留）。"""
        r = pres_client.get("/api/metrics/pB")
        assert r.status_code == 200
        assert r.get_json()["dP"]["value"] is not None

    def test_pB_presenter_viewer_blocked_by_contract(self, pres_client):
        """presenter 模式下 pB 查看器仍被契约完备性闸门如实拦截
        （缺 dP_1/2/3mm 占位档——严禁套用其他患者数字）。"""
        r = pres_client.get("/viewer/pB")
        assert r.status_code == 200
        t = r.get_data(as_text=True)
        assert "占位" in t


# ================================================================ 类 3：exit 2/3 映射 + PII 闸门
class TestGateMapping:
    def test_map_exit_code_contract(self):
        """R-10：退出码 → 状态映射契约（⛔ 拦截卡 / ⚠️ 环境缺失）。"""
        assert SRV.map_exit_code(0) == "done"
        assert SRV.map_exit_code(2) == "blocked"
        assert SRV.map_exit_code(3) == "failed_env"
        assert SRV.map_exit_code(1) == "failed"
        assert SRV.map_exit_code(-999) == "failed"

    def test_extract_fatal_reason(self):
        """exit-2 拦截卡原因列表 = 进度日志中最后一条 FATAL 原文。"""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "manifest-progress.json")
            with open(p, "w", encoding="utf-8") as f:
                f.write(json.dumps(
                    {"ts": 1.0, "msg": "[S0] PII 头扫描 ..."},
                    ensure_ascii=False) + "\n")
                f.write(json.dumps(
                    {"ts": 2.0,
                     "msg": "!!! FATAL (exit 2): PII 头扫描 FAIL ×3（首条：...）——停工上报"},
                    ensure_ascii=False) + "\n")
            reason = SRV.extract_fatal_reason(d)
            assert "PII 头扫描 FAIL" in reason

    @pytest.mark.skipif(not CT_BASE_OK, reason="P0_CT_BASE 未配置")
    def test_scan_pii_pA_passes(self):
        """run_all 同款闸门契约：真实 pA 序列（脱敏在案）全过。"""
        import run_all as RA
        dicom = os.path.join(CT_BASE, "患者A", "脱敏后图像数据",
                             "ISO_Soft_0.35mm_合并")
        rec = RA.scan_pii(dicom)
        assert rec["pass"] is True
        assert rec["files"] == 394  # pA 序列 394 头（交付基线在案）

    @pytest.mark.skipif(not CT_BASE_OK, reason="P0_CT_BASE 未配置")
    def test_scan_pii_bad_dir_gate(self):
        """同款闸门：无 .dcm 目录即停工（SystemExit→服务端转 ⛔ 拦截）。"""
        import run_all as RA
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            with pytest.raises(SystemExit) as ei:
                RA.scan_pii(d)
            assert ei.value.code == 2  # exit 2 契约

    def test_blocked_case_progress_carries_gate(self, client):
        """⛔ 拦截卡数据通路：blocked 病例的进度端点带 gate_failures。"""
        reg = SRV.load_registry(SRV.ServerConfig(
            mode="m1-local", state_dir=STATE_M1,
            base_dir=CT_BASE if CT_BASE_OK else ""))
        reg["pXtest"] = {
            "case_id": "pXtest", "kind": "upload", "prefix": "pXtest",
            "case_name": "v1", "label": "拦截测试病例",
            "dicom_dir": "", "out_dir": os.path.join(STATE_M1, "cases", "pXtest"),
            "status": "blocked", "synthetic": False,
            "gate": "PII 头扫描（run_all 同款闸门）",
            "gate_failures": ["PII 头扫描 FAIL ×1：PatientName 非空"],
            "exit_code": 2,
        }
        SRV.save_registry(SRV.ServerConfig(
            mode="m1-local", state_dir=STATE_M1,
            base_dir=CT_BASE if CT_BASE_OK else ""), reg)
        r = client.get("/api/progress/pXtest")
        assert r.status_code == 200
        j = r.get_json()
        assert j["status"] == "blocked"
        assert j["exit_code"] == 2
        assert j["gate_failures"] and "PII" in j["gate_failures"][0]


# ================================================================ 类 4：指标卡一致性 + 双口径标签
class TestMetricsConsistency:
    @pytest.mark.skipif(not CT_BASE_OK, reason="P0_CT_BASE 未配置")
    def test_pA_metrics_match_frozen_viewer_data(self, client):
        """指标卡与冻结 viewer_data.js 逐字段一致（pA 基线在案数字）。"""
        j = client.get("/api/metrics/pA").get_json()
        # 冻结资产独立解析（不经 server 代码路径）
        single = os.path.join(PIPE, "webapp", "cases", "pA", "viewer_single.html")
        meta = SRV.extract_viewer_meta(single)
        mm = SRV._metrics_block(meta)
        assert j["dP"]["value"] == mm["dP_baseline_Pa"] == 18.45
        assert j["split"]["L"] == mm["split_L_pct"] == 51.9
        assert j["split"]["R"] == mm["split_R_pct"] == 48.1
        assert j["resistance"]["value"] == 66.2

    @pytest.mark.skipif(not CT_BASE_OK, reason="P0_CT_BASE 未配置")
    def test_pA_double_koujing_labels_not_interchangeable(self, client):
        """R-10 双口径标签断言：ΔP 定流量 vs R 等压——标签在场且不可互换。"""
        j = client.get("/api/metrics/pA").get_json()
        assert "定流量" in j["dP"]["口径"]
        assert "等压" in j["resistance"]["口径"]
        assert j["dP"]["口径"] != j["resistance"]["口径"], "双口径标签不可相同"
        assert "不可互换" in j["口径_note"]
        # 常人对照带分开标注（压降带 vs 阻力带）
        assert j["dP"]["band"] == {"lo": 30.0, "hi": 50.0, "unit": "Pa",
                                   "label": j["dP"]["band"]["label"]}
        assert j["resistance"]["band"]["lo"] == 120.0
        assert j["resistance"]["band"]["hi"] == 600.0
        assert j["dP"]["band"]["unit"] != j["resistance"]["band"]["unit"]

    def test_demo_metrics_synthetic_labels(self, client):
        j = client.get("/api/metrics/demo").get_json()
        assert j["dP"]["value"] == 23.7
        assert j["split"]["L"] == 50.0
        assert "合成" in j["dP"]["口径"]
        assert "合成" in j["resistance"]["口径"]

    def test_pB_metrics_match_postcfd(self, client):
        """pB 指标与本例真实后处理 metrics.json 一致（out/结果/P0-result-pB-v1）。"""
        j = client.get("/api/metrics/pB").get_json()
        mp = os.path.join(PIPE, "out", "结果", "P0-result-pB-v1", "后处理", "metrics.json")
        m = json.load(open(mp, encoding="utf-8"))
        t = m["totals"]
        assert j["dP"]["value"] == round(float(t["dP_Pa"]), 2)
        # R=定流量口径复算 dP/(Q/60)
        expect_R = round(float(t["dP_Pa"]) / (float(t["Q_inlet_total_L_min"]) / 60.0), 1)
        assert j["resistance"]["value"] == expect_R
        assert "定流量" in j["resistance"]["口径"]

    @pytest.mark.skipif(not CT_BASE_OK, reason="P0_CT_BASE 未配置")
    def test_pC_anatomy_metrics(self, client):
        j = client.get("/api/metrics/pC").get_json()
        sp = os.path.join(PIPE, "webapp", "cases", "pC", "case_stats-pC-v4.json")
        s = json.load(open(sp, encoding="utf-8"))
        assert j["anatomy"]["cells"] == s["cells"] == 14242
        assert j["cfd_status"] == "待结果回传"

    @pytest.mark.skipif(not CT_BASE_OK, reason="P0_CT_BASE 未配置")
    def test_pA_manifest_contract_consistency(self, client):
        """指标口径与 run_all 契约汇编口径一致（assemble_contract 口径注记）。"""
        import run_all as RA
        j = client.get("/api/metrics/pA").get_json()
        # 契约汇编口径注记：定流量（Run-A dP/Q）——与指标卡 ΔP 标签同口径
        assert "Run-A" in j["dP"]["口径"]
        assert RA.assemble_contract(
            {"totals": {"dP_Pa": 18.45, "Q_inlet_total_L_min": 15.0,
                        "flow_share_L_pct": 51.9, "flow_share_R_pct": 48.1},
             "wss": {"mean_Pa": 0.011, "p95_Pa": 0.054}}, "A", "v5"
        )[0]["metrics"]["dP_baseline_Pa"] == 18.45
