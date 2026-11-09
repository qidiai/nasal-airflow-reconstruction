# 随仓库分发的 FlowScope 预编译二进制

本目录随仓库分发 **FlowScope**（本项目自研 CFD 求解器）的预编译可执行文件，
目的是让患者 / 医生在**干净 clone 后无需安装 Rust / cargo、无需 WSL / OpenFOAM**，
即可用 `auto` 后端命中 `custom` 求解，直接 `--solve local` 跑通 CT → 3D 结果。

> 前期为**纯本地**形态：仓库拉取到本机运行，不提供云端服务，数据不上传外网。

## 二进制清单

| 文件 | 平台 / 架构 | 格式 | 体积 | sha256 |
|---|---|---|---|---|
| `flowscope-win-x64.exe` | Windows x86_64（AMD64） | PE32+ | 616960 B | `e5c439c2b4e3b70b75637b888d4a52fd95310db03e372feeaceb1867586f219e` |
| `flowscope-linux-x64` | Linux x86_64 | ELF PIE | 921344 B | `43b6f839bca42c8f3907fbe32000770a75594e3d8a90d72d50e5027856e89a65` |

核对：`sha256sum flowscope-win-x64.exe flowscope-linux-x64`。

## 来源与编译环境（历史记录；本目录文件为复制品、非重新编译）

- **Windows**：由 `code/solver/` 在 Windows 上 `cargo build --release` 产出
  `code/solver/target/release/flowscope.exe`（rustc **1.98.1**），复制并重命名为
  `flowscope-win-x64.exe`。
- **Linux**：由 WSL 内
  `cargo build --release --target x86_64-unknown-linux-gnu --target-dir /tmp/fs-linux-build`
  产出 `…/release/flowscope`（rustc **1.99.0**，零第三方依赖、纯标准库），复制并
  重命名为 `flowscope-linux-x64`。

本目录两个文件是**逐字节复制**自上述已编译产物，未经重新编译；编译产物原件
（`code/solver/target/release/`）被 `.gitignore` 忽略、不入库，故以本目录随仓库分发。

## 平台边界（如实）

- **仅提供 Windows x86_64 与 Linux x86_64 两个预编译二进制。**
- **macOS、ARM / aarch64、其它架构与操作系统没有预编译二进制**：
  `solver_backend.flowscope_path()` 在这些平台不会匹配本目录，会回退到
  `code/solver/target/release/flowscope[.exe]` 自构建路径，绝不把 ELF/PE 误喂给
  非对应平台。这些平台请安装 Rust 后自行构建（见下）。
- **Linux clone 后须补可执行位**：Windows 侧 NTFS 不保留 Unix 可执行位，Linux
  首次使用前执行 `chmod +x code/solver/bin/flowscope-linux-x64`
  （`scripts/bootstrap.sh` 探测到该文件时会自动补 `chmod +x`）。

## 自行构建 / 复现

源码在 **`code/solver/src/`**（零第三方依赖、Rust 纯标准库）：

```bash
cd code/solver
cargo build --release                     # 产出 target/release/flowscope[.exe]
# 交叉编译 Linux x86_64（示例）：
cargo build --release --target x86_64-unknown-linux-gnu
```

构建产物会被 `solver_backend.flowscope_path()` 在「无本目录预编译二进制」时自动
探测；也可用环境变量 `FLOWSCOPE_BIN=<路径>` 显式指定（优先级最高）。
探测顺序：`FLOWSCOPE_BIN` → 本目录平台预编译 → `target/release` 自构建产物。

## 许可

本二进制属于 **Licensed Work**，随仓库按 **Business Source License 1.1** 分发
（见根 `LICENSE` / `NOTICE`）。BSL 1.1 的 **Additional Use Grant** 允许
**patient self-use（患者本人自用）** 与 **非商业 Production Use**：
个人 / 患者自用 / 学术研究 / 教育用途免费；**商业用途须获得 Licensor 书面授权**；
Change Date（2099-01-01）后转为 Apache-2.0。源码同样受该许可约束，详见根 `LICENSE`。
