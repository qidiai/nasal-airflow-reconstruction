# -*- coding: utf-8 -*-
import os  # T11 开源脱敏
"""T10 左右符号链决定性测试 v2（真投影比对版 · 替代 cmd_lr_chain.py 的 print 结论版）

背景：cmd_lr_chain.py docstring 承诺"把 split_L/R 的原始 patch 体素质心投影到查看器世界坐标验证"，
实际只 print 了 airwayMesh 顶点范围+硬编码结论，投影比对一行都没有（T10 审计 N5）。
本脚本补上那次比对，且全部断言可复跑：

判定规则（钉死在源码事实，不由本脚本自证）：
  R1 step5_export_viewer_data.py:85 `V_air = np.stack([verts_kji[:,2], verts_kji[:,1], verts_kji[:,0]], axis=1)`
     ⇒ 查看器 x = 数组列轴 i（无反射）；marching_cubes spacing=(spz,spy,spx)，mask shape=(394,512,512) ⇒ 列轴=512
  R2 DICOM IOP=[1,0,0, 0,1,-0]（394 层逐层实测一致）+ LPS 约定 ⇒ 列+ = 患者坐标 +x = 患者左
     ⇒ 查看器世界 x<0 半区 = 患者右
  R3 三条产品线命名一致为"低列=L"：step1 l_areas=[:,:,:mid]、step2 inletL=(cx<split_i·dx)、step3 shellL=(xgrid<xs_s)
帧一致性：OF case x = 列×dx（step2:189/283），viewer x = 列×0.3496−CENTER_x（step5:85/:103），同一 CT-mm 物理帧

断言（输出 PASS/FAIL，任一 FAIL 即 Y1 禁止施工）：
  A1 v5C inletL.face_centre_mm 经 CENTER 平移后 world_x < 0  ⇒ "L"patch 落在患者右半区
  A2 v5C inletR 经平移后 world_x > 0
  A3 viewer_data.js airwayMesh 顶点均值 ≈ 0（CENTER 同帧自证）
  A4 line439 显示值 51.9 属 v5C flow_share_L_pct（Run-B 等压法实测通气分配）
  A5 line1262 显示值 13.99/21.30 属 v5（Run-A）dP_L_Pa/dP_R_Pa，与 439 不同源
  A6 DICOM IOP 全 394 层逐层实测 = [1,0,0, 0,1,-0]（判定规则 R2 自证闭环：列+=患者左）
  A7 镜像敏感（v1.2.1 增补）：叶瓣双在场 + 入口质心最近顶点 ≤3mm 且符号同侧 + cavity 均值窗
     [−6,−0.5]——实证 7 断言对 x→−x 反射全盲（A3 均值为镜像不变量），A7 的距离锚与均值窗
     是鉴别子（实格 1.45/0.76mm、−2.97；镜像 5.70mm、+2.97 必 FAIL）
"""
import sys, os, re, json
sys.stdout.reconfigure(encoding="utf-8")

SHARE = r"%DATA_ROOT%\项目\P0-鼻塞设计工具\阶段5-交互查看器"
RES = r"%DATA_ROOT%\项目\P0-鼻塞设计工具\阶段2-CFD算例包\结果"
PIPE = os.path.dirname(os.path.abspath(__file__))

ok_all = True
def check(name, cond, detail):
    global ok_all
    ok_all = ok_all and bool(cond)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {detail}")

# ---- CENTER：从 step5 源码解析（不 import，避免触发整个导出流程）----
src = open(os.path.join(PIPE, "step5_export_viewer_data.py"), encoding="utf-8").read()
mC = re.search(r"CENTER\s*=\s*np\.array\(\[\s*([-\d.,\s]+?)\s*\]\)", src)
CENTER = [float(x) for x in mC.group(1).split(",")]
print(f"CENTER (step5 源码解析) = {CENTER}")

# ---- v5C（Run-B 等压法）metrics ----
m5C = json.load(open(os.path.join(RES, "P0-result-pA-v5C", "后处理", "metrics.json"), encoding="utf-8"))
mL_cx = m5C["patches"]["inletL"]["face_centre_mm"][0]
mR_cx = m5C["patches"]["inletR"]["face_centre_mm"][0]
wL = mL_cx - CENTER[0]
wR = mR_cx - CENTER[0]
print(f"inletL face_centre_x={mL_cx:.2f} -> viewer world_x={wL:+.2f}")
print(f"inletR face_centre_x={mR_cx:.2f} -> viewer world_x={wR:+.2f}")

print("\n== A1/A2 patch 质心投影（决定性比对）==")
check("A1 inletL 落 x<0 半区（=患者右，R2）", wL < 0, f"wL={wL:+.2f}")
check("A2 inletR 落 x>0 半区（=患者左，R2）", wR > 0, f"wR={wR:+.2f}")
check("A1b inletL 面积=小口侧(95.3mm²)", abs(m5C['patches']['inletL']['area_mm2'] - 95.34) < 0.5,
      f"area={m5C['patches']['inletL']['area_mm2']:.2f} (占双侧 {100*m5C['patches']['inletL']['area_mm2']/(m5C['patches']['inletL']['area_mm2']+m5C['patches']['inletR']['area_mm2']):.1f}%)")

# ---- A3 airwayMesh 顶点均值（viewer_data.js）----
js = open(os.path.join(SHARE, "viewer_data.js"), encoding="utf-8").read()
start = js.index("{")
data, _ = json.JSONDecoder().raw_decode(js[start:])
pos = data["airwayMesh"]["positions"]
n = len(pos) // 3
mean_x = sum(pos[0::3]) / n
mean_y = sum(pos[1::3]) / n
mean_z = sum(pos[2::3]) / n
print("\n== A3 CENTER 同帧自证 ==")
check("A3 airwayMesh 顶点均值 ≈ 0（±0.5mm）",
      max(abs(mean_x), abs(mean_y), abs(mean_z)) < 0.5,
      f"mean=({mean_x:+.3f},{mean_y:+.3f},{mean_z:+.3f}), n_verts={n}")

# ---- A4/A5 439 与 1262 的数据源 ----
m5 = json.load(open(os.path.join(RES, "P0-result-pA-v5", "后处理", "metrics.json"), encoding="utf-8"))
fsL = m5C["totals"]["flow_share_L_pct"]
meta_split = data["meta"]["metrics"]["split_L_pct"]
vol = open(os.path.join(SHARE, "volume_data.js"), encoding="utf-8").read()
mv = re.search(r'"metrics_deltaP":\s*\{[^}]*?"dP_L_Pa":\s*([\d.]+),\s*"dP_R_Pa":\s*([\d.]+)', vol)
vdL, vdR = float(mv.group(1)), float(mv.group(2))
print("\n== A4/A5 面板两行数据源 ==")
check("A4 439 行 51.9 = v5C flow_share_L_pct（Run-B 等压法）",
      abs(meta_split - round(fsL, 1)) < 0.051 and abs(fsL - 51.867) < 0.01,
      f"meta.split_L_pct={meta_split} vs v5C {fsL:.3f}")
check("A5 1262 行 13.99/21.30 = v5（Run-A）dP_L/dP_R，与 439 不同源",
      abs(vdL - m5["totals"]["dP_L_Pa"]) < 0.02 and abs(vdR - m5["totals"]["dP_R_Pa"]) < 0.02,
      f"volume_data {vdL}/{vdR} vs v5 {m5['totals']['dP_L_Pa']:.3f}/{m5['totals']['dP_R_Pa']:.3f}（v5C 同名值 {m5C['totals']['dP_L_Pa']:.2f}/{m5C['totals']['dP_R_Pa']:.2f}）")
print("    注：13.99 为 13.9845 的历史转写显示值（2dp 应为 13.98，+0.01 舍入痕迹）——口径归属不受影响，")
print("    Y1 翻转时保留 13.99 以与环节②/诊断报告3/单文件存档一致，不改数。")

# ---- A6 DICOM IOP 全量实测（规则 R2 自证：列+ = 患者坐标 +x = 患者左）----
import glob as _glob
_D = os.environ.get("P0_DICOM_DIR", "./dicom")
_f0 = sorted(_glob.glob(os.path.join(_D, "*.dcm")))
_bad_iop = 0
if _f0:
    import pydicom
    for _f in _f0:
        try:
            _iop = [int(round(float(x))) for x in pydicom.dcmread(_f, stop_before_pixels=True).ImageOrientationPatient]
        except Exception:
            _bad_iop += 1
            continue
        if _iop != [1, 0, 0, 0, 1, 0]:
            _bad_iop += 1
print("\n== A6 DICOM IOP 全层实测 ==")
check("A6 IOP=[1,0,0,0,1,-0] 全 394 层逐层一致（列+=患者左，R2 自证）",
      len(_f0) == 394 and _bad_iop == 0, f"n={len(_f0)} 层，不一致/读取失败 {_bad_iop} 层")

# ---- A7 镜像敏感检测（v1.2.1 增补：7 断言对 x→−x 反射全盲之实证补救）----
print("\n== A7 镜像敏感（叶瓣 + 入口距离锚 + 符号 + 腔体均值窗）==")
import math as _math
pos3 = data["airwayMesh"]["positions"]
vx_all = pos3[0::3]
n_neg = sum(1 for x in vx_all if x < 0)
cavx = data["airwayCavity"]["positions"][0::3]
cav_mean = sum(cavx) / len(cavx)
P_Lw = [m5C["patches"]["inletL"]["face_centre_mm"][i] - CENTER[i] for i in range(3)]
P_Rw = [m5C["patches"]["inletR"]["face_centre_mm"][i] - CENTER[i] for i in range(3)]
def _near(q):
    bd, bx = 1e18, None
    for i in range(0, len(pos3), 3):
        dx = pos3[i] - q[0]; dy = pos3[i+1] - q[1]; dz = pos3[i+2] - q[2]
        d2 = dx*dx + dy*dy + dz*dz
        if d2 < bd:
            bd, bx = d2, pos3[i]
    return _math.sqrt(bd), bx
dL, xL = _near(P_Lw)
dR, xR = _near(P_Rw)
lobes = 0 < n_neg < len(vx_all)
dist_ok = dL <= 3.0 and dR <= 3.0
sign_ok = ((xL < 0) == (P_Lw[0] < 0)) and ((xR < 0) == (P_Rw[0] < 0))
cav_ok = -6.0 <= cav_mean <= -0.5
check("A7 叶瓣双在场+入口距离锚≤3mm+符号同侧+cavity均值窗[−6,−0.5]（镜像必 FAIL）",
      lobes and dist_ok and sign_ok and cav_ok,
      f"叶瓣 x<0 {n_neg}/{len(vx_all)}；d(P_L)={dL:.2f}mm d(P_R)={dR:.2f}mm（镜像时 P_L→5.70mm）；cavity均值={cav_mean:+.2f}（镜像+2.97）")

print("\n== 结论 ==")
if ok_all:
    print("全部 PASS ⇒ step1/step2 的 'L' 命名块（低列）物理上=患者右半气道。")
    print(f"⇒ Y1 翻转方向成立：439 行应显示 'R {fsL:.1f}% / L {100-fsL:.1f}%'（患者右拿 {fsL:.1f}% 通气）。")
    print("⇒ 口径：v5C 等压法实测通气分配（该侧开口面积仅约39%）；1262 行 13.99/21.30 属 Run-A 面积分流口径。")
    sys.exit(0)
else:
    print("存在 FAIL ⇒ Y1 禁止施工，回指挥官复核。")
    sys.exit(1)
