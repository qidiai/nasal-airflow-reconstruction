//! FlowScope 自研有限体积（FVM）求解器 —— Rust 清洁室实现
//!
//! # 定位
//! 复刻对象唯一：`pipeline/docs/contracts/numerical-contract.md`（v1.0，M1 轨 A 交付，E1-E22 实证）。
//! 数值基准 = OpenFOAM v2406 `simpleFoam`（laminar / steady / incompressible）。
//!
//! # 清洁室纪律（产品宪法 §5）
//! 1. 文献基线（允许且必须读）：Patankar & Spalding《SIMPLE 1972/1980》、Rhie & Chow 1983
//!    （checkerboard 抑制）、Versteeg & Malalasekera《An Introduction to CFD: the FVM》、
//!    Ferziger & Peric《Computational Methods for Fluid Dynamics》、Golub & Van Loan（Krylov 迭代法）。
//! 2. 禁止把任何 OpenFOAM 实现源码读入开发上下文；本仓库 `吸收库/` 与被禁库一律不读。
//! 3. 每个模块顶部写 provenance 注释（依据的文献/算法）。
//! 4. 复刻对象只有 numerical-contract.md 一份。
//!
//! # 模块
//! - [`mesh`] / [`meshio`]：OpenFOAM ascii polyMesh 数据结构与读取（数据文件，非源码）
//! - [`bc`] / [`config`]：边界条件框架与算例配置（Run-A 定流量 / Run-B 等压双口径）
//! - [`fields`]：体/面场与 Gauss linear 插值、Gauss linear 梯度
//! - [`fvm`]：离散算子（bounded linearUpwind 对流 / corrected laplacian / snGrad）
//! - [`linalg`]：CSR 稀疏矩阵 + PCG（IC0）/ BiCGSTAB（Gauss-Seidel 光滑）
//! - [`simple`]：SIMPLE 主循环（Rhie-Chow 耦合 + 欠松弛 0.3/0.7 + 1500 步上限）
//! - [`metrics`]：后处理口径（p_mean 面数平均、dP、WSS、通量闭合）

pub mod bc;
pub mod config;
pub mod fields;
pub mod fvm;
pub mod linalg;
pub mod mesh;
pub mod meshio;
pub mod metrics;
pub mod simple;

/// 全局物性常量（契约 §3/§11）：nu = 1.800e-05 m²/s；后处理口径 rho = 1.2 kg/m³。
pub const NU_AIRWAY: f64 = 1.800e-05;
pub const RHO_AIR: f64 = 1.2;
/// mu = rho * nu = 2.16e-05 Pa·s（契约 §11，仅后处理 WSS 用）
pub const MU_AIR: f64 = 2.16e-05;
