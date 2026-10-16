# -*- coding: utf-8 -*-
"""make_slices_glb.py — 真实 CFD 切片 3D 导出（hero 图层「切片（速度/压力）」数据端）。

从 OpenFOAM 稳态解 internal.vtu（U 速度场 + p 压力场，米制）切 3 个解剖切面：
  矢状面 sag  normal=[1,0,0]（左右轴，VTU x 实测=inletL/inletR 分离轴）
  轴位面 ax   normal=[0,0,1]（垂直轴）
  冠状面 cor  normal=[0,1,0]（前后/流向轴）
每面两份顶点色网格（U=viridis 0–P98 |U|；p=RdYlBu_r P2–P98）→ 单 GLB 6 mesh：
  slice_sag_U / slice_sag_p / slice_ax_U / slice_ax_p / slice_cor_U / slice_cor_p
坐标与气道 GLB 同帧：perm[2,1,0]（VTU z,y,x → GLB x,y,z）×1000 转 mm + bbox 自校准平移，
含入断言 >=0.8（对齐 align_frames/pN 流线同款经验）。
输出 webapp/models/slices_<cid>.glb + slices_meta_<cid>.json（色标范围/物理指纹，前端图例用）。

用法：venv python make_slices_glb.py [pA pB]
"""
import json
import sys
import numpy as np
import pyvista as pv
import trimesh
import matplotlib
from matplotlib import colormaps as _cmaps

BASE = r"F:\比赛项目\罕见无界黑客松\开源仓库\code\pipeline\out\结果"
MODELS = r"F:\比赛项目\罕见无界黑客松\开源仓库\code\pipeline\webapp\models"

CASES = {
    "pA": {
        "vtu": BASE + r"\P0-result-pA-v1\VTK\P0-case-pA-v1_1500\internal.vtu",
        "bnd": BASE + r"\P0-result-pA-v1\VTK\P0-case-pA-v1_1500\boundary",
        "glb": MODELS + r"\airway_pA.glb",
        "label": "患者A",
    },
    "pB": {
        "vtu": BASE + r"\P0-result-pB-v1\VTK\P0-case-pB-v1_1500\internal.vtu",
        "bnd": BASE + r"\P0-result-pB-v1\VTK\P0-case-pB-v1_1500\boundary",
        "glb": MODELS + r"\airway_pB.glb",
        "label": "患者B",
    },
}
PERM = [2, 1, 0]            # GLB(x,y,z) = VTU(z,y,x) x1000
MM = 1000.0
FLOW_AXIS_EXPECT = 1        # 实测经验：VTU y=流向（入口鼻孔 -> 出口鼻咽）
SAG_N, AX_N, COR_N = [1, 0, 0], [0, 0, 1], [0, 1, 0]
WIN_MM, STEP_MM = 10.0, 2.0  # 切面 origin 微调窗口（中线锚点 +-10mm 步进 2mm 取最大面积）


def cmap256(name):
    cm = _cmaps[name]
    return (cm(np.linspace(0.0, 1.0, 256))[:, :3])


def hex10(name):
    cm = _cmaps[name]
    out = []
    for t in np.linspace(0, 1, 11):
        c = np.asarray(cm(float(t)))[:3]
        out.append("#%02x%02x%02x" % tuple((c * 255).astype(int)))
    return out


def patch_centroid(path):
    p = pv.read(path)
    return np.asarray(p.points).mean(axis=0)


def pick_origin_axis(lo, hi, anchor, axis):
    """沿 axis 轴在 anchor（米制）附近 WIN 窗口内步进扫掠，取切面面积最大的 origin。
    全程米制（与 SLICE_SRC 同单位）；返回 (origin_m, area)。"""
    best = (None, -1.0)
    step = STEP_MM / MM
    win = WIN_MM / MM
    a0 = float(np.clip(anchor, lo, hi))
    k = -int(round(win / step))
    while k <= int(round(win / step)):
        c = a0 + k * step
        if lo - 1e-9 <= c <= hi + 1e-9:
            n = np.zeros(3); n[axis] = 1.0
            o = np.zeros(3); o[axis] = c
            sl = SLICE_SRC.slice(normal=n, origin=o)
            if sl.n_cells > 0:
                ar = float(sl.n_cells)      # 切面规模代理（sl.area 实测不可靠，返回 0）
                if ar > best[1]:
                    best = (c, ar)
        k += 1
    return best


def compact(V, F, C):
    """去退化三角形 + 未用顶点压缩（确定性，不依赖 trimesh.process）。"""
    F = np.asarray(F, dtype=np.int64)
    tri = F[:, :3]
    good = (tri[:, 0] != tri[:, 1]) & (tri[:, 1] != tri[:, 2]) & (tri[:, 0] != tri[:, 2])
    tri = tri[good]
    e1 = V[tri[:, 1]] - V[tri[:, 0]]
    e2 = V[tri[:, 2]] - V[tri[:, 0]]
    ar = 0.5 * np.linalg.norm(np.cross(e1, e2), axis=1)
    tri = tri[ar > 1e-9]
    used = np.unique(tri)
    remap = -np.ones(len(V), dtype=np.int64)
    remap[used] = np.arange(len(used))
    return V[used], remap[tri], C[used], int(good.sum() - len(tri))


def make_case(cid):
    cfg = CASES[cid]
    print("== %s（%s）==" % (cid, cfg["label"]))
    m = pv.read(cfg["vtu"])
    U = np.asarray(m.point_data["U"])[:, :3]
    mag = np.linalg.norm(U, axis=1)
    p = np.asarray(m.point_data["p"]).ravel()
    pts_of = np.asarray(m.points) * MM            # mm, OF/VTU 帧

    # ---- 轴向实测（不盲信任务书）：入口/出口补片质心 ----
    cin = 0.5 * (patch_centroid(cfg["bnd"] + r"\inletL.vtp") +
                 patch_centroid(cfg["bnd"] + r"\inletR.vtp")) * MM
    cout = patch_centroid(cfg["bnd"] + r"\outlet.vtp") * MM
    flow_axis = int(np.argmax(np.abs(cout - cin)))
    lr = patch_centroid(cfg["bnd"] + r"\inletL.vtp") - patch_centroid(cfg["bnd"] + r"\inletR.vtp")
    lr_axis = int(np.argmax(np.abs(lr * MM)))
    assert flow_axis == FLOW_AXIS_EXPECT, "流向轴实测 %d != 预期 %d" % (flow_axis, FLOW_AXIS_EXPECT)
    assert lr_axis == 0, "左右分离轴实测 %d != 0（x）" % lr_axis
    print("  轴向实测：流向=y 左右=x 垂直=z（inlet->outlet dy=%.1fmm）" % (cout[1] - cin[1]))

    # ---- GLB 帧自校准：perm + bbox 平移 + 含入断言 ----
    g = trimesh.load(cfg["glb"], process=False)
    if isinstance(g, trimesh.Scene):
        g = trimesh.util.concatenate([gm for gm in g.geometry.values()])
    gv = np.asarray(g.vertices)
    Q0 = pts_of[:, PERM]
    trans = gv.min(axis=0) - Q0.min(axis=0)
    Q = Q0 + trans
    inter = np.minimum(Q.max(axis=0), gv.max(axis=0)) - np.maximum(Q.min(axis=0), gv.min(axis=0))
    cover = float(np.min(np.clip(inter, 0, None) / np.maximum(Q.max(axis=0) - Q.min(axis=0), 1e-9)))
    assert cover >= 0.8, "bbox 含入 %.3f < 0.8（帧对齐失败）" % cover
    print("  GLB 帧自校准：trans=%s cover=%.3f" % (np.round(trans, 2).tolist(), cover))

    # ---- 三切面（中线锚点=流体质心，窗口内取最大面积）----
    global SLICE_SRC
    SLICE_SRC = m
    centroids = pts_of.mean(axis=0)
    planes = {"sag": (SAG_N, 0), "ax": (AX_N, 2), "cor": (COR_N, 1)}
    slices, fp = {}, {}
    for pn, (nrm, ax_i) in planes.items():
        c, ar = pick_origin_axis(m.bounds[2 * ax_i], m.bounds[2 * ax_i + 1],
                                 centroids[ax_i] / MM, ax_i)
        assert c is not None, "%s 面窗口内无有效切片" % pn
        n = np.zeros(3); n[ax_i] = 1.0
        o = np.zeros(3); o[ax_i] = c
        sl = m.slice(normal=n, origin=o).triangulate().clean(tolerance=1e-7)
        assert sl.n_points > 100, "%s 切面过小（%d 点）" % (pn, sl.n_points)
        su = np.asarray(sl.point_data["U"])[:, :3]
        smag = np.linalg.norm(su, axis=1)
        sp = np.asarray(sl.point_data["p"]).ravel()
        slp = np.asarray(sl.points) * MM
        fa = np.asarray(sl.faces)
        assert len(fa) % 4 == 0 and bool((fa[::4] == 3).all()), "%s 面含非三角形 cell" % pn
        F3 = fa.reshape(-1, 4)[:, 1:].astype(np.int64)
        e1 = slp[F3[:, 1]] - slp[F3[:, 0]]
        e2 = slp[F3[:, 2]] - slp[F3[:, 0]]
        area_mm2 = float(0.5 * np.linalg.norm(np.cross(e1, e2), axis=1).sum())
        slices[pn] = (slp, F3, smag, sp, area_mm2)
        print("  %s面 origin_%s=%.1fmm 面积=%.0fmm2 三角=%d" % (pn, "xyz"[ax_i], c * MM, area_mm2, sl.n_cells))
        # 物理指纹：沿流向 y 分 8 段（cor 面法向=y，全程同 y，跳过）
        if pn != "cor":
            ylo, yhi = slp[:, 1].min(), slp[:, 1].max()
            rows = []
            for b in range(8):
                s = (slp[:, 1] >= ylo + (yhi - ylo) * b / 8) & (slp[:, 1] < ylo + (yhi - ylo) * (b + 1) / 8)
                if s.sum() < 5:
                    rows.append(None); continue
                rows.append({"n": int(s.sum()), "U_mean": float(smag[s].mean()),
                             "U_p95": float(np.percentile(smag[s], 95)), "p_mean": float(sp[s].mean())})
            fp[pn] = {"bins": rows}
            print("    流向指纹(y 8 段) U_mean: %s" % " ".join("%.2f" % r["U_mean"] if r else "—" for r in rows))
            print("                    p_mean : %s" % " ".join("%.1f" % r["p_mean"] if r else "—" for r in rows))

    # ---- 物理合理性断言（入口均匀低压降沿程递减/鼻阀加速）----
    fs = fp["sag"]["bins"]
    ok = [b for b in fs if b]
    assert ok[0]["p_mean"] > ok[-1]["p_mean"] + 2.0, "矢状面压力未沿流向递减（%.1f -> %.1f）" % (
        ok[0]["p_mean"], ok[-1]["p_mean"])
    peak = max(b["U_p95"] for b in ok)
    assert peak > ok[0]["U_p95"] * 1.15, "矢状面未见鼻阀/狭窄加速峰（入口 p95 %.2f vs 峰 %.2f）" % (
        ok[0]["U_p95"], peak)
    print("  物理断言通过：压降 %.1f->%.1f Pa，速度峰 p95 %.2f（入口 %.2f）" % (
        ok[0]["p_mean"], ok[-1]["p_mean"], peak, ok[0]["U_p95"]))

    # ---- 色标归一化 + 顶点色 ----
    allu = np.concatenate([s[2] for s in slices.values()])
    allp = np.concatenate([s[3] for s in slices.values()])
    umax = float(np.percentile(allu, 98))
    plo, phi = float(np.percentile(allp, 2)), float(np.percentile(allp, 98))
    cv = cmap256("viridis"); cp = cmap256("RdYlBu_r")

    def col_u(v):
        t = np.asarray(v) / max(umax, 1e-9)
        return (cv[np.clip(t * 255, 0, 255).astype(int)] * 255).astype(np.uint8)

    def col_p(v):
        t = (np.asarray(v) - plo) / max(phi - plo, 1e-9)
        return (cp[np.clip(t * 255, 0, 255).astype(int)] * 255).astype(np.uint8)

    scene = trimesh.Scene()
    meshes_meta = {}
    for pn in ("sag", "ax", "cor"):
        slp, faces, smag, sp, area = slices[pn]
        Vg = slp[:, PERM] + trans                # mm，GLB 帧
        for fld, arr, cm_name in (("U", smag, "viridis"), ("p", sp, "RdYlBu_r")):
            C8 = col_u(arr) if fld == "U" else col_p(arr)
            V2, F2, C2, ndeg = compact(Vg, faces, C8)
            tm = trimesh.Trimesh(vertices=V2, faces=F2, face_colors=None,
                                 vertex_colors=C2, process=False)
            name = "slice_%s_%s" % (pn, fld)
            scene.add_geometry(tm, node_name=name, geom_name=name)
            meshes_meta[name] = {
                "field": fld, "plane": pn,
                "plane_cn": {"sag": "矢状", "ax": "轴位", "cor": "冠状"}[pn],
                "vmin": 0.0 if fld == "U" else round(plo, 2),
                "vmax": round(umax, 2) if fld == "U" else round(phi, 2),
                "unit": "m/s" if fld == "U" else "Pa",
                "cmap": cm_name, "n_faces": int(len(F2)), "area_mm2": round(float(area), 1),
            }
            print("  %s: %d 三角（去退化 %d）" % (name, len(F2), ndeg))
    out_glb = MODELS + r"\slices_%s.glb" % cid
    scene.export(out_glb)
    meta = {
        "cid": cid, "label": cfg["label"],
        "source": "P0-result-%s-v1 internal.vtu @1500 步稳态解（simpleFoam，15 L/min）" % cid,
        "frame": "与气道 GLB 同帧：perm[2,1,0] x1000 + 平移 %s mm；bbox含入=%.3f" % (
            [round(float(t), 2) for t in trans], cover),
        "colormaps": {"U": hex10("viridis"), "p": hex10("RdYlBu_r")},
        "meshes": meshes_meta,
        "physics_check": fp,
    }
    with open(MODELS + r"\slices_meta_%s.json" % cid, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)

    # ---- 导出验证：GLB JSON chunk 的 mesh 命名 + COLOR_0 存在 ----
    with open(out_glb, "rb") as f:
        blob = f.read()
    jl = int.from_bytes(blob[12:16], "little")
    gj = json.loads(blob[20:20 + jl].decode("utf-8"))
    names = sorted(mm.get("name", "") for mm in gj.get("meshes", []))
    hascol = all("COLOR_0" in pr["attributes"] for mm in gj["meshes"] for pr in mm["primitives"])
    assert len(names) == 6 and hascol, "GLB 验证失败 names=%s COLOR_0=%s" % (names, hascol)
    print("  导出 %s（%.1f MB）mesh=%s COLOR_0=OK" % (out_glb.split("\\")[-1], len(blob) / 1e6, names))


if __name__ == "__main__":
    ids = sys.argv[1:] or ["pA", "pB"]
    for cid in ids:
        make_case(cid)
    print("ALL DONE")
