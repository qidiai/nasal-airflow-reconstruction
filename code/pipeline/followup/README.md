# M4 · 随访 diff 引擎（followup/）

> 任务书：M4「成像工作室·患者面」R2。编码手：deepseek-v4-pro-222。
> 方法论继承 M1 轨 B 的 **F-15 排查报告**：先配准，再做几何差（体积/截面/顶点集），最后才看指标差。

## 1. 流水线

```
两份分析产物 (A, B)
   │
   ├─ ① CT/几何配准      cKDTree + 截尾 ICP + SVD 刚体配准（无缩放）
   │                      记录 RMS / 中位 / P95 / max / 1mm 内点比例
   ├─ ② 几何差
   │     ├─ STL 级：水密(trimesh) / 体积 / 表面积 / 逐层截面 / 顶点集差集
   │     └─ polyMesh 级：单元/点/面/patch / 散度定理单元体积 / 层均截面积
   ├─ ③ 指标差            ΔP / 分侧压降 / 分流 / U_max / WSS / 容积 / 网格
   └─ ④ 病程结论卡        “较上次：左鼻孔最小截面 +1.53 mm²（+102.9%）…”
```

配准是前置硬骨头：T1/T2 两次 CT 坐标系不同。本引擎先用 cKDTree 最近邻 +
10% 截尾 ICP + SVD 估计刚体变换；**不估计缩放/形变**，并在输出里记录精度。
t25-ma 的 0.357 mm 先例只作为方法参照，本引擎不假设每次都能达到该精度。

## 2. 快速开始

```powershell
# 合成对照自测（synth-001 vs synth-005）
..\.venv\Scripts\python.exe pipeline\followup\selftest_synth.py

# 任意一对病例
..\.venv\Scripts\python.exe pipeline\followup\run_diff.py ^
  --a pipeline\out\synth\synth-001 ^
  --b pipeline\out\synth\synth-005 ^
  --label-a synth-001 --label-b synth-005 ^
  --out pipeline\followup\out\synth-001-vs-005

# 真实归档病例（pA / demoA 等）
..\.venv\Scripts\python.exe pipeline\followup\run_diff.py ^
  --a pipeline\out\结果\P0-result-pA-v1 ^
  --b pipeline\out\结果\P0-result-demoA-v1 ^
  --label-a pA --label-b demoA ^
  --out pipeline\followup\out\pA-vs-demoA
```

## 3. 输入布局

`find_stl()` 依次查找：

1. `<case>/geometry.stl`
2. `<case>/step1/airway_*.stl`

`find_mesh()` 依次查找：

1. `<case>/case/constant/polyMesh`
2. `<case>/constant/polyMesh`
3. `<case>/step2/P0-OF-case-*-v1/constant/polyMesh`

指标文件依次查找：

1. `<case>/metrics.json`
2. `<case>/后处理/metrics.json`
3. `<case>/cfd/validate_solve.json`

可用 `--stl-a/--stl-b/--mesh-a/--mesh-b` 显式覆盖。

## 4. 输出

| 文件 | 内容 |
|---|---|
| `diff.json` | 完整机读结果：配准矩阵与精度、STL/polyMesh 几何差、指标差、结论卡 |
| `diff.md` | 人读报告：结论卡、配准精度、指标表、几何差表、方法与边界 |
| `selftest.json` | 自测断言逐条结果（仅自测） |
| `selftest.md` | 自测人读记录（仅自测） |

### 4.1 随库分发的证据副本（`examples/`）

`followup/out/` 被仓库根 `.gitignore` 的 `**/out/` 规则排除，无法随仓库分发。
因此把自测这一轮的结论卡与逐条断言复制到 `followup/examples/`：

| 文件 | 体积 | 内容 |
|---|---|---|
| `examples/diff.json` | 28,737 B | synth-001 vs synth-005 完整机读差异（配准/几何/指标/结论卡） |
| `examples/diff.md` | 4,316 B | 同一轮的人读报告 |
| `examples/selftest.md` | 1,720 B | 六条方向性断言的 PASS 记录与总判定 |

重建命令（在仓库 `code/` 目录下）：

```powershell
# ① 重新生成差异结果到 out/
..\.venv\Scripts\python.exe pipeline\followup\run_diff.py ^
  --a pipeline\out\synth\synth-001 --b pipeline\out\synth\synth-005 ^
  --label-a synth-001 --label-b synth-005 ^
  --out pipeline\followup\out\synth-001-vs-005

# ② 重新生成自测记录（含 selftest.md）
..\.venv\Scripts\python.exe pipeline\followup\selftest_synth.py

# ③ 覆盖证据副本
Copy-Item pipeline\followup\out\synth-001-vs-005\diff.json,pipeline\followup\out\synth-001-vs-005\diff.md,pipeline\followup\out\selftest-synth-001-vs-005\selftest.md pipeline\followup\examples\ -Force
```

`examples/` 只放人读结论与机读结果，不放患者原始几何或网格。

## 5. 自测结果（2026-10-19）

对照：`synth-001`（左鼻孔 a_min 1.5 mm²）→ `synth-005`（a_min 4.0 mm²），
其余设计参数相同或由 seed 决定。

| # | 断言 | 结果 | 实测 |
|---|---|---|---|
| 1 | 左鼻孔最小截面增大 | PASS | 1.491 → 3.025 mm² |
| 2 | 左侧流量份额增大 | PASS | 3.604% → 10.256% |
| 3 | 左侧压降下降 | PASS | 303.282 → 198.267 Pa |
| 4 | 气道容积基本不变 | PASS | 105.000 → 105.000 cm³（+0.000%） |
| 5 | 配准 RMS < 2 mm | PASS | RMS 1.108 mm；中位 0.460 mm；P95 2.615 mm |
| 6 | 顶点差定位到局部 | PASS | max 3.815 mm；中位 0.460 mm；>2 mm 顶点 9.40% |

**总判定：PASS**。完整记录见 `out/selftest-synth-001-vs-005/`。

### 未作方向性断言的行（如实）

- **总压降 ΔP**：62.040 → 106.690 Pa（+44.650，+71.97%），与左侧压降方向相反。
- **右侧压降**：53.022 → 96.224 Pa（+43.202，+81.48%）。
- 原因：Run-A 定流量按**面积**分配，左鼻孔变大后左侧分到更多流量、右侧分到更少；
  但右侧压降仍上升，说明右路几何也随 seed 改变，且两例均为 1500 步平台
  （未达 residualControl 1e-4）。因此总压降/右侧压降**不能**作为左鼻孔参数的
  单向响应，不能据此做剂量-反应结论。
- 这正是 F-15 的教训：几何差与指标差必须分开看，指标不敏感/方向相反时要回到几何与口径。

## 6. 文件清单

| 文件 | 作用 |
|---|---|
| `polymesh.py` | 清洁室 OpenFOAM ascii polyMesh 读取器（points/faces/owner/neighbour/boundary）+ 散度定理单元体积 + 层均截面积 |
| `registration.py` | cKDTree + 截尾 ICP + SVD 刚体配准；精度记录 |
| `geometry.py` | STL 级（trimesh 水密/体积/切片/顶点差集）与 polyMesh 级几何差 |
| `metrics.py` | 指标提取（synth / pA-demoA / 通用）与差表 |
| `conclusion.py` | 病程结论卡 + 患者语言随访句 + 注意事项 |
| `run_diff.py` | CLI：配准 → 几何差 → 指标差 → 结论卡 |
| `selftest_synth.py` | synth-001 vs synth-005 方向一致性自测 |

## 7. 许可与依赖

- 水密判决与 STL 体积：**trimesh（MIT）**；不使用被禁的 Sutura（PolyForm Noncommercial）。
- 配准：scipy `cKDTree`（BSD）；数值：numpy（BSD）。
- 未引入 GPL/NC 依赖；polyMesh 读取器为自写清洁室实现。

## 8. 已知限制

1. **刚体配准**：不处理缩放、非刚性形变或不同重建网格的局部膨胀；RMS 会如实暴露。
2. **不同体素/网格**：顶点差与层均曲线只作定位线索，不能直接当毫米级病程结论。
3. **STL 与 polyMesh 体积口径不同**：前者是 marching-cubes 表面体积，后者是单元体积和；
   synth-001 两者分别为 105.000 / 106.452 cm³（栅格化比 1.013），报告分别列出。
4. **指标差含收敛噪声**：本例两例均为 1500 步平台；真实随访应优先使用收敛病例，
   或在结论卡中标注平台状态。
5. **Run-B 等压口径未纳入本引擎**：当前指标差异基于 Run-A 定流量；等压自然分流是下一步。
