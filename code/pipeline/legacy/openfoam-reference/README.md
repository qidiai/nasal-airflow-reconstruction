# legacy/openfoam-reference — 求解后端默认行为与 Run-B 路由

> M3 切栈（2026-10-19）后，流水线默认求解后端 = 自研 FlowScope；
> 本目录只保存 OpenFOAM 衍生参考文件（GPL-3.0，见 `NOTICE`）。

## 1. 后端选择（`code/pipeline/solver_backend.py`）

| `--backend` / `FLOWSCOPE_BACKEND` | 行为 |
|---|---|
| `auto`（**默认**） | `code/solver/target/release/flowscope[.exe]` 存在且可用 → **custom**；否则回退 **openfoam** |
| `custom` | 自研 FlowScope；可执行文件缺失时**报错**（不静默回退） |
| `openfoam` | WSL `Allrun` → `simpleFoam` → `foamToVTK`（保留为对拍基准，**不删除**） |

`run_all.py --solve local` 与 `server.py` 的 `/api/run`、`/api/solve`、
`/api/full` 均走同一解析函数。custom 适配层把
`fields_<iter>.vtk` + §11 指标整理为既有结果目录契约
（`VTK/<case>_<iter>/internal.vtu` + `后处理/metrics.json`），
因此契约汇编 / `step5` / webapp 消费路径不变。

环境变量：`FLOWSCOPE_BIN` 可覆盖可执行文件路径；
`FLOWSCOPE_BACKEND` 等价于 `--backend`。

## 2. Run-B 路由（已知边界，必须保留）

- **Run-A（定流量）**：custom 优先。L1 对拍 pA dP +1.61%、pB −0.63%，均在 ±2% 内。
- **Run-B（等压）**：按网格规模路由——
  - `cells <= 50,000` → custom（pN-v6B 26,884 cells 已验证通过）；
  - `cells > 50,000` → openfoam（若可用；否则如实回退 custom 并标注风险）。
- **已知失稳边界**：custom Run-B 在 pA 满分辨率网格（269,913 cells）上发散——
  鼻阀高 Péclet 速度峰经 HbyA→压力→速度指数放大，斜坡/强松弛/一阶迎风/clamp/
  potential 初场等六种方案均不能阻止（机制表征见
  `code/solver/docs/equivalence-report.md` §2.2 与 `conditions-ledger` G-C3b）。
  因此 **OpenFOAM 后端保留不删**：它是 Run-B 大网格与 L3 回归的对拍真值源。
- 用户显式 `--backend custom` 时仍按 custom 尝试 Run-B；失败如实上报，不调参凑数。

## 3. 文件清单

- `P0-OF-case-pA-v1/`：Run-A 模板（定流量入口）
- `P0-OF-case-pA-v1B/`：Run-B 模板（入口 fixedValue 80）
- `MANIFEST.json` / `MD5SUMS.txt`：复制前后 md5 对照（10/10 一致）

这些文件**仅作参考**；运行时算例由 `step2_make_ofcase.py` 在 `out/` 下生成，
`out/` 被 `.gitignore` 排除，不进入公开发布面。
