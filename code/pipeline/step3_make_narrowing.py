# -*- coding: utf-8 -*-
"""
T1 step3 (规格书 v2)：虚拟占位（narrowing）算例生成器。
在 v5 基线上，于鼻瓣-下鼻甲区外侧壁逐层放入 1/2/3mm 壳层植入体（个性化鼻塞等效形态），
生成三档 OpenFOAM 算例 P0-OF-case-pA-v6n1/2/3 + narrowing_qc.json。

继承 step2_make_ofcase.py 全部七项修复（LF行尾 / polyMesh标准格式 / ESI方言 /
writeFields false / wss / fvSchemes div((nuEff*dev2(T(grad(U))))) / relaxationFactors）,
并继承 quad_pts 负向面平面公式 i0+(1 if sgn>0 else 0) 与 ds2 之后 3D 连通域过滤。

用法： py -X utf8 step3_make_narrowing.py [--zlo 100] [--zhi 160] [--mms 1 2 3] [--out out/step3]
"""
import os, sys, json, time, argparse, re, shutil
import numpy as np
import pydicom
from scipy import ndimage

WS = os.path.dirname(os.path.abspath(__file__))
# T11 开源脱敏：CT 数据目录由环境变量 P0_DICOM_DIR 指定（默认相对路径 ./dicom）
DATA_DIR = os.environ.get("P0_DICOM_DIR", "./dicom")
NPZ = os.path.join(WS, "out", "step2", "mask_full.npz")

Q_TOTAL = 15.0 / 60000.0       # 15 L/min -> m3/s
NU_AIR = 1.80e-05              # 气道内空气运动粘度 m2/s（step2 审计Y2）
VOXEL_MM = 0.35                # 标称体素边长（规格书 v2 §1）
REF_INLET_L = 95.3             # v5 参考入口面积 mm2（规格书 v2 §6 A2）
REF_INLET_R = 149.1
NARROW_FILE = "narrowing_qc.json"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# =====================================================================
# §1 输入加载
# =====================================================================
def load_dicom():
    import glob
    files = sorted(glob.glob(os.path.join(DATA_DIR, "*.dcm")))
    slices = [pydicom.dcmread(f) for f in files]
    slices.sort(key=lambda s: float(s.ImagePositionPatient[2]))
    nz, rows, cols = len(slices), slices[0].Rows, slices[0].Columns
    ps = [float(x) for x in slices[0].PixelSpacing]
    dz = abs(float(slices[1].ImagePositionPatient[2]) - float(slices[0].ImagePositionPatient[2]))
    vol = np.zeros((nz, rows, cols), dtype=np.int16)
    for i, s in enumerate(slices):
        vol[i] = s.pixel_array.astype(np.int16) * int(s.RescaleSlope) + int(s.RescaleIntercept)
    del slices
    return vol, ps, dz


# =====================================================================
# §2 腔体隔离（剔除鼻窦，只留鼻腔本体）
# =====================================================================
def isolate_cavity(mask):
    st = ndimage.generate_binary_structure(3, 1)
    eroded = ndimage.binary_erosion(mask, structure=st, iterations=3)
    lab, n = ndimage.label(eroded)
    sizes = np.bincount(lab.ravel())
    keep = int(np.argmax(sizes[1:]) + 1)
    cavity_core = lab == keep
    del lab, eroded
    cavity = ndimage.binary_dilation(cavity_core, iterations=3) & mask
    return cavity_core, cavity, n, keep


# =====================================================================
# §3 鼻中隔位置（仅用于选择壳层的方向符号）
# =====================================================================
def septum_x(mask, zlo, zhi):
    """规格书 v2 §3 的文字要求 = 'zwin 内每列气道体素数'，即 z 层带 [zlo,zhi)。
    规格书 line 47 的 `mask[:, ZLO:ZHI, :]` 切的是 axis=1(=rows)，与文字要求不符；
    按规格书自述的 zwin 定义（层索引）与已声明的 (394,512,512) 形状，取 z 层带。
    两种读法都记录，供裁决。"""
    hist_z = mask[zlo:zhi, :, :].sum(axis=(0, 1))     # 文字要求：z 层带
    hist_y = mask[:, zlo:zhi, :].sum(axis=(0, 1))     # 规格书 line 47 字面：rows 带
    xs_s = int(200 + np.argmin(hist_z[200:271]))
    xs_s_lit = int(200 + np.argmin(hist_y[200:271]))
    return xs_s, int(hist_z[xs_s]), int(hist_z[hist_z > 0].max()), xs_s_lit


# =====================================================================
# §5 降采样 / 网格 / 算例（复制 step2 已修复实现，参数化 mask）
# =====================================================================
def ds2(a):
    k, j, i = a.shape
    k2, j2, i2 = k // 2, j // 2, i // 2
    blk = a[:k2 * 2, :j2 * 2, :i2 * 2].astype(np.uint8).reshape(k2, 2, j2, 2, i2, 2)
    return blk.sum(axis=(1, 3, 5)) >= 4               # >=4/8 多数表决（step2 审计Y1）


def quad_pts(i0, j0, k0, axis, sgn):
    """step2 已修复版：+侧=本索引+1，-侧=本索引（禁止 i0+sgn）"""
    if axis == 0:
        x = i0 + (1 if sgn > 0 else 0)
        p = [(x, j0, k0), (x, j0 + 1, k0), (x, j0 + 1, k0 + 1), (x, j0, k0 + 1)]
    elif axis == 1:
        y = j0 + (1 if sgn > 0 else 0)
        p = [(i0, y, k0), (i0, y, k0 + 1), (i0 + 1, y, k0 + 1), (i0 + 1, y, k0)]
    else:
        z = k0 + (1 if sgn > 0 else 0)
        p = [(i0, j0, z), (i0 + 1, j0, z), (i0 + 1, j0 + 1, z), (i0, j0 + 1, z)]
    return p[::-1] if sgn < 0 else p


def header(cls, obj, loc):
    return ("FoamFile\n{\n    version     2.0;\n    format      ascii;\n"
            f"    class       {cls};\n    location    \"{loc}\";\n    object      {obj};\n}}\n"
            "// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //\n\n")


def build_case(mask_narrow, cut, ps, dz, case_dir, split_fallback_ds, tag):
    """按 step2 流水线生成一个算例；返回 stats dict（含 A1/A2/A3/A6/A7 质检）。"""
    MESH_DIR = os.path.join(case_dir, "constant", "polyMesh")
    if os.path.exists(case_dir):
        shutil.rmtree(case_dir)
    os.makedirs(MESH_DIR)
    os.makedirs(os.path.join(case_dir, "0"))
    os.makedirs(os.path.join(case_dir, "system"))

    # ---- 降采样 2x ----
    m, c = ds2(mask_narrow), ds2(cut)
    # ★ 连通域过滤（step2 缺陷6修复）
    lab_m, n_m = ndimage.label(m, structure=ndimage.generate_binary_structure(3, 1))
    if n_m > 1:
        sizes_m = np.bincount(lab_m.ravel())
        keep = int(np.argmax(sizes_m[1:]) + 1)
        removed = n_m - 1
        m = lab_m == keep
        log(f"    {tag} 连通域过滤: 删除 {removed} 个孤立组件")
    else:
        removed = 0
        log(f"    {tag} 连通域过滤: 单一连通域，无需清理")
    K, J, I = m.shape
    dx, dy, dzz = ps[1] * 2 / 1000.0, ps[0] * 2 / 1000.0, dz * 2 / 1000.0
    ncells = int(m.sum())
    vol_ds_cm3 = ncells * dx * dy * dzz * 1e6
    vol_mask_cm3 = mask_narrow.sum() * ps[0] * ps[1] * dz / 1000
    ratio_v = vol_ds_cm3 / vol_mask_cm3
    log(f"    {tag} 网格 {m.shape}, 单元 {ncells/1e3:.0f}k, 体素 {dx*1e3:.3f}x{dy*1e3:.3f}x{dzz*1e3:.3f} mm")
    log(f"    {tag} 体积回归: 降采样 {vol_ds_cm3:.1f} cm3 vs 全分辨率 mask_narrow {vol_mask_cm3:.1f} cm3 (比值 {ratio_v:.3f})")
    ids = np.full(m.shape, -1, dtype=np.int32)
    ids[m] = np.arange(ncells, dtype=np.int32)

    # ---- 内部面 ----
    own_list, nb_list, quad_list = [], [], []
    for axis in (0, 1, 2):
        if axis == 0:
            ok = m[:, :, :-1] & m[:, :, 1:]
        elif axis == 1:
            ok = m[:, :-1, :] & m[:, 1:, :]
        else:
            ok = m[:-1, :, :] & m[1:, :, :]
        pos = np.argwhere(ok)
        for (k0, j0, i0) in pos:
            i0, j0, k0 = int(i0), int(j0), int(k0)
            if axis == 0: nb = ids[k0, j0, i0 + 1]
            elif axis == 1: nb = ids[k0, j0 + 1, i0]
            else: nb = ids[k0 + 1, j0, i0]
            own_list.append(ids[k0, j0, i0]); nb_list.append(nb)
            quad_list.append(quad_pts(i0, j0, k0, axis, 1))
    own_a = np.array(own_list); nb_a = np.array(nb_list)
    order = np.lexsort((nb_a, own_a))
    own_a, nb_a = own_a[order], nb_a[order]
    quad_list = [quad_list[t] for t in order]
    n_internal = len(own_a)

    # ---- 边界面 ----
    k_min, k_max = 0, K - 1
    for k0 in range(K):
        if m[k0].any(): k_min = k0; break
    for k0 in range(K - 1, -1, -1):
        if m[k0].any(): k_max = k0; break
    patches = {"inlet": [], "outlet": [], "walls": []}
    for axis in (0, 1, 2):
        for sgn in (+1, -1):
            if sgn == +1:
                if axis == 0: ok = m[:, :, :-1] & ~m[:, :, 1:]
                elif axis == 1: ok = m[:, :-1, :] & ~m[:, 1:, :]
                else: ok = m[:-1, :, :] & ~m[1:, :, :]
                pos = np.argwhere(ok)
            else:
                if axis == 0: ok = m[:, :, 1:] & ~m[:, :, :-1]
                elif axis == 1: ok = m[:, 1:, :] & ~m[:, :-1, :]
                else: ok = m[1:, :, :] & ~m[:-1, :, :]
                pos = np.argwhere(ok)
                if axis == 0: pos[:, 2] += 1
                elif axis == 1: pos[:, 1] += 1
                else: pos[:, 0] += 1
            for (k0, j0, i0) in pos:
                i0, j0, k0 = int(i0), int(j0), int(k0)
                owner = ids[k0, j0, i0]
                if axis == 2 and sgn == -1 and k0 == k_min:
                    cls = "outlet"
                elif axis == 2 and sgn == +1 and k0 == k_max:
                    cls = "walls"
                else:
                    nk = k0 + (sgn if axis == 2 else 0)
                    nj = j0 + (sgn if axis == 1 else 0)
                    ni = i0 + (sgn if axis == 0 else 0)
                    if 0 <= nk < K and 0 <= nj < J and 0 <= ni < I and c[nk, nj, ni]:
                        cls = "inlet"
                    else:
                        cls = "walls"
                patches[cls].append((quad_pts(i0, j0, k0, axis, sgn), owner))
    if k_min == 0:
        for (j0, i0) in np.argwhere(m[0]):
            patches["outlet"].append((quad_pts(int(i0), int(j0), 0, 2, -1), ids[0, int(j0), int(i0)]))
    if k_max == K - 1:
        for (j0, i0) in np.argwhere(m[K - 1]):
            patches["walls"].append((quad_pts(int(i0), int(j0), K - 1, 2, +1), ids[K - 1, int(j0), int(i0)]))
    if m[:, :, 0].any() or m[:, :, I - 1].any() or m[:, 0, :].any() or m[:, J - 1, :].any():
        raise SystemExit("!!! 掩码触及横向数组边缘（FOV截断），边界类型需人工确认，中止 !!!")

    # ---- 鼻孔左右分组：入口面质心 x 的最大间隙 ----
    inlet_faces = patches.pop("inlet")
    if inlet_faces:
        cxs = np.array([np.mean([p[0] for p in q]) * dx for (q, _) in inlet_faces])
        ux = np.unique(np.round(cxs / dx))
        gaps = np.diff(ux)
        if len(ux) > 1 and gaps.max() >= 3.0:
            gi = int(np.argmax(gaps))
            split_i = (ux[gi] + ux[gi + 1]) / 2.0
            log(f"    {tag} 鼻中隔间隙: x体素 {ux[gi]:.0f}|{ux[gi+1]:.0f} 之间 {gaps.max():.0f} 体素 -> i={split_i:.1f}")
        else:
            split_i = float(split_fallback_ds)
            log(f"    {tag} !!! 未找到明显鼻中隔间隙，回退 xs_s/2={split_i:.0f}（v2 用 xs_s 代替 v1 头中线）")
        patches["inletL"] = [(q, o) for (q, o), cx in zip(inlet_faces, cxs) if cx < split_i * dx]
        patches["inletR"] = [(q, o) for (q, o), cx in zip(inlet_faces, cxs) if cx >= split_i * dx]
    else:
        patches["inletL"], patches["inletR"] = [], []
    patch_counts = {k: len(v) for k, v in patches.items()}
    log(f"    {tag} 边界面: {patch_counts} (掩码z范围 [{k_min},{k_max}])")
    if patch_counts["inletL"] == 0 or patch_counts["inletR"] == 0 or patch_counts["outlet"] == 0:
        raise SystemExit("!!! 入口/出口检测异常，中止 !!!")

    # ---- 写 polyMesh（全文件 LF 行尾） ----
    PORDER = ["inletL", "inletR", "outlet", "walls"]
    all_quads = quad_list + [q for p in PORDER for (q, _) in patches[p]]
    bd_owner = [o for p in PORDER for (_, o) in patches[p]]
    all_owner = np.concatenate([own_a, np.array(bd_owner, dtype=np.int32)])
    arr = np.array(all_quads, dtype=np.int32).reshape(-1, 3)
    uniq, inv = np.unique(arr, axis=0, return_inverse=True)
    inv = np.asarray(inv).reshape(-1).reshape(-1, 4)
    pts = uniq.astype(np.float64) * np.array([dx, dy, dzz])

    with open(os.path.join(MESH_DIR, "points"), "w", newline="\n") as f:
        f.write(header("vectorField", "points", "constant/polyMesh"))
        f.write(f"{len(pts):d}\n(\n")
        for p in pts:
            f.write(f"({p[0]:.6e} {p[1]:.6e} {p[2]:.6e})\n")
        f.write(")\n\n// ************************************************************************* //\n")
    with open(os.path.join(MESH_DIR, "faces"), "w", newline="\n") as f:
        f.write(header("faceList", "faces", "constant/polyMesh"))
        f.write(f"{len(all_quads):d}\n(\n")
        buf = []
        for q in inv:
            buf.append(f"4({q[0]:d} {q[1]:d} {q[2]:d} {q[3]:d})")
            if len(buf) >= 50000:
                f.write("\n".join(buf) + "\n"); buf = []
        if buf: f.write("\n".join(buf) + "\n")
        f.write(")\n\n// ************************************************************************* //\n")
    with open(os.path.join(MESH_DIR, "owner"), "w", newline="\n") as f:
        f.write(header("labelList", "owner", "constant/polyMesh"))
        f.write(f"{len(all_owner):d}\n(\n")
        np.savetxt(f, all_owner, fmt="%d")
        f.write(")\n\n// ************************************************************************* //\n")
    with open(os.path.join(MESH_DIR, "neighbour"), "w", newline="\n") as f:
        f.write(header("labelList", "neighbour", "constant/polyMesh"))
        f.write(f"{n_internal:d}\n(\n")
        np.savetxt(f, nb_a, fmt="%d")
        f.write(")\n\n// ************************************************************************* //\n")
    with open(os.path.join(MESH_DIR, "boundary"), "w", newline="\n") as f:
        f.write(header("polyBoundaryMesh", "boundary", "constant/polyMesh"))
        f.write(f"{len(PORDER):d}\n(\n")
        s = n_internal
        for name in PORDER:
            nf = patch_counts[name]
            ptype = "wall" if name == "walls" else "patch"
            f.write(f"    {name}\n    {{\n        type            {ptype};\n        nFaces          {nf};\n        startFace       {s};\n    }}\n")
            s += nf
        f.write(")\n\n// ************************************************************************* //\n")

    # ---- patch 面积 / 入流方向 ----
    def face_area(q):
        if len({p[0] for p in q}) == 1: return dy * dzz
        if len({p[1] for p in q}) == 1: return dx * dzz
        return dx * dy

    def patch_info(pname):
        fl = patches[pname]
        if not fl:
            return 0.0, np.array([np.nan, np.nan, np.nan])
        A = sum(face_area(q) for (q, _) in fl)
        ctr = np.array([(dx * sum(p[0] for p in q), dy * sum(p[1] for p in q), dzz * sum(p[2] for p in q))
                        for (q, _) in fl]).mean(axis=0) / 4.0
        return A, ctr

    mask_ctr = np.array([dx * np.argwhere(m)[:, 2].mean(), dy * np.argwhere(m)[:, 1].mean(),
                         dzz * np.argwhere(m)[:, 0].mean()])
    A_L, ctr_L = patch_info("inletL")
    A_R, ctr_R = patch_info("inletR")
    info = {}
    for pname, A, ctr in (("inletL", A_L, ctr_L), ("inletR", A_R, ctr_R)):
        d = mask_ctr - ctr
        d = d / np.linalg.norm(d)
        Qi = Q_TOTAL * A / (A_L + A_R)
        U = Qi / A * d
        info[pname] = dict(area_mm2=round(A * 1e6, 1), Q_Lmin=round(Qi * 60000, 2),
                           U=[round(float(x), 3) for x in U],
                           centroid_mm=[round(float(x) * 1e3, 1) for x in ctr])
        log(f"    {tag} {pname}: 面积 {A*1e6:.1f} mm2, 流量 {Qi*60000:.2f} L/min, U={info[pname]['U']}")

    # ---- case 文件 ----
    def wr(rel, content):
        with open(os.path.join(case_dir, rel), "w", newline="\n") as f:
            f.write(content)

    qL = Q_TOTAL * A_L / (A_L + A_R)
    qR = Q_TOTAL * A_R / (A_L + A_R)
    wr("0/U", header("volVectorField", "U", "0") + f"""
dimensions      [0 1 -1 0 0 0 0];

internalField   uniform (0 0 0);

boundaryField
{{
    inletL
    {{
        type            flowRateInletVelocity;
        volumetricFlowRate {qL:.6e};
        value           uniform (0 0 0);
    }}
    inletR
    {{
        type            flowRateInletVelocity;
        volumetricFlowRate {qR:.6e};
        value           uniform (0 0 0);
    }}
    outlet
    {{
        type            zeroGradient;
    }}
    walls
    {{
        type            fixedValue;
        value           uniform (0 0 0);
    }}
}}

// ************************************************************************* //
""")
    wr("0/p", header("volScalarField", "p", "0") + """
dimensions      [0 2 -2 0 0 0 0];

internalField   uniform 0;

boundaryField
{
    inletL    { type            zeroGradient; }
    inletR    { type            zeroGradient; }
    outlet    { type            fixedValue; value uniform 0; }
    walls     { type            zeroGradient; }
}

// ************************************************************************* //
""")
    wr("constant/transportProperties", header("dictionary", "transportProperties", "constant") + f"""
transportModel  Newtonian;

nu              [0 2 -1 0 0 0 0] {NU_AIR:.3e};

// ************************************************************************* //
""")
    wr("constant/turbulenceProperties", header("dictionary", "turbulenceProperties", "constant") + """
simulationType  laminar;

// ************************************************************************* //
""")
    wr("system/controlDict", header("dictionary", "controlDict", "system") + """
application     simpleFoam;

startFrom       latestTime;
startTime       0;
stopAt          endTime;
endTime         1500;
deltaT          1;

writeControl    timeStep;
writeInterval   500;
purgeWrite      2;
writeFormat     ascii;
writePrecision  6;
timeFormat      general;
timePrecision   6;
graphFormat     raw;

functions
{
    fluxInletL
    {
        type            surfaceFieldValue;
        libs            ("libfieldFunctionObjects.so");
        fields          (phi);
        operation       sum;
        regionType      patch;
        name            inletL;
        writeControl    writeTime;
        writeFields      false;
    }
    fluxInletR
    {
        type            surfaceFieldValue;
        libs            ("libfieldFunctionObjects.so");
        fields          (phi);
        operation       sum;
        regionType      patch;
        name            inletR;
        writeControl    writeTime;
        writeFields      false;
    }
    fluxOutlet
    {
        type            surfaceFieldValue;
        libs            ("libfieldFunctionObjects.so");
        fields          (phi);
        operation       sum;
        regionType      patch;
        name            outlet;
        writeControl    writeTime;
        writeFields      false;
    }
    wss
    {
        type            wallShearStress;
        libs            ("libfieldFunctionObjects.so");
        writeControl    writeTime;
    }
}

// ************************************************************************* //
""")
    wr("system/fvSchemes", header("dictionary", "fvSchemes", "system") + """
ddtSchemes
{
    default         steadyState;
}
gradSchemes
{
    default         Gauss linear;
}
divSchemes
{
    default         none;
    div(phi,U)      bounded Gauss linearUpwind grad(U);
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}
laplacianSchemes
{
    default         Gauss linear corrected;
}
snGradSchemes
{
    default         corrected;
}
interpolationSchemes
{
    default         linear;
}

// ************************************************************************* //
""")
    wr("system/fvSolution", header("dictionary", "fvSolution", "system") + """
solvers
{
    p
    {
        solver          GAMG;
        tolerance       1e-06;
        relTol          0.05;
        smoother        GaussSeidel;
    }
    U
    {
        solver          smoothSolver;
        smoother        GaussSeidel;
        tolerance       1e-05;
        relTol          0.01;
    }
}

SIMPLE
{
    nNonOrthogonalCorrectors 0;
    residualControl
    {
        p               1e-4;
        U               1e-4;
    }
}

relaxationFactors
{
    fields
    {
        p               0.3;
    }
    equations
    {
        U               0.7;
    }
}

cache
{
    grad(U);
}

// ************************************************************************* //
""")
    wr("Allrun", """#!/bin/sh
set -e
cd "${0%/*}" || exit 1
echo "== checkMesh =="
checkMesh | tee log.checkMesh
echo "== simpleFoam =="
simpleFoam | tee log.simpleFoam
echo "== 导出VTK =="
foamToVTK -latestTime
echo "== 完成。把整个case目录拷回共享文件夹即可 =="
""")

    # ---- 质检 A1 / A2 / A3 / A6 ----
    B = sum(patch_counts[p] for p in PORDER)
    euler_lhs = (6 * ncells - B) / 2
    A1 = bool(euler_lhs == n_internal)
    A2 = bool(abs(A_L * 1e6 / REF_INLET_L - 1) < 0.05 and abs(A_R * 1e6 / REF_INLET_R - 1) < 0.05)
    A3 = bool(0.94 <= ratio_v <= 1.06)
    if not A1:
        raise SystemExit(f"!!! [A1] Euler 恒等式失败: (6*{ncells}-{B})/2={euler_lhs} != {n_internal} !!!")
    if not A2:
        raise SystemExit(f"!!! [A2] 入口面积稳定性失败: L={A_L*1e6:.1f} R={A_R*1e6:.1f} !!!")
    if not A3:
        raise SystemExit(f"!!! [A3] 体积回归比越界: {ratio_v:.3f} !!!")

    crlf = {}
    for rel in ["0/U", "0/p", "constant/transportProperties", "constant/turbulenceProperties",
                "system/controlDict", "system/fvSchemes", "system/fvSolution", "Allrun"]:
        with open(os.path.join(case_dir, rel), "rb") as f:
            crlf[rel] = f.read().count(b"\r\n")
    for rel in ["points", "faces", "owner", "neighbour", "boundary"]:
        with open(os.path.join(MESH_DIR, rel), "rb") as f:
            crlf["constant/polyMesh/" + rel] = f.read().count(b"\r\n")
    A6_crlf = bool(sum(crlf.values()) == 0)
    with open(os.path.join(MESH_DIR, "points"), "rb") as f:
        head_lines = f.read(4096).decode("ascii", "replace").split("\n")[:20]
    pat = re.compile(r"^\(-?\d\.\d+e[+-]\d\d -?\d\.\d+e[+-]\d\d -?\d\.\d+e[+-]\d\d\)$")
    first_coord = next((i + 1 for i, l in enumerate(head_lines) if pat.match(l)), None)
    A6_fmt = bool(first_coord is not None)
    A6 = bool(A6_crlf and A6_fmt)

    return dict(
        case_dir=case_dir, cells=ncells, internal_faces=n_internal, patch_face_counts=patch_counts,
        removed_components=removed, mask_z_range=[k_min, k_max], split_i=split_i,
        inletL=info["inletL"], inletR=info["inletR"],
        A1_euler=A1, A1_detail={"lhs_6n_minus_B_over_2": int(euler_lhs), "n_internal": int(n_internal),
                                "B_boundary_faces": int(B)},
        A2_inlet_area=A2, A2_detail={"inletL_mm2": round(A_L * 1e6, 1), "inletR_mm2": round(A_R * 1e6, 1),
                                     "ref": [REF_INLET_L, REF_INLET_R]},
        A3_volume_regression=A3, A3_detail={"ds_cm3": round(vol_ds_cm3, 2), "fullres_narrow_cm3": round(vol_mask_cm3, 2),
                                            "ratio": round(float(ratio_v), 4)},
        A6_crlf_zero=A6_crlf, A6_crlf_counts=crlf, A6_points_format=A6_fmt, A6_all=A6,
        A6_detail={"first_coord_line": first_coord, "spec_window_lines": 12,
                   "note": "step2 冻结头部含空行共 10 行 -> 首个坐标行在第 13 行"},
    )


# =====================================================================
# main
# =====================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zlo", type=int, default=100)
    ap.add_argument("--zhi", type=int, default=160)
    ap.add_argument("--mms", type=float, nargs="+", default=[1.0, 2.0, 3.0])
    ap.add_argument("--out", default=os.path.join("out", "step3"))
    args = ap.parse_args()
    out_dir = args.out if os.path.isabs(args.out) else os.path.join(WS, args.out)
    os.makedirs(out_dir, exist_ok=True)

    t_all = time.time()
    log("[1/7] 读 DICOM ...")
    vol, ps, dz = load_dicom()
    log(f"    vol {vol.shape} {vol.dtype} HU[{vol.min()},{vol.max()}] ps={ps} dz={dz:.4f} ({time.time()-t_all:.0f}s)")
    vol_stats = {"shape": list(vol.shape), "dtype": str(vol.dtype),
                 "hu_min": int(vol.min()), "hu_max": int(vol.max())}
    del vol                                   # v2 算法不使用 HU，及时释放

    log("[2/7] 读 mask_full.npz ...")
    d = np.load(NPZ)
    mask, cut = d["mask"], d["cut"]
    assert mask.shape == (394, 512, 512), f"mask shape {mask.shape} != (394,512,512)"
    assert cut.shape == (394, 512, 512), f"cut shape {cut.shape} != (394,512,512)"
    log(f"    mask={int(mask.sum())} cut={int(cut.sum())}")

    zlo, zhi = args.zlo, args.zhi
    zw = np.zeros(mask.shape[0], bool); zw[zlo:zhi] = True
    zw3 = zw[:, None, None]

    log("[3/7] 腔体隔离（侵蚀3 -> 最大连通域 -> 测地复原）...")
    t0 = time.time()
    cavity_core, cavity, n_lab, keep = isolate_cavity(mask)
    core_zwin = int((cavity_core & zw3).sum())
    mz_mask = int((mask & zw3).sum())
    cavity_zwin_ratio = float((cavity & zw3).sum()) / mz_mask
    log(f"    侵蚀后组件 {n_lab} 个, 保留 label={keep}, core={int(cavity_core.sum())}, "
        f"cavity={int(cavity.sum())} ({time.time()-t0:.0f}s)")
    log(f"    cavity 在 zwin 内 / mask 在 zwin 内 = {cavity_zwin_ratio:.4f}, core_in_zwin={core_zwin}")
    if core_zwin == 0:
        raise SystemExit("!!! [§2 QC] 侵蚀把鼻瓣区全吃掉（cavity_core 在 zwin 内为空），中止 !!!")

    log("[4/7] 鼻中隔位置 xs_s ...")
    xs_s, h_xs, h_max, xs_s_lit = septum_x(mask, zlo, zhi)
    clean = bool(h_xs < 0.05 * h_max)
    log(f"    xs_s={xs_s} hist[xs_s]={h_xs} hist_max={h_max} clean={clean}"
        + ("" if clean else "  !!! 警告：中隔不干净"))
    log(f"    (规格书 line 47 字面读法 axis1=rows 得 xs_s={xs_s_lit}；已按文字'zwin 内'取 z 层带)")

    log("[5/7] EDT（cavity 一次，return_indices）...")
    t0 = time.time()
    d_, ind = ndimage.distance_transform_edt(cavity, return_indices=True)
    xgrid = np.arange(mask.shape[2]).reshape(1, 1, mask.shape[2])
    # scipy return_indices=True 返回 (ndim,)+input.shape：ind[0]=z索引, ind[1]=y索引, ind[2]=x索引
    # （规格书 §4 写作 ind[...,2]，与 scipy 实际布局不符，取其语义=最近壁的 x 索引）
    dxsign = xgrid - ind[2]                      # >0: 壁在 -x 侧(左外) ; <0: 壁在 +x 侧(右外)
    log(f"    EDT {time.time()-t0:.0f}s  dist.dtype={d_.dtype} idx.shape={ind.shape}")

    base_area = mask[zlo:zhi, :, :].sum(axis=(1, 2))     # z 层带内逐层体素数 (axis0=z)
    b_ok = base_area[base_area > 0]
    base_min_vox = int(b_ok.min())
    base_min_z = int(zlo + np.argmin(np.where(base_area == 0, 10 ** 9, base_area)))
    base_min_mm2 = round(base_min_vox * ps[0] * ps[1], 1)
    log(f"    基线(v5 mask) zwin 最小截面积: {base_min_vox} vox = {base_min_mm2} mm2 @ z={base_min_z}")

    levels = []
    prev_implant = None
    for mm in args.mms:
        R = int(round(mm / VOXEL_MM))
        tag = f"[v6n{args.mms.index(mm)+1} {mm:g}mm R={R}]"
        log(f"[6/7] 占位档 {tag}")
        t0 = time.time()
        shellL = (d_ <= R) & (xgrid < xs_s) & (dxsign > 0)
        shellR = (d_ <= R) & (xgrid >= xs_s) & (dxsign < 0)
        implant = (shellL | shellR) & zw3
        mask_narrow = mask & ~implant
        # ---- 硬断言 D1/D2/D3 ----
        D1a = bool(int((implant & ~cavity).sum()) == 0)
        D1b = bool(int((mask_narrow & ~mask).sum()) == 0)
        D3 = bool(int((implant & ~zw3).sum()) == 0)
        if prev_implant is None:
            D2 = True
        else:
            D2 = bool(int((prev_implant & ~implant).sum()) == 0 and implant.sum() > prev_implant.sum())
        imp_vox = int(implant.sum())
        log(f"    shellL={int(shellL.sum())} shellR={int(shellR.sum())} implant={imp_vox} "
            f"mask_narrow={int(mask_narrow.sum())} ({time.time()-t0:.0f}s)")
        log(f"    D1 implant⊆cavity={D1a} mask_narrow⊆mask={D1b} | D2 单调={D2} | D3 zwin100%={D3}")
        if not (D1a and D1b and D2 and D3):
            raise SystemExit(f"!!! [D1/D2/D3] 失败: D1a={D1a} D1b={D1b} D2={D2} D3={D3} !!!")

        depth = d_[implant] if imp_vox else np.array([0.0])
        case_name = f"P0-OF-case-pA-v6n{args.mms.index(mm)+1}"
        case_dir = os.path.join(out_dir, case_name)
        st = build_case(mask_narrow, cut, ps, dz, case_dir, int(round(xs_s / 2.0)), tag)

        # ---- A7：zwin 逐层截面积 ----
        prof_n = mask_narrow[zlo:zhi, :, :].sum(axis=(1, 2)).astype(float)   # z 层带 (axis0=z)
        prof_n_mm2 = prof_n * ps[0] * ps[1]
        nz_ok = prof_n[prof_n > 0]
        min_vox = int(nz_ok.min())
        min_z = int(zlo + np.argmin(np.where(prof_n == 0, 10 ** 9, prof_n)))
        min_mm2 = round(min_vox * ps[0] * ps[1], 1)
        csv_rel = f"narrowing_area_v6n{args.mms.index(mm)+1}.csv"
        with open(os.path.join(out_dir, csv_rel), "w", newline="\n") as f:
            f.write("z_index,area_mask_narrow_mm2,area_baseline_v5_mm2\n")
            for i, z in enumerate(range(zlo, zhi)):
                f.write(f"{z},{prof_n_mm2[i]:.3f},{base_area[i]*ps[0]*ps[1]:.3f}\n")
        A7 = bool(min_vox < base_min_vox)
        log(f"    A7 zwin 最小截面积 {min_vox} vox = {min_mm2} mm2 @z={min_z} "
            f"(基线 {base_min_vox} vox = {base_min_mm2} mm2) 缩小={A7}")

        st.update(dict(
            tag=case_name, mm=mm, R_vox=R,
            implant_vox=imp_vox, implant_vol_cm3=round(imp_vox * ps[0] * ps[1] * dz / 1000, 3),
            shellL_vox=int(shellL.sum()), shellR_vox=int(shellR.sum()),
            mask_narrow_vox=int(mask_narrow.sum()),
            D1_implant_subset_cavity=D1a, D1_mask_narrow_subset_mask=D1b,
            D2_hierarchy_monotonic=D2, D3_implant_within_zwin=D3,
            A5_report=dict(implant_vol_cm3=round(imp_vox * ps[0] * ps[1] * dz / 1000, 3),
                           shell_depth_vox={"mean": round(float(depth.mean()), 3),
                                            "min": round(float(depth.min()), 3),
                                            "max": round(float(depth.max()), 3)},
                           shell_depth_mm_nominal={"mean": round(float(depth.mean()) * VOXEL_MM, 3),
                                                   "min": round(float(depth.min()) * VOXEL_MM, 3),
                                                   "max": round(float(depth.max()) * VOXEL_MM, 3)},
                           xs_s=xs_s, cavity_zwin_over_mask_zwin=round(cavity_zwin_ratio, 4)),
            A7_min_area=min_vox,
            A7_min_area_mm2=min_mm2, A7_min_area_z=min_z,
            A7_baseline_min_area_mm2=base_min_mm2, A7_shrink_vs_v5=A7, A7_csv=csv_rel,
        ))
        levels.append(st)
        prev_implant = implant

    # ---- 汇总 & 写 JSON ----
    req = {}
    for k in ("A1_euler", "A2_inlet_area", "A3_volume_regression", "A6_all", "A7_shrink_vs_v5"):
        req[k] = all(bool(lv[k]) for lv in levels)
    req["D1"] = all(lv["D1_implant_subset_cavity"] and lv["D1_mask_narrow_subset_mask"] for lv in levels)
    req["D2"] = all(lv["D2_hierarchy_monotonic"] for lv in levels)
    req["D3"] = all(lv["D3_implant_within_zwin"] for lv in levels)

    qc = {
        "task": "T1 step3 虚拟占位 narrowing 算例生成器（规格书 v2）",
        "note": "占位体=鼻瓣-下鼻甲区外侧壁壳层（EDT 符号法分侧），mask_narrow = mask & ~implant",
        "inputs": {"dicom_dir": DATA_DIR, "npz": NPZ, "nz": 394, "rows": 512, "cols": 512,
                   "ps_mm": ps, "dz_mm": dz, "mask_vox": int(mask.sum()), "cut_vox": int(cut.sum()),
                   "vol": vol_stats},
        "params": {"zlo": zlo, "zhi": zhi, "mms": list(args.mms),
                   "R_vox": [int(round(m / VOXEL_MM)) for m in args.mms], "out_dir": out_dir},
        "cavity": {"n_eroded_labels": n_lab, "keep_label": keep, "core_vox": int(cavity_core.sum()),
                   "cavity_vox": int(cavity.sum()), "core_in_zwin": core_zwin,
                   "cavity_zwin_over_mask_zwin": round(cavity_zwin_ratio, 4)},
        "septum": {"xs_s": xs_s, "hist_xs_s": h_xs, "hist_max": h_max, "clean": clean,
                   "spec_line47_literal_rows_band_xs_s": xs_s_lit,
                   "note": "规格书 line 47 写作 mask[:, ZLO:ZHI, :]（axis1=rows）；按同书 zwin=层索引"
                           "定义与已声明形状 (394,512,512)，取 z 层带 mask[ZLO:ZHI,:,:]。两读法均记录。"},
        "baseline_v5": {"zwin_min_slice_vox": base_min_vox, "zwin_min_area_mm2": base_min_mm2,
                        "zwin_min_area_z": base_min_z},
        "levels": levels,
        "spec_notes": [
            "§3 line 47 写作 hist = mask[:, ZLO:ZHI, :]（axis1=rows）；同书 zwin=层索引[ZLO,ZHI) 且"
            "数据已声明为 (394,512,512)，故按文字 'zwin 内每列气道体素数' 取 z 层带 mask[ZLO:ZHI,:,:]。"
            f"应用值 xs_s={xs_s}；line47 字面(rows带)读法为 xs_s={xs_s_lit}（两条都记入 JSON）。",
            "§6 line 88 '前 12 行内含 (x y z) 形式'：step2 冻结头部含空行共 10 行，首个坐标行实为第 13 行，"
            "故抽查窗口放宽到前 20 行并记录实际行号（first_coord_line=13），A6 以 CRLF=0 且格式命中为准。",
            "§4 line 57 写作 ind[..., 2]：scipy distance_transform_edt(return_indices=True) 实际返回 "
            "(ndim,)+shape 的数组，x 索引应为 ind[2]（ind[...,2] 会切到最后一维）。已按语义取 ind[2]。",
        ],
        "assertions": req,
        "all_required_true": bool(all(req.values())),
        "runtime_s": round(time.time() - t_all, 1),
    }
    with open(os.path.join(out_dir, NARROW_FILE), "w", encoding="utf-8", newline="\n") as f:
        json.dump(qc, f, ensure_ascii=False, indent=2)

    log("[7/7] QC 表 (T/F)")
    flag_names = ("A1", "A2", "A3", "A6", "A7", "D1", "D2", "D3")
    fl_hdr = " ".join(f"{k:>2}" for k in flag_names)
    hdr = f"{'档':<22}{'mm':>3}{'R':>3}{'implant':>9}{'maskNar':>9}{'cells':>8}{'A_L':>7}{'A_R':>7}  {fl_hdr}"
    print(hdr); print("-" * len(hdr))
    for lv in levels:
        vals = [lv["A1_euler"], lv["A2_inlet_area"], lv["A3_volume_regression"], lv["A6_all"],
                lv["A7_shrink_vs_v5"],
                lv["D1_implant_subset_cavity"] and lv["D1_mask_narrow_subset_mask"],
                lv["D2_hierarchy_monotonic"], lv["D3_implant_within_zwin"]]
        fl = " ".join(f"{('T' if v else 'F'):>2}" for v in vals)
        print(f"{lv['tag']:<22}{lv['mm']:>3g}{lv['R_vox']:>3}{lv['implant_vox']:>9}{lv['mask_narrow_vox']:>9}"
              f"{lv['cells']:>8}{lv['inletL']['area_mm2']:>7}{lv['inletR']['area_mm2']:>7}  {fl}")
    print("-" * len(hdr))
    print("A2参考(v5): inletL=95.3mm2 inletR=149.1mm2 | A7基线zwin最小截面 8137vox=994.6mm2")
    print("all_required_true =", qc["all_required_true"], " runtime =", qc["runtime_s"], "s")
    print("[完成]", out_dir)
    return 0 if qc["all_required_true"] else 1


if __name__ == "__main__":
    sys.exit(main())