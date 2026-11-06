# 台账草稿 T10-a — 结论层口径批修（编码手拟，指挥官合并）

> **性质**：草稿，供指挥官合并进 `conditions-ledger.md`；本文件**不直接改** `conditions-ledger.md`（任务书「改动范围」）。
> **编号**：`conditions-ledger.md` 现行已合并最大号 **#93**（见该文件末「登记表（#93 已知限制与开放项）」）；`ledger-draft-T12-0.md` 预占 **#94**、`ledger-draft-T4.md` 顺延 **#95**、`ledger-draft-T6.md` 顺延 **#96**。为避免与待并草稿撞号，本 T10-a 草稿顺延预占 **#97**（DF1/DF4/DF5/DF6 四件共一登记号，下分四子项）；**最终编号由指挥官合并时统一裁定**（若前序草稿不占号则本登记依次回落）。
> **版本坐标**：HEAD `553135b`（`git rev-parse HEAD` 实测 `553135b3da5017b7ea174d80941e1594523d4add`，未前移）。任务书 `任务书-T10a-结论层口径v6-2026-11-06.md`（方案 v1.2 §3 T10 行终签 ACCEPT；**T10 固定走演示值路线**；A3 切片 D 的 DF1/DF4/DF5/DF6，均 P1，指挥官已抽验原文）。
> **纪律**：禁 git 写、禁 pip install、禁跑全量 pytest（指挥官收尾跑）；只改 `v6_curve_fit.py` / `v6_curve_fig.py` / `medical_extract/extract_clinical.py`，新增 `tests/test_conclusion_band_honesty.py` 与本草稿；禁动 `followup/`（DF2/DF3/DF7/DF18 属 T10-b）、`report/` 引擎与禁词表本体、`run_all.py`、`server.py`、step1-7、11 条锁定测试、`conditions-ledger.md`。

- 日期：2026-11-06。任务：结论层「演示数据被当成参考真值/文献带」类病批修；**不做配置框架**，三文件按同一份 `DEMO_BAND` 口径改（测试钉住三份一致）。

## 演示值路线声明（F5，终签裁决，贯穿全片）

本片所有 pA / ΔP / 18.45 / 4.238 / 4.366 / 8.239 / 10.415 / 28.55 / 47.32 / 52.40 等数值**一律按内部演示值（合成演示数据）处理**：三文件均显式写「非归档真值」「非文献参考带」「非临床建议」；`v6_curve_fit.py` 输入无论来自文件还是硬编码回退，打印均带演示属性；v6 图标题/点标/图注含「仿真估计·示例值（合成演示数据）」。**未引用、未暗示任何归档真值口径**；正式文献参考带赛后引入，**T12 定稿后由 T11 对账**（开放项入口见文末）。

## 二选一裁决（登记备案）

| 裁决位 | 备选项 | 本任务选定 | 依据 |
|---|---|---|---|
| F1 带口径数值 | ① 50/80 与 30–150 两套并存、各自加演示标注 ／ ② 合并为**单一** `DEMO_BAND`（绿档 30–50 / 黄档 50–80 / 红档 >80，30 Pa 为内部演示参考线） | **②（单一口径）** | F1 标题「单一参考带口径」+ 原文「统一为一个带口径」；DF1 病根正是两套带对 18.45 给出相反判读（50/80 判绿档、30–150 判低于下沿）。30–150 不再作为独立带出现，其 30 Pa 下沿保留为演示参考线并在两处共用 |
| F1 工况对齐 | ① 二选一（30 L/min 或 @15 L/min） ／ ② 显式双标 | **①+② 并行（如实披露不对齐）** | `DEMO_BAND.flow_caliber` 选 **@15 L/min 单口径**（pA 基线 18.45 Pa 与 v6 曲线同工况）；临床卡 `ref_Q_note` 同时**显式双标**：pA 18.45 @15 L/min 与 v6 同工况，而临床卡 ΔP-流量曲线跨 15/30/45 L/min，演示阈值未做跨工况归一化，旧「以 30 L/min 工况为准」口径已废。不伪装成已对齐 |
| F2 输入不在场 | ① fail-closed 停工 ／ ② 显式标「硬编码演示值」+ 台账登记 | **②（演示值路线）** | 本机实测 `narrowing_qc.json` / 诊断报告4 零命中、`DATA_ROOT` 未设（见「数据可用性」）；演示值路线下回退到显式标注的硬编码演示值，脚本仍可探针实跑并附原始输出（约束 :57 要求）。fail-closed 分支**未取**，如实登记 |

## 三件登记（反例 / 谁接住 / 实义判定）

### 反例（病象，均为「演示数据被当成参考真值/文献带」类）

1. **DF1/P1 两带互斥**：旧 `extract_clinical.py:98-100` `green_max_Pa=50.0 / yellow_max_Pa=80.0` 标「常人带/临界/受阻」且自述「正式文献参考带赛后引入」；旧 `v6_curve_fig.py:16` 把 `30–150 Pa` 画成 `Normal literature band`。同一 pA 基线演示值 18.45：前者判绿档、后者判低于 30 下沿 ⇒ 相反判读。
2. **DF4/P1 输入与外推无标注**：旧 `v6_curve_fit.py:59-60` `V/P` 为硬编码字面量（注释所指 narrowing_qc.json / 诊断报告4 无读取语句）；旧 `v6_curve_fig.py:12` `Vs=np.linspace(0,12,200)` 越过最大样本 10.415 且全程同一条实线不区分外推段；标题 `Patient A - Personalized...`、点标 `CFD simulation points`，全图无「合成/示例/demo」标注。
3. **DF5/P1 禁说词**：`report/wording.py:47` 将「常人带/正常带/正常人/健康人…」列为禁词、`report/README.md:139` 同；旧 `v6_curve_fit.py:76` 输出「工程推荐: 2mm档…常人带中部，安全余量」正撞禁词与红线。
4. **DF6/P1 叙事与计算矛盾**：旧 `:75` 括号写死「介于1mm档4.37与2mm档8.24之间，≈1.2mm壳」，而实测反解正根 **v30≈4.238 cm³（本轮探针复算 4.24）小于 4.37、不在该区间**；且 `v30 is None` 时对 None 用 `:.1f` 抛 TypeError。

钉住反例的测试：`code/pipeline/tests/test_conclusion_band_honesty.py` **32 例**（18 个测试函数、3 组参数化；本任务新增，AST 抽取带口径 + 真实子进程跑 v6 脚本 + 纯函数反例，见下「关闭证据」）。

### 谁接住（改动落点 / 消费链）

- **单一口径落点**：三文件各持**同一份**模块级 `DEMO_BAND` / `TIER_*` / `classify_demo_band(dp_pa)`（无配置文件、无跨包 import——`extract_clinical.py` 的 `sys.stdout.reconfigure` 与 `extract_compare` 导入、`v6_curve_fig.py` 的 matplotlib/QIDI_WORKSPACE 均保持独立）。`classify_demo_band(18.45)` 三处同返回 `TIER_BELOW`。
  - `extract_clinical.py`：`ref_band` 改读 `DEMO_BAND` 字段 + `TIER_*` 标签，新增 `caliber/flow_caliber/demo/source/ref_Q_note(显式双标)/classify_note`，`classify_note` 与打印行实际调用 `classify_demo_band(DP_CAL)`；文档头去「落常人带」，18.45 标内部演示值。
  - `v6_curve_fig.py`：`axhspan` 改为 `DEMO_BAND` 绿档 30–50 + 「内部工程/演示阈值（非文献参考带）」标签；点标/标题/图注「仿真估计·示例值（合成演示数据）」；档位标注走 `classify_demo_band`。
  - `v6_curve_fit.py`：档位结论走 `classify_demo_band`；`build_recommendation_lines` 全部输出经演示值标注。
- **DF4 输入溯源落点**：`v6_curve_fit.py#load_curve_points` 按 `V6_CURVE_INPUT_JSON` → `DATA_ROOT/.../narrowing_qc.json` → 脚本旁 `narrowing_qc.json` 顺序找文件；命中则读 `V_cm3/P_Pa`、打印来源路径 + `hashlib.md5` + 数组；不命中则回退 `DEMO_V/DEMO_P` 并打印「硬编码演示值·非归档真值」。断言 V/P 等长一维 ≥3 点。`#_candidate_inputs` 可 monkeypatch。
- **DF4 外推落点**：`v6_curve_fig.py#main` 把 `Vs` 拆成 `Vs_in`（0→V_MAX=10.415，实线 `b-`）与 `Vs_ext`（V_MAX→12，虚线 `b--` + 图例「外推段（V>10.415 cm³，超出样本域，仿真外推·示例值）」）。
- **DF6 动态叙事落点**：`v6_curve_fit.py#build_tiers(V,P)` 由样本数组动态生成档位表；`#describe_v30(v30,tiers)` 由 v30 与档位表算括号说明（本轮探针输出「反解占位 V≈4.24 cm³，低于最小演示档位 演示档位1(V=4.37)」）；`#solve_v30` 无正根返回 `None`；`#build_recommendation_lines` 在 `v30 is None` 分支不格式化数值、不抛 TypeError。
- **main guard**：`v6_curve_fit.py` / `v6_curve_fig.py` 均包 `def main()` + `if __name__ == '__main__':`，使测试可 import 而不触发 I/O / 绘图 / QIDI_WORKSPACE 退出。

### 实义判定（非重言、不换皮写死、不借措辞改判据）

- **F1 是数值口径统一 + 判读函数化**：两套互斥数值带合并为单一 `DEMO_BAND`，`classify_demo_band` 对 11 组输入（含 None、边界 30/50/80）在三文件独立定义下结果逐一相等（测试 `test_same_tier_conclusion_everywhere` 参数化 11 例 + `test_single_band_caliber_identical_across_three_files` 字典全等）；18.45 由「绿档/低于下沿」相反判读收敛为**同一** `TIER_BELOW`。三份定义为独立源码，任一被改即红 ⇒ 非重言。
- **F2 是真实 IO 替换**：`hashlib.md5` + `json.loads` + 文件读取为运行期执行（测试 `test_load_curve_points_from_file_prints_md5_and_path` 写 tmp_path 合成 json、断言 32 位 md5 与路径回显、V/P 原样读回）；`test_load_curve_points_falls_back_to_labeled_hardcoded_demo` 强制无文件、断言 `source=hardcoded_demo` 与「硬编码演示值/非归档真值」打印。实跑探针见回执。
- **F3/F5 双重锁**：源码级（`test_no_banned_wording_in_source` 三文件逐词扫 12 个禁词/旧冠名）+ 运行级（`test_v6_curve_fit_stdout_is_honest_and_runs` 真实子进程捕获 stdout 逐词扫）；`test_demo_value_route_declared_in_source` 钉「非归档真值」「非文献参考带」在场。非改判据、非放宽禁词表（禁词表本体零触碰）。
- **F4 纯函数反例 + 子进程双锁**：`test_v30_none_branch_no_typeerror...` 钉 None 分支无 `:.1f`、无 `V ≈`；`test_recommendation_lines_are_dynamic_and_honest` 钉括号文本 == `describe_v30(v30, build_tiers(V,P))` 计算值、且「介于」「1.2mm」「4.238」等写死串零残留；`test_build_tiers_is_data_driven_not_hardcoded` 用异于演示值的数组证档位表随输入变化。放行侧（v30 有正根）与停工侧（v30=None、无正根）都不是恒真。
- **未折进恒真布尔**：沿用 `conditions-ledger.md` #76/#88 纪律——没有把「演示属性」写成恒真 flag 当门；`classify_demo_band` 的 branches 由传入 dp 实义决定。

## 关闭证据（DF1 / DF4 / DF5 / DF6 + 验收条目）

| 条目 | 关闭证据 |
|---|---|
| 两处带口径统一 + 演示标注 + 工况对齐/双标（DF1） | `git diff`：`extract_clinical.py` `ref_band` 全字段改读 `DEMO_BAND`/`TIER_*`、增 `flow_caliber`/`ref_Q_note(显式双标)`；`v6_curve_fig.py` `axhspan` 改 30–50 演示绿档 + 去 `Normal literature band`；测试 `test_single_band_caliber_identical_across_three_files`、`test_pa_baseline_18_45_agrees_in_clinical_card_and_v6_fig`、`test_clinical_ref_band_uses_unified_caliber_and_dual_flow_label` |
| v6 输入有溯源（文件+md5 或显式硬编码演示标注）（DF4） | `git diff`：`v6_curve_fit.py#load_curve_points` + `hashlib.md5` + `_candidate_inputs`；测试 `test_load_curve_points_from_file_prints_md5_and_path`、`test_load_curve_points_falls_back_to_labeled_hardcoded_demo`、`test_v6_curve_fit_has_file_provenance_in_source`；探针实跑原始输出见回执（合成 json md5 `598ddb1bcd95ebaec333e996fdbf314c`） |
| 外推段虚线+标注、标题/点标/图注示例值、去病例冠名（DF4） | `git diff`：`v6_curve_fig.py` `Vs_in/Vs_ext` 拆分 + `"b--"` 外推图例、`参考病例演示` 标题、`fig.text` 图注；测试 `test_v6_fig_has_extrapolation_example_caption_and_main_guard`；`QIDI_WORKSPACE` 临时目录真跑渲染成功（PNG 96625 B，见回执） |
| v6 输出过禁词口径（DF5） | 删除「常人带中部 / 安全余量 / 工程推荐 / Normal literature band / Patient A / CFD simulation points」全部字面；档位结论改 `classify_demo_band` 输出；测试 `test_no_banned_wording_in_source`、`test_v6_curve_fit_stdout_is_honest_and_runs`、`test_recommendation_lines_are_dynamic_and_honest` |
| `:75` 括号叙事动态生成 + None 分支（DF6） | `git diff`：新增 `build_tiers` / `describe_v30` / `solve_v30` / `build_recommendation_lines`；旧写死区间/壳厚/`v30:.1f` 全删；测试 `test_v30_none_branch_no_typeerror_and_no_format_of_none`、`test_recommendation_lines_are_dynamic_and_honest`、`test_build_tiers_is_data_driven_not_hardcoded` |
| 新测试全绿 | `python -m pytest code/pipeline/tests/test_conclusion_band_honesty.py -q` → 单文件 **32 passed**；随靶向合并跑 **41 passed**（新 32 + `test_metrics_inputs_provenance.py` 9） |
| 相邻用例不红 | 靶向 6 文件 **93 passed / 50 warnings**（含 11 条锁定 `test_survey_series_select.py`、`test_z_gap_consistency.py`、`test_hardcoded_geometry_anchor.py`、`test_gate_messages_honest.py`、`test_metrics_inputs_provenance.py`；命令见回执） |
| git diff 仅改动范围 | `git diff --stat`：**3 files changed, 356 insertions(+), 81 deletions(-)**（`v6_curve_fit.py` +200/−39、`v6_curve_fig.py` +102/−30、`extract_clinical.py` +54/−12）；另 2 个新增文件为 untracked（`git status --short` 可见）。`git diff --name-only` 仅 3 文件；`followup/`、`report/`、`run_all.py`、`server.py`、step1-7、11 条锁定测试、`conditions-ledger.md` 零触碰（grep 实证见回执）；`git diff --check` clean；`git ls-files --eol` 三文件 `i/lf w/lf`，与仓内未触碰 `.py` 同 |
| 全量 pytest 不回归 | **未跑**（约束：禁跑全量，指挥官收尾跑） |
| 台账草稿三件登记 + 关闭证据 + 演示值路线 + 开放项 | 本文件（「三件登记」/「关闭证据」/「演示值路线声明」/「开放项」四节齐备） |

## 开放项 / 任务书内部冲突（如实上报，不隐瞒）

1. **v6 输入文件不在场（实测）**：`Glob **/narrowing_qc.json` 与 `Glob **/*诊断报告*` 全仓零命中；`DATA_ROOT` / `V6_CURVE_INPUT_JSON` 本机未设（`v6_curve_fit.py` 的 `%DATA_ROOT%` 字面路径 open 抛 `FileNotFoundError`，探针输出可见）。按任务书取**显式硬编码演示标注**分支（非 fail-closed），已在回执声明；合成 json 仅用于探针实证，未入库。
2. **T11 对账入口（本片明确不做）**：本片所有阈值/曲线数值为内部演示值，未引用归档真值；正式文献参考带赛后引入、T12 定稿后由 T11 对账。本任务**不**判定哪个数值是真值、不建立人群参考区间。
3. **任务书内部计数冲突（如实报）**：验收标准 `:66` 写「`git diff` 仅改动范围 **4 文件**」，而「改动范围」枚举为 **3 改 + 2 增 = 5 文件**；且 `git diff` 只列 3 个已跟踪改动文件（2 个新增为 untracked，不进 `git diff`）。本任务按「改动范围」执行 5 文件，计数字样不一致未擅自改任务书，请指挥官合并时裁定。
4. **F1 措辞张力（如实报）**：F1 正文「50/80 与 30–150 **一律标注**演示阈值」可读作两套带并存各自标注，而 F1 标题与正文首句要求「**统一为一个**带口径」。本实现取「合并为单一 `DEMO_BAND`」（30–150 不再作为独立带，其 30 Pa 下沿保留为共用演示参考线）；若指挥官裁定须保留两套带各自标注，改 `v6_curve_fig.py` 一行 axhspan 即可（测试 `test_single_band_caliber_identical_across_three_files` 不依赖带宽度）。
5. **图中文渲染字形告警**：`QIDI_WORKSPACE` 临时目录真跑 `v6_curve_fig.py` 成功出图（96625 B），但 matplotlib `DejaVu Sans` 缺中文字形，打印多条 `Glyph ... missing from font(s)` 告警，中文标题/图注在图上渲染为方框。F2 要求中文「仿真估计·示例值（合成演示数据）」字样，故中文标注为规格必需；字体配置属环境问题，本片未改 `rcParams`（超规格），登记为开放项。
6. **`ref_band.green_label` 等标签值变更的消费面未验证**：`git grep -nE "green_label|ref_band|常人带"` 全仓 `.js/.html/.py` 命中集中在 `wording.py`、`server.py` 的**另一套** `COMPARE_REF_BAND`（`lo_Pa_s_cm3/hi_Pa_s_cm3`，与临床卡 `dP_flow.ref_band` 不同源）、`webapp/index.html` 的演示文案；`viewer_plus_data.js` 为生成产物、`git grep` 对 `green_label` 零命中。标签值由「常人带/临界/受阻」改为 `TIER_*` 演示措辞后，**仓外/未跟踪前端是否消费该字段未验证**，请指挥官合并时确认（本任务禁动前端）。
7. **仓内其它文件仍含「常人带」字样**（`webapp/index.html` 多处演示/路演文案、`report/wording.py` 禁词表本体）：均在本任务禁动范围内，零触碰；本片只保证三改两增文件的口径与禁词，不等于全仓清零。
8. **AGENTS.md §9 派工额度纪律**：`Glob **/AGENTS.md` 实测零命中（实体不在被审仓库），纪律文本仅见任务书 `:4`（输出 tail-20 / ≤20 工具调用 / 每 ~8 次落进度笔记）。本会话为 workbuddy CLI 标准模式直连执行，工具调用数 >20、未采用 ai-bridge「单行指针读任务书」制；如该额度对本通道同样适用，请指挥官裁定是否需按额度重做，本草稿不谎报遵守（与 `ledger-draft-T6.md` 开放项 8 同口径）。
9. **未验证项汇总**：① 未跑全量 pytest（约束，指挥官收尾）；② 真 `narrowing_qc.json` / 诊断报告4 / 归档真值未接入（不在场，走演示值路线）；③ 图 CJK 字形渲染（见开放项 5）；④ `ref_band` 标签仓外消费（见开放项 6）；⑤ 未 git 写（`git diff` / `git status` / `git ls-files --eol` 全为只读）；⑥ OpenFOAM 抽验段因输入不在场被 try/except 跳过，打印演示值路线声明，未产出任何真 ΔP。
10. **行号漂移**：任务书坐标 = HEAD `553135b`；三文件改写后旧坐标（`v6_curve_fit.py:59-60/:75-76`、`v6_curve_fig.py:12/:16/:17/:18/:28`、`extract_clinical.py:98-100`）整体下移，回执/合并以 `git diff` 真实 hunk 为准。

## 改动面（供合并时核对）

- 改 `code/pipeline/v6_curve_fit.py`：+`DEMO_BAND`/`classify_demo_band`、+`load_curve_points`(md5/路径/硬编码回退)、+`build_tiers`/`describe_v30`/`solve_v30`/`build_recommendation_lines`、main guard、全量演示值/禁词标注；删旧硬编码 V/P 字面量与 `:75-76` 承诺义输出。
- 改 `code/pipeline/v6_curve_fig.py`：+同一份 `DEMO_BAND`/`classify_demo_band`、演示样本常量、`Vs_in/Vs_ext` 外推拆分、`axhspan` 演示绿档、标题/点标/图注示例值、去病例冠名、main guard。
- 改 `code/pipeline/medical_extract/extract_clinical.py`：+同一份 `DEMO_BAND`/`classify_demo_band`、文档头演示标注、`ref_band` 全字段统一口径 + 显式双标 + `classify_note`、打印统一档位。
- 增 `code/pipeline/tests/test_conclusion_band_honesty.py`（32 例）、本草稿。
- `conditions-ledger.md` / `followup/` / `report/` 引擎与禁词表 / `run_all.py` / `server.py` / step1-7 / 11 条锁定测试：**零触碰**。
