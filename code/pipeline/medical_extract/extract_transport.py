# -*- coding: utf-8 -*-
"""
T20-F3 extract_transport.py —— 冻结 viewer_data.js 的 streamlines 逐点弧长积分 Σ Δs/|U|
                              → viewer_plus_data.js `transportTime` 键
（Tecplot 360「粒子传输/驻留时间着色」逆向集成 · T20 吸收批 A4）

输入 : 阶段5-交互查看器/viewer_data.js（只读：streamlines[].points（mm，3n）+ streamlines[].speed（m/s，n））
输出 : 阶段5-交互查看器/viewer_plus_data.js 的 `transportTime` 键（读-改-写，幂等；只追加不重写其余字节）

物理口径（吸收方案 v2 §2 / K3 审计一致）：
  t = Σ Δs / |U| ——**运动学估计**（稳态流线沿程传输时间），**非**生理滞留量：
  不含扩散、沉积、黏液纤毛输运。逐点速度标量 speed 随数据冻结（15 L/min 标定工况）。
  段速取两端点速度均值；|U| < ε=1e-3 m/s 的段按 ε 计（防除零），clamp 端点数逐线如实披露。
  卡片名固定为「稳态流线传输时间（运动学估计）」（禁「生理滞留时间」）。
量化：int16 × **0.002 s**（覆盖 ±65.53 s）。
  「0.002 而非任务书 0.001」的实测理由（如实标注，非任意放宽）：63 条流线中 1 条为鼻窦死腔线
  （251 点中 78 点 |U|≡0），ε=1e-3 下其 t≈55.5 s，**超过 int16×0.001 s 的上限 32.767 s 会溢出**；
  0.002 s/LSB 后全部放得下（同时把显示集 p99 色标剩余量保持在 200 LSB 级）。数值侧另有全精度 total_s 字段。
色标：**固定分位**——上限 = 全体逐点时间的 p99（写死进数据），下限 = 0 s（写死）。
"""
import base64
import io
import json
import os
import shutil
import sys

import numpy as np

sys.stdout.reconfigure(encoding='utf-8')

ROOT = r'F:\比赛项目\罕见无界黑客松\赛题3-鼻腔气流分析\项目\P0-鼻塞设计工具'
VDATA = ROOT + r'\阶段5-交互查看器\viewer_data.js'
OUT = ROOT + r'\阶段5-交互查看器\viewer_plus_data.js'
MIRROR = ROOT + r'\阶段5-交互查看器\升级施工-T17\viewer_plus_data.js'

Q_T = 0.002          # s / LSB（见文件头「0.002 而非 0.001」说明）
EPS_U = 1e-3         # m/s


def b64_i16(arr_f, scale):
    q = np.round(np.asarray(arr_f, dtype=np.float64) / scale).astype(np.int16)
    err = abs(q.astype(np.float64) * scale - np.asarray(arr_f, dtype=np.float64)).max()
    assert err <= scale, '量化误差超 1 LSB（err=%.6g）' % err
    return base64.b64encode(q.tobytes()).decode('ascii')


def read_plus(path):
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
    body = json.dumps(obj, ensure_ascii=False, separators=(',', ':'))
    txt = header + 'window.VIEWER_PLUS_DATA = ' + body + ';\n'
    with io.open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(txt)


def load_streamlines():
    s = io.open(VDATA, 'r', encoding='utf-8').read()
    i = s.find('"streamlines"')
    if i < 0:
        raise RuntimeError('viewer_data.js 无 streamlines')
    j = s.find('[', i)
    depth, k, instr, esc = 0, j, False, False
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
            elif c in '[{':
                depth += 1
            elif c in ']}':
                depth -= 1
                if depth == 0:
                    break
        k += 1
    return json.loads(s[j:k + 1])


def main():
    sls = load_streamlines()
    print('[transport] streamlines n=%d' % len(sls))
    lines = []
    allt = []
    clamp_total = 0
    below_total = 0
    degenerate = []
    for li, sl in enumerate(sls):
        pts = np.asarray(sl['points'], dtype=np.float64).reshape(-1, 3)   # mm
        sp = np.asarray(sl['speed'], dtype=np.float64).ravel()            # m/s
        n = len(pts)
        assert len(sp) == n, 'line %d: speed 长度 %d != 点数 %d' % (li, len(sp), n)
        ds = np.sqrt(((pts[1:] - pts[:-1]) ** 2).sum(axis=1)) / 1000.0    # mm -> m，段弧长
        useg = 0.5 * (sp[1:] + sp[:-1])
        clamped = int((useg < EPS_U).sum())
        below = int((sp < EPS_U).sum())
        dt = ds / np.maximum(useg, EPS_U)
        t = np.concatenate(([0.0], np.cumsum(dt)))
        clamp_total += clamped
        below_total += below
        if below:
            degenerate.append({'line': li, 'stationary_points': below, 'n': int(n),
                               'total_s': round(float(t[-1]), 5)})
        lines.append({
            'n': int(n),
            't_b64': b64_i16(t, Q_T),
            'total_s': round(float(t[-1]), 6),
            'path_mm': round(float(ds.sum() * 1000.0), 3),
            'clamp_points': clamped,
            'speed_below_eps_points': below,
        })
        allt.append(t)
        if li < 20 or below or t[-1] > 0.5:
            print('[transport] line %2d n=%3d L=%7.2f mm  t_total=%.4f s  clamp=%d  |U|<eps=%d' %
                  (li, n, ds.sum() * 1000.0, t[-1], clamped, below))

    a = np.concatenate(allt)
    tot = np.array([l['total_s'] for l in lines])
    hi = float(np.percentile(a, 99))
    result = {
        'method': '冻结 viewer_data.js streamlines 逐点弧长积分：段速=两端点速度均值，t = Σ Δs/|U|'
                  '（Δs 由相邻点位移得，m；speed 为逐点速度标量，m/s，随数据冻结于 15 L/min 标定工况）',
        'quant': {
            't_scale_s': Q_T, 'dtype': 'int16', 'enc': 'base64',
            'note': '任务书指定 0.001 s/LSB；实测 1 条死腔流线 t≈55.5 s > int16×0.001 s 上限 32.767 s（溢出）'
                    ' → 取 0.002 s/LSB（覆盖 ±65.53 s），全 63 条无饱和；数值侧另有全精度 total_s',
        },
        'caliber': '稳态流线传输时间（运动学估计）· 仿真估计 · 非临床测量',
        'clamp_eps_ms': EPS_U,
        'clamp_points': clamp_total,
        'speed_below_eps_points': below_total,
        'degenerate_lines': degenerate,
        'color_scale': {
            'lo_s': 0.0,
            'hi_s': round(hi, 5),
            'basis': '固定分位色标（写死）：上限=全体逐点时间 p99，下限=0 s',
        },
        'summary': {
            'n_lines': len(lines),
            'total_s_min': round(float(tot.min()), 5),
            'total_s_p50': round(float(np.percentile(tot, 50)), 5),
            'total_s_p90': round(float(np.percentile(tot, 90)), 5),
            'total_s_max': round(float(tot.max()), 5),
            'total_s_mean': round(float(tot.mean()), 5),
            'n_outlier_gt_1s': int((tot > 1.0).sum()),
            'p99_per_point_s': round(hi, 5),
        },
        'note': '运动学估计（ΣΔs/|U|），非生理滞留量：不含扩散/沉积/黏液纤毛输运；'
                '|U| 低于 ε=1e-3 m/s 的段按 ε 计（低速/死腔端点），clamp 端点数逐线披露；'
                '死腔线（sn 窦内 |U|≡0）总时长 55 s 量级为数学后果，非生理时间',
        'lines': lines,
    }

    header, obj = read_plus(OUT)
    had = 'transportTime' in obj
    obj['transportTime'] = result
    write_plus(OUT, header, obj)
    if os.path.abspath(MIRROR) != os.path.abspath(OUT):
        shutil.copyfile(OUT, MIRROR)

    _, chk = read_plus(OUT)
    tk = chk['transportTime']
    for i, L in enumerate(tk['lines']):
        v = np.frombuffer(base64.b64decode(L['t_b64']), dtype='<i2').astype(np.float64) * Q_T
        assert len(v) == L['n'], '行 %d 时标数不符' % i
        assert abs(v[-1] - L['total_s']) <= Q_T * 1.5, '行 %d 总时长回读不符' % i
        assert v[0] == 0.0 and np.all(np.diff(v) >= 0), '行 %d 时间序列非单调' % i
    print('[transport] 回读校验 OK（transportTime 键%s）' % ('已更新' if had else '新增'))
    print('[transport] 总时长 min/p50/p90/max = %.4f / %.4f / %.4f / %.4f s；色标上限 p99=%.4f s' %
          (tk['summary']['total_s_min'], tk['summary']['total_s_p50'], tk['summary']['total_s_p90'],
           tk['summary']['total_s_max'], tk['color_scale']['hi_s']))
    print('[transport] clamp 段数合计=%d（|U|<eps 点数合计=%d），死腔线 %d 条' %
          (tk['clamp_points'], tk['speed_below_eps_points'], len(tk['degenerate_lines'])))
    print('[transport] OK -> %s (%.2f MB)' % (OUT, os.path.getsize(OUT) / 1048576.0))
    return 0


if __name__ == '__main__':
    sys.exit(main())
