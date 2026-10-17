# -*- coding: utf-8 -*-
import sys, numpy as np, manifold3d as m
sys.path.insert(0, r"F:\比赛项目\罕见无界黑客松\开源仓库\code\pipeline\synth")
import gen_geometry as G

c = m.Manifold.cylinder(4.0, 0.977, 0.977, circular_segments=32)
for tag, mf in (("raw", c), ("as_original", c.as_original())):
    mesh = mf.to_mesh()
    vp = np.asarray(mesh.vert_properties).reshape(-1,3)
    zs = np.unique(np.round(vp[:,2],5))
    print(tag, "nv", len(vp), "z-range", round(zs.min(),5), round(zs.max(),5), "n_unique_z", len(zs))

f = G.frustum([-9,0,0], [-9,0.2,4], 0.977, 0.977)
for tag, mf in (("frustum", f), ("frustum_as_orig", f.as_original())):
    mesh = mf.to_mesh()
    vp = np.asarray(mesh.vert_properties).reshape(-1,3)
    low = vp[vp[:,2] < 0.35]
    r = np.sort(np.round(np.sqrt((low[:,0]+9.0)**2 + low[:,1]**2), 4))
    print(tag, "nv", len(vp), "zmin", round(vp[:,2].min(),4), "low r[:6]", r[:6], "low r[-3:]", r[-3:])

U = f.scale([1.0, 1.0, 1.0104])
mesh = U.as_original().to_mesh()
vp = np.asarray(mesh.vert_properties).reshape(-1,3)
low = vp[vp[:,2] < 0.35]
r = np.sort(np.round(np.sqrt((low[:,0]+9.0)**2 + low[:,1]**2), 4))
print("scaled", "nv", len(vp), "zmin", round(vp[:,2].min(),4), "low r[:6]", r[:6], "low r[-3:]", r[-3:])
