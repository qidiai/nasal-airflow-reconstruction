# 台账草稿 T4 — 门禁话术诚实化（编码手拟，指挥官合并）

> **性质**：草稿，供指挥官合并进 `conditions-ledger.md`；本文件**不直接改** `conditions-ledger.md`（任务书「改动范围」）。
> **编号**：`conditions-ledger.md` 现行已合并最大号 **#93**（见该文件末「登记表（#93 已知限制与开放项）」）；`ledger-draft-T12-0.md`（指挥官代补，2026-11-06）已按「续现行最大 #93」预占 **#94** 待并。为避免与待并草稿撞号，本 T4 草稿顺延取 **#95**；两草稿最终编号由指挥官合并时统一裁定（若指挥官判定 T12-0 不占 #94，则本登记回落 #94）。
> **版本坐标**：HEAD `03a2c6b`（派工时实测一致，未前移）。任务书 `任务书-T4-门禁话术诚实化-v2-2026-11-06.md`，覆盖 A2-Q3 收尾 + A3 切片 C 的 CF1/CF2/CF3/CF7/CF8 与 B 片 B6/B10/B11。
> **纪律**：禁 git 写、禁 pip install、禁跑全量 pytest（指挥官收尾跑）；禁动 `airway_geom.py`、11 条锁定测试（`test_survey_series_select.py`）、`conditions-ledger.md`、T1/T3/T12-0 全部文件；只改 `run_all.py` / `server.py`、新增 `tests/test_gate_messages_honest.py` 与本草稿。

- 日期：2026-11-06。任务：门禁**话术**诚实化 + die 消息透传 + z_gap 暴露。改动**不含**任何门的判定式。

## 二选一裁决（选定，登记备案）

| 裁决位 | 备选项 | 本任务选定 | 依据 |
|---|---|---|---|
| F1 `server.py` 停工 `gate` 名（原 :2162） | 改「DICOM 头普查（读层完整性）」／保留原名 | **改为「DICOM 头普查（读层完整性）」** | 原名「层序结构断言」把恒真项当判据；新名对齐「读层完整性」实义（CF1/CF2） |
| F1 D5 `z_structurally_ok` 恒真条件 | 删／保留+披露 | **保留+披露（默认）** | 代码作者注释（原 `run_all.py:583-586`）已论证「删掉会动门的定义面且无收益」；本任务一字节不动，仅在文案标注「构造性恒真/非判据」 |
| F1/B10 `run_all.py` S1 日志（原 :1156） | 改打印 `filename_order_matches_physical`／删除该段 | **删除恒真「z 单调」段**，保留同行已打印的 `文件名序=物理序`（即 `filename_order_matches_physical`） | `z_monotonic_increasing` 构造性恒真、无信息量（CF3/B10）；`filename_order_matches_physical` 有判别力（#56 反例见 `test_survey_series_select.py`） |
| F2 web 白名单 `z_monotonic_increasing` | 移除／保留但文案标注非判据 | **移除**（`rec` 内键值不动，只改白名单投影） | 直接消除 CF3「恒真键进白名单」根因；选中「移除」而非「标注」 |

## 三件登记（反例 / 谁接住 / 实义判定）

- **反例**（病象，均为「无判别力字段被宣称为判据 / 恒真值当实测呈现」类话术病）：
  1. `run_all.py`（原 :1159-1161）与 `server.py`（原 :2159-2162）把三个值并列宣称为「层序结构断言 FAIL」，且把「读层器跳过的文件总数」误称「缺IPP层数」（CF1/CF2，A2-Q3）；
  2. `z_monotonic_increasing` 构造性恒真，却进 `server.py`（原 :2146）web 白名单、在 `run_all.py`（原 :1156）恒打印「z 单调增」（CF3/B10）；
  3. `die()` 原 `sys.exit(code)` 异常只带 code ⇒ `str(SystemExit(2))=='2'` ⇒ web `survey_error` 裸 `"2"`，并被 `or` 短路吞掉可读原因（CF7/#84，B11 另：FATAL 只走 stdout/manifest-progress）；
  4. 四个 `z_gap_*` 量化键已算（`run_all.py:624-627`）但不在 web 白名单（`grep -cF "z_gap_" server.py` 原 = 0），工作台不展示偏差/容差（CF8/#81）。
  - 钉住反例的测试：`code/pipeline/tests/test_gate_messages_honest.py` 12 例（本任务新增）；旧话术基线由锁定测试 `test_survey_series_select.py:4/11` 与 `test_z_gap_consistency.py:210` 保留。

- **谁接住**（改动落点 / 消费链）：
  - **层序停工文案**：新增 `run_all.structurally_ok_failure_message(rec)`（只报实际失败条件 + 上下文数值，不做文案框架，一函数够）。`run_all.py` S1 停工 `die(2, structurally_ok_failure_message(survey))` 与 `server.py` web `reason = ... RA.structurally_ok_failure_message(survey)` **共用同一函数** ⇒ 一处改、两端文案一致，将来新门复用只需加一个条件描述（问题定性泛化方案）。
  - **die 消息透传**：新增 `class DieExit(SystemExit)`（`super().__init__(code)` 存 `msg`、`__str__` 返回 msg），`die()` 改 `raise DieExit(code, msg)`；`server.py` 的 `except SystemExit` 改为 `e.msg if isinstance(e, RA.DieExit) else str(e)`，非 DieExit 保持 `str(e)` 原行为；PII 两处 `except SystemExit`（`server.py:2095/2890`）经 `DieExit.__str__` 自动获得可读原因（附带改善，未单列断言）。
  - **FATAL / 日志**：`die()` 内 FATAL 行除 `log()`（stdout + manifest-progress.json）外，同行 `print(..., file=sys.stderr)`；S1 日志删恒真段、保留有信息量的 `filename_order_matches_physical`。
  - **白名单**：`server.py` survey 键投影移出 `z_monotonic_increasing`、加入 `z_gap_max_abs_dev_mm` / `z_gap_max_rel_dev` / `z_gap_tol_mm` / `z_gap_bad_pairs`（tuple 排版风格保留，`z_gap_bad_pairs` 为 list 可 JSON 序列化）。四键仍由 `survey_dicom`（`run_all.py:624-627`）产出，源头未改。
  - **前端**：不要求改动（`z_gap` 四键的查看器/拦截卡渲染 = 开放项，另批）。

- **实义判定**（非重言、非「改文案顺手调判据」）：
  - 本任务纯属**话术 / 白名单投影 / 日志 / 异常机制**层。`z_structurally_ok` 三条件、`max(1, int(0.05 * len(files)))` 5% 容差、间隙一致性门 `if not greport["uniform"]`、PII 门、T2 准入/适用性断言**逐字节不动**；`git diff` 只含 die 机制 / helper / 日志 / 白名单 / reason / gate 名 / 注释（实证见回执 `git diff`）。`test_gate_judgment_expressions_byte_unchanged` 逐片段钉住。
  - 「跳过文件数（非图像/缺几何/读取失败）」口径 = 读层器实际跳过的文件总数（`survey_dicom` 内 `rep["n_skipped"]`，原 `run_all.py:568-570`），与 `n_slices_selected` 同源；**不是**「缺 IPP 的层数」。
  - 恒真两项（≥2 层、差值 >0）在文案中显式标注「构造性≥2 / 构造性>0，非判据」，不作失败判据宣称（D5 保留+披露）；「5% 容差上限由门内判定，不在此重算」——helper 不重算任何判据（实义：不借措辞改门）。
  - DieExit 实义：`super().__init__(code)` 保 `.code` 为数字，进程退出码实测仍为 2 / 3（既有退出码断言与 web `exit_code` 依赖）；`__str__` 给 msg，`web survey_error` 不再裸 `"2"`。
  - z_gap 暴露实义：四键入白名单后投影 JSON 可序列化（`test_zgap_keys_in_real_survey_json_serializable` 用真实 `survey_dicom` 产物钉住，非平凡：bad_pairs 为 list）。

## 关闭证据（CF1/CF2/CF3/CF7/CF8 + B6/B10/B11）

| 条目 | 关闭证据 |
|---|---|
| CF1/CF2（A2-Q3 收尾）+ B6 | `test_structural_message_only_claims_real_condition`（「缺IPP层数」消失、恒真项标非判据、只报实际失败条件、钉住 `层序结构（读层完整性）门 FAIL：实际失败条件=...` 具体串）、`test_structural_message_lists_context_numbers`（上下文数值齐）、`test_work_stop_callsites_share_helper_and_old_wording_gone`（两处共用 helper、旧话术/gate 名消失） |
| CF3 / B10 | `test_web_whitelist_has_four_zgap_and_drops_monotonic`（`z_monotonic_increasing` 移出 web 白名单）、`test_run_all_log_drops_constant_monotonic`（日志停打印恒真 z 单调、留 `文件名序`） |
| CF7 / #84 | `test_die_exit_carries_numeric_code_and_message`（code=2 且 `str(e)`/msg 带消息）、`test_die_exit_keeps_code_3`（code=3）、`test_non_dieexit_systemexit_str_unchanged`（非 DieExit 原行为）、`test_survey_die_error_readable_not_bare_2`（空目录 die 后 `str(e)!='2'` 且含「无有效轴位切片」）；`server.py` `e.msg if isinstance(e, RA.DieExit) else str(e)` 由源码测试钉住 |
| CF8 / #81 | `test_web_whitelist_has_four_zgap_and_drops_monotonic`（四键入白名单）、`test_zgap_keys_in_real_survey_json_serializable`（源 rec 四键 + 投影 JSON 可序列化） |
| B11 | `test_fatal_line_written_to_stderr_and_stdout_unchanged`（FATAL 同行进 stderr，stdout 既有内容不变） |
| 判定逻辑零改动 | `test_gate_judgment_expressions_byte_unchanged`（五段判定片段逐字仍在）+ `git diff` 实证（回执） |
| 新测试 | `python -m pytest code/pipeline/tests/test_gate_messages_honest.py -q` → **12 passed**（Python 3.12.10 / pytest 8.4.2，靶向） |
| 既有靶向回归 | `test_survey_series_select.py`（11 锁定）/ `test_z_gap_consistency.py` / `test_survey_header_only.py` 原始输出见回执；全量 pytest 由指挥官收尾跑 |

## 开放项 / 任务书内部冲突（如实上报，不隐瞒）

1. **【任务书内部冲突，须指挥官裁定】白名单 12 键硬断言**：`code/pipeline/tests/test_series_suitability.py:443-447` 的 `test_server_gate_web_path_blocks_with_card` 有硬编码 `assert sorted(rec["survey"]) == sorted([...12 个键...])`，注释自称「白名单 12 键一字未增」；本机 flask 3.1.3 在场（`pytest.importorskip("flask")` 不跳过）⇒ 该用例必跑。本任务 F2 移除 `z_monotonic_increasing` + F5 加四个 `z_gap_*` ⇒ 白名单由 **12 → 15 键（12−1+4）** ⇒ 该断言**必红**。该文件在「禁动：其它任何文件 / T1/T3/T12-0 文件」射程内，编码手**未改**；且任务书明定「禁跑全量 pytest（指挥官收尾跑）」。建议指挥官合并时把该期望键表更新为 15 键（或按裁决回退 F2 到「保留+标注」选项使其变 16 键后再更新）。编码手不擅自改禁动文件、不跑全量 pytest 凑数、**不以放宽 F5 回避冲突**。
2. **编号撞号**：`ledger-draft-T12-0.md` 预占 #94（见文首编号注），本草稿取 #95；合并时统一裁定。
3. **前端不展示 z_gap 键**：F5 仅打通 web 白名单投影，`server.py` 返回的 `rec["survey"]` 含四键，但查看器 / ⛔ 拦截卡前端不渲染这四个数值（#81 的 UI 消费侧），另批。
4. **PII 两处 except 的附带变化**：`server.py:2095/2890` 的 `str(e)` 现因 `DieExit.__str__` 由裸 `"2"` 变可读停工原因；属 F3 机制的副作用、非明确对象，未单列断言，登记备查。
5. **行号漂移**：任务书行号坐标 = HEAD `03a2c6b`（实测一致）；因 `run_all.py` 新增 ~44 行、`server.py` 新增若干行，任务书引用的旧坐标（如 `run_all.py:1161`、`server.py:2159-2162`）整体下移，回执以 `git diff` 真实 hunk 为准。
6. **未验证项**：按约束**未跑全量 pytest**（指挥官收尾）；`test_series_suitability.py` 冲突用例已单独靶向确认（输出见回执），其余既有用例仅做本任务相关的靶向回归，全量不回归由指挥官合并时核验。

## 改动面（供合并时核对）

- 改 `code/pipeline/run_all.py`：`DieExit` 类 + `die()`（raise DieExit / FATAL 写 stderr）+ `structurally_ok_failure_message()` 新增；S1 日志删恒真段；S1 层序停工 `die` 改用 helper。判定式零改动。
- 改 `code/pipeline/server.py`：survey 白名单（−`z_monotonic_increasing` +四 `z_gap_*`）；`survey_error` 取 `DieExit.msg`；web 停工 `reason` 改用 `RA.structurally_ok_failure_message`；gate 名改「DICOM 头普查（读层完整性）」；若干注释。
- 新增 `code/pipeline/tests/test_gate_messages_honest.py`（12 例）、本草稿。
- `conditions-ledger.md` / `airway_geom.py` / 11 条锁定测试 / T1/T3/T12-0 文件：**零触碰**。
