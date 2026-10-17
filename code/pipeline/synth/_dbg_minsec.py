# -*- coding: utf-8 -*-
import sys, numpy as np, trimesh
sys.path.insert(0, r"F:\比赛项目\罕见无界黑客松\开源仓库\code\pipeline\synth")
import gen_geometry as G

for name in ("synth-004", "synth-005", "synth-001"):
    p = [g for g in G.GRID if g["case"] == name][0]
    U, tune = G.build_full(p)
    st = U.status()
    print(name, "status=", st, "genus=", U.genus(), "vol=", round(U.volume()/1000,2))
    tm = trimesh.load(rf"F:\比赛项目\罕见无界黑客松\开源仓库\code\pipeline\out\synth\{name}\geometry.stl")
    print("  watertight=", tm.is_watertight, "bodies=", tm.body_count, "euler=", tm.euler_number)
    for z in (0.02, 0.05, 0.2, 0.5, 1.0, 2.0, 3.5, 3.95):
        sl = tm.section(plane_origin=[0,0,z], plane_normal=[0,0,1])
        if sl is None:
            print(f"  z={z}: None"); continue
        info = []
        for poly in sl.discrete:
            arr = np.asarray(poly, float)
            a = G._poly_area(arr[:,:2]); cx = arr[:,0].mean()
            info.append((round(a,3), round(cx,2)))
        print(f"  z={z}: {info}")
