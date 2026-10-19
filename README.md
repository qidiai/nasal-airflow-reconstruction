# 鼻腔气流分析工具（P0 鼻塞设计工具 · 源码公开版 · BSL 社区许可）

黑客松概念验证项目：从鼻腔 CT（DICOM）出发，经气道分割 → OpenFOAM 算例构建
→ CFD 仿真 → 鼻塞虚拟植入评估 → 查看器数据导出 → 体数据/皮肤层构建的完整
处理管线，配套一个自包含的 3D 交互查看器（内联 three.js，无外部依赖）。

本项目由 **患者社区 K-Hub** 发布。

## QUICKSTART（10 分钟开箱）

```bash
py -3 -m venv .venv && .venv\Scripts\activate   # ① 虚拟环境（Linux/Mac: python3 -m venv .venv && source .venv/bin/activate）
pip install -r requirements.txt                 # ② 装依赖（numpy/scipy/pydicom/scikit-image/trimesh/matplotlib/pytest）
cd code/viewer && python gen_demo_data.py       # ③ demo：重生成合成示例数据 viewer_data.js（无需患者数据）
cd ../.. && pytest                              # ④ 冒烟测试（全绿 = 开箱正常）
```

- 输出路径占位（Windows 示例，示例值格式 `<盘符>:\目录名`）：`set QIDI_WORKSPACE=C:\p0work`（管线输出工作区）、`set DATA_ROOT=D:\p0data`（数据根目录）；PowerShell 写作 `$env:QIDI_WORKSPACE="C:\p0work"`、`$env:DATA_ROOT="D:\p0data"`。设置后 step1/step2 输出到该工作区（未设置则使用字面量占位目录）。
- 真实 CT 输入：`set P0_DICOM_DIR=C:\p0work\dicom`（目录内放 `*.dcm`；本仓库不含患者数据，上述 ①-④ 步无需设置）。

## 数据说明（重要）

> **数据政策（2026-10-17 项目所有者亲定）**
>
> 本项目的可行性**已用真实患者数据测试验证**——鼻腔 CT → 气道分割 → CFD → 功能成像全链路跑通，指标经过对拍校验，未收敛算例如实标注"结果不可用"。
> 但**真实患者数据不开源**：除非取得患者本人同意，且患者数据**不得用于任何商业用途**。现有患者衍生资产（演示四例、pA/pB/pN 归档）均在上述闭门范围内，仓库与发布包只包含代码、文档与全合成数据。
> 感兴趣、有想法的贡献者：**欢迎用你自己的数据测试**——全流程本地运行，数据不出机（接入方式见 QUICKSTART 的 `P0_DICOM_DIR`）。
>
> **Data policy.** Feasibility of this project has been **validated on real patient data** — the full pipeline (nasal CT → airway segmentation → CFD → functional imaging) runs end-to-end, metrics were cross-checked, and unconverged runs are honestly flagged as "results unusable".
> Real patient data is **not open-sourced**: it may be distributed only with the patient's own consent, and is **never permitted for any commercial use**. All existing patient-derived assets (the four demo cases, pA/pB/pN archives) stay in this closed scope; the repository and release packages contain only code, documentation, and fully synthetic data.
> Interested contributors: **bring your own data and test** — everything runs locally and your data never leaves your machine (see `P0_DICOM_DIR` in QUICKSTART).


**本仓库不含任何患者数据。**

- 查看器自带 **100% 合成示例数据**（`code/viewer/viewer_data.js`），由
  `code/viewer/gen_demo_data.py` 生成（弯曲收缩管腔参数模型 + 层流泊肃叶
  解析），与任何真实案例、CT 影像、测量值无关。
- `volume_data.js`（CT 体数据层）与 `skin_data.js`（皮肤壳层）**不随仓库
  发布**：二者均由真实 CT 派生，属患者数据。查看器对缺失的体数据/皮肤层
  有优雅降级（对应图层自动隐藏，其余功能不受影响）。
- 真实 CT 数据需另行准备：DICOM 目录经环境变量 `P0_DICOM_DIR` 传入各
  管线脚本（默认相对路径 `./dicom`）。
- 查看器中的分侧压降、通气分配等数字在合成数据中为**合成示例值**，
  与演示环境的真实基线数字无关、不可互换。

## 运行方式

### 1. 交互查看器（无需构建）

```bash
cd code/viewer
python -m http.server 8080
# 浏览器打开 http://localhost:8080/viewer.html
```

查看器功能：气道三壳（主腔/腔体/鼻窦）3D 浏览、流线动画、截面切片、
1/2/3 mm 缩窄占位档对比、体积-压降曲线、皮肤层开关（默认关，
defacing 处置——皮肤层数据缺失时该开关自动隐藏）。

重新生成合成示例数据：

```bash
cd code/viewer
python gen_demo_data.py     # 重写 viewer_data.js
```

### 2. 数据处理管线（需 numpy/scipy/pydicom/trimesh；CFD 默认自研 FlowScope，OpenFOAM 可选）

```bash
export P0_DICOM_DIR=/path/to/dicom      # CT 数据目录（Windows: set P0_DICOM_DIR=...）

python code/pipeline/step1_airway_segment.py     # 气道分割（阈值+连通域+轮廓提取）
python code/pipeline/step2_make_ofcase.py        # OpenFOAM 算例构建（网格/边界/参数）
python code/pipeline/step3_make_narrowing.py     # 虚拟鼻塞（缩窄区几何）
python code/pipeline/step4_export_implant.py     # 植入体 STL 导出
python code/pipeline/step5_export_viewer_data.py # 查看器数据包导出
python code/pipeline/step6_build_volume_data.py  # 体数据层（需原始 CT，本仓库不发布产物）
python code/pipeline/step7_build_skin_data.py    # 皮肤壳层（需原始 CT，本仓库不发布产物）
python code/pipeline/run_all.py --dicom-dir <CT目录>  # 一键总控编排（step1→step7 + PII/朝向/回归比/出口/冒烟五闸门）
```

开箱自检（先 `cd code`）：`python -m pipeline.cli capabilities` —— 打印依赖/输入目录/输出占位环境变量就绪状态。
各脚本默认参数与内部路径已参数化（CT 目录经 `P0_DICOM_DIR`/`--dicom-dir`；输出与审计路径经 %QIDI_WORKSPACE%/%DATA_ROOT% 占位）——全仓无机器绝对路径，核心管线不含硬编码患者路径。
`step1_airway_segment.py` 与 `step2_make_ofcase.py` 支持 `--dicom-dir`（覆盖 `P0_DICOM_DIR`）；`step2_make_ofcase.py` 支持 `--case/--ext/--iso` 等选项（延长段、去窦对照）。
裸跑（无 DICOM）时 step1/step2 给出中文可操作报错并中止，不产生 IndexError 裸崩。

### 3. 验证与审计工具

`code/verify/` 收录施工期的验证/审计工具（网格校验、左右符号链、查看器
数据完整性等），可独立运行。

### 3b. 测试

- `tests/test_quickstart.py`：开箱冒烟——源码可编译、依赖清单存在、README 占位说明、
  合成示例数据完整、step1/step2 裸跑友好报错、cli capabilities。开箱仓库直接 `pytest tests/test_quickstart.py` 全绿（7 项开箱冒烟）；`tests/test_api.py` 全量需配置 CT 根与部署资产。
- `tests/test_api.py`：工作台 API 测试五类 36 项（契约 / 数据边界拒绝 / exit 2/3 闸门映射 /
  指标一致性，含双口径不可互换断言）。需工作台服务端 `code/pipeline/server.py`（随仓库发布；CT 根经 `P0_CT_BASE` 注入，不含患者数据；
  未配置该环境变量时内置用例跳过）。

### 3c. 一键管线与 Web 工作台

- `code/pipeline/run_all.py`：一键总控（step1→step7 顺序链路 + 五闸门；`--ext/--iso/--voxel-z/--merge-mode/--publish` 透传）。
- `code/pipeline/server.py` + `code/pipeline/webapp/`：多患者 Web 工作台（Flask 后端 + 前端；CT 根经 `P0_CT_BASE` 注入，不含患者数据）。
- 工作台默认仅监听本机（`--host` 默认 `127.0.0.1`，演示安全）；同网投屏 / 多机访问可显式 `--host 0.0.0.0`。
- `code/pipeline/标注协议-KHub鼻腔气道-20261009.md`：KHub 标注协议 v1（出口标志写死 / 冻结参数表）。

## 求解后端（M3 起）

流水线的 CFD 环节（`run_all.py --solve local`、Web 工作台的 `/api/solve` 与
`/api/full`）统一经 `code/pipeline/solver_backend.py` 选择后端，默认 `auto`：

| backend | 行为 |
|---|---|
| `custom` | 自研 FlowScope（`code/solver/target/release/flowscope[.exe]`，M2 产物）直接求解；**无需 WSL/OpenFOAM** |
| `openfoam` | 生成算例后在 WSL 运行 `Allrun`（`simpleFoam`）；保留为对拍基准 |
| `auto`（默认） | 找到 FlowScope 可执行文件即用 `custom`，否则回退 `openfoam` |

### auto 的路由规则

- **Run-A（定流量入口，15 L/min）**：一律优先 `custom`。L1 契约对拍 pA `dP` +1.61%、
  pB −0.63%（`code/solver/docs/equivalence-report.md` §2.1），均在 ±2% 容差内。
- **Run-B（等压入口，自然分流）**：流水线**不自动发起** Run-B 求解（沿用交接/手工
  流程）；需要时由 `solver_backend.choose_run_b_backend(cells)` 判定路由——
  `cells <= 50,000` 建议 `custom`，更大网格建议 `openfoam`。`run_all` 已把该建议写入
  manifest 的 `stages.S5_solve.run_b_routing`，便于审计复现。依据
  `equivalence-report.md` §2.2：自研求解器的 Run-B 在 pA 满分辨率网格（269,913 cells）
  上因鼻阀高 Péclet 速度峰失稳（斜坡/启动松弛/势流初场/限示器/一阶迎风均不能阻止，
  conditions-ledger G-C3b）；pN-v6B（26,884 cells）已收敛验证。阈值常量见
  `solver_backend.RUNB_CUSTOM_MAX_CELLS`。
- 显式指定 `custom` 时仍按用户要求尝试；失败如实报错（exit 3），不静默改后端。

### 如何手动指定

```bash
# 一键管线
python code/pipeline/run_all.py --dicom-dir <CT目录> --solve local --backend auto|custom|openfoam

# Web 工作台：server.py 无 --backend 参数，经环境变量注入后启动
#   PowerShell: $env:FLOWSCOPE_BACKEND="custom"
set FLOWSCOPE_BACKEND=custom
python code/pipeline/server.py

# 自定义 FlowScope 可执行文件位置（可选）
set FLOWSCOPE_BIN=D:\tools\flowscope.exe
```

- `run_all.py`：`--backend auto|custom|openfoam`（默认 `auto`）。
- `server.py`：无命令行参数；启动前设 `FLOWSCOPE_BACKEND`（未设则 `auto`）。

### OpenFOAM 后端的定位（为什么保留）

OpenFOAM 后端**不删除**，作为对拍真值源：L3 批量回归（baseline27）与 Run-B 大网格
仍需它提供归档指标；`code/pipeline/legacy/openfoam-reference/` 只保存 GPL-3.0 算例
模板作历史参考与对拍基准，**不随 BSL 核心分发**（见根 `NOTICE` 第 2 节）；OpenFOAM
本体不随仓库分发，用户自行安装（GPL-3.0）。细节见
`code/pipeline/legacy/openfoam-reference/README.md`。

## 仓库剔除说明

以下源工程文件**未收录**于本仓库（脱敏审查命中患者标识）：

- `cmd_self_audit.py`、`cmd_t10_step5_audit.py`：内含真实个人标识字面量
  （真实全名与出生年月值），作为其产物扫描的检测模式，无法参数化脱敏，
  整文件剔除。
- `cmd_t10_errata.py`：引用内部医疗监测文档名称（文件名含就诊日期标识），
  属就诊记录指涉，整文件剔除。

其余全部源码经五类个人标识关键字扫描（真实全名、出生年月、人名代称、
患者编号、身份号码）与正则扫描（身份号码格式、日期字面量、绝对路径）
通过后收录；`viewer.html` 仅页脚一处数据来源文案改为"合成示例数据"。

## 医学分析线（脱敏代码与文档）

本仓库补充收录医学分析线的纯代码与过程文档（**不含任何患者数据**）：

- `code/pipeline/medical_extract/` —— 九键交付物提取脚本族（planes / wall / wallp / zonal / clinical / residual / mesh_quality / compare / transport）。
- `docs/科学依据与公式附录.md` —— 科学依据与公式附录。
- `docs/kanban/` —— 施工看板（过程证据存档）。

> 患者 CT/DICOM/掩码及一切派生几何数据严禁入库（.gitignore 强制）；本仓库仅含管线代码、合成演示数据与聚合统计。

## 许可证

Business Source License 1.1（见 `LICENSE` 与 `NOTICE`）：
非商业用途（个人/患者自用/学术研究/教育）免费；**商用须获得 Licensor（Xu Changming）书面授权**；
Change Date 2099-01-01 后方转为 Apache-2.0。legacy OpenFOAM 模板为 GPL-3.0（见 NOTICE 第 2 节）。

## 免责

概念验证 · 非医疗器械 · 仿真几何禁止人体使用。
