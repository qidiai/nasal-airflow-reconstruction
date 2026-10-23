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

2026-10-23 增补（GAP 裁定，三处口径必须分开命名，禁止跨口径互证）
  · 两档最小轴面积：min_raw ≡ 现役字段 min_axial_area_mm2（门限 areas >= 0.1*max(areas) 内），
    min_no_threshold = 去掉门限后全部 total_mm2>0 层的最小；min_anatomic 本阶段不产出（挂 T7）。
    实现见 axial_area_minima()，extract_clinical.py 共用同一函数，禁止写两份。
  · 三档 split：split_imposed_RunA（边界条件复述，非患者真实分流）/
    split_natural_RunB（Run-B 等压终态，求解结果）/ split_synthetic_demo（合成演示）。
  · 三态断言：PASS / SKIP（资产缺失）/ FAIL。有 FAIL → 退出码 1；无 FAIL 有 SKIP → 退出码 0 且不写盘。
    资产缺失一律 SKIP（资产缺失），绝不静默通过、绝不伪造数值。
  · 默认 --dry-run（只打印目标与字节数，不落盘）；仓外在用件必须显式 --write 才写。

数据源（全部重读核实，逐项断言）
  pA ΔP    : 阶段2-CFD算例包/结果/P0-result-pA-v5/后处理/metrics.json            (totals.dP_Pa)
  pA 分流  : 阶段2-CFD算例包/结果/P0-result-pA-v5C/后处理/metrics.json           (Run-B 等压终态)
  pA 鼻瓣区: 阶段1-三维重建/metrics_v2.json（仓内副本 code/pipeline/out/step1/metrics_v2.json）
  pB ΔP    : 阶段2-CFD算例包/结果/P0-result-pB-v1/后处理/metrics.json            (totals.dP_Pa)
  pB 分流  : 阶段2-CFD算例包/结果/P0-result-pB-v1C/后处理/metrics.json           (Run-B 等压终态)
  pB 鼻瓣区: 升级施工-T14c/_regT14c/pB_v1_{base,facegrow,largest}/step1/metrics_pB_v2.json
             （三变体一致性断言；非正式环节①产物——参考值，标注口径）
  仓内输入（GAP-5）: code/pipeline/out/step1/area_per_slice_v2.csv（两档最小面积实算）、
             code/pipeline/out/postprocess/contract-pA-v1.json（Run-A 契约 39.0/61.0 的 1 位投影）、
             code/viewer/viewer_data.js:13（合成演示 50/50）

输出：`compare` 键追加进 viewer_plus_data.js（既有键原样保留——保留性断言：写入前键集 ⊆ 写入后键集；T17 工作副本 + 阶段5 根各写一份）
"""
import argparse
import csv
import hashlib
import io
import json
import math
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))                    # code/pipeline/medical_extract
# 仓库根：medical_extract -> pipeline -> code -> 仓库根
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))

CSV_REL = 'code/pipeline/out/step1/area_per_slice_v2.csv'
CONTRACT_REL = 'code/pipeline/out/postprocess/contract-pA-v1.json'
METRICS_REL = 'code/pipeline/out/step1/metrics_v2.json'
VIEWER_DATA_REL = 'code/viewer/viewer_data.js'

CSV_PATH = os.path.join(REPO_ROOT, 'code', 'pipeline', 'out', 'step1', 'area_per_slice_v2.csv')
CONTRACT_PATH = os.path.join(REPO_ROOT, 'code', 'pipeline', 'out', 'postprocess', 'contract-pA-v1.json')
METRICS_PATH = os.path.join(REPO_ROOT, 'code', 'pipeline', 'out', 'step1', 'metrics_v2.json')
VIEWER_DATA_PATH = os.path.join(REPO_ROOT, 'code', 'viewer', 'viewer_data.js')

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

LABEL_V5 = '阶段2-CFD算例包/结果/P0-result-pA-v5/后处理/metrics.json'
LABEL_V5C = '阶段2-CFD算例包/结果/P0-result-pA-v5C/后处理/metrics.json'
LABEL_VALVE = '阶段1-三维重建/metrics_v2.json'
LABEL_PB_V1 = '阶段2-CFD算例包/结果/P0-result-pB-v1/后处理/metrics.json'
LABEL_PB_V1C = '阶段2-CFD算例包/结果/P0-result-pB-v1C/后处理/metrics.json'
LABEL_PB_VALVE = '升级施工-T14c/_regT14c/pB_v1_{base,facegrow,largest}/step1/metrics_pB_v2.json'
LABEL_OUT_T17 = '阶段5-交互查看器/升级施工-T17/viewer_plus_data.js'

Q_ANCHOR_L_MIN = 15.0              # L/min，v5 定流量标定点
DP_ANCHOR_EXPECT = 18.45           # Pa，任务书锚点（实测 18.445960…）
DP_PB_EXPECT = 45.63               # Pa，患者B 参考点（实测 45.624982…）
SWEEP_Q = [7.5, 15.0, 30.0, 45.0]  # L/min，静息→用力呼吸四工况
THRESHOLD_PA = 75.0                # Pa，四相鼻测压法参考压

# ---------- 两档最小轴面积（与 extract_clinical.py 共用） ----------
MIN_RAW_LABEL = ('门限内轴面最小值，非解剖值；旧值 244.2 的来源 = `>=0.1×max_area`，'
                 '`step1_airway_segment.py:402`')
MIN_NO_THRESHOLD_LABEL = '未加区域约束，含边界毛刺，不可作解剖值'
MIN_ANATOMIC_NOTE = '本阶段不产出（挂 T7）'


def axial_area_minima(csv_path, threshold_ratio=0.1):
    """轴面最小面积的**两档**口径（本函数是唯一实现，extract_clinical.py 直接导入）。

    门限与 step1_airway_segment.py:402 对齐：
        main_body = (areas > 0) & (areas >= max(areas) * 0.1)
      min_raw          = 门限内最小（≡ 现役产物字段 min_axial_area_mm2，**非解剖值**）
      min_no_threshold = 去掉门限、对全部 total_mm2>0 层取最小（含两端边界毛刺）
      min_anatomic     = 本阶段不产出（挂 T7）；任何地方不得用 min_raw 冒充它
    """
    rows = []
    with io.open(csv_path, 'r', encoding='utf-8-sig') as f:
        rd = csv.reader(f)
        next(rd)                                    # slice,z_mm,total_mm2,left_mm2,right_mm2
        for row in rd:
            if row and row[0].strip():
                rows.append((float(row[0]), float(row[1]), float(row[2])))
    if not rows:
        raise ValueError('面积曲线为空: ' + csv_path)
    totals = [r[2] for r in rows]
    max_area = max(totals)
    gate = max_area * threshold_ratio
    gated = [i for i, t in enumerate(totals) if t > 0 and t >= gate]
    air = [i for i, t in enumerate(totals) if t > 0]
    if not gated or not air:
        raise ValueError('面积曲线无有效层: ' + csv_path)
    i_raw = min(gated, key=lambda i: totals[i])
    i_nt = min(air, key=lambda i: totals[i])

    def pack(i, label, n_cand):
        return {
            'mm2': totals[i],
            'mm2_6dp': round(totals[i], 6),
            'layer': int(rows[i][0]),
            'z_mm': rows[i][1],
            'label': label,
            'n_candidates': n_cand,
        }

    return {
        'source': CSV_REL,
        'threshold_rule': 'areas > 0 且 areas >= %.1f * max(areas)' % threshold_ratio,
        'threshold_mm2': gate,
        'total_max_mm2': max_area,
        'n_rows': len(rows),
        'n_slices_with_air': len(air),
        'min_raw': pack(i_raw, MIN_RAW_LABEL, len(gated)),
        'min_no_threshold': pack(i_nt, MIN_NO_THRESHOLD_LABEL, len(air)),
        'min_anatomic': {'mm2': None, 'mm2_6dp': None,
                         'label': MIN_ANATOMIC_NOTE, 'status': 'not_produced'},
    }


# ---------- 三档 split 出处（分开命名，禁止跨口径互证） ----------
# 母本钉值（仓外 metrics.json 实测，md5 固定；下方断言逐位比对）
SPLIT_RUNA_MOTHER_L = 39.00135467342238     # v5 totals.flow_share_L_pct（inletL 块 = 患者右）
SPLIT_RUNA_MOTHER_R = 60.99864532657763     # v5 totals.flow_share_R_pct（inletR 块 = 患者左）
SPLIT_RUNB_MOTHER_L = 51.86676904959288     # v5C totals.flow_share_L_pct
SPLIT_RUNB_MOTHER_R = 48.13323095040711     # v5C totals.flow_share_R_pct
MD5_V5 = '9a49276eed10bbef6a9210e3182ab854'
MD5_V5C = '4a8b22024769c0846cddf149d711f651'

SPLIT_PROVENANCE = {
    'split_imposed_RunA': {
        'label': 'Run-A 入口边界条件按开口面积分配（对输入的复述）',
        'source': (
            'ROOT 相对路径 ' + LABEL_V5 +
            '（totals.flow_share_L_pct=39.00135467342238 / flow_share_R_pct=60.99864532657763，'
            'md5=' + MD5_V5 + '）；仓内契约投影 ' + CONTRACT_REL +
            ' metrics.split_L_pct=39.0 / split_R_pct=61.0（母本的 1 位取整，非独立测量）；'
            '生成式 code/pipeline/step2_make_ofcase.py:1548（Qi = Q_TOTAL * A / (A_L + A_R)）与'
            ' :1563-1564（自注「按开口面积比例分配，声明为建模假设（审计R2）」）'
        ),
        'semantics': ('边界条件输入的复述，非生理量，非患者真实分流；'
                      '不得作为分流证据，也不得与 Run-B 互证'),
    },
    'split_natural_RunB': {
        'label': 'Run-B 等压终态自然分流（仓外 v5C 实测），单例未复算、未收敛判定',
        'source': (
            'ROOT 相对路径 ' + LABEL_V5C +
            '（totals.flow_share_L_pct=51.86676904959288 / flow_share_R_pct=48.13323095040711，'
            'md5=' + MD5_V5C + '）'
        ),
        'semantics': ('求解结果（等压终态），单例未复算、未做收敛判定；'
                      '与 Run-A 契约值口径不同，不可互相印证'),
    },
    'split_synthetic_demo': {
        'label': '合成演示（非患者数据）',
        'source': (VIEWER_DATA_REL + ':13（meta.metrics.split_L_pct=50.0 / split_R_pct=50.0；'
                   'md5={md5}）'),
        'semantics': '合成示例管腔的对称 50/50，仅用于演示；任何情况下不得当作患者分流',
    },
}


def md5_file(path):
    h = hashlib.md5()
    with io.open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def split_provenance():
    """把运行期 md5（合成演示件）填进出处串；其余两条母本 md5 为钉值。"""
    md5 = md5_file(VIEWER_DATA_PATH) if os.path.isfile(VIEWER_DATA_PATH) else 'unavailable'
    out = {}
    for key, spec in SPLIT_PROVENANCE.items():
        out[key] = {
            'label': spec['label'],
            'source': spec['source'].replace('{md5}', md5),
            'semantics': spec['semantics'],
        }
    return out


# ---------- 三态断言 ----------
RECORDS = []      # [(status, name, detail)]


def check(name, ok, detail=''):
    status = 'PASS' if ok else 'FAIL'
    RECORDS.append((status, name, detail))
    print(('PASS ' if ok else 'FAIL ') + name + (('  ' + detail) if detail else ''))
    return bool(ok)


def skip(name, detail=''):
    """资产缺失 ⇒ SKIP（资产缺失）。绝不静默通过、绝不伪造。"""
    RECORDS.append(('SKIP', name, detail))
    print('SKIP ' + name + (('  ' + detail) if detail else ''))
    return False


def skip_all(names, detail):
    for nm in names:
        skip(nm, detail)


def counts():
    p = len([1 for s, _, _ in RECORDS if s == 'PASS'])
    s = len([1 for st, _, _ in RECORDS if st == 'SKIP'])
    f = len([1 for st, _, _ in RECORDS if st == 'FAIL'])
    return p, s, f


# ---------- 断言名（资产缺失时按名登记 SKIP，绝不漏项） ----------
C_PA_DP = 'pA dP 与任务书锚点 18.45 Pa 一致'
C_PA_Q = 'pA 定流量 15 L/min 一致'
C_PA_R = 'pA 模型常数 R = 18.45 / 0.25 = 73.8 Pa/(L/s)（任务书口径）'
C_PA_SPLIT_SUM = 'pA 分流合计 100%'
C_PA_SPLIT_NAT = ('pA 分流与仓外 v5C 母本 flow_share_L_pct=51.86676904959288 / '
                  'flow_share_R_pct=48.13323095040711 逐位一致（split_natural_RunB；'
                  '1 位投影 flow_share_L_pct 51.9 / flow_share_R_pct 48.1，不另立证据；'
                  'inletL/inletR 是 step2 的补丁名，不等于放射学左右；'
                  '患者左右需按 case 元数据确认）')
C_PA_SI = 'pA 对称性指数 SI = 2|L-R|/(L+R)x100% ≈ 7.5%（源值直推 7.467%）'
C_PA_SWEEP_R = 'pA 扫描表 R 逐点恒为 73.8（层流线性假设下 R 退化为常数；两位显示口径回推 R∈[73.76,73.84]）'
C_PA_SWEEP_ANCHOR = 'pA 扫描表锚点工况点 15 L/min = 18.45 Pa'
C_PA_SWEEP_3045 = 'pA 扫描表 30/45 L/min 与页面既有 ΔP-流量卡（36.9 / 55.35）逐字一致'
C_PA_SWEEP_75 = 'pA 扫描 7.5 L/min = 9.23 Pa（任务书所列 13.84 对应 R=110.8，与本锚点不自洽，已按锚点重算）'
C_PA_Q75 = 'pA 75 Pa 阈值交点 Q = 61.0 L/min（任务书 40.7 对应 R=110.8，同上不自洽）'
C_PA_VALVE = ('pA 鼻瓣区最小截面积 244.2 mm2 @第273层'
              '（门限内轴面最小值（非解剖值）；旧值来源 = `areas >= 0.1*max(areas)`，'
              'step1_airway_segment.py:402）')

C_PB_Q = 'pB 定流量 15 L/min 一致'
C_PB_DP = 'pB dP 显示口径 45.63 Pa（源 45.624982 -> 三位 45.625 -> 两位 45.63）'
C_PB_R = 'pB 模型常数 R = 45.63 / 0.25 -> 182.5 Pa/(L/s)（任务书口径）'
C_PB_SPLIT_SUM = 'pB 分流合计 100%'
C_PB_RATIO = 'pB 右/左 ~ 3.5x（任务书口径；实测 3.43）'
C_PB_SI = 'pB 对称性指数 SI（近单侧闭塞，>100% 数学合理）'
C_PB_SWEEP = 'pB 扫描 15 L/min = 45.63 Pa（与参考点逐字一致）'
C_PB_Q75 = 'pB 75 Pa 阈值交点 Q = 24.7 L/min'
C_PB_VALVE = 'pB 鼻瓣区复现变体数值一致'

C_AREA_RAW = ('pA min_raw（门限 0.1*max 内轴面最小）= 244.208453 mm2 @层273'
              '（仓内 area_per_slice_v2.csv 实算，非解剖值）')
C_AREA_NT = ('pA min_no_threshold（全部 total>0 层最小）= 2.933435 mm2 @层294 z=-601.24'
             '（含边界毛刺，不可作解剖值）')
C_AREA_DISTINCT = 'min_raw 与 min_no_threshold 非同值（两档不得互相冒充）'
C_AREA_ANATOMIC = 'min_anatomic 本阶段不产出（挂 T7），输出中为 null'
C_AREA_LAYERS = 'area csv 有面积层数与 metrics_v2.json n_slices_with_air 一致'

C_CONTRACT_SPLIT = 'contract-pA-v1.json split_L/R = 39.0/61.0（split_imposed_RunA 的契约投影）'
C_CONTRACT_ROUND = '契约 39.0/61.0 恰为 v5 母本 39.00135467342238/60.99864532657763 的 1 位取整'
C_SYNTH = 'viewer_data.js:13 split = 50.0/50.0（split_synthetic_demo）'
C_CALIBER_DISTINCT = '三档 split 不可互证：Run-A 与 Run-B 差 > 0.5 个百分点，Run-B 与合成差 > 0.5'
C_PROV_SHAPE = 'SPLIT_PROVENANCE 恰为三键，且每键含 label/source/semantics'
C_PROV_IMPOSED_WORD = 'split_imposed_RunA 的 semantics 写明「非患者真实分流」'

C_SIX_KEYS = '写入前 data 键集在写入后保留（写入前 ⊆ 写入后，且含 compare）'
C_INJ_SCRIPT = 'compare 不含 </script 注入风险'
C_INJ_COMMENT = 'compare 不含 <!-- 注入风险'
C_INJ_LEGACY = 'compare 不含 legacy 字段名 resistance_total'
C_MD5_SAME = '两份 viewer_plus_data.js 字节一致（md5）'
C_BACK_KEYS = '回读键集保留写入前全部键，且含 compare'
C_BACK_CASES = '回读 compare 两病例齐'
C_BACK_R = '回读 pA R / ΔP 与锚定公式一致'
C_BACK_PB = '回读 pB ΔP 与源文件对拍一致'
C_BACK_SWEEP = '回读四工况扫描与 R*Q 公式一致（R 恒定，两位显示口径）'

PA_CHECKS = [C_PA_DP, C_PA_Q, C_PA_R, C_PA_SWEEP_R, C_PA_SWEEP_ANCHOR,
             C_PA_SWEEP_3045, C_PA_SWEEP_75, C_PA_Q75]
PA_SPLIT_CHECKS = [C_PA_SPLIT_SUM, C_PA_SPLIT_NAT, C_PA_SI]
PB_CHECKS = [C_PB_Q, C_PB_DP, C_PB_R, C_PB_SWEEP, C_PB_Q75]
PB_SPLIT_CHECKS = [C_PB_SPLIT_SUM, C_PB_RATIO, C_PB_SI]
AREA_CHECKS = [C_AREA_RAW, C_AREA_NT, C_AREA_DISTINCT, C_AREA_ANATOMIC, C_AREA_LAYERS]
CONTRACT_CHECKS = [C_CONTRACT_SPLIT, C_CONTRACT_ROUND]
PROV_CHECKS = [C_SYNTH, C_CALIBER_DISTINCT, C_PROV_SHAPE, C_PROV_IMPOSED_WORD]
BODY_CHECKS = [C_SIX_KEYS, C_INJ_SCRIPT, C_INJ_COMMENT, C_INJ_LEGACY]
BACKREAD_CHECKS = [C_MD5_SAME, C_BACK_KEYS, C_BACK_CASES, C_BACK_R, C_BACK_PB, C_BACK_SWEEP]

CHECK = RECORDS          # 兼容旧名（只读视图）


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


def load_totals(path, label, names):
    """资产缺失 ⇒ 依赖它的断言逐条 SKIP（资产缺失）。返回 totals 或 None。"""
    if not os.path.isfile(path):
        skip_all(names, '资产缺失 · ' + label)
        return None
    return rd(path)['totals']


def main():
    ap = argparse.ArgumentParser(
        description='多病例对比数据 → viewer_plus_data.js（默认 dry-run，不落盘）')
    g = ap.add_mutually_exclusive_group()
    g.add_argument('--dry-run', dest='write', action='store_false',
                   help='默认行为：只打印将写出的目标与字节数，不落盘')
    g.add_argument('--write', dest='write', action='store_true',
                   help='显式写盘（默认不写；仓外在用件无批复授权时不得使用）')
    ap.set_defaults(write=False)
    a = ap.parse_args()
    dry_run = not a.write

    # ---------- pA：ΔP 与流量（Run-A 定流量口径 = 锚点来源） ----------
    pa = load_totals(PA_V5, LABEL_V5, PA_CHECKS)
    pa_dp_raw = pa_q = pa_dp = R_A = None
    if pa is not None:
        pa_dp_raw = float(pa['dP_Pa'])
        pa_q = float(pa['Q_inlet_total_L_min'])
        check(C_PA_DP, abs(pa_dp_raw - DP_ANCHOR_EXPECT) < 0.01,
              '源文件实测 %.6f Pa' % pa_dp_raw)
        check(C_PA_Q, abs(pa_q - Q_ANCHOR_L_MIN) < 0.001,
              '源文件实测 %.6f L/min' % pa_q)
        pa_dp = DP_ANCHOR_EXPECT                                     # 显示/模型口径
        R_A = rh1(pa_dp / (Q_ANCHOR_L_MIN / 60.0))                   # 73.8
        check(C_PA_R, abs(R_A - 73.8) < 0.001,
              '实测 %.1f（源值直算 %.4f）' % (R_A, pa_dp_raw / (pa_q / 60.0)))

    # ---------- pA：Run-B 自然分流（等压终态） ----------
    pac = load_totals(PA_V5C, LABEL_V5C, PA_SPLIT_CHECKS)
    pa_left = pa_right = pa_si = None
    if pac is not None:
        pa_left = float(pac['flow_share_R_pct'])    # inletR 块 = 患者左
        pa_right = float(pac['flow_share_L_pct'])   # inletL 块 = 患者右
        check(C_PA_SPLIT_SUM, abs(pa_right + pa_left - 100.0) < 0.01,
              '右 %.4f / 左 %.4f' % (pa_right, pa_left))
        # GAP-4：比较对象必须是仓外 v5C 母本，不是 viewer_data.js 的历史投影
        check(C_PA_SPLIT_NAT,
              abs(pa_right - SPLIT_RUNB_MOTHER_L) < 1e-9
              and abs(pa_left - SPLIT_RUNB_MOTHER_R) < 1e-9,
              '实测 右 %.14f / 左 %.14f（母本 右 %.14f / 左 %.14f，md5=%s）'
              % (pa_right, pa_left, SPLIT_RUNB_MOTHER_L, SPLIT_RUNB_MOTHER_R, MD5_V5C))

    # ---------- pA：鼻瓣区（门限内轴面最小值，非解剖值；旧值来源 step1_airway_segment.py:402） ----------
    pav = None
    if os.path.isfile(PA_VALVE):
        pav = rd(PA_VALVE)
        pa_valve = float(pav['min_axial_area_mm2'])
        check(C_PA_VALVE, abs(pa_valve - 244.2) < 0.05,
              '实测 %.1f mm2 第 %s 层 z=%s mm（注：min_raw 精确值见下，非解剖值；'
              '244.2 旧值来源 = areas >= 0.1*max(areas)，step1_airway_segment.py:402）'
              % (pa_valve, pav['min_layer'], pav['min_z_mm']))
    else:
        pa_valve = None
        skip(C_PA_VALVE, '资产缺失 · ' + LABEL_VALVE)

    # ---------- pB：ΔP 与流量（Run-A 定流量口径） ----------
    pb = load_totals(PB_V1, LABEL_PB_V1, PB_CHECKS)
    pb_dp_raw = pb_q = pb_dp = R_B = None
    if pb is not None:
        pb_dp_raw = float(pb['dP_Pa'])
        pb_q = float(pb['Q_inlet_total_L_min'])
        check(C_PB_Q, abs(pb_q - Q_ANCHOR_L_MIN) < 0.001,
              '源文件实测 %.6f L/min' % pb_q)
        # 显示口径：先取三位 45.625，再 half-up 两位 -> 45.63（与 T17 卡片/参考点既有口径一致）
        pb_dp = rh2(round(pb_dp_raw, 3))
        check(C_PB_DP, abs(pb_dp - DP_PB_EXPECT) < 0.001, '实测 %.2f' % pb_dp)
        R_B = rh1(pb_dp / (Q_ANCHOR_L_MIN / 60.0))                    # 182.5
        check(C_PB_R, abs(R_B - 182.5) < 0.001,
              '实测 %.1f（源值直算 %.4f）' % (R_B, pb_dp_raw / (pb_q / 60.0)))

    # ---------- pB：Run-B 自然分流（等压终态） ----------
    pbc = load_totals(PB_V1C, LABEL_PB_V1C, PB_SPLIT_CHECKS)
    pb_left = pb_right = pb_si = None
    if pbc is not None:
        pb_left = float(pbc['flow_share_R_pct'])
        pb_right = float(pbc['flow_share_L_pct'])
        check(C_PB_SPLIT_SUM, abs(pb_right + pb_left - 100.0) < 0.01,
              '右 %.4f / 左 %.4f' % (pb_right, pb_left))
        check(C_PB_RATIO, 3.3 < (pb_right / pb_left) < 3.6,
              '实测 %.3fx' % (pb_right / pb_left))

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
        check(C_PB_VALVE, same, str(vals))
        pb_valve, pb_valve_layer, pb_valve_z = vals[0]
        pb_valve_src = (LABEL_PB_VALVE +
                        '（%d 变体一致） · 非正式环节① 产物（0.468mm soft-tissue），仅作对比参考' % len(vals))
    else:
        # GAP-5：缺失 ⇒ SKIP（资产缺失），不再「允许缺失即 PASS」
        skip(C_PB_VALVE, '资产缺失 · ' + LABEL_PB_VALVE + ' -> pB 鼻瓣区字段置 null')

    # ---------- 仓内资产：两档最小面积（GAP-2 / GAP-5） ----------
    area = None
    if os.path.isfile(CSV_PATH):
        area = axial_area_minima(CSV_PATH)
        mr = area['min_raw']
        mnt = area['min_no_threshold']
        check(C_AREA_RAW,
              mr['mm2_6dp'] == 244.208453 and mr['layer'] == 273,
              '实测 %.6f mm2 @层%d z=%.2f mm（门限 %.3f mm2，候选 %d 层）'
              % (mr['mm2'], mr['layer'], mr['z_mm'], area['threshold_mm2'], mr['n_candidates']))
        check(C_AREA_NT,
              mnt['mm2_6dp'] == 2.933435 and mnt['layer'] == 294,
              '实测 %.6f mm2 @层%d z=%.2f mm（无门限，全 %d 个有面积层）'
              % (mnt['mm2'], mnt['layer'], mnt['z_mm'], mnt['n_candidates']))
        check(C_AREA_DISTINCT, abs(mr['mm2'] - mnt['mm2']) > 1.0,
              'min_raw %.6f / min_no_threshold %.6f' % (mr['mm2'], mnt['mm2']))
        check(C_AREA_ANATOMIC, area['min_anatomic']['mm2'] is None,
              MIN_ANATOMIC_NOTE)
    else:
        skip_all(AREA_CHECKS, '资产缺失 · ' + CSV_REL)

    if area is not None and os.path.isfile(METRICS_PATH):
        mj = json.loads(io.open(METRICS_PATH, 'r', encoding='utf-8').read())
        check(C_AREA_LAYERS, area['n_slices_with_air'] == int(mj['n_slices_with_air']),
              'csv %d 层 vs metrics %d 层（md5=%s）'
              % (area['n_slices_with_air'], int(mj['n_slices_with_air']), md5_file(METRICS_PATH)))
    elif area is None:
        pass                       # 已在 AREA_CHECKS 里登记 SKIP
    else:
        skip(C_AREA_LAYERS, '资产缺失 · ' + METRICS_REL)

    # ---------- 仓内资产：Run-A 契约（GAP-4 / GAP-5） ----------
    contract = None
    if os.path.isfile(CONTRACT_PATH):
        contract = json.loads(io.open(CONTRACT_PATH, 'r', encoding='utf-8-sig').read())
        cm = contract.get('metrics', {})
        imp_l = cm.get('split_L_pct')
        imp_r = cm.get('split_R_pct')
        check(C_CONTRACT_SPLIT, imp_l == 39.0 and imp_r == 61.0,
              '契约实读 split_L_pct=%r / split_R_pct=%r（split_imposed_RunA）' % (imp_l, imp_r))
        if pa is not None:
            check(C_CONTRACT_ROUND,
                  abs(round(float(pa['flow_share_L_pct']), 1) - float(imp_l)) < 1e-9
                  and abs(round(float(pa['flow_share_R_pct']), 1) - float(imp_r)) < 1e-9,
                  '母本 %.14f/%.14f -> 1 位 %.1f/%.1f；契约 %r/%r'
                  % (float(pa['flow_share_L_pct']), float(pa['flow_share_R_pct']),
                     round(float(pa['flow_share_L_pct']), 1),
                     round(float(pa['flow_share_R_pct']), 1), imp_l, imp_r))
            check('pA Run-A 母本 split 与钉值逐位一致（39.00135467342238/60.99864532657763）',
                  abs(float(pa['flow_share_L_pct']) - SPLIT_RUNA_MOTHER_L) < 1e-9
                  and abs(float(pa['flow_share_R_pct']) - SPLIT_RUNA_MOTHER_R) < 1e-9,
                  '实测 %.14f/%.14f（md5=%s）'
                  % (float(pa['flow_share_L_pct']), float(pa['flow_share_R_pct']), MD5_V5))
        else:
            skip(C_CONTRACT_ROUND, '资产缺失 · ' + LABEL_V5)
            skip('pA Run-A 母本 split 与钉值逐位一致（39.00135467342238/60.99864532657763）',
                 '资产缺失 · ' + LABEL_V5)
    else:
        skip_all(CONTRACT_CHECKS, '资产缺失 · ' + CONTRACT_REL)
        skip('pA Run-A 母本 split 与钉值逐位一致（39.00135467342238/60.99864532657763）',
             '资产缺失 · ' + CONTRACT_REL)

    # ---------- 仓内资产：合成演示 split（GAP-4） ----------
    synth_l = synth_r = None
    if os.path.isfile(VIEWER_DATA_PATH):
        try:
            vd = load_payload(VIEWER_DATA_PATH)
            synth_l = float(vd['meta']['metrics']['split_L_pct'])
            synth_r = float(vd['meta']['metrics']['split_R_pct'])
        except Exception as exc:                                  # noqa: BLE001
            skip_all(PROV_CHECKS, '不可解析 · %s: %s' % (VIEWER_DATA_REL, exc))
    if synth_l is None:
        if os.path.isfile(VIEWER_DATA_PATH):
            pass
        else:
            skip_all(PROV_CHECKS, '资产缺失 · ' + VIEWER_DATA_REL)
    else:
        check(C_SYNTH, synth_l == 50.0 and synth_r == 50.0,
              '实读 %.1f/%.1f（md5=%s）' % (synth_l, synth_r, md5_file(VIEWER_DATA_PATH)))

    # ---------- 三档口径的分隔断言（禁止跨口径互证） ----------
    prov = split_provenance()
    have_runa = pa is not None
    have_runb = pac is not None
    if have_runa and have_runb and synth_l is not None:
        check(C_CALIBER_DISTINCT,
              abs(float(pa['flow_share_L_pct']) - SPLIT_RUNB_MOTHER_L) > 0.5
              and abs(SPLIT_RUNB_MOTHER_L - synth_l) > 0.5,
              'Run-A %.4f / Run-B %.4f / 合成 %.1f'
              % (float(pa['flow_share_L_pct']), SPLIT_RUNB_MOTHER_L, synth_l))
    elif not have_runa or not have_runb:
        if C_CALIBER_DISTINCT not in [n for _, n, _ in RECORDS]:
            skip(C_CALIBER_DISTINCT, '资产缺失 · 需 Run-A 与 Run-B 母本同时在位')

    if C_PROV_SHAPE not in [n for _, n, _ in RECORDS]:
        shape_ok = (sorted(prov) == ['split_imposed_RunA', 'split_natural_RunB', 'split_synthetic_demo']
                    and all(set(v) == {'label', 'source', 'semantics'} and all(v.values())
                            for v in prov.values()))
        check(C_PROV_SHAPE, shape_ok, '键=' + ','.join(sorted(prov)))
        check(C_PROV_IMPOSED_WORD, '非患者真实分流' in prov['split_imposed_RunA']['semantics'],
              '「非患者真实分流」已写入 semantics')

    print()
    for k in ('split_imposed_RunA', 'split_natural_RunB', 'split_synthetic_demo'):
        print('[compare] split 口径 %s：%s —— %s' % (k, prov[k]['label'], prov[k]['semantics']))
    print()

    # ---------- 派生量 ----------
    def si(right, left):
        return 2.0 * abs(right - left) / (right + left) * 100.0

    if pa_right is not None:
        pa_si = si(pa_right, pa_left)
        check(C_PA_SI, 7.4 < pa_si < 7.6, '实测 %.4f%%' % pa_si)
    if pb_right is not None:
        pb_si = si(pb_right, pb_left)
        check(C_PB_SI, pb_si > 90.0, '实测 %.4f%%' % pb_si)

    sweep_dp_a = sweep_r_a = q75_a = None
    if R_A is not None:
        sweep_dp_a = [rh2(R_A * (q / 60.0)) for q in SWEEP_Q]
        sweep_r_a = [rh2(d / (q / 60.0)) for d, q in zip(sweep_dp_a, SWEEP_Q)]
        check(C_PA_SWEEP_R,
              all(abs(x - 73.8) < 0.05 for x in sweep_r_a)
              and all(abs(round(x, 1) - 73.8) < 1e-9 for x in sweep_r_a), str(sweep_r_a))
        check(C_PA_SWEEP_ANCHOR, abs(sweep_dp_a[1] - 18.45) < 0.001,
              '扫描表 = ' + str(sweep_dp_a))
        check(C_PA_SWEEP_3045,
              abs(sweep_dp_a[2] - 36.9) < 0.001 and abs(sweep_dp_a[3] - 55.35) < 0.001,
              '30 -> %.2f / 45 -> %.2f' % (sweep_dp_a[2], sweep_dp_a[3]))
        check(C_PA_SWEEP_75, abs(sweep_dp_a[0] - 9.23) < 0.001,
              '实测 %.2f' % sweep_dp_a[0])
        q75_a = rh1(THRESHOLD_PA / R_A * 60.0)
        check(C_PA_Q75, abs(q75_a - 61.0) < 0.05, '实测 %.1f L/min' % q75_a)

    q75_b = None
    if R_B is not None:
        q75_b = rh1(THRESHOLD_PA / R_B * 60.0)
        check(C_PB_Q75, abs(q75_b - 24.7) < 0.05, '实测 %.1f L/min' % q75_b)

    sweep_dp_b = None
    if R_B is not None:
        sweep_dp_b = [rh2(R_B * (q / 60.0)) for q in SWEEP_Q]
        check(C_PB_SWEEP, abs(sweep_dp_b[1] - 45.63) < 0.001, str(sweep_dp_b))

    # ---------- 组装 compare ----------
    required = [pa_dp_raw, pa_right, pa_left, pb_dp_raw, pb_right, pb_left,
                R_A, R_B, q75_a, q75_b, sweep_dp_a, sweep_dp_b, pb_dp, area]
    ready = all(x is not None for x in required)
    compare = None
    if ready:
        compare = {
            'method': ('多病例对比：全部数值由各自后处理 metrics.json 直算 R=ΔP/Q（层流线性口径）；'
                       '不引用 legacy resistance_total'),
            'side_convention': ('分侧按患者自身左右显示：后处理 inletL 块=患者右、inletR 块=患者左'
                                '（2026-10-01 投影实测勘误）'),
            'split_provenance': prov,
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
                    'split_caliber': 'split_natural_RunB',
                    'split_semantics': prov['split_natural_RunB']['semantics'],
                    'side_ratio': rh2(max(pa_right, pa_left) / min(pa_right, pa_left)),
                    'symmetry_index_pct': rh2(pa_si),
                    'sweep_dP_Pa': sweep_dp_a,
                    'q_at_75Pa_L_min': q75_a,
                    'valve_min_area_mm2': pa_valve,
                    'valve_min_layer': (pav['min_layer'] if pav is not None else None),
                    'valve_min_z_mm': (pav['min_z_mm'] if pav is not None else None),
                    'valve_min_area_semantics': ('min_raw（门限内轴面最小值，非解剖值）；'
                                                 '见 valve_min_area_two_tier'),
                    'valve_min_area_two_tier': {
                        'min_raw_mm2': area['min_raw']['mm2_6dp'],
                        'min_raw_layer': area['min_raw']['layer'],
                        'min_raw_z_mm': area['min_raw']['z_mm'],
                        'min_raw_label': MIN_RAW_LABEL,
                        'min_no_threshold_mm2': area['min_no_threshold']['mm2_6dp'],
                        'min_no_threshold_layer': area['min_no_threshold']['layer'],
                        'min_no_threshold_z_mm': area['min_no_threshold']['z_mm'],
                        'min_no_threshold_label': MIN_NO_THRESHOLD_LABEL,
                        'min_anatomic_mm2': None,
                        'min_anatomic_note': MIN_ANATOMIC_NOTE,
                        'source': area['source'],
                        'threshold_rule': area['threshold_rule'],
                        'threshold_mm2': round(area['threshold_mm2'], 6),
                    },
                    'valve_source': '阶段1-三维重建/metrics_v2.json（环节① 0.35mm 各向同性，官方产物）',
                    'source': ('P0-result-pA-v5/后处理/metrics.json（ΔP）+ '
                               'P0-result-pA-v5C/后处理/metrics.json（Run-B 自然分流）+ '
                               '阶段1-三维重建/metrics_v2.json（鼻瓣区）+ '
                               'code/pipeline/out/step1/area_per_slice_v2.csv（两档最小面积实算）'),
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
                    'split_caliber': 'split_natural_RunB',
                    'split_semantics': (prov['split_natural_RunB']['semantics'] +
                                        '；本例读数取自 P0-result-pB-v1C/后处理/metrics.json，'
                                        '不是 v5C 母本数值'),
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
                           '科研与康复参考（非医疗器械）'),
        }

    # ---------- 组装 data 对象（保留既有键） ----------
    txt = None
    keys_before = None                      # 写盘后回读断言的保留性基线
    if not ready:
        skip_all(BODY_CHECKS, '上游资产缺失/未就绪，载荷未组装，无法生成输出文本')
    else:
        old = None
        if os.path.isfile(OUT_T17):
            try:
                old = load_payload(OUT_T17)
            except Exception as exc:                              # noqa: BLE001
                print('[compare] 既有 data 解析失败：%s' % exc)
        if old is None:
            skip_all(BODY_CHECKS, '资产缺失 · ' + LABEL_OUT_T17)
        else:
            keys_before = sorted(k for k in old if k != 'compare')
            print('[compare] 既有键（写入前，compare 除外）: ' + str(keys_before))
            old['compare'] = compare
            keys_post = sorted(old.keys())
            missing_pre = [k for k in keys_before if k not in set(keys_post)]
            check(C_SIX_KEYS,
                  not missing_pre and 'compare' in keys_post,
                  '写入前 %d 键 / 写入后 %d 键，缺：%s'
                  % (len(keys_before), len(keys_post), (missing_pre or '无')))
            body = json.dumps(old, ensure_ascii=False, separators=(',', ':'))
            check(C_INJ_SCRIPT, '</script' not in body.lower())
            check(C_INJ_COMMENT, '<!--' not in body)
            check(C_INJ_LEGACY, '"resistance_total"' not in body)
            head = ('// viewer_plus_data.js —— T17 SimScale后处理集成数据包（生成脚本：升级施工-T17/extract_*.py）\n'
                    '// T18-M4：compare 键由 extract_compare.py 追加（多病例对比 · ΔP/Q 直算 · 禁用 legacy resistance_total）\n'
                    '// 坐标系：mm，已减 airwayMesh 质心 CENTER=[79.22,71.87,56.98]（与 viewer_data.js 同帧）\n'
                    '// 说明：科研与康复参考 · 非医疗器械 · 仿真估计 · 非临床测量\n')
            txt = head + 'window.VIEWER_PLUS_DATA = ' + body + ';\n'

    _, s_pre, f_pre = counts()
    nbytes = len(txt.encode('utf-8')) if txt is not None else None
    wrote = False

    if f_pre or s_pre:
        print('[compare] 不写盘（失败 %d / 跳过 %d）' % (f_pre, s_pre))
        if dry_run and txt is not None:
            print('[compare] dry-run：目标（未写）')
            for p in (OUT_T17, OUT_ROOT):
                print('  - %s（%s B）' % (p, format(nbytes, ',')))
    elif dry_run:
        print('[compare] dry-run：默认不落盘，将写出：')
        for p in (OUT_T17, OUT_ROOT):
            print('  - %s（%s B）' % (p, format(nbytes, ',') if nbytes is not None else '字节数不可算'))
    else:
        for p in (OUT_T17, OUT_ROOT):
            with io.open(p, 'w', encoding='utf-8', newline='\n') as f:
                f.write(txt)
            print('[compare] 写出 %s (%.2f MB)' % (p, os.path.getsize(p) / 1048576.0))
        wrote = True

        def md5(p):
            return hashlib.md5(io.open(p, 'rb').read()).hexdigest().upper()

        m17, mroot = md5(OUT_T17), md5(OUT_ROOT)
        check(C_MD5_SAME,
              m17 == mroot and m17 == hashlib.md5(txt.encode('utf-8')).hexdigest().upper(),
              m17)

        # ---------- 回读断言（仅写盘后） ----------
        back = load_payload(OUT_T17)
        keys_after = sorted(back.keys())
        missing_back = [k for k in (keys_before or []) if k not in set(keys_after)]
        check(C_BACK_KEYS,
              'compare' in keys_after and not missing_back,
              '回读 %d 键，缺：%s' % (len(keys_after), (missing_back or '无')))
        check(C_BACK_CASES, [c['id'] for c in back['compare']['cases']] == ['pA', 'pB'])
        check(C_BACK_R,
              abs(back['compare']['cases'][0]['R_Pa_per_Lps'] - 73.8) < 0.001
              and abs(back['compare']['cases'][0]['dP_Pa'] - 18.45) < 0.001)
        check(C_BACK_PB,
              abs(back['compare']['cases'][1]['dP_raw_Pa'] - pb_dp_raw) < 1e-6,
              '%.6f' % back['compare']['cases'][1]['dP_raw_Pa'])
        check(C_BACK_SWEEP,
              all(abs(x - 73.8) < 0.05 and abs(round(x, 1) - 73.8) < 1e-9
                  for x in [back['compare']['anchor']['sweep_dP_Pa'][i] / (SWEEP_Q[i] / 60.0)
                            for i in range(4)]),
              str(back['compare']['anchor']['sweep_dP_Pa']))
        print('[compare] md5(viewer_plus_data.js) = %s' % m17)
    if not wrote:
        print('[compare] 回读断言未登记（本轮未写盘，没有可回读的对象）')

    print()
    n, s, f = counts()
    tail = ''
    if f:
        tail = ' · 存在失败，不写盘'
    elif s:
        tail = ' · 未写盘（存在 SKIP）'
    elif wrote:
        tail = ' · 已写盘 2 份（--write）'
    else:
        tail = ' · 未写盘（dry-run 默认；如需写盘加 --write）'
    print('[compare] 断言 %d / 跳过 %d / 失败 %d%s' % (n, s, f, tail))
    return 1 if f else 0


if __name__ == '__main__':
    sys.exit(main())
