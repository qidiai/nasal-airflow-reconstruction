# -*- coding: utf-8 -*-
"""环节③指挥官抽验 + 占位量-ΔP曲线拟合与最终推荐

结论层口径批修（T10-a）：DF1 单一演示带口径 / DF4 输入溯源 / DF5 禁词清理 /
DF6 动态叙事 / F5 演示值路线。
本脚本所有 pA/ΔP/V 数值一律为**内部演示值（合成演示数据）**，非归档真值、
非文献参考带、非临床建议；正式文献参考带赛后引入，T12 定稿后由 T11 对账。
"""
import hashlib
import json
import os
import re

import numpy as np

# ===== 单一演示带口径（T10-a / DF1 / F5；三文件同口径，正式文献参考带赛后引入）=====
# 与 v6_curve_fig.py / extract_clinical.py 完全同一份：50/80 与 30 Pa 一律为
# 「内部工程/演示阈值（非文献参考带）」；pA 基线 18.45 Pa 与 v6 曲线同为 @15 L/min 演示工况。
# 所有 pA/ΔP/V 数值均为内部演示值（合成演示数据），非归档真值；T12 定稿后由 T11 对账。
DEMO_BAND = {
    "green_max_Pa": 50.0,
    "yellow_max_Pa": 80.0,
    "demo_lower_ref_Pa": 30.0,
    "caliber": "内部工程/演示阈值（非文献参考带）",
    "flow_caliber": "@15 L/min（pA 基线演示值 18.45 Pa 与 v6 曲线同工况）",
    "demo": True,
    "source": "内部演示阈值；正式文献参考带赛后引入；T12 定稿后 T11 对账",
}
TIER_BELOW = "低于内部演示参考线（30 Pa）——内部演示值，非临床判读"
TIER_GREEN = "内部演示阈值·绿档（非文献参考带）"
TIER_YELLOW = "内部演示阈值·黄档（非文献参考带）"
TIER_RED = "内部演示阈值·红档（非文献参考带）"


def classify_demo_band(dp_pa):
    """按统一演示带口径给出档位结论（同一 pA 演示值在任何口径源结论一致）。"""
    if dp_pa is None:
        return "无 ΔP 数值（内部演示值缺失）"
    if dp_pa < DEMO_BAND["demo_lower_ref_Pa"]:
        return TIER_BELOW
    if dp_pa <= DEMO_BAND["green_max_Pa"]:
        return TIER_GREEN
    if dp_pa <= DEMO_BAND["yellow_max_Pa"]:
        return TIER_YELLOW
    return TIER_RED


RES = r"%DATA_ROOT%\项目\P0-鼻塞设计工具\阶段2-CFD算例包\结果"
RHO = 1.2

# ===== DF4：V/P 输入溯源 =====
# 候选输入（注释所指 narrowing_qc.json / 诊断报告4）：JSON 需含 V_cm3 / P_Pa 两个等长数组。
# 在场 → 读文件 + 打印 md5/来源路径；不在场 → 显式标注「硬编码演示值」并在台账登记
# （演示值路线，非 fail-closed；fail-closed 为另一可选分支，见 ledger-draft-T10a.md）。
def _candidate_inputs():
    cands = []
    env = os.environ.get("V6_CURVE_INPUT_JSON")
    if env:
        cands.append(env)
    root = os.environ.get("DATA_ROOT")
    if root:
        base = os.path.join(root, "项目", "P0-鼻塞设计工具", "阶段2-CFD算例包", "结果")
        cands.append(os.path.join(base, "narrowing_qc.json"))
    cands.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "narrowing_qc.json"))
    return cands


DEMO_V = [0.0, 4.366, 8.239, 10.415]   # cm³，硬编码演示值（非归档真值）
DEMO_P = [18.45, 28.55, 47.32, 52.40]  # Pa，硬编码演示值（非归档真值）
V_MAX = 10.415                          # 最大样本占位（cm³），超出即外推段


def load_curve_points(verbose=True):
    """返回 (V, P, provenance)：优先读文件（附 md5/路径），否则回落到显式标注的硬编码演示值。"""
    for path in _candidate_inputs():
        if os.path.isfile(path):
            raw = open(path, "rb").read()
            md5 = hashlib.md5(raw).hexdigest()
            obj = json.loads(raw.decode("utf-8"))
            V = np.asarray(obj["V_cm3"], dtype=float)
            P = np.asarray(obj["P_Pa"], dtype=float)
            assert V.shape == P.shape and V.ndim == 1 and len(V) >= 3, \
                "%s: V_cm3/P_Pa 须为等长一维数组且 ≥3 点" % path
            prov = {"source": "file", "path": path, "md5": md5, "demo": False}
            if verbose:
                print(f"  [输入溯源] 文件读入：{path}")
                print(f"  [输入溯源] md5 = {md5}")
                print(f"  [输入溯源] V={V.tolist()} / P={P.tolist()}（来自文件；演示值路线，非归档真值）")
            return V, P, prov
    # 不在场：显式硬编码演示值路线
    prov = {"source": "hardcoded_demo", "path": None, "md5": None, "demo": True,
            "note": "v6 输入文件（narrowing_qc.json / 诊断报告4）不在场；改用硬编码演示值，非归档真值"}
    if verbose:
        print("  [输入溯源] " + prov["note"])
        print(f"  [输入溯源] V={DEMO_V} / P={DEMO_P}（硬编码演示值·合成演示数据，md5 不适用）")
    return np.asarray(DEMO_V, dtype=float), np.asarray(DEMO_P, dtype=float), prov


def read_scalar_list(path):
    lines = open(path, encoding="utf-8").read().splitlines()
    for i, l in enumerate(lines):
        s = l.strip()
        if s == "(":
            n = int(lines[i-1].strip())
            vals = []
            for l2 in lines[i+1:]:
                s2 = l2.strip()
                if s2 == ")": break
                vals.append(float(s2))
            a = np.array(vals)
            assert len(a) == n, f"{path}: {len(a)} != {n}"
            return a
        if re.fullmatch(r"\((\d+)", s):
            n = int(s[1:]); vals = []
            for l2 in lines[i+1:]:
                s2 = l2.strip()
                if s2 == ")": break
                vals.append(float(s2))
            return np.array(vals)
    raise ValueError(path)


def parse_owner(path):
    return read_scalar_list(path).astype(np.int64)


def parse_boundary(d):
    txt = open(d + r"\constant\polyMesh\boundary", encoding="utf-8").read()
    info = {}
    for m in re.finditer(r"(\w+)\s*\{\s*type\s+(\w+);\s*nFaces\s+(\d+);\s*startFace\s+(\d+);", txt):
        info[m.group(1)] = dict(nFaces=int(m.group(3)), startFace=int(m.group(4)))
    return info


# ===== DF6 / F5：动态叙事（不写死区间/壳厚；v30 is None 走无正根分支）=====
def build_tiers(V, P):
    """由样本数组动态生成演示档位表（V>0，按 V 升序），不写死任何档位数值。"""
    tiers = []
    for v, p in sorted(zip(np.asarray(V, dtype=float).tolist(),
                           np.asarray(P, dtype=float).tolist())):
        if v <= 0:
            continue
        tiers.append({"label": "演示档位%d" % (len(tiers) + 1),
                      "V_cm3": v, "P_Pa": p})
    return tiers


def describe_v30(v30, tiers):
    """括号说明由 v30 与档位表动态推出；v30 is None 走无正根分支，不抛 TypeError。"""
    if v30 is None:
        return "无正根：由演示数据反解不出正的占位 V（内部演示值，非临床结论）"
    below = [t for t in tiers if t["V_cm3"] < v30]
    above = [t for t in tiers if t["V_cm3"] >= v30]
    lo = max(below, key=lambda t: t["V_cm3"]) if below else None
    hi = min(above, key=lambda t: t["V_cm3"]) if above else None
    if lo and hi:
        return (f"反解占位 V≈{v30:.2f} cm³，落在 {lo['label']}(V={lo['V_cm3']:.2f}) "
                f"与 {hi['label']}(V={hi['V_cm3']:.2f}) 之间（均为内部演示值）")
    if lo is None:
        return (f"反解占位 V≈{v30:.2f} cm³，低于最小演示档位 {hi['label']}"
                f"(V={hi['V_cm3']:.2f})（内部演示值，非区间内）")
    return (f"反解占位 V≈{v30:.2f} cm³，高于最大演示档位 {lo['label']}"
            f"(V={lo['V_cm3']:.2f})（内部演示值，外推段）")


def build_recommendation_lines(v30, V, P):
    """DF5 禁词清理 + DF6 动态叙事 + F5 演示值标注：返回推荐汇总各行。"""
    tiers = build_tiers(V, P)
    lines = ["===== 推荐汇总（仿真探索结论，非临床建议；内部演示值）====="]
    detail = describe_v30(v30, tiers)
    if v30 is None:
        lines.append("  恢复至内部演示参考线 30 Pa 的最小占位：无正根，不给出数值（" + detail + "）")
    else:
        lines.append(f"  恢复至内部演示参考线 30 Pa 的最小占位：V ≈ {v30:.1f} cm³（{detail}）")
    for t in tiers:
        # 档位结论走统一 classify_demo_band（旧承诺义/人群对照类表述已全部清除）
        lines.append(f"  {t['label']}（V={t['V_cm3']:.2f} cm³ → ΔP={t['P_Pa']:.2f} Pa，演示值）："
                     + classify_demo_band(t["P_Pa"]))
    lines.append("  以上为内部演示阈值区间的仿真探索结论，非临床建议；"
                 "全部 pA/ΔP/V 为内部演示值（合成演示数据），非归档真值。"
                 "正式文献参考带赛后引入，T12 定稿后由 T11 对账。")
    return lines


def solve_v30(c, target_Pa):
    """由二次拟合系数反解 target_Pa 对应的正根；无正根返回 None（不抛 TypeError）。"""
    roots = np.roots([c[0], c[1], c[2] - target_Pa])
    pos = [float(r.real) for r in roots if abs(r.imag) < 1e-9 and r.real > 0]
    return pos[0] if pos else None


def main():
    print("===== 指挥官独立抽验（v6n2，1500步）—— 内部演示口径 =====")
    d = RES + r"\P0-result-pA-v6n2"
    try:
        owner = parse_owner(d + r"\constant\polyMesh\owner")
        bnd = parse_boundary(d)
        p = read_scalar_list(d + r"\1500\p")
        tot_w, tot_p = 0.0, 0.0
        for patch in ["inletL", "inletR"]:
            b = bnd[patch]
            cells = owner[b["startFace"]: b["startFace"] + b["nFaces"]]
            pm = float(p[cells].mean()) * RHO
            w = b["nFaces"]
            print(f"  {patch}: {w}面, p̄={pm:.2f} Pa（内部演示值）")
            tot_w += w; tot_p += pm * w
        dP = tot_p / tot_w
        print(f"  ΔP(v6n2) = {dP:.2f} Pa（内部演示值；笔记本口径 47.32 Pa 亦为演示值）")
    except (OSError, KeyError, ValueError, AssertionError) as e:
        print(f"  [演示值路线] OpenFOAM 抽验输入不在场（{type(e).__name__}: {e}）→ 跳过抽验；"
              "以下 ΔP 数值一律为内部演示值（合成演示数据），非归档真值")

    print()
    print("===== 占位量-ΔP 曲线拟合（二次，最小二乘；内部演示值）=====")
    V, P, prov = load_curve_points()
    c = np.polyfit(V, P, 2)
    fit = np.polyval(c, V)
    res = np.abs(fit - P).max()
    print(f"  拟合: ΔP = {c[0]:.4f}·V² + {c[1]:.4f}·V + {c[2]:.3f}（内部演示值）")
    print(f"  各点拟合偏差: {np.round(fit - P, 2).tolist()} (max {res:.2f} Pa，内部演示值)")

    v30 = solve_v30(c, DEMO_BAND["demo_lower_ref_Pa"])
    print(f"  ΔP=30 Pa（内部演示参考线）解: V ≈ {v30:.2f} cm³" if v30 is not None
          else "  ΔP=30 Pa（内部演示参考线）解: 无正根")

    # 交叉验证（演示值）：取样本中间点 ΔP 反解，动态取自数组、不写死
    p_check = float(P[len(P) // 2])
    v_chk = solve_v30(c, p_check)
    print(f"  ΔP={p_check:.2f} Pa 演示反解：V ≈ {v_chk:.2f} cm³（内部演示值，非归档真值）"
          if v_chk is not None else f"  ΔP={p_check:.2f} Pa 演示反解：无正根（内部演示值）")

    print()
    for line in build_recommendation_lines(v30, V, P):
        print(line)


if __name__ == '__main__':
    main()
