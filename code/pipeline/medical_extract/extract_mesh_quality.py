# -*- coding: utf-8 -*-
"""
T17-F2 extract_mesh_quality.py —— log.checkMesh 解析 → 网格质量卡数据 → viewer_plus_data.js
（数据管道第 6 脚本：T10 审计口径的网格质量数字 + 社区对照）
"""
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

ROOT = r'F:\比赛项目\罕见无界黑客松\赛题3-鼻腔气流分析\项目\P0-鼻塞设计工具'
CASE = ROOT + r'\阶段2-CFD算例包\结果\P0-result-pA-v5'
OUT = ROOT + r'\阶段5-交互查看器\升级施工-T17\viewer_plus_data.js'


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
    txt = io.open(CASE + r'\log.checkMesh', 'r', encoding='utf-8', errors='replace').read()

    def grab(pat, cast=float, default=None):
        m = re.search(pat, txt, re.M)
        if not m:
            return default
        s = m.group(1)
        if s.endswith('.'):
            s = s[:-1]   # 日志句读：数值后紧跟句号时剥掉
        return cast(s)

    result = {
        'source': 'P0-result-pA-v5/log.checkMesh（T10 审计口径）',
        'cells': grab(r'cells:\s+(\d+)', int),
        'points': grab(r'points:\s+(\d+)', int),
        'faces': grab(r'faces:\s+(\d+)', int),
        'hexahedra': grab(r'hexahedra:\s+(\d+)', int),
        'nonOrthoMax': grab(r'Mesh non-orthogonality Max:\s+([0-9.eE+\-]+)'),
        'nonOrthoAvg': grab(r'non-orthogonality Max:\s*([0-9.eE+\-]+)\s+average:\s+([0-9.eE+\-]+)'),
        'aspectRatioMax': grab(r'Max aspect ratio =\s+([0-9.eE+\-]+)'),
        'skewnessMax': grab(r'Max skewness =\s+([0-9.eE+\-]+)'),
        'volMin_m3': grab(r'Min volume =\s+([0-9.eE+\-]+)'),
        'volMax_m3': grab(r'Max volume =\s+([0-9.eE+\-]+)'),
        'boundaryOpennessOK': 'Boundary openness' in txt and 'OK' in txt.split('Boundary openness')[1][:60],
        'verdict': 'Mesh OK' if re.search(r'^Mesh OK\.', txt, re.M) else 'CHECK FAILED',
        'communityCompare': '外部公开自查页旧算例记载（不指名）：网格质量检查未通过、求解未证实收敛——详见路演对标页',
    }
    # nonOrthoAvg 修正（第二个分组）
    m = re.search(r'non-orthogonality Max:\s*([0-9.eE+\-]+)\s+average:\s+([0-9.eE+\-]+)', txt)
    if m:
        result['nonOrthoMax'] = float(m.group(1))
        result['nonOrthoAvg'] = float(m.group(2))
    # 体积均匀度
    if result['volMin_m3'] and result['volMax_m3']:
        ratio = (result['volMax_m3'] - result['volMin_m3']) / result['volMax_m3'] * 100
        result['volUniformPct'] = round(ratio, 4)
    print('[mesh] cells=%s  nonOrtho=%s/%s  aspect=%s  skew=%s  volUniform=%s%%  verdict=%s' %
          (result['cells'], result['nonOrthoMax'], result['nonOrthoAvg'],
           result['aspectRatioMax'], result['skewnessMax'], result.get('volUniformPct'), result['verdict']))
    assert result['verdict'] == 'Mesh OK', 'checkMesh 结论非 Mesh OK'

    obj = read_json_blob(OUT)
    if obj is None:
        obj = {}
        print('[mesh] creating new viewer_plus_data.js')
    obj['meshQuality'] = result
    write_json_blob(OUT, obj)
    print('[mesh] OK -> %s (%.2f MB)' % (OUT, os.path.getsize(OUT) / 1048576.0))
    return 0


if __name__ == '__main__':
    sys.exit(main())
