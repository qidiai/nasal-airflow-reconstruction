# consent-ledger.md — 授权链台账（患者数据治理 · M1 轨 D 建立）

> 建立：M1 P0.1 整改季 轨 D，2026-10-17，编码手 step-5-preview。依据：规划 v2.3.2 §2.1「数据宪法」与三级资产分类；README《数据说明（重要）》数据政策块（2026-10-17 项目所有者亲定）。
> 维护规则：**逐资产登记**；新资产入仓/新演示前必须登记；发布前机审 + 双审计官抽检；授权状态变化当日更新。本文件只做登记与判定，不授予任何授权。
> 数据宪法（用户原话级，v2.3.2 §2.1）：①患者数据不开源，除非得到患者本人同意（逐例授权书，含分发范围+撤销条款，进本台账）；②患者数据不可商用（任何产品/服务/模型训练/交易一律禁用）；③源码公开但商用须所有者授权（BSL）。

## 0. 三级分类（v2.3.2 §2.1，打标依据）

| 级 | 定义 | 本仓库实例 |
|---|---|---|
| **L1 可分发** | 代码、文档、**全合成数据**（管线自产，无授权问题）、公共许可数据集（逐个验许可、**禁患者来源**） | pipeline/verify/viewer/tests 代码（BSL 1.1，Change Date 2099-01-01）、docs/、`code/viewer/viewer_data.js`（100% 合成示例）、`gen_demo_data.py` 可再生 |
| **L2 条件门** | 新采集患者数据——仅当本人签署「去标识+分发+非商用+可撤销」授权书后方可分发给指定范围 | 当前**无一例**进入 L2（无签署授权书） |
| **L3 闭门** | 现有全部患者衍生资产——不开源、不商用，仅限内部研发；对外发布包只含 L1 | 本台账 §2–§6 全部患者来源资产（consent 均为 local_only / 官方演示口径） |

**通用硬标记**：所有患者来源资产一律带 **商用禁止**（数据宪法②）；所有患者来源资产 **不可随仓库/发布包分发**；仓库与发布包只含 L1。

---

## 1. 总表（资产 × 治理字段）

| # | 资产 | 来源 | consent 范围（实证） | 保留期 | 可分发性 | 商用 | 分级 |
|---|---|---|---|---|---|---|---|
| A1 | demoA DICOM 源（患者a） | `参赛群资料\4例演示ct\（患者a）鼻中隔+鼻甲消融+其他\ISO_Soft_0.35mm_合并`（394 头，0.35mm ISO） | 官方确认演示授权（2026-10-16）+ 官方脱敏后使用（provenance.md） | 未设自动过期（内部封存） | 不可分发 | **禁止** | L3 |
| A2 | demoA 衍生归档 | `out\结果\P0-result-demoA-v1\`（cfd/step1/step2/step5，269,913 cells，ΔP=18.45 Pa）+ webapp viewer 数据 | 同 A1；归档仅含结果与日志，**无任何 .dcm** | 同上 | 不可分发 | **禁止** | L3 |
| A3 | demoB DICOM 源（患者b） | `4例演示ct\（患者b）鼻甲消融\20250902-Head^07_Sinus (Adult)\4-Sinus 0.75 H40s`（薄层 0.75mm） | 同 A1 | 同上 | 不可分发 | **禁止** | L3 |
| A4 | demoB 衍生归档 | `out\结果\P0-result-demoB-v1\`（142,914 cells，ΔP=12.48 Pa，197 步收敛）+ viewer 数据 | 同 A1 | 同上 | 不可分发 | **禁止** | L3 |
| A5 | pN-Lat DICOM 源（正常·鼻甲外移） | `4例演示ct\鼻甲外移\20260127`（ISO 0.348mm） | 同 A1 | 同上 | 不可分发 | **禁止** | L3 |
| A6 | pN-Lat 衍生归档 | `out\结果\P0-result-pN2-v1\`（87,975 cells，ΔP=148.65 Pa，1500 步未收敛；映射结论见 provenance.md） | 同 A1 | 同上 | 不可分发 | **禁止** | L3 |
| A7 | pN-Med DICOM 源（正常·鼻甲内移） | `4例演示ct\鼻甲内移\20260217-5.___`（ISO 0.367mm） | 同 A1 | 同上 | 不可分发 | **禁止** | L3 |
| A8 | pN-Med 衍生归档 | `out\结果\P0-result-pN-v1\`（53,747 cells，ΔP=27.76 Pa，322 步收敛） | 同 A1 | 同上 | 不可分发 | **禁止** | L3 |
| B1 | pA DICOM 源（患者A） | `参赛群资料\患者A\脱敏后图像数据\ISO_Soft_0.35mm_合并`（394 头；使用说明.txt：「仅用于本人影像的科研/学习用途」） | S0 PII 扫描 PASS（PatientID 空值域，StudyID=sinus）；本人提供脱敏序列；**与 demoA 同源**（md5 前 20 头逐字节全同，2026-10-17 实证） | 同上 | 不可分发 | **禁止** | L3 |
| B2 | pA 衍生归档 | `out\step1\`（STL/QC）、`out\step2\P0-OF-case-pA-v1(+v1B)`、`out\结果\P0-result-pA-v1\`（allrun.log 1437.68s→复测 1270.48s）、`out\postprocess\contract-pA-v1.json`、`out\webapp-state\cases\pA\` | 同 B1 | 同上 | 不可分发 | **禁止** | L3 |
| B3 | pB DICOM 源（患者B） | `参赛群资料\赛方CT\ISO_Soft_0.468mm`（420 头；run_all_manifest-pB-v1.json args） | S0 PII PASS（manifest 留档） | 同上 | 不可分发 | **禁止** | L3 |
| B4 | pB 衍生归档 | `out\结果\P0-result-pB-v1\`（203,387 cells，ΔP=44.9067 Pa）+ 变窄系列 v6n1/2/3 | 同 B3 | 同上 | 不可分发 | **禁止** | L3 |
| B5 | pC DICOM 源（患者C） | `参赛群资料\赛方CT\ISO_1mm_0.613mm`（156 头；webapp-state/cases/pC 注册） | S0 PII PASS | 同上 | 不可分发 | **禁止** | L3 |
| B6 | pN 早期算例（27 例来源） | `out\step2\P0-OF-case-pN-v1..v6`（例1–例6_重排，体素 0.977×0.977×1.25mm）+ case_stats | 见 C1 授权 | 同上 | 不可分发 | **禁止** | L3 |
| C1 | 27 例候选集（无症状） | `参赛群资料\副鼻窦27例_脱敏完整\副鼻窦27例_脱敏完整`（6,212 dcm；ANON-P01..P27 / ANONYMIZED 占位，零真 PII——T27 case_manifest.json 实证） | T27 看板 §6：「授权：meta 已标『已授权（官方确认演示 2026-10-16，含本批 27 例）』」；**授权范围=官方演示，非分发** | 同上 | 不可分发 | **禁止** | L3 |
| C2 | 27 例合规版中间态 | `参赛群资料\副鼻窦27例_合规版`（7,184 文件 = 例1–6_重排 972 + 嵌套脱敏完整 6,212） | 同 C1 | 同上 | 不可分发 | **禁止** | L3 |
| C3 | T27 批量产物（正常参考带 v0） | `G:\qidicode\target\tmp\t27\case_1..27`（仅 metrics.json + qc_overlay.png，**零 DICOM**）+ `normal_reference_band_v0.json` + 四图 | 同 C1；T27 合规自检：「真实 DICOM 未出 F: 盘」 | 同上 | 不可分发（演示口径须带「n=27 脱敏集·几何形态参考带·非人群临床参考区间·非诊断依据」） | **禁止** | L3（衍生） |
| C4 | sinus27 命名集 | **仓库内不存在该命名资产**（全库检索无 `sinus27` 目录）；实际载体 = C1（DICOM 源）+ C3（指标产物）+ T27 case_manifest.json（机器可读索引） | 同 C1 | — | — | — | L3 |
| D1 | webapp 工作台上传（真实会话） | `out\webapp-state\uploads\`（946 dcm，2026-10-15/16 会话）+ cases.json（pA/pB/pC） | consent-audit.jsonl 3 条：pX2(10-15 23:57)、pX(10-16 16:27)、pX(10-16 21:10)——**processing_scope=local_only、retention=days:7、pii_scan=fail** | **7 天**（T17 弹窗授权口径） | 不可分发 | **禁止** | L3 |
| D2 | T17 冒烟上传（pX） | `out\webapp-state-t17smoke\`（3 头，526KB/头）+ `cases\pX\consent_record.json` | data_subject=self；「本人 2026-09 鼻窦 CT（赛方合规脱敏序列，冒烟模拟）」；**local_only、days:7、pii_scan=pass**；authorization_ref=空 | **7 天** | 不可分发 | **禁止** | L3 |
| D3 | 云端冒烟记录（pV/pY/pZ） | `out\webapp-state-t17smoke-cloud\cases\*\consent_record.json` | pV：local_only/days:7/self；pY：**cloud_optin**/days:7/self；pZ：**cloud_optin**/**days:30**/authorized_third_party；source 均标「冒烟」 | 7 / 7 / 30 天 | 不可分发 | **禁止** | L3（冒烟测试件） |
| D4 | M1 测试夹具 | `out\webapp-state-test-m1\`（116 个 pX 例，4 字节哑 .dcm） | 测试夹具，**非患者数据**（文件为占位空壳） | 随测试清理 | 可随测试件管理 | 不涉 | 测试件（非患者资产） |
| D5 | 其他测试态 | `out\webapp-state-test-cloud\`、`webapp-state-test-pres\` | 同 D4 | 同上 | 同上 | 不涉 | 测试件 |
| E1 | 队友个人医疗资料 | `参赛群资料\个人资料\`：睡眠监测报告转录（2022-03-24 PSG：AHI 41.1 等）、微信图片×3（**含完整个人信息的原始报告照片**）、OSA 管理方案、设备研究 | 审计报告-双模型汇总.md：「原始报告照片（JPG）仍含完整个人信息，保留于本人磁盘，**未经本人同意不再送任何模型**」；工作区与赛题文件夹 MD 已完成姓名+生日脱敏 | 本人磁盘保留 | 不可分发 | **禁止** | L3（个人医疗数据） |
| F1 | L1 发布面（对照） | 代码/文档/合成数据 | 无患者来源 | — | **可分发** | 代码 BSL：商用须所有者授权；合成数据无限制 | **L1** |

---

## 2. 四例演示数据（A 组）明细

演示四例 = 官方四例演示 CT（`参赛群资料\4例演示ct\`：鼻甲内移 / 鼻甲外移 /（患者a）/（患者b）），前端注册名 demoA / demoB / pN-Lat / pN-Med。四例的 consent 实证统一来自各自 `out\结果\P0-result-*\provenance.md`：

> 患者标识：`已授权（官方确认演示，2026-10-16）`；脱敏状态：**官方脱敏后使用**（官方确认演示授权，2026-10-16）；归档仅含结果与日志，无任何 .dcm 患者原始数据。

- **demoA**（患者a：鼻中隔+鼻甲消融+其他）：DICOM 394 头 0.35mm ISO（浙一 0.67mm 原始重采样）；网格 269,913 cells；ΔP=18.45 Pa；1500 步平台未收敛。**注意：demoA 与 B1 pA 为同一患者数据**（两处 DICOM 目录前 20 头 md5 逐字节全同，2026-10-17 轨 D 实证）——登记时按同一 consent 主体合并管理，避免"一数两登"。
- **demoB**（患者b：鼻甲消融）：序列 `4-Sinus 0.75 H40s`；网格 142,914 cells；ΔP=12.48 Pa；197 步 SIMPLE 收敛。
- **pN-Lat**（正常·鼻甲外移）：ISO 0.348mm；87,975 cells；ΔP=148.65 Pa；1500 步未收敛。结果目录 `P0-result-pN2-v1`（命名映射经 provenance.md ⑤核对：收敛态+出口截面 90.6 mm² ↔ 前端 pN-Lat）。
- **pN-Med**（正常·鼻甲内移）：ISO 0.367mm；53,747 cells；ΔP=27.76 Pa；322 步收敛。结果目录 `P0-result-pN-v1`（映射同上，出口 156.4 mm² ↔ pN-Med）。

**授权范围边界**：官方演示授权 ≠ 分发授权。四例 DICOM 源与全部衍生资产（算例/网格/结果/viewer 数据/GLB/流线）均 L3 闭门；路演与提交包只可含 L1 + 由 L3 产出的**聚合指标**（须带口径标注，且不含可重建个人的几何/影像）。

---

## 3. 参照病例归档（B 组）明细

- **pA**：DICOM 源 `患者A\脱敏后图像数据\ISO_Soft_0.35mm_合并`（394 头）。使用说明.txt 明示「仅用于本人影像的科研/学习用途」。PII 扫描：PatientID 值域=['']、非空字段仅 StudyID=sinus（run_all_manifest-pA-v1.json S0）。衍生：step1/step2/结果/契约/webapp-state/cases/pA。**与 demoA 同源（md5 实证）**。
- **pB**：DICOM 源 `赛方CT\ISO_Soft_0.468mm`（420 头，赛方 CT）。PII PASS（manifest）。衍生含变窄系列 v6n1/2/3（轨 B 排查对象）。
- **pC**：DICOM 源 `赛方CT\ISO_1mm_0.613mm`（156 头）。webapp-state/cases/pC 注册（label「患者C · 拦截修复实证」，anatomy_inclusion=true）。
- **pN 早期算例**：`out\step2\P0-OF-case-pN-v1..v6` 由 27 例合规版例1–例6_重排生成（2026-10-15/16 manifests）——属 C 组授权的批量几何产物，按 L3 管理。

---

## 4. 27 例候选 / sinus27（C 组）明细

- **C1 脱敏完整集**（6,212 dcm，嵌套同名目录）：T27 批量唯一源（case_manifest.json ROOT 实证）。脱敏态：ANON-P01..P27 / ANONP01..27 / InstitutionName=ANONYMIZED / AccessionNumber=ANON——**占位格式脱敏，零真 PII**（T27 看板 §2）。
- **授权**：T27 看板 §6「meta 已标『已授权（官方确认演示 2026-10-16，含本批 27 例）』」。**授权性质=官方群口径的演示授权，无逐例书面授权书（authorization_ref 全为空，见 §7 缺口 G2）**。
- **C3 产物**：scratch 零 DICOM（只存指标 JSON/QC 图）；参考带 v0 演示口径：「n=27 无症状成人鼻窦 CT 脱敏集 · 几何形态参考带 · 非人群临床参考区间 · 非诊断依据」。
- **C4 sinus27**：检索确认仓库内**无** `sinus27` 命名目录/文件；文档（PLAN-v2.3.2、审计报告）中的「sinus27」指代的即 C1+C3 工作集。本台账以 C1/C3 为登记载体，C4 注销该命名（防双账）。
- **分辨率混杂**（影响参考带解释，非治理项）：例1–24 单序列 0.625mm/0.488mm 未压缩；例25（9 序列 JPEG Lossless）、26（15 序列）、27（8 序列）多序列按「层数≥100 中层厚最小」选薄层——pA/pB（0.35mm ISO）与本批（0.488–0.677mm）存在部分容积效应差异，T27 已如实标注。

---

## 5. 工作台上传 / 冒烟 / 测试（D 组）明细

- **D1 真实会话上传**（946 dcm）：T17 弹窗授权工作流产物。consent-audit.jsonl 现存 3 条均 local_only + 7 天 + **pii_scan=fail**（见 §7 缺口 G1）。
- **D2 pX 冒烟**：consent_record/v1 schema，prompt_version=T17-v1，source_declaration「本人 2026-09 鼻窦 CT（赛方合规脱敏序列，冒烟模拟）」，local_only/days:7/pii_scan=pass。
- **D3 云端冒烟**：pV/pY/pZ 三态覆盖 local_only 与 cloud_optin、7/30 天保留、self 与 authorized_third_party——**冒烟合成记录**（source 标「冒烟」），用于验证授权门禁分支，非真实患者。
- **D4/D5 测试夹具**：4 字节哑 .dcm，非患者数据。
- **T17 consent 模型**（tests/test_consent.py 实证）：processing_scope ∈ {local_only, cloud_optin}（白名单校验，"上传到微信群"等拒 400）；retention ∈ {session_only, days:1, days:7, days:30}（permanent 拒）；source_declaration 必填（demo 除外）。

---

## 6. 队友个人医疗资料（E 组）

`参赛群资料\个人资料\`：2022-03-24 整夜 PSG 转录（重度 OSAHS：AHI 41.1、最低血氧 65%、最长暂停 76s）、3 张含完整个人信息的原始报告照片、OSA 中西医管理方案 v2、设备研究 v0。治理口径引自该目录《审计报告-双模型汇总.md》脱敏执行记录：送审材料匿名化；原始 JPG 保留本人磁盘、未经本人同意不再送任何模型；工作区与赛题文件夹 MD 已完成姓名+生日脱敏。**L3 + 商用禁止 + 不可分发**；与 CT 资产相互独立（不同数据主体场景：本人自用健康数据）。

---

## 7. 授权链缺口与风险（如实登记，待关闭）

| # | 缺口 | 证据 | 风险 | 建议关闭方式 |
|---|---|---|---|---|
| G1 | consent-audit.jsonl 现存 3 条 **pii_scan=fail** | `out\webapp-state\consent-audit.jsonl`（pX2×1、pX×2，2026-10-15/16） | 上传门禁的 PII 扫描失败被记录但未见处置闭环 | 指挥官核验 T17 冒烟期记录性质（冒烟数据预期 fail？）；若是真实会话需补处置记录 |
| G2 | 全部 consent_record 的 **authorization_ref 为空**；四例/27 例授权为「官方确认演示」群口径，**无逐例书面授权书** | D1–D3 记录；provenance.md；T27 看板 §6 | 授权链缺书面载体，发布前机审/双审计抽检无法回溯到签字级证据 | 向赛方/患者补取书面授权（去标识+分发范围+撤销条款）；至少在台账登记授权人+日期+渠道 |
| G3 | pN 结果目录两套命名映射（pN-v1/pN2-v1 ↔ pN-Med/pN-Lat），且 provenance 标注 ISO 0.367/0.348mm 与 manifest 源（27 例例1/例2_重排，0.488mm 面内）存在**分辨率标注不一致** | `P0-result-pN-v1/pN2-v1\provenance.md` vs `run_all_manifest-pN-v1/v2.json`；mesh 统计（53,747/87,975 cells）两边一致 | 治理账与数据账可能错配；影响参考带与演示口径 | 轨 C 建基线时以 DICOM 头实测裁定并回写本台账 |
| G4 | pA 与 demoA 同源双登记（两套目录/两套命名） | md5 前 20 头全同（2026-10-17） | 重复管理、更新不同步 | 本台账已合并登记（A1/B1 互注）；建议仓库侧建别名索引 |
| G5 | 27 例「合规版」为中间整理态（例1–6_重排 + 嵌套完整集），与「脱敏完整」并存 | 目录实证（7,184 = 972 + 6,212） | 版本歧义 | 轨 C 跑批明确唯一源（建议=脱敏完整），合规版标记 deprecated |
| G6 | L3 资产无自动保留期机制（仅 webapp 上传有 7 天口径） | 本台账 | 归档无限期堆积患者衍生数据 | M3 切栈时裁定：L3 归档继续封存 or 销毁（需用户决定），销毁须留台账记录 |

---

## 8. 发布前机审清单（交付门）

1. 发布包/仓库仅含 L1：代码（BSL）+ 文档 + 合成数据（`viewer_data.js` 等）；**体积/皮肤层数据（volume_data.js / skin_data.js）不随仓库发布**（真实 CT 派生，README 已声明）。
2. 全库无 .dcm / 无患者原始影像 / 无可重建个人的几何产物（现有归档均在 `out\` 且 .gitignore 管控——机审须实测）。
3. 聚合指标引用带口径标注（参考带：非人群临床区间、非诊断）。
4. 本台账 G1–G6 缺口逐条有关闭计划或用户裁定记录。
5. README 数据政策块与台账三级分类一致（已一致，2026-10-17）。

---

## 9. 实证证据索引

| 证据 | 路径 |
|---|---|
| consent-audit.jsonl（3 条） | `code\pipeline\out\webapp-state\consent-audit.jsonl` |
| pX consent_record | `code\pipeline\out\webapp-state-t17smoke\cases\pX\consent_record.json` |
| pV/pY/pZ consent_record | `code\pipeline\out\webapp-state-t17smoke-cloud\cases\{pV,pY,pZ}\consent_record.json` |
| 四例 provenance（授权+映射） | `code\pipeline\out\结果\P0-result-{demoA,demoB,pN,pN2}-v1\provenance.md` |
| pA 运行 manifest（PII/源/计时） | `code\pipeline\out\run_all_manifest-pA-v1.json`（及 pB/pN 版） |
| pA 数据使用说明 | `参赛群资料\患者A\脱敏后图像数据\ISO_Soft_0.35mm_合并\..\使用说明.txt`（「仅用于本人影像的科研/学习用途」） |
| T27 批量 manifest（27 例脱敏态+源） | `G:\qidicode\target\tmp\t27\case_manifest.json` |
| T27 看板（授权+合规自检） | `G:\qidicode\target\tmp\t27\kanban-T27.md` |
| 队友资料脱敏记录 | `参赛群资料\个人资料\审计报告-双模型汇总.md` |
| 数据政策块 | `开源仓库\README.md`《数据说明（重要）》 |
| 分类依据 | `赛题3-鼻腔气道随访\项目\规划-v2.3.2-M0门控全关闭-2026-10-17.md` §2.1 |
| pA=demoA 同源实证 | 轨 D 复测底稿 `G:\qidicode\target\tmp\M1\trackD\`（md5 比对记录，见复测报告 §6） |

—— 建立完。2026-10-17。本台账只登记不授权；授权状态变化须经项目所有者/本人书面确认后更新。

---

## 10. 合成数据集 L1 —— M2.5 synth 产线（2026-10-17 追加）

> 本节为**纯追加**（未改动 §0-§9 任何原有条目）。登记 M2.5 合成数据产线 v1
> 产出的首批 L1 合成数据集。依据：任务书
> `G:\qidicode\target\tmp\nasal-hack\M2.5-synth-prompt.md`。

| # | 数据 | 位置 | consent 范围/实证 | 保留期 | 可分发性 | 用途 | 分级 |
|---|---|---|---|---|---|---|---|
| S1 | synth-001..010 合成鼻腔腔体 + OpenFOAM Run-A 真值（10 例） | `code\pipeline\out\synth\synth-001..010\`（geometry.stl + params.json + case/ + case_stats.json + metrics.json + provenance.json + MD5.txt）；根目录 README.md / MD5-MANIFEST.md / monotonicity.json | **无患者数据（L1 铁证）**：几何由 manifold3d 3.5.4（Apache-2.0）参数化生成（gen_geometry.py，seed 可复现）；合成 DICOM 由 stl_to_dicom.py 从 STL 栅格化生成（DERIVED/SECONDARY，PatientID=SYNTH-\*，无任何 PII），仅作 step2 输入载体、**不随数据集分发**（可由 STL 确定性再生，QC 记录于每例 dicom_qc.json）；求解走既有管线（step2 未修改）+ WSL OpenFOAM-2406 simpleFoam laminar Run-A 15L/min | 无限期（合成资产） | **可自由分发** | 算法验证/基准真值/演示（禁临床用途） | **L1** |

**许可**：项目 BSL-1.1（Change Date 2099-01-01）；几何内核 manifold3d Apache-2.0（已在每例 provenance.json 记录版本与许可）。

**溯源链**（每例可复现）：`gen_geometry.py`（seed+设计参数 → geometry.stl/params.json）→ `stl_to_dicom.py`（STL → 合成 DICOM，0.35mm/0.7mm，朝向约定 NOSTRIL_AT_LOW=True）→ `step2_make_ofcase.py --merge-mode largest --voxel-z 0.7`（0.7mm 各向同性网格）→ `solve_wsl.py`（WSL Allrun：checkMesh + simpleFoam 1500 步 residualControl p/U 1e-4 + foamToVTK）→ `finalize_case.py`（metrics.json 全部实测：VTK 补丁统计 + log 解析，零手写）+ MD5 清单。

**量化边界（如实登记）**：0.7mm 网格下 1.5-4mm² 狭窄段仅 2-4 个 mesh 细胞宽，ds2 majority 使实测 inletL 面积略大于设计 a_min；ΔP 量级与单调趋势可信，绝对值含网格量化误差（v1 不做网格收敛性研究）。参数-指标单调性抽查 3 组结果见 `out\synth\monotonicity.json` 与 README §7。

**看板**：`code\pipeline\out\synth\看板-M2.5.md`（进度 + 失败项/踩坑如实清单）。

