# 数值契约 v1.0 —— 自研求解器复刻 OpenFOAM 配置全量规格（M1 轨 A 交付）

> **定位**：本文档是 M2（自研求解器）的**直接输入**。自研求解器必须逐字段复刻本文档钉住的 OpenFOAM 配置；凡本文档未覆盖的行为，以归档实证文件为唯一裁决源。
> **上游**：规划 v2.3.2 §3/#2（Run-A/Run-B 双口径漏吸收）、#3（L1 基线取值标准）、#4（指标去同义反复）、§4 验证门控表、§5 清洁室规程。
> **纪律**：每个字段附**实证文件路径 + md5**（2026-10-17 实测）；契约冻结后任何变更走 G2 迷你审计门（至少一位审计官）。
> **引用忠实性**：本文所有 ``` 代码块均由归档实证文件**原文直接注入生成**（非手工转抄），生成时逐块断言"块文本 ∈ 归档文件文本"；自验脚本 `G:\qidicode\target\tmp\M1\trackA\selfcheck.py` 可复跑复核。
> **归档根**：`F:\比赛项目\罕见无界黑客松\开源仓库\code\pipeline\out\`（下称 `out/`）。求解器基准 = OpenFOAM v2406 `simpleFoam`，laminar / steady / incompressible。

---

## 1. 实证文件清单（契约的事实基础）

| # | 实证文件（相对 `out/`） | md5（2026-10-17） | 钉住的内容 |
|---|---|---|---|
| E1 | `step2/P0-OF-case-pA-v1B/system/fvSolution` | `e8b426a7f3c409d649647fc908867d12` | 线性求解器、SIMPLE 残差控制、松弛因子 |
| E2 | `step2/P0-OF-case-pA-v1B/system/fvSchemes` | `554fb551af3732630d8a1090c9ffdfa9` | 全部离散格式 |
| E3 | `step2/P0-OF-case-pA-v1B/system/controlDict` | `81657ade0175b03224004a8c3c6265da` | 应用、迭代步数、写出控制、函数对象 |
| E4 | `step2/P0-OF-case-pA-v1/0/U` | `d9f986d54b596b78b0ce503e3e980ebb` | Run-A 定流量入口 BC（pA 流量值） |
| E5 | `step2/P0-OF-case-pA-v1/0/p` | `01c968ff17074d6da7b92098187ee327` | Run-A 压力 BC（pB 的 `0/p` 与本文件 md5 逐字节相同） |
| E6 | `step2/P0-OF-case-pB-v1/0/U` | `ce817cd962f8af6cc28c1f9d014520d1` | Run-A 定流量入口 BC（pB 流量值） |
| E7 | `step2/P0-OF-case-pA-v1B/0/U` | `e9a2f792fbf7d943e86472581d02671e` | Run-B 等压速度 BC |
| E8 | `step2/P0-OF-case-pA-v1B/0/p` | `5680a82c4478f9866c000eef122225cc` | Run-B 等压压力 BC（inletL/R fixedValue 80） |
| E9 | `step2/P0-OF-case-pA-v1B/Allrun` | `c4505791109c7668b95ee87fbde7f626` | 求解流程（checkMesh → simpleFoam → foamToVTK） |
| E10 | `step2/P0-OF-case-pA-v1B/constant/transportProperties` | `58c2e8e340c5702493b11033c08b37c0` | nu = 1.800e-05 m²/s，Newtonian |
| E11 | `step2/P0-OF-case-pA-v1B/constant/turbulenceProperties` | `8e296953c7a06bded5b4980c7e24efac` | laminar |
| E12 | `step2/P0-OF-case-pA-v1B/constant/polyMesh/boundary` | `e150572600d0ebeacf6274bbff2ad379` | 四 patch 定义（inletL/inletR/outlet/walls） |
| E13 | `step2/case_stats-v1.json` | `b3d3eb26c0971a7511a11618b12382df` | pA 网格/流量/设计注记/发布门 |
| E14 | `step2/case_stats-pB-v1.json` | `b77ff33a57c1c0d24a66584bbcfbcf25` | pB 网格/流量/Run-A+Run-B 注记 |
| E15 | `结果/P0-result-pA-v1/log.simpleFoam` | `a94b3d4ff1b5acffef287a3accfbd3c4` | 运行期实证：收敛判据回显、末步残差、通量写出 |
| E16 | `结果/P0-result-pA-v1/log.checkMesh` | `508be063ec87d08befc0ea04bf23c52d` | Mesh OK、cells=269913、域包围盒 |
| E17 | `结果/P0-result-pA-v1/allrun.log` | `1449efff2ea68c9b26410f55435e2636` | ExecutionTime = 1437.68 s（末行） |
| E18 | \结果/P0-result-pA-v1/后处理/metrics.json\ | 9f7ee36caab14d6943f971ecc06c837\ | pA 后处理全量指标（dP/split/WSS） |
| E19 | `结果/P0-result-pB-v1/后处理/metrics.json` | `c0bbb99f13dbb6d74628ad2799698dc5` | pB 后处理全量指标（**D1 基线载体**） |
| E20 | `结果/P0-result-pB-v1/后处理/report.md` | `96560f0b97835526092fcbd6b392b2fa` | pB 后处理口径与公式说明 |
| E21 | `postprocess/contract-pA-v1.json` | `a0b3ec4806920da6bcfe61004321f9e1` | pA 契约取值（L1 门） |
| E22 | `postprocess/contract-pB-v1.json` | `6ea9676722c3e70573eb2982484f611d` | pB 契约取值（L1 门） |

**一致性备注**：`结果/P0-result-pA-v1/system/{fvSolution,fvSchemes,controlDict}` 与 `0/{U,p}` 同 E1–E5 **md5 逐字节相同**——归档运行所用的就是 `step2/P0-OF-case-pA-v1`（Run-A）这套配置；`P0-OF-case-pA-v1` 与 `P0-OF-case-pA-v1B`（Run-B）的 `system/` 三个字典亦互相同（md5 均为 E1/E2/E3）——**Run-A 与 Run-B 共享同一套数值配置，差别只在 `0/` 边界条件**。

---

## 2. 网格与算例（复刻的几何输入）

实证：E12（patch 定义）、E13/E14（case_stats）、E16（checkMesh 日志）。

| 项 | pA（P0-OF-case-pA-v1 / -v1B） | pB（P0-OF-case-pB-v1 / -v1B） |
|---|---|---|
| cells | 269,913 | 203,387 |
| internal faces | 752,129 | 556,076 |
| patch 面数 | inletL 195 / inletR 305 / outlet 536 / walls 114,184 | inletL 56 / inletR 62 / outlet 236 / walls 107,816 |
| 体素 (mm) | 0.699 × 0.699 × 0.7 | 0.936 × 0.936 × 0.6 |
| 体积回归比 | 1.026 | 1.037 |
| 域包围盒 (m) | (0.0349609, 0.0209765, 0) – (0.123062, 0.119566, 0.1029)（E16） | — |
| checkMesh | **Mesh OK**（E16） | — |

- patch 类型（E12）：inletL/inletR/outlet = `patch`，walls = `wall`（审计 G1：壁面必须 wall 类型）。
- 出口定义 = 掩码最下层平面（鼻咽截断）；inletL/R = 鼻孔自然开口（鼻中隔 x 间隙分组）（E13 `design` 字段）。
- Run-A/Run-B **共用同一 polyMesh**（v1 与 v1B 的 polyMesh 文件同尺寸；两例差别仅 `0/` 目录，见 §7/§8）。

---

## 3. 物性与湍流模型（constant/）

实证：E10、E11（以下为原文，自 `transportModel` / `simulationType` 行起）：

```
transportModel  Newtonian;

nu              [0 2 -1 0 0 0 0] 1.800e-05;

// ************************************************************************* //


simulationType  laminar;

// ************************************************************************* //
```

**契约字段**：`transportModel = Newtonian`；`nu = 1.800e-05 m²/s`（气道温度口径，审计 Y2）；`simulationType = laminar`（Stokes 应力模型，无湍流模型）；据此后处理口径 `rho = 1.2 kg/m³`、`mu = rho*nu = 2.16e-05 Pa·s`（OpenFOAM 运动学压力求解不显式使用 rho，见 §11）。

---

## 4. fvSolution（逐字段契约）

实证：E1（以下为原文，自 `solvers` 起）；运行期回显实证：E15（`SIMPLE: convergence criteria` / `field p` <tab> `tolerance 0.0001` / `field U` <tab> `tolerance 0.0001`）。

```
solvers
{
    p
    {
        solver          GAMG;
        tolerance       1e-06;
        relTol          0.05;
        smoother        GaussSeidel;
    }
    U
    {
        solver          smoothSolver;
        smoother        GaussSeidel;
        tolerance       1e-05;
        relTol          0.01;
    }
}

SIMPLE
{
    nNonOrthogonalCorrectors 0;
    residualControl
    {
        p               1e-4;
        U               1e-4;
    }
}

relaxationFactors
{
    fields
    {
        p               0.3;
    }
    equations
    {
        U               0.7;
    }
}

cache
{
    grad(U);
}

// ************************************************************************* //
```

| 字段 | 契约值 | 说明 |
|---|---|---|
| `solvers.p.solver` | **GAMG** | 压力用代数多重网格 |
| `solvers.p.tolerance` | **1e-06** | |
| `solvers.p.relTol` | **0.05** | |
| `solvers.p.smoother` | **GaussSeidel** | |
| `solvers.U.solver` | **smoothSolver** | 速度用平滑求解器 |
| `solvers.U.smoother` | **GaussSeidel** | |
| `solvers.U.tolerance` | **1e-05** | |
| `solvers.U.relTol` | **0.01** | |
| `SIMPLE.nNonOrthogonalCorrectors` | **0** | |
| `SIMPLE.residualControl.p` | **1e-4** | 不是 1e-5 |
| `SIMPLE.residualControl.U` | **1e-4** | 不是 1e-5；p/U 双口径均为 1e-4（任务书红线） |
| `relaxationFactors.fields.p` | **0.3** | 欠松弛（笔记本病根①修复） |
| `relaxationFactors.equations.U` | **0.7** | |
| `cache.grad(U)` | **开** | 缓存 grad(U) 供 div(phi,U) 的 linearUpwind 复用 |

---

## 5. fvSchemes（逐字段契约）

实证：E2（以下为原文，自 `ddtSchemes` 起）：

```
ddtSchemes
{
    default         steadyState;
}
gradSchemes
{
    default         Gauss linear;
}
divSchemes
{
    default         none;
    div(phi,U)      bounded Gauss linearUpwind grad(U);
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}
laplacianSchemes
{
    default         Gauss linear corrected;
}
snGradSchemes
{
    default         corrected;
}
interpolationSchemes
{
    default         linear;
}

// ************************************************************************* //
```

| 字段 | 契约值 | 说明 |
|---|---|---|
| `ddtSchemes.default` | **steadyState** | 稳态 |
| `gradSchemes.default` | **Gauss linear** | |
| `divSchemes.default` | **none** | |
| `div(phi,U)` | **bounded Gauss linearUpwind grad(U)** | 必须带 `bounded`（M2 红线） |
| `div((nuEff*dev2(T(grad(U)))))` | **Gauss linear** | 层流下 nuEff=nu |
| `laplacianSchemes.default` | **Gauss linear corrected** | |
| `snGradSchemes.default` | **corrected** | |
| `interpolationSchemes.default` | **linear** | |

---

## 6. controlDict（逐字段契约）

实证：E3（以下为原文，自 `application` 行起，含 functions 全块）：

```
application     simpleFoam;

startFrom       latestTime;
startTime       0;
stopAt          endTime;
endTime         1500;
deltaT          1;

writeControl    timeStep;
writeInterval   500;
purgeWrite      2;
writeFormat     ascii;
writePrecision  6;
timeFormat      general;
timePrecision   6;
graphFormat     raw;

functions
{
    fluxInletL
    {
        type            surfaceFieldValue;
        libs            ("libfieldFunctionObjects.so");
        fields          (phi);
        operation       sum;
        regionType      patch;
        name            inletL;
        writeControl    writeTime;
        writeFields      false;
    }
    fluxInletR
    {
        type            surfaceFieldValue;
        libs            ("libfieldFunctionObjects.so");
        fields          (phi);
        operation       sum;
        regionType      patch;
        name            inletR;
        writeControl    writeTime;
        writeFields      false;
    }
    fluxOutlet
    {
        type            surfaceFieldValue;
        libs            ("libfieldFunctionObjects.so");
        fields          (phi);
        operation       sum;
        regionType      patch;
        name            outlet;
        writeControl    writeTime;
        writeFields      false;
    }
    wss
    {
        type            wallShearStress;
        libs            ("libfieldFunctionObjects.so");
        writeControl    writeTime;
    }
}

// ************************************************************************* //
```

| 字段 | 契约值 |
|---|---|
| `application` | **simpleFoam** |
| `startFrom` / `startTime` | latestTime / 0 |
| `stopAt` / `endTime` | endTime / **1500**（稳态迭代上限） |
| `deltaT` | 1 |
| `writeControl` / `writeInterval` / `purgeWrite` | timeStep / **500** / 2 |
| `writeFormat` / `writePrecision` | ascii / 6 |
| `timeFormat` / `timePrecision` | general / 6 |
| `graphFormat` | raw |
| 函数对象 | fluxInletL/fluxInletR/fluxOutlet（surfaceFieldValue，phi 求和，writeTime）+ wss（wallShearStress，writeTime） |

---

## 7. Run-A 定流量口径（边界条件全量）

实证：E4（pA `0/U`，原文自 `dimensions` 起）、E5（`0/p`，pA/pB 逐字节相同）、E6（pB `0/U`，仅流量值不同：inletL `1.170260e-04`、inletR `1.329740e-04`）。

**pA `0/U`（E4 原文）**：

```
dimensions      [0 1 -1 0 0 0 0];

internalField   uniform (0 0 0);

boundaryField
{
    inletL
    {
        type            flowRateInletVelocity;
        volumetricFlowRate 9.750341e-05;
        value           uniform (0 0 0);
    }
    inletR
    {
        type            flowRateInletVelocity;
        volumetricFlowRate 1.524966e-04;
        value           uniform (0 0 0);
    }
    outlet
    {
        type            zeroGradient;
    }
    walls
    {
        type            fixedValue;
        value           uniform (0 0 0);
    }
}

// ************************************************************************* //
```

**`0/p`（E5 原文，pA/pB 相同）**：

```
dimensions      [0 2 -2 0 0 0 0];

internalField   uniform 0;

boundaryField
{
    inletL    { type            zeroGradient; }
    inletR    { type            zeroGradient; }
    outlet    { type            fixedValue; value uniform 0; }
    walls     { type            zeroGradient; }
}

// ************************************************************************* //
```

| 字段 | Run-A 契约值 |
|---|---|
| U inletL/inletR | **flowRateInletVelocity**，pA = 9.750341e-05 / 1.524966e-04 m³/s；pB = 1.170260e-04 / 1.329740e-04 m³/s（两侧合计恒 2.5e-4 m³/s = **15.0 L/min**） |
| U outlet | zeroGradient |
| U walls | fixedValue uniform (0 0 0)（无滑移） |
| p inletL/inletR | zeroGradient |
| p outlet | **fixedValue uniform 0**（运动学压力参考零点） |
| p walls | zeroGradient |

**同义反复注记（规划 #4 / GLM F-06）**：Run-A 的分流比由 BC 输入逐位决定（pA：9.750341e-05 : 1.524966e-04 = **39.0 : 61.0**；pB：1.170260e-04 : 1.329740e-04 = **46.8 : 53.2**）——流量按面积分配是**建模假设**（E13 `runA_note`：审计 R2），因此**定流量分流比不作 L1 验收指标**（见 validation-baselines.md §3）。E15 末步 flux 写出（`sum(inletL) of phi = -9.75034e-05`、`sum(inletR) of phi = -0.000152497`）即 BC 值的执行实证。

---

## 8. Run-B 等压口径（边界条件全量）

实证：E7（`0/U`）、E8（`0/p`）、E14（`runB_note`）。以下均为原文（自 `dimensions` 起）。

**`0/p`（E8 原文）**：

```
dimensions      [0 2 -2 0 0 0 0];

internalField   uniform 0;

boundaryField
{
    inletL    { type fixedValue; value uniform 80; }
    inletR    { type fixedValue; value uniform 80; }
    outlet    { type fixedValue; value uniform 0; }
    walls     { type zeroGradient; }
}

// ************************************************************************* //
```

**`0/U`（E7 原文）**：

```
dimensions      [0 1 -1 0 0 0 0];

internalField   uniform (0 0 0);

boundaryField
{
    inletL    { type zeroGradient; }
    inletR    { type zeroGradient; }
    outlet    { type zeroGradient; }
    walls     { type fixedValue; value uniform (0 0 0); }
}

// ************************************************************************* //
```

| 字段 | Run-B 契约值 |
|---|---|
| p inletL/inletR | **fixedValue uniform 80**（运动学压力，m²/s²；×rho=1.2 → 96 Pa；E14 `runB_note` 归档原文记为"约 98 Pa"） |
| p outlet | fixedValue uniform 0 |
| p walls | zeroGradient |
| U inletL/inletR | zeroGradient |
| U outlet | zeroGradient |
| U walls | fixedValue uniform (0 0 0) |

**Run-B 口径用途**（E14）：双侧入口等压 80 压力驱动，输出**真实自然分流比**与鼻腔阻力 R = dP/Q；Run-B 的分流比**仅在该模式下**可作指标（规划 #4）。`system/` 与 Run-A 完全相同（E1–E3）。

**归档现状（如实）**：`out/` 中 Run-B 只有 step2 算例（`0/constant/system`），**没有 Run-B 的求解结果归档**（`out/结果/` 无 `P0-result-*-v1B`）。M2 复刻 Run-B 时需自行求解并新建归档，其数值验收以 Run-B 模式指标为准（不得回头引用 Run-A 分流）。

---

## 9. 求解流程（Allrun）

实证：E9（全文原文）：

```
#!/bin/sh
set -e
cd "${0%/*}" || exit 1
echo "== checkMesh =="
checkMesh | tee log.checkMesh
echo "== simpleFoam =="
simpleFoam | tee log.simpleFoam
echo "== 导出VTK =="
foamToVTK -latestTime
echo "== 完成。把整个case目录拷回共享文件夹即可 =="
```

---

## 10. 收敛行为实测（M2 对拍时必须复现的"过程量"）

实证：E15（`log.simpleFoam`）、E17（`allrun.log`）。

- **残差判据回显**（E15 开头）：`SIMPLE: convergence criteria`，随后 `field p` <tab> `tolerance 0.0001`、`field U` <tab> `tolerance 0.0001`——与 §4 residualControl 一致。
- **实际收敛情况**：全文 `SIMPLE solution converged` 命中 **0 次**——运行未触发残差早停，**跑满 1500 步由 endTime 硬停**。末步（Time = 1500）：Ux/Uy/Uz smoothSolver 末残差 4.03e-05 / 1.78e-05 / 1.81e-05（均 < 1e-4）；p 的 GAMG **初始残差 1.07e-2 > 1e-4**（未达标）。
- **连续性误差**（末步）：`sum local = 0.0989548, global = 0.00386624, cumulative = 0.30299`。
- **耗时**：`ExecutionTime = 1437.68 s`（E17 末行；pA-v1，269,913 cells，nProcs=1，WSL）。
- **发布门口径**（E13 `release_gates`）：checkMesh 0 errors；flux 闭合 < 1%；残差早停或 1500 步平台（如实报告）；末 500 步 Δp 变化 < 2%；Run-B 分流比方向与几何不对称一致。
- M2 自研求解器对拍时：**不得**伪造"converged"——过程量（残差曲线形态、1500 步硬停、连续性误差量级）须与归档同构；指标量按 validation-baselines.md 的 ±2% 容差判定。

---

## 11. 后处理口径（指标如何从场算出来）

实证：E18/E19/E20（report.md 的 Formulae / sources 节）。

- `rho = 1.2 kg/m³`，`nu = 1.8e-05 m²/s`，`mu = 2.16e-05 Pa·s`；VTK 几何单位 **m**，速度 m/s，OpenFOAM `p` 为**运动学压力**（`[0 2 -2]`，m²/s²）。
- 面积 `A = Σ_f A_f`；流量 `Q = Σ_f |U_f·n_f|·A_f`（mm²→m² 乘 1e-6；m³/s→L/min 乘 60000）。
- 压强 `p_mean = rho · Σ_f p_f / N_f`（**入口 patch 面数平均——非质量加权**；M1 门控审计 GLM 复算实证：(56·pL+62·pR)/118 = 44.90667058007191 与 metrics.json 逐位吻合；原契约『质量加权』描述有误，以归档 metrics 为 ground truth 修正；generator 脚本不在仓库（M1C3），本口径系输出反推，M2 后处理 harness 必须同构实现此平均）。
- **dP = p_in − p_out**，p_out = 0（outlet patch fixedValue 0）→ dP 即入口质量加权总压。
- WSS 二阶口径（2026-10-20 W8 修订）：壁面法向三点二次重构（含 U_w=0 约束）	au = mu*(9*u1 - u2)/(3*Delta)，u1/u2=贴壁/第二层 cell 切向速度、Delta=层距；守卫（层距比 [2,4]±eps、方向对齐 >0.9、sliver）不满足回退一阶 mu*|(I-nn^T)U_i|/d_n 并计数。原一阶口径保留为回退路径与对照基线；归档值为 OF wallShearStress functionObject（controlDict 已挂 wss），M2 等同口径说明见 equivalence-report D-7。
- 入口为均匀速度 BC（非充分发展剖面）——报告原文明示 dP 含入口发展段效应（Caveat 3）。

---

## 12. M2 复刻清单（红线 / 可异 / 禁止）

**必须逐位一致（红线）**：
1. fvSolution 全字段（§4）：GAMG(GaussSeidel, 1e-6, 0.05) / smoothSolver(GaussSeidel, 1e-5, 0.01)；residualControl **p=1e-4 且 U=1e-4**；relaxationFactors **p=0.3 / U=0.7**；cache grad(U)。
2. fvSchemes 全字段（§5）：`div(phi,U) = bounded Gauss linearUpwind grad(U)`；laplacian `Gauss linear corrected`；snGrad `corrected`；ddt steadyState。
3. controlDict（§6）：simpleFoam、endTime 1500、deltaT 1、writeInterval 500、三个 flux 函数对象 + wallShearStress。
4. constant/（§3）：nu=1.8e-5、laminar。
5. Run-A BC（§7）与 Run-B BC（§8）全字段，含 `flowRateInletVelocity` 两侧流量值与 `fixedValue uniform 80`。
6. 稳态迭代上限 1500 步 + 欠松弛 0.3/0.7 的**组合行为**（残差平台形态，§10）。

**允许不同**：线性求解器的内部实现细节（GAMG 的 coarse 策略、smoothSolver 的迭代次数）——以"收敛到同等残差水平"为准；写出格式/精度。

**禁止**：①把 residualControl 改成 1e-4/1e-5 混搭；②丢 `bounded` 限示；③定流量分流比作为自研求解器正确性证据（同义反复）；④在开发上下文引入 OpenFOAM 源码（规划 §5 清洁室：只读方法论文档）。

---

## 13. 契约冻结与变更

- 本文档随 M1 轨 A 交付，经双模型审计 GO 后按 G2 冻结；任何字段变更 → 迷你审计门（至少一位审计官）+ 本文件版本号递增 + 变更记录表。
- 审计 GO 前，M2 只可按本文档**只读参照**，不得据未冻结版本写实现。

（完 · v1.0 · 2026-10-17 · 编码手 step-5-preview · 轨 A）


## 修订记录

- **2026-10-20（W6 收官）**：线性求解器预条件子默认值 SGS → **IC(0)+常数模 deflation**（`FLOWSCOPE_PRECOND`/`FLOWSCOPE_DEFLATE` 可覆盖回退）。判据不受影响——"同等残差水平"语义不变（relTol/absTol 未动，仅收敛路径改变）；L0-L3 全门重验 7/7（证据：`solver/docs/W6-验收.md` v3 章节）。附带修复求解器提前收敛跳过最终写出的路径缺陷（simple.rs 兜底写）。

## 修订记录

- **2026-10-20（W8）**：§5 divSchemes 的 `div((nuEff*dev2(T(grad U)))) Gauss linear` 显式源**已实现**（D-6 关闭）；§11 WSS 口径行修订为二阶三点重构（D-7 关闭，L0 解析门 ny=41 1.42%）；evidence 指向 solver/docs/W8-验收.md。
