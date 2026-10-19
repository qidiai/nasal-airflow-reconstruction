"""Single-file HTML report renderer.

The output is deliberately dependency-free: CSS and the tiny print helper are
inline, every image is a base64 ``data:`` URI, and there are no remote fonts or
scripts.  A report can be opened by double-clicking the file or sent through
WeChat without a server.
"""

from __future__ import annotations

import base64
import html
import json
from datetime import datetime
from pathlib import Path

from .cases import CaseBundle
from .wording import assert_patient_safe, assert_report_safe, compose_patient_conclusion


def _fmt(x, digits: int = 1) -> str:
    if x is None:
        return "—"
    try:
        v = float(x)
    except (TypeError, ValueError):
        return str(x)
    if v != v:  # NaN
        return "—"
    return f"{v:.{digits}f}"


def _pct(x) -> str:
    return "—" if x is None else f"{float(x):.1f}%"


def _img(path: str | Path) -> str:
    p = Path(path)
    mime = "image/png"
    if p.suffix.lower() in (".jpg", ".jpeg"):
        mime = "image/jpeg"
    data = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def _figure(bundle: CaseBundle, key: str, alt: str) -> str:
    path = bundle.figures.get(key)
    if not path or not Path(path).is_file():
        return ""
    cap = bundle.figure_captions.get(key, "")
    return (
        '<figure class="evidence">'
        f'<img src="{_img(path)}" alt="{html.escape(alt)}">'
        f"<figcaption>{html.escape(cap)}</figcaption>"
        "</figure>"
    )


def _gap(text: str) -> str:
    return (
        '<div class="gap"><div class="gap-title">证据缺口</div>'
        f"<p>{html.escape(text)}</p></div>"
    )


def _card(
    *,
    kicker: str,
    value: str,
    unit: str,
    sub: str,
    evidence_html: str,
    badge: str | None = None,
    extra: str = "",
) -> str:
    badge_html = f'<span class="badge">{html.escape(badge)}</span>' if badge else ""
    return (
        '<article class="metric-card">'
        f'<div class="kicker">{html.escape(kicker)} {badge_html}</div>'
        f'<div class="value">{html.escape(value)} <span class="unit">{html.escape(unit)}</span></div>'
        f'<div class="sub">{html.escape(sub)}</div>'
        f"{extra}"
        f"{evidence_html}"
        "</article>"
    )


def _status_badge(bundle: CaseBundle) -> str:
    m = bundle.metrics
    if m.get("converged") is True:
        return "已收敛"
    if m.get("converged") is False:
        return "平台 · 未达 1e-4"
    return "未记录收敛判据"


def _method_rows(bundle: CaseBundle) -> list[tuple[str, str]]:
    m = bundle.metrics
    g = bundle.geometry
    rows = [
        ("算例类型", {"patient": "真实患者归档", "patient_demo": "官方演示病例", "synthetic": "合成数据（非真人）"}.get(bundle.case_kind, bundle.case_kind)),
        ("数据来源", bundle.data_source),
        ("求解口径", "层流 · 定常 · 不可压缩；Run-A 定流量 15 L/min"),
        ("物性", "rho = 1.2 kg/m³；nu = 1.8e-5 m²/s"),
        ("入口边界", "左右鼻孔流量入口；出口 fixedValue p = 0；壁面无滑移"),
        ("网格单元", f"{g.get('cells'):,}" if g.get("cells") else "—"),
        ("体素尺度", " × ".join(f"{v:g}" for v in g["voxel_mm"]) + " mm" if g.get("voxel_mm") else "—"),
        ("迭代步数", f"{m.get('iterations')}" if m.get("iterations") is not None else "—"),
        ("收敛状态", _status_badge(bundle)),
        ("报告引擎", "M4 report engine v1 · 单文件内嵌 CSS/JS/图"),
    ]
    return rows


def render_html(bundle: CaseBundle, out_path: str | Path) -> Path:
    m = bundle.metrics
    g = bundle.geometry
    conclusion = compose_patient_conclusion(
        case_kind=bundle.case_kind,
        split_l=m.get("split_L_pct"),
        split_r=m.get("split_R_pct"),
        dp_pa=m.get("dP_Pa"),
        min_area_mm2=m.get("min_area_mm2"),
        min_area_scope=m.get("min_area_scope"),
        converged=m.get("converged"),
        iterations=m.get("iterations"),
        has_reference_range=False,
    )
    assert_patient_safe(conclusion)

    # ---- metric cards -------------------------------------------------
    conv_evidence = _figure(bundle, "convergence", "收敛曲线")
    if not conv_evidence:
        conv_evidence = _gap("本例未归档求解日志或残差序列，无法绘制收敛曲线；收敛状态以指标文件记录为准。")
    dp_extra = (
        f'<div class="mini">迭代 {m.get("iterations", "—")} 步 · '
        f'末步 p 初始残差 {_fmt(bundle.residuals.get("last"), 3)}</div>'
    )
    card_dp = _card(
        kicker="呼吸阻力指标",
        value=_fmt(m.get("dP_Pa"), 1),
        unit="Pa",
        sub="15 L/min 定流量 · 两侧入口面平均静压差",
        evidence_html=conv_evidence,
        badge=_status_badge(bundle),
        extra=dp_extra,
    )

    split_evidence = _figure(bundle, "split", "两侧流量分配")
    if not split_evidence:
        split_evidence = _gap("缺少左右两侧流量数值，无法绘制分流条图。")
    card_split = _card(
        kicker="气流分配",
        value=f"{_pct(m.get('split_L_pct'))} / {_pct(m.get('split_R_pct'))}",
        unit="左 / 右",
        sub=f"总流量 {_fmt(m.get('Q_total_L_min'), 1)} L/min"
        + (f"；左 {_fmt(m.get('Q_L_L_min'), 2)}、右 {_fmt(m.get('Q_R_L_min'), 2)} L/min" if m.get("Q_L_L_min") is not None else ""),
        evidence_html=split_evidence,
    )

    area_evidence = _figure(bundle, "area", "截面积曲线")
    if not area_evidence:
        area_evidence = _gap("未提供逐层截面积曲线，无法展示最小截面的位置证据。")
    area_extra = ""
    if m.get("left_nostril_area_mm2") is not None:
        area_extra = (
            f'<div class="mini">左鼻孔 {_fmt(m.get("left_nostril_area_mm2"), 2)} mm² · '
            f'右鼻孔 {_fmt(m.get("right_nostril_area_mm2"), 2)} mm²</div>'
        )
    scope_label = {
        "axial_total": "鼻孔平面轴向总截面",
        "left_nostril": "左鼻孔截面",
        "main_airway": "主气道轴向切片",
    }.get(m.get("min_area_scope"), "轴向切片")
    z_note = f" · z = {_fmt(m.get('min_area_z_mm'), 1)} mm" if m.get("min_area_z_mm") is not None else ""
    layer_note = f" · 层 {m.get('min_area_layer')}" if m.get("min_area_layer") is not None else ""
    card_area = _card(
        kicker="最小截面",
        value=_fmt(m.get("min_area_mm2"), 2),
        unit="mm²",
        sub=f"{scope_label}{z_note}{layer_note}",
        evidence_html=area_evidence,
        extra=area_extra,
    )

    geom_evidence = _figure(bundle, "qc", "step1 QC 图") or _figure(bundle, "geometry", "几何投影")
    if not geom_evidence:
        geom_evidence = _gap("缺少几何 QC 图或 STL，无法展示气道轮廓。")
    card_volume = _card(
        kicker="气道容积",
        value=_fmt(m.get("volume_cm3"), 1),
        unit="cm³",
        sub="step1 分割 / STL 口径；不是肺功能测量",
        evidence_html=geom_evidence,
    )

    vel_evidence = _figure(bundle, "velocity", "速度切片")
    if not vel_evidence:
        vel_evidence = _gap("本例未归档 VTU 场文件，无法绘制速度切片；卡片数值来自指标文件。")
    card_velocity = _card(
        kicker="最大流速",
        value=_fmt(m.get("U_max_m_s"), 2),
        unit="m/s",
        sub=m.get("U_max_note") or "全场单元/点最大值 · 用于定位高速区",
        evidence_html=vel_evidence,
    )

    wss_evidence = _figure(bundle, "wss_hist", "WSS 分布")
    if not wss_evidence:
        wss_evidence = _gap("本例只保留了 WSS 汇总值，未保留壁面分布图；不能用汇总值反推分布。")
    card_wss = _card(
        kicker="壁面剪切力",
        value=_fmt(m.get("wss_mean_Pa"), 4),
        unit="Pa · 均值",
        sub=f"高值（95% 面覆盖）{_fmt(m.get('wss_high_Pa'), 4)} Pa · 最大 {_fmt(m.get('wss_max_Pa'), 4)} Pa",
        evidence_html=wss_evidence,
    )

    outlet_evidence = _figure(bundle, "outlet_hist", "出口速度分布")
    if not outlet_evidence:
        outlet_evidence = _gap("本例未归档出口面 VTP，无法绘制出口速度分布直方图。")
    card_outlet = _card(
        kicker="出口速度",
        value=_fmt(m.get("outlet_area_mm2"), 1),
        unit="mm² · 出口面积",
        sub="出口面速度分布见右图；面积与流量共同决定出口平均速度",
        evidence_html=outlet_evidence,
    )

    pressure_evidence = _figure(bundle, "pressure", "压力切片")
    if not pressure_evidence:
        pressure_evidence = _gap("本例未归档 VTU 场文件，无法绘制压力切片。")
    card_pressure = _card(
        kicker="压力场证据",
        value=_fmt(m.get("dP_L_Pa"), 1),
        unit="Pa · 左侧入口",
        sub=f"右侧入口 {_fmt(m.get('dP_R_Pa'), 1)} Pa；切片显示压力在入口与出口之间的分布",
        evidence_html=pressure_evidence,
    )

    cards = [card_dp, card_split, card_area, card_volume, card_velocity, card_wss, card_outlet, card_pressure]

    # ---- evidence gaps list ------------------------------------------
    gaps = []
    for key, label, reason in [
        ("convergence", "收敛曲线", "未归档求解日志/残差序列"),
        ("velocity", "速度切片", "未归档 VTU 场文件"),
        ("pressure", "压力切片", "未归档 VTU 场文件"),
        ("outlet_hist", "出口速度直方图", "未归档出口面 VTP"),
        ("wss_hist", "WSS 分布图", "只保留 WSS 汇总值"),
        ("geometry", "几何投影", "未提供 STL（QC 图可能仍可用）"),
    ]:
        if key not in bundle.figures and not (key == "geometry" and "qc" in bundle.figures):
            gaps.append(f"{label}：{reason}。")
    if not gaps:
        gaps.append("本例的所有报告卡片均有对应的数据图或 QC 图；未发现证据缺口。")

    # ---- method / provenance ------------------------------------------
    method_rows = "".join(
        f"<tr><th>{html.escape(k)}</th><td>{html.escape(str(v))}</td></tr>" for k, v in _method_rows(bundle)
    )
    prov_rows = "".join(
        f"<tr><td><code>{html.escape(p['path'])}</code></td><td><code>{html.escape(p['md5'][:16])}</code></td><td>{html.escape(p['note'])}</td></tr>"
        for p in bundle.provenance
    )
    assumptions = "".join(f"<li>{html.escape(a)}</li>" for a in bundle.assumptions)
    notes = "".join(f"<li>{html.escape(n)}</li>" for n in bundle.notes)
    gap_items = "".join(f"<li>{html.escape(g)}</li>" for g in gaps)

    css = """
:root{color-scheme:light;--ink:#1f2d3d;--muted:#61758a;--line:#dbe4ee;--bg:#f5f8fb;--card:#ffffff;--mint:#2a9d8f;--orange:#e07b39;--blue:#3d6fb4;--red:#c0392b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:system-ui,-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;line-height:1.65}
.wrap{max-width:1080px;margin:0 auto;padding:24px 18px 48px}
header.top{background:linear-gradient(135deg,#12303a,#1d4a4a);color:#eaf7f4;border-radius:16px;padding:26px 28px;margin-bottom:18px}
header.top .kicker{font-size:12px;letter-spacing:.12em;text-transform:uppercase;opacity:.8}
header.top h1{margin:6px 0 8px;font-size:26px;line-height:1.3}
header.top .meta{font-size:13px;opacity:.86;word-break:break-all}
header.top button{margin-top:14px;border:1px solid #ffffff66;background:#ffffff14;color:#fff;border-radius:999px;padding:8px 16px;font:600 13px inherit;cursor:pointer}
.patient-card{background:linear-gradient(135deg,#e9f7f2,#f2fbf8);border:1px solid #bfe6da;border-radius:16px;padding:22px 24px;margin-bottom:18px}
.patient-card .label{font-size:12px;letter-spacing:.1em;color:var(--mint);font-weight:700;margin-bottom:6px}
.patient-card p{margin:0;font-size:17px;line-height:1.8}
.patient-card .foot{margin-top:10px;font-size:12px;color:var(--muted)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:16px}
.metric-card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px;box-shadow:0 1px 2px #1f2d3d0a}
.metric-card .kicker{font-size:12px;color:var(--muted);letter-spacing:.06em;font-weight:700}
.metric-card .value{font-size:30px;font-weight:800;margin:4px 0 2px;color:var(--ink)}
.metric-card .unit{font-size:14px;font-weight:600;color:var(--muted)}
.metric-card .sub{font-size:13px;color:var(--muted);min-height:2.2em}
.metric-card .mini{font-size:12px;color:var(--muted);margin-top:4px}
.badge{display:inline-block;margin-left:8px;padding:1px 8px;border-radius:999px;background:#eef2f6;color:var(--muted);font-size:11px;font-weight:600;vertical-align:middle}
figure.evidence{margin:12px 0 0}
figure.evidence img{width:100%;height:auto;border:1px solid var(--line);border-radius:10px;background:#fff}
figure.evidence figcaption{font-size:12px;color:var(--muted);margin-top:6px}
.gap{margin-top:12px;border:1px dashed #e3b27a;background:#fff8ef;border-radius:10px;padding:12px 14px}
.gap-title{font-size:12px;font-weight:800;color:var(--orange);letter-spacing:.06em}
.gap p{margin:4px 0 0;font-size:13px;color:#7a5a35}
section.block{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin-top:18px}
section.block h2{margin:0 0 12px;font-size:18px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;vertical-align:top;padding:8px 10px;border-bottom:1px solid var(--line);word-break:break-word}
th{width:26%;color:var(--muted);font-weight:700}
code{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px;background:#f1f5f9;padding:1px 4px;border-radius:4px}
ul{margin:6px 0 0 20px;padding:0}
li{margin:5px 0}
footer.disclaimer{margin-top:22px;border-radius:14px;padding:18px 20px;background:#fff4f2;border:1px solid #f2c7c1;color:#7a2f26;font-size:13px}
footer.disclaimer strong{display:block;font-size:15px;margin-bottom:6px}
@media print{body{background:#fff}.wrap{max-width:none;padding:0}header.top{background:#fff;color:#000;border:1px solid #ccc}.metric-card,section.block,footer.disclaimer{break-inside:avoid;box-shadow:none}header.top button{display:none}}
"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    title = f"{bundle.label} · 呼吸说明书"
    doc = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>{css}</style>
</head>
<body>
<div class="wrap">
<header class="top">
  <div class="kicker">呼吸说明书 · 单文件报告 · 离线可用</div>
  <h1>{html.escape(bundle.label)}</h1>
  <div class="meta">生成时间 {now} · 数据来源 {html.escape(bundle.data_source)} · 本文件不含外部依赖</div>
  <button onclick="window.print()">打印 / 存为 PDF</button>
</header>

<section class="patient-card">
  <div class="label">一句话结论（患者语言）</div>
  <p>{html.escape(conclusion)}</p>
  <div class="foot">本段按患者措辞白名单生成：不做人群对照，不作诊断或治疗建议。</div>
</section>

<section class="grid">
{''.join(cards)}
</section>

<section class="block">
  <h2>方法与口径</h2>
  <table>{method_rows}</table>
</section>

<section class="block">
  <h2>关键假设</h2>
  <ul>{assumptions}</ul>
</section>

<section class="block">
  <h2>证据缺口与已知限制</h2>
  <ul>{gap_items}</ul>
</section>

<section class="block">
  <h2>本报告的说明</h2>
  <ul>{notes}</ul>
</section>

<section class="block">
  <h2>数据来源与校验</h2>
  <table>
    <thead><tr><th>文件</th><th>md5（前 16 位）</th><th>用途</th></tr></thead>
    <tbody>{prov_rows}</tbody>
  </table>
</section>

<footer class="disclaimer">
  <strong>重要说明</strong>
  <ul>
    <li>本报告不是诊断结论，不能替代医生阅片与临床检查。</li>
    <li>报告中的数值来自本次影像分析与气流模拟，存在建模假设与数值误差；不能单独作为治疗决策依据。</li>
    <li>如有不适、症状变化或需要治疗决策，请咨询耳鼻喉科医生。</li>
    <li>报告在本机生成，不上传云端；分享前请确认接收方可以接触本次分析数据。</li>
  </ul>
</footer>
</div>
</body>
</html>
"""
    assert_report_safe(doc)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    return out
