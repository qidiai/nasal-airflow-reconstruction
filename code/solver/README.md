# FlowScope 自研 FVM 求解器（M2 · Rust 清洁室）

自研有限体积求解器，逐字段复刻 `pipeline/docs/contracts/numerical-contract.md`（v1.0）
钉住的 OpenFOAM v2406 `simpleFoam` 配置（laminar / steady / incompressible），
用于替代 OpenFOAM 成为 FlowScope 鼻腔气流分析工具的核心自研资产。

## 构建

```powershell
cargo build --release          # 产物：target/release/flowscope.exe
```

零第三方依赖（纯标准库），清洁室可审计。

## 运行

```powershell
# 网格核对（checkMesh 口径：单元/面/patch 计数 + 几何体检）
flowscope check-mesh <caseDir>

# 算例配置加载与契约核对（constant/ + system/ + 0/）
flowscope case-info <caseDir>

# SIMPLE 求解（W2/W3 起）
flowscope run <caseDir> [--max-iter N] [--out DIR]

# 解析验证（W4 硬门：Poiseuille 管流）
flowscope poiseuille [--nx N --ny N --nz N]
```

归档算例路径示例（`pipeline/out/step2/`）：
`P0-OF-case-pA-v1`（Run-A 定流量）、`P0-OF-case-pB-v1`（Run-A）、
`P0-OF-case-pA-v1B`（Run-B 等压，M2 首跑自建归档）。

## 清洁室纪律

- 文献基线：Patankar & Spalding（SIMPLE）、Rhie & Chow 1983、Versteeg & Malalasekera
  （FVM）、Ferziger & Peric、Golub & Van Loan（Krylov 迭代法）。
- **不读任何 OpenFOAM 实现源码**；复刻对象唯一 = `numerical-contract.md`。
- 每个模块顶部有 provenance 注释。

## 验证门

- W4 硬门：Poiseuille 中心速度误差 <1%、ΔP 误差 <2%（`docs/poiseuille-gate.md`）。
- W5 对拍：L1 dP（±2%）/ L2 速度场相关 >0.98 / L3 baseline27 批量（`docs/equivalence-report.md`）。

## 状态

见 `看板-M2.md`（每周更新：W1-W5 状态 + 证据 + 失败项如实清单）。
