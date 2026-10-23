#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""split_validity 侧车生成器（R-10 / 裁定3 §2 第 1–2 项）。

为什么要有这个文件：`metrics_v2.json` 的左右字段与契约里的 `split_L/R_pct` 都**不可当解剖值读**，
但**不能**直接往在用 JSON 里加 `split_valid=false`——那会让已登记 md5 失配，违反发布门①⑥。
所以作废标记走**本侧车**：在用产物一字节不动，作废声明单独成件。

两类作废理由（reason 封闭枚举，禁止自由文本）：
  septum_grouping_failed  鼻中隔分组失效：`left_min_mm2` 恒 0 ⇒ 左右对称度 1.0 是算术副产物
  imposed_by_area_BC      左右分流由入口边界条件按开口面积设定（step2_make_ofcase.py:1548
                          `Qi = Q_TOTAL * A / (A_L + A_R)`），后处理只是把输入假设复述一遍

输出**确定**（不含时间戳），因此本文件自身可通过发布门⑨ 的字节级重放。

用法：
    python split_validity.py                 # 生成 docs/contracts/split-validity.json
    python split_validity.py --check         # 重算并比对现存件（不一致则退出码 3）
    python split_validity.py --out 某路径    # 生成到别处（自测/临时）
    python split_validity.py --replica-check # 现场比对仓内副本与仓外母本 md5（只打印，不写文件）

侧车为什么**不放** replica 比对结果（2026-10-23 GAP-7 裁定）：
    比对结果依赖本机是否存在仓外资产。若写进侧车，干净克隆里 `--check` 必红，
    直接破坏发布门⑨「可重放要给哈希级对照」。所以侧车只放**机器中立**的
    replica_check_policy（期望值+算法+出处），结果由 --replica-check 现场算出、只打印。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))          # code/pipeline
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))               # 仓库根
OUT_ROOT = os.path.join(HERE, "out")                        # code/pipeline/out（.gitignore:23）
DEFAULT_TARGET = os.path.join(HERE, "docs", "contracts", "split-validity.json")

# 仓内副本 ↔ 仓外母本（GAP-7：只登记机器中立的期望值，不登记本机比对结论）
REPLICA_IN_REPO = "code/pipeline/out/step1/metrics_v2.json"
REPLICA_EXTERNAL_REL = "阶段1-三维重建/metrics_v2.json"   # 相对 ROOT，不写绝对路径
REPLICA_EXPECTED_MD5 = "c5759af68d72b5fc6274bc38016de93a"
REPLICA_EXPECTED_BYTES = 668
REPLICA_NOTE = "结果现场计算，不入本文件，以保证字节可重放"

REASONS = {
    "septum_grouping_failed": {
        "why": "鼻中隔分组失效，left_* 恒为 0",
        # {src} 必须用**本条自己的来源文件**实例化（2026-10-22 自审修正：原先硬编码 metrics_v2.json，
        # 导致 pB/pN 两条的出处指向 pA 的文件）。
        "ref_template": "{src}：left_min_mm2 == 0.0 且 left_right_asymmetry == 1.0",
        "read_as": "该字段不可用（前端显示『—』）",
    },
    "imposed_by_area_BC": {
        "why": "左右流量由入口边界条件按开口面积设定，非求解得到的生理分流",
        "ref_template": "code/pipeline/step2_make_ofcase.py:1548（Qi = Q_TOTAL * A / (A_L + A_R)）；:1563-1564 同式，代码自注『Run-A…按开口面积比例分配，声明为建模假设（审计R2）』；本条读数取自 {src}",
        "read_as": "只能读作『按面积输入的假设』，不得读作患者真实分流",
    },
}

# step1 里被判作废的左右字段
STEP1_SPLIT_FIELDS = (
    "left_min_mm2",
    "left_min_layer",
    "right_min_mm2",
    "right_min_layer",
    "left_right_asymmetry",
)


def md5_of(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def case_from_step1_name(name: str) -> str:
    """metrics_v2.json → pA；metrics_pB_v2.json → pB；metrics_pN_v2.json → pN。
    其它一律用**去后缀的文件名**做键，禁止返回空串（空 case 键会让前端查不到又默认有效）。"""
    if name == "metrics_v2.json":
        return "pA"
    body = name[len("metrics_") : -len(".json")] if name.startswith("metrics_") else name[: -len(".json")]
    body = body.split("_", 1)[0].strip()
    return body or name[: -len(".json")]


def iter_step1_metrics():
    d = os.path.join(OUT_ROOT, "step1")
    if not os.path.isdir(d):
        return
    for fn in sorted(os.listdir(d)):
        if fn.startswith("metrics") and fn.endswith(".json"):
            yield os.path.join(d, fn), fn


def iter_contracts():
    d = os.path.join(OUT_ROOT, "postprocess")
    if not os.path.isdir(d):
        return
    for fn in sorted(os.listdir(d)):
        if fn.startswith("contract-") and fn.endswith(".json"):
            yield os.path.join(d, fn), fn


def iter_baseline27():
    d = os.path.join(OUT_ROOT, "baseline27")
    if not os.path.isdir(d):
        return
    for sub in sorted(os.listdir(d)):
        p = os.path.join(d, sub, "metrics.json")
        if os.path.isfile(p):
            yield p, f"baseline27/{sub}"


def entry(case: str, field: str, reason: str, observed, src: str) -> dict:
    spec = REASONS[reason]
    return {
        "case": case,
        "field": field,
        "valid": False,
        "reason": reason,
        "why": spec["why"],
        "ref": spec["ref_template"].replace("{src}", src),
        "read_as": spec["read_as"],
        "observed": observed,
        "source_file": src,
    }


def build() -> dict:
    entries = []

    for path, fn in iter_step1_metrics():
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        case = case_from_step1_name(fn)
        rel = os.path.relpath(path, REPO_ROOT).replace("\\", "/")
        for field in STEP1_SPLIT_FIELDS:
            if field in data:
                entries.append(
                    entry(case, field, "septum_grouping_failed", data[field], rel)
                )

    for path, fn in iter_contracts():
        with open(path, encoding="utf-8-sig") as fh:
            data = json.load(fh)
        metrics = data.get("metrics", {})
        case = fn[len("contract-") : -len(".json")]
        rel = os.path.relpath(path, REPO_ROOT).replace("\\", "/")
        for field in ("split_L_pct", "split_R_pct"):
            if field in metrics:
                entries.append(
                    entry(case, field, "imposed_by_area_BC", metrics[field], rel)
                )

    for path, tag in iter_baseline27():
        with open(path, encoding="utf-8-sig") as fh:
            data = json.load(fh)
        totals = data.get("totals", {})
        rel = os.path.relpath(path, REPO_ROOT).replace("\\", "/")
        for field in ("flow_share_L_pct", "flow_share_R_pct"):
            if field in totals:
                entries.append(
                    entry(tag, field, "imposed_by_area_BC", totals[field], rel)
                )

    inputs = []
    for path, _ in iter_step1_metrics():
        inputs.append(path)
    for path, _ in iter_contracts():
        inputs.append(path)
    for path, _ in iter_baseline27():
        inputs.append(path)

    index = {}
    for e in entries:
        index.setdefault(e["case"], []).append(e["field"])

    return {
        "schema": "split_validity/v1",
        "generated_by": "code/pipeline/split_validity.py",
        "note": "在用产物（metrics_v2.json / contract-*.json / baseline27 metrics.json）一字节未改；本文件是作废声明的侧车。无时间戳，输出确定，可按发布门⑨ 做字节级重放。",
        "rule_ref": "裁定书（三）§2 第 1–2 项（R-10 范围修正：左右字段与 split 在所有 Run-A 算例上默认 false）",
        "reason_enum": sorted(REASONS),
        "defaults": {
            "unlisted_case": "unknown（本侧车不推断未登记的算例）",
            "unlisted_field": "unknown（缺键不得当作有效）",
        },
        # 机器中立：只写期望值与算法出处，不写本机比对结论（GAP-7）
        "replica_check_policy": {
            "in_repo_ref": REPLICA_IN_REPO,
            "external_ref": REPLICA_EXTERNAL_REL,
            "expected_md5": REPLICA_EXPECTED_MD5,
            "expected_bytes": REPLICA_EXPECTED_BYTES,
            "evaluated_by": "python code/pipeline/split_validity.py --replica-check",
            "note": REPLICA_NOTE,
        },
        "inputs": [
            {
                "file": os.path.relpath(p, REPO_ROOT).replace("\\", "/"),
                "bytes": os.path.getsize(p),
                "md5": md5_of(p),
            }
            for p in sorted(set(inputs))
        ],
        "entries_count": len(entries),
        "cases_count": len(index),
        "index": index,
        "entries": [
            {"key": f"{e['case']}|{e['field']}", **e} for e in sorted(entries, key=lambda x: (x["case"], x["field"]))
        ],
    }


def render(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=False) + "\n"


def resolve_external_root(cli_root=None):
    """仓外母本根 ROOT 三级解析：--root → 环境变量 P0_TOOL_ROOT → 仓库父目录（带 WARNING）。

    ROOT 是「阶段1-三维重建」「阶段2-CFD算例包」等目录的上级（即 P0-鼻塞设计工具）。
    解析不出或路径不可达时**不抛异常**（fail-soft），由调用方输出 unknown。
    """
    if cli_root:
        return os.path.abspath(cli_root), "--root"
    env = os.environ.get("P0_TOOL_ROOT", "").strip()
    if env:
        return os.path.abspath(env), "环境变量 P0_TOOL_ROOT"
    fallback = os.path.dirname(REPO_ROOT)     # 仓库的父目录：开源仓库 ↔ 阶段* 同级
    print("[WARNING] 未指定 --root 也未设置 P0_TOOL_ROOT，回退到仓库父目录：" + fallback)
    return fallback, "fallback(仓库父目录)"


def replica_check(cli_root=None):
    """现场比对仓内副本与仓外母本：只打印 identical / divergent / unknown，**不写任何文件**。"""
    root, how = resolve_external_root(cli_root)
    in_repo = os.path.join(REPO_ROOT, *REPLICA_IN_REPO.split("/"))
    external = os.path.join(root, *REPLICA_EXTERNAL_REL.split("/"))

    print("[replica-check] ROOT = %s（来源：%s）" % (root, how))
    print("[replica-check] in_repo  = %s" % REPLICA_IN_REPO)
    print("[replica-check] external = %s" % REPLICA_EXTERNAL_REL)
    print("[replica-check] expected md5=%s bytes=%d" % (REPLICA_EXPECTED_MD5, REPLICA_EXPECTED_BYTES))

    state = "unknown"
    if os.path.isfile(in_repo) and os.path.isfile(external):
        m_in, m_ext = md5_of(in_repo), md5_of(external)
        b_in, b_ext = os.path.getsize(in_repo), os.path.getsize(external)
        print("[replica-check] in_repo  md5=%s bytes=%d" % (m_in, b_in))
        print("[replica-check] external md5=%s bytes=%d" % (m_ext, b_ext))
        ok = (m_in == m_ext == REPLICA_EXPECTED_MD5
              and b_in == b_ext == REPLICA_EXPECTED_BYTES)
        state = "identical" if ok else "divergent"
    else:
        missing = [p for p in (in_repo, external) if not os.path.isfile(p)]
        print("[replica-check] 不可达：%s" % ("、".join(missing),))
    print("[replica-check] result: %s" % state)
    # identical / unknown 视为正常（干净克隆本来就 unknown）；divergent 才是异常
    return 1 if state == "divergent" else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 split_validity 侧车（只读在用产物）")
    ap.add_argument("--out", default=DEFAULT_TARGET)
    ap.add_argument("--check", action="store_true", help="与现存件比对，不一致退出码 3")
    ap.add_argument("--replica-check", action="store_true",
                    help="现场比对仓内副本与仓外母本 md5（只打印，不写文件）")
    ap.add_argument("--root", default=None,
                    help="仓外母本根（--replica-check 用；缺省 → P0_TOOL_ROOT → 仓库父目录）")
    a = ap.parse_args()

    if a.replica_check:
        return replica_check(a.root)

    text = render(build())
    if a.check:
        if not os.path.isfile(a.out):
            print(f"[FAIL] 侧车不存在：{a.out}")
            return 3
        with open(a.out, encoding="utf-8") as fh:
            old = fh.read()
        if old == text:
            print(f"[OK] 字节级一致（{len(text.encode('utf-8'))} B）：{a.out}")
            return 0
        print(f"[FAIL] 现存侧车与重算结果不一致：{a.out}")
        return 3

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print(f"[WROTE] {a.out}  {os.path.getsize(a.out):,} B")
    return 0


if __name__ == "__main__":
    sys.exit(main())
