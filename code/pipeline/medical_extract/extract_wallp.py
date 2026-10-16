# -*- coding: utf-8 -*-
"""
T20-F1 extract_wallp.py —— walls.vtp 壁面静压 p（运动学压力 m²/s²）×ρ → 表压 Pa
                                 → airwayMesh/cavity/sinus 顶点标量 → viewer_plus_data.js `wallP` 键
（SimScale / CFD-Post「壁面静压着色」逆向集成 · T20 吸收批 A3）

输入 : 阶段2-CFD算例包/结果/P0-result-pA-v5/VTK/P0-case-v5_1500/boundary/walls.vtp
       阶段2-CFD算例包/结果/P0-result-pA-v5/后处理/metrics.json（仅取 ρ=1.2 与出口参考、分侧对拍值）
       阶段5-交互查看器/viewer_data.js（只读：airwayMesh/airwayCavity/airwaySinus 顶点坐标）
输出 : 阶段5-交互查看器/viewer_plus_data.js 的 `wallP` 键（读-改-写，幂等；**只追加不重写**其余字节）

单位铁律（K3 审计 F1 实证 · T20 吸收方案 v2 §0）：
  simpleFoam 不可压求解器导出的是运动学压力 p/ρ（m²/s²）；表压 Pa = p_field × ρ，**ρ 恒取 1.2**
  （与 metrics.json inputs.rho_kg_m3 同源；禁 1.204）。出口 patch p=0 → 数值即「以出口 0 为参考」的表压。
  壁面 U 场全零（无滑移壁面）——本脚本**只读 p**，禁用壁面 U 做任何着色。

映射：米→mm×1000 减 CENTER 后，cKDTree 最近邻映射到 viewer_data.js 三组网格顶点。
量化：int16 × 0.002 Pa/LSB（量程 ±3.38~30.46 Pa，int16 覆盖 ±65.53 Pa，无饱和），base64。
色标：**固定分位**——上限 = p99（写死进数据），下限 = (min 与 0 的中点)（写死进数据），
      避免高压带被对称色标弱化；0 为出口参考点，图例显式标注。
"""
import base64
import io
import json
import os
import shutil
import sys

import numpy as np
import pyvista as pv
from scipy.spatial import cKDTree

sys.stdout.reconfigure(encoding='utf-8')

ROOT = r'F:\比赛项目\罕见无界黑客松\赛题3-鼻腔气流分析\项目\P0-鼻塞设计工具'
CASE = ROOT + r'\阶段2-CFD算例包\结果\P0-result-pA-v5'
WALL = CASE + r'\VTK\P0-case-v5_1500\boundary\walls.vtp'
INL = [CASE + r'\VTK\P0-case-v5_1500\boundary\inletL.vtp',
       CASE + r'\VTK\P0-case-v5_1500\boundary\inletR.vtp']
METRICS = CASE + r'\后处理\metrics.json'
VDATA = ROOT + r'\阶段5-交互查看器\viewer_data.js'
OUT = ROOT + r'\阶段5-交互查看器\viewer_plus_data.js'
MIRROR = ROOT + r'\阶段5-交互查看器\升级施工-T17\viewer_plus_data.js'

CENTER_MM = np.array([79.22, 71.87, 56.98])
RHO = 1.2            # 铁律：与 metrics.json inputs.rho_kg_m3 同源，禁 1.204
Q_P = 0.002          # Pa / LSB
SURF_ORDER = ['airwayMesh', 'airwayCavity', 'airwaySinus']


def b64_i16(arr_f, scale):
    q = np.round(np.asarray(arr_f, dtype=np.float64) / scale).astype(np.int16)
    assert abs(q.astype(np.float64) * scale - np.asarray(arr_f, dtype=np.float64)).max() <= scale, '量化误差超 1 LSB'
    return base64.b64encode(q.tobytes()).decode('ascii')


def read_plus(path):
    """读 viewer_plus_data.js：返回 (header_text, obj)。header 原样保留（含既有注释行）。"""
    s = io.open(path, 'r', encoding='utf-8').read()
    i = s.find('window.VIEWER_PLUS_DATA')
    if i < 0:
        raise RuntimeError('未找到 window.VIEWER_PLUS_DATA: %s' % path)
    br = s.find('{', i)
    depth, k, instr, esc = 0, br, False, False
    while k < len(s):
        c = s[k]
        if instr:
            if esc:
                esc = False
            elif c == '\\':
                esc = True
            elif c == '"':
                instr = False
        else:
            if c == '"':
                instr = True
            elif c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    break
        k += 1
    return s[:i], json.loads(s[br:k + 1])


def write_plus(path, header, obj):
    """写回：header 逐字节保留 + json.dumps 同参序列化（与既有文件序列化口径一致 → 其余键字节不变）。"""
    body = json.dumps(obj, ensure_ascii=False, separators=(',', ':'))
    txt = header + 'window.VIEWER_PLUS_DATA = ' + body + ';\n'
    with io.open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(txt)


def load_viewer_meshes():
    s = io.open(VDATA, 'r', encoding='utf-8').read()
    out = {}
    for key in SURF_ORDER:
        i = s.find('"%s"' % key)
        if i < 0:
            raise RuntimeError('viewer_data.js 无 %s' % key)
        j = s.find('{', i)
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
        print('[wallP] %-13s %d 顶点' % (key, len(pos)))
    return out


def inlet_calib():
    """对拍：inlet patch 点 p 均值 ×1.2 → Pa，与 metrics.json patches.p_mean_Pa 比对（容差如实记录）。"""
    m = json.load(io.open(METRICS, 'r', encoding='utf-8'))
    rho_m = float(m['inputs']['rho_kg_m3'])
    res = {'rho_kg_m3__metrics': rho_m, 'rho_used': RHO,
           'p_outlet_Pa__metrics': float(m['totals']['p_outlet_Pa']),
           'note': '对拍口径：inlet patch 点值 p 均值 ×ρ vs metrics.json patches.*.p_mean_Pa（点/面加权差如实）'}
    for tag, fp in zip(('inletL', 'inletR'), INL):
        w = pv.read(fp)
        pm = float(np.asarray(w.point_data['p'], dtype=np.float64).mean()) * RHO
        mm = float(m['patches'][tag]['p_mean_Pa'])
        res[tag] = {'p_mean_walls_Pa': round(pm, 6), 'p_mean_metrics_Pa': mm,
                    'rel_err_pct': round(100.0 * (pm - mm) / mm, 4)}
        print('[wallP] 对拍 %s: %.4f Pa(重算) vs %.4f Pa(metrics)  err=%.4f%%' %
              (tag, pm, mm, res[tag]['rel_err_pct']))
    return res


def main():
    print('[wallP] reading', WALL)
    w = pv.read(WALL)
    if 'p' not in w.point_data:
        raise RuntimeError('walls.vtp 无 point_data["p"]（T20-A3 前提不成立）')
    p_kin = np.asarray(w.point_data['p'], dtype=np.float64).ravel()
    p_pa = p_kin * RHO
    print('[wallP] %d 壁面点  p∈[%.6f, %.6f] m2/s2  -> x%.1f 表压 p∈[%.4f, %.4f] Pa' %
          (len(p_pa), p_kin.min(), p_kin.max(), RHO, p_pa.min(), p_pa.max()))

    wp = np.asarray(w.points, dtype=np.float64) * 1000.0 - CENTER_MM
    tree = cKDTree(wp)
    meshes = load_viewer_meshes()

    surfaces = []
    nn_max = {}
    union = []
    for key in SURF_ORDER:
        pos = meshes[key]
        dist, idx = tree.query(pos, k=1)
        vals = p_pa[idx]
        union.append(vals)
        surfaces.append({
            'mesh': key,
            'n': int(len(pos)),
            'values_b64': b64_i16(vals, Q_P),
            'min_Pa': round(float(vals.min()), 4),
            'max_Pa': round(float(vals.max()), 4),
            'p99_Pa': round(float(np.percentile(vals, 99)), 4),
            'mean_Pa': round(float(vals.mean()), 4),
        })
        nn_max[key] = round(float(np.percentile(dist, 99)), 3)
        print('[wallP] %-13s n=%-6d 表压 %.3f..%.3f Pa  p99=%.3f  nnP99=%.2f mm' %
              (key, len(pos), vals.min(), vals.max(), np.percentile(vals, 99), np.percentile(dist, 99)))

    u = np.concatenate(union)
    p99 = float(np.percentile(u, 99))
    lo = float((u.min() + 0.0) / 2.0)
    result = {
        'method': "walls.vtp point_data['p']（OpenFOAM 运动学压力 m2/s2）×ρ=1.2 → 表压 Pa；"
                  "cKDTree 最近邻映射到 viewer_data.js 网格顶点（mm-质心系同帧）",
        'quant': {'p_scale_Pa': Q_P, 'dtype': 'int16', 'enc': 'base64'},
        'rho_kg_m3': RHO,
        'scale_note': '量程 p∈[−2.814, +25.381] m2/s2 ×1.2 → [−3.3768, +30.4577] Pa；'
                      'int16×0.002 Pa/LSB（覆盖 ±65.53 Pa，量化误差 ≤1 LSB，无饱和）',
        'caliber': '表压 Pa（出口 0 参考）· 仿真估计 · 非临床测量',
        'walls_src': {
            'n_points': int(len(p_pa)),
            'p_field_min_m2s2': round(float(p_kin.min()), 6),
            'p_field_max_m2s2': round(float(p_kin.max()), 6),
            'p_min_Pa': round(float(p_pa.min()), 4),
            'p_max_Pa': round(float(p_pa.max()), 4),
            'p99_Pa': round(float(np.percentile(p_pa, 99)), 4),
            'p_mean_Pa': round(float(p_pa.mean()), 4),
            'U_note': 'walls.vtp 的 U point_data 全零（无滑移壁面）——本指标只用 p，禁用壁面 U',
        },
        'color_scale': {
            'lo_Pa': round(lo, 4),
            'hi_Pa': round(p99, 4),
            'zero_Pa': 0.0,
            'basis': '固定分位色标（写死）：上限=p99(显示集顶点并集)，下限=min 与 0 的中点；0=出口参考点',
        },
        'nn_max_dist_mm': nn_max,
        'calib_inlet': inlet_calib(),
        'surfaces': surfaces,
    }

    header, obj = read_plus(OUT)
    had = 'wallP' in obj
    obj['wallP'] = result
    write_plus(OUT, header, obj)
    if os.path.abspath(MIRROR) != os.path.abspath(OUT):
        shutil.copyfile(OUT, MIRROR)

    # 回读校验（JSON 可解析 + 量化往返 + p99 一致）
    _, chk = read_plus(OUT)
    wpk = chk['wallP']
    for s in wpk['surfaces']:
        v = np.frombuffer(base64.b64decode(s['values_b64']), dtype='<i2').astype(np.float64) * Q_P
        assert len(v) == s['n'], '顶点数不符: %s' % s['mesh']
        p99r = float(np.percentile(v, 99))
        assert abs(p99r - s['p99_Pa']) <= Q_P * 1.5, 'p99 回读不符: %s' % s['mesh']
    print('[wallP] 回读校验 OK（wallP 键%s）' % ('已更新' if had else '新增'))
    print('[wallP] wallP.color_scale = [%.4f, %.4f] Pa（0=%.1f）' % (wpk['color_scale']['lo_Pa'], wpk['color_scale']['hi_Pa'], wpk['color_scale']['zero_Pa']))
    print('[wallP] wallP.p99_Pa(显示集并集上限) = %.4f Pa' % wpk['color_scale']['hi_Pa'])
    print('[wallP] OK -> %s (%.2f MB)' % (OUT, os.path.getsize(OUT) / 1048576.0))
    return 0


if __name__ == '__main__':
    sys.exit(main())
