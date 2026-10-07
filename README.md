# 鼻腔气流分析工具（P0 鼻塞设计工具 · 开源脱敏版）

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

### 2. 数据处理管线（需 numpy/scipy/pydicom/trimesh，CFD 环节需 OpenFOAM）

```bash
export P0_DICOM_DIR=/path/to/dicom      # CT 数据目录（Windows: set P0_DICOM_DIR=...）

python code/pipeline/step1_airway_segment.py     # 气道分割（阈值+连通域+轮廓提取）
python code/pipeline/step2_make_ofcase.py        # OpenFOAM 算例构建（网格/边界/参数）
python code/pipeline/step3_make_narrowing.py     # 虚拟鼻塞（缩窄区几何）
python code/pipeline/step4_export_implant.py     # 植入体 STL 导出
python code/pipeline/step5_export_viewer_data.py # 查看器数据包导出
python code/pipeline/step6_build_volume_data.py  # 体数据层（需原始 CT，本仓库不发布产物）
python code/pipeline/step7_build_skin_data.py    # 皮肤壳层（需原始 CT，本仓库不发布产物）
```

开箱自检（先 `cd code`）：`python -m pipeline.cli capabilities` —— 打印依赖/输入目录/输出占位环境变量就绪状态。
各脚本默认参数与内部路径已参数化（`P0_DICOM_DIR`），核心管线无硬编码患者路径（审计/验证脚本为参考件，含本机路径占位，见 %QIDI_WORKSPACE%/%DATA_ROOT%）。
`step1_airway_segment.py` 与 `step2_make_ofcase.py` 支持 `--dicom-dir`（覆盖 `P0_DICOM_DIR`）；`step2_make_ofcase.py` 支持 `--case/--ext/--iso` 等选项（延长段、去窦对照）。
裸跑（无 DICOM）时 step1/step2 给出中文可操作报错并中止，不产生 IndexError 裸崩。

### 3. 验证与审计工具

`code/verify/` 收录施工期的验证/审计工具（网格校验、左右符号链、查看器
数据完整性等），可独立运行。

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

## 许可证

MIT License（见 `LICENSE`）。

## 免责

概念验证 · 非医疗器械 · 仿真几何禁止人体使用。
