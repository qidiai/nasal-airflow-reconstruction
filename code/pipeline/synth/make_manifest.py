# -*- coding: utf-8 -*-
"""
M2.5 synth 数据集根目录 md5 清单（对齐 baseline27 MD5-MANIFEST 格式）：
脚本 md5（synth 产线 + 复用的 step2）+ 10 例交付文件 md5。
用法: python make_manifest.py --repo ...
"""
import argparse
import hashlib
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.dirname(HERE)

SYNTH_SCRIPTS = [
    ("gen_geometry.py", os.path.join(HERE, "gen_geometry.py")),
    ("stl_to_dicom.py", os.path.join(HERE, "stl_to_dicom.py")),
    ("prepare_case.py", os.path.join(HERE, "prepare_case.py")),
    ("solve_wsl.py", os.path.join(HERE, "solve_wsl.py")),
    ("finalize_case.py", os.path.join(HERE, "finalize_case.py")),
    ("check_monotonic.py", os.path.join(HERE, "check_monotonic.py")),
    ("synth_dpcheck.py", os.path.join(HERE, "synth_dpcheck.py")),
    ("wsl_solve_synth.sh", os.path.join(HERE, "wsl_solve_synth.sh")),
    ("step2_make_ofcase.py(复用未改)", os.path.join(PIPELINE, "step2_make_ofcase.py")),
]


def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    args = ap.parse_args()
    out_synth = os.path.join(args.repo, "code", "pipeline", "out", "synth")
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"# synth 数据集 md5 清单 {now}", "",
             f"根目录：`{out_synth}`", "",
             "## 脚本（venv 同环境生成）", "", "| 脚本 | md5 |", "|---|---|"]
    for label, p in SYNTH_SCRIPTS:
        lines.append(f"| {label} | {md5(p) if os.path.isfile(p) else 'MISSING'} |")
    lines += ["", "## 交付文件", "", "| case | 文件 | bytes | md5 |",
              "|---|---|---|---|"]
    man = {"generated_at": now, "scripts": {}, "files": {}}
    for label, p in SYNTH_SCRIPTS:
        if os.path.isfile(p):
            man["scripts"][label] = md5(p)
    for case in sorted(d for d in os.listdir(out_synth)
                       if d.startswith("synth-")):
        d = os.path.join(out_synth, case)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            p = os.path.join(d, fn)
            if os.path.isfile(p):
                m = md5(p)
                lines.append(f"| {case} | {fn} | {os.path.getsize(p)} | {m} |")
                man["files"].setdefault(case, {})[fn] = m
    for fn in sorted(os.listdir(out_synth)):
        p = os.path.join(out_synth, fn)
        if os.path.isfile(p) and fn not in ("MD5-MANIFEST.md",
                                            "MD5-MANIFEST.json"):
            m = md5(p)
            lines.append(f"| (root) | {fn} | {os.path.getsize(p)} | {m} |")
            man["files"].setdefault("(root)", {})[fn] = m
    with open(os.path.join(out_synth, "MD5-MANIFEST.md"), "w",
              encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(out_synth, "MD5-MANIFEST.json"), "w",
              encoding="utf-8", newline="\n") as f:
        json.dump(man, f, ensure_ascii=False, indent=1)
    print(f"[manifest] -> {os.path.join(out_synth, 'MD5-MANIFEST.md')} "
          f"({len(man['files'])} cases/roots)")


if __name__ == "__main__":
    main()
