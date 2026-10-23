#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""solver_backend.py — 求解后端抽象（M3 切栈）

后端语义
--------
``backend = custom | openfoam | auto``

- **custom**：自研 FlowScope（``code/solver/target/release/flowscope[.exe]``，
  M2 产物）。直接读算例 ``constant/polyMesh`` + ``0/``，Run-A 定流量模式；
  求解产物 ``fields_<iter>.vtk`` + §11 口径指标（stdout）。本模块把产物整理成
  既有结果目录契约——``VTK/<case>_<iter>/internal.vtu`` +
  ``后处理/metrics.json``——使 downstream ``run_all`` 的契约汇编 / ``step5``
  完全无感（行为不变性）。
- **openfoam**：保留为对拍基准（WSL ``Allrun`` → ``simpleFoam``），**不删除**。
  L3 回归与 Run-B 大网格仍需它提供真值（见 ``equivalence-report.md`` §2.2 /
  conditions-ledger G-C3）。
- **auto**（默认）：custom 可执行文件存在即用 custom，否则回退 openfoam。

Run-B 路由（已知边界）
----------------------
自研求解器的 Run-B 等压模式在 pA 满分辨率网格（269,913 cells）上失稳——鼻阀
高 Péclet 速度峰经 HbyA→压力→速度指数放大，三种离散均不能阻止（机制已表征，
见 ``code/solver/docs/equivalence-report.md`` §2.2 与 conditions-ledger G-C3b）。
因此：

- **Run-A**：一律优先 custom（L1 契约 pA +1.61% / pB −0.63%，均在 ±2% 内）。
- **Run-B**：按算例规模路由——``cells <= RUNB_CUSTOM_MAX_CELLS``（默认 50,000）
  走 custom；更大网格走 openfoam（若可用），否则如实回退 custom 并在报告中
  标注风险。用户显式 ``backend=custom`` 时仍尝试 custom，失败如实上报，不隐瞒。

默认行为（auto）与本路由规则同时写入 ``pipeline/legacy/openfoam-reference/README.md``
与根目录 ``NOTICE``。

文件域（M3）：本文件为新增抽象层，不改 ``solver/``、``docs/contracts/``、``out/``、
``data-governance/``、``webapp/``。
"""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

# ---------------------------------------------------------------- 常量与路径
HERE = os.path.dirname(os.path.abspath(__file__))
CODE = os.path.dirname(HERE)                       # code/
REPO = os.path.dirname(CODE)                       # repo root
SOLVER_DIR = os.path.join(CODE, "solver")
SOLVER_TOOLS = os.path.join(SOLVER_DIR, "tools")

RHO_AIR = 1.2          # kg/m3（契约 §11 后处理口径）
MU_AIR = 2.16e-5       # Pa·s（契约 §11：rho * nu = 1.2 * 1.8e-5，仅 WSS 用）
# 注：上面两个是**后处理口径常量**，不是 metrics.inputs 的取值来源。
# inputs.nu_m2_s 一律从该次求解用的 case 文件回读（见 build_inputs_provenance）。
DEFAULT_MAX_ITER = 1500
DEFAULT_WRITE_EVERY = 500
DEFAULT_P_RELTOL = 1e-3

# Run-B 路由阈值：pN-v6B（26,884 cells）通过；pA-v1B（269,913 cells）失稳。
RUNB_CUSTOM_MAX_CELLS = 50_000

VALID_BACKENDS = ("auto", "custom", "openfoam")


def log(msg):
    print(f"[solver_backend] {msg}", flush=True)


# ---------------------------------------------------------------- 后端探测
def flowscope_path():
    """返回 FlowScope 可执行文件路径（不存在返回空串）。

    优先级：环境变量 ``FLOWSCOPE_BIN`` → ``solver/target/release/flowscope[.exe]``。
    """
    env = os.environ.get("FLOWSCOPE_BIN", "")
    if env and os.path.isfile(env):
        return env
    exe = "flowscope.exe" if os.name == "nt" else "flowscope"
    p = os.path.join(SOLVER_DIR, "target", "release", exe)
    return p if os.path.isfile(p) else ""


def custom_available():
    return bool(flowscope_path())


def openfoam_available():
    """粗探测：PATH 中的 simpleFoam/foamExec 或 WSL 可执行（不发起昂贵调用）。"""
    for prog in ("simpleFoam", "blockMesh", "foamExec", "ifoam"):
        if shutil.which(prog):
            return True
    return bool(shutil.which("wsl"))


def resolve_backend(requested=None):
    """解析实际后端名。``requested`` 可为 auto/custom/openfoam/None。"""
    req = (requested or os.environ.get("FLOWSCOPE_BACKEND") or "auto").strip().lower()
    if req not in VALID_BACKENDS:
        raise ValueError(f"未知求解后端 {req!r}（允许 {VALID_BACKENDS}）")
    if req == "auto":
        return "custom" if custom_available() else "openfoam"
    return req


def backend_status(requested=None):
    """供 manifest / 看板落盘的探测快照（不抛异常）。"""
    backend = resolve_backend(requested)
    return {
        "requested": requested or os.environ.get("FLOWSCOPE_BACKEND") or "auto",
        "resolved": backend,
        "custom_available": custom_available(),
        "flowscope": flowscope_path(),
        "openfoam_available": openfoam_available(),
        "runb_custom_max_cells": RUNB_CUSTOM_MAX_CELLS,
    }


def choose_run_b_backend(cells, requested=None):
    """Run-B 后端路由（见模块 docstring）。返回 ``custom`` 或 ``openfoam``。"""
    req = (requested or os.environ.get("FLOWSCOPE_BACKEND") or "auto").strip().lower()
    if req not in VALID_BACKENDS:
        raise ValueError(f"未知求解后端 {req!r}（允许 {VALID_BACKENDS}）")
    if req != "auto":
        return req
    try:
        cells = int(cells)
    except (TypeError, ValueError):
        return "openfoam" if openfoam_available() else "custom"
    if cells <= RUNB_CUSTOM_MAX_CELLS:
        return "custom"
    return "openfoam" if openfoam_available() else "custom"


# ---------------------------------------------------------------- 求解器调用
def build_custom_command(case_dir, out_dir, max_iter=DEFAULT_MAX_ITER,
                         write_every=DEFAULT_WRITE_EVERY,
                         p_reltol=DEFAULT_P_RELTOL, quiet=False):
    exe = flowscope_path()
    if not exe:
        raise FileNotFoundError(
            "FlowScope 可执行文件不存在：请先构建 "
            "`cargo build --release`（code/solver）或设置 FLOWSCOPE_BIN")
    cmd = [exe, "run", os.path.abspath(case_dir),
           "--max-iter", str(int(max_iter)),
           "--write-every", str(int(write_every)),
           "--p-reltol", str(p_reltol),
           "--out", os.path.abspath(out_dir)]
    if quiet:
        cmd.append("--quiet")
    return cmd


def _run_process(cmd, log_path, progress=None, tag="custom", stall_limit=1200,
                 poll_sec=10):
    """启动求解进程并写日志；心跳看护（日志 ``Time = N`` 无增长超时终止）。

    返回 ``(rc, last_time)``；超时 rc=-998，启动异常 rc=-999。
    """
    os.makedirs(os.path.dirname(os.path.abspath(log_path)) or ".", exist_ok=True)
    if progress:
        progress(f"[{tag}] $ " + " ".join(cmd))
    try:
        fh = open(log_path, "w", encoding="utf-8", errors="replace")
        proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT)
    except Exception as e:  # noqa: BLE001
        if progress:
            progress(f"[{tag}] !!! 启动异常：{e!r}")
        return -999, None
    last_step, stall = -1.0, 0
    try:
        while proc.poll() is None:
            time.sleep(poll_sec)
            step = parse_last_time(log_path)
            if step is not None and step > last_step:
                last_step = step
                stall = 0
                if progress:
                    progress(f"[{tag}] 求解进行：Time = {step:g}")
            else:
                stall += poll_sec
                if stall_limit and stall >= stall_limit:
                    proc.kill()
                    proc.wait()
                    if progress:
                        progress(f"[{tag}] !!! 看护触发：{stall_limit}s 无步数增长"
                                 "——已终止（日志保留）")
                    return -998, parse_last_time(log_path)
    finally:
        try:
            fh.close()
        except Exception:  # noqa: BLE001
            pass
    return proc.poll(), parse_last_time(log_path)


def parse_last_time(log_path):
    """解析求解日志最后一个 ``Time = N``。"""
    try:
        size = os.path.getsize(log_path)
        with open(log_path, "rb") as f:
            f.seek(max(0, size - 262144))
            tail = f.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    steps = re.findall(r"Time\s*=\s*([\d.eE+-]+)", tail)
    return float(steps[-1]) if steps else None


# ---------------------------------------------------------------- 指标解析
def parse_contract_metrics(log_path):
    """解析 FlowScope stdout 的 §11 指标段（ASCII 键，容忍中文乱码）。"""
    try:
        txt = open(log_path, "rb").read().decode("utf-8", errors="replace")
    except OSError:
        return {}
    d = {"patches": {}, "split": {}}
    for ln in txt.splitlines():
        m = re.match(r"patch\s+(\w+)\s*:\s*sum\(phi\)\s*=\s*([-\d.eE+]+) m3/s\s+"
                     r"A\s*=\s*([-\d.eE+]+) m2\s+p_mean\(kin\)\s*=\s*([-\d.eE+]+)", ln)
        if m:
            d["patches"][m.group(1)] = {
                "Q_signed_m3_s": float(m.group(2)),
                "area_m2": float(m.group(3)),
                "p_mean_kin": float(m.group(4)),
            }
            continue
        m = re.match(r"dP \(rho\*p_in - p_out\)\s*=\s*([-\d.eE+]+) Pa", ln)
        if m:
            d["dP_Pa"] = float(m.group(1))
            continue
        m = re.match(r"split\s+(\w+)\s*:\s*([-\d.eE+]+)", ln)
        if m:
            d["split"][m.group(1)] = float(m.group(2))
            continue
        m = re.match(r"WSS \(1st-order voxel est\):\s*mean\s+([-\d.eE+]+) Pa,\s*"
                     r"max\s+([-\d.eE+]+) Pa", ln)
        if m:
            d["wss_mean"] = float(m.group(1))
            d["wss_max"] = float(m.group(2))
            continue
        m = re.match(r"iterations\s*:\s*(\d+)", ln)
        if m:
            d["iterations"] = int(m.group(1))
            continue
        m = re.match(r"stop reason\s*:\s*(.+)$", ln)
        if m:
            d["stop_reason"] = m.group(1).strip()
            continue
        # dP 稳定早停三元组（2026-10-20 新增；上面的人读 stop_reason 保持原样）
        # 注意：机器行键名是下划线 `stop_reason`，人读行是空格 `stop reason`——
        # 两条正则互不匹配（空格 vs 下划线），故可安全并存。
        m = re.match(r"stop_reason\s*:\s*(\S+)", ln)
        if m:
            d["stop_reason_code"] = m.group(1).strip()
            continue
        m = re.match(r"stop_iter\s*:\s*(\d+)", ln)
        if m:
            d["stop_iter"] = int(m.group(1))
            continue
        m = re.match(r"dp_band_pct\s*:\s*(\S+)", ln)
        if m:
            # NaN（未评估过，如 residualControl 早停或 dP 判据不适用）→ None
            # 单位 = **百分数数值**：0.1896 表示 0.19%，不是 0.1896%
            try:
                fv = float(m.group(1))
            except ValueError:
                fv = None
            d["dp_band_pct"] = None if (fv != fv) else fv
            continue
        m = re.match(r"run mode\s*:\s*(.+)$", ln)
        if m:
            d["run_mode"] = m.group(1).strip()
            continue
        m = re.match(r"final residuals\s*:\s*(.+)$", ln)
        if m:
            d["final_residuals"] = m.group(1).strip()
            continue
        m = re.match(r"continuity \(1/s\)\s*:\s*local\s+([-\d.eE+]+)\s+global\s+([-\d.eE+]+)", ln)
        if m:
            d["continuity_local"] = float(m.group(1))
            d["continuity_global"] = float(m.group(2))
            continue
        m = re.search(r"cells\s+(\d+)\s*\|\s*faces\s+(\d+)\s*\(internal\s+(\d+)\)", ln)
        if m:
            d["cells"] = int(m.group(1))
            d["faces"] = int(m.group(2))
            d["internal_faces"] = int(m.group(3))
    return d


# ---------------------------------------------------------------- VTK 适配
def _read_flowscope_vtk(path):
    """流式读取 FlowScope legacy VTK（UNSTRUCTURED_GRID + VTK_POLYHEDRON）。

    返回 ``(points, conn, U, p)``：``conn`` 为 (ncell, 8) 六面体节点索引，
    与 cell_data 行序一一对应（solver 按 polyMesh cell 序写出）。
    """
    import numpy as np

    pts = None
    conn = None
    U = None
    p = None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for ln in f:
            if ln.startswith("POINTS"):
                n = int(ln.split()[1])
                pts = np.empty((n, 3), dtype=np.float64)
                for i in range(n):
                    v = f.readline().split()
                    pts[i] = (float(v[0]), float(v[1]), float(v[2]))
            elif ln.startswith("CELLS"):
                parts = ln.split()
                ncell = int(parts[1])
                conn = np.empty((ncell, 8), dtype=np.int64)
                for c in range(ncell):
                    vals = [int(x) for x in f.readline().split()]
                    k = 0
                    nf = vals[k]
                    k += 1
                    uniq = []
                    seen = set()
                    for _ in range(nf):
                        npf = vals[k]
                        k += 1
                        for _j in range(npf):
                            nid = vals[k]
                            k += 1
                            if nid not in seen:
                                seen.add(nid)
                                uniq.append(nid)
                    if len(uniq) != 8:
                        raise ValueError(
                            f"cell {c} 有 {len(uniq)} 个节点（仅支持体素六面体；"
                            f"文件 {path}）")
                    conn[c] = uniq
            elif ln.startswith("CELL_DATA"):
                ncell = int(ln.split()[1])
                hdr = f.readline()
                if not hdr.startswith("VECTORS"):
                    raise ValueError(f"CELL_DATA 首段非 VECTORS U：{hdr!r}")
                U = np.empty((ncell, 3), dtype=np.float64)
                for i in range(ncell):
                    v = f.readline().split()
                    U[i] = (float(v[0]), float(v[1]), float(v[2]))
                hdr = f.readline()
                if not hdr.startswith("SCALARS"):
                    raise ValueError(f"U 段后非 SCALARS p：{hdr!r}")
                f.readline()  # LOOKUP_TABLE default
                p = np.empty(ncell, dtype=np.float64)
                for i in range(ncell):
                    p[i] = float(f.readline().split()[0])
                break
    if pts is None or conn is None or U is None or p is None:
        raise ValueError(f"VTK 解析不完整：{path}")
    return pts, conn, U, p


def vtk_to_vtu(vtk_path, vtu_path):
    """把 FlowScope legacy VTK 转成 step5 可读的 VTU（hexahedron + cell U/p）。"""
    import meshio
    import numpy as np

    pts, conn, U, p = _read_flowscope_vtk(vtk_path)
    mesh = meshio.Mesh(
        points=np.asarray(pts, dtype=np.float64),
        cells=[("hexahedron", np.asarray(conn, dtype=np.int64))],
        cell_data={"U": [np.asarray(U, dtype=np.float64)],
                   "p": [np.asarray(p, dtype=np.float64)]},
    )
    os.makedirs(os.path.dirname(os.path.abspath(vtu_path)) or ".", exist_ok=True)
    meshio.write(vtu_path, mesh, file_format="vtu")
    return vtu_path


def _wss_stats(case_dir, vtk_path, parsed, geom=None):
    """WSS 统计：按契约 §11 逐壁面复算 ``tau = mu*|(I-nn^T)U_c|/d_n``。

    单元中心取 VTK 六个面/八个角点的均值（体素六面体下与 solver 的 tet 分解
    重心一致）；``d_n = |C_f - C_c|``（真实法向距离）。该实现与 solver 自带
    §11 指标（mean/max）逐位一致，且避免旧 ``round6_extract.cell_centres``
    只累计 owner 面导致的偏心偏差（D-7 的 −5~−9% 口径差来源之一）。
    失败则回退日志 mean/max（p95 记 NaN，如实披露）。
    """
    import numpy as np

    try:
        mesh_dir = os.path.join(case_dir, "constant", "polyMesh")
        if SOLVER_TOOLS not in sys.path:
            sys.path.insert(0, SOLVER_TOOLS)
        import outlet_probe as op

        if geom is not None:
            pts, conn, U = geom
        else:
            pts, conn, U, _p = _read_flowscope_vtk(vtk_path)
        cc = np.asarray(pts, dtype=np.float64)[conn].mean(axis=1)
        pts_np = np.asarray(pts, dtype=np.float64)
        faces = op.read_faces(os.path.join(mesh_dir, "faces"))
        owner = np.asarray(op.read_int_field(os.path.join(mesh_dir, "owner")),
                           dtype=np.int64)
        bnd = op.read_boundary(os.path.join(mesh_dir, "boundary"))
        walls = next(b for b in bnd if b[0] == "walls")
        _, nf, sf = walls
        tau = []
        for f in range(sf, sf + nf):
            nodes = faces[f]
            a = pts_np[nodes]
            s = np.zeros(3)
            for i in range(len(nodes)):
                s += 0.5 * np.cross(a[i], a[(i + 1) % len(nodes)])
            mag = np.linalg.norm(s)
            if mag <= 0:
                continue
            nh = s / mag
            uc = U[owner[f]]
            tang = uc - float(np.dot(uc, nh)) * nh
            dn = np.linalg.norm(a.mean(axis=0) - cc[owner[f]])
            tau.append(MU_AIR * np.linalg.norm(tang) / max(dn, 1e-300))
        arr = np.sort(np.asarray(tau, dtype=np.float64))
        n = len(arr)
        if n == 0:
            raise ValueError("walls patch 无有效面")
        return {
            "mean_Pa": float(arr.mean()),
            "median_Pa": float(arr[n // 2]),
            "p95_Pa": float(arr[int(0.95 * n)]),
            "max_Pa": float(arr[-1]),
            "n_faces": n,
            "source": "exact §11 recompute (hex cell centres, dn=|Cf-Cc|)",
        }
    except Exception as e:  # noqa: BLE001
        return {
            "mean_Pa": parsed.get("wss_mean", float("nan")),
            "p95_Pa": float("nan"),
            "max_Pa": parsed.get("wss_max", float("nan")),
            "source": f"flowscope log fallback ({e.__class__.__name__}: {e})",
        }


def _final_vtk(out_dir):
    cands = glob.glob(os.path.join(out_dir, "fields_*.vtk"))
    if not cands:
        return None, None

    def _it(p):
        m = re.search(r"fields_(\d+)\.vtk$", os.path.basename(p))
        return int(m.group(1)) if m else -1

    p = max(cands, key=_it)
    return p, _it(p)


def read_case_transport_properties(case_dir):
    """从**该次求解实际使用的 case 文件**读 nu（求解器真正读的就是它）。

    返回 ``(nu, tp_path, error)``：解析成功时 error 为 ``None``；失败时 nu 为
    ``None`` 且 error 说明原因。调用方**不得**在失败时回落到任何硬编码默认值。
    """
    if not case_dir:
        return None, "", "case_dir 未提供"
    tp = os.path.join(case_dir, "constant", "transportProperties")
    if not os.path.isfile(tp):
        return None, tp, "找不到 %s" % tp
    try:
        with open(tp, "r", encoding="utf-8", errors="replace") as f:
            txt = f.read()
    except OSError as e:
        return None, tp, "读不了 %s：%s" % (tp, e)
    m = re.search(r"^\s*nu\s+\[[^\]]*\]\s*([0-9.eE+\-]+)\s*;", txt, re.M)
    if not m:
        return None, tp, "%s 里没有可解析的 'nu [..] <value>;' 行" % tp
    try:
        return float(m.group(1)), tp, None
    except ValueError as e:
        return None, tp, "%s 的 nu 值不可解析：%s" % (tp, e)


def build_inputs_provenance(case_dir, vtk_dir=None, extra=None, solver_backend="custom"):
    """构造 ``metrics.inputs``——nu/rho/mu 一律**从 case 文件回读**，无默认值回落。

    规则（裁定五）：
    - ``nu_m2_s``：解析该 case 的 ``constant/transportProperties`` 的 nu 行；
      解析失败 ⇒ ``None``，并在返回的 warnings 里记一条，**不猜、不回落**。
    - ``rho_kg_m3``：不可压缩算例的 transportProperties 不声明 rho；若 case 里
      确实有 rho 行就用它（``rho_source`` = case 路径），否则用契约 §11 的
      后处理口径常量 1.2，并在 ``rho_source`` 里写明是契约常量（不伪装成读回）。
    - ``mu_Pa_s``：= rho * nu；nu 不可解析时同样为 ``None``。

    返回 ``(inputs_dict, warnings_list)``。
    """
    nu, tp_path, err = read_case_transport_properties(case_dir)
    warnings = []
    if err:
        warnings.append(
            "inputs.nu_m2_s=null：%s（按裁定五禁止回落到硬编码默认值）" % err)

    rho = None
    rho_source = "case:%s" % tp_path
    if tp_path and os.path.isfile(tp_path):
        try:
            with open(tp_path, "r", encoding="utf-8", errors="replace") as f:
                txt = f.read()
            m = re.search(r"^\s*rho\s+(\[[^\]]*\]\s*)?([0-9.eE+\-]+)\s*;", txt, re.M)
            if m:
                rho = float(m.group(2))
        except (OSError, ValueError):
            rho = None
    if rho is None:
        rho = RHO_AIR
        rho_source = "contract_constant:rho=1.2（case 文件不声明 rho，不可压缩）"

    mu = rho * nu if (nu is not None and rho is not None) else None
    if mu is None and nu is None:
        warnings.append("inputs.mu_Pa_s=null：nu 不可解析，mu 无法计算")

    inputs = {
        "vtk_dir": os.path.abspath(vtk_dir) if vtk_dir else None,
        "rho_kg_m3": rho,
        "rho_source": rho_source,
        "nu_m2_s": nu,
        "nu_source": tp_path if tp_path else "unavailable",
        "mu_Pa_s": mu,
        "geom_units": "m",
        "solver_backend": solver_backend,
    }
    if solver_backend == "custom":
        inputs["flowscope"] = flowscope_path()
    if extra:
        inputs.update(extra)
    return inputs, warnings


def build_metrics(case_dir, out_dir, log_path, prefix="", case="", tag=""):
    """汇编 ``后处理/metrics.json`` + ``VTK/<tag>/internal.vtu``（契约形状）。"""
    import numpy as np

    parsed = parse_contract_metrics(log_path)
    vtk_path, it = _final_vtk(out_dir)
    if vtk_path is None:
        raise FileNotFoundError(f"{out_dir} 无 fields_*.vtk（求解未完成？）")

    pts, conn, U, p = _read_flowscope_vtk(vtk_path)
    umax = float(np.linalg.norm(U, axis=1).max())

    tag = tag or f"P0-case-{case or os.path.basename(case_dir)}_{it}"
    vtu = os.path.join(out_dir, "VTK", tag, "internal.vtu")
    if not (os.path.isfile(vtu) and os.path.getmtime(vtu) >= os.path.getmtime(vtk_path)):
        vtk_to_vtu(vtk_path, vtu)

    # 面数：§11 patch 行不含面数，从 flux 行（Time = it flux(name) ... (patch N faces)）提取
    face_counts = {}
    try:
        txt = open(log_path, "rb").read().decode("utf-8", errors="replace")
        for m in re.finditer(r"flux\((\w+)\s*\) sum\(phi\) = [-\d.eE+]+  \(patch (\d+) faces\)", txt):
            face_counts[m.group(1)] = int(m.group(2))
    except OSError:
        pass

    patches = {}
    p_in_num = 0.0
    p_in_den = 0.0
    q_in = 0.0
    for name, rec in parsed.get("patches", {}).items():
        q = rec["Q_signed_m3_s"]
        area = rec["area_m2"]
        q_abs = abs(q)
        patches[name] = {
            "n_cells": float(face_counts.get(name, 0)),
            "area_mm2": area * 1e6,
            "Q_signed_m3_s": q,
            "Q_L_min": q_abs * 60000.0,
            "p_mean_Pa": RHO_AIR * rec["p_mean_kin"],
        }
        if name.startswith("inlet"):
            n = face_counts.get(name, 1)
            p_in_num += rec["p_mean_kin"] * n
            p_in_den += n
            q_in += q_abs

    p_in = (RHO_AIR * p_in_num / p_in_den) if p_in_den else float("nan")
    p_out = RHO_AIR * parsed.get("patches", {}).get("outlet", {}).get("p_mean_kin", 0.0)
    dP = parsed.get("dP_Pa")
    if dP is None:
        dP = p_in - p_out if p_in_den else float("nan")
    q_total = q_in
    outlet = parsed.get("patches", {}).get("outlet", {}).get("Q_signed_m3_s", float("nan"))
    closure = abs(q_total - outlet) / q_total * 100.0 if q_total else float("nan")
    split = parsed.get("split", {})
    split_l = split.get("inletL", float("nan")) * 100.0
    split_r = split.get("inletR", float("nan")) * 100.0
    if split_l != split_l and q_total:  # NaN fallback
        ql = patches.get("inletL", {}).get("Q_L_min", 0.0)
        qr = patches.get("inletR", {}).get("Q_L_min", 0.0)
        tot = ql + qr
        split_l, split_r = (ql / tot * 100.0, qr / tot * 100.0) if tot else (0.0, 0.0)

    wss = _wss_stats(case_dir, vtk_path, parsed, geom=(pts, conn, U))

    # inputs 段：nu/rho/mu 从该次求解实际使用的 case 文件回读（裁定五），
    # 解析失败写 null + warnings，禁止回落到任何硬编码默认值。
    inputs, inputs_warnings = build_inputs_provenance(case_dir, vtk_dir=out_dir)

    metrics = {
        "inputs": inputs,
        "files": {
            "internal": vtu,
            "fields_vtk": vtk_path,
            "log": os.path.abspath(log_path),
        },
        "patches": patches,
        "totals": {
            "dP_Pa": dP,
            "p_inlet_Pa": p_in,
            "p_outlet_Pa": p_out,
            "Q_inlet_total_m3_s": q_total,
            "Q_inlet_total_L_min": q_total * 60000.0,
            "Q_outlet_L_min": abs(outlet) * 60000.0 if outlet == outlet else float("nan"),
            "flow_share_L_pct": split_l,
            "flow_share_R_pct": split_r,
            "U_max_m_s": umax,
            "flux_closure_pct": closure,
            "iterations": parsed.get("iterations"),
            "stop_reason": parsed.get("stop_reason"),
            # 停车判据三元组（新增字段，供 manifest / /api/metrics 透出）
            "stop_reason_code": parsed.get("stop_reason_code"),
            "stop_iter": parsed.get("stop_iter"),
            # dp_band_pct = dP 稳定性评估带宽，单位是**百分数数值**（0.1896 = 0.19%）；
            # 判据未评估/不适用（NaN）时为 None。仅供展示与审计，不参与任何停车判定。
            "dp_band_pct": parsed.get("dp_band_pct"),
            "final_residuals": parsed.get("final_residuals"),
            "continuity_local": parsed.get("continuity_local"),
            "continuity_global": parsed.get("continuity_global"),
        },
        "wss": wss,
        "geometry": {
            "cells": parsed.get("cells"),
            "faces": parsed.get("faces"),
            "internal_faces": parsed.get("internal_faces"),
        },
        "field_snapshot_iter": it,
        "solver": {
            "backend": "custom",
            "run_mode": parsed.get("run_mode"),
            "contract_metrics_source": os.path.abspath(log_path),
        },
        # inputs 段来源缺陷（如 case 文件里读不到 nu）在此逐条记录，不静默吞掉
        "warnings": inputs_warnings,
    }
    post_dir = os.path.join(out_dir, "后处理")
    os.makedirs(post_dir, exist_ok=True)
    with open(os.path.join(post_dir, "metrics.json"), "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=1)
    # 原样保留 §11 指标段，便于审计逐字段核对
    try:
        txt = open(log_path, "rb").read().decode("utf-8", errors="replace")
        idx = txt.find("---- \u5951\u7ea6 \u00a711")
        if idx < 0:
            idx = txt.find("run mode")
        with open(os.path.join(post_dir, "solver-contract.txt"), "w",
                  encoding="utf-8", newline="\n") as f:
            f.write(txt[idx:] if idx >= 0 else txt[-4000:])
    except OSError:
        pass
    return metrics


# ---------------------------------------------------------------- 对外求解入口
def run_custom(case_dir, out_dir, max_iter=DEFAULT_MAX_ITER,
               write_every=DEFAULT_WRITE_EVERY, p_reltol=DEFAULT_P_RELTOL,
               progress=None, tag="custom", stall_limit=7200):
    """阻塞式 custom 求解 + 结果目录适配。

    返回 ``(rc, metrics_path_or_empty)``；``rc=0`` 且 metrics 落盘才算成功。
    """
    case_dir = os.path.abspath(case_dir)
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    log_path = os.path.join(out_dir, "solver.log")
    cmd = build_custom_command(case_dir, out_dir, max_iter, write_every, p_reltol)
    rc, _last = _run_process(cmd, log_path, progress=progress, tag=tag,
                             stall_limit=stall_limit)
    if rc != 0:
        return rc, ""
    try:
        metrics = build_metrics(case_dir, out_dir, log_path, tag=tag)
    except Exception as e:  # noqa: BLE001
        if progress:
            progress(f"[{tag}] !!! 结果适配失败：{e!r}")
        return -997, ""
    if progress:
        t = metrics["totals"]
        progress(f"[{tag}] 完成：dP={t['dP_Pa']:.4f} Pa，"
                 f"U_max={t['U_max_m_s']:.4f} m/s，"
                 f"flux 闭合={t['flux_closure_pct']:.4f}%，"
                 f"iters={t['iterations']}")
    return 0, os.path.join(out_dir, "后处理", "metrics.json")


def run_custom_monitored(case_dir, out_dir, tag="custom", stall_limit=1200,
                         progress=None, max_iter=None):
    """server 使用的心跳看护封装（签名对齐 ``_run_wsl_allrun_monitored``）。"""
    rc, _mp = run_custom(case_dir, out_dir, max_iter=max_iter or DEFAULT_MAX_ITER,
                         progress=progress, tag=tag, stall_limit=stall_limit)
    return rc
