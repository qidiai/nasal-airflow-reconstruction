# -*- coding: utf-8 -*-
"""
M2.5 合成数据产线 v1 -- 参数化鼻腔腔体几何生成器（manifold3d, Apache-2.0）

物理可行性设计（Run-A 定流量 15 L/min 约束下推得）：
  若 1.5-4 mm2 的最窄截面承担半数流量，局部流速 60-90 m/s（对标 pC 1.5mm2
  狭窄 166 m/s -> simpleFoam GAMG FPE 发散先例），层流求解必炸。故采用
  非对称分叉：
    - 左鼻道（狭窄侧）：整条均匀细管，鼻孔面积 = 设计最窄截面 a_min，
      流量份额仅 3-8%，stenosis 流速 ~5 m/s（Re~500，层流安全）；
    - 右鼻道（健康侧）：半径 ~3.78mm（45mm2），承担 ~95% 流量；
    - 合并腔 + 出口管（55mm2，Re<2300）+ 6 组鼻窦腔（容积主力）。
  预期：dP_L 随 a_min 收紧单调上升；dP（面积加权入流均压）~24 Pa，
  对标 pA 18.45 Pa 量级框架。

参数维度（v1 任务书）：总体积 V_target(80-130 cm3)、最窄截面 a_min(1.5-4 mm2)、
弯曲度 curv、分叉不对称度 asym；seed 控制随机微扰（窦腔位置/鼻甲位置/弯曲偏航），
保证"同参数同 seed 可复现、不同 seed 同参数异构"。

输出：case-synth-NNN/geometry.stl（水密二进流 STL，单位 mm）+ params.json
"""
import argparse
import json
import math
import os
import struct
import time

import numpy as np
import manifold3d

try:
    MANIFOLD_VERSION = str(manifold3d.__version__)
except Exception:
    MANIFOLD_VERSION = "3.5.4"
MANIFOLD_LICENSE = "Apache-2.0"
SEG = 32  # 圆周离散段数（与球/柱一致）


# ---------------------------------------------------------------- 基础工具
def rodrigues_z_to(d):
    """旋转矩阵 R 使 R.(0,0,1) = d（单位向量）"""
    z = np.array([0.0, 0.0, 1.0])
    d = np.asarray(d, dtype=np.float64)
    n = float(np.linalg.norm(d))
    if n < 1e-12:
        return np.eye(3)
    d = d / n
    v = np.cross(z, d)
    s = float(np.linalg.norm(v))
    c = float(np.dot(z, d))
    if s < 1e-12:
        return np.eye(3) if c > 0 else np.diag([1.0, -1.0, -1.0])
    vx = np.array([[0.0, -v[2], v[1]], [v[2], 0.0, -v[0]], [-v[1], v[0], 0.0]])
    return np.eye(3) + vx + vx @ vx * ((1.0 - c) / (s * s))


def _xf(mf, T):
    """应用 Double3x4 变换（numpy (3,4) 优先，失败回退嵌套 list）"""
    try:
        return mf.transform(np.asarray(T, dtype=np.float64))
    except Exception:
        return mf.transform([[float(x) for x in row] for row in T])


def frustum(p0, p1, r0, r1, seg=SEG):
    """p0->p1 圆台段：manifold cylinder 沿 +Z，经 (3,4) 刚体变换到位"""
    p0 = np.asarray(p0, dtype=np.float64)
    p1 = np.asarray(p1, dtype=np.float64)
    L = float(np.linalg.norm(p1 - p0))
    if L < 1e-9:
        return None
    R = rodrigues_z_to(p1 - p0)
    T = np.zeros((3, 4), dtype=np.float64)
    T[:, :3] = R
    T[:, 3] = p0
    return _xf(manifold3d.Manifold.cylinder(
        L, max(float(r0), 1e-3), max(float(r1), 1e-3),
        circular_segments=int(seg)), T)


def sphere(c, r, seg=SEG):
    return manifold3d.Manifold.sphere(float(r), int(seg)).translate(
        [float(c[0]), float(c[1]), float(c[2])])


def tube(points, radii, seg=SEG):
    """多变半径管：相邻圆台共端面拼接，布尔并集保证水密"""
    m = None
    for i in range(len(points) - 1):
        f = frustum(points[i], points[i + 1], radii[i], radii[i + 1], seg)
        if f is None:
            continue
        m = f if m is None else m + f
    return m


def bezier2(A, B, C, ts):
    A = np.asarray(A, float)
    B = np.asarray(B, float)
    C = np.asarray(C, float)
    out = []
    for t in ts:
        u = 1.0 - t
        out.append(u * u * A + 2.0 * u * t * B + t * t * C)
    return out


def arc_len(points):
    return float(sum(np.linalg.norm(np.asarray(points[i + 1]) - np.asarray(points[i]))
                     for i in range(len(points) - 1)))


# ---------------------------------------------------------------- 几何构建
def build_main(p, rng):
    """主气流域：左狭窄鼻道 + 右健康鼻道 + 垂直入鼻段 + 合并腔 + 出口管 + 鼻甲"""
    a_min = float(p["a_min_mm2"])
    curv = float(p["curv"])
    asym = float(p["asym"])
    r_sten = math.sqrt(a_min / math.pi)          # 左鼻孔半径 = 设计最窄截面
    r_R = 3.78 * (1.0 + 0.12 * asym)             # 右鼻道半径（45mm2  nominal）
    jitter = lambda s: float(rng.uniform(-1.0, 1.0) * s)

    # -- 左狭窄支：垂直入鼻段(z 0->4) + Bezier 至汇合点(0,0,55)
    A_L = np.array([-9.0, 0.0, 0.0])
    P0_L = np.array([-9.0, jitter(0.5), 4.0])
    C_L = np.array([0.0, 0.0, 55.0])
    B_L = P0_L + np.array([-7.0 * curv * (1.0 - 0.1 * asym), 5.0 * curv, 25.5])
    pts_L = [A_L, P0_L] + bezier2(P0_L, B_L, C_L, np.linspace(0.0, 1.0, 48))
    rad_L = [r_sten] * len(pts_L)
    m_left = tube(pts_L, rad_L)

    # -- 右健康支：镜像弯曲 + asym 放大
    A_R = np.array([9.0, 0.0, 0.0])
    P0_R = np.array([9.0, jitter(0.5), 4.0])
    C_R = np.array([0.0, jitter(0.8), 55.0])
    B_R = P0_R + np.array([7.0 * curv * (1.0 + 0.25 * asym), -4.0 * curv, 25.5])
    pts_R = [A_R, P0_R] + bezier2(P0_R, B_R, C_R, np.linspace(0.0, 1.0, 48))
    n_R = len(pts_R)
    rad_R = [r_R * (1.0 - 0.06 * i / (n_R - 1)) for i in range(n_R)]
    m_right = tube(pts_R, rad_R)

    # -- 右支鼻甲凸起（2 个，内外壁交替；内突 0.30*r_R，局部截面 ~22mm2 > a_min）
    turb = []
    for t_side, sgn in ((0.30 + jitter(0.04), +1.0), (0.65 + jitter(0.04), -1.0)):
        c = np.asarray(pts_R[int(round(t_side * (n_R - 1)))])
        turb.append(sphere(c + np.array([0.0, sgn * r_R * 0.9, 0.0]),
                           0.30 * r_R))
    m_turb = turb[0] + turb[1]

    # -- 合并腔 + 出口管（出口 55mm2，Re<2300；顶部被组织覆盖 -> outlet patch）
    m_chamber = frustum([0.0, 0.0, 55.0], [0.0, 0.0, 77.0], 7.0, 7.0)
    m_outlet = frustum([0.0, 0.0, 77.0], [0.0, 0.0, 117.0], 4.2, 4.2)

    m = m_left + m_right + m_turb + m_chamber + m_outlet
    return m


def build_sinuses(p, rng):
    """6 组鼻窦腔（容积主力）：maxillary L/R / frontal / sphenoid / ethmoid L/R"""
    j = lambda s: float(rng.uniform(-1.0, 1.0) * s)
    specs = [
        # (center, r, neck_from, neck_to, neck_r)
        ([-21.0 + j(1.5), 5.0 + j(1.0), 30.0 + j(1.5)], 17.0,
         [-6.0, 2.0, 36.0], [-21.0 + j(1.5), 5.0 + j(1.0), 30.0 + j(1.5)], 3.0),
        ([21.0 + j(1.5), 5.0 + j(1.0), 30.0 + j(1.5)], 17.0,
         [6.0, 2.0, 36.0], [21.0 + j(1.5), 5.0 + j(1.0), 30.0 + j(1.5)], 3.0),
        ([0.0, 17.0 + j(1.0), 76.0 + j(1.0)], 15.0,
         [0.0, 6.0, 72.0], [0.0, 17.0 + j(1.0), 76.0 + j(1.0)], 3.0),
        ([0.0, -16.0 + j(1.0), 58.0 + j(1.5)], 14.0,
         [0.0, -6.0, 58.0], [0.0, -16.0 + j(1.0), 58.0 + j(1.5)], 3.0),
        ([-8.0 + j(1.0), 12.0 + j(1.0), 60.0 + j(1.0)], 11.0,
         [-4.0, 5.0, 60.0], [-8.0 + j(1.0), 12.0 + j(1.0), 60.0 + j(1.0)], 2.5),
        ([8.0 + j(1.0), 12.0 + j(1.0), 60.0 + j(1.0)], 11.0,
         [4.0, 5.0, 60.0], [8.0 + j(1.0), 12.0 + j(1.0), 60.0 + j(1.0)], 2.5),
    ]
    m = None
    for c, r, a, b, rn in specs:
        s = sphere(c, r)
        nk = frustum(a, b, rn, rn)
        if nk is not None:
            s = s + nk
        m = s if m is None else m + s
    return m


def build_full(p):
    """构建 + 体容积调节（z 拉伸 65% + 窦腔缩放 35% + 末段精确 z 校正）"""
    rng = np.random.default_rng(int(p["seed"]))
    M = build_main(p, rng)
    S = build_sinuses(p, rng)
    v_m = float(M.volume())
    v_s = float(S.volume())
    v0 = v_m + v_s
    if v0 <= 0:
        raise RuntimeError("empty geometry")
    rho = float(p["V_target_cm3"]) * 1000.0 / v0
    z1 = rho ** 0.65
    k1 = rho ** 0.35
    v_est = z1 * (v_m + (k1 ** 3) * v_s)
    z2 = z1 * float(p["V_target_cm3"]) * 1000.0 / v_est
    U = M + S.scale([k1, k1, k1])
    U = U.scale([1.0, 1.0, z2])
    # 末段精确校正（重叠区体积非线性的一次修正；scale 为廉价变换，不重跑布尔）
    v_f = float(U.volume())
    if v_f > 0:
        U = U.scale([1.0, 1.0, float(p["V_target_cm3"]) * 1000.0 / v_f])
    v_f2 = float(U.volume())
    return U, dict(v_main_mm3=round(v_m, 1), v_sinus_mm3=round(v_s, 1),
                   v_nominal_mm3=round(v0, 1), z_scale=round(float(z2), 5),
                   sinus_scale=round(float(k1), 5),
                   v_final_cm3=round(v_f2 / 1000.0, 3))


# ---------------------------------------------------------------- 导出与测量
def export_stl(mf, path):
    mo = mf.as_original()
    mesh = mo.to_mesh()
    vp = np.asarray(mesh.vert_properties, dtype=np.float32).reshape(-1, 3)
    tv = np.asarray(mesh.tri_verts, dtype=np.int32).reshape(-1, 3)
    with open(path, "wb") as f:
        f.write(b"\x00" * 80)
        f.write(struct.pack("<I", len(tv)))
        buf = []
        for t in tv:
            a, b, c = vp[t[0]], vp[t[1]], vp[t[2]]
            n = np.cross(b - a, c - a)
            ln = float(np.linalg.norm(n))
            n = n / ln if ln > 1e-20 else np.zeros(3, dtype=np.float32)
            buf.append(struct.pack("<12fH", float(n[0]), float(n[1]), float(n[2]),
                                   float(a[0]), float(a[1]), float(a[2]),
                                   float(b[0]), float(b[1]), float(b[2]),
                                   float(c[0]), float(c[1]), float(c[2]), 0))
            if len(buf) >= 20000:
                f.write(b"".join(buf))
                buf = []
        if buf:
            f.write(b"".join(buf))
    return len(vp), len(tv)


def _poly_area(poly):
    x = poly[:, 0]
    y = poly[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def measure_stl(path):
    """STL 实测：水密性、体积、左鼻孔截面(=设计最窄)、全局轴向最小截面"""
    import trimesh
    tm = trimesh.load(path)
    res = {
        "watertight": bool(tm.is_watertight),
        "winding_consistent": bool(tm.is_winding_consistent),
        "volume_cm3": round(float(tm.volume) / 1000.0, 3),
        "n_tri": int(len(tm.faces)),
    }

    def sec(z):
        sl = tm.section(plane_origin=[0.0, 0.0, z], plane_normal=[0.0, 0.0, 1.0])
        if sl is None:
            return []
        try:
            polys = sl.discrete
        except Exception:
            return []
        out = []
        for poly in polys:
            arr = np.asarray(poly, dtype=np.float64)
            if arr.ndim != 2 or arr.shape[0] < 3:
                continue
            a = _poly_area(arr[:, :2])
            cx = float(arr[:, 0].mean())
            out.append((a, cx))
        return out

    # 鼻孔截面（z=0.05mm，恰在鼻底上方）：按 x 拆左右
    loops = sec(0.05)
    aL = sum(a for a, cx in loops if cx < 0.0)
    aR = sum(a for a, cx in loops if cx >= 0.0)
    res["nostril_area_L_mm2"] = round(aL, 3)
    res["nostril_area_R_mm2"] = round(aR, 3)
    # 全局轴向最小截面（0.5mm 步长，避开鼻底/顶盖）
    zmax = float(tm.bounds[1][2])
    amin = float("inf")
    z_at = None
    z = 0.1
    while z < zmax - 0.1:
        tot = sum(a for a, _ in sec(z))
        if tot > 1e-6 and tot < amin:
            amin = tot
            z_at = z
        z += 0.5
    res["a_min_axial_global_mm2"] = round(amin, 3) if amin < float("inf") else None
    res["a_min_axial_z_mm"] = round(z_at, 2) if z_at is not None else None
    res["a_min_stl_mm2"] = round(min(amin, aL) if amin < float("inf") else aL, 3)
    res["z_extent_mm"] = round(zmax, 2)
    return res


# ---------------------------------------------------------------- 10 例 DoE
GRID = [
    {"case": "synth-001", "a_min_mm2": 1.5, "V_target_cm3": 105.0, "curv": 0.5, "asym": 0.2, "seed": 1001},
    {"case": "synth-002", "a_min_mm2": 2.0, "V_target_cm3": 105.0, "curv": 0.5, "asym": 0.2, "seed": 1002},
    {"case": "synth-003", "a_min_mm2": 2.5, "V_target_cm3": 105.0, "curv": 0.5, "asym": 0.2, "seed": 1003},
    {"case": "synth-004", "a_min_mm2": 3.0, "V_target_cm3": 105.0, "curv": 0.5, "asym": 0.2, "seed": 1004},
    {"case": "synth-005", "a_min_mm2": 4.0, "V_target_cm3": 105.0, "curv": 0.5, "asym": 0.2, "seed": 1005},
    {"case": "synth-006", "a_min_mm2": 2.5, "V_target_cm3": 80.0, "curv": 0.5, "asym": 0.2, "seed": 1006},
    {"case": "synth-007", "a_min_mm2": 2.5, "V_target_cm3": 95.0, "curv": 0.5, "asym": 0.2, "seed": 1007},
    {"case": "synth-008", "a_min_mm2": 2.5, "V_target_cm3": 115.0, "curv": 0.5, "asym": 0.2, "seed": 1008},
    {"case": "synth-009", "a_min_mm2": 2.5, "V_target_cm3": 130.0, "curv": 0.5, "asym": 0.2, "seed": 1009},
    {"case": "synth-010", "a_min_mm2": 2.0, "V_target_cm3": 105.0, "curv": 1.0, "asym": 0.8, "seed": 1010},
]


def gen_case(p, out_root):
    case_dir = os.path.join(out_root, p["case"])
    os.makedirs(case_dir, exist_ok=True)
    stl_path = os.path.join(case_dir, "geometry.stl")
    t0 = time.time()
    U, tune = build_full(p)
    nv, nt = export_stl(U, stl_path)
    meas = measure_stl(stl_path)
    vol_mf = float(U.volume()) / 1000.0
    params = {
        "case": p["case"],
        "design": {k: p[k] for k in ("a_min_mm2", "V_target_cm3", "curv", "asym", "seed")},
        "realized": dict(meas, volume_manifold_cm3=round(vol_mf, 3),
                         n_vert=nv, n_tri_stl=nt),
        "volume_tuning": tune,
        "generator": {
            "script": "synth/gen_geometry.py",
            "manifold_version": MANIFOLD_VERSION,
            "manifold_license": MANIFOLD_LICENSE,
            "circular_segments": SEG,
            "note": ("左鼻道=均匀狭窄气道(鼻孔=设计最窄截面 a_min, 流量份额3-8%); "
                     "右鼻道健康 45mm2; 6 组鼻窦腔为容积主力; "
                     "z 拉伸+窦腔缩放调体容积"),
        },
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "gen_seconds": round(time.time() - t0, 1),
    }
    with open(os.path.join(case_dir, "params.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(params, f, ensure_ascii=False, indent=1)
    return params


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default=None, help="synth-NNN；缺省 --all")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--out-root", required=True)
    args = ap.parse_args()
    if args.all or args.case is None:
        cases = GRID
    else:
        cases = [g for g in GRID if g["case"] == args.case]
        if not cases:
            raise SystemExit(f"unknown case {args.case}")
    for g in cases:
        r = gen_case(g, args.out_root)
        print(f"[gen] {g['case']}: V={r['realized']['volume_manifold_cm3']}cm3 "
              f"(target {g['V_target_cm3']}), a_min_stl={r['realized']['a_min_stl_mm2']}mm2 "
              f"(design {g['a_min_mm2']}), nostrilL={r['realized']['nostril_area_L_mm2']}mm2, "
              f"watertight={r['realized']['watertight']}, tris={r['realized']['n_tri']}, "
              f"{r['gen_seconds']}s", flush=True)


if __name__ == "__main__":
    main()

