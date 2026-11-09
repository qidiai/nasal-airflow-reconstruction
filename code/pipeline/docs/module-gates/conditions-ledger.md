# 条件台账 conditions-ledger（module-gates · G1 纪律）

> **纪律来源**：规划 v2.3.2 §8 门控防架空规则 **G1**——审计"带条件通过"的每条条件进本台账（责任人/验证人/关闭证据），**指挥官不得自宣关闭，由审计官或指定验证人签结**。
> **范围**：M0/M1 模块门控周期内登记的全部条件项。本文件由各模块编码手登记修复证据，签结权在审计官/指定验证人。
> **本次登记**：M1 派发时审计官 GLM 指定的附带修复项 **N3**（源自 `审计-规划v2.3.2-GLM53-2026-10-17.md` §3）。

---

## 登记表

| 项 | 内容 |
|---|---|
| 编号 | **N3** |
| 来源 | 审计-规划v2.3.2-GLM53-2026-10-17.md §3「新发现（非阻塞）：N3——§6 登记声称未兑现」；M1 派工任务书附带项 |
| 定级 | N 级小瑕疵（文档声称与事实不符；披露主体四要素已落地于 §2.1 L38，缺的仅是登记动作）——不回退门控 |
| 现象 | 规划 v2.3.2 §2.1（L38）句末声称"BSL 社区接受度风险以……对冲，**并列入 §6 风险登记**"，但 §6（L101-L103）六条目中无"授权窗口张力/BSL 社区接受度"任何条目；"接受度/2099"关键词 §6 区域零命中 |
| 修复动作 | 规划文档 §6 增补单行风险条目："授权窗口张力/BSL 社区接受度（'等 2099 就能免费用'误读风险……以'永久授权+清晰商用通道+非商用全功能免费'对冲）"（按审计处置建议①，单行） |
| 责任人 | 文档轨编码手（M1 轨 A，step-5-preview） |
| 验证人 | 审计官（GLM-5.3-222）或指定验证人——**M1 复审时签结** |
| 状态 | **已修复 · 待签结**（2026-10-17） |

## 关闭证据（E-01）

- **被改文件**：`F:\比赛项目\罕见无界黑客松\赛题3-鼻腔气道随访\项目\规划-v2.3.2-M0门控全关闭-2026-10-17.md`
- **改动性质**：仅 §6 条目区**插入 1 行**（393 字节，CRLF 保留；文件总字节数 14328 → 14721，增量即新增行全长，无其他字节变动；UTF-8 无 BOM 不变）
- **md5**：修复前 `b813d28f0e93517672c853b307622f7a` → 修复后 `cbd824cebf7836d266c1dfa2dc99af42`
- **插入内容**（§6 第二条款式行）：

```
+ 授权窗口张力/BSL 社区接受度（"等 2099 就能免费用"误读风险——对外沟通统一表述为"永久授权制"、明示不存在等待自动转换的免费商用窗口；社区接受度风险以"永久授权+清晰商用通道+非商用全功能免费"对冲）（N3 修复·2026-10-17·关闭证据见 code/pipeline/docs/module-gates/conditions-ledger.md）
```

- **修复后 §6 现状**（两行）：

```
+ 授权链不实（台账+发布前机审）+ 患者误用（措辞白名单+法务三件套）+ MDR 分类误判（法务评审前置）+ 清洁室质疑（规程+provenance）+ F-15 类几何-指标脱耦（几何差脚本进 P0.1）+ equivalence 失败回退（OpenFOAM 保留至 L3 全过）
+ 授权窗口张力/BSL 社区接受度（……见上 ……）
```

- **签结栏**（验证人填写）：☐ 通过（签名/日期：__________） ☐ 退回（原因：__________）

## 备注

- 本台账随 M1 四轨交付统一提交；轨 A 只登记并修复 N3（任务书指定），其他轨/其他条件项由对应责任人登记，禁止跨轨代签。
- 编码手（本人）只填"修复动作/证据"两栏；"状态→已关闭"必须由验证人签结后改判。

## 2026-10-17 吸收判词修正（GLM §10 审计结论，待验证人签结）
| # | 项 | 状态 | 责任人 | 验证人 | 证据 |
|---|---|---|---|---|---|
| A1 | Sutura 实为 PolyForm Noncommercial 1.0.0（《吸收方案》标 Apache-2.0 失实）→ 禁入；② 随访引擎水密判决改 trimesh | 已修入 plan §10/§11 | 指挥官 | 审计官 | 吸收库 Sutura/LICENSE 原文 |
| A2 | avatree MIT 声明悬空（本地无 LICENSE）→ 标注待查 upstream；M2.5 v1 不依赖 | 已修入 plan §10 | 指挥官 | 审计官 | 吸收库 avatree 无 LICENSE 实测 |
| A3 | Apache-2.0 四义务（NOTICE/副本/标注/专利报复披露）入 plan §10 | 已修入 plan §10 | 指挥官 | 审计官 | GLM 审计报告 5 仓库实测 |

| A4 | 自研替代铁律成立（许可不过关→自研/换件，功能目标不降）+ 六项替代清单 | 已修入 plan §10 | 指挥官 | 审计官 | 用户 2026-10-17 指令 |

## 2026-10-17 M1 轨 D 交付登记（待 M1 门签结）
| # | 项 | 状态 | 责任人 | 验证人 | 证据 |
|---|---|---|---|---|---|
| D1 | 77.3s 口径定案：链计时不含求解，『端到端 77 秒』禁用；对外 21–24 分钟区间 | 已入 plan §3/§12 + baselines B6/B7 | 轨 D | 审计官 | 复测报告+manifest 75.3s |
| D2 | pA=demoA 同一患者（DICOM 头 md5 全同）→ 别名索引 | 已登记，M1 门裁定 | 轨 D | 指挥官+审计官 | ledger G4 |
| D3 | G2 授权书缺口（authorization_ref 全空） | **待用户裁定**（补签/维持 L3） | 用户 | — | consent-ledger 缺口章 |

| C1 | 27 例基线：22 成功/5 发散（如实）；口径=鼻窦CT，禁与 pA/pB/pN 混表或作临床常模 | 已入 plan §12 | 轨 C | 审计官 | baseline27 阶段报告 |
| C2 | 重复患者：case-25/26=pN-Lat/pN-Med（7 位一致）；连同 pA=demoA 建去重索引 | 已登记，M1 门裁定 | 轨 C | 指挥官+审计官 | MD5-MANIFEST+体积比对 |
| C3 | 5 例发散集转为自研求解器 L1 压力测试案例 | 已入 L1 门定义 | 轨 C | 审计官 | metrics.json status=DIVERGED |

| B1 | F-15 定论：变窄退化（0.16-0.40% 细胞全在滞留区）；根因 EDT-cavity erode(3) 断颈；手术模拟须换壁面位移法 | 已入 plan §12，P4 前置硬条件 | 轨 B | 审计官 | 排查报告 §1/§4 |

## 2026-10-17 M1 门控条件（Kimi 裁定 GO-with-conditions；GLM 待合并）
| # | 条件 | 状态 | 责任人 | 验证人 |
|---|---|---|---|---|
| M1C1 | N3 重落（§6 授权窗口张力项）+ 规划单点权威（项目目录为准，scratch 从属） | 已关闭 | 指挥官 | 审计官 |
| M1C2 | M2 首跑必须含 Run-B 等压模式求解归档 | 开 M2 时关闭 | M2 编码手 | 审计官 |
| M1C3 | metrics.json 后处理脚本归档或重写决议 | 开 M2 时关闭 | 指挥官 | 审计官 |
| M1C4 | pN 名实不符裁定（G3）+ consent_record 第 5 条补登 + 四分位口径注明 | M1 门签结前关闭 | 指挥官 | 审计官 |

| M1C5 | 契约 §11 dP 口径修正为入口 patch 面数平均（GLM 实证 (56·pL+62·pR)/118 逐位吻合） | 已关闭 | 指挥官 | 审计官 |
| M1C4b | pN 命名消歧公约：同名不同轮次的病例一律加轮次前缀（t26-pN-Lat / demo-pN-Lat）， consent_record 第 5 条补登 | 已立公约，随 M2 文档落地 | 指挥官 | 审计官 |
| M1C6 | ledger B3 头数复核：现文本已为 420 头（GLM 审计所报 120 疑为旧版/笔误），无需修改 | 已关闭 | 指挥官 | — |

## 2026-10-18 M2 门控合并条件（GLM+Kimi 双裁定 GO-with-conditions，收敛一致）
M2 裁定：数值内核就绪（多算例 <±2%、热点同位、审计官逐位复核无虚构、清洁室合规）；
OpenFOAM 退役（M3）须待以下条件闭合——退役不可逆（永久失去对拍真值源）。
| # | 条件 | 状态 | 责任人 |
|---|---|---|---|
| G-C1 | pA/pB 满程 1500 步 L1 对拍（契约基线 pA 18.45/pB 44.9067；pB 约 9h/例已量化） | pB 后台批跑中（C1-pB-1500，紧容差 1e-3） | 指挥官+审计官复核 |
| G-C2 | L3 27/27 全量（22 成功例 + 5 发散例健壮性行为记录） | 待派（场提取可批跑） | 编码手 |
| G-C3 | Run-B 等压自研求解首跑+归档（M1C2 移交项；M1 的 Run-B 是 OF 求解不计入） | pA-v1B 后台批跑中（C3-pA-runB） | 指挥官+审计官复核 |
| G-C4 | 文书收口：W4 表更新（D-1 已解除）、L2 状态回写、fvm.rs/lib.rs 头注释矛盾 | 待派 | 编码手 |
| G-C5 | WSS 口径裁决（−5~−9% 归因：近壁梯度量敏感性 vs 实现缺陷） | 待派 | 编码手+审计官 |

| G-C3b | **Run-B 首跑实测发散（新发现，夜班 06:00）**：pA-v1B 等压模式 iter 400 pLin 解出 NaN、全场 NaN、gradp 爆 1e9——fixedValue 80 入口压差从 U=0 冷启动冲爆 SIMPLE（OF 的 GAMG+松弛能扛住，我们不行）。批已杀（NaN 垃圾），转调试项：候选方向=启动松弛下调/potential-flow 初场/入口压力分层施加 | 开放，明早处理 | 编码手 |
| G-C1b | pB 满程已过：dP 44.62 vs 归档 44.91 = −0.63%（±2% 门内，1500 步同硬停 regime，cont 1.1e-3）；pA 满程批跑中（C1-pA-1500） | pA 批跑中 | 指挥官 |

| G-C1c | **pA 满程达成（08:45）**：dP 18.747088 Pa vs 归档 18.45 = +1.61%（±2% 门内）；split 39.0:61.0 与 contract-pA-v1.json 逐位相同（BC 实现铁证）；1500 步 endTime 硬停同 regime；cont 2.7e-3/2.5e-4。**G-C1 全闭（pA+pB 双基线均过）** | 已关闭 | 指挥官+审计官复核 |

## 2026-10-19 M2 收官续棒结果（代理 01a14f51，检查点 021f0cb）
| # | 结果 | 判定 |
|---|---|---|
| G-C2 L3 | **15/22 PASS**（\|dP\|≤0.63%、\|U_max\|≤1.23%、flux≤0.08%）；批跑脱离会话后台继续（PID 19460，l3b-full.log），剩 7 例 | 趋势达成，等批跑完 --extract 出终表 |
| G-C3 Run-B | **小网格通过**（pN-v6B 26,884 cells：斜坡200+1500步 residualControl 收敛、无 NaN、dP(kin)=80 保持）；**pA-v1B 大网格失败**（六方案全发散，机制=鼻阀高 Péclet 速度峰经 HbyA→压力→速度指数放大，三种离散均不能阻止） | 机制验证通过；pA 满分辨率 Run-B 为已知边界（如实登记，未调参凑数） |
| G-C4 文书 | 看板终版 + docs/equivalence-report.md（L0-L3 总表+未决项） | 已关闭 |


## 2026-10-19 L3 收尾复核（M2 代理，07:52-08:30）
| # | 结果 | 判定 |
|---|---|---|
| G-C2 L3 终表 | **22/22 PASS**（\|dP\|≤1.44%、\|U_max\|≤1.23%、flux≤0.22%，全部 22 例 dP/U_max/flux 三列齐全） | 已关闭 |
| G-C2 T1 五例补跑 | 批跑已于 02:08 收官（l3b-full.log）：002/019/025 满 1500 步，dP +0.14%/−0.40%/−0.70%；026/027 与归档 OF 同为 residualControl 提前收敛（我们 199/219 步 vs 归档 182/197 步，dP +1.44%/−0.20%）。因收敛点不写 1500 快照，补跑捕获收敛前快照（026 write-every 100、027 write-every 200，WMI PID 9476/子进程 19684 串行完成）：U_max 3.326 vs 3.3279 = −0.04%、5.546 vs 5.5452 = +0.02%；flux 闭合 0.000% | 5 例全部跑成且三列齐全 |
| G-C2 T2 004 判定 | **③ 提取时序错误，非算例/非求解**：825.441 Pa 是日志 Time=3 瞬态（l3b-004.log 第 14 行），旧 summary last_iter=3——生成于 00:14:37，而 004 于 00:10:41 启动、00:55:20 才完成。终态 dP 395.242 vs 归档 396.671 = −0.36%；VTK U_max 18.800 vs 18.795 = +0.03%；flux 闭合 0.001%；dP 轨迹 100→1500 步稳定在 395.2~396.7 Pa（漂移 <0.3%）。重建算例与归档同源：check-mesh cells 69414 / internal faces 180426 / patches inletL 74、inletR 162、outlet 61、walls 55335 / 入口 BC 7.783574e-5、1.721643e-4 全部一致 | 已澄清并重算 → PASS |
| G-C2 工具修复 | l3_batch.py 三项：①extract 增加完整性闸门（日志无 §11 收官段即拒绝抽取，防瞬态值入表）；②solve_done 改按 §11 收官段判定（提前收敛例不再被反复重跑）；③完成判据不再硬编码 last_iter==1500，并新增 §11 patch flux 回退（提前收敛例无 writeTime flux 行）。串行批跑 WMI PID 25384 于 07:58:36 启动，22/22 全跳过即时退出（todo=[]，l3b-serial.log 留证） | 已落盘 |

## 2026-10-19 M2 关闭件复审（Kimi 裁定 GO；GLM 待回）
- G-C1~C5 全部核验通过：Kimi 从 VTK 场+polyMesh 独立复算 pA dP=18.7555（宣称 18.747，
  面心插值近似差 0.045%）、split 0.3900:0.6100 逐位复现、pB 44.7449；G-C2 抽 4 行
  对归档全中；G-C3 六方案发散记录逐位吻合；0 项数值造假
- 文书级发现已修（指挥官当日）：equivalence-report.md 原停在批跑中间态
  （L3 15/22、004 标 825.441 瞬态值、D-1 旧 22% FAIL）——已同步至终态
  （22/22 PASS、004=395.242 −0.36%、D-1 解除 0.45%、WSS 22 例 −7.92~+7.86）
- 证据形态偏差（F-4）：C1 批日志不存在，物证为 VTK 三快照——已登记

## 2026-10-19 M3 门控审计整改（GLM 裁定 GO-with-conditions 后）
| # | 审计发现 | 整改 | 状态 |
|---|---|---|---|
| F1 | legacy 10 模板被 .gitignore `**/P0-OF-case*/` 静默吞掉未入库，NOTICE/MD5SUMS 悬空 | git add -f 强制入库（GPL 边界声明与现实一致） | 已修 |
| F2 | case-001 回归死于 Time=400（日志 12:48 停更），commit f53b708"回归全过"失实 | 登记更正：pA ✅ +1.632%、case-003 ✅ +0.116%、case-001 ❌ 死于 Time=400 待补跑；看板 §6 更正 | 已登记，补跑入 M4 首周 |
| F3 | 证据包 README md5 快照与终态不符 | 证据包勘误 | 待 M4 首周 |
| F4 | M3-reg-summary.json 悬空引用 | 清理或补生成 | 待 M4 首周 |

## 2026-10-19 F1 裁决：legacy OF 模板不入库（Kimi 方向胜）

- **背景**：GLM 审计建议 `git add -f` 强制入库 10 个 legacy 模板（commit 553636c）；Kimi 审计建议保持不入库 + NOTICE 措辞澄清为"本地归档"。
- **裁决（用户授权下指挥官裁定）**：采 **Kimi 方向**。依据：M3 任务书原文"**不随 BSL 核心分发**"——force-add 与之相悖。
- **执行**：`git rm -r --cached` 回退 553636c 的 10 文件（保留工作副本）；NOTICE 增补"本地归档"措辞（干净 clone 不含这些文件，HEAD 仅含 NOTICE 与清单元数据）。
- **教训**：审计官建议相悖时，以任务书原始意图为第一裁决依据，而非"哪条更好"。

## 2026-10-19 F2 关闭：case-001 回归重跑 PASS（-0.53%）

- 重跑背景：前次（13:11 起，58 分钟）跑满 1500 步未猝死（前次 Time=400 死亡），stop_reason=endTime 硬停、
  residualControl 未双达标（末次 p 初残 2.140e-4，U 6.043e-5/1.754e-5/1.989e-5）——与归档 OpenFOAM
  跑法同构（同样跑满 endTime），非求解器缺陷。
- 结果：**dP 27.617 Pa vs 归档 27.763 Pa = -0.527%（PASS，容差 ±2%）**；
  U_max 5.3146 vs 5.3293 = -0.276%；flow_share_L 61.58% vs 61.581%；Q_inlet 14.99999 vs 15.00002 L/min；
  flux closure 4e-6%；cells 53,747。
- M3 回归三例全过：pA +1.632% / case-003 +0.116% / case-001 -0.527%，全部在 ±2% 内。
- errata 闭环：f53b708"回归全过"失实声明（case-001 未跑完即宣称）至此纠正。

## 2026-10-19 M4 门控关闭：双审计 GO-with-conditions → 整改全闭环 → 历史干净重写

- **双审计**（报告：`项目\审计-M4成像-GLM53-2026-10-19.md` / `审计-M4成像-KIMI27-2026-10-19.md`）：
  GLM53 GO-with-conditions（10 发现/C1-C5）；KIMI27 GO-with-conditions（1 中 5 低）。
  分歧裁决：GLM 的 C1（患者影像禁入仓）成立——consent-ledger L62"实图也禁"明文，
  KIMI 未列该条属漏检（只对照 wording.py 禁则、未查影像来源）。
- **C1 闭环（高·推送前硬闸）**：初版交付 f39de64 曾将患者派生影像（qc_pA_mid.png
  CT 轴位轮廓 + 患者几何场切片）随样例报告入仓。因两提交均未推送，按审计要求做
  **本地历史干净重写**：`git reset --soft ce2320f` 后以审计整改后树重组单一提交
  `633014f`（32 文件/5492 行）；`git diff --name-only ce2320f HEAD` 患者产物=0。
  旧哈希 f39de64/8c748c9 仅存 reflog，**推送前不得恢复**。
- **C2-C5 闭环**：plus/ 入 gitignore；requirements.txt 补 meshio/pyvista；cases.py
  pN-Lat/pN-Med 双口径注释（前端包 116.28/8.30 vs 归档 148.65/27.76 Pa）；
  看板-M4.md 重写（门结果+证据引用+提交态措辞校正）。
- **提交态边界**：examples/ 仅 synth-001（100% 合成）；患者例报告/渲染图本地授权展示，
  `embed_demo_reports.py --cases` 本地重建；demo.html 患者例按钮转提示文案。
- **遗留（不阻断 M5 派工，阻断 M5 供数）**：pN-Lat/pN-Med 口径对账须在 M5 API
  对外供数前完成（cases.py 注释已标）。
- **推送闸门**：本地领先 origin 16 提交；C1-C3 已复验闭环，推送待用户确认。

## 2026-10-20 W6 收官：IC(0)+deflation 设为默认 + 求解器写出 bug 修复

- 全门 7/7 PASS（新默认 @1500/提前收敛）：INV-001 −0.000%、pN6 −0.026%、pB −0.084%、
  L3-006 −0.082%、L3-019 −0.409%、L3-026 +1.446%、pA −1.618%（vs SGS；vs OF 归档 −0.03%）
- 真 bug 修复：residualControl 提前 break 跳过循环内 fields 写出（SGS 时代潜伏）——
  simple.rs 循环后兜底写，case-026（iter 199 提前收敛）复验 PASS
- 合同已修订注记（判据不变：仅收敛路径改变；env 可回退）
- 证据：solver/docs/W6-验收.md v3 章节；W6 正式收官

## 2026-11-01 预检门登记：#76 逐层间隙一致性（停工）与 #79 头普查读层

### 登记表一（#76）

| 项 | 内容 |
|---|---|
| 编号 | **#76**（编号沿用项目侧缺陷台账） |
| 来源 | `step1_airway_segment.py` 旧 `dz` 只取最底两层 |
| 定级 | P0（患者数值正确性） |
| 现象 | 体积换算 `vox_vol`、`marching_cubes` spacing、QC 图 aspect 所用 `dz` 取最底两层间隙，缺层时数字静默失真：首间隙翻倍会让气道体积恰好变 2.0 倍（体积 ∝ dz），且旧预检 `z_structurally_ok` 全程放行 |
| 修复动作 | commit `561ef2c`：加逐层间隙一致性门（停工）——判定式 tol = max(1% × 中位间隙, 0.005 mm)（`code/pipeline/airway_geom.py#Z_GAP_REL_TOL` `:70`、`#Z_GAP_ABS_FLOOR_MM` `:71`、判定函数 `#z_gap_report` `:148`），不一致即预检与 step1 双双 exit 2 停工上报；step1 的 `dz` 改取中位间隙（`step1_airway_segment.py:91`），与预检 `slice_gap_measured` 同一个数 |
| 责任人 | 管线轨编码手（T2 = `561ef2c`） |
| 验证人 | 指挥官 + 审计官 |
| 状态 | **已修复 · 待签结**（本文件 `:3` 纪律：签结权在审计官/指定验证人，指挥官与编码手均不得自宣关闭） |

### 登记表二（#79）

| 项 | 内容 |
|---|---|
| 编号 | **#79**（编号沿用项目侧缺陷台账） |
| 来源 | DICOM 头普查与 step1 读的不是同一批层 |
| 定级 | P0 相邻（真患者目录假拒绝） |
| 现象 | 总控预检 `run_all.py#survey_dicom` 的头普查与 step1 实际读取不是同一批层，真患者目录被假拒绝（误停工） |
| 修复动作 | commit `6fca6ee`：DICOM 头普查改读 step1 同一批层（2 files changed, +295/−36；新增 `code/pipeline/tests/test_survey_series_select.py`）；复跑真实数据 16 个序列目录：放行 16 / 停工 0 |
| 责任人 | 管线轨编码手（T1 = `6fca6ee`） |
| 验证人 | 指挥官 + 审计官 |
| 状态 | **已修复 · 待签结**（同上，本文件 `:3` 纪律） |

### 关闭证据

口径：下表 md5 一律 `git show <rev>:<path> | md5sum`（**blob 空间**；前 = 该缺陷修复提交之前、后 = 之后）。实测上表五个 `.py`/测试文件的**工作树 md5 与该 blob md5 逐位相同**（行尾取证用 `tr -cd '\r' | wc -c`，口径=CR 字节数，五个文件均为 0）。本仓 `.md` 文档工作树多为 CRLF 而 blob 为 LF（`git ls-files --eol` 实测 `i/lf w/crlf`），两者 md5 不相等，引用 `.md` 的 md5 须注明取的是哪个空间。

| 文件 | md5 前 → 后 |
|---|---|
| `code/pipeline/airway_geom.py` | `eabe7e4bf5de558b5c243d1dabad69bc` → `a77229406ddaa2c63131f6ca1c56e262` |
| `code/pipeline/run_all.py` | `f298535f81afe4a5b6c9f2c08394a546` → `cabbd9f6be02f1a6405a01e9e3d84a27`（#76 前/后；#79 前值 `efd6beb9597d687842161de1b07e8747`，#79 的后值即 #76 的前值） |
| `code/pipeline/step1_airway_segment.py` | `ab43679b9b6a58a668e25312cef55f87` → `bcf9c9c6cb93100a9a5bdb7557d0cdad` |
| `code/pipeline/tests/test_survey_series_select.py` | 新增（`6fca6ee^` 无此文件，`git show` 原文 `fatal: path '…' exists on disk, but not in '6fca6ee^'`）→ `fb3bff1bb56ead7d212c66a5fd67e441` |
| `code/pipeline/tests/test_z_gap_consistency.py` | 新增 → md5 `e556367f0e03d48e9600963a09353fd1` / sha1 `25d2264b3ea72c2b784512f83c66d86c184b7aef` |

改动性质（`561ef2c` 内各文件 `git diff --numstat`，删/加）：`airway_geom.py` 30 0（纯新增）、`run_all.py` 15 3、`step1_airway_segment.py` 10 2、`tests/test_z_gap_consistency.py` 新增。
两提交：`6fca6ee fix(precheck): DICOM 头普查改读 step1 同一批层，修掉真患者目录的假拒绝`（2 files changed, +295/−36）；`561ef2c fix(precheck): 加逐层间隙一致性门（停工），step1 的 dz 改取中位间隙`（4 files changed, +354/−5）。

### 反例 / 谁接住 / 实质判别 / 未折进恒真布尔

- **反例**（反例证据一律用仓内可指的 `code/pipeline/tests/test_z_gap_consistency.py` 用例名）：首间隙翻倍形态由纯函数、预检、step1 三处钉死——`test_gap_report_flags_doubled_first_gap`、`test_survey_stops_work_on_doubled_first_gap`、`test_step1_standalone_stops_on_non_uniform_gap`；中间跳层形态——`test_gap_report_flags_mid_stack_hole`、`test_survey_stops_work_on_mid_stack_hole`；短链防御——`test_gap_report_rejects_short_input`；口径钉死——`test_gate_constants_match_measured_basis`、`test_gap_report_median_is_upper_median_abs`、`test_step1_dz_is_median_not_first_pair`。
- **谁接住**：总控预检 `run_all.py:450` `die(2, "层间距不一致：中位间隙 …停工上报")`；单独执行 step1 时 `step1_airway_segment.py:93-97` 同措辞 print + `raise SystemExit(2)`，位于 `:98` 体素数组分配之前（停工不分配体素、不产出 `metrics*_v2.json`）；web 上传路径 `server.py:2150-2152` `except SystemExit` 记录 `survey_error`，`server.py:2157-2163` 落 `status="blocked"`、`gate="DICOM 头普查（层序结构断言）"`、`exit_code=2` ⛔ 拦截卡。
- **实质判别**：真实数据 16 个序列目录实测放行 16 / 停工 0，最大 `z_gap_max_rel_dev` = 2.033e-04（= 0.020%）、其余 ≤ 3.2e-13，`z_gap_tol_mm` 实测落点 0.005 / 0.006 / 0.00625 mm；阴性对照用例 `test_gap_report_accepts_uniform_stack`、`test_step1_control_uniform_runs_clean` 证明均匀链放行——停工侧与放行侧都不是恒真。
- **未折进恒真布尔**：uniformity 不写进 `z_structurally_ok`——停工门在 `survey_dicom` `return rec` 之前 `die`，能返回的 rec 该布尔恒为真，做成门的一部分就是构造性恒真的假闸门；此理由仓内已有代码注释可指：`run_all.py:445-448`。故 `z_structurally_ok` 一字节不动，一致性只做独立门 + 四个量化键。

### 对外开放边界

四个 `z_gap_*` 量化键（`z_gap_max_abs_dev_mm`、`z_gap_max_rel_dev`、`z_gap_tol_mm`、`z_gap_bad_pairs`）当前只在预检 rec / manifest 内；`server.py:2144-2149` 的 survey 键白名单不含它们（`grep -cF "z_gap_" server.py` = 0）⇒ 工作台不展示偏差/容差数值，属开放项 #81。

### 开放项（未修，勿据此理解现状）

- #77 选组并列仍按输入顺序（`airway_geom.py:204-206` 注释：dict 保序，并列时先出现的组胜出）；
- #81 四个 `z_gap_*` 量化键无消费者；
- #84 `die` 不带消息（web 卡显示 "2"）；
- #85 停工前 `makedirs` 留空目录；
- #86 `层厚 {dz}mm` 打印现带 6 位圆整。

## 2026-11-05 选序列「重建适用性」准入（A2-Q1）+ S1 适用性断言（T2）

编号沿用本台账单调口径：#86 之后的首两个空号为 **#87 / #88**。上面 #76/#79 两个段落与"开放项"列表**一字未动**。

### 登记表三（#87 选序列重建适用性准入）

| 项 | 内容 |
|---|---|
| 编号 | **#87**（沿用外审 A2 条目，台账续号） |
| 来源 | `read_ct_series` 的"取层数最多的一组"（`code/pipeline/airway_geom.py:286`）整条链无任何判据识别"被选中的序列是否适合重建" |
| 定级 | P0（患者数值正确性：选错序列 ⇒ 下游全错且不报错） |
| 现象 | 多帧动态序列、定位像、另一套层数更多的非重建序列，只要**文件数更多**就被选中，预检跟着 step1 一起选错而不报错；且旧实现组间比较用**去重前** `len(grp)`，重复层多的组凭虚高文件数胜出 |
| 修复动作 | `airway_geom.py` 新增准入判定表 `#ADMISSION_CHECKS`（`:252`；常量 `#MODALITY_FOR_REBUILD` `:194`、`#AXIAL_NZ_MIN` `:195`）、判定函数 `#admission_rejection`（`:259`）、IOP 三态分类 `#_iop_values`（`:198`，missing / unparseable / ok）、组内同 z 去重 `#_dedup_by_z`（`:268`）；**准入判在选优之前**、组间比较一律用去重后层数；被拒组进 `report["rejected_series"]`（`:386`），准入组进 `report["admitted_series"]`（含 `iop_missing`，`:338` / `:387`）；全部组被拒仍 `SystemExit(1)` 并补原因统计（`:396`） |
| 责任人 | 管线轨编码手（T2） |
| 验证人 | 指挥官 + 审计官 |
| 状态 | **待签结**（本文件 `:3` 纪律：签结权在审计官/指定验证人，指挥官与编码手均不得自宣关闭） |

### 登记表四（#88 S1 重建适用性断言）

| 项 | 内容 |
|---|---|
| 编号 | **#88**（台账续号） |
| 来源 | 选中的"层数最多"序列即使模态/朝向正确，物理尺度仍可能不是诊断轴位 CT（拼接序列、视野外重建等） |
| 定级 | P0（体素尺度错 ⇒ 体积/面积/速度全错） |
| 现象 | 旧链路对 `PixelSpacing` / 实测层间距不做任何合理性判定，2.4mm 面内间距的序列照常进 step1 出数 |
| 修复动作 | `run_all.py` 纯函数 `#suitability_failures`（`:467`）+ 常量 `#PIXEL_SPACING_RANGE_MM`（`:463`）、`#SLICE_GAP_RANGE_MM`（`:464`）；两个消费点：S1 主流程 `run_all.py:1011-1013` `die(2, "重建适用性断言 FAIL：…——几何不可重建，停工上报")`（位于维度动态断言 `:1007-1008` 之后、层序门 `:1020` 之前）；web 上传路径 `server.py:2175-2186` 落 `status="blocked"`、`gate="重建适用性断言"`、`exit_code=2` ⛔ 拦截卡（在 step1 之前，`survey` 键白名单 `server.py:2144-2149` 未动） |
| 责任人 | 管线轨编码手（T2） |
| 验证人 | 指挥官 + 审计官 |
| 状态 | **待签结**（同上纪律） |

### 反例（合成 fixture，全部落在 `code/pipeline/tests/test_series_suitability.py`）

准入侧（#87）：
- `:109 test_sagittal_series_with_more_layers_loses` —— 12 层矢状（IOP `[0,1,0, 0,0,-1]`，n_z=0）vs 6 层轴位 ⇒ 轴位胜出；矢状进 `rejected_series`，`reason` 含 `非轴位`/`|n_z|`，且打印「准入拒绝 1 组（非轴位 1 组）」；
- `:130 test_non_ct_modality_with_more_layers_loses` —— 14 层 `Modality=MR` vs 5 层 CT ⇒ CT 胜出，MR 进 `rejected_series`；
- `:163 test_group_count_uses_deduped_layers` —— A 组 10 层含 5 个同 z 重复（去重后 5）vs B 组 6 层 ⇒ 选 B（旧实现 10>6 会选 A；`ignored` 记 A 的 `n=5`）；
- `:148 test_missing_iop_is_admitted_and_disclosed` —— 无 IOP 的 8 层组准予入围，`admitted_series[0]["iop_missing"] is True` 且打印披露行；
- `:203 test_all_groups_rejected_exits_with_reason_stats` —— 两组全非轴位 ⇒ `SystemExit(1)` + 「其中 2 组因非轴位被拒」；
- `:229 test_admission_boundary_and_orientation_math` —— `|n_z|=0.9` 放行 / `0.8999` 拒绝；矢状与冠状都拒；
- `:252 test_iop_unparseable_is_rejected_fail_closed` —— IOP 六分量含 NaN / ±inf / 非数值 ⇒ 标签 `IOP不可解析`、reason 含「不可解析」（R1 新增，钉死旧 `abs(n_z)<0.9` 对 NaN 恒 False 的静默放行路径）；缺失与分量不足 6 个仍按 missing 披露放行；
- `:272 test_nan_iop_series_with_more_layers_is_rejected` —— NaN-IOP 的 **14 层**组 vs 6 层轴位 ⇒ 不得靠层数胜出，进 `rejected_series` 且不出现在 `admitted_series`；
- `:293 test_rejected_entry_n_uses_deduped_layers` —— rejected 条目 `n` 也是去重后层数（6 文件 → 3），与 `ignored` 同口径；
- `:221 test_admission_table_is_the_single_source_of_truth`、`:246 test_modality_check_is_case_insensitive`（`Modality="ct"` 放行）；
- `:178 test_ignored_and_rejected_entry_schemas` —— `ignored` 条目仍是 `{"series","n","desc"}` 精确 schema，`rejected` 多一个 `reason`。

断言侧（#88）：
- `:316 test_suitability_flags_out_of_range_pixel_spacing` —— PS=2.4mm ⇒ 两条失败文案（含 `[0.05, 1.50]mm`、`被选中的序列可能不是诊断轴位 CT`）；
- `:326 test_suitability_flags_slice_gap` —— gap=5.0mm ⇒ 失败（`[0.05, 3.00]mm`）；
- `:332 test_suitability_flags_slice_gap_below_lower_bound` —— gap=0.01mm 低于下界 ⇒ 失败（R1 新增，补上轮只钉上界的缺口）；
- `:353 test_suitability_fails_closed_on_missing_fields` —— rec 缺字段必须报失败，不 fail-open；
- `:360 test_survey_dicom_does_not_die_on_4x4_bad_spacing` —— 门**不在** `survey_dicom` 内部（理由见下"被否方案③"，**不是**"放进去会打坏锁定测试"——锁定 fixture 的 0.7/1.0 本来就在门区间内）：4×4 / PS=2.4 体模照常返回 rec，但 `suitability_failures(rec)` 非空；
- `:382 test_run_all_main_dies_with_suitability_gate` —— **真实子进程**跑 `run_all.py`：PS=2.4 序列 `returncode=2`，stdout 含「重建适用性断言 FAIL：」「面内像素间距 2.40mm」「几何不可重建，停工上报」；
- `:401 test_server_web_path_uses_same_suitability_function` —— web 路径消费同一纯函数、`gate="重建适用性断言"`、`exit_code=2`，且门位置在 `cmd1 = [sys.executable, STEP1` 之前；
- `:417 test_server_gate_web_path_blocks_with_card` —— **真跑** `server._register_case`（Flask app context）：PS=2.4 序列落 `status="blocked"` / `gate="重建适用性断言"` / `exit_code=2` 卡，`gate_failures` 含「面内像素间距 2.40mm…」，`survey` 白名单仍 12 键，且没有 `preview/` 目录（门确实挡在 step1 之前）。

放行侧阴性对照（证明门既非恒真也非恒假）：
- `:340 test_suitability_accepts_demo_geometry_and_closed_bounds`（0.7/1.0 与端点 0.05 / 1.5 / 3.0 都放行）；
- `:347 test_suitability_has_no_matrix_or_layer_count_gate`（4×4 / 19 层放行 —— 被否的两条绝对门不得回潮）；
- `:458 test_demo_synthetic_dir_passes_suitability_gate`（`out/synthetic-ct`：96×96 / PS 0.7 / gap 1.0 放行）；
- `:469 test_local_upload_dirs_pass_suitability_gate`（`out/e2e-state-*/uploads/*` 两个目录放行）。

### 谁接住

- **选层器**：`airway_geom.read_ct_series` —— 不准入的组不进选优（被拒原因进 `report["rejected_series"]`）；全部不准入仍 `SystemExit(1)`（`airway_geom.py:396`）。step1 与预检共用这一份实现（`step1_airway_segment.py:98`、`run_all.py:371`）⇒ 不会再出现"预检放行、step1 选错"的分叉。
- **总控 S1**：`run_all.py:1011-1013` `die(2, …)`，exit 2 停工（不产出任何患者数值产物）。
- **web 上传**：`server.py:2175-2186` 落 `status="blocked"`、`gate="重建适用性断言"`、`gate_failures=[失败文案…]`、`exit_code=2` 的 ⛔ 拦截卡，与既有 PII / 层序拦截图同一机制；进度日志同步一行「⛔ 门禁拦截：重建适用性断言 FAIL：…」。

### 每个条件：实义判据还是重言式

| 条件 | 判定 | 依据 |
|---|---|---|
| `Modality.upper()=="CT"`（`:221-226`） | **实义** | 值来自 DICOM 头，不由本函数其它分支保证；去掉即选 14 层 MR（`:130` 直接红）。本机 13 目录实测 `rejected=0` ⇒ 零误停，触发侧由合成反例提供 |
| IOP 存在但不可解析（NaN/±inf/非数值）⇒ 拒绝（`:198-226`、`:229-234`） | **实义（fail-closed）** | 旧实现 `abs(n_z) < 0.9` 对 NaN 恒 False ⇒ 损坏 IOP 的组被**静默准入**且 `iop_missing=False`（零披露）；现在按"轴向性未知"拒绝。反例 `:252`（三态单测）、`:272`（14 层 NaN 组不得胜出）。与 F2 侧 NaN fail-closed 同口径 |
| `|n_z| >= 0.9`，仅在 IOP 可解析时判（`:237-248`） | **实义** | `n_z = iop[0]*iop[4] - iop[1]*iop[3]`；矢状 `[0,1,0,0,0,-1]`、冠状 `[1,0,0,0,0,-1]` 都得 `n_z=0`（精确拒绝），边界 0.9/0.8999 由 `:229` 钉死。阈值语义：`0.9 = cos 25.8°`，即容忍 ≤25.8° 倾斜/重排，常规机架倾斜 ≤±10°；本机 13 目录被选中序列 IOP 均 `[1,0,0,0,1,0]`（`|n_z|=1.0`，余量 0.1） |
| IOP 缺失 ⇒ 准予入围 + `iop_missing` 披露（`:243-244`、`:338`） | **不是门，是披露位（如实登记为非判据）** | 仓内 11 条锁定测试的 `_write_ct` 不写 IOP（`test_survey_series_select.py:47-82`），做成拒绝会让所有组被拒 → `SystemExit(1)` → 这 11 条**全部失败**（这条理由经复核为**真**，与上文被否方案③的假理由不同）；老设备导出确有缺 IOP。`:148` 只钉"入围 + 打印披露"。本机 13 目录 `iop_missing=False` ⇒ 当前不触发 |
| 组间比较用去重后层数（`:341-349`） | **实义** | 修既有错误比较（旧口径去重前 `len(grp)`）；`:163` 是直接反例（10 层含 5 重复 vs 6 层） |
| `0.05 <= PixelSpacing[i] <= 1.5`（`:463`） | **实义** | 反例 PS=2.4（`:316`）；端点闭合；本机实测取值 0.35（10 个 synth 目录）与 0.7（演示/上传 3 目录），距上界余量 0.8mm、距下界余量 0.30mm |
| `0.05 <= slice_gap_measured <= 3.0`（`:464`） | **实义** | 反例 gap=5.0（`:326`）与 gap=0.01（`:332`）；本机实测 0.7（synth）/ 1.0（演示），重叠重建实测 0.3mm（`README-输入规范.md:14`）也在区间内 |
| 矩阵 / 层数绝对门 | **明确不做** | `:347` 钉死 4×4 / 19 层放行；理由见下"被否方案" |
| `z_structurally_ok` 一类键 | **不得入新门** | 沿用 #76 段同一纪律（停工的 `die` 在 `return rec` 之前 ⇒ 能返回的 rec 该布尔恒真，属构造性恒真的假闸门，见 `run_all.py:445-448`） |

### 被否方案（四条，逐条正式落点 + 数据依据）

① **`rows >= 256 and cols >= 256`——否**：仓库自合成演示数据即 96×96（`scripts/make_synthetic_ct.py:56` `ROWS = COLS = 96`；`out/synthetic-ct/slice_000.dcm` 实测 `Rows=96 Columns=96`）。本机 3 个演示/上传目录全是 96×96（`out/synthetic-ct`、`out/e2e-state-20261102-234820/uploads/20261102-234836`、`out/e2e-state-20261102-235512/uploads/20261102-235527`）⇒ 该门会拦掉**全部**演示/e2e 流程。

② **`n_slices_selected >= 30`——否**：派工书记录的真实放行病例「20 层序列缺 1 层 IPP ⇒ selected=19」会被该门制造新假拒绝；本机可复现的最小反例是锁定测试 fixture 8–12 层（`test_survey_series_select.py` 全 11 条直接调 `survey_dicom`）与 `:163` 里胜出的 6 层组。**限制如实记录**：19 层那条无法本机复发（见下"数据可用性"，真数据根不在本机），按派工书原始记录引用，未独立复测——两条并列写明，不用合成数据冒充真数据结论。

③ **在 `survey_dicom` 内部直接 die——否**（规格决定 + 三条实义理由）：
   - **规格明文**：任务书「被否方案」直接否掉这条（门放消费点，是规格决定，不是实现偏好）；
   - **语术会串**：`survey_dicom` 是 run_all/server 共用的**测量原语**，它的 `SystemExit` 在 web 侧统一落进 `server.py:2150-2152` 的 `except SystemExit` → `server.py:2157-2163` 的通用「DICOM 头普查（层序结构断言）」⛔ 卡 ⇒ 用户看到的是"层序结构断言 FAIL"，而不是"重建适用性断言 FAIL"，专有诊断信息丢失；
   - **次序有规格要求**：S1 要求本门 `die` 位于维度动态断言之后（`run_all.py:1007-1008` → `:1011-1013`），并带 exit 2。
   - **更正（R1）**：上轮此处曾写"门放进 `survey_dicom` 会打坏那 11 条锁定测试"——**该理由与事实相反**：锁定 fixture 固定 PS=0.7 / ST=1.0 / z 整数步长（`test_survey_series_select.py:47-82`），全部落在门区间内，放进去并不会被拦；该表述已删除，今后不得据此论证。反例落点 `:360 test_survey_dicom_does_not_die_on_4x4_bad_spacing` 固定的是"门在消费点"这一事实，与被打坏的说法无关。

④ **IOP 缺失即不准入——否**：仓内 11 条锁定测试的 `_write_ct` 根本不写 IOP（`test_survey_series_select.py:47-82`），做成拒绝会让所有组被拒 → `SystemExit(1)` → 这 11 条**全部失败**（这条理由经复核为**真**，与③的假理由不同，它依赖的是"缺 IOP 组会被整体拒绝"）。且老设备导出确有缺 IOP 的真实形态。改为「存在则必须轴位；缺失则准予入围 + `iop_missing` 披露」（`:243-244`），反例落点 `:148`。

### 本轮开放项（不并入上文 #76/#79 那段冻结列表）

- **`rejected_series` / `admitted_series` 诊断止于 stdout**：两组结构只进 `read_ct_series` 的返回值与终端摘要，未进 `manifest`（`run_all.py` S1 只把 `ignored_series` 等既有键写入 rec），也未进 web 拦截卡（`server.py:2144-2149` 白名单不含它们）⇒ 工作台上看不到"哪个组被拒、为什么被拒"。与开放项 **#84/`die` 不带消息** 同型（诊断算了但没人消费），登记为开放项，本轮不改（改它=动 manifest 契约与 web 白名单，属规格外）。

### 数据可用性（本轮实测口径）

- 实测脚本：`%TEMP%\T2-suit-check\check.py`（只读，直接调 `run_all.py#survey_dicom` + `airway_geom.read_ct_series`，只输出计数/数值，不落患者派生产物），结果 `%TEMP%\T2-suit-check\report.txt`。
- 本机可复跑 **13 个目录，放行 13 / 停工 0**：`out/synthetic-ct`、`out/e2e-state-*/uploads/*` ×2（均 48 层 / 96×96 / PS 0.7 / gap 1.0）、`C:/qidi-synth-work/dicom/synth-001..010`（230–232 层 / PS 0.35 / gap 0.7 / `admitted=1 rejected=0`）。
- `#76/#79` 段落所述"真实数据 16 个序列目录"本轮**无法复发**：交接文档给出的真数据根 `F:\比赛项目\罕见无界黑客松\赛题3-鼻腔气流分析\参赛群资料`（`交接文档-2026-10-16-管线线.md:21`）在本机不存在（`os.path.isdir(...) = False`）。该限制如实登记，不以合成数据冒充真数据结论。

## 2026-11-05 预检门登记续：T3 survey 只读头包装（A2-Q2）

> 本登记由指挥官依据「编码手实证报告 + 指挥官实测 + step-5 审计席裁决」汇编——T3 编码手会话（deepseek）三次被 AMD 池 429 切断，未能自写草稿；证据链完整可复放。

### 登记表（#89 本体）

| 项 | 内容 |
|---|---|
| 编号 | **#89** |
| 来源 | A2 对抗审计 Q2：预检把整个目录像素读进内存（+91MB，psapi/tracemalloc 双机制），web 请求路径内同步调用 |
| 定级 | P0 相邻（web 进程 OOM / 请求超时） |
| 修复动作 | `run_all.py` `survey_dicom` 内 `_DicomHeaderOnly` 上下文管理器：thread-local 作用域拦截 `pydicom.dcmread`（显式只读 kwarg 透传；压缩/未知语法整读透传；非压缩按文件原始字节判像素元素头完整性、按文件实际 tag `setattr` 空占位）。`airway_geom.py` 零改动 |
| 内存实测（指挥官，基线 = `a0fe149` worktree） | synth-001/005/010：tracemalloc 50.21–52.07 → 3.40–3.43 MiB；psapi 峰值工作集 101.55–103.41 → 54.62–55.20 MiB（双机制同向，降 47–49 MiB）；`n_slices_selected` 三目录逐一相等（230/230/232） |
| 验证 | 全量 pytest **248 passed / 8 skipped / 0 failed**（指挥官亲跑）；11 条锁定测试未动 |
| 状态 | 已修复 · 待签结 |

### 登记表（#90 返工：step-5 独立审计 3 项）

| 项 | 内容 |
|---|---|
| 编号 | **#90** |
| B1（BLOCKING） | 并发二次进入作用域：旧实现锁外采集 `_HDR_LOCAL.orig = pydicom.dcmread`，线程 B 进入时捕到代理自身 → RecursionError（threaded server 两并发上传必炸，被 `except Exception` 吞成假拦截）。修：orig 采集移进锁内且只认 `_HDR_SAVED`，代理头加 `orig is _dcmread_header_only` 保险 |
| B2 | Deflated 传输语法 `is_compressed=False` 被当非压缩 → 只读头分支拿不到像素 → 静默分叉。修：正向白名单（`is_transfer_syntax and not is_compressed and not is_deflated`） |
| B3 | 非传输语法 UID 的 `is_compressed` 抛 ValueError，`getattr` 默认值不吞 → 冲出。修：白名单判定包 `try/except (ValueError, AttributeError)` |
| 回归钉 | `test_survey_header_only.py` 10 例：干净目录 rec 逐键相等 / 截断文件两侧都收下 / FloatPixelData-only 两侧都跳过 / 压缩透传 / kwarg 透传与作用域恢复 / 读失败不吞 / **并发二次进入不递归** / deflated rec 相等 / 垃圾 TS 不抛 ValueError / implicit VR LE 覆盖 |

### 登记表（#91 实证记录与开放项）

| 项 | 内容 |
|---|---|
| pydicom 3.0.2 截断行为实证 | 截断像素值**不抛错不告警**，`fp_read(length)` 读多少给多少 → 短 PixelData、survey 与 step1 两侧都收下（任务书 v1「EOFError→静默跳过」系据审计席读码推断，被编码手 5 组截断探针证伪——见 RUBRICS R-023） |
| 残留开放项 | ① step1 对截断像素文件在 `pixel_array` 处崩错（既有缺陷，T3 不修）；② `rejected/admitted` 类诊断键同样未进 manifest/web 卡（与 #84 同型）；③ step1 子进程并发仍乘性放大机器总内存（N×~50MB，web 信号量延后） |
| 关闭证据取代 | `:207-217` #76/#79 表中 `run_all.py` 行钉的 blob md5 已被 T3 改动取代，签结时以本提交 blob 为准 |
| 墙钟纪律 | 全程未以任何墙钟比值作门（A2 实测方向随文件缓存翻转） |

### 反例 / 谁接住 / 实义判定（#89 三件）

- **反例**：`test_concurrent_scope_entry_no_recursion`（旧实现必 RecursionError）、`test_deflated_*`（旧实现静默跳过该层）、`test_bogus_transfer_syntax_*`（旧实现抛 ValueError）、截断/Float-only/隐式 VR 三形态
- **谁接住**：survey 只吃头字段故拦截无消费方影响；step1 子进程整读不受影响（进程隔离）；web 路径经同一 `survey_dicom` 自动获得只读化
- **实义判定**：包装器等价性 = 「复刻 pydicom 收录语义」而非字节数校验——截断收下、Float-only 跳过、元素头不完整交整读，均有测试逐形态钉死；实义非重言

## 2026-11-05 预检门登记续：T1 干净克隆测试全绿（A2-Q4）

> 本登记由指挥官依据「前序编码手残留实现审查 + 指挥官 F3 实证」汇编；workbuddy 通道完成 bootstrap 两脚本同步。

### 登记表（#92 本体）

| 项 | 内容 |
|---|---|
| 编号 | **#92** |
| 来源 | A2 对抗审计 Q4：干净克隆跑测试 5 红（3 条 webapp/tools 已修于 `33a6c77`；剩 2 条依赖故意不入库的 15MB 查看器产物） |
| 定级 | 演示场景阻断（克隆者无法一键演示） |
| 修复动作 | ① `tests/conftest.py` session 级 autouse fixture：产物缺失时调 `scripts/build_pa_placeholder.py` 生成最小占位（内嵌四个库内已公开聚合数 18.45/51.9/48.1/66.2 + 合成几何 + 两行式诚实声明），提交包在场则复制真产物（堵 skip→fail 迁移）；② `tests/test_clean_clone_artifact.py` 机审兜底（产物必须存在，不允许 skip）；③ `scripts/bootstrap.ps1|sh` 增 [5/7] 生成步（失败仅 Step-Warn，ps1 保留 BOM） |
| 反例 | `tests/test_clean_clone_artifact.py`（干净克隆形态产物缺席即红）；两条目标用例本身（isfile 判据） |
| 谁接住 | fixture 在 session 开始补齐；bootstrap 装机时补齐；两处同一生成入口（`build_pa_placeholder.py`） |
| 实义判定 | 两条目标用例判据只有文件存在性（server.py:3432-3433），0 字节文件即可满足——本任务不放宽任何判据，只补产物；实义非重言 |
| 验证 | F3 真克隆实证（指挥官，Python 3.12 + `P0_CT_BASE`/`DATA_ROOT` 均置空）：段 1 基线 3 failed（两条目标 + `test_check_17features_is_green` 既有红）；段 2 叠加改动后 **1 failed（仅剩那条既有红）/ 238 passed / 16 skipped**——两条目标用例由红转绿，无新增失败 |
| 状态 | 已修复 · 待签结 |

### 登记表（#93 已知限制与开放项）

| 项 | 内容 |
|---|---|
| 既有干净克隆红（不在本任务射程） | `test_check_17features_is_green`：`webapp/plus/` 被 .gitignore 屏蔽，17 功能查看器检查在干净克隆必红——单列上报，**未为凑绿扩大改动范围** |
| bootstrap 环境敏感性 | `py -3` 在装有 Python 3.15 的机器上解析到 3.15，requirements 钉版（numpy 2.5.4 等）不支持 → pip 安装失败（实测）；本机 F3 用 Python 3.12 复现通过。bootstrap 的 Python 版本下限约束需另批明确（QUICKSTART 现称 3.10+，与钉版实际口径不符） |
| 产物性质 | 干净克隆形态下 pA 查看器为合成占位（非 20261002 冻结资产），已在 `从零复现.md` 披露；`server.py:424` 的 15,069,209 B 证据串与本地 15,036,993 B 至少一处过期（未改，另批核实） |
| 关闭证据 | F3 两段式命令与输出见派工记录；套件 238 passed / 16 skipped（叠加态，本机 DATA_ROOT 未设） |

## 2026-11-05 补审登记：T2/T1 独立实现审计（step-5 席，646s）

**裁决：T2（fc2ed80）可签结；T1（bc884e7）可签结；0 BLOCKING。** 审计范围：T2 准入五条逻辑逐行核对（Modality 归一化/IOP 三态/n_z 公式与 0.9 闭边界/去重后 n 口径/全组被拒路径）+ 两处消费点 + 白名单 12 键 + 绝对门无回潮 + 红线 intact；T1 fixture 六条 + 生成链九条 + bootstrap 两脚本 + 测试机审可判性。对抗性边界输入（空目录/单层/同 UID 混朝向/IOP NaN/inf/"abc"/并列层数）均未发现与规格不符。

**非阻断遗留（登记备查，不阻断签结）**：
- N-1：`scripts/build_pa_placeholder.py` 与 `tests/test_clean_clone_artifact.py` 共 6 处注释行号 off-by-one（test_api.py 断言值实为 :329-332）——**本次已修**（commander 机械修正，审计席给定值）；
- N-2：本段以上 :264 等对 `run_all.py` 的行号引用因 T3（+138 行）已漂移，下次触碰时更新；
- N-3（规格澄清）：T2 对「IOP 分量不足 6 个」的口径 = missing 披露放行（代码 `airway_geom.py:210-211` docstring 已有，任务书未写明）——后续修订任务书时补；
- N-4（归因不对称）：run_all 适用性门在层序门前（:1149 vs :1159）、server 相反（层序卡 :2157-2170 在前）——双败输入的归因文案两端口径不同，统一或文档化列为后续项；
- N-5（验证局限）：审计席无 shell，diff 边界已由指挥官实核补上——`git diff --stat` 两提交范围（T2 6 文件 +878/−31；T1 7 文件 +438/−29）、`tests/test_api.py` 两提交零触碰、`git ls-files` 全仓 >1MB 仅 3 个历史在位文件（webapp/demo/viewer.html、webapp/demo/viewer_data.js、code/viewer/viewer_data.js），两任务均未新增/修改大文件入库。

---

## 2026-11-06 指挥官合并登记：T12-0 / T4(+R1) / T6 / T10-a（A3 整改线 1 前四棒）

> 来源：四份 `ledger-draft-*.md` 由指挥官合并定号；各草稿全文保留在原文件。套件基线演进：248 → 260（T4 +12）→ 276（T6 +16）→ 308（T10-a +32），均为指挥官在各提交时点亲跑，0 failed。

### #94 T12-0 equivalence 作废标记冻结（提交 `03a2c6b`）
| 项 | 内容 |
|---|---|
| 反例 | `equivalence-report.md` L1 表 pA=18.747088(+1.61%) PASS 与判定行「Run-A 三例全部过 ±2%」——被 `W8-验收.md:37` 明令「版本漂移（M3→W8），未解释，不得作为 PASS 依据」；`W6-验收.md:73` 实测新默认 18.444(−0.03%)。后出验收作废先出报告依据，先出报告未同步（证据链版本控制失效，E3-1） |
| 谁接住 | 文档头版本锚点块（各值标来源版本+日期；现行 PASS 依据以 T12 按当前 HEAD 重跑值为准，**不以文档时间先后判定**）+ F1/F2 作废标注（:42/:68，新行号 :48/:70）+ F4 pB 仅标旧快照（W8:38 +0.126% PASS 未作废）。T12-0 只冻结不改数值 |
| 实义判定 | 纯文档动作：diff 8 行纯新增 0 删除，表格数值/结构逐字未变 |
| 验证 | W8:37/:38、W6:73 引文逐字核验；套件 248 passed/8 skipped/0 failed |
| 状态 | 已修复 · 已提交（未推送，待批准） |

### #95 T4 门禁话术诚实化+die 消息透传+z_gap 暴露（提交 `8e36d68`，含 R1 返工）
| 项 | 内容 |
|---|---|
| 反例 | A2-Q3/CF1/CF2：`z_structurally_ok` 三条件两条构造性恒真却停工文案宣称为「层序结构断言 FAIL」；「缺IPP层数」误称读层器跳过文件总数；CF3 恒真键进 web 白名单+日志恒打印；CF7/#84 `survey_error` 裸 "2"；CF8/#81 四 z_gap 键未暴露；B10 恒真日志；B11 FATAL 不走 stderr |
| 谁接住 | `structurally_ok_failure_message()`（只报实际失败条件，恒真项标非判据，两处共用）；`DieExit(SystemExit)` 承载 msg（退出码保持数字 2/3）；FATAL 同行 stderr；白名单移出恒真键+纳入四 z_gap 键；`survey_error` 取 `DieExit.msg`；gate 更名「读层完整性」；**判定式逐字节未动**（D5 默认保留+披露） |
| 实义判定 | 措辞/呈现/机制层；`z_structurally_ok` 三条件与 5% 容差、PII、T2 准入零改动（diff 实证） |
| 验证 | 新测试 12 例；R1 正当连带更新 test_series_suitability 白名单断言 12→15 键（编码手撞冲突停手上报，指挥官裁决后返工）；套件 260 passed/8 skipped/0 failed |
| 遗留 | `structurally_ok_failure_message()` 调用契约未硬钉（仅设计上门 FAIL 时调用）——**后续任务书补 docstring/断言**（复审观察项 3）；D5 若改判「删恒真条件」须动判定式+重跑回归+再改白名单断言，建议独立小补丁（复审提醒：成本已变） |
| 状态 | 已修复 · 已提交（未推送，待批准） |

### #96 T6 硬编码几何锚定批修（提交 `553135b`）
| 项 | 内容 |
|---|---|
| 反例 | B1（P1）：step4 `spacing=(0.35,0.3496,0.3496)` 写死与 DICOM 头脱钩（同链路 step1/3/5 均头推导），STL 尺寸系统性偏差无披露；B8：step5 CENTER 锚定参考例种子值，非参考例几何错位 |
| 谁接住 | B1：`read_case_spacing()` 头推导（round4 同 step5 口径）+四分支 fail-closed+`assert_mask_normalized()` 次选断言；B8：种子标「仅参考数据集有效」+`_CENTER_IS_REFERENCE`+非参考例质心重算+QC/日志显式降级（次选，参考例数值分支零变化） |
| 实义判定 | 写死常量零残留（AST+字面量双查）；STL 尺寸随头变化（合成例实测 rtol 2e-3）；**round(...,4) 张力指挥官裁定：不构成换皮写死**——该精度是 step5:83-85 对同量（SX/SY/SZ_FULL）的既有口径，且派生值逐例变化（测试实证），非为回归绿把旧值 rounding 成新值 |
| 验证 | 新测试 16 例；套件 276 passed/8 skipped/0 failed |
| 遗留 | 参考例（患者A）逐字节回归未实测（本机无基线）——须真数据环境 `sha256sum` 复跑后关或转开放项；step4 新增必需 DICOM 输入属行为变化（run_all 不调 step4，集成调用方参数未验证） |
| 状态 | 已修复 · 已提交（未推送，待批准） |

### #97 T10-a 结论层口径批修·v6 侧（提交 `2c40f9e`）
| 项 | 内容 |
|---|---|
| 反例 | DF1：常人带两处口径互斥（50/80 vs 30–150 literature band），同患者相反判读；DF4：v6 输入硬编码无溯源、外推不区分、无合成标注却冠 Patient A；DF5：「工程推荐/常人带中部/安全余量」撞报告层禁词；DF6：:75 写死叙事与实测反解值矛盾（4.238 不在「介于 4.37 与 8.24 之间」）+None 崩 |
| 谁接住 | 三文件统一「内部工程/演示阈值（非文献参考带）」+`classify_demo_band`（同值同结论）；v6 输入文件读入+md5 溯源（不在场显式标硬编码演示值）；外推段虚线+标注；禁词/冠名全清过 wording.py 口径；:75 括号叙事由 v30+档位表动态生成+None 分支；**演示值路线**（涉 pA/ΔP 一律内部演示值，不引归档真值，T11 对账入口） |
| 实义判定 | 数值口径统一+标注链修复；判定逻辑层无（本片不涉门） |
| 验证 | 新测试 32 例；套件 308 passed/8 skipped/0 failed；禁词残留 grep 零命中 |
| 遗留 | v6 输入文件（narrowing_qc.json/诊断报告4）本机不在场，溯源链末端未闭环（T11 对账入口）；followup 侧 DF2/DF3/DF7/DF18 属 T10-b 未派 |
| 状态 | 已修复 · 已提交（未推送，待批准） |

### #98 T10-b 结论层口径批修·followup 侧（提交见 git log）
| 项 | 内容 |
|---|---|
| 反例 | DF2（P1）：`conclusion.py:69` 对每对 diff 无条件写死「两例均为 1500 步平台（未达 1e-4）」而 metrics.py 已读 converged/n_iter（能判而不判）；DF3（P1）：「方向相反」守卫只判左侧×总压降，右侧进字典从不参与（假阴性）；DF7（P1）：随库分发的 examples/diff.md 用真实随访话术却无任何合成标注（course_card 无 case_kind 入参）；DF18（P3）：该副本与 HEAD 输出格式漂移 |
| 谁接住 | `_convergence_caveat()` 四态据实生成；守卫改逐行判定只写实际触发行；`case_kind` 入参+run_diff 从 provenance.json data_class 推导，synthetic 时 headline/caveats/患者语言三处注入「本轮为合成体模、非真实患者、非临床结论」；examples/diff.md 真跑重生成 |
| 实义判定 | 措辞/数据驱动层；metrics.py 等读数口径零改动 |
| 验证 | 新测试 29 例；套件 337 passed/8 skipped/0 failed；examples 三处标注 grep 实证；真跑一对（generated_at 2026-11-06T11:23:02 为产物非回填） |
| 遗留 | 前端是否消费新文案未验证；除 synth-001→005 外未跑其它对（三态由单测覆盖）；T11 对账入口本片不做 |
| 状态 | 已修复 · 已提交（未推送，待批准） |

### #99 T12 片 A — solver 证据链文档冻结与更正（2026-11-06，指挥官合并）
| 项 | 内容 |
|---|---|
| 反例 | E3（P1）：`equivalence-report.md:8` 写死「按当前 HEAD（`6dbb517`）重跑值为准」，T12-0 已提交文档留旧 hash 与 v1.2「派工当日 HEAD」冲突；E1（P1）：L0 D-1 状态三方矛盾（:25 表格「PASS/已解除」vs :29 判定段「门未过/开放项」vs :115 未决项表「已解除」）；E5（P2）：Backstep 验证台未实现却判「L0 部分通过」；E6（P2）：Run-B pA 失稳证据不可复核；E12（P3）：L3「044/004」笔误；#95 遗留：`structurally_ok_failure_message()` 调用契约未硬钉 |
| 谁接住 | :8 删 `6dbb517` →「以派工当日 HEAD 重跑值为准」；§1 判定段整行更正为「Δp/dx 门已过…以实测复跑为准，D-1 已解除；L0 仅 Poiseuille 已建验证台，Backstep 未覆盖，故不构成完整通过」；§2.2 补失稳 trace 摘要未入库说明；`①044`→`①004`；W6/W8 各补 pA 版本标注（来源版本+日期，三文档不强求数值一致）；`run_all.py` 补调用契约 docstring + 首行 `assert not rec.get("z_structurally_ok", False)` 防御性断言 |
| 实义判定 | 纯文档/注释/断言层；`equivalence-report.md` 表格数值逐字未动；`z_structurally_ok` 三条件、5% 容差、PII、T2 准入判定式零改动 |
| 验证 | 编码手靶向 `pytest code/pipeline/tests/test_gate_messages_honest.py -q` → 12 passed；**指挥官第 2 层抽验**：`git diff --stat` 4 文件 +11/−4 与回执一致、表格行零改动、断言上下文亲读；**全量 337 passed / 8 skipped / 0 failed（指挥官收尾跑，101.82s）**，与基线一致无新增红。派工通道：CodeBuddy 原生子智能体（默认模型），单行指针读任务书 |
| 遗留 | **片 B 未做**：按当前 HEAD 重跑刷新 L1/L3、E4 两步门证（`cargo test --release -- --ignored` + ny=21 红证 + ny=41 绿证）、E2 干净克隆重建链；E1 择一更正依据文档内已记录的实测复跑证据（双审计官 0.1371%~0.45%），非本轮 current-HEAD 重跑。真实病例 L2 场相关 / 22 例 WSS 归档重测未复核 |
| 回执勘误 | 编码手回执称「台账 #94–#98 盘上未检索到」——**指挥官实测 `conditions-ledger.md:429/438/448/458/468` 五条均在**，该句为检索失误，不进正本；其余三要素（命令+输出 / 改动摘要 / 主动声明未验证项）齐备 |
| 独立实现审计 | **2026-11-06 补做**（提交后补派只读子智能体，只给规格+commit hash+验收命令，不信自述）：逐条核 6 项——① 表格数值逐字未动（完整 diff 全部增删行 + 两版全表格行 diff，非只靠 `grep ^\|`）✅；② E1 三方矛盾真消解（`:28/:32/:123` 全「已解除」，旧「门未过」无残留）✅；③ 新 assert 无误伤（全树 4 处调用点亲查，生产 2 处均在门 FAIL 分支内；判定式零改动）✅；④ 射程实质达标（禁改区 diff 全空）✅；⑤ W6/W8 版本标注无新矛盾（日期经 git log 实证）✅；⑥ E12 只改编号、E3 文档头自洽 ✅。**裁决：0 BLOCKING 可签结**，靶向 `12 passed` 复跑 |
| 审计遗留（非返工） | (a) **形式性射程偏差**：`conditions-ledger.md` 原未列 §0 可改，但 #99 系指挥官本人纯追加合并（编码手已明确回避），已在任务书 §0 补规格追认闭合；(b) **新 assert 防回归未钉**：两条现有测试 `rec` 均无 `z_structurally_ok` 键 ⇒ 断言分支未被触发，docstring 只列 `run_all.py:1208` 漏列 `server.py:2165`。建议补一条「`rec` 含 `z_structurally_ok=True` → 断言抛 AssertionError」的反例测试 + docstring 补第二调用点，走独立小补丁 |
| 审计席回执勘误 | 审计席称「origin/master 仍 `6dbb517`、本地领先 3 个提交」——**指挥官实测领先 8 提交**（`03a2c6b`…`4af6370`），该句为 `git log` 截断误读，不进结论；其「全量套件未跑」属只读审计射程限制，全量 `337/8/0` 已由指挥官第 2 层跑过，不构成缺口 |
| 状态 | 片 A 已修复 · 已提交（未推送，待批准）· **独立审计 0 BLOCKING 已签结**；片 B 待派 |

### #100 三步契约分层 v1 — 第一步 step5 契约拆分（2026-11-07，指挥官直接改）

| 项 | 内容 |
|---|---|
| 反例 | 用户 2026-11-07 定三步路线：①建气道模型（**不需鼻塞虚拟植入**，即「上线」）②按气流设计 **3D 打印外部佩戴鼻塞**（非手术植入）③三态对比正常人带。真 CT 实证（会话纪要十八节）：`run_all.py:807-810`、`step5_export_viewer_data.py:1390-1392` 把**第二/三步的三档占位数据**（`dP_1/2/3mm_Pa`、`volumes_cm3`、`dP_Pa`、`band_Pa`）绑进第一步 step5 契约**必需字段** ⇒ standard 档求解跑通（FlowScope `backend: custom`、ΔP 27.646 Pa）却判 `deferred_contract_incomplete` 不导出 3D。属阶段错位；且 `step3/step4` 的「鼻腔内侧壁壳层植入体」已被用户排除（需手术），物理上不等效于外部空心管鼻塞（R-1 内孔+缝隙双通道） |
| 谁接住 | 落盘《规格-三步契约分层-v1-2026-11-07.md》；`run_all.py`：`assemble_contract` 返回 `(contract, core_missing, stage2_missing)`，S6/S7 闸门只看 `core_missing`、占位缺失只标注，`--allow-partial-viewer` 降为 quick 档几何开关（不再作闸门）；`step5`：`_META_REQ` 去 `curve`、检查只拦 `_CORE_METRICS_REQ`（7 项）、`_METRICS_REQ` 沿用原 10 项**原序**、`--ph-dir` 默认 `None` 且各使用点 None 安全；`server.py:1997` 解包适配三元组；新增 `tests/test_stage1_contract.py` 9 条（含 3 条 subprocess 行为级） |
| 实义判定 | 纯契约/闸门/标注层；判定式（PII / 准入 / 5% 容差）零改动；红线保持——核心字段缺失仍 `SystemExit` 中止、不写盘；严禁伪造三档数字、严禁套用其他患者数字或几何；`step3/step4` 植入体实现本轮不动 |
| 验证 | `py_compile` 通过；契约函数实证 `core_missing=[]` / `stage2_missing` 恰 6 项；**全量 346 passed / 8 skipped / 0 failed（354 tests / 0 failures / 0 errors，104.69s）**，较基线 337 + 9 条新回归；真 CT（195 层，`20261019-215629`）走 `/api/upload → /api/run {"solve":"local"}` **不传 mode、不传 quick** → run_all 日志「第一步导出：第二步占位档字段未做…不阻断第一步」，**新 state-dir 内 `step5_deferred-*.json` 数量 0**；本机 pytest capture 插件报 `ValueError: I/O operation on closed file`，需 `-s --junitxml` 取权威计数，与代码无关 |
| 独立实现审计 | 补派只读子智能体审未提交工作树（8 项核查）。**首轮裁决有 BLOCKING 不可签结**：B1 `server.py:1997` 2 变量解包 3 元组必崩、B2 `_METRICS_REQ` 重排破坏 pA 逐字节不变、B3 新增测试全为源码子串断言且规格声称的两条行为测试不存在。**三条均已返工**（见上「谁接住」），复核 `test_stage1_contract.py` 9/0/0、全量 354/0/0/8 ⇒ **0 BLOCKING 可签结** |
| 遗留 | **standard 档仍未出 3D**：契约放行后暴露下一层 `step5` F3 六板门禁 `board4_lr_ratio_change_le_0.1pct` FAIL（`airwayMesh` 0.2236% / `airwayCavity` 0.2571%，阈值 0.1%；standard 做 Taubin 平滑，quick 跳过平滑故板④ SKIP），`sys.exit(3)` → `status=blocked`。此前被 deferred 长期遮住，与本轮改动无关。处置待裁决：建议第一步改用原始 marching_cubes 等值面、不做视觉平滑（把「跳过平滑」从 quick 专有提升为第一步通用），不建议放宽板④ 阈值。`step5:40/47/125/38-39` 仍残留患者 A 默认值（`--vtu` / `--skin-data-js` / `SHARED_VIEWER_DATA_JS` / `case-prefix=pA`），主路径靠显式覆盖，另行登记。审计未独立复核项见规格 §9 |
| 回执勘误 | `out/e2e-ct-run-20261107/cases/pX/step5_deferred-pX-v1.json` 是 **8080 改代码前旧实例**留下的旧文案产物，非本轮 8081 新实例结果；审计曾据工作树该文件质疑「deferred 数量 0」，口径已澄清（以 `out/e2e-stage1-20261107/` 为准） |
| 状态 | 第一步契约分层已修复 · 已提交（未推送，待批准）· **独立审计返工后 0 BLOCKING 已签结**；F3 板④ 门禁待裁决（已由 #101 闭合） |

### #101 第一步档位解耦与验收判据修复 v2（2026-11-07，指挥官实施）

| 项 | 内容 |
|---|---|
| 反例 | `2502ff1` 契约放行后，真 CT 走 standard 档仍 `status=blocked`、`step5 exit 3`。独立根因诊断席复现并裁决「不是板④ 这一个问题」：**单一直接停工点**（`board4_lr_ratio_change_le_0.1pct` FAIL）+ **架构缺位（真根因）**——`--quick`（300 步+z 降采样）、`--allow-partial-viewer`（→`--single-case` 跳过 Taubin 视觉平滑）、`/quick` 产物根（由 mode 决定）是三个互不耦合的独立参数，只是恰好写在同一 `if mode=="quick":` 分支；第一步「全精度 + 不平滑」无对应档位。另有门禁设计矛盾（0.1% 阈值 vs Taubin 固有 0.22–0.26% 漂移）与共享目录污染（按 case_id 单键 last-writer-wins）。详见规格 §8/§9、方案 v2 §0 |
| 谁接住 | 落盘《方案-第一步档位解耦与验收判据修复-v2-2026-11-07.md》（v1 经独立审计裁决「过度设计 + 2 BLOCKING，不可签结」，转历史；v2 经独立复审 2 BLOCKING 回填后签结）。**实施 4 文件**：`server.py`（① `:1508` 把 `--allow-partial-viewer` 由 quick 分支移出为单个 `if mode=="quick" or rec.get("kind")=="upload":`；`--quick`/`--voxel-z`/两条 `append_progress` 严格留 quick 分支；② 新增 `_clear_stale_staged_viewer(rec)` 仅对 `kind=="upload"` 清三类旧舞台化文件，run 开头调用；③ `stage_viewer_if_exported` 末尾把三类文件 sha256 写入本例 `out_dir/viewer_stage_sha256.json`）；`run_all.py` 仅 docstring + argparse help 文案（去掉「仅用于患者快速档」）；新增 `tests/test_stage1_v2_flags.py` 8 条行为级；`tests/test_stage1_contract.py` 仅 1 条 docstring 口径 |
| 实义判定 | **判定式（PII/准入/5% 容差）零改动**；`assemble_contract` 三元组与契约分层零改动；`step5`/`run_all` **执行逻辑零改动**（只文案）；`step3/step4` 未动；`F3_LR_RATIO_TOL` 未放宽；未新增 `--raw-surface`/`RAW_SURFACE`；未改走 quick；未回退 `2502ff1`；未改前端 URL 契约；pA/内置/demo 冻结副本未触碰 |
| 验证 | `py_compile` 通过；靶向 26/0/0；**全量 354 passed / 8 skipped / 0 failed（362 tests / 0 failures / 0 errors，170.03s）**。**真 CT 195 层走 `/api/upload → /api/run {"solve":"local"}`（不传 mode、不传 quick）→ `status=done`**：`step5/viewer_data.js` 1,838,571 B、`meta.smoothing_skipped=True`/`partial=True`/`placeholders=[]`、7 项核心 metrics 键序不变；`run_all_manifest` 的 `args.quick=false`/`args.allow_partial_viewer=true`/`args.max_iter=1500`/`args.voxel_z=2.0`、`S7_step5.status=exported_partial`；`step5_deferred` 数 0；`viewer_stage_sha256.json` 三类 hash 与 `webapp/cases/pX/` 全 match、`/viewer/pX` 200、iframe 目标 `viewer_single.html`（2,665,086 B）hash match。**v2 §2.3 四项判据全 PASS**。证据 `out/e2e-v2-20261107/v2-trace.jsonl` |
| 独立实现审计 | 补派只读子智能体审未提交工作树（9 项核查），**裁决 0 BLOCKING 可签结**：§2.1 严格按方案、`--quick`/`--voxel-z` 仍在 quick 分支、开关只追加一次、产物根未受影响；§3「明确不做」逐文件守住；清理射程限定 kind（BLOCKING A 闭合）；sha256 写本例 state-dir 同一临界区、不含患者可识别信息、覆盖 `viewer_single.html`（BLOCKING B 闭合）；新增测试真实调用 `run_chain_thread` 捕获 argv 非同义反复、8 条可捕获五类回归；junit 362/0/0/8 属实、8 skipped 全为既有冻结资产用例；真 CT 证据独立重算可复现、`exported_partial` 是诚实标注非缺陷、无「临床可用/上线完成」夸大 |
| 非阻断登记（5 条，审计附） | ① 方案 §4「最稳」建议抽纯函数 `build_run_all_cmd` 未采纳，改用 monkeypatch 真实 `run_chain_thread` 捕获 argv（行为级目标达成、生产代码改动面更小，与 §2.1 最小射程一致）；② `/api/full` 的 `_full_chain_impl`（`:2096`）直接调舞台化、**不经 `run_chain_thread` 故不清旧**，共享目录污染在该路径残留（属第二步/参考数据集用途，射程外）；③ `viewer_stage_sha256.json` 写失败被 `except OSError: pass` 静默吞掉（验收脚本 `drive_v2.py` 显式判文件存在，不会假绿；实现层不上报）；④ `drive_v2.py` 的 `PASS_4` 表达式未纳入 `iframe_hash_match`（本次实证该值 true，独立审计已单独核实）；⑤ 提交面：`viewer.html` NOT-IGNORED + `report/`、`shots/`、`webapp/查看器-*.md` 等历史 `??` 产物未忽略，`git add -A` 有带入风险 —— 本笔**显式路径 add** 避开，扩展 gitignore 按方案 §4 另笔 |
| 材料澄清（审计附） | 方案 §2.2「本例 `step5/` 产出的三类文件 sha256」措辞不精确：实现算的是 `webapp/cases/<cid>/` 舞台化产物（`viewer.html` 来自模板、`viewer_single.html` 由 `build_single_file.py` 内联构建），判据 4 比对舞台化产物与 `/viewer` 取回文件，语义自洽；`S7_step5.status=exported_partial` 不是缺陷、无需改 `exported` |
| 流程例外与三层验证（2026-11-07 严格乐团质检复核） | **本轮实施由指挥官主会话直接改代码，未派编码手 Worker、缺 Worker 回执，属不可逆的流程缺口**；台账 #101 表头已自标「指挥官实施」，但正文与交接文档二十三节此前**未把该例外列为登记项**（第 3 层复核第 10 项判 ❌ 登记缺口）。用户裁定「严格按照乐团模式，质检复核」后按 §9 高风险「三层全上 + Router 亲读关键 diff」事后补齐：① 任务书 `任务书-v2实施质检复核-2026-11-07.md`；② 第 1 层实施回执 `回执-v2实施-2026-11-07.md`（三要素齐，主动声明 **11 条**未验证项）；③ 第 2 层 Router 抽验 `抽验-v2-2026-11-07.md`（重跑靶向 8/0/0 + 全量 362/0/0/8 + git 实证，只重跑命令不读实现；`qc-full.xml` 与实施时 `v2-full-junit.xml` sha256 不同 ⇒ 真两次执行）；④ 第 3 层独立只读复核席（CodeBuddy 原生子智能体，13 次只读取证，不信自述独立重算 meta/manifest/hash/iframe）。**复核裁决：技术面 0 BLOCKING 可签结（10 项中 1–9 全 ✅）；流程面按严格乐团标准仍是缺口，事后验证与补证不能倒推成「已完整走过派工流程」**。结论分层记录：**代码/证据可签结；流程合规性 = 已登记的流程例外 + 事后三层验证通过**。复核勘误 2 处已回填方案 v2（standard manifest 顶层 `quick` 实为 `None`/四字段全 absent，非 dict；sha256 算的是舞台化产物自身而非 step5 源产物）。复核建议 4 条：交接登记流程例外（本节 + 交接二十四节已补）、方案两处文字（已修）、`drive_v2.py` 的 `PASS_4` 补 `iframe_hash_match` / `.gitignore` 补 `viewer.html` / sha256 写失败改告警（**按方案 §4 另笔保留，本笔不动代码**） |
| 状态 | **第一步主路径已打通（患者上传 CT → 完整精度气道 3D）** · 已提交（未推送，待批准）· 独立审计 0 BLOCKING 已签结 · **严格乐团质检复核：技术面可签结，流程面记为已登记的流程例外** |

### #102 复核建议另笔补项（2026-11-07，严格乐团派工）

| 项 | 内容 |
|---|---|
| 反例 | 严格乐团质检复核（#101）后按方案 v2 §4「另笔保留」的 5 项：A `.gitignore` 未忽略 `viewer.html`（提交面风险）；B `viewer_stage_sha256.json` 写失败被 `except OSError: pass` 静默吞掉；C 方案 §2.2 要求「源↔舞台化产物一致性硬校验」但实现只算舞台化产物自身 hash（自证）；D `test_stage1_v2_flags.py` 把 `case_slice_dz` mock 成 None，quick 档 `--voxel-z` 无行为级覆盖；E `drive_v2.py` 的 `PASS_4` 未纳入 `iframe_hash_match` |
| 谁接住 | 落盘 `任务书-复核建议另笔补项-2026-11-07.md`（§0 禁改面 / §1 A–E / §2 射程恰 4 文件 / §3 验收 / §4 回执三要素）；**严格乐团派工**：编码手 = CodeBuddy 原生子智能体（Agent `agent-9616cc21…`，19 次调用、非主会话直改）→ Worker 回执 `回执-复核建议另笔补项-2026-11-07.md` → 第 2 层 Router 抽验 `抽验-复核建议另笔补项-2026-11-07.md` → 第 3 层独立只读审计 `复核回执-补项审计-2026-11-07.md`（Agent `agent-73891b42…`，17 次取证）→ 本台账 → 指挥官提交。**改动 3 个进提交文件**：`.gitignore`（+2，新增 `:61` 忽略 `viewer.html`）、`code/pipeline/server.py`（B：`except OSError as e: append_progress(...)`；C：写 JSON 前比对源 `vd` 与 `case_web/viewer_data.js` sha256、不一致只告警、`_doc` 四键不变只新增可选 `stage_source_match`）、`code/pipeline/tests/test_stage1_v2_flags.py`（+30，新增 1 条 quick 档 `--voxel-z` 行为级测试，8→9 条）。E 改 `out/e2e-v2-20261107/drive_v2.py` 的 `PASS_4`，**该文件被 `**/out/` 忽略、不进提交**（任务书 §1E/§2 显式授权的本地证据脚本例外） |
| 实义判定 | 禁改面零越界：`run_all.py`/`step5_export_viewer_data.py`/`step3-4`/判定式（PII/准入/5% 容差）/`assemble_contract` 三元组/契约分层/`F3_LR_RATIO_TOL`/前端 URL 契约全部零入 diff；无 `RAW_SURFACE`；B/C 均**不阻断导出**（无 raise/sys.exit/新增 return）；`diff` 恰 3 文件、`+57/−6` |
| 验证 | Worker 靶向 `9 passed`、主动声明 **7 条**未验证项（非只报成功）；第 2 层抽验真重跑（`qc2-*.xml` 与编码手 `qc-*.xml` sha/mtime/size 全不同）、py_compile OK、`git check-ignore -v` 命中 `.gitignore:61`、`git status` 恰 3 个 `M`；**全量 363 tests / 355 passed / 8 skipped / 0 failed**（158.542s，基线 362/354/8 +1 吻合，8 skipped 用例名与三份基线逐条全同）；第 3 层独立审计 **0 BLOCKING 可签结**，10 项全 ✅，独立重算源↔舞台化 sha256 一致（`ac7f52e3…`） |
| 流程合规性 | **与 #101 不同**：本轮有前置任务书 + 实际派编码手 Worker + Worker 回执 + 三层验证，**不再是「主会话直改」例外**。但按严格乐团七环标准，第 3 层审计时点⑥台账/⑦提交尚未发生 ⇒ 准确表述为「派工与前五环已合规走过、完整链条待台账 #102 与本笔提交收尾」，不把「待收尾」倒推成「已合规」（本行与提交即为收尾） |
| 非阻断登记 | ① `append_progress` 在 `out_dir` 不可创建时可能二次抛错冒泡（任务书 §1B 明文 prescribed 该调用、禁 raise；上游 copy2/写 viewer.html 已先失败；彻底兜底属扩射程，另笔）；② C 的 `fp.read()` 整读 + 比对块无 try（TOCTOU），属既有模式边际放大，分块 hash + try 包裹另笔；③ **盘上 `viewer_stage_sha256.json` 仍为旧四键、`stage_source_match` ABSENT** —— C 新键从未经真实导出写出（任务书 §3 只要求只读脚本核数据前提 + py_compile，属验收射程内未验证项、非缺陷），**待起服务复现运行期写出路径**；④ E 与 §0「`out/**` 只读」字面张力由 §1E/§2 显式授权 + 回执 §3-6 主动声明化解，非阻断例外；⑤ `/api/full` 路径不经清理（#101 非阻断②）仍保留，射程外 |
| 回执勘误 | 编码手回执 `9 passed in 53.41s` 与 junit `time=51.062` 为墙钟 vs 累计用例时间口径差，非造假；首段「无与 §0 禁改面冲突」与 §3-6「E 是 §0 刻意例外」口径不完全一致，**以 §3-6 保守表述为准**；回执/抽验页脚「台账 #102 归档」为前瞻指向（当时 #102 尚不存在）；抽验 CMD4 `check-ignore` 规则与路径连写系 tab 复制丢失，不影响结论；任务书 §2 标题由「恰好 5 个」修正为「恰好 4 个」（指挥官改，规格内容不变，宜留痕） |
| 状态 | **复核建议另笔补项已落地** · 0 BLOCKING 已签结 · 已本地提交（**未推送**，待用户批准；推送前须再跑 §10 可见性闸门） |

### #103 第一步完成与泛化验收 v1.1 · 阶段 0 定尺子 + 阶段 1 冒烟（2026-11-08）

| 项 | 内容 |
|---|---|
| 反例 | 方案 `方案-第一步完成与泛化验收-v1-2026-11-07.md` 经 ai-bridge→atomcode 审计（0 BLOCKING，3 条文字勘误）→ 回填为 v1.1（唯一权威）→ 子代理复审（0 BLOCKING，8 项全过）→ 严格乐团派编码手 Worker 实施阶段 0 + 阶段 1 冒烟。目标：把「任意一个患者上传 CT 出模型」的缺口径子落在「任意」二字，先证伪再补门 |
| 谁接住 | 文档：`方案-…v1.1-2026-11-08.md`（勘误 1 判据 1 注明层厚/算法轴依赖 §6 拍板第 1 项 + §6 限定；勘误 2 新增 §3.5「残留缺陷归属」，如实区分「已由 `a13746c` 补掉」5 项与「仍挂账」4 项挂阶段 0/3；勘误 3 阶段 0 服务实例改「复用 8082 或新起独立 state-dir」；另订正 §4「阶段 5」笔误为阶段 3）。派工：`任务书-阶段0定尺子-2026-11-08.md` → 编码手 Worker（Agent `agent-184d6e73…`）→ `回执-阶段0-2026-11-08.md` → `抽验-阶段0-2026-11-08.md`（第 2 层）→ `复核回执-阶段0-2026-11-08.md`（第 3 层，Agent `agent-8802fbfd…`）。阶段 0 产物全在 `out/e2e-v2-20261107/`（gitignored、不进提交）：`drive_batches.py`(197) 参数化批次驱动 / `batch_manifest.md`(22) 仅目录名+层数 / `breakpoints.md`(26) / `batch-trace.jsonl`(pX2) / `batch-trace-2.jsonl`(pX3) |
| 实义判定 | **F 仓产品代码零改动、0 个 `M`、`git diff` 空**；5 产物全被 `.gitignore:23:**/out/` 忽略。合规铁律实测：两 trace 严格 §1A 白名单 13 字段 `extra=[] PIIhit=[]`，无 PatientName/ID；`drive_batches.py` 无 dcm 头/VTK/图像读取，`.dcm` 仅二进制句柄上传，viewer_data.js 仅 `raw_decode` 取 `meta`/`args` 标量，患者派生内容未进上下文/trace。根因链：pX2 首报 `viewer_data_missing` 经指挥官只读实证为**驱动侧假断点**（产物 1838576 B 落 `e2e-v2/cases/pX2/step5/`，全精度、deferred=0）；真因由指挥官更正为「**单参数绑两目录**」（上传源 `webapp-state/uploads` vs 服务产物根 `e2e-v2-20261107/cases`，编码手自述「传错值」不准确）→ 纠偏拆 `--uploads-root`/`--state-dir` 并复跑 pX3 得 `gate=all_pass` |
| 验证 | pX3 经第 3 层独立 `raw_decode` 重算：`viewer_data.js` 1838576 B / `smoothing_skipped=True` / `partial=True` / `placeholders=0`；`args.max_iter=1500 / quick=False / voxel_z=2.0 / allow_partial_viewer=True`、`S7_step5.status=exported_partial`、`deferred=0`；`gate=all_pass` 逐项一致。`exported_partial`/`partial=True` 合格（第一步缺第二步占位的诚实标注，非缺陷）。pX2 三项 `null` 原样保留未篡改。pX(1838571 B)/pX2/pX3 三者并存未覆盖。**三层验证**：第 1 层 Worker 回执三要素（7+ 条未验证项，非只报成功）；第 2 层指挥官抽验（重跑 trace 解析 / pX3 标量 / 参数拆分 / git 实证，只重跑命令不读实现）；第 3 层独立只读审计（自己重算 10 项全 ✅）。**裁决：技术/证据面 0 BLOCKING 可签结** |
| 流程合规性（如实登记） | **前五环形体齐备**（任务书 → 派编码手 Worker → Worker 回执 → 第 2 层抽验 → 第 3 层审计），后两环（本台账 + 本笔提交）收尾。与 #101「主会话直改」性质不同（本轮确有前置任务书与实际派工）。**但登记 P1 缺口不圆场**：纠偏段（`drive_batches.py` 190→197、breakpoints 重写、新增 `batch-trace-2.jsonl`、复跑 pX3）系两次抽验之间 **resume 同一 Worker 的第二次派工/返工，无独立返工单**；而 `抽验-阶段0:3` 自称「未改任何文件」、任务书 §1D 写「只找断点不修」——两处字面与纠偏改动冲突，回执 §4.6 以「属阶段 0 收尾」自我豁免。按 #101 裁决纪律（事后补证不倒推成已完整走过派工流程），**如实登记为流程登记缺口**：纠偏改的是本轮 gitignored 证据脚本、非产品代码，但「第 2 层只抽验不改」边界与任务书 §1D 字面确被越过，不作为「七环全合规」宣称 |
| 非阻断登记 / 待办 | **P2** `drive_batches.py:89` 防覆盖预检查期望名 `a.case_id` 而非服务端实际 cid（pX2/pX3），重启计数复位有覆盖风险 → 后续另笔；**P3** `:132/158-159` 终态无 gate 回退取 `/api/run` 的 `status=running`，两 trace 记 `status=done gate=running` 易误导 → 后续另笔；**P4** `:21/:23` 两默认值盘上正确但复跑为显式传参、未做无人值守回归 → 后续另笔；**P5** `breakpoints.md:1`「无产品断点」略绝对、未点名 §6 拍板第 1 项 → 后续另笔；**P6** `:50` `f.read()` 整读进脚本局部变量（非上下文/不输出，实质合规）→ 低优先。**v1.1 复审 5 条非阻断润色建议**（§0「全部沿用 v1 零改动」措辞过满 / 判据 1 是改写主干非补注 / `stage_source_match` 措辞 / 阶段 0 归属张力 / #102④ 未单列）：登记留痕，v1.1 正文保持签结版不改。**阶段 1 剩余 5 批（378/286/94/10/2 层）未跑**、层厚/重建算法轴未覆盖（依赖 §6 拍板第 1 项）、`stage_source_match` 运行期写出待验、干净克隆未复跑、跨机批次待拍板、未跑全量 pytest（355/8/0 以 #102 为据） |
| 回执勘误 | 编码手回执 §3-7「首行前有标题行」纠偏后已过期；`:139/:194`「全部 gitignored」把项目目录回执也算入（实为「不在仓内」而非被 `**/out/` 忽略，「不进提交」成立）；§1(3)「假断点」与 §4.1 根因更正并列易读成两结论。指挥官抽验 CMD1 标题「复跑」实为**解析已有 `batch-trace-2.jsonl`**（case_id=pX3 非新分配 cid）、CMD1–4 为摘要式非逐条原始输出；`:3`「未改任何文件」与纠偏改动冲突（P1）。任务书 §1A CLI 未列 `--uploads-root`（纠偏必需，宜补登非越界）、§1D「实跑 1 批」与同 CT 跑 2 次不符、「独立产物路径」与 pX2/pX3 落同一 state-dir `cases/`（靠新 cid 区分）不符。第 3 层审计席声明：未真重跑驱动/服务、未跑全量 pytest、未核 8082 启动命令行、未亲读 `server.py:2482`、纠偏执行主体无独立派工记录可证（P1 归属为文档比对推断） |
| 状态 | **阶段 0 定尺子完成（驱动可复用 + 清单 + 服务确认）、阶段 1 冒烟首行 `done/全精度齐全/无产品断点`（同一批 CT `20261019-215629`，仅验驱动可用）** · 双轮方案审计 + 第 3 层独立审计技术面 0 BLOCKING 已签结 · 流程面 P1 如实登记 · 已本地提交（**未推送**，待用户批准；推送前须再跑 §10 可见性闸门） |

### #104 两处留痕缺口补落盘/补做 + 独立审计（2026-11-09，用户「补同时审计」）

| 项 | 内容 |
|---|---|
| 反例 | 上一轮如实登记两处留痕缺口：① **v1.1 方案复审回执未落盘**（裁决仅在 2026-11-08 对话内，Agent `agent-b3330ace…`，无盘上文件）；② **严格 §9「Router 亲读关键 diff」未做**（第 2 层抽验文档自述「只重跑命令、不读实现，代码级核验交第 3 层」）。两处均属「审计环节在、留痕缺」，非「没审」 |
| 谁接住 | 补件 1 `复核回执-v1.1方案复审-补落盘-2026-11-09.md`：按对话内原文逐字转录（§1 命令输出 / §2 8 条结论 / §3 0 BLOCKING 裁决 / §4 5 条勘误 / §5 6 条未验证项），抬头明写「2026-11-08 对话内返回、当时未落盘；2026-11-09 补落盘；内容未改；事后留痕不倒推」。补件 2 `Router亲读-关键diff-补做-2026-11-09.md`：Router 真跑 `git show c22ff35`（台账 #103 纯文档 diff）+ `sed` 读 `drive_batches.py` 四关键段，落命令+输出+亲读结论 5 条，明写「2026-11-09 补做、不倒推成 11-08 抽验当时已亲读、不改动抽验原文」。第三份 `复核回执-补件审计-2026-11-09.md` 落盘闭合两份补件页脚的引用链 |
| 实义判定 | 两处均为**「事后补记、不倒推」的有限闭合**：① 闭合「盘上文件」这一环，但「原始 11-08 对话内返回」无独立旁证；② 闭合「亲读留痕」这一环，但执行主体身份不可倒推。**P1 缺口仍按 #103 如实登记、未被冒充闭合**；补件未把技术面 0 BLOCKING 圆成「七环全合规」，未否定 P1。补件正文**保持被审定原样、未做任何修订**——审计席 §5-5 明说两份补件在 `项目/` 目录不受 F 仓 git 管辖、无法用 git 核验其后是否被改动，审后再改会制造「审定文本 vs 现行文本」不一致，故 3 条呈现级勘误只登记留痕、不改补件 |
| 验证 | 派独立只读子智能体（Agent `agent-18d9aa3a…`）审两份补件，14 次只读取证、**10 项全 ✅、0 BLOCKING 可签结**：抬头如实、转录忠实（8 条结论/5 条勘误/6 条未验证项与台账 #103、交接二十六节、atomcode 回执、v1/v1.1 实文件逐项一致，未删不利项、未新增结论）、与既有记载无冲突、Router 亲读有真实可复现命令（`git show`/`sed` 重跑输出支撑结论，P2/P3/P6 编号位置与 #103 逐项一致）、如实不倒推、未圆掉流程缺口、无新矛盾、合规（无患者信息/无 viewer 内容入上下文）、未越界（F 仓 HEAD 仍 `c22ff35`、0 个 `M`、项目目录不在 git 管辖内）。`date` 实证 2026-11-09 |
| 非阻断登记 | 审计 §4 三条**呈现级**勘误（均非 BLOCKING、可选修订，登记留痕不改动补件）：① 补件 2 CMD-A 命令未带 `--stat` 而输出要点含「1 file/13 insertions」（数值经重跑属实）；② CMD-B 相对路径依赖 cwd（补件未写，审计用全路径复现成功）；③ 补件 2 :7「F 仓唯一提交 c22ff35」应限定为「本轮唯一」（F 仓实有 2 个未推送提交 `a13746c`+`c22ff35`）。审计 §5 七条未验证项：原始对话内复审文本从未落盘故「逐字」为交叉一致性间接证据、完整 UUID 后半段无旁证、Router 执行主体身份不可独立实证、历史时点输出未重跑、补件自身不受 git 管辖无法核验落盘时间、未逐行重核补件 1 引用的产品代码行、页脚引用文件（本回执）当时未核（已由本次落盘闭合） |
| 状态 | **两处留痕缺口有限闭合** · 两份补件 + 审计回执落盘 · 独立审计 0 BLOCKING 可签结 · 补件正文零修订 · 已本地提交（**未推送**，待用户批准；推送前须再跑 §10 可见性闸门；**11-09 已随 3 提交推送至 origin/master**） |

### #105 阶段 1 五批泛化实测 · 断点在准入/脱敏层（2026-11-09，用户「派子代理跑五批出断点表」）

| 项 | 内容 |
|---|---|
| 反例 | 阶段 1 剩余 5 批（378/286/94/10/2 层）真跑，按 v1.1「先证伪再补门、只找断点不修」。目标：把「任意一个患者上传 CT 出模型」的缺口从「一批已通」推向泛化证据。任务书 `任务书-阶段1五批泛化实测-2026-11-09.md` |
| 谁接住 | 严格乐团：任务书 → 编码手 Worker（Agent `agent-17661b32…`，默认模型）→ `回执-阶段1五批-2026-11-09.md`（三要素）→ 指挥官第 2 层抽验 `抽验-阶段1五批-2026-11-09.md` → 第 3 层独立只读审计 `复核回执-阶段1五批-2026-11-09.md`（Agent `agent-6b378aa6…`，16 次只读取证）→ 台账 #105 → 提交。产物全在 `out/e2e-v2-20261107/`（gitignored、不进提交）：`run_5batches.py`(109) / `breakpoints-5batches.md`(38，主交付) / 5 条 `batch-trace-202610*.jsonl` / `run5.log|summary|DONE.flag` |
| 实义判定 | **5 批全部在 `/api/upload` 被 HTTP 422 `status=blocked` 拒收**（`gate=upload_rejected`、`case_id=null`、全精度三标量 null、`viewer_data_bytes=0`），`done 0 / blocked 5`，0 批到达求解/导出。**根因经第 2 层抽验 + 第 3 层独立复算钉死**：`server.py:2974` 是全文**唯一** 422 来源 —— HR-1「PII 前置闸门」：`RA.scan_pii(up_dir)` FAIL → 清理上传目录 → 返回 `{"gate":"PII 头扫描（上传前置）"},422`。6 目录 `scan_pii` 只读对照（只取 pass/files/fail_count/命中字段名，**不输出字段值**）：冒烟批次 `20261019-215629`(195层) `pass=True`（已脱敏）；5 批全部 `pass=False`，命中 PatientName/PatientID/PatientBirthDate/AccessionNumber/InstitutionName 等。**结论：患者安全门在正确工作，是这 5 批未脱敏的原始 CT 被合规门拦下，不是产品缺陷、不是求解/网格/层数轴问题**；与阶段 0 冒烟成功不矛盾（差异全在脱敏状态）。**无人把「未脱敏」当 bug 修门 / 放宽 PII / 擅自脱敏**（第 3 层复算 5 批仍 `pass=False` 为强证据） |
| 验证 | 第 2 层：422 唯一来源 grep + 6 目录 `RA.scan_pii` 对照，落 `抽验-阶段1五批-2026-11-09.md`（断点表原文保持「疑似…待抽验」未改）。第 3 层：自己复算 `scan_pii` 6 目录与抽验**逐位一致**、逐文件 `check-ignore` 全命中 `.gitignore:23`、trace 13 字段白名单无患者值、`run5.log` 每批恰 1 次 RESULT 无重跑、`git diff` 空 / 0 个 `M`；**11 项全 ✅、0 BLOCKING 可签结**。合规：全程未输出任何患者字段值、未读 viewer_data.js/VTK/图像内容、患者内容未出 `out/` |
| 诚实结论（不夸大） | **断点表已交付且合格，但「层数轴泛化实测」实际未达成**：0/5 到达终态，全精度/`deferred_count`/`viewer_data_bytes` 无从采集。真正的下一个断点 = **脱敏/准入口径**，正对应 v1.1 阶段 2 的 **L2-b（脱敏 CT 合并 + 逐批准入校准）** 与阶段 3 的 **T7（PII 门）**。须先按数据政策做脱敏（真实患者数据不开源、不得商用、仅本人同意、本地处理）——**脱敏是合规动作，须用户拍板**，本轮未做任何脱敏。**不得**把 422 当缺陷修门或放宽 PII 判定。口径差如实：方案 §3 原列 6 批含 195 层 `20261017-212959`（另一批），冒烟跑的是 `20261019-215629`（另一个 195 层目录），两者不是同一批；本轮按用户「五批」未纳入 `20261017-212959`，**不擅自扩到 6 批**、不把「已跑 195 冒烟」写成「195 档已覆盖」、不把 5 批夸大成「任意患者已验证」 |
| 非阻断登记 | 审计 §4 四条呈现级勘误（均非 BLOCKING、登记留痕不改被审对象）：(a) 判定条件实际为 `pii_pre is not None and not pii_pre.get("pass",True)`（扫描器异常 `None` 时不拦、注册链兜底），抽验简记为 `not pii_pre.get(...)`；(b) 抽验 §2「替换断点表的疑似」易误读为改写文件，实为定性闭环、断点表 :31 原文未改；(c) `PII_FIELDS` 行号近似（:87-91 / CORE_PII :92-95）；(d) 回执 git 实证含 `awk` 占位、贴了全 13 字段略宽于任务书 §4 要求。审计 §5 七条未验证项：未逐批 POST 取 422 响应体 `gate` 原文（禁 POST，定性靠代码级唯一来源 + 独立复算）、未验证脱敏后能否跑通层数轴（须拍板）、未独立重跑 5 批（禁 POST，靠 trace/log/断点表交叉）、`drive_batches.py` 被 gitignore 忽略故 git 级无法证明字节未改（靠行范围读 + P2/P3/P6 基线对照）、未读 viewer_data 内容、未核 8082 启动配置与阶段 0 完全一致、未判源 5 批是否同一患者。另 `drive_batches.py` 的 `terminal_reason` 只取 `body.get("status")` 未取服务端 `gate`/`error`，故 trace 看不到真实闸门名（P3 同族，非产品缺陷） |
| 状态 | **断点表已交付 · 独立审计 0 BLOCKING 可签结** · 阶段 1 层数轴泛化**未达成**（断点在准入/脱敏层）· 下一动作 = L2-b 脱敏（须用户拍板）后重跑 5 批 · F 仓产品代码零改动、0 个 `M` · 已本地提交（**未推送**，待用户批准） |

### #106 预编译二进制入仓 · 干净 clone 无需 Rust 即可本机求解（2026-11-09，用户「拉下来就跑」）

| 项 | 内容 |
|---|---|
| 反例 | 用户定产品形态：**前期纯本地、不提供云端服务 → 患者/医生拉下来在自己电脑跑起来是关键；数据合规/PII/脱敏/授权书后置**。核实发现「装机自检显示成功 ≠ 上传 CT 能出 3D」：`flowscope.exe`(616KB) 是编译产物不进 git（根 `.gitignore:71` + `code/solver/.gitignore:1`），仓库无 CI/Release；bootstrap 无 cargo 降级 `--solve skip`（只算例不出 CFD），但前端 `pg-run` 硬编码 `solve=local` → `auto` 找不到 FlowScope → 回退 openfoam → 干净机器无 WSL → 求解失败 |
| 谁接住 | 用户选 **B：预编译二进制进仓库·clone 即用**（并补充「Linux 等台式机也要能直接用」「Windows 系统里就有 rust 工具链」）+「在仓库里写明完整安装使用流程」。任务书 `任务书-预编译二进制入仓-2026-11-09.md` → 编码手 Worker（Agent `agent-040f1f6d…`，**3 轮 T4-R1 上报均按限定射程修复**：文档过时表述 5 处 + 残留路径 2 处，无第 8 处遗漏）→ 回执三要素 → 第 2 层抽验 `抽验-二进制入仓-2026-11-09.md` → 第 3 层独立只读审计 `复核回执-二进制入仓-2026-11-09.md`（Agent `agent-25fa4073…`，18 次取证）→ 台账 #106 → 本地提交 `b2baaf1`（8 文件，未推送） |
| 实义判定 | 新增 `code/solver/bin/`：`flowscope-win-x64.exe`（PE32+ 616960B sha `e5c439c2…219e`，Windows rustc 1.98.1）、`flowscope-linux-x64`（ELF PIE 921344B sha `43b6f839…a65`，WSL `cargo build --release --target x86_64-unknown-linux-gnu` rustc 1.99.0，零第三方依赖纯标准库，1m08s）、`README.md`（来源/哈希/BSL 1.1 Additional Use Grant 允许 patient self-use 与商用外 Production Use/源码 `code/solver/src/` 可自构建/仅 Win-Linux x86_64 预编译、macOS-ARM 需自构建、Linux clone 后 `chmod +x`）。`solver_backend.flowscope_path()` **仅加一段**按平台探测 `bin/`（`FLOWSCOPE_BIN` → `bin/` 平台二进制 → `target/release` 自构建；macOS/ARM 返回空不误喂 ELF/PE），**路由与判定逻辑零改动**。bootstrap 两版优先用预置二进制、有则第 7 步强制 `--solve local` 不降级 skip。README QUICKSTART 重写为患者/医生完整 7 步流程（拿仓库→Win/Linux 各一条命令装机→起 Web 工作台→上传 CT→看 3D→验证标准→排错），明确「无需 Rust/WSL/OpenFOAM」但「Python 3.10+ 与 pip 依赖仍必需」、未声称任意平台开箱即用；历史实测数字全部保留并标注；`从零复现.md`、`bin/README.md` 同步 |
| 验证 | **第 2 层干净 clone 实证（决定性）**：模拟 clone（196 tracked + bin 三文件，无 `.venv`/`target`/患者数据）在 **PATH 剔除 cargo/rustup/rust** 下 `flowscope_path()` 命中 `bin/flowscope-win-x64.exe`、`custom_available=True`、`resolve_backend('auto')='custom'`；两平台 `--help` 真执行成功（第 3 层复核**两平台均 EXIT=2**，非抽验初稿所称 Win=0 版本差异，已回填勘误）；sha256 逐位一致；`git check-ignore` 对 bin/ 三文件无命中。第 3 层独立审计 **12 项、0 BLOCKING 可签结**。**全量 363 tests / 355 passed / 8 skipped / 0 failed**（`b2baaf1` 提交前指挥官收尾跑）。提交**显式 8 路径**、禁 `git add -A`（76 个既有 `??` 含 `report-pA.html`/`figures/pA/*` 等患者衍生演示资产标签未跟踪产物一律不入库），pre-commit 密钥钩子通过 |
| 流程合规性 | 严格乐团七环齐备：任务书 → 派编码手 Worker（非主会话直改）→ Worker 回执三要素 → 第 2 层抽验 → 第 3 层独立只读审计 → 台账 → 指挥官提交。审计 5 条勘误（抽验 CMD-B 两平台 EXIT 均 2、抽验提交面 `??` 实为 79、任务书 §0 实为 ahead 1 未推送、§3.6 M 数应为 5、CMD-C 无需勘误）已如实登记；抽验文档与任务书口径未倒推成已合规 |
| 非阻断登记 / 诚实边界 | ① **PII 前置门 422 仍会拒收带姓名的真实 CT** —— 按用户「数据问题后置」本笔**零碰**（`server.py`/`run_all.py` 零入 diff），README QUICKSTART ④ 已补「检出身份字段返回 422、请先自行匿名化、闸门调整属后续数据合规议题」的诚实提示，未被误写为已解决。② standard 档 viewer 3D 导出仍要求完整占位档契约，FlowScope 不产这些字段 → 「出 3D」以 quick 档/`--allow-partial-viewer` 为条件，README/从零复现已如实写明。③ 未真跑完整 bootstrap 全链（20 分钟级 `--solve local` 合成 CT 冒烟）、未在 Linux 实机（非 WSL）执行 ELF、未在 Windows 实机执行 `bootstrap.ps1`、未跑患者真实 CT 端到端、macOS/ARM 未覆盖。④ 本笔闭合的是**求解器可用性断点**，不等于「上传任意 CT 无条件出 3D」 |
| 状态 | **「拉下来就跑」求解器断点已闭合**（Win/Linux x86_64 干净 clone 无 Rust 可 `auto→custom`）· 独立审计 0 BLOCKING 可签结 · 全量 355/8/0 · 已本地提交 `b2baaf1`（**未推送**，待用户批准；推送前须再跑 §10 可见性闸门） |
