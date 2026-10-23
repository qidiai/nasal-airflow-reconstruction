# contract-pA-v1 溯源与降级标注（provenance-pA-v1）

> 依据：执行官 **裁定（四）D-3**（2026-10-23）。
> 性质：**标注文件**。在用件 `code/pipeline/out/postprocess/contract-pA-v1.json` **一字未改**
> （本轮前后 md5 均为 `a0b3ec4806920da6bcfe61004321f9e1`，核验命令见 §5）。

## 1. dP_baseline_Pa = 18.45 的上游与物性

| 项 | 值 | 出处（可复核） |
|---|---|---|
| 契约值 | `dP_baseline_Pa = 18.45` | `code/pipeline/out/postprocess/contract-pA-v1.json`（在用件，未改） |
| 上游文件 | `阶段2-CFD算例包/结果/P0-result-pA-v5/后处理/metrics.json`（仓外） | `code/pipeline/medical_extract/extract_compare.py:77`（`PA_V5`） |
| 上游 md5 | `9a49276eed10bbef6a9210e3182ab854` | 实测（可复现）：`cd code/pipeline/medical_extract && python -c "import hashlib,extract_compare as e;print(hashlib.md5(open(e.PA_V5,'rb').read()).hexdigest())"` → 该值；同一值钉在 `extract_compare.py:163`（`MD5_V5`） |
| 上游 `totals.dP_Pa` | `18.445960544586182` | 上述 metrics.json `totals` 直读 |
| 上游 `inputs.nu_m2_s` | `1.48e-05` | 上述 metrics.json `inputs` 直读 |
| 上游 `inputs.mu_Pa_s` | `1.776e-05` | 同上（= rho 1.2 × nu 1.48e-5，自洽） |
| 现役物性 `nu` | `1.80e-05` | ① `code/solver/src/lib.rs:35` `pub const NU_AIRWAY: f64 = 1.800e-05;` ② `code/pipeline/out/step2/P0-OF-case-pA-v1/constant/transportProperties:14` `nu [0 2 -1 0 0 0 0] 1.800e-05;` ③ 三份 pA `solver.log` 首行均含 `nu 1.8000e-5`：`code/solver/out/M3-reg-pA/solver.log:1`、`code/solver/out/W6v3-L1-pA/solver.log:1`、`code/solver/out/W8-L1-pA/solver.log:1` |

**结论（2026-10-23 08:5x 收紧）：该契约值为历史运行产物；其物理输入 `nu` 目前在同一次运行的两个在册件里互相矛盾（见 §1.2），因此"与现役不可互证"只是**候选结论**，尚未证。**
> 措辞规矩：在 §1.2 的矛盾被判定之前，**不得**在任何对外/内部文档写"上游用了 `nu=1.48e-5`"这一断言——只能写"`nu` 身份未定（两个在册读数冲突）"。
> 理由：`inputs.nu_m2_s = 1.48e-05` 是后处理写进去的**声明**，而求解器真正读的是 case 的 `constant/transportProperties`（那里写 `1.800e-05`）。**声明不等于输入**；把声明当输入，就是我们一直在防的那类错。

### 1.1 观察（原样登记，未裁定）

仓外 pA-v5 算例自身的 `constant/transportProperties:14` 写的是
`nu [0 2 -1 0 0 0 0] 1.800e-05;`（文件 md5 `58c2e8e340c5702493b11033c08b37c0`），与**同一算例**后处理
`metrics.json` 的 `inputs.nu_m2_s = 1.48e-05` 不一致。两处各自原样登记；"哪一处才是该次求解的 physical input"
不在 D-3 授权内，本文件不作推断。

## 2. 事实登记：baseline27 归档内没有 "OF 归档 18.45"

- **已复核**（本轮独立执行，非引用他文）。命令（在仓库根执行）：

```
python -c "
import io,json,glob,os
rows=[]
for d in sorted(glob.glob('code/pipeline/out/baseline27/case-*')):
    m=json.loads(io.open(os.path.join(d,'metrics.json'),encoding='utf-8-sig').read())
    tot=m.get('totals',m)
    rows.append((os.path.basename(d), tot.get('dP_Pa'), m.get('case_id'), m.get('status')))
print('N=',len(rows))
print('pA-like:',[r for r in rows if r[2] and 'pA' in str(r[2])])
print('dP in (15,25):',[r for r in rows if isinstance(r[1],(int,float)) and 15<r[1]<25])
print('OK=',len([r for r in rows if r[3]=='OK']),'DIVERGED=',len([r for r in rows if r[3]=='DIVERGED']))
"
```

  输出原文末四行：`N= 27`、`pA-like: []`、`dP in (15,25): []`、`OK= 22 DIVERGED= 5`（末行与
  `code/pipeline/docs/module-gates/conditions-ledger.md:63`「22 成功/5 发散」一致）。
  27 例逐条为 `case-001 … case-027`；`case_id` 字段全为 `None`，故"无 pA"以**目录命名**与
  `provenance.json` 交叉核验为准（读 `case` / `of_case` / `label` 三字段，输出
  `count 27`、`any pA/demoA in fields: []`）；
  与区间最近的两侧值为 `case-014 = 8.193655712573559 Pa`、`case-026 = 8.30261877188042 Pa`
  （均 < 15）与 `case-001 = 27.76323254252589 Pa`（> 25）。

- **结论**：baseline27 的 27 例归档中**无 pA、且无 dP∈(15,25) 者** ⇒ 在 baseline27 归档范围内，
  "OF 归档 18.45" **无归档产物**。18.45 的唯一物证是仓外 `P0-result-pA-v5/后处理/metrics.json`
  （md5 见 §1），它不在 baseline27 内。

## 3. 新门（执行官拟加）

> **任何 dP / 阻力 / 流量口径必须写 `nu`、温度或等效物性；跨物性禁止并列。**

落地判据（建议写法）：

1. 任一 dP / R=ΔP/Q / 分流 / 流量数字，落盘或成文时必须带 `nu`（或温度 T / μ 等等效物性）；
2. 并列（同表、同段、求差、算比值、作 "vs 基线" 结论）前先断言两侧 `nu` 相等（逐位或显式容差）；
3. `nu` 不等 ⇒ 只允许作"跨物性差"单列，**禁止**并列互证，禁止以一方判另一方 PASS/FAIL；
4. 契约/归档件缺 `nu` ⇒ 视作 `unknown`，不得参与并列。

## 4. 待生成 contract-pA-v2 的要求（仅规格；本文件不生成、不跑求解）

### 4.1 物性统一

- `nu = 1.80e-05 m²/s`、`rho = 1.2 kg/m³`、`mu = 2.16e-05 Pa·s`（出处 `code/solver/src/lib.rs:35-38`）；
- 与 case `constant/transportProperties` 的 `nu` 逐位一致；不一致即失败，不得静默取一侧；
- 温度等效物性须写一句（项目内既有表述：气道内空气 ~35 °C，见
  `项目/…/多患者管线验证/交接文档-笔记本执行-pC-*.md` 的"求解器设置"行）；
- **禁止**把 §1 的 1.48e-5 历史值与 1.80e-5 并列，或折算成同一基线后比较。

### 4.2 四要素必填（缺一即不合规）

| 要素 | 含义 | 取法 |
|---|---|---|
| `exe_md5` | 求解器可执行文件 md5 | `md5sum target/release/flowscope.exe`（Windows 可用 python `hashlib`） |
| `commit` | 产出该结果的仓库 commit | `git rev-parse HEAD`（只读） |
| `iter` | 实际迭代数 + `stop_reason` | `solver.log` §11 收官段 / `后处理/solver-contract.txt`（如 `iterations : 1500`、`stop reason : …`） |
| `nu` | 该次运行的 nu | 日志首行 `nu 1.8000e-5` 与 case `transportProperties` 双向对齐 |

### 4.3 早停

- 判据：`residualControl` p/U 双达标即停；必须记录 `stop_reason`（形如
  `SIMPLE solution converged：iter N …`）与 `iter`。
- 预期时长 **约 35 min** —— **出处状态：推算值，非台账实测**。本轮在仓内检索
  `grep -rn -e "35 min" -e "35分钟" -e "35 分钟" -e "2100s" --include=*.md code docs`
  （排除本文件自身）**0 命中**；`项目/` 同法 **0 命中**；即无直接台账实测可引。可复核的实测与推算如下：
  - 实测摊销：`code/solver/out/W8-L1-pA/solver.log` 末行 `（求解耗时 12540.5s）`、
    `后处理/solver-contract.txt` 的 `iterations : 1500` ⇒ `12540.5 / 1500 = 8.36 s/步`；
  - 实测早停实例：`code/solver/out/W8-L3-026/solver.log` ⇒ `iterations : 195`、`（求解耗时 503.7s）`；
  - 推算：`12540.5 × 250 / 1500 ≈ 2090 s ≈ 34.8 min`（≈ 早停 250 步），与"约 35 min"同量级；
  - **标注**：35 min 系按上述实测摊销推算；正式契约落地前须补台账实测出处，否则不得写成"实测 35 min"。

### 4.4 并存与不覆盖

- `contract-pA-v2.json` 与 `contract-pA-v1.json` **并存**；v1 保持只读，不覆盖、不改写；
- v2 内嵌 provenance 块，至少含：上游 metrics md5 + §4.2 四要素。

## 5. 未改动声明（在用件与网格目录）

本轮未写入任何在用产物（`code/pipeline/out/**`、`code/solver/out/**`）。关键件 md5 改前 = 改后：

| 文件 | md5（改前 = 改后） |
|---|---|
| `code/pipeline/out/postprocess/contract-pA-v1.json` | `a0b3ec4806920da6bcfe61004321f9e1` |
| `code/pipeline/out/step1/metrics_v2.json` | `c5759af68d72b5fc6274bc38016de93a` |
| `code/pipeline/out/step1/area_per_slice_v2.csv` | `1aec3fba54b263a8bbcce45fed73e421` |
| `code/viewer/viewer_data.js` | `ba54073c5d63f3d9fad84ffadac70624` |

核验命令：`md5sum` 上述四件（改前、改后各一次，输出逐字节相同）。
