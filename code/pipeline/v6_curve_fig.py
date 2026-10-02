# -*- coding: utf-8 -*-
"""环节③④交付：占位量-ΔP曲线图"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

V = np.array([0.0, 4.366, 8.239, 10.415])
P = np.array([18.45, 28.55, 47.32, 52.40])
c = np.polyfit(V, P, 2)
Vs = np.linspace(0, 12, 200)
Ps = np.polyval(c, Vs)

fig, ax = plt.subplots(figsize=(9, 5.5))
ax.axhspan(30, 150, color="green", alpha=0.10, label="Normal literature band (30-150 Pa)")
ax.plot(Vs, Ps, "b-", lw=1.8, label=f"Quadratic fit: dP = {c[0]:.3f}V$^2$ + {c[1]:.2f}V + {c[2]:.1f}")
ax.plot(V, P, "ko", ms=8, label="CFD simulation points (v5/v6n1/n2/n3)")
for v, p, t in zip(V, P, ["baseline", "1mm shell\n4.37 cm3", "2mm shell\n8.24 cm3", "3mm shell\n10.42 cm3"]):
    ax.annotate(t, (v, p), textcoords="offset points", xytext=(8, -18), fontsize=8.5)
ax.axhline(30, color="green", ls="--", lw=1)
r30 = np.roots([c[0], c[1], c[2] - 30])
v30 = [r for r in r30 if r.imag == 0 and r.real > 0][0]
ax.plot([v30], [30], "r*", ms=16, label=f"Minimum for 30 Pa: V = {v30:.1f} cm3")
ax.plot([8.24], [47.32], "bD", ms=10, label="Engineering recommendation: 2mm tier (47.3 Pa, mid-band)")
ax.set_xlabel("Implant volume V (cm3, bilateral lateral-wall shells, valve-turbinate zone)")
ax.set_ylabel("Transnasal pressure drop dP (Pa) @ 15 L/min")
ax.set_title("Patient A - Personalized Nasal Plug Design Curve (Occupancy vs Airway Resistance)")
ax.set_xlim(0, 12); ax.set_ylim(0, 80)
ax.legend(fontsize=8.5, loc="upper left"); ax.grid(alpha=0.3)
fig.tight_layout()
out = r"G:\程序开发\qidicode\qidicode-portable-windows-x64\qidicode-portable\contest3_workspace\pipeline\out\step4\占位量-ΔP曲线.png"
fig.savefig(out, dpi=150)
print("saved:", out)
