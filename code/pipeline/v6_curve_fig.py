# -*- coding: utf-8 -*-
"""环节③④交付：占位量-ΔP曲线图

结论层口径批修（T10-a）：DF1 单一演示带口径 / DF4 外推标注+示例值图注 /
DF5 禁词清理 / F5 演示值路线。
全图数值为内部演示值（合成演示数据），非归档真值、非文献参考带、非临床建议。
"""
import os

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ===== 单一演示带口径（T10-a / DF1 / F5；三文件同口径，正式文献参考带赛后引入）=====
# 与 v6_curve_fit.py / extract_clinical.py 完全同一份：50/80 与 30 Pa 一律为
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


# 演示样本（与 v6_curve_fit.py 的硬编码演示值同源；本图输入文件不在场时用之）
DEMO_V = np.array([0.0, 4.366, 8.239, 10.415])
DEMO_P = np.array([18.45, 28.55, 47.32, 52.40])
V_MAX = 10.415   # 最大样本占位（cm³），超出即外推段


def main():
    V, P = DEMO_V, DEMO_P
    c = np.polyfit(V, P, 2)
    # DF4：样本域内实线；域外（V>V_MAX）改虚线 + 显式「外推」标注
    Vs_in = np.linspace(0, V_MAX, 160)
    Vs_ext = np.linspace(V_MAX, 12, 40)
    Ps_in = np.polyval(c, Vs_in)
    Ps_ext = np.polyval(c, Vs_ext)

    fig, ax = plt.subplots(figsize=(9, 5.5))
    # DF1：唯一演示带口径（30 Pa 参考线 ~ 50 Pa 绿档上界），显式标注非文献参考带 + 工况
    ax.axhspan(DEMO_BAND["demo_lower_ref_Pa"], DEMO_BAND["green_max_Pa"],
               color="green", alpha=0.10,
               label="内部工程/演示阈值（非文献参考带）·绿档 30–50 Pa @15 L/min")
    ax.plot(Vs_in, Ps_in, "b-", lw=1.8,
            label=f"仿真估计·示例值：二次拟合 dP = {c[0]:.3f}V$^2$ + {c[1]:.2f}V + {c[2]:.1f}")
    ax.plot(Vs_ext, Ps_ext, "b--", lw=1.8,
            label="外推段（V>10.415 cm³，超出样本域，仿真外推·示例值）")
    ax.plot(V, P, "ko", ms=8, label="仿真估计·示例值（合成演示数据）采样点")
    # 点标：示例值字样，删除旧病例 / 旧仿真点冠名
    for v, p, t in zip(V, P, ["baseline（示例值）", "1mm档 4.37 cm³（示例值）",
                              "2mm档 8.24 cm³（示例值）", "3mm档 10.42 cm³（示例值）"]):
        ax.annotate(t, (v, p), textcoords="offset points", xytext=(8, -18), fontsize=8.5)
    ax.axhline(DEMO_BAND["demo_lower_ref_Pa"], color="green", ls="--", lw=1,
               label="内部演示参考线 30 Pa（非文献参考带）")
    r30 = np.roots([c[0], c[1], c[2] - DEMO_BAND["demo_lower_ref_Pa"]])
    v30 = [r for r in r30 if r.imag == 0 and r.real > 0][0]
    ax.plot([v30], [DEMO_BAND["demo_lower_ref_Pa"]], "r*", ms=16,
            label=f"30 Pa 参考线最小占位：V = {v30:.1f} cm³（示例值）")
    # DF5：删旧承诺义冠名，改统一演示带口径档位结论
    ax.plot([8.24], [47.32], "bD", ms=10,
            label="2mm 演示档位（47.3 Pa）：" + classify_demo_band(47.32))

    ax.set_xlabel("Implant volume V (cm3, bilateral lateral-wall shells, valve-turbinate zone) · 演示值")
    ax.set_ylabel("Transnasal pressure drop dP (Pa) @ 15 L/min · 演示值")
    # DF4 / DF5 / F5：删除病例冠名；标题含「仿真估计·示例值（合成演示数据）」
    ax.set_title("参考病例演示 — 仿真估计·示例值（合成演示数据）：占位量-气道阻力曲线\n"
                 "（非归档真值 · 非文献参考带 · 非临床建议）", fontsize=11)
    ax.set_xlim(0, 12); ax.set_ylim(0, 80)
    ax.legend(fontsize=7.5, loc="upper left"); ax.grid(alpha=0.3)
    # 图注：仿真估计·示例值字样 + 演示值路线声明
    fig.text(0.5, 0.01,
             "仿真估计·示例值（合成演示数据）：所有 pA/ΔP/V 为内部演示值，非归档真值；"
             "带为内部工程/演示阈值（非文献参考带）；正式文献参考带赛后引入，T12 定稿后 T11 对账。",
             ha="center", fontsize=7.5)
    fig.tight_layout(rect=(0, 0.04, 1, 1))

    _ws = os.environ.get("QIDI_WORKSPACE")
    if not _ws:
        raise SystemExit("[错误] 环境变量 QIDI_WORKSPACE 未设置——请设置后再运行本脚本")
    out = os.path.join(_ws, "contest3_workspace", "pipeline", "out", "step4", "占位量-ΔP曲线.png")
    fig.savefig(out, dpi=150)
    print("saved:", out)


if __name__ == '__main__':
    main()
