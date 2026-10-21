# -*- coding: utf-8 -*-
"""
T17-F1 extract_planes.py —— internal.vtu 三向切面序列提取 → viewer_plus_data.js
（SimScale「任意切面扫描」逆向集成 · 数据管道第 1 脚本）

输入 : 阶段2-CFD算例包/结果/P0-result-pA-v5/VTK/P0-case-v5_1500/internal.vtu
       （40.9MB，全场 U/p/wallShearStress，米坐标）
输出 : 升级施工-T17/viewer_plus_data.js 的 `planes` 键（读-改-写，幂等，不碰其他键）

坐标契约：viewer_data.js 为 mm 且已减 airwayMesh 质心 CENTER(mm)=[79.22,71.87,56.98]，
本脚本切面点做同款变换（m→mm×1000，再减 CENTER），保证与流线/气道壳同帧。

量化契约：pos=int16×0.1mm；vel=int16×0.001 m/s；p=int16×0.01 Pa；base64 编码。
每层抽稀 ≤6000 点（等距抽样）。三向各 NL=28 层，层位取场点分布 P2–P98 均匀铺层。
"""
import base64
import io
import json
import os
import sys

import numpy as np
import pyvista as pv

sys.stdout.reconfigure(encoding='utf-8')

ROOT = r'F:\比赛项目\罕见无界黑客松\赛题3-鼻腔气流分析\项目\P0-鼻塞设计工具'
VTU = ROOT + r'\阶段2-CFD算例包\结果\P0-result-pA-v5\VTK\P0-case-v5_1500\internal.vtu'
OUT = ROOT + r'\阶段5-交互查看器\升级施工-T17\viewer_plus_data.js'

CENTER_MM = np.array([79.22, 71.87, 56.98])
NL = 28            # 每向层数（任务书 24-32 取中）
MAX_PTS = 6000     # 每层抽稀上限
Q_POS = 0.1        # mm / LSB
Q_VEL = 0.001      # m/s / LSB
Q_P = 0.01         # Pa / LSB


def b64_i16(arr_f32, scale):
    q = np.round(np.asarray(arr_f32, dtype=np.float64) / scale).astype(np.int16)
    return base64.b64encode(q.tobytes()).decode('ascii')


def read_json_blob(path):
    """读 viewer_plus_data.js（window.VIEWER_PLUS_DATA = {...}; 形态）→ dict。不存在则返回 None。"""
    if not os.path.isfile(path):
        return None
    s = io.open(path, 'r', encoding='utf-8').read()
    i = s.find('{')
    j = s.rfind('}')
    if i < 0 or j <= i:
        return None
    return json.loads(s[i:j + 1])


def write_json_blob(path, obj):
    """写 viewer_plus_data.js，LF-only，键序保持插入序。"""
    body = json.dumps(obj, ensure_ascii=False, separators=(',', ':'))
    txt = ('// viewer_plus_data.js —— T17 SimScale后处理集成数据包（生成脚本：升级施工-T17/extract_*.py）\n'
           '// 坐标系：mm，已减 airwayMesh 质心 CENTER=[79.22,71.87,56.98]（与 viewer_data.js 同帧）\n'
           '// 说明：科研与康复参考 · 非医疗器械 · 仿真估计 · 非临床测量\n'
           'window.VIEWER_PLUS_DATA = ' + body + ';\n')
    with io.open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(txt)


def main():
    print('[planes] reading', VTU)
    mesh = pv.read(VTU)
    pts_m = np.asarray(mesh.points, dtype=np.float64)
    pts_mm = pts_m * 1000.0 - CENTER_MM          # 变换到 viewer 同帧（mm-质心系）
    U = np.asarray(mesh.point_data['U'], dtype=np.float64)
    vel = np.linalg.norm(U, axis=1) if U.ndim == 2 else np.abs(U)
    p = np.asarray(mesh.point_data['p'], dtype=np.float64).ravel()
    n = len(pts_mm)
    print('[planes] n_points=%d  vel=%.3f..%.3f m/s  p=%.2f..%.2f Pa' %
          (n, vel.min(), vel.max(), p.min(), p.max()))

    # 三向定义：法向 + 该轴索引
    axes = [
        ('axial',    2, np.array([0.0, 0.0, 1.0])),   # 轴位：法向 z（viewer z-up，颅顶-颈项）
        ('coronal',  1, np.array([0.0, 1.0, 0.0])),   # 冠状：法向 y（左右）
        ('sagittal', 0, np.array([1.0, 0.0, 0.0])),   # 矢状：法向 x（前后）
    ]

    planes = {
        'method': 'internal.vtu 场点沿轴三向切面（pyvista slice 点插值）；mm-质心系；每层≤%d点' % MAX_PTS,
        'quant': {'pos_scale_mm': Q_POS, 'vel_scale_ms': Q_VEL, 'p_scale_Pa': Q_P,
                  'dtype': 'int16', 'enc': 'base64',
                  'vel_range_ms': [round(float(vel.min()), 3), round(float(vel.max()), 3)],
                  'p_range_Pa': [round(float(p.min()), 2), round(float(p.max()), 2)],
                  'vel_p98_ms': round(float(np.percentile(vel, 98)), 2)},
        'n_layers_per_axis': NL,
        'coord_center_mm': CENTER_MM.tolist(),
    }

    for name, ai, nrm in axes:
        axis_vals = pts_mm[:, ai]
        lo, hi = np.percentile(axis_vals, [2.0, 98.0])
        zs = np.linspace(lo, hi, NL)
        origin_m = (CENTER_MM.copy())
        origin_m[ai] = 0.0
        layers = []
        total_pts = 0
        for li, z_mm in enumerate(zs):
            org = origin_m.copy()
            org[ai] = (z_mm + CENTER_MM[ai]) / 1000.0   # 回米坐标做 slice
            sl = mesh.slice(normal=nrm, origin=org)
            sp = np.asarray(sl.points, dtype=np.float64)
            if len(sp) == 0:
                layers.append({'pos_b64': '', 'vel_b64': '', 'p_b64': '', 'n': 0, 'coord_mm': round(float(z_mm), 1)})
                continue
            sp_mm = sp * 1000.0 - CENTER_MM
            su = np.asarray(sl.point_data['U'], dtype=np.float64)
            sv = np.linalg.norm(su, axis=1) if su.ndim == 2 else np.abs(su)
            spv = np.asarray(sl.point_data['p'], dtype=np.float64).ravel()
            if len(sp) > MAX_PTS:                        # 等距抽稀
                idx = np.linspace(0, len(sp) - 1, MAX_PTS).astype(np.int64)
                sp_mm, sv, spv = sp_mm[idx], sv[idx], spv[idx]
            total_pts += len(sp_mm)
            layers.append({
                'n': int(len(sp_mm)),
                'coord_mm': round(float(z_mm), 1),
                'pos_b64': b64_i16(sp_mm.ravel(), Q_POS),
                'vel_b64': b64_i16(sv, Q_VEL),
                'p_b64': b64_i16(spv, Q_P),
            })
        planes[name] = {
            'axis': int(ai),
            'layers': layers,
            'total_pts': int(total_pts),
            'range_mm': [round(float(lo), 1), round(float(hi), 1)],
        }
        print('[planes] %-8s %d layers, %d pts total' % (name, NL, total_pts))

    obj = read_json_blob(OUT)
    if obj is None:
        obj = {}
        print('[planes] creating new viewer_plus_data.js')
    obj['planes'] = planes
    write_json_blob(OUT, obj)
    sz = os.path.getsize(OUT)
    print('[planes] OK -> %s  (%.2f MB whole file)' % (OUT, sz / 1048576.0))
    return 0


if __name__ == '__main__':
    sys.exit(main())
