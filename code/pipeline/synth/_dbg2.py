# -*- coding: utf-8 -*-
import sys, numpy as np, trimesh
sys.path.insert(0, r"F:\比赛项目\罕见无界黑客松\开源仓库\code\pipeline\synth")
import gen_geometry as G
p = [g for g in G.GRID if g["case"] == "synth-004"][0]
U, tune = G.build_full(p)
print("tune:", tune)
mesh = U.as_original().to_mesh()
vp = np.asarray(mesh.vert_properties).reshape(-1,3)
tv = np.asarray(mesh.tri_verts).reshape(-1,3)
print("in-memory mesh: nv", len(vp), "nt", len(tv))
# 左鼻孔附近顶点（x in [-11,-7], z<0.6）
sel = np.where((vp[:,0] > -11.5) & (vp[:,0] < -6.5) & (vp[:,2] < 0.6))[0]
zs = np.sort(np.unique(np.round(vp[sel,2], 4)))
print("unique z of left-nostril verts (z<0.6):", zs[:12])
for z in zs[:6]:
    m = np.abs(vp[sel,2] - z) < 1e-4
    pts = vp[sel][m]
    r = np.sqrt((pts[:,0]+9.0)**2 + pts[:,1]**2)
    print(f"  z={z:.4f} n={len(pts)} r range [{r.min():.4f},{r.max():.4f}]")
# 内存 mesh 直接 section
tm2 = trimesh.Trimesh(vertices=vp, faces=tv, process=False)
print("in-memory watertight:", tm2.is_watertight)
for z in (0.02, 0.05, 0.2, 0.5):
    sl = tm2.section(plane_origin=[0,0,z], plane_normal=[0,0,1])
    if sl is None: print(f"  mem z={z}: None"); continue
    info = [(round(G._poly_area(np.asarray(pl,float)[:,:2]),3), round(float(np.asarray(pl,float)[:,0].mean()),2)) for pl in sl.discrete]
    print(f"  mem z={z}: {info}")
