# L1 验证基线表 v1.0（M1 轨 A 交付）

> **定位**：自研求解器（M2）L1 门对拍的**唯一取值标准**。基线一律取**归档实证文件**的标准取值；任何注释值/界面值/历史值不得混入。
> **上游**：规划 v2.3.2 §0 #3（Kimi F-04：44.91 vs 45.63 双源 ~1.6% 吃掉 ±2% 容差）、#4（GLM F-06 同义反复）、§4 验证门控表。
> **归档根**：`F:\比赛项目\罕见无界黑客松\开源仓库\code\pipeline\out\`（下称 `out/`）。md5 均为 2026-10-17 实测。

---

## 0. D1 结论：44.9067 Pa 基线载体——**已定位（找到，非复算记录）**

按任务书要求逐个排查 `out/` 归档（metrics.json / case_stats / validate_solve / QC json / report），结论：

| 角色 | 载体文件 | 字段路径 | 值 | md5 |
|---|---|---|---|---|
| **主载体（全精度）** | `out\结果\P0-result-pB-v1\后处理\metrics.json` | `totals.dP_Pa` | **44.90667058007191**（标准取值 44.9067 = 四位小数圆整） | `c0bbb99f13dbb6d74628ad2799698dc5` |
| 辅证 1（报告口径） | `out\结果\P0-result-pB-v1\后处理\report.md` | §2 Pressure drop 表 `dP = p_in - p_out [Pa]` 行 | 44.9067（四位小数） | `96560f0b97835526092fcbd6b392b2fa` |
| 辅证 2（契约回填） | `out\postprocess\contract-pB-v1.json` | `metrics.dP_baseline_Pa` | 44.91（两位小数圆整） | `6ea9676722c3e70573eb2982484f611d` |

- **同源佐证**（同一 metrics.json 内）：`totals.p_inlet_Pa = 44.90667058007191`、`totals.p_outlet_Pa = 0.0`、`totals.Q_inlet_total_L_min = 15.000008576313505`；`patches.inletL.p_mean_Pa = 17.484478037697926`、`patches.inletR.p_mean_Pa = 69.67510255382906`。
- **圆整链自洽**：44.90667058007191 → 四位 44.9067 → 两位 44.91；契约文件 `contract-pB-v1.json` 的 44.91 与主载体一致（非 45.63）。
- **交叉验证方式**（M2/审计可独立复算，不依赖本表）：
  1. **公式重算法**：按 `out\结果\P0-result-pB-v1\后处理\report.md` §1/§2 记载的口径（`p_mean = rho·Σ_f(|U_f·n_f| p_f)/Σ_f|U_f·n_f|`，rho=1.2，p 为运动学压力），从归档 VTK 场 `out\结果\P0-result-pB-v1\VTK\P0-case-pB-v1_1500\{internal.vtu,boundary\inletL.vtp,boundary\inletR.vtp,boundary\outlet.vtp}` 重算入口质量加权压强 → 应得 44.9067 ± 数值噪声。
  2. **通量法旁证**：`out\结果\P0-result-pB-v1\allrun.log` 末步 surfaceFieldValue 通量（`sum(inletL) of phi = -1.17026e-04`、`sum(inletR) of phi = -1.32974e-04`）与 BC 输入逐位一致（流量闭合），排除"流量口径漂移导致 dP 不可比"。
  3. **先例模式**：`out\结果\核对脚本-T51C.py` 即"前端数字 vs 归档 metrics"逐项比对的既有范式（T51C 已对 demoA/demoB/pN 执行），pB 可按同法复跑。
- **诚实声明**：`后处理/metrics.json` 的**生成脚本不在本仓库**（`run_all.py` 注释明确"另需笔记本侧后处理脚本"按患者 A 既有口径生成，该脚本未归档）——载体文件本身在位且三源互证，但"从原始场一键重生成 metrics.json"的复现路径依赖上述公式重算法（交叉验证方式 1），M2 对拍 harness 应自带该重算，不得假设生成脚本可得。
- Kimi R-016"当轮 15+ 目录未定位到、可溯出处为前轮复算记录"的状态**已升级**：本轮在 `out/结果/P0-result-pB-v1/后处理/metrics.json` 定位到全精度载体。

---

## 1. L1 门基线表（容差 ±2% vs 归档标准取值；4/4 病例；判定=指挥官+审计官）

| # | 指标 | 基线值 | 载体文件 | 字段路径 | md5 |
|---|---|---|---|---|---|
| B1 | **pA ΔP（Run-A，15 L/min）** | **18.45 Pa**（全精度 18.445960544586182） | `out\结果\P0-result-pA-v1\后处理\metrics.json` | `totals.dP_Pa` | `49f7ee36caab14d6943f971ecc06c837` |
| B1' | pA ΔP 契约回填值 | 18.45 | `out\postprocess\contract-pA-v1.json` | `metrics.dP_baseline_Pa` | `a0b3ec4806920da6bcfe61004321f9e1` |
| B2 | **pB ΔP（Run-A，15 L/min）** | **44.9067 Pa**（全精度 44.90667058007191） | `out\结果\P0-result-pB-v1\后处理\metrics.json` | `totals.dP_Pa` | `c0bbb99f13dbb6d74628ad2799698dc5` |
| B2' | pB ΔP 契约回填值 | 44.91 | `out\postprocess\contract-pB-v1.json` | `metrics.dP_baseline_Pa` | `6ea9676722c3e70573eb2982484f611d` |
| B3 | **pA 分流比（Run-A）** | **39.0 : 61.0** | `out\postprocess\contract-pA-v1.json` | `metrics.split_L_pct` / `metrics.split_R_pct`（= 39.0 / 61.0）；metrics.json 侧 `totals.flow_share_L_pct = 39.00135467342238` / `totals.flow_share_R_pct = 60.99864532657763` | `a0b3ec4806920da6bcfe61004321f9e1` / `49f7ee36caab14d6943f971ecc06c837` |
| B4 | pB 分流比（Run-A，辅证） | 46.8 : 53.2 | `out\postprocess\contract-pB-v1.json` | `metrics.split_L_pct` / `split_R_pct`；metrics.json 侧 46.810379281049464 / 53.18962071895055 | `6ea9676722c3e70573eb2982484f611d` / `c0bbb99f13dbb6d74628ad2799698dc5` |
| B5 | **求解耗时（pA-v1）** | **1437.68 s** | `out\结果\P0-result-pA-v1\allrun.log` | 末行 `ExecutionTime = 1437.68 s`（simpleFoam；nProcs=1；WSL） | `1449efff2ea68c9b26410f55435e2636` |
| B5' | 求解耗时（pB-v1，辅证） | 638.71 s | `out\结果\P0-result-pB-v1\allrun.log` | 末行 `ExecutionTime` | `4f6f349164987f0d6ecd7ec8b68bd181` |
| B6 | pA WSS mean / p95（辅证） | 0.013 / 0.066 Pa | `out\postprocess\contract-pA-v1.json` | `metrics.wss_mean_Pa` / `wss_p95_Pa`；metrics.json 侧 `wss.mean_Pa = 0.012972871312951833` / `wss.p95_Pa = 0.06602786821638565` | `a0b3ec4806920da6bcfe61004321f9e1` / `49f7ee36caab14d6943f971ecc06c837` |
| B7 | pA 总阻力（辅证） | 73.8 Pa/(L/s) | `out\postprocess\contract-pA-v1.json` | `metrics.resistance_total`（= 18.45 / 0.25 L/s） | `a0b3ec4806920da6bcfe61004321f9e1` |
| B8 | pB 总阻力（辅证） | 179.6 Pa/(L/s) | `out\postprocess\contract-pB-v1.json` | `metrics.resistance_total`（= 44.9067 / 0.25 L/s） | `6ea9676722c3e70573eb2982484f611d` |

**口径注记**：
- B1/B2 的"显示值"（18.45 / 44.9067）与"全精度值"差异 < 0.0003%，远小于 ±2% 容差；对拍时以全精度值为比对基准、显示值为报告口径（与 extract_compare.py 的 half-up 圆整链条一致）。
- B5 耗时为**参考量非门控量**（机器相关）；门控只看指标不看过墙时间。
- WSS 为一阶体素估计（report.md Caveat 2），仅作辅证；L2 场相关门（VTK 对拍）才是 WSS 的主裁决。

---

## 2. 45.63 裁定：**历史注释值，不作基准**

- **事实**：45.63 Pa 在仓库中的现存出处均为**界面/注释层**，且源自**旧一代** pB metrics：
  - `code\pipeline\medical_extract\extract_compare.py`：`DP_PB_EXPECT = 45.63  # Pa，患者B 参考点（实测 45.624982…）`
  - `code\pipeline\webapp\plus\viewer_plus_data_pB.js` / `viewer_plus_data.js`：`"anchor":{...,"dP_Pa":45.63,"dP_raw_Pa":45.624982,...}`、`"标定点 v1 定流量 15 L/min → ΔP 45.63 Pa（R=182.5…）"`
  - `docs\kanban\看板-T17报告.md` / `看板-T18医学增强报告.md`：T17 当时按"阶段2-CFD算例包\结果\P0-result-pB-v1\后处理\metrics.json"核对 45.62498248148772 Pa（该外部包在本机两处候选路径均不存在）。
- **偏差量化**：45.624982 vs 现行归档 44.90667058007191 = **+1.60%**——单源就吃掉 L1 ±2% 容差的 80%（Kimi F-04 原始论证）。
- **裁定**：45.63（及其全精度源 45.624982、派生 R=182.5 Pa/(L/s)、sweep 曲线 22.81/45.63/91.25/136.88）**一律为历史注释值**：入门披露可，**不得作为 L1 对拍基准、不得进入 contract-pB-v1.json、不得写进数值契约**。
- **遗留处理（移交项，不属本轨文件域）**：webapp 三文件与 extract_compare.py 的 45.63 注释链需在 M3 切栈前清理为 44.9067 口径（登记看板"未完成/移交项"）。

---

## 3. 定流量分流比：**不作验收指标**（BC 输入决定，同义反复）

- **证据**：Run-A `0/U` 的 `flowRateInletVelocity` 输入即分流：pA `9.750341e-05 : 1.524966e-04` = 39.0 : 61.0；pB `1.170260e-04 : 1.329740e-04` = 46.8 : 53.2——求解器输出的分流比只是 BC 输入的回显（`log.simpleFoam` 末步 flux 写出与 BC 逐位相同）。
- **来源**：流量按面积分配是建模假设（`case_stats-v1.json` `runA_note`：审计 R2），非物理解——拿它验证求解器等于自证（GLM F-06）。
- **规则**：L1 门的指标 = **ΔP（Run-A 与 Run-B 双口径）+ 出口速度分布 + WSS 分布**；L2 场相关。分流比**仅在 Run-B 等压模式**下作为指标（该模式下分流是求解结果而非输入）。
- B3/B4 在本表中的地位 = **归档留痕**（记录 BC 假设与圆整口径），不是 M2 的通过条件。

---

## 4. 门控判定口径（引自规划 v2.3.2 §4）

| 级 | 容差/标准 | 指标 | 通过率 | 判定 |
|---|---|---|---|---|
| L1 | **±2% vs 归档标准取值**（pB ΔP=44.9067 Pa；pA ΔP=18.45 Pa） | ΔP（Run-A/Run-B 双口径）、出口速度分布、WSS 分布；定流量分流比不作指标 | 4/4 病例 | 指挥官+审计官 |
| L2 | 速度场相关系数 >0.98（逐病例 VTK 对拍） | 场相关 | 4/4 | 审计官 |
| L3 | 27 例基线全部跑通，指标漂移 <2% | 批量 | 27/27 | 双审计官 |
| 稳定性前置 | flux 闭合 <1%、checkMesh 0 errors | 守恒 | 每例 | 自动门 |

（完 · v1.0 · 2026-10-17 · 编码手 step-5-preview · 轨 A）
