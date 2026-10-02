# -*- coding: utf-8 -*-
"""合成示例数据生成器 —— 生成 viewer_data.js（无任何患者数据）。

模型：弯曲收缩管腔（模拟鼻腔气道主腔）+ 上颌窦囊 + 流线 + 截面切片
+ 缩窄占位档（1/2/3 mm）+ 体积-压降曲线（参数化合成）。

用法：python gen_demo_data.py   →  在本脚本同目录生成 viewer_data.js

结构与真实数据包完全一致（meta / airwayMesh / streamlines / slices /
placeholders / curve / airwayCavity / airwaySinus 八键），viewer.html
可直接加载；全部数值为合成示例，与任何真实案例无关。
"""
import json
import math
import os

import numpy as np

# ----------------------------------------------------------------------
# 1. 管腔参数模型（中心线 + 半径剖面）
# ----------------------------------------------------------------------
Z_MIN, Z_MAX = -70.0, 70.0


def centerline(z):
    """气道中心线（mm）：z 为主轴，x/y 方向轻微弯曲。"""
    return np.array([
        9.0 * math.sin(math.pi * z / 160.0),
        4.0 * math.sin(2.0 * math.pi * z / 160.0),
        z,
    ])


def centerline_tangent(z, dz=0.05):
    c0 = centerline(z - dz)
    c1 = centerline(z + dz)
    t = c1 - c0
    return t / np.linalg.norm(t)


def radius(z, shrink_mm=0.0):
    """管腔半径（mm）：鼻瓣区（z≈12）主收缩 + 鼻咽部（z≈-48）轻度收缩。"""
    r = 13.0
    r -= 6.0 * math.exp(-(((z - 12.0) / 13.0) ** 2))   # 鼻瓣
    r -= 2.5 * math.exp(-(((z + 48.0) / 11.0) ** 2))   # 鼻咽
    return max(r - shrink_mm, 1.0)


def tube_mesh(n_theta, n_z, shrink_mm=0.0, r_scale=1.0):
    """参数化管腔网格 → (positions 展开列表, indices 列表)。"""
    zs = np.linspace(Z_MIN, Z_MAX, n_z)
    verts = []
    for z in zs:
        c = centerline(z)
        t = centerline_tangent(z)
        up = np.array([0.0, 1.0, 0.0])
        n1 = np.cross(t, up)
        n1 /= np.linalg.norm(n1)
        n2 = np.cross(t, n1)
        r = radius(z, shrink_mm) * r_scale
        for k in range(n_theta):
            th = 2.0 * math.pi * k / n_theta
            v = c + r * (math.cos(th) * n1 + math.sin(th) * n2)
            verts.extend(v.tolist())
    idx = []
    for j in range(n_z - 1):
        for k in range(n_theta):
            k2 = (k + 1) % n_theta
            a = j * n_theta + k
            b = j * n_theta + k2
            c2 = (j + 1) * n_theta + k
            d = (j + 1) * n_theta + k2
            idx.extend([a, c2, b, b, c2, d])
    return verts, idx


# ----------------------------------------------------------------------
# 2. 鼻窦囊（上颌窦椭球模型，独立于主管腔）
# ----------------------------------------------------------------------
def sinus_mesh(n_u, n_v):
    """椭球囊网格 → (positions, indices)。球心 (16, 30, 26)，半径 (15, 13, 14)。"""
    cx, cy, cz = 16.0, 30.0, 26.0
    rx, ry, rz = 15.0, 13.0, 14.0
    verts = []
    for iv in range(n_v):
        phi = math.pi * iv / (n_v - 1)
        for iu in range(n_u):
            th = 2.0 * math.pi * iu / n_u
            x = cx + rx * math.sin(phi) * math.cos(th)
            y = cy + ry * math.sin(phi) * math.sin(th)
            z = cz + rz * math.cos(phi)
            verts.extend([x, y, z])
    idx = []
    for iv in range(n_v - 1):
        for iu in range(n_u):
            iu2 = (iu + 1) % n_u
            a = iv * n_u + iu
            b = iv * n_u + iu2
            c2 = (iv + 1) * n_u + iu
            d = (iv + 1) * n_u + iu2
            idx.extend([a, c2, b, b, c2, d])
    return verts, idx


# ----------------------------------------------------------------------
# 3. 流线（63 条 × 188 点，带速度剖面）
# ----------------------------------------------------------------------
def make_streamlines(n_lines=63, n_pts=188):
    lines = []
    rng = np.random.default_rng(20261002)
    for li in range(n_lines):
        # 入口截面内的径向位置（0.15~0.85 倍半径）与角向
        frac = 0.15 + 0.70 * (li / max(n_lines - 1, 1)) + rng.normal(0, 0.02)
        frac = min(max(frac, 0.05), 0.95)
        ang = 2.0 * math.pi * li / n_lines + rng.normal(0, 0.1)
        pts = []
        spd = []
        for ip in range(n_pts):
            z = Z_MIN + (Z_MAX - Z_MIN) * ip / (n_pts - 1)
            c = centerline(z)
            t = centerline_tangent(z)
            up = np.array([0.0, 1.0, 0.0])
            n1 = np.cross(t, up)
            n1 /= np.linalg.norm(n1)
            n2 = np.cross(t, n1)
            r = radius(z) * frac
            p = c + r * (math.cos(ang) * n1 + math.sin(ang) * n2)
            pts.extend(p.tolist())
            # 泊肃叶剖面：壁面慢、中心快；收缩段加速
            v = 4.2 * (1.0 - frac ** 2) * (radius(z + 6.0) / max(radius(z), 1.0)) ** 2
            spd.append(max(v, 0.02))
        lines.append({"points": pts, "speed": spd})
    return lines


# ----------------------------------------------------------------------
# 4. 截面切片（4 片 z 位置，每片截面圆盘采样点，带速度）
# ----------------------------------------------------------------------
def make_slices(z_list=(-30.0, 0.0, 20.0, 45.0), n_pts=3991):
    slices = []
    rings = 34
    per_ring = max((n_pts - 1) // rings, 1)
    for z in z_list:
        c = centerline(z)
        t = centerline_tangent(z)
        up = np.array([0.0, 1.0, 0.0])
        n1 = np.cross(t, up)
        n1 /= np.linalg.norm(n1)
        n2 = np.cross(t, n1)
        r = radius(z)
        positions = []
        speed = []
        positions.extend(c.tolist())
        speed.append(5.1)
        for ir in range(1, rings + 1):
            rr = r * ir / rings
            for k in range(per_ring):
                th = 2.0 * math.pi * k / per_ring
                p = c + rr * (math.cos(th) * n1 + math.sin(th) * n2)
                positions.extend(p.tolist())
                speed.append(5.1 * (1.0 - (rr / r) ** 2) + 0.05)
        slices.append({"z_mm": z, "positions": positions, "speed": speed})
    return slices


# ----------------------------------------------------------------------
# 5. 缩窄占位档（1/2/3 mm 缩窄几何，15000 面/档）
# ----------------------------------------------------------------------
def make_placeholders(mm_list=(1, 2, 3)):
    ph = []
    for mm in mm_list:
        verts, idx = tube_mesh(75, 101, shrink_mm=float(mm))
        ph.append({"mm": mm, "positions": verts, "indices": idx})
    return ph


# ----------------------------------------------------------------------
# 6. 体积-压降曲线（参数化合成模型：单调平缓增长，量级与鼻腔
#    鼻瓣区压降文献报道一致；纯演示用，非物理仿真）
# ----------------------------------------------------------------------
def make_curve():
    volumes = [0.0, 5.5, 11.0, 16.5]
    dP = [round(18.0 * (1.0 + 1.6 * v / 16.5), 2) for v in volumes]
    band = [round(0.6 * dP[-1], 2), round(1.5 * dP[-1], 2)]
    return {
        "volumes_cm3": volumes,
        "dP_Pa": dP,
        "band_Pa": band,
    }


# ----------------------------------------------------------------------
# 7. 组装 VIEWER_DATA 并写盘
# ----------------------------------------------------------------------
def main():
    airway_verts, airway_idx = tube_mesh(100, 201)          # 40000 面
    cavity_verts, cavity_idx = tube_mesh(100, 151, r_scale=0.80)   # 30000 面
    sinus_verts, sinus_idx = sinus_mesh(100, 101)           # 20000 面

    data = {
        "meta": {
            "title": "鼻腔气流仿真查看器（合成示例数据）",
            "caseBaseline": "demo-synthetic @15 L/min 层流（非患者数据）",
            "units": "mm, m/s, Pa",
            "metrics": {
                "dP_baseline_Pa": 23.7,
                "dP_1mm_Pa": 35.2,
                "dP_2mm_Pa": 58.9,
                "dP_3mm_Pa": 66.1,
                "dP_note": "合成示例·参数化估计，仅供演示，非诊疗依据",
                "split_L_pct": 50.0,
                "split_R_pct": 50.0,
                "wss_mean_Pa": 0.013,
                "wss_p95_Pa": 0.061,
                "resistance_total": "78.5 Pa/(L/s)（合成示例）",
            },
        },
        "airwayMesh": {"positions": airway_verts, "indices": airway_idx},
        "streamlines": make_streamlines(),
        "slices": make_slices(),
        "placeholders": make_placeholders(),
        "curve": make_curve(),
        "airwayCavity": {"positions": cavity_verts, "indices": cavity_idx},
        "airwaySinus": {"positions": sinus_verts, "indices": sinus_idx},
    }

    gen_time = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    n_air_f = len(airway_idx) // 3
    n_air_v = len(airway_verts) // 3
    n_cav_f = len(cavity_idx) // 3
    n_sin_f = len(sinus_idx) // 3
    n_sl = len(data["streamlines"])
    n_sl_pts = len(data["streamlines"][0]["speed"])
    n_slices = len(data["slices"])
    header = (
        "// ============================================================================\n"
        "// viewer_data.js  ——  鼻腔气流 CFD 结果查看器数据包（合成示例 · T11 开源版）\n"
        f"// 生成时间 : {gen_time}\n"
        "// 生成器   : gen_demo_data.py（弯曲收缩管腔参数模型 + 参数化曲线）\n"
        "// 数据性质 : 100% 合成示例，不含任何患者数据、CT 影像或真实测量值\n"
        "// 坐标系   : mm（参数化管腔，中心线为 z 轴）\n"
        f"// 条数统计 : airwayMesh {n_air_f} 面 / {n_air_v} 顶点;\n"
        f"//            streamlines {n_sl} 条(均长 {n_sl_pts} 点, 速度 0.00~5.40 m/s);\n"
        f"//            slices {n_slices} 片; placeholders [15000, 15000, 15000] 面/档;\n"
        f"//            [T4] airwayCavity {n_cav_f} 面 / airwaySinus {n_sin_f} 面\n"
        "// 说明     : 概念验证 · 非医疗器械 · 仿真几何禁止人体使用\n"
        "// ============================================================================\n"
    )

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "viewer_data.js")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(header)
        f.write("window.VIEWER_DATA = ")
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")
        f.write(
            "console.log('VIEWER_DATA loaded', {"
            f'"airwayFaces": {n_air_f}, "streamlines": {n_sl}, "slices": {n_slices}, "placeholders": 3}});\n'
        )
    print("SAVED:", out)
    print("airwayMesh", len(airway_idx) // 3, "faces /", len(airway_verts) // 3, "verts")
    print("airwayCavity", len(cavity_idx) // 3, "faces / airwaySinus", len(sinus_idx) // 3, "faces")
    print("bytes", os.path.getsize(out))


if __name__ == "__main__":
    main()
