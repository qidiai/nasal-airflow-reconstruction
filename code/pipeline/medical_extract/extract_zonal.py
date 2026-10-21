# -*- coding: utf-8 -*-
"""
T17-F1 extract_zonal.py —— 鼻腔 z 向三带边界切面 U·n 通量积分 → 分区通气占比 → viewer_plus_data.js
（会上共识指标「总鼻道中下方 + 嗅区通气量」的真实流场版 · 数据管道第 3 脚本）

物理模型（任务书授权口径「切面通量积分（分区通气近似）」）：
  鼻腔沿 z（viewer z-up，颅顶-颈项）分三带：上 1/3=嗅区带 / 中带=中鼻道 / 下带=下鼻道。
  在两处带边界高度取水平切面（法向 ẑ），积分向上通量 Q_up(z) = Σ max(0, U·ẑ)·dA：
    嗅区带流量 ≈ Q_up(b_mid)   （穿过中/上边界的向上流量 → 去嗅区）
    中鼻道带   ≈ Q_up(b_low) − Q_up(b_mid)
    下鼻道带   ≈ Q0 − Q_up(b_low)
  占比 = 各带 / Q0（Q0 = 15 L/min 定流量边界，v5 锚点）。
  主流沿前后向水平流动（U·ẑ≈0），逐级上升分量由边界切面捕捉——如实标注近似。
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
Q0_L_MIN = 15.000015732560104   # v5 metrics.json totals.Q_inlet_total_L_min（定流量锚点）


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
           '// 说明：科研与康复参考 · 非医疗器械 · 仿真估计 · 非临床测量\n'
           'window.VIEWER_PLUS_DATA = ' + body + ';\n')
    with io.open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(txt)


def flux_up_at_z(mesh, pts_mm, ai, z_mm):
    """在轴坐标 z_mm（mm-质心系）取水平切面，返回向上通量 Q_up（m³/s）与切面点数。"""
    org = CENTER_MM.copy()
    org[ai] = (z_mm + CENTER_MM[ai]) / 1000.0
    sl = mesh.slice(normal=np.array([0.0, 0.0, 1.0]), origin=org)
    if sl.n_points == 0:
        return 0.0, 0
    sl = sl.compute_cell_sizes(length=False, area=True, volume=False)
    areas = np.asarray(sl.cell_data['Area'], dtype=np.float64)   # m²
    U = np.asarray(sl.point_data['U'], dtype=np.float64)
    uz = U[:, 2]                                                  # m/s，z 分量
    # 面片值 = 面片顶点均值（PolyData.faces: [nv, i, j, k, ...] 混合拓扑）
    faces = np.asarray(sl.faces)
    per_face_uz = np.zeros(sl.n_cells, dtype=np.float64)
    i = 0
    fi = 0
    while i < len(faces):
        nv = faces[i]
        verts = faces[i + 1:i + 1 + nv]
        per_face_uz[fi] = uz[verts].mean()
        i += nv + 1
        fi += 1
    q_up = float(np.sum(np.maximum(per_face_uz, 0.0) * areas))   # m³/s（只计向上分量）
    return q_up, int(sl.n_points)


def main():
    print('[zonal] reading', VTU)
    mesh = pv.read(VTU)
    pts_mm = np.asarray(mesh.points, dtype=np.float64) * 1000.0 - CENTER_MM
    z_axis = pts_mm[:, 2]
    lo, hi = np.percentile(z_axis, [2.0, 98.0])
    band_h = (hi - lo) / 3.0
    b_low = lo + band_h       # 下带/中带边界
    b_mid = lo + 2 * band_h   # 中带/上带（嗅区）边界
    print('[zonal] 场点 z 有效范围 %.1f..%.1f mm（质心系，z+ 为颅顶向）' % (lo, hi))
    print('[zonal] 边界切面：b_low=%.1f  b_mid=%.1f' % (b_low, b_mid))

    q_up_low, n1 = flux_up_at_z(mesh, pts_mm, 2, b_low)
    q_up_mid, n2 = flux_up_at_z(mesh, pts_mm, 2, b_mid)
    print('[zonal] Q_up(b_low)=%.3e m³/s (%d pts)  Q_up(b_mid)=%.3e m³/s (%d pts)' %
          (q_up_low, n1, q_up_mid, n2))

    q0_m3s = Q0_L_MIN / 60000.0
    q_olf = max(q_up_mid, 0.0)
    q_mid = max(q_up_low - q_up_mid, 0.0)
    q_inf = max(q0_m3s - q_up_low, 0.0)
    tot = q_olf + q_mid + q_inf
    shares = [q_olf / q0_m3s * 100, q_mid / q0_m3s * 100, q_inf / q0_m3s * 100]
    print('[zonal] 带流量（L/min）：嗅区 %.3f / 中鼻道 %.3f / 下鼻道 %.3f' %
          (q_olf * 60000, q_mid * 60000, q_inf * 60000))
    print('[zonal] 占比：嗅区 %.1f%% / 中鼻道 %.1f%% / 下鼻道 %.1f%%' % tuple(shares))

    result = {
        'method': '切面通量积分（分区通气近似）：带边界水平切面 Q_up=Σ max(0,U·ẑ)dA，逐级分解',
        'note': '切面通量积分（分区通气近似）· 非临床测量',
        'consensus': '总鼻道中下方 + 嗅区通气量（会上共识评估标准的流场近似版）',
        'Q0_L_min': round(Q0_L_MIN, 3),
        'z_range_mm': [round(float(lo), 1), round(float(hi))],
        'boundaries_mm': {'b_low': round(float(b_low), 1), 'b_mid': round(float(b_mid), 1)},
        'slice_pts': {'b_low': n1, 'b_mid': n2},
        'bands': [
            {'key': 'olfactory', 'name': '嗅区带（上1/3）', 'Q_L_min': round(q_olf * 60000, 3), 'share_pct': round(shares[0], 1)},
            {'key': 'middle', 'name': '中鼻道带（中1/3）', 'Q_L_min': round(q_mid * 60000, 3), 'share_pct': round(shares[1], 1)},
            {'key': 'inferior', 'name': '下鼻道带（下1/3）', 'Q_L_min': round(q_inf * 60000, 3), 'share_pct': round(shares[2], 1)},
        ],
        'share_sum_pct': round(sum(shares), 1),
    }
    # sanity
    assert all(np.isfinite(shares)), '占比非有限值'

    obj = read_json_blob(OUT)
    if obj is None:
        obj = {}
        print('[zonal] creating new viewer_plus_data.js')
    obj['zonal'] = result
    write_json_blob(OUT, obj)
    print('[zonal] OK -> %s (%.2f MB)' % (OUT, os.path.getsize(OUT) / 1048576.0))
    return 0


if __name__ == '__main__':
    sys.exit(main())
