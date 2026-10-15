#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T17 弹窗授权工作流测试（三问字段校验 / consent 落档 / 路由矩阵分级放行 / fail-closed）。

覆盖任务书 §验收第 2 条（≥8 用例）：
  1. 三问字段校验 ×3（数据主体 / 处理位置 / 数据保留）+ 来源声明必填
  2. consent 落档断言（/api/upload 与 /api/consent 两条路，字段逐项对齐 v1 契约）
  3. fail-closed：云形态无 consent 记录必拦
  4. m2-cloud 他人数据无 authorization_ref 必拦
  5. m2-cloud 本人 + 云端 opt-in 放行
  6. PII FAIL 不被弹窗放行
  7. m1-local 现状不回归（无 consent 也放行）
  8. 合成 demo 云形态直通（现状不变）
  9. 『仅本次会话（跑完即删）』清理语义

运行：py -X utf8 -m pytest tests/test_consent.py -v
依赖：flask、pytest（与 test_api.py 同）；本文件不需要 CT 资产（无 skip）。
"""
import io
import json
import os
import sys

import pytest

PIPE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "code", "pipeline"))
if PIPE not in sys.path:
    sys.path.insert(0, PIPE)

try:
    import server as SRV  # noqa: E402
except ImportError:
    pytest.skip("server/flask 不可用（可选 Web 控制台后端未安装），跳过 T17 授权测试",
                allow_module_level=True)

DISCLAIMER = "分析结果仅供科研与康复参考，非诊断依据，非医疗器械。"


# ---------------------------------------------------------------- 夹具与工具
@pytest.fixture()
def env(tmp_path):
    """两形态隔离环境（独立 state_dir，互不干扰、不污染仓库 out/）。"""
    m1 = SRV.ServerConfig(mode="m1-local", state_dir=str(tmp_path / "m1"))
    cloud = SRV.ServerConfig(mode="m2-cloud", state_dir=str(tmp_path / "cloud"))
    return {"m1": m1, "cloud": cloud,
            "m1c": SRV.build_app(m1).test_client(),
            "cloudc": SRV.build_app(cloud).test_client()}


def _mk_case(cfg, cid="pX1", **extra):
    """登记一个"上传病例"（kind=upload，真实患者数据语义）到注册表。"""
    rec = {"case_id": cid, "kind": "upload", "prefix": cid, "case_name": "v1",
           "label": "授权测试病例 " + cid, "dicom_dir": "",
           "out_dir": os.path.join(cfg.state_dir, "cases", cid),
           "status": "segmented", "synthetic": False,
           "created": SRV.now_iso(), "updated": SRV.now_iso()}
    rec.update(extra)
    os.makedirs(rec["out_dir"], exist_ok=True)
    reg = SRV.load_registry(cfg)
    reg[cid] = rec
    SRV.save_registry(cfg, reg)
    return rec


def _write_consent(rec, pii_scan="pass", **over):
    """直接落一条 consent_record.json（模拟"已通过弹窗授权"的病例）。"""
    fields = {"data_subject": "self", "source_declaration": "本人 2026-09 CT（已脱敏）",
              "authorization_ref": "", "processing_scope": "cloud_optin",
              "retention": "days:7"}
    fields.update(over)
    crec = SRV.build_consent_record(rec["case_id"], fields, pii_scan=pii_scan)
    SRV.save_consent_record(rec, crec)
    return crec


def _upload(cli, consent=None, n=2):
    files = [(io.BytesIO(b"DICM"), "s%d.dcm" % i) for i in range(n)]
    data = {"files": files}
    if consent is not None:
        data["consent"] = json.dumps(consent, ensure_ascii=False)
    return cli.post("/api/upload", data=data, content_type="multipart/form-data")


# ================================================================ 1. 三问字段校验（×3+）
class TestConsentFieldValidation:
    def test_subject_invalid_400(self, env):
        r = env["m1c"].post("/api/consent", json={
            "case_id": "pX1", "data_subject": "路人甲",
            "processing_scope": "cloud_optin", "retention": "days:7",
            "source_declaration": "x"})
        assert r.status_code == 400
        assert "数据主体" in r.get_json()["error"]

    def test_processing_scope_invalid_400(self, env):
        r = env["m1c"].post("/api/consent", json={
            "case_id": "pX1", "data_subject": "self",
            "processing_scope": "上传到微信群", "retention": "days:7",
            "source_declaration": "x"})
        assert r.status_code == 400
        assert "处理位置" in r.get_json()["error"]

    def test_retention_invalid_400_and_whitelist(self):
        # N 仅允许 1/7/30；不提供永久保留
        assert SRV._parse_retention("days:5") is None
        assert SRV._parse_retention("permanent") is None
        assert SRV._parse_retention("") is None
        assert SRV._parse_retention("session_only") == "session_only"
        assert SRV._parse_retention("仅本次会话（跑完即删）") == "session_only"
        assert SRV._parse_retention("保留1天") == "days:1"
        assert SRV._parse_retention("days:30") == "days:30"
        ok, err = SRV.parse_consent_fields({"data_subject": "self",
                                            "processing_scope": "local_only",
                                            "retention": "days:5"})
        assert ok is None and "数据保留" in err

    def test_source_declaration_required_unless_demo(self):
        ok, err = SRV.parse_consent_fields({"data_subject": "self",
                                            "processing_scope": "local_only",
                                            "retention": "days:7"})
        assert ok is None and "来源声明必填" in err
        ok2, err2 = SRV.parse_consent_fields({"data_subject": "demo",
                                              "processing_scope": "local_only",
                                              "retention": "days:7"})
        assert err2 == "" and ok2["data_subject"] == "demo"

    def test_ui_labels_accepted(self):
        """弹窗中文选项文案 → 规范枚举（前端文案与落档字段解耦）。"""
        ok, err = SRV.parse_consent_fields({"data_subject": "已获授权的他人CT",
                                            "processing_scope": "允许云端处理",
                                            "retention": "保留 30 天",
                                            "source_declaration": "家属 CT",
                                            "authorization_ref": "AUTH-2026-101"})
        assert err == ""
        assert ok == {"data_subject": "authorized_third_party",
                      "source_declaration": "家属 CT",
                      "authorization_ref": "AUTH-2026-101",
                      "processing_scope": "cloud_optin",
                      "retention": "days:30"}

    def test_upload_rejects_invalid_consent_blob(self, env):
        """带非法 consent 的上传 400 且不落病例、不落盘（校验先于写文件）。"""
        r = _upload(env["m1c"], consent={"data_subject": "self",
                                         "processing_scope": "local_only",
                                         "retention": "days:5",
                                         "source_declaration": "x"})
        assert r.status_code == 400
        assert "校验失败" in r.get_json()["error"]
        up = os.path.join(env["m1"].state_dir, "uploads")
        assert (not os.path.isdir(up)) or not os.listdir(up)


# ================================================================ 2. consent 落档断言
class TestConsentRecordPersistence:
    def test_record_written_on_upload(self, env):
        """上传真实 CT 携带三问 → 病例输出目录落 consent_record.json（v1 契约逐字段）。"""
        consent = {"data_subject": "self",
                   "source_declaration": "本人 2026-09 鼻窦 CT（已自行脱敏）",
                   "authorization_ref": "", "processing_scope": "local_only",
                   "retention": "days:7"}
        r = _upload(env["m1c"], consent=consent)
        assert r.status_code == 200
        cid = r.get_json()["case_id"]
        rec = SRV.get_case_record(env["m1"], cid)
        p = SRV.consent_record_path(rec)
        assert p.endswith("consent_record.json") and os.path.isfile(p)
        d = json.load(open(p, encoding="utf-8"))
        assert d["schema"] == "consent_record/v1"
        assert d["prompt_version"] == "T17-v1"
        assert d["case_id"] == cid
        assert d["data_subject"] == "self"
        assert d["source_declaration"] == consent["source_declaration"]
        assert d["authorization_ref"] == ""
        assert d["processing_scope"] == "local_only"
        assert d["retention"] == "days:7"
        assert d["ui_lang"] == "zh-CN"
        # 假 DICOM 头无法解析 → PII 闸门如实拦截，记录照落（pii_scan=fail，留证）
        assert d["pii_scan"] == "fail"
        assert r.get_json().get("status") == "blocked"
        # 与产物同目录（同 out_dir），可随 manifest 追溯
        assert os.path.dirname(p) == rec["out_dir"]
        assert os.path.isfile(os.path.join(rec["out_dir"], "manifest-progress.json"))

    def test_consent_endpoint_writes_and_reports(self, env):
        rec = _mk_case(env["m1"], "pX9")
        r = env["m1c"].post("/api/consent", json={
            "case_id": "pX9", "data_subject": "本人CT",
            "source_declaration": "本人 CT", "authorization_ref": "",
            "processing_scope": "仅本机处理", "retention": "session_only"})
        assert r.status_code == 200
        b = r.get_json()
        assert b["schema"] == "consent_record/v1"
        assert b["prompt_version"] == "T17-v1"
        assert b["record"]["retention"] == "session_only"
        assert b["record"]["processing_scope"] == "local_only"
        assert b["release"]["ok"] is True and b["release"]["basis"] == "local"
        assert b["disclaimer"] == DISCLAIMER
        assert os.path.isfile(SRV.consent_record_path(rec))
        g = env["m1c"].get("/api/consent/pX9").get_json()
        assert g["has_record"] is True
        assert g["record"]["schema"] == "consent_record/v1"
        assert g["disclaimer"] == DISCLAIMER

    def test_consent_endpoint_unknown_case_404(self, env):
        r = env["m1c"].post("/api/consent", json={
            "case_id": "pNope", "data_subject": "self",
            "processing_scope": "local_only", "retention": "days:7",
            "source_declaration": "x"})
        assert r.status_code == 404

    def test_health_declares_consent_workflow(self, env):
        j = env["m1c"].get("/api/health").get_json()
        assert j["consent_workflow"] == "T17-v1"
        assert j["consent_disclaimer"] == DISCLAIMER


# ================================================================ 3. 路由矩阵（云形态分级放行 + fail-closed）
class TestRoutingMatrixCloud:
    def test_fail_closed_no_record(self, env):
        """兜底：consent 记录缺失 → 一律按拦截处理（旧硬闸语义保留）。"""
        _mk_case(env["cloud"], "pX1")
        r = env["cloudc"].get("/api/progress/pX1")
        assert r.status_code == 403
        assert "数据边界" in r.get_json()["error"]
        assert "fail-closed" in r.get_json()["error"]
        g = env["cloudc"].get("/api/consent/pX1").get_json()
        assert g["has_record"] is False
        assert g["release"] == {"ok": False, "basis": "fail_closed",
                                "reason": g["release"]["reason"]}
        assert "consent 授权记录缺失" in g["release"]["reason"]

    def test_cloud_third_party_without_ref_blocked(self, env):
        """m2-cloud：他人数据无 authorization_ref → ⛔ 缺少授权凭证。"""
        rec = _mk_case(env["cloud"], "pX2")
        _write_consent(rec, data_subject="authorized_third_party",
                       authorization_ref="", processing_scope="cloud_optin")
        r = env["cloudc"].get("/api/progress/pX2")
        assert r.status_code == 403
        assert "缺少授权凭证" in r.get_json()["error"]
        g = env["cloudc"].get("/api/consent/pX2").get_json()
        assert g["release"]["basis"] == "missing_ref"

    def test_cloud_self_optin_released(self, env):
        """m2-cloud：本人 + 云端 opt-in → 放行（写 consent 后即可访问）。"""
        rec = _mk_case(env["cloud"], "pX3")
        _write_consent(rec, data_subject="self", processing_scope="cloud_optin",
                       retention="days:7")
        r = env["cloudc"].get("/api/progress/pX3")
        assert r.status_code == 200
        assert r.get_json()["consent"]["data_subject"] == "self"
        assert env["cloudc"].get("/api/consent/pX3").get_json()["release"]["ok"] is True

    def test_cloud_authorized_with_ref_released(self, env):
        rec = _mk_case(env["cloud"], "pX4")
        _write_consent(rec, data_subject="authorized_third_party",
                       authorization_ref="授权书-20261001.pdf",
                       processing_scope="cloud_optin")
        assert env["cloudc"].get("/api/progress/pX4").status_code == 200

    def test_cloud_local_only_scope_blocked(self, env):
        """处理位置=仅本机处理 → 不得在云形态访问。"""
        rec = _mk_case(env["cloud"], "pX5")
        _write_consent(rec, processing_scope="local_only")
        r = env["cloudc"].get("/api/progress/pX5")
        assert r.status_code == 403
        assert "未授权云端处理" in r.get_json()["error"]

    def test_pii_fail_not_released_by_consent(self, env):
        """红线：PII 头扫描 FAIL 的病例，即使有"本人+云端 opt-in"记录也不放行。"""
        rec = _mk_case(env["cloud"], "pX6", status="blocked",
                       pii={"pass": False, "fail_count": 1, "files": 1,
                            "fails": [["a.dcm", "PatientName", "<值已隐藏,长度4>",
                                       "PatientName 非空"]]},
                       gate="PII 头扫描（run_all 同款闸门）", exit_code=2)
        _write_consent(rec, data_subject="self", processing_scope="cloud_optin",
                       pii_scan="pass")   # 记录谎称 pass，也必须被拦
        r = env["cloudc"].get("/api/progress/pX6")
        assert r.status_code == 403
        assert "PII" in r.get_json()["error"]
        g = env["cloudc"].get("/api/consent/pX6").get_json()
        assert g["release"]["basis"] == "pii_fail"

    def test_cloud_record_for_other_case_blocked(self, env):
        """记录 case_id 与病例不符（篡改/串档）→ 拦截。"""
        rec = _mk_case(env["cloud"], "pX7")
        crec = _write_consent(rec, processing_scope="cloud_optin")
        crec["case_id"] = "pX8"
        SRV.save_consent_record(rec, crec)
        g = env["cloudc"].get("/api/consent/pX7").get_json()
        assert g["release"]["ok"] is False and g["release"]["basis"] == "record_mismatch"

    def test_cloud_demo_synthetic_passthrough(self, env):
        """合成 demo：无 consent 记录也直通（现状不变）。"""
        assert env["cloudc"].get("/viewer/demo").status_code == 200
        assert env["cloudc"].get("/api/metrics/demo").status_code == 200
        demo = [c for c in env["cloudc"].get("/api/cases").get_json()["cases"]
                if c["case_id"] == "demo"][0]
        assert demo["synthetic"] is True

    def test_cloud_builtin_real_case_still_403(self, env):
        """内置真实病例（无 consent 记录）云形态仍 403——基线语义不回归。"""
        for path in ("/viewer/pA", "/api/metrics/pA", "/api/qc/pA", "/api/progress/pA"):
            r = env["cloudc"].get(path)
            assert r.status_code == 403, path
            txt = (r.get_json(silent=True) or {}).get("error") or r.get_data(as_text=True)
            assert "数据边界" in txt, path


# ================================================================ 4. m1-local 现状不回归 + 会话清理
class TestLocalAndSessionPurge:
    def test_local_case_without_consent_still_accessible(self, env):
        """m1-local 真实数据本形态即放行（无 consent 记录也不收紧；现状语义保留）。"""
        _mk_case(env["m1"], "pX10")
        r = env["m1c"].get("/api/progress/pX10")
        assert r.status_code == 200
        assert r.get_json()["consent"] is None

    def test_local_pii_blocked_case_progress_visible(self, env):
        """m1-local：PII 拦截卡的进度可见性不变（不得因弹窗改造收紧为 403）。"""
        _mk_case(env["m1"], "pX11", status="blocked", exit_code=2,
                 gate="PII 头扫描（run_all 同款闸门）",
                 gate_failures=["PII 头扫描 FAIL ×1：PatientName 非空"])
        r = env["m1c"].get("/api/progress/pX11")
        assert r.status_code == 200
        assert r.get_json()["status"] == "blocked"
        assert "PII" in r.get_json()["gate_failures"][0]

    def test_session_only_purge_removes_case(self, env):
        """『仅本次会话（跑完即删）』：跑完（链结束）即删本例数据 + 注册表条目。"""
        cfg = env["m1"]
        _mk_case(cfg, "pX12")
        up_dir = os.path.join(cfg.state_dir, "uploads", "20260101-000000")
        os.makedirs(up_dir, exist_ok=True)
        open(os.path.join(up_dir, "a.dcm"), "wb").write(b"DICM")
        rec = SRV.get_case_record(cfg, "pX12")
        rec["dicom_dir"] = up_dir
        reg = SRV.load_registry(cfg)
        reg["pX12"] = rec
        SRV.save_registry(cfg, reg)
        _write_consent(rec, retention="session_only")
        assert SRV._session_purge(cfg, "pX12") is True
        assert not os.path.isdir(rec["out_dir"])
        assert not os.path.isdir(up_dir)
        assert "pX12" not in SRV.load_registry(cfg)
        audit = os.path.join(cfg.state_dir, "consent-audit.jsonl")
        assert os.path.isfile(audit)
        assert "session_only_purge" in open(audit, encoding="utf-8").read()

    def test_session_purge_not_triggered_for_days_retention(self, env):
        cfg = env["m1"]
        rec = _mk_case(cfg, "pX13")
        _write_consent(rec, retention="days:7")
        assert SRV._session_purge(cfg, "pX13") is False
        assert os.path.isdir(rec["out_dir"])
        assert "pX13" in SRV.load_registry(cfg)

    def test_session_purge_skips_non_upload_case(self, env):
        """内置/合成病例即便记录被写成 session_only 也不得删除（保护冻结资产）。"""
        cfg = env["m1"]
        reg = SRV.load_registry(cfg)
        reg["pA"] = {"case_id": "pA", "kind": "builtin", "prefix": "pA",
                     "case_name": "v5", "label": "内置", "dicom_dir": "",
                     "out_dir": os.path.join(cfg.state_dir, "cases", "pA"),
                     "status": "done", "synthetic": False}
        SRV.save_registry(cfg, reg)
        rec = SRV.get_case_record(cfg, "pA")
        _write_consent(rec, retention="session_only")
        assert SRV._session_purge(cfg, "pA") is False
        assert "pA" in SRV.load_registry(cfg)
