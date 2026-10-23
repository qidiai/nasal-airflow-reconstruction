# 口径说明（medical_extract）

本文件回答四件事：**三档 split 各是什么**、**两档最小轴面积各是什么**、
**ROOT 怎么解析/失败怎么办**、**为什么作废侧车不放 replica 比对结果**。
文中所有数字都注明来源文件与行号；不写本机绝对路径，不含任何连接端点与凭据信息。

---

## 1. 三档 split（分流比例）——分开命名，禁止跨口径互证

同一个 `51.9 / 48.1` 在不同文件里出现，但它们是三个**不同口径**，不得拼成一条证据链。

| 键名 | 读数（L / R 按代码 inletL/inletR 命名；inletL=患者右、inletR=患者左） | 出处（路径 + 行号 + md5） | 语义 | 能否互证 |
|---|---|---|---|---|
| `split_imposed_RunA` | `39.00135467342238 / 60.99864532657763`（契约侧投影 `39.0 / 61.0`） | ROOT 相对路径 `阶段2-CFD算例包/结果/P0-result-pA-v5/后处理/metrics.json`（`totals.flow_share_L_pct` / `flow_share_R_pct`，md5=`9a49276eed10bbef6a9210e3182ab854`）；仓内契约 `code/pipeline/out/postprocess/contract-pA-v1.json` `metrics.split_L_pct/split_R_pct`；生成式 `code/pipeline/step2_make_ofcase.py:1548` 与 `:1563-1564`（代码自注「按开口面积比例分配，声明为建模假设（审计R2）」） | **边界条件输入的复述，非生理量，非患者真实分流** | 否 |
| `split_natural_RunB` | `51.86676904959288 / 48.13323095040711` | ROOT 相对路径 `阶段2-CFD算例包/结果/P0-result-pA-v5C/后处理/metrics.json`（Run-B 等压终态，md5=`4a8b22024769c0846cddf149d711f651`） | 求解结果（等压终态），**单例未复算、未收敛判定** | 与 Run-A 口径不同，不可互证 |
| `split_synthetic_demo` | `50.0 / 50.0` | `code/viewer/viewer_data.js:13`（`meta.metrics.split_L_pct/split_R_pct`） | 合成示例管腔的对称分流，仅演示 | 否，任何情况下不得当作患者分流 |

规则：

- `extract_compare.py` 的 `SPLIT_PROVENANCE` 就是上表三键（`label` + `source` + `semantics`），
  断言 `SPLIT_PROVENANCE 恰为三键`、`split_imposed_RunA 的 semantics 写明「非患者真实分流」`。
- `51.9 / 48.1` **只是** `split_natural_RunB` 的 1 位投影，不另立第四条读数。
  历史提交包里的 `51.9` 与本口径同源，**不是**独立证据。
- 输出载荷 `compare.split_provenance` 与每个 `compare.cases[*].split_caliber/split_semantics`
  并列写出上表语义句；控制台也会逐条打印三档语义。

---

## 2. 两档最小轴面积（min area）

唯一实现：`extract_compare.py::axial_area_minima()`；`extract_clinical.py` 直接 `import` 该函数，
**禁止写第二份**（GAP-2）。输入统一为 `code/pipeline/out/step1/area_per_slice_v2.csv`
（列：`slice,z_mm,total_mm2,left_mm2,right_mm2`，394 行，其中有面积 294 层）。

门限与 `code/pipeline/step1_airway_segment.py:402` 对齐：
`main_body = (areas > 0) & (areas >= max(areas) * 0.1)`。

| 字段 | 定义 | pA 实测值 | 固定标签 |
|---|---|---|---|
| `min_raw` | 门限内（`areas >= 0.1 * max(areas)` 且 `areas > 0`）的轴面最小值。**等价于现役产物字段 `min_axial_area_mm2`** | `244.208452856238 mm² @层273`（`z=-608.59 mm`；写成 6 位 = `244.208453`） | 「门限内轴面最小值，非解剖值；旧值 244.2 的来源 = `>=0.1×max_area`，`step1_airway_segment.py:402`」 |
| `min_no_threshold` | 去掉门限，对全部 `total_mm2 > 0` 层取最小值 | `2.933434869144 mm² @层294`（`z=-601.24 mm`；6 位 = `2.933435`） | 「未加区域约束，含边界毛刺，不可作解剖值」 |
| `min_anatomic` | 解剖学意义上的最小截面积 | **本阶段不产出（挂 T7）**，输出恒为 `null` + `min_anatomic_note` | 「本阶段不产出（挂 T7）」 |

纪律：

- 任何地方**不得**让 `min_raw` 冒充解剖值。载荷里 `valve_min_area_mm2`（244.2）
  与 `valve_min_area_two_tier.min_raw_mm2`（244.208453）都只是 `min_raw` 口径，
  故并列 `valve_min_area_semantics` 与两档标签。
- `min_raw` 与 `min_no_threshold` 相差两个数量级（断言 `> 1.0 mm²`），两者不得互相顶替。

---

## 3. ROOT 解析（三级）与 fail-soft

ROOT = 仓外母本根，即 `阶段1-三维重建/`、`阶段2-CFD算例包/` 等目录的上级。
侧车只登记**相对 ROOT 的路径**（如 `阶段1-三维重建/metrics_v2.json`），不写绝对路径。

三级解析（`split_validity.py::resolve_external_root`）：

1. `--root <路径>`（显式，最高优先）；
2. 环境变量 `P0_TOOL_ROOT`；
3. 仓库父目录（`os.path.dirname(REPO_ROOT)`），并打印 `[WARNING] ... 回退到仓库父目录：...`。

fail-soft 语义：

- 解析不出、目录不存在、母本文件缺失 → **不抛异常**，`--replica-check` 输出 `result: unknown`，退出码 0；
- 只有两侧文件都在、且 md5/字节数与期望不符时才输出 `result: divergent`，退出码 1；
- 比对过程**只读**，不创建目录、不写任何文件。

`--replica-check` 的期望值固定在侧车 `replica_check_policy` 里：

```
in_repo_ref      = code/pipeline/out/step1/metrics_v2.json
external_ref     = 阶段1-三维重建/metrics_v2.json      （相对 ROOT）
expected_md5     = c5759af68d72b5fc6274bc38016de93a
expected_bytes   = 668
evaluated_by     = python code/pipeline/split_validity.py --replica-check
note             = 结果现场计算，不入本文件，以保证字节可重放
```

---

## 4. 为什么侧车**不放** replica 比对结果

`docs/contracts/split-validity.json` 是发布门⑨「字节级重放」的对象：同一输入必须逐字节重现。
replica 比对结论（identical / divergent / unknown）取决于**本机是否存在仓外资产**：

- 干净克隆里 `code/pipeline/out/**` 被 `.gitignore` 屏蔽、仓外母本也不在 → 结论必然是 `unknown`；
- 若把本机结论写进侧车，同一份代码在「有仓外地」的机器上生成 `identical`、在干净克隆上生成
  `unknown`，字节不再可重放，`--check` 必红，发布门⑨ 直接破。

所以侧车只放**机器中立**字段：期望值 (`expected_md5` / `expected_bytes`)、算法入口
(`evaluated_by`)、语义说明 (`note`)。比对结论由 `--replica-check` **现场计算、只打印到 stdout**，
不入任何文件。侧车因此不含时间戳、不含盘符路径（测试已钉：无盘符、policy 无日期/时刻）。

---

## 5. 三态断言与退出码（extract_compare.py）

| 状态 | 含义 | 退出码影响 |
|---|---|---|
| `PASS` | 断言成立 | 不影响 |
| `SKIP` | **资产缺失**（仓内/仓外文件不在）——逐条登记，绝不静默通过、绝不伪造数值 | 有 SKIP 无 FAIL → 退出码 **0**，但**不写盘** |
| `FAIL` | 断言不成立 | 退出码 **1** |

末行固定打印：`[compare] 断言 n / 跳过 s / 失败 f`，并在其后注明处置：

- `· 存在失败，不写盘`
- `· 未写盘（存在 SKIP）`
- `· 未写盘（dry-run 默认；如需写盘加 --write）`
- `· 已写盘 2 份（--write）`

写盘策略：**默认 `--dry-run`**，只打印两个目标路径与将写出的字节数，不落盘；
仓外在用件只有在显式 `--write` 时才写（仓外 3.3 MB `viewer_plus_data.js` 的写入需单独授权）。
回读断言（七键齐 / md5 一致 / 两病例齐 / R·ΔP 对拍）仅在真正写盘后登记；
未写盘时打印「回读断言未登记（本轮未写盘，没有可回读的对象）」，不伪装成 SKIP。

`n` 的口径：本轮登记的全部断言条数（`n = PASS + SKIP + FAIL`）。
