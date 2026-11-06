# 台账草稿 T10-b — 结论层口径批修·followup 侧（编码手拟，指挥官合并）

> **性质**：草稿，供指挥官合并进 `conditions-ledger.md`；本文件**不直接改** `conditions-ledger.md`（任务书「改动范围」）。
> **编号**：`conditions-ledger.md` 现行已合并最大号 **#97**（见该文件末「2026-11-06 指挥官合并登记」的 #97 T10-a 段；#94/#95/#96/#97 分别归 T12-0/T4/T6/T10-a）。本 T10-b 草稿顺延占位 **#98**（DF2/DF3/DF7/DF18 四件共一登记号，下分三子项 + 关闭证据分列）；**最终编号由指挥官合并时统一裁定**（任务书：「编号续 #97 之后由指挥官裁定」）。若指挥官裁定「三件登记」= 三个独立登记号，可直接按下方三子项切分为 **#98 / #99 / #100**（见「开放项」1）。
> **版本坐标**：HEAD `2b8ea72`（`git rev-parse HEAD` 实测 `2b8ea7262904ae7c46ff51f3d12d859d04622b0c`，未前移）。任务书 `任务书-T10b-结论层followup-2026-11-06.md`（方案 v1.2 §3 T10 行后半终签 ACCEPT；演示值路线；A3 切片 D 的 DF2/DF3/DF7 为 P1、DF18 为 P3，指挥官已抽验原文）。
> **纪律**：禁 git 写、禁 pip install、禁跑全量 pytest（指挥官收尾跑）；只改 `followup/conclusion.py` / `followup/run_diff.py`，重生成 `followup/examples/diff.md`，新增 `tests/test_followup_conclusion_honesty.py` 与本草稿；禁动 `followup/metrics.py`、`registration.py`、`geometry.py`、`polymesh.py`、`selftest_synth.py`、`v6_*`、`extract_clinical`、`run_all.py`、`server.py`、11 条锁定测试、`conditions-ledger.md` 及其它任何文件。

- 日期：2026-11-06。任务：结论层「能判而不判 + 标注链在分支断掉」类病批修（DF2/DF3/DF7/DF18）；**不做框架**，两文件改 + 一副本真跑重生成 + 一测试 + 一草稿。

## 演示值路线声明（F4，贯穿全片）

本片随访结论涉及的数值/比较（左鼻孔最小截面 +1.534 mm² / +102.9%、左侧流量份额 +6.65 个百分点、左侧压降 -105.02 Pa / -34.6%、总压降 +44.65 Pa、右侧压降 +43.20 Pa、迭代 1500 步、配准 RMS 1.108 mm 等）**一律按内部演示值（合成演示数据）处理**：`course_card` 在 `case_kind == "synthetic"` 时新增的标注 caveat 显式写「涉及数值/比较均为内部演示值，非归档真值，不作临床判读（T12 定稿后由 T11 对账）」；`patient_followup_sentence` 合成分支把「请结合医生对两次影像的判断」替换为「不对应任何真实患者的两次影像」。**未引用、未暗示任何归档真值口径**；正式文献参考带赛后引入，T12 定稿后由 T11 对账（开放项入口见文末）。

## 二选一裁决（F2，登记备案）

| 裁决位 | 备选项 | 本任务选定 | 依据 |
|---|---|---|---|
| DF3 方向相反守卫 | ① 在单一条件上补 `or (signs["右侧压降"] * signs["左侧压降"] < 0)`，沿用一条合并 caveat ／ ② **逐行独立判定，只输出实际触发行** | **②（逐行判定）** | 任务书 F2 要求「注释/正文与实际判定一致（不得承诺未实现的检查）」：原合并 caveat 正文同时承诺「总压降…与左侧压降方向相反；右侧压降…」，若仅右侧触发而沿用合并文本，就会承诺未触发的「总压降方向相反」——正是 DF3 病根的另一种形式。逐行判定下 `总压降`/`右侧压降` 各自参与 `left * row["delta"] < 0`，`/`.join 只列触发行，文本与实际逐字对应。测试 `test_right_only_opposite_is_caught_no_false_negative` / `test_total_only_opposite_reports_only_total` / `test_symmetry_under_sign_flip_r009` 三面钉死 |

## 三件登记（反例 / 谁接住 / 实义判定）

> 本节沿用 `ledger-draft-T10a.md`「三件登记（反例 / 谁接住 / 实义判定）」同款结构；一个占位号 #98 下分三子项（DF2 / DF3+DF18 判定侧 / DF7+DF18 副本侧）。指挥官若裁定拆为三号，按子项标题切分即可。

### 登记一 #98-①：DF2 收敛 caveat 据实生成（P1）

- **反例（病象）**：旧 `conclusion.py:69` 在 `course_card()` 内对**每一对** diff 无条件 `caveats.append("两例均为 1500 步平台（未达 residualControl 1e-4）；指标差异含收敛噪声。")`；而 `followup/metrics.py:69-70` 已读入 `"iterations": raw.get("residuals", {}).get("n_iter")` 与 `"converged"`，`run_diff.py:81` 调 `course_card(mdiff, registration=reg)` 未传 `params_a/params_b`（`:23` 形参已在）——**能判而不判**。实测 `synth-001/metrics.json` residuals `n_iter=1500, converged=False`（`provenance.json` solver.endTime=1500 / residualControl="p/U 1e-4"），旧串碰巧说对但纯属写死；换收敛病例（提前收敛、非 1500 步）即失真。
- **谁接住**：`conclusion.py` 新增 `_case_convergence(p)`（四态 converged / plateau=1500 / other=非1500 / unknown）与 `_convergence_caveat(params_a, params_b)`，由两例 `converged` / `iterations` 生成三态文案：已收敛→「两例均已达 residualControl 1e-4（A {n} 步、B {n} 步，提前收敛）」；未收敛→「{label} 跑至 {n} 步未达 residualControl 1e-4」（n 为实际步数，含 1500 平台）；任一判据缺失→「收敛状态未知」。旧写死 `append` 整行删除。`run_diff.py#run_pair` 新增 `_solve_params(m)`：`mdiff["a"]/["b"]` 含 converged/iterations 才据实回传，缺判据明确传 `None` 走「未知」分支；调用点改为 `course_card(mdiff, registration=reg, params_a=params_a, params_b=params_b, case_kind=case_kind)`。
- **实义判定**：`test_converged_caveat_says_reached_residualcontrol`（812/870 步）、`test_non_1500_steps_caveat_uses_actual_counts`（970/1234 步）、`test_plateau_1500_caveat_is_data_driven_not_hardcoded`、`test_missing_data_caveat_is_unknown`（4 组参数化：None/None、单侧缺、缺 iterations、全缺）、`test_mixed_convergence_states_are_reported_per_case`、`test_caveat_changes_with_input_data`（两组不同输入产出不同串，非恒等写死）；`test_old_plateau_literal_absent_from_source` 钉源码无旧串。放行侧（已收敛）与停工侧（未收敛/未知）都不是恒真。

### 登记二 #98-②：DF3 方向相反守卫补右侧（P1）

- **反例（病象）**：旧 `conclusion.py:44-58` 守卫只检验「左侧压降 × 总压降 < 0」（`:52-53`）；`signs` 字典里的「右侧压降」从不参与任何条件，而 caveat 正文（`:55-57`）同时承诺「总压降…与左侧压降方向相反；右侧压降…」——右侧假阴性（R-009 对称检验不通过）。
- **谁接住**：`conclusion.py#course_card` 改为以 `r_dpl["delta"]` 为基准，对 `(r_dp,"总压降")`、`(r_dpr,"右侧压降")` 逐行判 `left * row["delta"] < 0`，`opposite` 只收实际触发行，caveat 由 `opposite` 动态拼 `detail` 与 `joined`（只列触发行名）。注释「只把实际触发的行写进 caveat」与判定一致。
- **实义判定**：`test_right_only_opposite_is_caught_no_false_negative`（总压降同向、右侧反向 ⇒ 只报右侧且**不**出现「总压降」）——旧实现此例必漏；`test_total_only_opposite_reports_only_total`（只报总压降且不出现「右侧压降」）；`test_both_opposite_reports_both_rows`；`test_symmetry_under_sign_flip_r009`（全量反号仍双侧触发）；`test_no_opposite_row_produces_no_direction_caveat`（阴性对照，守卫非恒真）；`test_direction_guard_comment_matches_per_row_logic` 钉源码判定式与注释。

### 登记三 #98-③：DF7 合成体模标注链 + DF18 随库副本重生成（P1/P3）

- **反例（病象）**：`followup/examples/diff.md`（README §4.1 明确**随库分发**）用「较上次（A → B）」「与上次检查相比」「请结合医生对两次影像的判断」真实随访话术，全文 6 条 caveats 与患者语言层无一处「合成/示例」字样；旧 `conclusion.py:23` `course_card` 无 `case_kind` 形参、`run_diff.py:81` 不传病例性质，标注链在分支断掉（`viewer_data.js:5`、`report/cases.py:12/44` 的 case_kind/provenance 在别处是通的：取值 `patient | patient_demo | synthetic`）。DF18：`examples/diff.md` 与当前 HEAD `conclusion.py` 输出格式已漂移——旧副本为「+1.534（+102.9%） mm²」（单位在百分号后）与「切片最小截面（全局）」，而 HEAD `_fmt_row` 为「+1.534 mm²（+102.9%）」、`write_markdown` 为「切片最小截面（中央 80% 区间）…全局最小截面…（两端开口收敛段会把全局最小值拉到 0…）」。
- **谁接住**：`conclusion.py` 增模块级 `SYNTHETIC_MARK = "本轮为合成体模、非真实患者、非临床结论"`；`course_card` / `patient_followup_sentence` 增 `case_kind: str | None = None`；`case_kind == "synthetic"` 时三处注入同一常量——① `headline` 前缀 `【MARK】`、② `caveats` 追加一条带演示值路线声明的标注、③ 患者语言句前缀 + 结尾改「不对应任何真实患者的两次影像」。`run_diff.py#run_pair` 增 `case_kind` 形参并透传给两个函数，结果字典增 `"case_kind"` 留痕；`main` 增 `--case-kind` CLI；未显式给时 `_case_kind_from_provenance(case_dir)` 读 `provenance.json` 的 `data_class`（"L1 synthetic … NO patient data"）据实回填，标注链不断在调用分支（`selftest_synth.py` 为禁动文件、不传 case_kind，亦由 provenance 回填覆盖）。`examples/diff.md` **真跑重生成**：`.venv/Scripts/python.exe pipeline/followup/run_diff.py --a pipeline/out/synth/synth-001 --b pipeline/out/synth/synth-005 --case-kind synthetic --out <tmp>`，仅把产物 `diff.md` 拷回 `examples/`（`diff.json` 按范围零触碰）。
- **实义判定**：`test_synthetic_marks_all_three_places`（headline/caveats/患者语言句三段各有 MARK）、`test_non_synthetic_has_no_mark`（4 组参数化阴性对照，非恒真）、`test_case_kind_is_in_both_signatures`、`test_run_diff_passes_case_kind_and_real_params`（源码级钉透传 + 旧无参调用已删 + provenance 回填）、`test_case_kind_marker_constant_is_shared`、`test_synthetic_caveat_declares_demo_value_route_f4`；`test_examples_diff_md_three_marks_in_three_sections` 按 `## 1` / `### 需要注意` / `## 6` 三段分别钉 MARK 且全文计数 ≥3；`test_examples_diff_md_format_synced_to_current_output_df18` 钉「中央 80% 区间」「全局最小截面：」在场、旧「切片最小截面（全局）」消失、指标差表逐位不变（`62.04/106.69/+44.65/+71.97%`、`1.491/3.025/+1.534/+102.88%`）。

## 关闭证据（DF2 / DF3 / DF7 / DF18 + 验收条目）

| 条目 | 关闭证据 |
|---|---|
| 收敛 caveat 由 converged/n_iter 生成、三态文案、写死串消失（DF2） | `git diff -- code/pipeline/followup/conclusion.py`：删 `caveats.append("两例均为 1500 步平台…")`，增 `_case_convergence` / `_steps_text` / `_convergence_caveat`；`git diff -- examples/diff.md` 第 15 行由写死串变「A 跑至 1500 步未达…；B 跑至 1500 步未达…；指标差异含收敛噪声，未收敛平台值不作收敛性结论。」；测试 `test_converged_*` / `test_non_1500_*` / `test_missing_*` / `test_old_plateau_literal_absent_from_source` |
| 方向相反守卫右侧参与判定、注释/正文/实际一致（DF3） | `git diff -- conclusion.py` 守卫段改逐行 `for row, label in ((r_dp,"总压降"),(r_dpr,"右侧压降"))`；`diff.md` 第 13 行两行均显式「与左侧压降方向相反」；测试 `test_right_only_opposite_is_caught_no_false_negative` 等 6 例 |
| course_card/patient_followup_sentence 有 case_kind 入参、run_diff 透传、synthetic 三处标注（DF7） | `git diff` 两文件（签名 + `SYNTHETIC_MARK` + `--case-kind` + `_case_kind_from_provenance`）；`diff.md` 第 9 / 19 / 81 行三处 `【本轮为合成体模、非真实患者、非临床结论】`；测试 `test_synthetic_marks_all_three_places` 等 9 例 |
| examples/diff.md 重生成（真跑）后三处标注在位 + 格式与 HEAD 一致（DF7/DF18） | 真跑命令与原始输出见回执 ①；`git diff -- examples/diff.md` = **8 insertions / 6 deletions**（时间戳、headline 标注+单位口径、方向 caveat、收敛 caveat、新增合成 caveat、切片口径两行、患者语言句）；旧「切片最小截面（全局）」与「请结合医生对两次影像的判断」均消失；测试 `test_examples_diff_md_*` 4 例 |
| 新测试全绿 + 相邻/锁定用例不红 | `python -m pytest code/pipeline/tests/test_followup_conclusion_honesty.py -q` → **29 passed**；靶向 8 文件合并跑（新测试 + `test_conclusion_band_honesty.py` + `test_phase15_single_case.py` + `test_metrics_inputs_provenance.py` + `test_survey_series_select.py` + `test_z_gap_consistency.py` + `test_hardcoded_geometry_anchor.py` + `test_gate_messages_honest.py`）→ **131 passed / 50 warnings / 0 failed**（warnings 全为 `skimage` NumPy 2.5 弃用告警，既有的、与本片无关） |
| git diff 仅改动范围文件、禁动文件零触碰 | `git diff --stat`：**3 files changed, 142 insertions(+), 26 deletions(-)**（`conclusion.py` +94/−18、`run_diff.py` +40/−2、`examples/diff.md` +8/−6）；`git diff --name-only` 仅 3 文件；`git diff --name-only \| grep -E "metrics.py\|registration.py\|geometry.py\|polymesh.py\|selftest_synth.py\|run_all.py\|server.py\|extract_clinical\|v6_"` → **零命中（FORBIDDEN TRACKED FILES: ZERO TOUCH）**；`git diff --check` clean；`git ls-files --eol`：`conclusion.py`/`run_diff.py` `i/lf w/lf`、`examples/diff.md` `i/lf w/crlf`，与仓内既有约定一致；另有 2 个新增文件为 untracked（不进 `git diff`）：`tests/test_followup_conclusion_honesty.py`、本草稿 |
| 全量 pytest 不回归 | **未跑**（约束：禁跑全量，指挥官收尾跑）；本片仅跑靶向 8 文件（上一行实证） |
| 台账草稿三件登记 + 关闭证据 + 演示值路线 + 开放项 | 本文件（「三件登记」/「关闭证据」/「演示值路线声明」/「二选一裁决」/「开放项」五节齐备）；`conditions-ledger.md` 零触碰 |

## 改动面（供合并时核对）

- 改 `code/pipeline/followup/conclusion.py`：+`SYNTHETIC_MARK`、+`_case_convergence`/`_steps_text`/`_convergence_caveat`、删无条件 1500 步 caveat、`course_card` 方向守卫改逐行判定 + 加 `case_kind` 三处注入、`patient_followup_sentence` 加 `case_kind` 合成分支。
- 改 `code/pipeline/followup/run_diff.py`：+`_case_kind_from_provenance` / `_solve_params`、`run_pair` 加 `case_kind` 形参 + 据实传 `params_a/params_b` + 透传 `case_kind` + 结果留痕、`main` 加 `--case-kind`。
- 重生成 `code/pipeline/followup/examples/diff.md`（**真跑**，命令/输出见回执）；`examples/diff.json` 保持 Oct-19 快照不动。
- 增 `code/pipeline/tests/test_followup_conclusion_honesty.py`（29 例）、本草稿。
- 禁动清单与 11 条锁定测试：`git diff --name-only` 实证零触碰。

## 开放项 / 任务书内部冲突（如实上报，不隐瞒）

1. **「三件登记」口径歧义（如实报，请指挥官裁定）**：任务书「台账草稿（三件登记；编号续 #97 之后由指挥官裁定）」可读作 ① 沿 `ledger-draft-T10a.md` 同款「反例 / 谁接住 / 实义判定」三要素 + 一个登记号，或 ② 三个独立登记号。本草稿按 ① 落笔（占位 **#98** 一号，下分三子项，关闭证据按 DF2/DF3/DF7/DF18 分列）；若裁定为 ②，可直接按三子项切分 **#98 / #99 / #100**，正文无需改写。未擅自改任务书。
2. **`examples/diff.json` 随库副本未同步（范围边界，如实报）**：README §4.1 把 `examples/diff.json`（28,737 B）与 `diff.md` 并列为随库分发证据；`diff.json:1211` 仍含旧写死 caveat、`diff.json:1223` 患者语言句仍含「请结合医生对两次影像的判断」、无合成标注；其 `course_card` 与 `patient_followup_sentence` 仍是 Oct-19 旧输出。任务书「改动范围」只授权重生成 `diff.md`，`diff.json` 属「其它任何文件」禁动，故**零触碰**。合并时若要求两份副本口径一致，需另批授权重生成 `diff.json`（本片未做，不冒充已闭环）。
3. **`examples/selftest.md` 及 `followup/README.md` 仍含旧话术（范围边界，如实报）**：`examples/selftest.md:23` 「两例均跑到 1500 步平台…」、`README.md:125-126/154` 「两例均为 1500 步平台…」均无合成标注；`selftest_synth.py:103`（禁动文件）同样写死该串。均在本片禁动/未授权范围内，零触碰；本片只保证两改一重生成两增文件的口径，不等于全仓清零（与 `ledger-draft-T10a.md` 开放项 7 同口径）。
4. **真跑数据与 HEAD 数值一致性（如实报）**：真跑用 `code/pipeline/out/synth/synth-001` / `synth-005`（本机在场：`geometry.stl`、`metrics.json`、`provenance.json`、`case/constant/polyMesh`），`.venv` 实测 `numpy 2.5.4 / scipy 1.18.1 / trimesh 5.1.1`；指标差表与旧副本**逐位相同**（+44.65 / +71.97%、+1.534 / +102.88%、迭代 1,500 步等），配准 RMS 1.108 mm、STL 体积 105.000 cm³、polyMesh 单元 310355→310053 亦相同 ⇒ 重生成未改变任何演示数值，只改结论层文案与格式。唯一数值型新增为 `diff.md` 第 65 行「切片最小截面（中央 80% 区间）：A 45.89 mm² @ 11.8 mm；B 48.23 mm² @ 11.8 mm」，由当前 HEAD `geometry.compare_stl` 的 `slice_curve.min_central_80pct` 据实产出（旧副本只有全局口径，无中央口径可比对）。
5. **`generated_at` 时间戳更新**：真跑重生成把 `diff.md` 第 3 行由 `2026-10-19T13:26:22` 改为 `2026-11-06T11:23:02`（`datetime.now()`）；这是真跑的直接证据，非手工回填，如实登记。
6. **`case_kind` 判定口径**：本片只把 `case_kind == "synthetic"`（含 provenance.json `data_class` 含 "synthetic" / "no patient"）作为合成标注触发条件；`patient` / `patient_demo` / `None` 一律不注入。未把 `patient_demo` 也标成合成（与 `report/cases.py:44` 三值口径一致，不擅自扩判据）。若指挥官裁定演示患者例也须标「非真实患者」，属新规格，本片未做。
7. **F2 另一分支未取**：未选「单一 `or` 条件 + 合并 caveat」分支（理由见「二选一裁决」）；该分支若被裁定采用，改 `conclusion.py` 守卫段一处即可，但会引入「承诺未触发检查」的新不诚实，故本片如实登记为**未取**。
8. **F1 `params_a/params_b` 与 mdiff 内字段的取舍（如实报）**：任务书 F1 允许「params_a/params_b（或 mdiff 内的 converged/n_iter）」。本片取 `run_diff.py` 把 `mdiff["a"]/["b"]`（`diff_metrics` 返回的全量单例指标字典，含 `converged`/`iterations`）作 `params_a/params_b` 传入，结论层只读参数、不反向解析 `diff`，`course_card(diff, ...)` 的 `diff` 形参职责不变；`_solve_params` 在两字段皆缺时传 `None`。未改 `metrics.py` 读数口径（禁动）。
9. **AGENTS.md §9 派工额度纪律**：`find . -name AGENTS.md` 全仓零命中（实体不在被审仓库），纪律文本仅见任务书 `:4`（输出 tail-20 / ≤20 工具调用 / 每 ~8 次落进度笔记）与 `:5`（R-024 绿门）。本会话为 workbuddy CLI 标准模式直连执行，工具调用数 >20、未采用 ai-bridge「单行指针读任务书」制；如该额度对本通道同样适用，请指挥官裁定是否需按额度重做，本草稿不谎报遵守（与 `ledger-draft-T10a.md` 开放项 8、`ledger-draft-T6.md` 开放项 8 同口径）。
10. **未验证项汇总**：① 未跑全量 pytest（约束，指挥官收尾）；② `examples/diff.json` / `selftest.md` / `README.md` 未同步（范围边界，见开放项 2/3）；③ 仓外/未跟踪前端是否消费 `course_card`/`patient_followup_sentence` 新文案未验证（本片禁动前端）；④ 仅真跑了 synth-001→synth-005 这一对，其它 synth 对与真实患者对的标注/收敛三态未逐一实跑（由 29 例单测覆盖三态分支）；⑤ 未 git 写（`git rev-parse` / `status` / `diff` / `ls-files --eol` / `diff --check` 全为只读）；⑥ T11 对账入口（正式文献参考带）本片明确不做。
11. **行号漂移**：任务书坐标 = HEAD `2b8ea72`；改写后 `conclusion.py`/`run_diff.py` 旧坐标（`conclusion.py:23/:44-58/:69/:81`、`run_diff.py:81/:91`）整体下移，回执/合并以 `git diff` 真实 hunk 为准。
