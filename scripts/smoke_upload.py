#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""上传链路端到端冒烟：真实 HTTP 走 server.py 的完整 Web 流程。

============================================================
默认使用合成数据（scripts/make_synthetic_ct.py 生成），
仅用于冒烟验证，不代表真实病例结果。
============================================================

流程（全部真实 HTTP，urllib 标准库）：
  1. 启动 server.py（子进程，独立 --state-dir，不污染现有病例库）
  2. GET  /api/health                    等服务就绪
  3. POST /api/upload（multipart 全序列 .dcm）→ 建病例 + step1
  4. POST /api/run/<case_id> {"solve":"local","mode":<mode>} → 202
  5. 轮询 GET /api/progress/<case_id> 直到 done/failed
  6. GET  /api/metrics/<case_id>         记录关键指标
  7. GET  /viewer/<case_id>              检查查看器页（iframe / 待解算卡）
  8. 收尾：杀服务子进程，打印 JSON 实测摘要

用法：
  python scripts/smoke_upload.py                       # standard 档（完整契约）
  python scripts/smoke_upload.py --mode quick          # quick 档（部分导出 viewer）
  python scripts/smoke_upload.py --mode both           # 两档都跑
退出码：0 全部通过；1 任一步失败。
"""

import argparse
import glob
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
VENV_PY = (os.path.join(REPO, ".venv", "Scripts", "python.exe") if os.name == "nt"
           else os.path.join(REPO, ".venv", "bin", "python"))
PYTHON = VENV_PY if os.path.isfile(VENV_PY) else sys.executable
SERVER = os.path.join(REPO, "code", "pipeline", "server.py")
GEN_CT = os.path.join(REPO, "scripts", "make_synthetic_ct.py")


def http_json(req, timeout=960):
    """发请求，返回 (http_status, parsed_json_or_None, raw_text)。"""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", errors="replace")
            try:
                return r.status, json.loads(raw), raw
            except json.JSONDecodeError:
                return r.status, None, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(raw), raw
        except json.JSONDecodeError:
            return e.code, None, raw


def multipart_upload(url, field, files):
    boundary = "----smoke" + uuid.uuid4().hex
    chunks = []
    for path in files:
        with open(path, "rb") as f:
            data = f.read()
        head = (f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{field}"; '
                f'filename="{os.path.basename(path)}"\r\n'
                f"Content-Type: application/dicom\r\n\r\n").encode("utf-8")
        chunks += [head, data, b"\r\n"]
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(chunks)
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    return http_json(req)


def wait_health(base, timeout=90):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            st, js, _ = http_json(urllib.request.Request(base + "/api/health"), timeout=5)
            if st == 200:
                return time.time() - t0
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1.0)
    raise RuntimeError(f"server 启动超时（{timeout}s 内 /api/health 未就绪）")


def poll_done(base, case_id, timeout=900, interval=5.0, log=print):
    t0 = time.time()
    last = ""
    while time.time() - t0 < timeout:
        st, js, _ = http_json(urllib.request.Request(f"{base}/api/progress/{case_id}"))
        if st != 200:
            raise RuntimeError(f"/api/progress HTTP {st}")
        status = str(js.get("status", ""))
        if status != last:
            log(f"    [progress] {int(time.time()-t0):4d}s  status={status}")
            last = status
        if status in ("done", "blocked", "handover") or status.startswith("failed"):
            return status, time.time() - t0, js
        time.sleep(interval)
    raise RuntimeError(f"轮询超时（{timeout}s 未结束，最后 status={last}）")


def run_one_mode(base, case_id, mode, result, log=print):
    """POST /api/run + 轮询 + metrics + viewer，结果写进 result[mode]。"""
    body = json.dumps({"solve": "local", "mode": mode}).encode("utf-8")
    req = urllib.request.Request(f"{base}/api/run/{case_id}", data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    st, js, _ = http_json(req)
    entry = {"run_http": st, "run_resp": js}
    log(f"  [{mode}] POST /api/run -> {st} {js}")
    if st != 202:
        entry["ok"] = False
        result[mode] = entry
        return False
    status, secs, prog = poll_done(base, case_id, log=log)
    entry.update(final_status=status, chain_seconds=round(secs, 1))
    if status != "done":
        entry["ok"] = False
        entry["gate_failures"] = prog.get("gate_failures")
        result[mode] = entry
        return False

    st, metrics, _ = http_json(urllib.request.Request(f"{base}/api/metrics/{case_id}"))
    entry["metrics_http"] = st
    if st == 200 and metrics:
        entry["metrics_source"] = metrics.get("source") or ""
        entry["metrics_mode"] = metrics.get("mode") or ""
        entry["dP_baseline_Pa"] = (metrics.get("dP") or {}).get("value")
        entry["split_L_pct"] = (metrics.get("split") or {}).get("L")
        entry["split_R_pct"] = (metrics.get("split") or {}).get("R")
        entry["resistance_Pa_per_Ls"] = (metrics.get("resistance") or {}).get("value")
        entry["wss_mean_Pa"] = (metrics.get("wss") or {}).get("mean")
        entry["partial"] = metrics.get("partial")
    else:
        entry["metrics_error"] = (metrics or {}).get("error") if metrics else st

    st, _, raw = http_json(urllib.request.Request(f"{base}/viewer/{case_id}"))
    entry["viewer_http"] = st
    entry["viewer_iframe"] = ("<iframe" in raw) if raw else False
    entry["viewer_pending_card"] = ("待解算" in raw) if raw else False
    entry["total_seconds"] = round(time.time() - t0, 1)
    entry["ok"] = (st == 200 and entry.get("metrics_http") == 200)
    result[mode] = entry
    log(f"  [{mode}] status=done 链耗时={entry['chain_seconds']}s "
        f"metrics_http={entry.get('metrics_http')} "
        f"dP={entry.get('dP_baseline_Pa')}Pa "
        f"viewer_http={st} iframe={entry['viewer_iframe']}")
    return True


def main():
    ap = argparse.ArgumentParser(description="上传链路端到端冒烟（合成数据，非真实病例）")
    ap.add_argument("--ct-dir", default=os.path.join(REPO, "out", "synthetic-ct"),
                    help="DICOM 目录（缺省先用 make_synthetic_ct.py 生成合成 CT）")
    ap.add_argument("--port", type=int, default=8123)
    ap.add_argument("--state-dir", default=None,
                    help="server 状态目录（缺省 out/e2e-state-<时间戳>，全新不污染）")
    ap.add_argument("--mode", choices=["standard", "quick", "both"], default="standard")
    ap.add_argument("--timeout", type=int, default=900, help="单档链轮询超时秒")
    args = ap.parse_args()

    log = lambda *a: print(*a, flush=True)  # noqa: E731
    result = {"note": "本冒烟使用合成数据，不代表真实病例结果",
              "port": args.port, "steps": []}
    ok_all = True

    # ---- 0. 合成 CT 就绪 ----
    files = sorted(glob.glob(os.path.join(args.ct_dir, "*.dcm")))
    if len(files) < 2:
        log(f"[0] 未发现 DICOM（{args.ct_dir}）——先生成合成 CT")
        t0 = time.time()
        rc = subprocess.call([PYTHON, GEN_CT, "--out", args.ct_dir])
        if rc != 0:
            log("[FAIL] 合成 CT 生成失败")
            return 1
        files = sorted(glob.glob(os.path.join(args.ct_dir, "*.dcm")))
        result["steps"].append({"step": "make_synthetic_ct",
                                "seconds": round(time.time() - t0, 1),
                                "files": len(files)})
    log(f"[0] DICOM 序列：{len(files)} 个文件 @ {args.ct_dir}")

    # ---- 1. 启动 server ----
    state_dir = args.state_dir or os.path.join(
        REPO, "out", "e2e-state-" + time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(state_dir, exist_ok=True)
    srv_log = open(os.path.join(state_dir, "server.stdout.log"), "w", encoding="utf-8")
    proc = subprocess.Popen([PYTHON, SERVER, "--port", str(args.port),
                             "--state-dir", state_dir],
                            stdout=srv_log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{args.port}"
    try:
        secs = wait_health(base)
        result["steps"].append({"step": "server_start", "seconds": round(secs, 1)})
        log(f"[1] server 已就绪（{secs:.1f}s）state-dir={state_dir}")

        # ---- 2. 上传 ----
        t0 = time.time()
        st, js, raw = multipart_upload(base + "/api/upload", "files", files)
        up_secs = time.time() - t0
        log(f"[2] POST /api/upload -> HTTP {st}（{up_secs:.1f}s，含 step1）")
        log(f"    响应：{json.dumps(js, ensure_ascii=False)[:400]}")
        result["steps"].append({"step": "upload", "http": st,
                                "seconds": round(up_secs, 1), "resp": js})
        if st != 200 or not js or js.get("status") != "segmented":
            log("[FAIL] 上传未成功建病例")
            result["ok"] = False
            print(json.dumps(result, ensure_ascii=False, indent=1))
            return 1
        case_id = js["case_id"]
        result["case_id"] = case_id

        # ---- 3. 分档跑链 ----
        modes = ["standard", "quick"] if args.mode == "both" else [args.mode]
        for mode in modes:
            log(f"[3] 启动 {mode} 档全链（solve=local）")
            if not run_one_mode(base, case_id, mode, result, log=log):
                ok_all = False
                log(f"[FAIL] {mode} 档链未达成 done+metrics")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        srv_log.close()

    result["ok"] = ok_all
    log("\n==== 冒烟摘要（JSON） ====")
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
