# -*- coding: utf-8 -*-
"""
extract_compare.py —— T18-M4 多病例对比数据 → viewer_plus_data.js 的 compare 键

口径红线（T18 任务书 · 2026-10-16）
  · 新卡片一律以「本算例 ΔP/Q 直算」为锚：
        锚点 dP_baseline = 18.45 Pa @15 L/min = 0.25 L/s  →  R = 73.8 Pa/(L/s)
  · 禁用 legacy 字段 viewer_data.js meta.metrics.resistance_total = 66.2
    （口径疑点正被 K3 裁定，引用会引雷）——本脚本不读该字段、不写出该字段
  · 全部新数字带「层流线性外推 · 仿真估计 · 非临床测量」口径

口径实现（与页面既有卡片同法，防页内自相矛盾）
  · 显示口径 ΔP 取两位：pA 18.45 Pa（源 18.445961）、pB 45.63 Pa（源 45.624982）
  · 模型常数 R = round(ΔP_显示 / 0.25 L/s, 1)：pA 73.8、pB 182.5 Pa/(L/s)
  · 扫描/交点全部由该模型常数算出 —— 保证「R 退化为常数」在表内逐点成立，
    且 Q=30/45 L/min 的 ΔP 与页面既有 ΔP–流量卡（36.9 / 55.35 Pa）逐字一致

侧向口径（2026-10-01 投影实测勘误 · 7 断言 PASS）
  · 后处理脚本的 inletL 块 = 患者右半气道；inletR 块 = 患者左半气道
  · 因此 flow_share_L_pct 读作「患者右份额」，flow_share_R_pct 读作「患者左份额」
  · 界面按患者自身左右显示（面对患者判读）

数据源（全部重读核实，逐项断言）
  pA ΔP    : 阶段2-CFD算例包/结果/P0-result-pA-v5/后处理/metrics.json            (totals.dP_Pa)
  pA 分流  : 阶段2-CFD算例包/结果/P0-result-pA-v5C/后处理/metrics.json           (Run-B 等压终态)
  pA 鼻瓣区: 阶段1-三维重建/metrics_v2.json
  pB ΔP    : 阶段2-CFD算例包/结果/P0-result-pB-v1/后处理/metrics.json            (totals.dP_Pa)
  pB 分流  : 阶段2-CFD算例包/结果/P0-result-pB-v1C/后处理/metrics.json           (Run-B 等压终态)
  pB 鼻瓣区: 升级施工-T14c/_regT14c/pB_v1_{base,facegrow,largest}/step1/metrics_pB_v2.json
             （三变体一致性断言；非正式环节①产物——参考值，标注口径）

输出：`compare` 键追加进 viewer_plus_data.js（既有六键原样保留；T17 工作副本 + 阶段5 根各写一份）
"""
import hashlib
import io
import json
import math
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

ROOT = r'F:\比赛项目\罕见无界黑客松\赛题3-鼻腔气流分析\项目\P0-鼻塞设计工具'
T17 = ROOT + r'\阶段5-交互查看器\升级施工-T17'
OUT_T17 = T17 + r'\viewer_plus_data.js'
OUT_ROOT = ROOT + r'\阶段5-交互查看器\viewer_plus_data.js'

PA_V5 = ROOT + r'\阶段2-CFD算例包\结果\P0-result-pA-v5\后处理\metrics.json'
PA_V5C = ROOT + r'\阶段2-CFD算例包\结果\P0-result-pA-v5C\后处理\metrics.json'
PA_VALVE = ROOT + r'\阶段1-三维重建\metrics_v2.json'
PB_V1 = ROOT + r'\阶段2-CFD算例包\结果\P0-result-pB-v1\后处理\metrics.json'
PB_V1C = ROOT + r'\阶段2-CFD算例包\结果\P0-result-pB-v1C\后处理\metrics.json'
PB_VALVE_DIR = ROOT + r'\阶段5-交互查看器\升级施工-T14c\_regT14c'

Q_ANCHOR_L_MIN = 15.0              # L/min，v5 定流量标定点
DP_ANCHOR_EXPECT = 18.45           # Pa，任务书锚点（实测 18.445960…）
DP_PB_EXPECT = 45.63               # Pa，患者B 参考点（实测 45.624982…）
SWEEP_Q = [7.5, 15.0, 30.0, 45.0]  # L/min，静息→用力呼吸四工况
THRESHOLD_PA = 75.0                # Pa，四相鼻测压法参考压
SIX_KEYS = ['clinical', 'meshQuality', 'planes', 'residual', 'wallWSS', 'zonal']

CHECK = []


def check(name, ok, detail=''):
    CHECK.append((name, bool(ok), detail))
    print(('PASS ' if ok else 'FAIL ') + name + (('  ' + detail) if detail else ''))
    return bool(ok)


def rh2(x):
    """半进位（half-up）两位圆整 —— 避开 Python 银行家进位，与页面显示口径一致。"""
    return math.floor(abs(float(x)) * 100.0 + 0.5 + 1e-9) / 100.0 * (1 if float(x) >= 0 else -1)


def rh1(x):
    return math.floor(abs(float(x)) * 10.0 + 0.5 + 1e-9) / 10.0 * (1 if float(x) >= 0 else -1)


def rd(path):
    if not os.path.isfile(path):
        raise IOError('数据源缺失: ' + path)
    return json.loads(io.open(path, 'r', encoding='utf-8').read())


def load_payload(path):
    s = io.open(path, 'r', encoding='utf-8').read()
    i = s.find('{')
    obj, _ = json.JSONDecoder().raw_decode(s[i:])
    return obj


def main():
    # ---------- pA：ΔP 与流量（Run-A 定流量口径 = 锚点来源） ----------
    pa = rd(PA_V5)['totals']
    pa_dp_raw = float(pa['dP_Pa'])
    pa_q = float(pa['Q_inlet_total_L_min'])
    check('pA dP 与任务书锚点 18.45 Pa 一致', abs(pa_dp_raw - DP_ANCHOR_EXPECT) < 0.01,
          '源文件实测 %.6f Pa' % pa_dp_raw)
    check('pA 定流量 15 L/min 一致', abs(pa_q - Q_ANCHOR_L_MIN) < 0.001,
          '源文件实测 %.6f L/min' % pa_q)
    pa_dp = DP_ANCHOR_EXPECT                                     # 显示/模型口径
    R_A = rh1(pa_dp / (Q_ANCHOR_L_MIN / 60.0))                   # 73.8
    check('pA 模型常数 R = 18.45 / 0.25 = 73.8 Pa/(L/s)（任务书口径）',
          abs(R_A - 73.8) < 0.001, '实测 %.1f（源值直算 %.4f）' % (R_A, pa_dp_raw / (pa_q / 60.0)))

    # ---------- pA：Run-B 自然分流（等压终态） ----------
    pac = rd(PA_V5C)['totals']
    pa_left = float(pac['flow_share_R_pct'])    # inletR 块 = 患者左
    pa_right = float(pac['flow_share_L_pct'])   # inletL 块 = 患者右
    check('pA 分流合计 100%', abs(pa_right + pa_left - 100.0) < 0.01,
          '右 %.4f / 左 %.4f' % (pa_right, pa_left))
    check('pA 分流与 viewer_data.js split 51.9/48.1 一致（右 51.9 / 左 48.1）',
          abs(round(pa_right, 1) - 51.9) < 0.05 and abs(round(pa_left, 1) - 48.1) < 0.05,
          '右 %.1f / 左 %.1f' % (pa_right, pa_left))

    # ---------- pA：鼻瓣区 ----------
    pav = rd(PA_VALVE)
    pa_valve = float(pav['min_axial_area_mm2'])
    check('pA 鼻瓣区最小截面积 244.2 mm2 @第273层（阶段1 官方产物）',
          abs(pa_valve - 244.2) < 0.05,
          '实测 %.1f mm2 第 %s 层 z=%s mm' % (pa_valve, pav['min_layer'], pav['min_z_mm']))

    # ---------- pB：ΔP 与流量（Run-A 定流量口径） ----------
    pb = rd(PB_V1)['totals']
    pb_dp_raw = float(pb['dP_Pa'])
    pb_q = float(pb['Q_inlet_total_L_min'])
    check('pB 定流量 15 L/min 一致', abs(pb_q - Q_ANCHOR_L_MIN) < 0.001,
          '源文件实测 %.6f L/min' % pb_q)
    # 显示口径：先取三位 45.625，再 half-up 两位 -> 45.63（与 T17 卡片/参考点既有口径一致）
    pb_dp = rh2(round(pb_dp_raw, 3))
    check('pB dP 显示口径 45.63 Pa（源 45.624982 -> 三位 45.625 -> 两位 45.63）',
          abs(pb_dp - DP_PB_EXPECT) < 0.001, '实测 %.2f' % pb_dp)
    R_B = rh1(pb_dp / (Q_ANCHOR_L_MIN / 60.0))                    # 182.5
    check('pB 模型常数 R = 45.63 / 0.25 -> 182.5 Pa/(L/s)（任务书口径）',
          abs(R_B - 182.5) < 0.001, '实测 %.1f（源值直算 %.4f）' % (R_B, pb_dp_raw / (pb_q / 60.0)))

    # ---------- pB：Run-B 自然分流（等压终态） ----------
    pbc = rd(PB_V1C)['totals']
    pb_left = float(pbc['flow_share_R_pct'])
    pb_right = float(pbc['flow_share_L_pct'])
    check('pB 分流合计 100%', abs(pb_right + pb_left - 100.0) < 0.01,
          '右 %.4f / 左 %.4f' % (pb_right, pb_left))
    check('pB 右/左 ~ 3.5x（任务书口径；实测 3.43）',
          3.3 < (pb_right / pb_left) < 3.6, '实测 %.3fx' % (pb_right / pb_left))

    # ---------- pB：鼻瓣区（T14c 复现回归三变体一致） ----------
    pb_valve = pb_valve_layer = pb_valve_z = None
    pb_valve_src = '未产出'
    variants = ['pB_v1_base', 'pB_v1_facegrow', 'pB_v1_largest']
    vals = []
    for v in variants:
        p = os.path.join(PB_VALVE_DIR, v, 'step1', 'metrics_pB_v2.json')
        if os.path.isfile(p):
            m = rd(p)
            vals.append((float(m['min_axial_area_mm2']), int(m['min_layer']), float(m['min_z_mm'])))
    if vals:
        same = all(abs(x[0] - vals[0][0]) < 1e-9 for x in vals)
        check('pB 鼻瓣区 %d 个复现变体数值一致' % len(vals), same, str(vals))
        pb_valve, pb_valve_layer, pb_valve_z = vals[0]
        pb_valve_src = ('升级施工-T14c\\_regT14c\\pB_v1_{base,facegrow,largest}\\step1\\metrics_pB_v2.json'
                        '（%d 变体一致） · 非正式环节① 产物（0.468mm soft-tissue），仅作对比参考' % len(vals))
    else:
        check('pB 鼻瓣区数据（允许缺失）', True, '未产出 -> 置 null')

    # ---------- 派生量 ----------
    def si(right, left):
        return 2.0 * abs(right - left) / (right + left) * 100.0

    pa_si = si(pa_right, pa_left)
    pb_si = si(pb_right, pb_left)
    check('pA 对称性指数 SI = 2|L-R|/(L+R)x100% ≈ 7.5%（源值直推 7.467%）',
          7.4 < pa_si < 7.6, '实测 %.4f%%' % pa_si)
    check('pB 对称性指数 SI（近单侧闭塞，>100% 数学合理）', pb_si > 90.0, '实测 %.4f%%' % pb_si)

    sweep_dp_a = [rh2(R_A * (q / 60.0)) for q in SWEEP_Q]
    sweep_r_a = [rh2(d / (q / 60.0)) for d, q in zip(sweep_dp_a, SWEEP_Q)]
    check('pA 扫描表 R 逐点恒为 73.8（层流线性假设下 R 退化为常数；两位显示口径回推 R∈[73.76,73.84]）',
          all(abs(x - 73.8) < 0.05 for x in sweep_r_a)
          and all(abs(round(x, 1) - 73.8) < 1e-9 for x in sweep_r_a), str(sweep_r_a))
    check('pA 扫描表锚点工况点 15 L/min = 18.45 Pa',
          abs(sweep_dp_a[1] - 18.45) < 0.001, '扫描表 = ' + str(sweep_dp_a))
    check('pA 扫描表 30/45 L/min 与页面既有 ΔP-流量卡（36.9 / 55.35）逐字一致',
          abs(sweep_dp_a[2] - 36.9) < 0.001 and abs(sweep_dp_a[3] - 55.35) < 0.001,
          '30 -> %.2f / 45 -> %.2f' % (sweep_dp_a[2], sweep_dp_a[3]))
    check('pA 扫描 7.5 L/min = 9.23 Pa（任务书所列 13.84 对应 R=110.8，与本锚点不自洽，已按锚点重算）',
          abs(sweep_dp_a[0] - 9.23) < 0.001, '实测 %.2f' % sweep_dp_a[0])

    q75_a = rh1(THRESHOLD_PA / R_A * 60.0)
    q75_b = rh1(THRESHOLD_PA / R_B * 60.0)
    check('pA 75 Pa 阈值交点 Q = 61.0 L/min（任务书 40.7 对应 R=110.8，同上不自洽）',
          abs(q75_a - 61.0) < 0.05, '实测 %.1f L/min' % q75_a)
    check('pB 75 Pa 阈值交点 Q = 24.7 L/min', abs(q75_b - 24.7) < 0.05,
          '实测 %.1f L/min' % q75_b)

    sweep_dp_b = [rh2(R_B * (q / 60.0)) for q in SWEEP_Q]
    check('pB 扫描 15 L/min = 45.63 Pa（与参考点逐字一致）',
          abs(sweep_dp_b[1] - 45.63) < 0.001, str(sweep_dp_b))

    # ---------- 组装 compare ----------
    compare = {
        'method': ('多病例对比：全部数值由各自后处理 metrics.json 直算 R=ΔP/Q（层流线性口径）；'
                   '不引用 legacy resistance_total'),
        'side_convention': ('分侧按患者自身左右显示：后处理 inletL 块=患者右、inletR 块=患者左'
                            '（2026-10-01 投影实测勘误）'),
        'anchor': {
            'Q_L_min': Q_ANCHOR_L_MIN,
            'dP_Pa': pa_dp,
            'dP_raw_Pa': round(pa_dp_raw, 6),
            'R_Pa_per_Lps': R_A,
            'q_at_75Pa_L_min': q75_a,
            'sweep_q_L_min': SWEEP_Q,
            'sweep_dP_Pa': sweep_dp_a,
            'threshold_Pa': THRESHOLD_PA,
            'note': ('层流线性外推 · 锚点=本算例 v5 实测 18.45 Pa @15 L/min · '
                     '不确定度±20-50% · 非临床测量'),
        },
        'cases': [
            {
                'id': 'pA',
                'label': '患者A（主算例）',
                'dP_Pa': pa_dp,
                'dP_raw_Pa': round(pa_dp_raw, 6),
                'Q_L_min': Q_ANCHOR_L_MIN,
                'R_Pa_per_Lps': R_A,
                'split_right_pct': round(pa_right, 4),
                'split_left_pct': round(pa_left, 4),
                'side_ratio': rh2(max(pa_right, pa_left) / min(pa_right, pa_left)),
                'symmetry_index_pct': rh2(pa_si),
                'sweep_dP_Pa': sweep_dp_a,
                'q_at_75Pa_L_min': q75_a,
                'valve_min_area_mm2': pa_valve,
                'valve_min_layer': pav['min_layer'],
                'valve_min_z_mm': pav['min_z_mm'],
                'valve_source': '阶段1-三维重建/metrics_v2.json（环节① 0.35mm 各向同性，官方产物）',
                'source': ('P0-result-pA-v5/后处理/metrics.json（ΔP）+ '
                           'P0-result-pA-v5C/后处理/metrics.json（Run-B 自然分流）+ '
                           '阶段1-三维重建/metrics_v2.json（鼻瓣区）'),
            },
            {
                'id': 'pB',
                'label': '患者B（内部对照例 n=1）',
                'dP_Pa': pb_dp,
                'dP_raw_Pa': round(pb_dp_raw, 6),
                'Q_L_min': Q_ANCHOR_L_MIN,
                'R_Pa_per_Lps': R_B,
                'split_right_pct': round(pb_right, 4),
                'split_left_pct': round(pb_left, 4),
                'side_ratio': rh2(max(pb_right, pb_left) / min(pb_right, pb_left)),
                'symmetry_index_pct': rh2(pb_si),
                'sweep_dP_Pa': sweep_dp_b,
                'q_at_75Pa_L_min': q75_b,
                'valve_min_area_mm2': (rh2(pb_valve) if pb_valve is not None else None),
                'valve_min_layer': pb_valve_layer,
                'valve_min_z_mm': pb_valve_z,
                'valve_source': pb_valve_src,
                'source': ('P0-result-pB-v1/后处理/metrics.json（ΔP）+ '
                           'P0-result-pB-v1C/后处理/metrics.json（Run-B 自然分流）'),
            },
        ],
        'reference': {
            'label': '参考点：患者B 45.63 Pa @15 L/min（n=1 内部对照例 · 非人群参考区间）',
            'dP_Pa': pb_dp,
            'Q_L_min': Q_ANCHOR_L_MIN,
        },
        'disclaimer': ('仿真估计 · 非临床测量 · 层流线性外推 · 不确定度±20-50% · '
                       '概念验证（非医疗器械）'),
    }

    # ---------- 组装 data 对象（保留既有六键） ----------
    old = load_payload(OUT_T17)
    keys_before = sorted(k for k in old if k != 'compare')
    print('[compare] 既有键（写入前，compare 除外）: ' + str(keys_before))
    check('写入前 data 六键齐', keys_before == SIX_KEYS, str(keys_before))
    old['compare'] = compare
    body = json.dumps(old, ensure_ascii=False, separators=(',', ':'))

    # 单文件内联护栏（同打包脚本口径）
    check('compare 不含 </script 注入风险', '</script' not in body.lower())
    check('compare 不含 <!-- 注入风险', '<!--' not in body)
    check('compare 不含 legacy 字段名 resistance_total', '"resistance_total"' not in body)

    print()
    nf = len([1 for _, ok, _ in CHECK if not ok])
    if nf:
        print('[compare] 前置断言失败 %d 项 —— 不写盘，请先核查数据源' % nf)
        return 1

    head = ('// viewer_plus_data.js —— T17 SimScale后处理集成数据包（生成脚本：升级施工-T17/extract_*.py）\n'
            '// T18-M4：compare 键由 extract_compare.py 追加（多病例对比 · ΔP/Q 直算 · 禁用 legacy resistance_total）\n'
            '// 坐标系：mm，已减 airwayMesh 质心 CENTER=[79.22,71.87,56.98]（与 viewer_data.js 同帧）\n'
            '// 说明：概念验证 · 非医疗器械 · 仿真估计 · 非临床测量\n')
    txt = head + 'window.VIEWER_PLUS_DATA = ' + body + ';\n'

    for p in (OUT_T17, OUT_ROOT):
        with io.open(p, 'w', encoding='utf-8', newline='\n') as f:
            f.write(txt)
        print('[compare] 写出 %s (%.2f MB)' % (p, os.path.getsize(p) / 1048576.0))

    def md5(p):
        return hashlib.md5(io.open(p, 'rb').read()).hexdigest().upper()

    m17, mroot = md5(OUT_T17), md5(OUT_ROOT)
    check('两份 viewer_plus_data.js 字节一致（md5）', m17 == mroot, m17)

    # ---------- 回读断言 ----------
    back = load_payload(OUT_T17)
    keys_after = sorted(back.keys())
    check('回读七键齐（六键 + compare）', keys_after == sorted(SIX_KEYS + ['compare']), str(keys_after))
    check('回读 compare 两病例齐', [c['id'] for c in back['compare']['cases']] == ['pA', 'pB'])
    check('回读 pA R / ΔP 与锚定公式一致',
          abs(back['compare']['cases'][0]['R_Pa_per_Lps'] - 73.8) < 0.001
          and abs(back['compare']['cases'][0]['dP_Pa'] - 18.45) < 0.001)
    check('回读 pB ΔP 与源文件对拍一致',
          abs(back['compare']['cases'][1]['dP_raw_Pa'] - pb_dp_raw) < 1e-6,
          '%.6f' % back['compare']['cases'][1]['dP_raw_Pa'])
    check('回读四工况扫描与 R*Q 公式一致（R 恒定，两位显示口径）',
          all(abs(x - 73.8) < 0.05 and abs(round(x, 1) - 73.8) < 1e-9
              for x in [back['compare']['anchor']['sweep_dP_Pa'][i] / (SWEEP_Q[i] / 60.0)
                        for i in range(4)]),
          str(back['compare']['anchor']['sweep_dP_Pa']))

    print()
    n = len(CHECK)
    nf = len([1 for _, ok, _ in CHECK if not ok])
    print('[compare] 断言 %d 项，失败 %d 项' % (n, nf))
    print('[compare] md5(viewer_plus_data.js) = %s' % m17)
    return 1 if nf else 0


if __name__ == '__main__':
    sys.exit(main())
