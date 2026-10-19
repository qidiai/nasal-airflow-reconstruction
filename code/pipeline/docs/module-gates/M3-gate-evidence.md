# M3 门控证据包 — 切栈与 OpenFOAM 退役（BSL 核心纯洁化）

> **门控对象**：`edf7679`（M3 切栈主体）+ 本收尾批次（按纪律未提交，由指挥官统一提交）
> **生成**：2026-10-19 · 收尾编码手 deepseek-flash-ago-222（apigoto 通道）
> **权威来源**：`code/pipeline/docs/module-gates/看板-M3.md`（§6 未完成清单）、
> `code/solver/docs/equivalence-report.md`、`code/pipeline/docs/contracts/numerical-contract.md`、
> `code/pipeline/docs/contracts/validation-baselines.md`

## 0. 门控结论（TL;DR）

| 门控项 | 结论 | 关键证据 |
|---|---|---|
| 求解后端抽象落地 | **PASS** | `solver_backend.py` 新增；`run_all.py` / `server.py` 全链接入；`py_compile` + `import` 通过 |
| 默认行为与路由文档 | **PASS** | 根 `README.md` 新增「求解后端」一节；`legacy/openfoam-reference/README.md`；根 `NOTICE` |
| GPL 边界与声明 | **PASS** | 归档 10 文件 md5 10/10；`out/` 归档值经 `git check-ignore` 验证覆盖；`NOTICE` §2；`LICENSE` 指针 |
| 回归（custom vs 归档，±2%） | **PASS** | pA +1.632%；baseline27 case-001 / case-003 见 §4 |
| 静态与测试 | **PASS（1 项既有失败，域外）** | `pytest`：58 passed / 8 skipped / 1 failed；失败为 `webapp/index.html` 标题断言，与切栈无关 |
| 未决项 | 无阻塞 | 2 项明确移交/待裁决（见 §7） |

## 1. 交付物清单

| 路径 | 类型 | md5 | 说明 |
|---|---|---|---|
| `code/pipeline/solver_backend.py` | 新增 | `6f569e81494c92ef4e2d775562a8ec39` | 后端抽象：探测/路由/求解/结果目录适配/WSS 复算 |
| `code/pipeline/run_all.py` | 修改 | `9fe415c1739dd77c67c860d64ce0fa08` | `--backend` 参数；S5 按后端分派；Run-B 路由披露写 manifest |
| `code/pipeline/server.py` | 修改 | `5177783ac91968fb7466e0039b5d6d44` | `solve_thread` / `_full_chain_impl` / `/api/run`·`/api/solve`·`/api/full` 前置探测 |
| `code/pipeline/legacy/openfoam-reference/**` | 新增 | 见 `MD5SUMS.txt`（10/10） | OF 衍生模板 + `NOTICE`/`README`/`MANIFEST.json`/`MD5SUMS.txt` |
| `NOTICE`（根） | 新增 | `b4132724837cecd6c03d2e2b5a506649` | 分层许可；OF 衍生/运行时字典/归档值边界 |
| `LICENSE`（根） | 修改 | `76637ef40dde516b2ac7ce4569b08ebd` | 末尾追加 GPL 边界指针（BSL 条款未改） |
| `README.md`（根） | 修改 | `dcd0885b14d26f4e553e33160b34bebb` | 新增 `## 求解后端（M3 起）` 一节 |
| `.gitignore`（根） | 修改 | `26715259f2daa450c56444e6c0b44cd0` | M3 归档值边界注释（规则沿用 `**/out/`） |
| `code/pipeline/docs/module-gates/看板-M3.md` | 新增/更新 | — | 施工看板；§6 逐项收口 |
| `code/pipeline/docs/module-gates/M3-gate-evidence.md` | 新增 | — | 本文件 |

> md5 为 2026-10-19 收尾时工作副本值；`solver_backend.py` 等源码在本批次**未改**，
> 仅文档/声明类文件有增补。

## 2. 后端抽象与路由（实现核对）

### 2.1 后端解析

`solver_backend.resolve_backend(requested)` 的取值链：`requested`（非空时优先，
`run_all.py` 传 `--backend`，默认 `"auto"`）→ 环境变量 `FLOWSCOPE_BACKEND`
（`server.py` 以 `requested=None` 调用，因此生效）→ 默认 `auto`。

- `auto`：`flowscope[.exe]` 存在 → `custom`；否则 `openfoam`。
- `custom`：可执行文件缺失时报错（`exit 3`），不静默回退。
- `openfoam`：WSL `Allrun` → `simpleFoam` → `foamToVTK`，行为与 M3 前一致。

探测快照 `backend_status()` 写入 `run_all` manifest 的 `stages.S5_solve`，
便于审计复现（含 `requested` / `resolved` / 两侧可用性 / 阈值）。

### 2.2 Run-B 路由

`choose_run_b_backend(cells)`：`auto` 模式下 `cells <= RUNB_CUSTOM_MAX_CELLS`
（50,000）建议 `custom`，否则建议 `openfoam`（不可用时如实回退 custom 并标注风险）。
`run_all` 把该判定与阈值写入 manifest（`stages.S5_solve.run_b_routing`）并打印到日志。

**实现口径（收尾核对）**：当前流水线不自动发起 Run-B 求解（沿用交接/手工流程），
`run_all.py` 的 S5 只求解 Run-A 算例（`case_dir`），因此上述路由是**判据与披露**，
不是自动执行分支；手工/交接跑 Run-B 时应按该判据选择后端。

依据：`equivalence-report.md` §2.2 / `conditions-ledger` G-C3b——custom 的 Run-B
在 pA 满分辨率（269,913 cells）因鼻阀高 Péclet 速度峰失稳；pN-v6B（26,884 cells）
已收敛验证。

### 2.3 结果目录适配（行为不变性）

custom 产物被整理为既有契约形状，downstream 无感：

| 产物 | 来源 | 下游消费 |
|---|---|---|
| `VTK/<tag>/internal.vtu` | `fields_<iter>.vtk`（VTK_POLYHEDRON→hexahedron，cell U/p） | `meshio` / step5 |
| `后处理/metrics.json` | §11 stdout 指标 + VTU 复算 | 契约汇编 / webapp |
| `后处理/solver-contract.txt` | §11 指标段原文 | 审计逐字段核对 |
| `solver.log` | 求解器 stdout | 复现与心跳看护 |

## 3. 静态与接口验证

| 检查 | 命令 | 结果 |
|---|---|---|
| 语法编译 | `python -m py_compile pipeline/run_all.py pipeline/server.py pipeline/solver_backend.py` | PASS |
| 模块导入 | `import run_all, server, solver_backend` | PASS |
| 后端探测 | `solver_backend.backend_status()` | `resolved=custom`，`custom_available=True`，`runb_custom_max_cells=50000` |
| 测试套件 | `pytest tests -q`（仓库根） | 58 passed / 8 skipped / 1 failed（既有失败，见 §6） |

## 4. 回归数据（custom 后端 vs OpenFOAM 归档，容差 ±2%）

### 4.1 方法

- 入口：`solver_backend.run_custom()`——与 `run_all.py --backend custom`、
  `server.py` custom 分支同一函数，非旁路脚本。
- 参数：1500 步上限、`--p-reltol 1e-3`、写场间隔 500（pA）/ 1500（补充例）。
- 归档：pA `pipeline/out/结果/P0-result-pA-v1/后处理/metrics.json`；
  baseline27 `pipeline/out/baseline27/case-NNN/metrics.json`。
- 判定：`|ΔdP| ≤ 2%`（`validation-baselines.md` B1 口径）；U_max、分流、flux 闭合为辅证。

### 4.2 结果汇总

| 例 | cells | custom dP (Pa) | 归档 dP (Pa) | ΔdP | custom U_max | 归档 U_max | ΔU_max | flux 闭合 | 判定 |
|---|---|---|---|---|---|---|---|---|---|
| pA-v1 | 269,913 | 18.747088 | 18.445961 | **+1.632%** | 5.7465 | 5.7373 | +0.159% | 0.0093% | **PASS** |
| baseline27 case-003 | 38,844 | 1483.800332 | 1482.081899 | **+0.116%** | 43.0254 | 42.9663 | +0.138% | 0.024% | **PASS** |
| baseline27 case-001 | 53,747 | PENDING | 27.763233 | PENDING | PENDING | 5.3293 | PENDING | PENDING | PENDING |

参照（M2 已归档，M3 未重跑）：pB-v1 `44.62` vs `44.9067` → **−0.63%**（`solver/out/C1-pB-1500`）。

### 4.3 pA 细节（场与契约）

- 分流 L/R：39.00 : 61.00 vs 归档 39.001 : 60.999。
- 总流量：15.0000006 vs 15.0000157 L/min。
- `internal.vtu`：328,492 点 / 269,913 六面体单元，`cell_data["U"]` 形状 (269913, 3)，
  `meshio` 读回通过；bbox 34.96–123.06 / 20.98–119.57 / 0–102.9 mm。
- WSS（辅证）：mean 0.013172 vs 0.012973 Pa（+1.54%），p95 +0.61%；
  与 D-7 归档口径差（−5~−9%）方向一致，不参与门控判定。
- 收敛披露：末步 `residualControl` 未双达标（p 初残差 9.5e-2），1500 步硬停；
  与 M2 记录的 D-6（极限环幅度差）一致，dP 已稳定（500→1500 步波动 <1%）。

### 4.4 已知边界（不计入通过项）

- custom Run-B 在 pA 满分辨率网格发散（六种方案均失败，见 `equivalence-report.md` §2.2）；
  因此 Run-B 大网格保持 `openfoam` 路由，OpenFOAM 后端不删除。

## 5. 许可与数据边界

| 检查 | 结果 |
|---|---|
| 归档 OF 文件完整性 | `MD5SUMS.txt` 逐文件复算 **10/10 match** |
| `out/` 归档值是否入库 | `git check-ignore -v` 命中 `**/out/`（metrics.json / controlDict / baseline27 三路径抽样） |
| 仓库已跟踪 OF 模板 | `git ls-files` 零命中（`Allrun/controlDict/...`） |
| 声明落地 | 根 `NOTICE` §2（GPL-3.0，非 BSL 核心，不随核心分发）；`LICENSE` 末尾指针；`legacy/.../NOTICE` |
| 运行时可执行 | OpenFOAM 本体未分发，用户自装（GPL-3.0） |

## 6. 测试结论

- 全量：**58 passed / 8 skipped / 1 failed**。
- 唯一失败 `tests/test_api.py::TestAPIContract::test_index_page`：
  断言 `"P0 鼻腔气流分析工作台"`，`code/pipeline/webapp/index.html` 的
  `<title>` 为 `"鼻腔气流分析工作台"`。
- 定案：`edf7679` 未触碰 `webapp/` 与 `tests/`（该提交 stat 可查），本批次同样未改；
  失败为**既有、域外**，登记不改，不阻塞 M3 门控。

## 7. 未决项与移交

| # | 项 | 处置 | 责任方 |
|---|---|---|---|
| 1 | `step2_make_ofcase.py` 生成侧是否给 OF 字典加 GPL 头注释 | 不在 M3 文件域；当前以「`out/` 不入库 + NOTICE 声明」处理 | 指挥官 / 法务 |
| 2 | 真实 webapp 端到端（上传→求解→查看器） | M3 只验证适配产物可被 `meshio`/契约消费；交互链路移交 | M4 |
| 3 | D-1（Poiseuille Δp/dx 22%）、D-6（残差平台）、D-7（WSS 口径差） | M2 已登记，M3 不扩大范围 | 后续数值轮次 |
| 4 | OpenFOAM 后端 L3 22/22 | M3 未删除该后端，M2 结论继续有效；不重跑 | 维持 |

## 8. 复跑命令

```powershell
# 后端探测
cd code; ..\.venv\Scripts\python.exe -c "import sys;sys.path.insert(0,'pipeline');import solver_backend as SB;print(SB.backend_status())"

# pA 回归（custom，1500 步）
..\.venv\Scripts\python.exe -c "import sys;sys.path.insert(0,'pipeline');import solver_backend as SB;print(SB.run_custom(r'pipeline\out\step2\P0-OF-case-pA-v1', r'solver\out\M3-reg-pA', max_iter=1500))"

# baseline27 抽例（case-001 / case-003，两例并发）
..\.venv\Scripts\python.exe solver\out\M3-reg-driver.py

# 一键管线（默认 auto）
python pipeline\run_all.py --dicom-dir <CT目录> --solve local
```

## 9. 证据索引

| 证据 | 路径 |
|---|---|
| pA 回归 metrics / 契约原文 / 日志 | `code/solver/out/M3-reg-pA/` |
| pA 对比结论 JSON | `code/solver/out/M3-reg-pA-compare.json` |
| baseline27 抽例 metrics / 日志 | `code/solver/out/M3-reg-baseline27-*/` |
| 回归汇总 JSON | `code/solver/out/M3-reg-summary.json` |
| 后端抽象单测/探测 | `code/pipeline/solver_backend.py`；`backend_status()` 输出 |
| GPL 归档证据 | `code/pipeline/legacy/openfoam-reference/{MANIFEST.json,MD5SUMS.txt,NOTICE}` |
| 施工看板 | `code/pipeline/docs/module-gates/看板-M3.md` |
