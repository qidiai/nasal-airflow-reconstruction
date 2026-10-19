# M4 · 单文件 HTML 报告引擎（report/）

> 任务书：M4「成像工作室·患者面」R1。编码手：deepseek-v4-pro-222。
> 纪律：禁 commit / 禁推送；只写 `pipeline/report/`（本目录）+ R3 的 `demo.html` 小改 + 看板。

## 1. 目标

把一次分析产物变成**患者自己能看懂、医生能直接打开**的呼吸说明书：

- **单文件 HTML**：CSS/JS/图片全部内嵌，无外部依赖，本地双击即开，可微信直传。
- **每个数字旁挂证据图**：ΔP 旁是收敛曲线；分流比旁是左右流量条；最小截面旁是沿轴截面积曲线；最大流速旁是 VTU 切片；WSS 旁是壁面分布图。
- **患者语言层**：一句人话结论，禁人群分位表述，不作诊断/治疗建议。
- 固定尾部：非诊断、咨询医生、数据不出本地。

## 2. 快速开始

在仓库 `code/` 目录下：

```powershell
# 三例验收样例（pA / demoA / synth-001）
..\.venv\Scripts\python.exe pipeline\report\build_report.py --cases pA demoA synth-001

# 只跑一例
..\.venv\Scripts\python.exe pipeline\report\build_report.py --cases synth-001

# 任意 metrics.json（通用输入）
..\.venv\Scripts\python.exe pipeline\report\build_report.py ^
  --metrics path\to\metrics.json --label "我的病例" ^
  --area-csv path\to\area.csv --vtu path\to\internal.vtu ^
  --outlet-vtp path\to\outlet.vtp --walls-vtp path\to\walls.vtp ^
  --qc-image path\to\qc.png

# 单文件自检（体积、内嵌、每卡有图、数字在场、措辞）
..\.venv\Scripts\python.exe pipeline\report\selfcheck.py pipeline\report\out\report-pA.html

# 措辞 grep 自检（全量报告）
..\.venv\Scripts\python.exe pipeline\report\check_wording.py
```

输出：

| 路径 | 说明 |
|---|---|
| `report/out/report-<case>.html` | 单文件报告（验收要求 <5 MB/例） |
| `report/out/build-manifest.json` | 本次构建清单：路径、体积、图片数、自检结果 |
| `report/figures/<case>/*.png` | 证据图底稿（可回收，HTML 已内嵌） |

### 2.1 随库分发的证据副本（`examples/`）

仓库根 `.gitignore` 的 `**/out/` 规则会把 `report/out/` 整体排除，运行产物不入库。
为了让评审**不重跑流水线**就能打开三份验收样例，另存一份证据副本到
`report/examples/`（引擎默认输出仍是 `report/out/`，两者内容一致）：

| 文件 | 体积 | 对应病例 |
|---|---|---|
| `examples/report-synth-001.html` | 210,008 B（205.1 KB） | synth-001（合成数据） |

副本由构建命令直接生成（在仓库 `code/` 目录下）：

```powershell
..\.venv\Scripts\python.exe pipeline\report\build_report.py ^
  --cases pA demoA synth-001 --out-dir pipeline\report\examples
```

> **Consent-ledger 边界（2026-10-19 M4 审计 C1 裁决）**：`examples/` 随库分发
> **仅 synth-001 一篇（100% 合成几何）**。患者算例（pA/demoA/demoB/pN-Lat/pN-Med）
> 的报告与渲染图含患者派生影像/几何（如 step1 QC 轴位图、患者几何场切片），
> 按 `code/data-governance/consent-ledger.md` L15/L62/L117"实图也禁"**不入库、
> 不发布、不进 demo.html 提交态载荷**，仅在本地授权展示。本地重新生成：
>
> ```powershell
> # 患者例报告（本地授权展示用，勿提交勿外传）
> ..\.venv\Scripts\python.exe pipeline\report\build_report.py --cases pA demoA
> # 患者例 demo.html 载荷（本地）
> ..\.venv\Scripts\python.exe pipeline\report\embed_demo_reports.py --cases pA,demoA,demoB,pN-Lat,pN-Med
> ```

同一条命令会把 `examples/build-manifest.json`（逐例体积、内嵌图数、七项自检结论）
一并写入，作为这一轮构建的可复核留痕。

## 3. 输入契约

### 3.1 必需：`metrics.json`

引擎接受仓库既有后处理指标的形状（`pipeline/out/结果/*/后处理/metrics.json` 或
`pipeline/out/synth/*/metrics.json`）：

| 字段 | 用途 | 缺失时 |
|---|---|---|
| `totals.dP_Pa` | ΔP 主数字 | 显示 “—” |
| `totals.dP_L_Pa` / `dP_R_Pa` | 分侧压降 | 显示 “—” |
| `totals.Q_inlet_total_L_min` | 总流量 | 显示 “—” |
| `totals.flow_share_L_pct` / `flow_share_R_pct` | 分流比 | 由 `patches.inletL/R.Q_L_min` 计算 |
| `totals.U_max_m_s` | 最大流速 | 显示 “—” |
| `wss.mean_Pa` / `p95_Pa` / `max_Pa` | 壁面剪切力 | 显示 “—” |
| `geometry.airway_volume_cm3` | 气道容积 | 显示 “—” |
| `geometry.min_axial_area_mm2` + `min_layer` / `min_z_mm` | 最小截面 | 显示 “—” |
| `residuals.n_iter` / `converged` / `p_init_first` / `p_init_last` | 收敛状态 | 显示 “未记录” |

### 3.2 可选证据

| 输入 | 生成的图 | 缺失时的行为 |
|---|---|---|
| 求解日志 / `p_init_series` | 收敛曲线 | 用首末残差柱图；再缺则“证据缺口” |
| `area_per_slice*.csv` 或 `geometry.stl` | 沿轴截面积曲线 | “证据缺口” |
| `internal.vtu` | 速度切片 + 压力切片 | “证据缺口” |
| `outlet.vtp` | 出口速度直方图 | “证据缺口” |
| `walls.vtp` | WSS 幅值分布 | “证据缺口” |
| `qc_*_mid.png` 或 STL | 几何/QC 图 | “证据缺口” |

**原则**：缺失的证据不补、不猜、不造；卡片里明确写“证据缺口”及原因。

## 4. 内置病例适配器

| case | 数据来源 | 证据完整度 |
|---|---|---|
| `pA` | `pipeline/out/结果/P0-result-pA-v1` | 收敛曲线、面积曲线、VTU 切片、出口直方图、WSS 分布、QC 图 |
| `demoA` | `pipeline/out/结果/P0-result-demoA-v1` | 同上（demoA 与 pA 是同一患者的别名，D2） |
| `synth-001` | `pipeline/out/synth/synth-001` | 首末残差、面积曲线（STL）、几何投影；无 VTU/日志 → 场图缺口 |
| `demoB` / `pN-Lat` / `pN-Med` | `pipeline/webapp/plus/viewer_plus_data_*.js` | 残差序列、面积曲线（前端数据包）、分流条；无 VTU → 场图缺口 |

> `demoB` / `pN-*` 适配器用于 R3 演示页的“下载报告”入口；它们只读取前端数据包，
> 不读取原始 DICOM。

## 5. 患者措辞白名单

任务书要求“白名单见 `docs/contracts/` 的患者措辞节”。**该节在当前仓库不存在**
（`pipeline/docs/contracts/` 只有数值契约、验证基线、M1 轨 A 看板），且
`docs/contracts/` 不在 M4 文件域。本引擎因此按已冻结的上游规则实现
`wording.py`：

- 规划 v2.3.2 §2.2：一句人话结论；**禁任何人群分位表述**；分位功能在基线建成前不实现。
- 审计 v2.1-GLM53 A2：患者文案用描述性语言；禁止词表 = 偏窄 / 狭窄 / 正常 / 异常 /
  健康人群分位对比 / 诊断 / 手术指征。
- 审计 v2.1-KIMI27 F-12：常模建成前，P85/P92 类对比不得出现在任何对外材料。

实现要点：

- 报告**全文**禁止 `分位 / 百分位 / percentile / P85 / P92 / P95`、`健康人群 / 正常人群 / 正常人 / 常人带 / 正常带`。
- 患者卡片额外禁止 `偏窄 / 狭窄 / 确诊 / 诊断为 / 手术指征` 等。
- 允许并使用的描述性措辞：`影像与气流模拟显示`、`两侧气流分配不完全对称`、
  `截面相对较小`、`气流更多从另一侧通过`、`与参考范围相比`（仅在确有参考范围时）、
  `这不是诊断结论，请咨询医生`。
- 没有人群参考范围时，明确写“本次未使用人群对照，报告只描述本例自身的模拟结果”。

自检：`check_wording.py` 对 `out/report-*.html` 全文 grep，0 命中才返回 0。

> 任务书示例中的“偏窄”没有采用：它在上游审计的禁止词表里。报告改用
> “截面相对较小 / 气流更多从另一侧通过”的描述性表述，既保留患者能懂的信息，
> 又不滑向诊断语义。

## 6. 已知限制（如实）

1. **`synth-001` 没有归档 VTU 与逐步求解日志**：速度/压力切片、出口速度直方图、
   WSS 分布图不可用；报告用“证据缺口”明确标注，收敛状态用首末残差柱图。
2. **`demoB` / `pN-*` 只有前端数据包**：原始 VTU 未随演示数据打包；场图同样以缺口标注。
3. **轴向截面积不垂直于中心线**：最小截面是轴向切片口径（step1 原 caveat），
   不是真正的鼻瓣垂直截面；报告在卡片与假设中明示。
4. **收敛口径**：pA/demoA/synth-001 均为 1500 步平台，未满足 residualControl
   （p/U 均 1e-4）；报告用“平台 · 未达 1e-4”徽标，不写成“已收敛”。
5. **数据边界（ consent-ledger 硬闸）**：患者算例的 QC/轴位图源自 step1 原始影像，
   属患者派生影像——**已从 git 历史与提交态彻底移除**（2026-10-19 M4 审计 C1 裁决），
   demo.html 提交态载荷仅保留 synth-001（`--cases` 参数可本地重建患者例载荷）。
   公开仓库只含 L1 层（代码/文档/聚合数值），引用 consent-ledger L15/L62/L117。
## 7. 文件清单

| 文件 | 作用 |
|---|---|
| `wording.py` | 患者措辞白名单、禁用词扫描、一句人话结论模板 |
| `figures.py` | 收敛/分流/面积/切片/出口/WSS/几何七类证据图 |
| `cases.py` | pA/demoA/synth-001/前端数据包适配器 + 通用 metrics 适配器 |
| `engine.py` | 单文件 HTML 渲染（内嵌 CSS/JS/base64 图） |
| `build_report.py` | CLI：构建 + 自检 + manifest |
| `selfcheck.py` | 体积/内嵌/每卡有图/数字在场/措辞检查 |
| `check_wording.py` | 全量报告措辞 grep 自检 |
