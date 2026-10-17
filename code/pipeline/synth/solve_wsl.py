# -*- coding: utf-8 -*-
"""
M2.5 合成数据产线 v1 -- WSL 求解编排（Run-A 定流量 15 L/min）

流程（复刻 M1 trackC baseline27 链路，MAXPAR 2 防 OOM）：
  push  : C:\\qidi-synth-work\\step2out\\step2\\P0-OF-case-synth-NNN
          -> WSL ~/synth-solve/（经 /mnt/c，WSL 侧原生 ext4 落盘求解）
  solve : wsl -d Ubuntu -- bash <sandbox>/wsl_solve_synth.sh <cases...>
          Allrun = checkMesh + simpleFoam(1500, residualControl p/U 1e-4)
          + foamToVTK -latestTime
  pull  : log.checkMesh / log.simpleFoam / allrun.log + VTK/ 回拉
          -> C:\\qidi-synth-work\\wslpull\\synth-NNN\\；dpcheck 在 WSL 内
          用 stdlib python3 跑（synth_dpcheck.py），输出 dpcheck.txt

用法：
  python solve_wsl.py push   [--cases synth-001 ...]   # 缺省=全部 OK 例
  python solve_wsl.py solve  [--cases ...]
  python solve_wsl.py pull   [--cases ...]
  python solve_wsl.py all    [--cases ...]             # push+solve+pull
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DPCHECK = os.path.join(HERE, "synth_dpcheck.py")     # 部署到 WSL 用
WSL = ["wsl", "-d", "Ubuntu", "--"]
SANDBOX_WSL = "/mnt/g/qidicode/target/tmp/nasal-hack"   # 沙箱在 WSL 侧的挂载点
WSL_SOLVE_DIR = "synth-solve"


def wsl_run(cmd, timeout=28800):
    t0 = time.time()
    r = subprocess.run(WSL + ["bash", "-lc", cmd], capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       timeout=timeout)
    return r.returncode, r.stdout, r.stderr, time.time() - t0


def ok_cases(work):
    out = []
    d = os.path.join(work, "status")
    for f in sorted(os.listdir(d)):
        if f.endswith(".json"):
            st = json.load(open(os.path.join(d, f), encoding="utf-8"))
            if st.get("status") == "OK":
                out.append(st["case"])
    return out


def of_case(case):
    return "P0-OF-case-" + case


def push(case, work):
    name = of_case(case)
    src = os.path.join(work, "step2out", "step2", name)
    if not os.path.isdir(src):
        return False, f"missing {src}"
    rc, out, err, _ = wsl_run(
        f'test -d ~/{WSL_SOLVE_DIR}/{name} && echo EXISTS || echo MISSING')
    if "EXISTS" in out:
        return True, "exists"
    rc, out, err, dt = wsl_run(
        f'mkdir -p ~/{WSL_SOLVE_DIR} && '
        f'cp -r /mnt/c/qidi-synth-work/step2out/step2/{name} '
        f'~/{WSL_SOLVE_DIR}/ && echo PUSH_OK')
    return rc == 0 and "PUSH_OK" in out, f"{dt:.0f}s {out.strip()} {err.strip()[:200]}"


def solve(cases):
    names = [of_case(c) for c in cases]
    script = f"{SANDBOX_WSL}/wsl_solve_synth.sh"
    cmd = f"bash {script} " + " ".join(names)
    print(f"[solve] launching: {cmd}", flush=True)
    rc, out, err, dt = wsl_run(cmd)
    print(out)
    if err.strip():
        print("[stderr]", err[:2000])
    print(f"[solve] rc={rc} wall={dt:.0f}s")
    return rc


def pull(case, work):
    name = of_case(case)
    dst = os.path.join(work, "wslpull", case)
    os.makedirs(dst, exist_ok=True)
    got = []
    for item in ("log.simpleFoam", "log.checkMesh", "allrun.log"):
        rc, out, err, dt = wsl_run(
            f'test -f ~/{WSL_SOLVE_DIR}/{name}/{item} && '
            f'cp ~/{WSL_SOLVE_DIR}/{name}/{item} '
            f'/mnt/c/qidi-synth-work/wslpull/{case}/ && echo OK || echo MISS')
        if "OK" in out:
            got.append(item)
        else:
            print(f"[pull] {case} {item}: {out.strip()}")
    # VTK 目录（metrics 提取用；提取后可删）
    rc, out, err, dt = wsl_run(
        f'test -d ~/{WSL_SOLVE_DIR}/{name}/VTK && '
        f'cp -r ~/{WSL_SOLVE_DIR}/{name}/VTK '
        f'/mnt/c/qidi-synth-work/wslpull/{case}/ 2>/dev/null; '
        f'ls /mnt/c/qidi-synth-work/wslpull/{case}/VTK 2>/dev/null | head -3')
    # dpcheck（WSL 内 stdlib python3）
    rc, out, err, dt = wsl_run(
        f'cp {SANDBOX_WSL}/synth_dpcheck.py ~/{WSL_SOLVE_DIR}/ 2>/dev/null; '
        f'cd ~/{WSL_SOLVE_DIR} && python3 synth_dpcheck.py {name} 2>&1')
    with open(os.path.join(dst, "dpcheck.txt"), "w", encoding="utf-8") as f:
        f.write(out + err)
    has_vtk = os.path.isdir(os.path.join(dst, "VTK"))
    print(f"[pull] {case}: logs={got} vtk={has_vtk} "
          f"dpcheck={out.strip()[:120]}")
    return has_vtk


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["push", "solve", "pull", "all"])
    ap.add_argument("--work", required=True, help="C: 沙箱根")
    ap.add_argument("--cases", nargs="*", default=None)
    args = ap.parse_args()
    cases = args.cases or ok_cases(args.work)
    print(f"[solve_wsl] mode={args.mode} cases={cases}", flush=True)
    if args.mode in ("push", "all"):
        for c in cases:
            ok, msg = push(c, args.work)
            print(f"[push] {c} ok={ok} {msg}", flush=True)
    if args.mode in ("solve", "all"):
        solve(cases)
    if args.mode in ("pull", "all"):
        for c in cases:
            pull(c, args.work)


if __name__ == "__main__":
    main()
