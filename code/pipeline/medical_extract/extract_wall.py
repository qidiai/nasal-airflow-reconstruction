# -*- coding: utf-8 -*-
"""
T17-F1 extract_wall.py —— walls.vtp 壁面 WSS → airwayMesh/cavity/sinus 顶点标量 → viewer_plus_data.js
（SimScale「壁面场渲染」逆向集成 · 数据管道第 2 脚本）

输入 : 阶段2-CFD算例包/结果/P0-result-pA-v5/VTK/P0-case-v5_1500/boundary/walls.vtp（13.4MB）
       阶段5-交互查看器/viewer_data.js（只读引用：airwayMesh/airwayCavity/airwaySinus 顶点坐标）
输出 : viewer_plus_data.js 的 `wallWSS` 键（读-改-写，幂等）

映射契约：walls.vtp 的 wallShearStress 为矢量场（OpenFOAM），取模长 |WSS|；
米→mm×1000 减 CENTER 后，用 scipy cKDTree 对三组网格顶点各自最近邻映射。
量化：int16×0.0001 Pa，base64。数组序 = 各网格 positions 数组序（顶点一一对应）。
"""
import base64
import io
import json
import os
import re
import sys

import numpy as np
import pyvista as pv
from scipy.spatial import cKDTree

sys.stdout.reconfigure(encoding='utf-8')

ROOT = r'F:\比赛项目\罕见无界黑客松\赛题3-鼻腔气流分析\项目\P0-鼻塞设计工具'
WALL = ROOT + r'\阶段2-CFD算例包\结果\P0-result-pA-v5\VTK\P0-case-v5_1500\boundary\walls.vtp'
VDATA = ROOT + r'\阶段5-交互查看器\viewer_data.js'
OUT = ROOT + r'\阶段5-交互查看器\升级施工-T17\viewer_plus_data.js'

CENTER_MM = np.array([79.22, 71.87, 56.98])
Q_WSS = 0.0001   # Pa / LSB


def b64_i16(arr_f32, scale):
    q = np.round(np.asarray(arr_f32, dtype=np.float64) / scale).astype(np.int16)
    return base64.b64encode(q.tobytes()).decode('ascii')


def read_json_blob(path):
    if not os.path.isfile(path):
        return None
    s = io.open(path, 'r', encoding='utf-8').read()
    i = s.find('{')
    j = s.rfind('}')
    if i < 0 or j <= i:
        return None
    return json.loads(s[i:j + 1])


def write_json_blob(path, obj):
    body = json.dumps(obj, ensure_ascii=False, separators=(',', ':'))
    txt = ('// viewer_plus_data.js —— T17 SimScale后处理集成数据包（生成脚本：升级施工-T17/extract_*.py）\n'
           '// 坐标系：mm，已减 airwayMesh 质心 CENTER=[79.22,71.87,56.98]（与 viewer_data.js 同帧）\n'
           '// 说明：概念验证 · 非医疗器械 · 仿真估计 · 非临床测量\n'
           'window.VIEWER_PLUS_DATA = ' + body + ';\n')
    with io.open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(txt)


def load_viewer_meshes():
    """从 viewer_data.js 提取三组网格顶点（json 子串解析，不执行 JS）。"""
    s = io.open(VDATA, 'r', encoding='utf-8').read()
    out = {}
    for key in ('airwayMesh', 'airwayCavity', 'airwaySinus'):
        i = s.find('"%s"' % key)
        if i < 0:
            print('[wall] viewer_data.js 无 %s（跳过）' % key)
            continue
        j = s.find('{', i)
        # 从 j 起做括号配平
        depth, k = 0, j
        while k < len(s):
            c = s[k]
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    break
            k += 1
        obj = json.loads(s[j:k + 1])
        pos = np.asarray(obj['positions'], dtype=np.float64).reshape(-1, 3)
        out[key] = pos
        print('[wall] %s: %d 顶点' % (key, len(pos)))
    return out


def main():
    print('[wall] reading', WALL)
    w = pv.read(WALL)
    wss_raw = None
    if 'wallShearStress' in w.point_data:
        wss_raw = np.asarray(w.point_data['wallShearStress'], dtype=np.float64)
    elif 'wallShearStress' in w.cell_data:
        wss_raw = np.asarray(w.cell_data['wallShearStress'], dtype=np.float64)
    if wss_raw is None:
        raise RuntimeError('walls.vtp 无 wallShearStress 场')
    if wss_raw.ndim == 2:
        wss = np.linalg.norm(wss_raw, axis=1)
    else:
        wss = np.abs(wss_raw.ravel())
    wp = np.asarray(w.points, dtype=np.float64) * 1000.0 - CENTER_MM
    print('[wall] %d 壁面点，|WSS| %.6f..%.6f Pa' % (len(wss), wss.min(), wss.max()))

    tree = cKDTree(wp)
    meshes = load_viewer_meshes()
    result = {
        'method': 'walls.vtp wallShearStress 矢量取模 → 最近邻映射到 viewer_data.js 网格顶点（cKDTree）',
        'quant': {'wss_scale_Pa': Q_WSS, 'dtype': 'int16', 'enc': 'base64'},
        'note': '壁面剪应力 WSS (Pa) · 仿真估计',
        'walls_src': {'n_points': int(len(wss)), 'min_Pa': float(wss.min()), 'max_Pa': float(wss.max()),
                      'p95_Pa': float(np.percentile(wss, 95)), 'mean_Pa': float(wss.mean())},
        'surfaces': {},
        'nn_max_dist_mm': {},
    }
    for key, pos in meshes.items():
        dist, idx = tree.query(pos, k=1)
        vals = wss[idx]
        result['surfaces'][key] = {
            'n_verts': int(len(pos)),
            'values_b64': b64_i16(vals, Q_WSS),
            'min_Pa': float(vals.min()), 'max_Pa': float(vals.max()),
            'p95_Pa': float(np.percentile(vals, 95)), 'mean_Pa': float(vals.mean()),
        }
        result['nn_max_dist_mm'][key] = float(np.percentile(dist, 99))
        print('[wall] %-13s -> n=%d  wss %.4f..%.4f Pa  nnP99dist=%.2fmm' %
              (key, len(pos), vals.min(), vals.max(), np.percentile(dist, 99)))

    obj = read_json_blob(OUT)
    if obj is None:
        obj = {}
        print('[wall] creating new viewer_plus_data.js')
    obj['wallWSS'] = result
    write_json_blob(OUT, obj)
    print('[wall] OK -> %s (%.2f MB)' % (OUT, os.path.getsize(OUT) / 1048576.0))
    return 0


if __name__ == '__main__':
    sys.exit(main())
