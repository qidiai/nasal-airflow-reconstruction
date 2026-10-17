# 看板 · M1 轨 A（数值契约重写）· 2026-10-17

> 编码手：step-5-preview（轨 A）。纪律：禁 commit；只写本轨文件域 + 审计官指定附带项；随做随留证据。
> 自验：`G:\qidicode\target\tmp\M1\trackA\selfcheck.py` 复跑结果 **66/66 PASS**（数字、md5、引用忠实性三类断言）。

## 一、交付物清单（勾选 + 证据）

| # | 交付物 | 状态 | 路径 | md5 / 字节 |
|---|---|---|---|---|
| 1 | 数值契约 | ✅ | `F:\比赛项目\罕见无界黑客松\开源仓库\code\pipeline\docs\contracts\numerical-contract.md` | `c4e84870e991cbfc89da87d24645acd3` / 19912 B |
| 2 | 验证基线表 | ✅ | `F:\比赛项目\罕见无界黑客松\开源仓库\code\pipeline\docs\contracts\validation-baselines.md` | `392c251ab118250a2ae4a4af48387540` / 9411 B |
| 3 | 本看板 | ✅ | `docs/contracts\看板-M1轨A.md` | 见文末自校验 |
| 4 | 条件台账（N3，G1 纪律） | ✅ 待签结 | `F:\比赛项目\罕见无界黑客松\开源仓库\code\pipeline\docs\module-gates\conditions-ledger.md` | `e80b44e565071705b622e9f712a2d1cf` / 3461 B |
| 5 | 规划 §6 增补（N3 附带①） | ✅ 待签结 | `F:\比赛项目\罕见无界黑客松\赛题3-鼻腔气道随访\项目\规划-v2.3.2-M0门控全关闭-2026-10-17.md` | `b813d28f0e93517672c853b307622f7a` → `cbd824cebf7836d266c1dfa2dc99af42`（仅 +1 行 393 B） |

## 二、D1 结论：**载体已定位（找到，非复算记录）**

- **主载体**：`out\结果\P0-result-pB-v1\后处理\metrics.json` → `totals.dP_Pa = 44.90667058007191`（md5 `c0bbb99f13dbb6d74628ad2799698dc5`）。
- **辅证**：同目录 `report.md` §2（44.9067，md5 `96560f0b97835526092fcbd6b392b2fa`）；`out\postprocess\contract-pB-v1.json` `metrics.dP_baseline_Pa = 44.91`（md5 `6ea9676722c3e70573eb2982484f611d`）。
- 圆整链自洽：44.90667058007191 → 44.9067 → 44.91；Kimi R-016"未定位到"状态已升级。
- 交叉验证方式（三种）与诚实声明（metrics.json 生成脚本不在仓库）详见 validation-baselines.md §0。

## 三、任务书三项验收对照

| 任务书要求 | 落实 |
|---|---|
| 逐字段抄录归档实证（fvSolution/fvSchemes/controlDict + 0/U + 0/p 全 BC） | numerical-contract.md §3–§8；**所有代码块由归档文件原文注入生成**，自验含 10 项"块 ⊆ 归档文件"忠实性断言 |
| GAMG(GaussSeidel, tol 1e-6, relTol 0.05)、U smoothSolver(GaussSeidel) | §4 字段表 + E1 原文 |
| residualControl p=1e-4 **且** U=1e-4（非 1e-4/1e-5） | §4 + E15 运行期回显（tab 分隔 0.0001×2）双重实证 |
| bounded Gauss linearUpwind grad(U) + laplacian(Gauss linear corrected) + snGrad(corrected) | §5 + E2 原文 |
| relaxationFactors 实证值（p 0.3 / U 0.7） | §4 + E1 原文 |
| Run-A 定流量 + Run-B 等压双口径；Run-B 的 0/p inletL/R fixedValue 80 kinematic | §7/§8 + E4–E8 原文 |
| 每字段附实证文件路径 | §1 实证表 E1–E22（路径 + md5） |
| L1 基线：pA 18.45 / 分流 39.0:61.0 / pB 44.9067 / 1437.68s / 45.63 历史注释值不作基准 / 定流量分流比不作验收指标 | validation-baselines.md §1–§4 全覆盖 |

## 四、N3 附带项（审计官 GLM 指定）

- ① 规划 §6 已增补"授权窗口张力/BSL 社区接受度"单行条目（按审计处置建议原文口径）；字节级外科手术：14328 → 14721 B，增量恰为新行 393 B，CRLF/无 BOM 不变，无其他字节变动。
- ② `docs/module-gates/conditions-ledger.md` 已登记 N3（现象/定级/责任人=轨A编码手/验证人=审计官或指定验证人/关闭证据=前后 md5 + 插入行原文）。
- **状态：已修复 · 待签结**——按 G1，指挥官不得自宣关闭，M1 复审时由审计官/指定验证人签结。

## 五、未完成 / 失败项 / 移交项（如实清单，不许藏）

1. **Run-B 无求解结果归档**：`out/` 中 Run-B 只有 step2 算例（`0/constant/system`），`out/结果/` 无 `P0-result-*-v1B`——Run-B 的数值验收基线（等压 ΔP、自然分流比）**尚无归档实证**，M2 复刻 Run-B 时需自行求解并新建归档。已在契约 §8 明示。
2. **`后处理/metrics.json` 生成脚本不在仓库**（run_all.py 注明"笔记本侧后处理脚本"未归档）：基线载体的**文件**在三，但"从原始场一键重生成"路径缺失；交叉验证只能靠公式重算（已写入基线文档 §0 三种方式）。**建议 M1 复审时决议：将该后处理脚本归档或重写进 verify/**。
3. **45.63 历史注释值清理（移交 M3，不属本轨文件域）**：`webapp/plus/viewer_plus_data_pB.js`、`viewer_plus_data.js`、`medical_extract/extract_compare.py`（DP_PB_EXPECT=45.63）、T17/T18 看板仍持旧值；已裁定为历史注释值不作基准，切栈前需清理为 44.9067 口径。
4. **契约未经审计 GO**：按 G2，本文档待双模型审计通过后才冻结；审计 GO 前 M2 只可只读参照。
5. **pN/demo 系未纳入本契约**：契约只钉 pA/pB 的 v1/v1B 归档配置（任务书指定范围）；27 例轨 C 建成后的批量基线（L3 门）不在本轨范围。

## 六、工作底稿（可回收区）

`G:\qidicode\target\tmp\M1\trackA\`：`write_contract.py`（v1 稿，已被 v2 取代）、`write_contract_v2.py`（原文注入生成器）、`write_baselines.py`、`write_ledger.py`、`fix_plan_s6.py`（§6 插入）、`selfcheck.py`（66 断言自验，可复跑）。

## 七、自验清单（复跑命令）

```
& "F:\比赛项目\罕见无界黑客松\开源仓库\.venv\Scripts\python.exe" "G:\qidicode\target\tmp\M1\trackA\selfcheck.py"
```

覆盖：23 个载体 md5、dP/split/WSS/契约字段/ExecutionTime/残差/通量/checkMesh 数字复核、圆整链、10 项引用忠实性、3 份文档无 BOM、N3/§6/台账落地。

（完 · 轨 A · 2026-10-17 · 编码手 step-5-preview）
