# 台账草稿 T6 — 硬编码几何锚定批修（编码手拟，指挥官合并）

> **性质**：草稿，供指挥官合并进 `conditions-ledger.md`；本文件**不直接改** `conditions-ledger.md`（任务书「改动范围」）。
> **编号**：`conditions-ledger.md` 现行已合并最大号 **#93**（见该文件末「登记表（#93 已知限制与开放项）」）；`ledger-draft-T12-0.md` 预占 **#94**、`ledger-draft-T4.md` 顺延取 **#95**。为避免撞号，本 T6 草稿顺延取 **#96**；三草稿最终编号由指挥官合并时统一裁定（若前两草稿不占号则本登记依次回落）。
> **版本坐标**：HEAD `8e36d68`（`git rev-parse --short HEAD` 实测一致，未前移）。任务书 `任务书-T6-硬编码几何锚定-2026-11-06.md`（方案 v1.2 §3 T6 行终签 ACCEPT；A3 切片 B 的 B1 P1 / B8 P2）。
> **纪律**：禁 git 写、禁 pip install、禁跑全量 pytest（指挥官收尾跑）；只改 `step4_export_implant.py` / `step5_export_viewer_data.py`，新增 `tests/test_hardcoded_geometry_anchor.py` 与本草稿；禁动 step1/2/3/6/7、`run_all.py`、`server.py`、`airway_geom.py`、11 条锁定测试（`test_survey_series_select.py`）、T1/T3/T4/T12-0 文件、`conditions-ledger.md`。

- 日期：2026-11-06。任务：写死几何常量与逐例数据脱钩（一类「硬编码锚定」病）批修；**不做框架**，两文件各按同源读法改。

## 二选一裁决（两处均取次选，登记备案）

| 裁决位 | 备选项 | 本任务选定 | 依据 |
|---|---|---|---|
| F1/B1 `step4` spacing | 首选：头推导且参考例输出逐字节不变 ／ 次选：头推导 + 显式断言输入 mask 已归一化到该 spacing + 台账理由 | **次选** | 本机无患者A 参考例回归基线（实测见「开放项 1」与回执），无法保证逐字节不变；任务书 F1 点名「历史产物间距恰为 0.35/0.3496 而头读值 rounding 不同」的风险；用户指令「若发现参考例回归无法保持逐字节不变，按任务书次选方案执行并在回执声明」。**spacing 仍一律头推导**（B1 P1 核心不降级），次选只额外加断言 |
| F2/B8 `step5` CENTER | 首选：一律由本例 mask 质心推导（去种子锚点） ／ 次选：保留种子值 + 契约/文档头显式标注「仅参考数据集有效」+ 非参考病例显式降级 | **次选** | `step5:281-283` 自述 decimate 跨进程不确定使重算质心在 1e-6mm 级波动；删种子后 `center_round(...,1)` 在 0.05 圆整边界可能翻转 ⇒ 参考例逐字节不变不可保证；本机无基线实测。次选**保留种子值** ⇒ 参考例 CENTER 数值分支零变化 |

## 三件登记（反例 / 谁接住 / 实义判定）

- **反例**（病象，均为「写死几何常量与逐例 DICOM 头脱钩」类硬编码锚定）：
  1. **B1/P1**：`step4` 原 `:37` `spacing = (0.35, 0.3496, 0.3496)  # z,y,x mm` 与 `:17` `VOX = 0.3496 * 0.3496 * 0.35`；同链路 `step1:439` / `step3:609` / `step5:74-85` 均从头推导，step4 独写死，且 step4 内无重采样/披露。PixelSpacing≠0.3496 或实测层间距≠0.35 时导出 STL 物理尺寸系统性偏差（「看起来对的错数据」）。
  2. **B8/P2**：`step5` 原 `:12` 文档头「CENTER 沿用 v1（[79.22,71.87,56.98]）」+ `:776`「沿用 v1，不重算」+ `:1725-1726` QC `expected_CENTER_mm` / `center_matches_v1` 硬编码参考常量，与 `:74-90` 逐例 `SX/SY/SZ_FULL` 不对齐；`:282-284` 自述患者A 回归逐字节一致故锚定种子值；`run_all.py:1064-1070` 已自披露此类写死几何「对其它病例生成 = 几何错位且 QC FAIL 不退出」。
  - 钉住反例的测试：`code/pipeline/tests/test_hardcoded_geometry_anchor.py` **16 例**（本任务新增）；旧锚定形态由源码断言 + step5 保留的字段哈希记录（`:1737` 注释）追溯。

- **谁接住**（改动落点 / 消费链）：
  - **F1**：step4 新增 `read_case_spacing(dicom_dir)`（pydicom 只读头、前两张切片 `PixelSpacing` + `ImagePositionPatient[2]` 实测层间距、`round(...,4)`，与 `step5:74-85` 同口径；≥2 层 / 字段齐备 / 有限正值断言，否则 `SystemExit` 明确报错**不回退写死常量**）；新增 `assert_mask_normalized(mask, ds_a)`（次选的显式断言：面内网格 == 本例 `Rows/Columns`）；模块级 `spacing` / `VOX` 全部由头推导，两处 `marching_cubes(..., spacing=spacing)` 与 `vox*VOX/1000` 体积打印随之。DICOM 目录经 `--dicom-dir` 或 `P0_DICOM_DIR`（与 `step3:29` / `cli.py:35` / README 同源）。
  - **F2**：step5 文档头显式标注种子仅参考数据集有效 + 坐标行改指逐例头读常量；种子分支 log 增 `[T6/B8] 告警`；新增 `_CENTER_IS_REFERENCE`（静态种子字典命中判据，与磁盘缓存无关）；QC `N3_same_center` 对非参考例追加 `center_source` / `reference_seed_applies=False` / `degraded_notice` 三字段（**条件块** ⇒ 参考例 qc JSON 逐字节不变）；`:788` 注释不再宣称「沿用 v1，不重算」。非参考病例仍走 `CENTER = _center_pre` 本例质心重算分支。

- **实义判定**（非重言、不换皮写死、不借措辞改判据）：
  - **F1 是数值来源替换**：写死常量全删（源码 `0.3496` / `0.35` 浮点常量零残留，AST 钉住），spacing 逐例随头变化（合成例 PixelSpacing 0.3496→0.5、dz 0.35→0.7，STL extents 逐轴按 spacing 比例变化、体积按三分量乘积变化，`rtol 2e-3` 实测）。fail-closed 侧 0/1 层、缺 PixelSpacing、缺 IPP 均 `SystemExit`；放行侧干净头通过 —— 既非恒真也非恒假。
  - **F1 的 `round(...,4)`** 沿用 `step5:83-85` **既有**口径（`SX/SY/SZ_FULL`），非为回归绿新增；与任务书「被否方案：为让参考例回归绿把头读值 rounding 成旧常量」的张力如实登记于开放项 2，未独立验证患者A 头读原始 DS 值（无真数据）。若指挥官判定构成换皮写死，改 step4 一行（去 `round`）即可。
  - **F2 纯属契约 / 文档头 / 日志 / QC 记录层**：`_SEED_CENTER_CACHE` 数值、`_center_pre` 口径、CENTER 三分支、`center_round`、QC 现有字段（`expected_CENTER_mm` / `center_matches_v1` / `samples` / `pass`）一字未动；新增字段只在非参考例的条件块内 ⇒ 参考例 `viewer_data.js` / `viewer_data_qc.json` 不受影响。`LOG` 无写盘消费者（`step5:95/98`），告警行只进 stdout。**判定逻辑零改动**（与 `ledger-draft-T4.md` 同纪律）。

## 关闭证据（B1 / B8 + 验收条目）

| 条目 | 关闭证据 |
|---|---|
| step4 spacing 来自本例头、无写死常量残留 | `git diff`（删 2 行写死常量 / 增 2 纯函数）；`test_step4_has_no_hardcoded_voxel_constants`（源码字面量 + AST 浮点常量双查）、`test_step4_wires_header_spacing_into_marching_cubes`（两处 MC 接线 + `VOX` 为 BinOp） |
| 合成例 STL 尺寸随头变化 | `test_exported_stl_extents_track_header_spacing`（step4 生产 `export_mask` 真导出 STL、真落盘，extents/volume 比例断言） |
| F1 fail-closed | `test_read_case_spacing_fails_closed_without_two_slices`、`test_read_case_spacing_fails_closed_on_missing_header_fields`（0/1 层 + 缺 PS + 缺 IPP 共 4 形态） |
| F1 次选断言 | `test_assert_mask_normalized_rejects_mismatched_grid`（正例 + 网格不一致 + 2D 三形态） |
| F2 次选落地 + 二选一已登记 | 本草稿「二选一裁决」表；`test_step5_contract_declares_seed_center_reference_only` / `test_step5_doc_header_drops_hardcoded_voxel_mm` / `test_step5_non_reference_center_is_explicitly_degraded` |
| 非参考病例不再静默错位 | 文档头限定 + log 告警 + QC 三字段降级；`test_step5_still_recomputes_center_for_non_reference` 钉住重算分支仍在 |
| 参考病例逐字节不变 | **F1**：头读值在参考例上等于旧常量（`test_read_case_spacing_tracks_pixel_spacing` 断言 `sp_ref == (0.35, 0.3496, 0.3496)`），且归一化断言不改变 mask/导出流程 ⇒ 代码级论证；**F2**：种子值与 QC 现有字段零改动，新增 QC 字段条件块对参考例不执行 ⇒ 代码级论证。**均未本机实测**（基线不存在，见开放项 1） |
| 新测试全绿 | `python -m pytest code/pipeline/tests/test_hardcoded_geometry_anchor.py -q` → **16 passed**（Python 3.12.10 / pytest 8.4.2） |
| 相邻用例不红 | 靶向 7 文件 **66 passed**（含真跑 step5 的 `test_step5_quick_z_streamlines.py` / `test_step5_zero_streamlines.py`、`--help` 的 `test_phase15_single_case.py`、11 条锁定测试 `test_survey_series_select.py`；命令见回执） |
| git diff 仅改动范围 4 文件 | `git diff --stat`：`2 files changed, 107 insertions(+), 6 deletions(-)`；另 2 个新增文件为 untracked（`git status --short` 可见）。工作树其余 untracked 项为派工前既有（HEAD `8e36d68` 时已存在），本任务零触碰 |
| 全量 pytest 不回归 | **未跑**（约束：禁跑全量，指挥官收尾跑） |

## 开放项 / 任务书内部冲突（如实上报，不隐瞒）

1. **参考例回归基线本机不可复跑**（实测命令与输出见回执）：`QIDI_WORKSPACE` / `P0_DICOM_DIR` / `DATA_ROOT` 均未设；真数据根 `F:\比赛项目\罕见无界黑客松\赛题3-鼻腔气流分析\参赛群资料` 不存在（与 `conditions-ledger.md` 2026-11-05 段记录一致）；`mask_full.npz` / step4 冻结 STL / 患者A `viewer_data.js` 基线均不在本机。故 F1/F2 均按用户指令与任务书取次选；「逐字节不变」为**代码级论证**（头读值相等 + 种子分支零改动 + 条件块对参考例不执行），**非实测**，须指挥官在具备真数据的环境复跑比对。
2. **F1 同源口径的张力**（见上「实义判定」）：`step5:83-85` 的 `round(...,4)` 既有口径 vs 任务书被否方案「为回归绿把头读值 rounding 成旧常量」。本实现按「同源口径」照抄 round 4；若裁定为换皮写死，改 step4 一行即可。未验证患者A 头读原始 DS 值。
3. **F1 次选「mask 已归一化到该 spacing」的可证代理边界**：`step2_make_ofcase.py:725-730` 只落盘 `mask/cut[/z_frame]`，无 spacing 元数据，故断言的是「面内网格 == 本例 Rows/Columns」（无裁剪/重采样），**层数不比**（`step1` 的 `read_ct_series` 去重/跳层可使有效层数少于 `.dcm` 文件数）。若 step2 未来写入 spacing 键，应补逐分量数值比对 —— 开放项。
4. **step5 `:343` 注释**「`0.35×9 = 3.15mm`」为参考例口径的说明性文字（不参与计算），未改（避免超规格）；如审计要求 step5 彻底清零写死数值，另批处理。
5. **QC 降级字段的 UI 消费**：与 `#81`/`#84` 同型（诊断算了但工作台不渲染），本任务只打通 QC 记录，查看器/拦截卡渲染另批。
6. **真跑 step5 的两条相邻用例**命中非参考分支 ⇒ `viewer_data_qc.json` 多 3 个字段；已核其断言只读 streamlines / boards / meta / stdout，不检查 QC 字段，靶向 66 passed；全量仍由指挥官核验。
7. **行号漂移**：任务书坐标 = HEAD `8e36d68`；step4 +83 行、step5 +30 行后旧坐标（`step4:17/:37`、`step5:12/:19/:282-284/:776/:1725-1726`）整体下移，回执以 `git diff` 真实 hunk 为准。
8. **AGENTS.md §9 派工额度纪律**：仓库内 `Glob **/AGENTS.md` 实测**零命中**（AGENTS.md 实体不在被审仓库），纪律文本仅见任务书 `:4`。本会话为 workbuddy CLI 标准模式直连执行，未采用 ai-bridge「单行指针读本任务书」/ tail-20 制，工具调用数 >20；如该额度对本通道同样适用，请指挥官裁定是否需按额度重做，本草稿不谎报遵守。
9. **未验证项**：① 未跑全量 pytest（约束）；② step4/step5 端到端全流程未实跑（无 `QIDI_WORKSPACE` / `mask_full.npz` / VTU / 真 DICOM），仅合成例钉住 spacing→STL 尺寸与源码接线；③ 参考例逐字节回归未实测；④ 未 git 写（`git diff` / `git status` 只读）。
10. **step4 新增必需输入（行为变化，如实登记）**：旧脚本不传任何参数即可用写死常量跑出 STL；现缺 `--dicom-dir` 且 `P0_DICOM_DIR` 未设即 `SystemExit` 停工（F1「无头可读 fail-closed」的必然结果）。真实链路 step1/2/3 已同用 `P0_DICOM_DIR`（`step3:29` / `cli.py:35` / README:30），`run_all.py` 不调用 step4（grep 仅 3 处消息文本），但**集成环境里 step4 的调用方是否已带该参数未验证**，须指挥官确认；本任务不擅自给默认参考例路径（那会重新引入硬编码锚定）。

## 改动面（供合并时核对）

- 改 `code/pipeline/step4_export_implant.py`：+2 纯函数 + CLI 解析 + spacing/VOX 头推导；删 2 行写死常量；导出流程其余一字未动。
- 改 `code/pipeline/step5_export_viewer_data.py`：文档头 2 处、种子注释与告警、`_CENTER_IS_REFERENCE`、`:788` 注释、QC 条件降级块；判定式/种子值/字段哈希零改动。
- 新增 `code/pipeline/tests/test_hardcoded_geometry_anchor.py`（16 例）、本草稿。
- `conditions-ledger.md` / `airway_geom.py` / 11 条锁定测试 / step1/2/3/6/7 / `run_all.py` / `server.py` / T1/T3/T4/T12-0 文件：**零触碰**。
