# 看板-M1轨D（77.3s 复测 + 授权链台账）— 2026-10-17

> 编码手 step-5-preview 执行。文件域：`G:\qidicode\target\tmp\M1\trackD\`（底稿）+ `开源仓库\code\data-governance\`（台账）+ `赛题3-鼻腔气道随访\项目\复测-端到端计时-2026-10-17.md`。禁 commit（未执行任何 git 操作）。

## 1. 交付物清单（勾选 + md5）

| # | 交付物 | 位置 | 状态 | md5 |
|---|---|---|---|---|
| 1 | 复测-端到端计时-2026-10-17.md | `G:\qidicode\target\tmp\M1\trackD\` | ✅ | 10DB42A8E3AF1B9131F3A7471CDF4FEF |
| 2 | 复测-端到端计时-2026-10-17.md（副本） | `F:\…\赛题3-鼻腔气道随访\项目\` | ✅ 同 md5（UTF-8 无 BOM） | 10DB42A8E3AF1B9131F3A7471CDF4FEF |
| 3 | consent-ledger.md（授权链台账） | `F:\…\开源仓库\code\data-governance\` | ✅ | 24BD7BE88A1D484B3D051935B32458EA |
| 4 | 本看板 | `F:\…\开源仓库\code\data-governance\看板-M1轨D.md` | ✅ | 见文末自验 |
| 5 | 复测底稿（脚本/日志/证据/计时输出） | `G:\qidicode\target\tmp\M1\trackD\retest\`、`evidence\` | ✅ | 见复测报告 §8 索引 |

## 2. 轨 D 任务验收对照

### 任务 1：端到端复测（pA，269,913 cells）— ✅ 完成

- [x] 全链路分阶段计时：S0 PII 94.0/34.4s、S1 ~1s、S2 step1 96.3–239.2s、S3 step2 49.4–193.8s、S4 gate ~1s、S5 交接 ~0.2s、S6 <1ms、S7 step5 31.9s、**求解 ExecutionTime 归档 1437.68s / 复测 1270.48s**；总计时链 75.3s（归档）vs 252.9–473.3s（复测，负载致），真端到端 ≈25.2–25.9 min
- [x] 三问三答：
  - ① **77.3s 可溯源**：`交接文档-2026-10-16.md` L34/L35/L109 + 路演速览镜像 = 工作台 POST /api/run/pA 全链（S0→S5 handover，**不含求解**）；佐证 run_all_manifest elapsed_sec=75.3；混淆源 pN2-v1 allrun.log 77.34s（pN-Lat 求解）；T28 引用文件名错位；**口径错位已定案**（数字真实，禁作"端到端/77 秒出 CFD"）
  - ② **1437.68s 数值可复现、耗时恒等式不成立**：WSL OpenFOAM 2406 重跑归档算例（输入 md5 全同）→ 1500 步满跑、末步残差/continuity 与归档**逐字符相同**、checkMesh Mesh OK、无 converged；ExecutionTime 1270.48s（-11.6% 负载波动）
  - ③ **端到端口径**：DICOM→S0/S1→S2→S3/S4→S5 求解（ExecutionTime 口径）→S6→S7；求解占 82–95%；须声明算例身份+机器状态
- [x] 求解计时以 allrun.log ExecutionTime 为口径 ✅
- [x] WSL/OpenFOAM 可用性验证并实跑 ✅（非"不可用"路径）

### 任务 2：授权链台账 — ✅ 完成

- [x] 逐个资产登记：四例演示（demoA/demoB/pN-Lat/pN-Med，A1–A8）、pA/pB/pC/pN 归档（B1–B6）、27 例候选（C1/C2）、T27 产物（C3）、**sinus27（C4：命名资产不存在，已注销防双账）**、webapp 上传/冒烟/测试（D1–D5）、队友个人医疗资料（E1）、L1 发布面（F1）
- [x] 每项：来源 / consent 范围（实证引用 consent-audit.jsonl 3 条 + consent_record.json ×4 + provenance.md ×4 + T27 看板授权行 + 使用说明.txt）/ 保留期（7 天 vs 未设自动过期）/ 可分发性 / **商用禁止标记** / v2.3.2 §2.1 三级打标（L3 闭门全覆盖患者资产；L1=代码/文档/合成数据）
- [x] 授权链缺口 6 项如实登记（G1 pii_scan=fail 无处置闭环；G2 authorization_ref 全空无书面授权书；G3 pN 命名映射+分辨率标注不一致；G4 pA=demoA 同源双登记；G5 合规版中间态；G6 L3 无保留期机制）
- [x] 新发现（副产品）：**pA 与 demoA 为同一患者数据**（两 DICOM 目录前 20 头 md5 逐字节全同）；管线**完全确定**（复跑产物与归档 md5 全同，连 PNG）

## 3. 未完成 / 失败项（如实，不许藏）

1. **干净机链路段基线未取得**：复测期本机 Defender ~50% CPU，链段时间 252.9–473.3s vs 归档 75.3s（差 3.4–6.3 倍，纯环境——md5 全同可证）。已做"求解并发/求解后"双样本并列。未 Kill 任何进程（纪律）。
2. **求解 ExecutionTime 单次采样**（1270.48s）；未做 3 次重复取中位数（时间盒）。
3. **S7 归档口径即 deferred**：pA/pB 契约缺 6 字段（dP_1/2/3mm、volumes_cm3、dP_Pa、band_Pa），run_all T12 下从未导出成功；计时 run 用"v5 归档值补齐+显式标注 TIMING-ONLY"的 scratch 契约（31.9s，A1–A7/N1–N5 全 PASS），**非数据产出**。
4. **77.3s 当次 server progress 原件被后续运行截断覆盖**；溯源依赖文档载体+归档 manifest 互证（充分但不完满）。
5. WSL 每次调用有 systemd 用户会话告警，不影响 OpenFOAM（已验证）。

## 4. 给指挥官/审计的裁定请求

1. PPT T28 P9「77.3s 在端到端验证数字块」→ 建议改注口径或替换（复测报告 §5.1）。
2. v2.3.2 §4 L1 门基线「求解耗时 1437.68s」→ 建议改区间表述（1270.48–1437.68s，数值轨迹一致）（复测报告 §5.3）。
3. 台账 G2（无书面授权书）与 G6（L3 保留期）需用户/所有者裁定后关闭。
4. pA=demoA 同源（G4）：建议仓库侧建别名索引，防止双账更新不同步。

## 5. 自验清单

- [x] 复测文档三问三答齐全、每个数字有载体路径
- [x] 台账全覆盖（任务点名资产逐项在表）+ 每项有实证引用
- [x] 两处文档 UTF-8 无 BOM（字节级验证：首字节非 EF BB BF）
- [x] 归档目录零写入（全程只读+scratch 输出；未对比外任何进程）
- [x] 零 git 操作（禁 commit 纪律遵守）
- [x] 失败项如实清单（§3）

