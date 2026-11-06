# -*- coding: utf-8 -*-
"""
T17-B extract_clinical.py —— 临床口径指标数据 → viewer_plus_data.js
（四相鼻测压法 R@75/150Pa + ΔP-流量曲线 + 鼻瓣区面积曲线 · 数据管道第 5 脚本）

数据锚点：
  R_base = 66.2 Pa/(L/s)（viewer_data.js meta.metrics.resistance_total，v5C 等压法口径）
  层流线性外推：层流下 R 恒定 → R@75Pa = R@150Pa = 66.2 Pa/(L/s)（75/150Pa 工况对应流量
  68/136 L/min，已超层流适用域，前端必须标注）
  ΔP-流量三点：15/30/45 L/min → 18.45/36.9/55.4 Pa（线性，18.45 为内部演示值·v5 定流量标定点）
  参考带：绿 ≤50 / 黄 50-80 / 红 >80 Pa —— 内部工程/演示阈值（非文献参考带）；
  患者B 45.63 Pa @15 L/min 为内部演示对照例，正式文献参考带赛后引入（T12 定稿后 T11 对账）
  鼻瓣区：metrics_v2.json（244.2 mm² @273 层）+ area_per_slice_v2.csv 逐层面积曲线
"""
import base64
import csv
import io
import json
import os
import sys

import numpy as np

sys.stdout.reconfigure(encoding='utf-8')

# 两档最小轴面积只用一套实现（GAP-2）：直接导入 extract_compare 的共用函数与固定标签
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract_compare import (  # noqa: E402
    MIN_ANATOMIC_NOTE,
    MIN_NO_THRESHOLD_LABEL,
    MIN_RAW_LABEL,
    axial_area_minima,
)

ROOT = r'F:\比赛项目\罕见无界黑客松\赛题3-鼻腔气流分析\项目\P0-鼻塞设计工具'
CSV = ROOT + r'\阶段1-三维重建\area_per_slice_v2.csv'
MJ = ROOT + r'\阶段1-三维重建\metrics_v2.json'
OUT = ROOT + r'\阶段5-交互查看器\升级施工-T17\viewer_plus_data.js'

R_BASE = 66.2          # Pa/(L/s)，viewer_data.js meta.metrics.resistance_total
Q_CAL = 15.0           # v5 标定点 L/min
DP_CAL = 18.45         # 内部演示值：v5 dP_baseline_Pa（非归档真值）

# ===== 单一演示带口径（T10-a / DF1 / F5；三文件同口径，正式文献参考带赛后引入）=====
# 与 v6_curve_fit.py / v6_curve_fig.py 完全同一份：50/80 与 30 Pa 一律为
# 「内部工程/演示阈值（非文献参考带）」；pA 基线 18.45 Pa 与 v6 曲线同为 @15 L/min 演示工况。
# 所有 pA/ΔP/V 数值均为内部演示值（合成演示数据），非归档真值；T12 定稿后由 T11 对账。
DEMO_BAND = {
    "green_max_Pa": 50.0,
    "yellow_max_Pa": 80.0,
    "demo_lower_ref_Pa": 30.0,
    "caliber": "内部工程/演示阈值（非文献参考带）",
    "flow_caliber": "@15 L/min（pA 基线演示值 18.45 Pa 与 v6 曲线同工况）",
    "demo": True,
    "source": "内部演示阈值；正式文献参考带赛后引入；T12 定稿后 T11 对账",
}
TIER_BELOW = "低于内部演示参考线（30 Pa）——内部演示值，非临床判读"
TIER_GREEN = "内部演示阈值·绿档（非文献参考带）"
TIER_YELLOW = "内部演示阈值·黄档（非文献参考带）"
TIER_RED = "内部演示阈值·红档（非文献参考带）"


def classify_demo_band(dp_pa):
    """按统一演示带口径给出档位结论（同一 pA 演示值在任何口径源结论一致）。"""
    if dp_pa is None:
        return "无 ΔP 数值（内部演示值缺失）"
    if dp_pa < DEMO_BAND["demo_lower_ref_Pa"]:
        return TIER_BELOW
    if dp_pa <= DEMO_BAND["green_max_Pa"]:
        return TIER_GREEN
    if dp_pa <= DEMO_BAND["yellow_max_Pa"]:
        return TIER_YELLOW
    return TIER_RED


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
           '// 说明：科研与康复参考 · 非医疗器械 · 仿真估计 · 非临床测量\n'
           'window.VIEWER_PLUS_DATA = ' + body + ';\n')
    with io.open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(txt)


def main():
    # --- 鼻阻力（临床口径） ---
    # 层流外推：ΔP = R·Q（Q 单位 L/s）。R@75Pa 口径 = 75Pa 驱动压下的阻力 = 75 / (75/R_base) = R_base
    q75 = 75.0 / R_BASE        # L/s
    q150 = 150.0 / R_BASE      # L/s
    resistance = {
        'R_base_Pa_per_Lps': R_BASE,
        'R_at_75Pa_Pa_per_Lps': round(R_BASE, 1),
        'R_at_150Pa_Pa_per_Lps': round(R_BASE, 1),
        'q_at_75Pa_L_min': round(q75 * 60, 1),
        'q_at_150Pa_L_min': round(q150 * 60, 1),
        'method': '四相鼻测压法临床口径（ΔP/Q）· 层流外推（R 恒定线性换算）',
        'calib': '标定点 v5 定流量 15 L/min → ΔP 18.45 Pa（R=73.8 Pa/(L/s) 定流量口径）；'
                 'R 66.2 Pa/(L/s) 系 v5C 等压法口径——两口径不可互换，与主指标面板一致',
        'out_of_range_note': '75/150 Pa 工况对应流量 %.0f/%.0f L/min，已超层流适用域——数值仅作临床口径演示，非实测' % (q75 * 60, q150 * 60),
    }
    print('[clinical] R@75Pa=%.1f Pa/(L/s)（Q=%.1f L/min）' % (R_BASE, q75 * 60))

    # --- ΔP-流量曲线 + 单一演示参考带（DF1/F5）---
    qs = [15.0, 30.0, 45.0]
    r_flow = DP_CAL / (Q_CAL / 60.0)   # 73.8 Pa/(L/s)（定流量口径线性外推，演示值）
    dps = [round(r_flow * (q / 60.0), 2) for q in qs]
    dpc = {
        'Q_L_min': qs,
        'dP_Pa': dps,
        'method': '层流线性外推（ΔP∝Q，v5 定流量标定点 15 L/min；内部演示值）',
        # DF1/F5：与 v6_curve_fit.py / v6_curve_fig.py 同一演示带口径（非文献参考带）
        'ref_band': {
            'green_max_Pa': DEMO_BAND['green_max_Pa'],
            'yellow_max_Pa': DEMO_BAND['yellow_max_Pa'],
            'demo_lower_ref_Pa': DEMO_BAND['demo_lower_ref_Pa'],
            'green_label': TIER_GREEN, 'yellow_label': TIER_YELLOW, 'red_label': TIER_RED,
            'caliber': DEMO_BAND['caliber'],
            'flow_caliber': DEMO_BAND['flow_caliber'],
            'demo': DEMO_BAND['demo'],
            'source': DEMO_BAND['source'],
            # 显式双标（工况不对齐，如实披露）：旧「以 30 L/min 工况为准」口径已废
            'ref_Q_note': ('显式双标（工况不对齐，如实披露）：pA 基线演示值 18.45 Pa @15 L/min '
                           '与 v6 曲线同工况；临床卡 ΔP-流量曲线跨 15/30/45 L/min，演示阈值未做跨工况归一化；'
                           '旧「以 30 L/min 工况为准」口径已废，不声称任何人群或文献参考带'),
            'classify_note': ('同一 pA 演示值 18.45 在临床卡与 v6 图由 classify_demo_band 得同一档位：'
                              + classify_demo_band(DP_CAL)),
        },
    }
    print('[clinical] ΔP-流量：Q=%s → ΔP=%s Pa（R_flow=%.1f）' % (qs, dps, r_flow))
    print('[clinical] 统一演示带口径：pA 基线演示值 18.45 → %s' % classify_demo_band(DP_CAL))

    # --- 鼻瓣区（面积曲线） ---
    mj = json.loads(io.open(MJ, 'r', encoding='utf-8').read())
    rows = []
    with io.open(CSV, 'r', encoding='utf-8-sig') as f:
        rd = csv.reader(f)
        header = next(rd)
        for row in rd:
            if not row or not row[0].strip():
                continue
            rows.append([float(x) for x in row[:5]])
    arr = np.asarray(rows, dtype=np.float64)
    slice_no = arr[:, 0]
    z_mm = arr[:, 1]
    total = arr[:, 2]
    left = arr[:, 3]
    right = arr[:, 4]
    has_air = total > 0
    print('[clinical] CSV %d 行（有面积 %d 层），total max %.1f mm²' %
          (len(arr), int(has_air.sum()), total.max()))
    assert int(has_air.sum()) == int(mj['n_slices_with_air']), \
        'CSV 有面积层数(%d)与 metrics_v2.json n_slices_with_air(%d)不一致' % (int(has_air.sum()), int(mj['n_slices_with_air']))

    # --- 两档最小轴面积（与 extract_compare.py 共用 axial_area_minima，禁止写两份） ---
    area_min = axial_area_minima(CSV)
    mr = area_min['min_raw']
    mnt = area_min['min_no_threshold']
    print('[clinical] min_raw           %.6f mm² @层%d z=%.2f mm（%s）'
          % (mr['mm2'], mr['layer'], mr['z_mm'], MIN_RAW_LABEL))
    print('[clinical] min_no_threshold  %.6f mm² @层%d z=%.2f mm（%s）'
          % (mnt['mm2'], mnt['layer'], mnt['z_mm'], MIN_NO_THRESHOLD_LABEL))
    print('[clinical] min_anatomic      null —— %s' % MIN_ANATOMIC_NOTE)
    assert abs(mr['mm2'] - float(mj['min_axial_area_mm2'])) < 0.05, \
        '实算 min_raw %.6f 与 metrics_v2.json min_axial_area_mm2 %.1f 不一致' % (
            mr['mm2'], float(mj['min_axial_area_mm2']))

    valve = {
        'min_area_mm2': mj['min_axial_area_mm2'],
        'min_layer': mj['min_layer'],
        'min_z_mm': mj['min_z_mm'],
        # 旧字段 min_area_mm2 就是 min_raw，禁止被读成解剖值
        'min_area_mm2_caliber': 'min_raw（' + MIN_RAW_LABEL + '）',
        # 两档口径分开写，标签固定；min_raw 不得冒充解剖值
        'min_raw_mm2': mr['mm2_6dp'],
        'min_raw_layer': mr['layer'],
        'min_raw_z_mm': mr['z_mm'],
        'min_raw_label': MIN_RAW_LABEL,
        'min_no_threshold_mm2': mnt['mm2_6dp'],
        'min_no_threshold_layer': mnt['layer'],
        'min_no_threshold_z_mm': mnt['z_mm'],
        'min_no_threshold_label': MIN_NO_THRESHOLD_LABEL,
        'min_anatomic_mm2': None,
        'min_anatomic_note': MIN_ANATOMIC_NOTE,
        'min_area_source': area_min['source'],
        'min_area_threshold_rule': area_min['threshold_rule'],
        'source': '阶段1-三维重建/area_per_slice_v2.csv + metrics_v2.json',
        'caveat': mj['caveat'],
        'curve': {
            'n': int(len(arr)),
            'quant': {'slice_scale': 1.0, 'z_scale_mm': 0.1, 'area_scale_mm2': 0.1,
                      'dtype': 'int16', 'enc': 'base64'},
            'slice_b64': b64_i16(slice_no, 1.0),
            'z_mm_b64': b64_i16(z_mm, 0.1),
            'total_mm2_b64': b64_i16(total, 0.1),
            'left_mm2_b64': b64_i16(left, 0.1),
            'right_mm2_b64': b64_i16(right, 0.1),
            'total_max_mm2': round(float(total.max()), 1),
            'n_slices_with_air': int(has_air.sum()),
        },
    }

    result = {
        'resistance': resistance,
        'dP_flow': dpc,
        'valve': valve,
        'disclaimer': '仿真估计 · 非临床测量 · 科研与康复参考（非医疗器械）',
    }
    obj = read_json_blob(OUT)
    if obj is None:
        obj = {}
        print('[clinical] creating new viewer_plus_data.js')
    obj['clinical'] = result
    write_json_blob(OUT, obj)
    print('[clinical] OK -> %s (%.2f MB)' % (OUT, os.path.getsize(OUT) / 1048576.0))
    return 0


if __name__ == '__main__':
    sys.exit(main())
