# -*- coding: utf-8 -*-
"""
M2.5 合成数据产线 v1 -- 适配层 B：DICOM -> step2 -> OpenFOAM 算例 -> 交付落位

对每个 synth-NNN：
  1. 调 stl_to_dicom.py 生成合成 DICOM 序列（若未生成）；
  2. 调 step2_make_ofcase.py（**不改 step2**，参数与 baseline27/M1 正式链一致：
     --merge-mode largest --voxel-z 0.7，不加 --ext/--iso，即自然鼻孔/出口开口，
     与 run_chain.py 的 step2 调用同款约定）；
  3. 校验产物（Allrun/0/p/0/U/constant/polyMesh/boundary + case_stats）；
  4. 落位交付：out/synth/synth-NNN/case/（OpenFOAM 算例）+ case_stats.json
     + dicom_qc.json + step2.log；状态写 work/status/synth-NNN.json。

step2 的 --out-root 指向沙箱（C:\\qidi-synth-work\\step2out），不污染仓库
out/step2/（文件域纪律）。G: 盘余量不足，重中间产物一律走 C: 沙箱。
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.dirname(HERE)                      # .../code/pipeline
REPO = os.path.dirname(os.path.dirname(PIPELINE))     # .../开源仓库
STL_TO_DICOM = os.path.join(HERE, "stl_to_dicom.py")
STEP2 = os.path.join(PIPELINE, "step2_make_ofcase.py")
VENV_PY = os.path.join(REPO, ".venv", "Scripts", "python.exe")
if not os.path.isfile(VENV_PY):
    VENV_PY = sys.executable

NEED = ["Allrun", os.path.join("0", "p"), os.path.join("0", "U"),
        os.path.join("constant", "transportProperties"),
        os.path.join("constant", "turbulenceProperties"),
        os.path.join("constant", "polyMesh", "boundary"),
        os.path.join("system", "controlDict"),
        os.path.join("system", "fvSchemes"),
        os.path.join("system", "fvSolution")]


def run(cmd, logf):
    t0 = time.time()
    with open(logf, "w", encoding="utf-8", errors="replace") as f:
        r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT)
    return r.returncode, round(time.time() - t0, 1)


def prepare(case, repo, work, force=False):
    out_synth = os.path.join(repo, "code", "pipeline", "out", "synth")
    dicom_dir = os.path.join(work, "dicom", case)
    step2out = os.path.join(work, "step2out")
    status = {"case": case, "t0": time.strftime("%Y-%m-%d %H:%M:%S")}
    os.makedirs(os.path.join(work, "logs"), exist_ok=True)
    os.makedirs(os.path.join(work, "status"), exist_ok=True)

    # ---- 1. DICOM ----
    if force or not os.path.isfile(os.path.join(dicom_dir, "dicom_qc.json")):
        rc, dt = run([VENV_PY, STL_TO_DICOM, "--case", case,
                      "--stl-root", out_synth,
                      "--dicom-root", os.path.join(work, "dicom")],
                     os.path.join(work, "logs", f"{case}-dicom.log"))
        status["dicom_exit"] = rc
        status["dicom_s"] = dt
        if rc != 0:
            status["status"] = "FAIL_DICOM"
            dump(status, work)
            return status
    else:
        status["dicom_exit"] = "cached"

    # ---- 2. step2（禁改 step2；--out-root 指沙箱）----
    nnn = case.split("-")[-1]
    case_dir = os.path.join(step2out, "step2", f"P0-OF-case-synth-{nnn}")
    stats_file = os.path.join(step2out, "step2", f"case_stats-synth-{nnn}.json")
    rc, dt = run([VENV_PY, STEP2,
                  "--dicom-dir", dicom_dir,
                  "--case", nnn,
                  "--case-prefix", "synth",
                  "--out-root", step2out,
                  "--merge-mode", "largest",
                  "--voxel-z", "0.7"],
                 os.path.join(work, "logs", f"{case}-step2.log"))
    status["step2_exit"] = rc
    status["step2_s"] = dt
    if rc != 0:
        status["status"] = "FAIL_STEP2"
        dump(status, work)
        return status
    missing = [rel for rel in NEED
               if not os.path.isfile(os.path.join(case_dir, rel))]
    if missing or not os.path.isfile(stats_file):
        status["status"] = "FAIL_INCOMPLETE"
        status["missing"] = missing + ([] if os.path.isfile(stats_file)
                                       else ["case_stats"])
        dump(status, work)
        return status
    stats = json.load(open(stats_file, encoding="utf-8"))

    # ---- 3. 落位交付 ----
    dst = os.path.join(out_synth, case)
    dst_case = os.path.join(dst, "case")
    if os.path.isdir(dst_case):
        shutil.rmtree(dst_case)
    shutil.copytree(case_dir, dst_case)
    shutil.copy2(stats_file, os.path.join(dst, "case_stats.json"))
    shutil.copy2(os.path.join(dicom_dir, "dicom_qc.json"),
                 os.path.join(dst, "dicom_qc.json"))
    shutil.copy2(os.path.join(work, "logs", f"{case}-step2.log"),
                 os.path.join(dst, "step2.log"))

    status["status"] = "OK"
    status["of_case"] = f"P0-OF-case-synth-{nnn}"
    status["cells"] = stats.get("cells")
    status["patch_face_counts"] = stats.get("patch_face_counts")
    status["inletL_area_mm2"] = (stats.get("inletL") or {}).get("area_mm2")
    status["inletR_area_mm2"] = (stats.get("inletR") or {}).get("area_mm2")
    status["outlet_area_mm2"] = stats.get("outlet_area_mm2")
    status["nostril_at_low"] = stats.get("nostril_at_low")
    status["voxel_mm"] = stats.get("voxel_mm")
    status["volume_regression_ratio"] = stats.get("volume_regression_ratio")
    status["runA_flux_Lmin"] = stats.get("runA_flux_Lmin")
    dump(status, work)
    return status


def dump(status, work):
    p = os.path.join(work, "status", f"{status['case']}.json")
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(status, f, ensure_ascii=False, indent=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--repo", required=True, help="开源仓库根（含 code/pipeline）")
    ap.add_argument("--work", required=True, help="C: 沙箱根")
    ap.add_argument("--force", action="store_true", help="重算 DICOM")
    args = ap.parse_args()
    out_synth = os.path.join(args.repo, "code", "pipeline", "out", "synth")
    cases = sorted(d for d in os.listdir(out_synth)
                   if d.startswith("synth-")) if args.all else [args.case]
    for c in cases:
        st = prepare(c, args.repo, args.work, force=args.force)
        print(f"[prepare] {c}: {st['status']} cells={st.get('cells')} "
              f"patches={st.get('patch_face_counts')} "
              f"A_L/R={st.get('inletL_area_mm2')}/{st.get('inletR_area_mm2')} "
              f"nostril_at_low={st.get('nostril_at_low')} "
              f"volreg={st.get('volume_regression_ratio')} "
              f"({st.get('step2_s')}s)", flush=True)


if __name__ == "__main__":
    main()
