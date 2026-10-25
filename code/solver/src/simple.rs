//! SIMPLE 主循环驱动 + 结构化盒网格生成 + Poiseuille 解析验证
//!
//! provenance（清洁室，依据文献）：
//! - SIMPLE 主循环：Patankar & Spalding（SIMPLE, 1972/1980）。每步：
//!   ①组装松弛后动量矩阵（方程松弛 α_U=0.7）→ ②HbyA = A'⁻¹b'（动量无压预测）
//!   → ③Rhie-Chow 面通量 phi = HbyA·Sf − rAU·k·Δp → ④压力方程 laplacian(rAUf,p)=div(phiHbyA)
//!   → ⑤p 欠松弛（α_p=0.3）→ ⑥U = HbyA − rAU·grad(p) 校正 + BC 刷新。
//! - Rhie & Chow（1983）压力-速度耦合抑制 checkerboard。
//! - 解析验证：平面 Poiseuille 层流（u(y)=u_max(1−((y−H/2)/(H/2))²)，u_max=1.5·U_mean，
//!   −dp/dx = 12·nu·U_mean/H²）——经典 FVM 教科书基准（Versteeg & Malalasekera §4.2.2）。

use std::collections::VecDeque;
use std::path::Path;

use crate::bc::{BoundaryConditions, PatchBC, PressureBC, VelocityBC};
use crate::config::{CaseConfig, RunMode, SolverParams};
use crate::fields::{grad_scalar, grad_vector, VolScalar, VolVector};
use crate::fvm::{
    adjust_phi, assemble_momentum, assemble_pressure, bnd_pres_fixed_flags, compile_patches,
    hbya_flux, rhie_chow_phi, FvVectorMatrix,
};
use crate::linalg::{
    dump_csr, ic0_reset_stats, ic0_stats, matrix_precheck, pcg, pcg_equiv_check, sgs_solve,
    two_level_enabled, two_level_reset_stats, two_level_stats, Csr, LinSolveInfo, PrecondKind,
};
use crate::mesh::{dot, Mesh, Patch};
use crate::metrics::{
    dp_pa, flow_split, patch_area, patch_face_mean_p, patch_flux_sum, vtk_write,
    wall_shear_stress, wall_shear_stress_ex,
};
use crate::{MU_AIR, NU_AIRWAY, RHO_AIR};

/// 单步迭代记录（过程量，对拍归档 log 用）
#[derive(Debug, Clone)]
pub struct IterRecord {
    pub iter: usize,
    pub ux: f64,
    pub uy: f64,
    pub uz: f64,
    pub p_res: f64,
    pub cont_local: f64,
    pub cont_global: f64,
}

/// dP 稳定性早停判据参数（**写死**，见任务书「判据定义」；只换停车判据，不动物理）
///
/// 判据动机（实测）：质量档 1500 步里后 1000 步对 dP 无贡献——dP 早在 100~500 步
/// 就进入 0.2% 带且不再离开，多跑只是在追 1e-4 级的线性残差；而线性容差收紧
/// 4.1 倍时间只换来外残差 3% 改善、dP 反动 4.3%——残差不是 dP 的可靠代理。
#[derive(Debug, Clone, Copy)]
pub struct DpStopConfig {
    /// 采样间隔（步）：每 20 步算一次 dP
    pub sample_every: usize,
    /// 参考窗口：最近 5 个采样的均值
    pub window: usize,
    /// 相对带（0.002 = 0.2%）
    pub band_rel: f64,
    /// 最小步数下限（避免入口瞬态误判）
    pub min_iter: usize,
    /// 最近采样的全局连续性上限（防在数值爆掉的瞬态里停）
    pub cont_global_max: f64,
    /// 连续满足轮数（2 = 已覆盖 5 样本窗口再加一轮确认）
    pub confirm_rounds: usize,
}

impl Default for DpStopConfig {
    fn default() -> Self {
        DpStopConfig {
            sample_every: 20,
            window: 5,
            band_rel: 0.002,
            min_iter: 100,
            cont_global_max: 1e-2,
            confirm_rounds: 2,
        }
    }
}

/// 单次评估窗的判据结论（`dp_stop_decide` 的纯函数输出，无任何副作用）
///
/// 三道门（带内 / 最小迭代 / 连续性余量）+ 确认计数全在这里表达，求解循环只做
/// 「取值 → 打印 → 赋值 → break」；因此判据行为可被单测直接构造输入覆盖，
/// 不需要跑完整个 SIMPLE 迭代才能验证。
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct DpStopVerdict {
    /// 采样窗是否已满（未满 → 不评估：confirm 原样返回、stop = false）
    pub ready: bool,
    /// 参与判定的样本数
    pub n_samples: usize,
    /// 窗内 dP 均值（参考值 dp_ref）；窗未满时为 NaN
    pub dp_ref: f64,
    /// 窗内最大相对偏差（无量纲）
    pub band_rel: f64,
    /// 窗内最大相对偏差的**百分数数值**（0.1896 表示 0.19%，不是 0.1896%）
    pub band_pct: f64,
    /// 本窗三道门是否全过：带内 && iter >= min_iter && cont_global < cont_global_max
    pub stable: bool,
    /// 累计确认次数：本窗稳定则 prev_confirm + 1，否则**清零**
    pub confirm: usize,
    /// 是否应当停车：confirm >= confirm_rounds
    pub stop: bool,
}

/// 「是否该停车」的**纯判定**：输入采样窗 + 迭代号 + 连续性全局余量 + 判据参数 +
/// 上一窗的确认计数，输出本窗结论。不读 `self`、不看时钟、不落盘 ——
/// 求解循环与单测走同一条代码路径。
///
/// 语义与抽函数前逐字一致（三道门、confirm 递增/清零、stop 条件），仅把跨窗状态
/// 外置为 `prev_confirm` 参数以实现纯函数化；判据参数仍全部来自 [`DpStopConfig`]。
pub fn dp_stop_decide(
    samples: &[f64],
    iter: usize,
    cg: f64,
    cfg: &DpStopConfig,
    prev_confirm: usize,
) -> DpStopVerdict {
    // 只取尾部 window 个样本（调用方已压窗；此处再兜一层，纯函数不依赖外部裁剪）
    let window: &[f64] = if cfg.window > 0 && samples.len() > cfg.window {
        &samples[samples.len() - cfg.window..]
    } else {
        samples
    };
    if cfg.window == 0 || window.len() < cfg.window {
        return DpStopVerdict {
            ready: false,
            n_samples: window.len(),
            dp_ref: f64::NAN,
            band_rel: f64::NAN,
            band_pct: f64::NAN,
            stable: false,
            confirm: prev_confirm,
            stop: false,
        };
    }
    let n = window.len() as f64;
    let dp_ref = window.iter().sum::<f64>() / n;
    let dev = window
        .iter()
        .map(|v| (v - dp_ref).abs())
        .fold(0.0f64, f64::max);
    let band_rel = if dp_ref.abs() > 1e-300 {
        dev / dp_ref.abs()
    } else {
        f64::INFINITY
    };
    let band_pct = band_rel * 100.0;
    // 三道门：dP 带内 + 已过最小迭代 + 连续性全局余量 —— 任一不过即不稳定（confirm 清零）
    let stable = band_rel < cfg.band_rel && iter >= cfg.min_iter && cg < cfg.cont_global_max;
    let confirm = if stable { prev_confirm + 1 } else { 0 };
    DpStopVerdict {
        ready: true,
        n_samples: window.len(),
        dp_ref,
        band_rel,
        band_pct,
        stable,
        confirm,
        stop: confirm >= cfg.confirm_rounds,
    }
}

/// dP 稳定性判据的运行模式：决定「是否评估」，也决定横幅文案
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DpStopMode {
    /// 判据生效：residualControl OR dP-stable
    Enabled,
    /// 显式关闭：`--no-dp-stop` 或 `FLOWSCOPE_DP_STOP=0`
    SwitchOff,
    /// 不适用：入口 p 为 fixedValue 的定压驱动模式（Run-B），dP 由边界条件决定
    InletPressureFixed,
    /// 不适用：没有 inlet* / outlet patch 对
    MissingPatches,
}

/// 由开关 + 入口/出口 patch 情形派生判据模式（纯函数；优先级与抽函数前一致）
pub fn dp_stop_mode(
    dp_stop: bool,
    env_off: bool,
    inlet_pres_fixed: bool,
    n_inlets: usize,
    has_outlet: bool,
) -> DpStopMode {
    if !dp_stop || env_off {
        DpStopMode::SwitchOff
    } else if inlet_pres_fixed {
        DpStopMode::InletPressureFixed
    } else if n_inlets == 0 || !has_outlet {
        DpStopMode::MissingPatches
    } else {
        DpStopMode::Enabled
    }
}

/// 判据横幅文案：**仅判据真正生效时**罗列参数元组；关闭/不适用时只给一行原因，
/// 避免把「residualControl only」误读成「dP 判据已启用」。
pub fn dp_stop_banner(mode: DpStopMode, cfg: &DpStopConfig) -> String {
    match mode {
        DpStopMode::Enabled => format!(
            "residualControl OR dP-stable（每 {} 步采样 / {} 样本 / {:.1}% 带 / 最少 {} 步 / 连续 {} 轮确认 / 连续性 < {}）",
            cfg.sample_every,
            cfg.window,
            cfg.band_rel * 100.0,
            cfg.min_iter,
            cfg.confirm_rounds,
            cfg.cont_global_max
        ),
        DpStopMode::SwitchOff => "residualControl only —— dP 稳定性判据已关闭（--no-dp-stop / FLOWSCOPE_DP_STOP=0），本次运行不评估 dP 稳定性，也不会因 dP 停车".to_string(),
        DpStopMode::InletPressureFixed => "residualControl only —— dP 稳定性判据不适用：入口 p 为 fixedValue 的定压驱动模式（Run-B），dP 由边界条件决定，不含判据信息".to_string(),
        DpStopMode::MissingPatches => "residualControl only —— dP 稳定性判据不适用：未找到 inlet*/outlet patch 对".to_string(),
    }
}

pub struct SimpleSolver {
    pub mesh: Mesh,
    pub cfg: CaseConfig,
    pub patches: Vec<crate::fvm::PatchCtx>,
    pub bnd_pf: Vec<bool>,
    pub u: VolVector,
    pub p: VolScalar,
    pub hbya: VolVector,
    pub rau: Vec<f64>,
    /// Run-B 启动压力斜坡的基准值（PatchCtx.pres_value 的初始快照）
    pub p_bc_base: Vec<f64>,
    pub phi: Vec<f64>,
    pub grad_u: Vec<[[f64; 3]; 3]>,
    pub grad_p: Vec<[f64; 3]>,
    pub records: Vec<IterRecord>,
    pub lin_p: Vec<LinSolveInfo>,
    pub iter: usize,
    pub converged: bool,
    /// 停车判据代码（机器可读）：`dp_stable` | `residual` | `endtime`
    pub stop_reason: String,
    /// 停车原因的人读文本（日志 `stop reason :` 行；内容与改动前逐字节一致）
    pub stop_detail: String,
    /// 实际停车步（判据触发步；`endtime` 时为跑满步数）
    pub stop_iter: usize,
    /// 最后一次 dP 稳定性评估的带宽，**百分数数值**（0.1896 表示 0.19%，不是 0.1896%）；未评估过为 NaN
    pub dp_band_pct: f64,
    /// 结果稳定性早停开关（默认开；`--no-dp-stop` 或 `FLOWSCOPE_DP_STOP=0` 关闭）
    pub dp_stop: bool,
}

impl SimpleSolver {
    pub fn new(mesh: Mesh, cfg: CaseConfig) -> Result<Self, String> {
        let patches = compile_patches(&mesh, &cfg.bcs)?;
        let bnd_pf = bnd_pres_fixed_flags(&mesh, &patches);
        let u = VolVector::zeros(&mesh);
        let p = VolScalar::zeros(&mesh);
        let hbya = VolVector::zeros(&mesh);
        let rau = vec![0.0; mesh.n_cells()];
        let phi = vec![0.0; mesh.n_faces()];
        let p_bc_base: Vec<f64> = patches.iter().map(|p| p.pres_value).collect();
        Ok(SimpleSolver {
            mesh,
            cfg,
            patches,
            bnd_pf,
            u,
            p,
            hbya,
            rau,
            p_bc_base,
            phi,
            grad_u: Vec::new(),
            grad_p: Vec::new(),
            records: Vec::new(),
            lin_p: Vec::new(),
            iter: 0,
            converged: false,
            stop_reason: String::new(),
            stop_detail: String::new(),
            stop_iter: 0,
            dp_band_pct: f64::NAN,
            dp_stop: true,
        })
    }

    pub fn from_case_dir(dir: &Path) -> Result<Self, String> {
        let cfg = CaseConfig::load(dir)?;
        let mesh = crate::meshio::load_mesh(dir)?;
        Self::new(mesh, cfg)
    }

    /// 从 CSV（每行 Ux Uy Uz p，按 polyMesh 单元序）载入初始场（诊断/对拍用）
    pub fn load_init_csv(&mut self, path: &Path) -> Result<(), String> {
        let text = std::fs::read_to_string(path)
            .map_err(|e| format!("读取初始场 {} 失败: {e}", path.display()))?;
        let mut n = 0usize;
        for line in text.lines() {
            if n >= self.mesh.n_cells() {
                break;
            }
            let v: Vec<f64> = line
                .split_whitespace()
                .filter_map(|x| x.parse::<f64>().ok())
                .collect();
            if v.len() >= 4 {
                self.u.data[n] = [v[0], v[1], v[2]];
                self.p.data[n] = v[3];
                n += 1;
            }
        }
        if n != self.mesh.n_cells() {
            return Err(format!("初始场行数 {n} != 单元数 {}", self.mesh.n_cells()));
        }
        self.update_bcs();
        // 由速度场重建面通量（restart 时必须：否则首步 phi=0，对流项被整体跳过）
        for f in 0..self.mesh.n_faces() {
            let uf = self.u.face_value(&self.mesh, f);
            self.phi[f] = dot(uf, self.mesh.face_sf[f]);
        }
        Ok(())
    }

    /// correctBoundaryConditions：固定值 patch 用 BC 值，零梯度 patch 取相邻单元值
    fn update_bcs(&mut self) {
        let ni = self.mesh.n_internal;
        for p in &self.patches {
            for f in p.start..p.start + p.n_faces {
                let bi = f - ni;
                let c = self.mesh.face_owner[f] as usize;
                self.u.bnd[bi] = if p.vel_fixed {
                    p.vel_at(f)
                } else {
                    self.u.data[c]
                };
                self.p.bnd[bi] = if p.pres_fixed {
                    p.pres_value
                } else {
                    self.p.data[c]
                };
            }
        }
    }

    /// HbyA 边界值：固定速度 patch = 入口/壁面速度；零梯度 = 相邻单元 HbyA
    fn update_hbya_bnd(&mut self) {
        let ni = self.mesh.n_internal;
        for p in &self.patches {
            for f in p.start..p.start + p.n_faces {
                let bi = f - ni;
                let c = self.mesh.face_owner[f] as usize;
                self.hbya.bnd[bi] = if p.vel_fixed {
                    p.vel_at(f)
                } else {
                    self.hbya.data[c]
                };
            }
        }
    }

    /// 压力求解后刷新零梯度 patch 的边界面值（保证 Rhie-Chow 边界修正为零；
    /// 固定值 patch 不变）
    fn refresh_p_bnd(&mut self) {
        let ni = self.mesh.n_internal;
        for p in &self.patches {
            if p.pres_fixed {
                continue;
            }
            for f in p.start..p.start + p.n_faces {
                let bi = f - ni;
                let c = self.mesh.face_owner[f] as usize;
                self.p.bnd[bi] = self.p.data[c];
            }
        }
    }

    /// Run-B 等压模式启动压力斜坡（`FLOWSCOPE_RUNB_RAMP=<N>`，默认 0=关）：
    /// 入口 fixedValue 压力在前 N 步由 0 线性升到归档值（pA-v1B = 80 kinematic）。
    /// 动机（看板 G-C3b）：U=0 冷启动 + 全压差 fixedValue 在首步产生 |U|≈800 m/s
    /// 的非物理射流种子，随后压力场指数放大（iter 3 已 |p|max 1.4e5）直至 NaN。
    /// 压力参数连续性（pressure continuation）是 SIMPLE 标准启动手段；第 N+1 步起
    /// BC 与归档 0/p 逐字段一致（终态同口径），仅在启动阶段改动。
    fn apply_runb_p_ramp(&mut self, it: usize) {
        if self.cfg.run != RunMode::RunB {
            return;
        }
        let ramp = std::env::var("FLOWSCOPE_RUNB_RAMP")
            .ok()
            .and_then(|v| v.parse::<usize>().ok())
            .unwrap_or(0);
        if ramp == 0 {
            return;
        }
        let scale = (it as f64 / ramp as f64).min(1.0);
        for (i, p) in self.patches.iter_mut().enumerate() {
            if p.pres_fixed {
                p.pres_value = self.p_bc_base[i] * scale;
            }
        }
    }

    /// 动量预测器初残差（过程量；对标 OpenFOAM Ux/Uy/Uz smoothSolver Initial residual）
    fn momentum_init_res(&self, csr: &Csr, m: &FvVectorMatrix) -> [f64; 3] {
        let n = self.mesh.n_cells();
        let mut out = [0.0f64; 3];
        for comp in 0..3 {
            let x: Vec<f64> = self.u.data.iter().map(|v| v[comp]).collect();
            let mut ax = vec![0.0f64; n];
            csr.matvec(&x, &mut ax);
            let mut bsum = 0.0f64;
            let mut rsum = 0.0f64;
            for i in 0..n {
                let b_eff = m.source[i][comp] - self.mesh.cell_vol[i] * self.grad_p[i][comp];
                let r = b_eff - ax[i];
                bsum += b_eff.abs();
                rsum += r.abs();
            }
            out[comp] = (rsum / n as f64) / (bsum / n as f64).max(1e-300);
        }
        out
    }

    /// 连续性误差（1/s）：local = mean|Σ_f phi_f|/V，global = |mean Σ_f phi_f|/V
    fn continuity_errs(&self) -> (f64, f64) {
        let n = self.mesh.n_cells();
        let mut sum_abs = 0.0f64;
        let mut sum_signed = 0.0f64;
        for c in 0..n {
            let mut s = 0.0f64;
            for f in self.mesh.cell_face_iter(c) {
                s += if self.mesh.is_owner(f, c) {
                    self.phi[f]
                } else {
                    -self.phi[f]
                };
            }
            let v = self.mesh.cell_vol[c].max(1e-300);
            sum_abs += (s / v).abs();
            sum_signed += s / v;
        }
        (sum_abs / n as f64, (sum_signed / n as f64).abs())
    }

    pub fn run(
        &mut self,
        max_iter: Option<usize>,
        out_dir: Option<&Path>,
        verbose: bool,
    ) -> Result<(), String> {
        self.run_adv(max_iter, out_dir, verbose, 3000, None, None, None)
    }

    /// 带实验开关的 run（诊断用）
    #[allow(clippy::too_many_arguments)]
    pub fn run_adv(
        &mut self,
        max_iter: Option<usize>,
        out_dir: Option<&Path>,
        verbose: bool,
        p_cap: usize,
        alpha_p: Option<f64>,
        alpha_u: Option<f64>,
        lu_dev: Option<bool>,
    ) -> Result<(), String> {
        let max_iter = max_iter.unwrap_or(self.cfg.params.max_iter).max(1);
        let nu = self.cfg.nu;
        let alpha_u = alpha_u.unwrap_or(self.cfg.params.alpha_u);
        let alpha_p = alpha_p.unwrap_or(self.cfg.params.alpha_p);
        let lu_dev = lu_dev.unwrap_or(self.cfg.params.lu_deviation);
        // W6 开关：`FLOWSCOPE_PRECOND=sgs|ic0|mic0`（W6-v3 起默认 ic0 + 常数模 deflation，
        // 可用 `FLOWSCOPE_PRECOND=sgs` / `FLOWSCOPE_DEFLATE=0` 分别回退）。
        // 必须同时作用于下面两处 pcg 调用点（Run-B 位势流初始化 + 主循环压力方程），
        // 否则 A/B 对照会被初始化路径污染。
        let precond = PrecondKind::from_env();
        ic0_reset_stats();
        two_level_reset_stats();
        if std::env::var("FLOWSCOPE_INIT_UNIFORM").is_ok()
            && self.u.data.iter().all(|v| v == &[0.0, 0.0, 0.0])
        {
            let mut acc = [0.0f64; 3];
            let mut n = 0usize;
            for p in &self.patches {
                if p.vel_fixed {
                    let m = (p.vel_value[0].powi(2) + p.vel_value[1].powi(2) + p.vel_value[2].powi(2)).sqrt();
                    if m > 1e-12 {
                        acc[0] += p.vel_value[0];
                        acc[1] += p.vel_value[1];
                        acc[2] += p.vel_value[2];
                        n += 1;
                    }
                }
            }
            if n > 0 {
                let u0 = [acc[0] / n as f64, acc[1] / n as f64, acc[2] / n as f64];
                for c in 0..self.mesh.n_cells() {
                    self.u.data[c] = u0;
                }
                println!("[init] uniform U = ({:.4}, {:.4}, {:.4}) m/s", u0[0], u0[1], u0[2]);
            }
        }
        self.update_bcs();
        // 初始面通量：对标 OpenFOAM createPhi（phi = fvc::flux(U)）。
        // 边界面的 phi 必须来自 BC（定流量入口 = −Q），否则首步动量方程
        // 完全看不到入口对流通量，U* 与 HbyA 严重偏小，压力方程被迫用巨大的
        // 局部压差"补"出流量——这正是高 Péclet 几何上启动即发散的直接原因。
        for f in 0..self.mesh.n_faces() {
            let uf = self.u.face_value(&self.mesh, f);
            self.phi[f] = dot(uf, self.mesh.face_sf[f]);
        }
        self.grad_p = grad_scalar(&self.mesh, &self.p);
        self.grad_u = grad_vector(&self.mesh, &self.u);
        // Run-B 势流初场（`FLOWSCOPE_RUNB_POTENTIAL=1`，默认关）：
        // 先解无对流 Laplace 压力场（边界 fixedValue 80/0），再由 U = -rAU·grad(p)
        // 初始化速度并生成满足守恒的 Rhie-Chow 面通量。目的是消除 U=0 冷启动下
        // 全压差 fixedValue 对 SIMPLE 首步的冲击（G-C3b 发散机制）。
        if self.cfg.run == RunMode::RunB && std::env::var("FLOWSCOPE_RUNB_POTENTIAL").is_ok() {
            let m0 = assemble_momentum(
                &self.mesh,
                nu,
                alpha_u,
                &self.patches,
                &self.phi,
                &self.u,
                &self.grad_u,
                lu_dev,
            );
            let csr0 = m0.to_csr(&self.mesh);
            for c in 0..self.mesh.n_cells() {
                self.rau[c] = self.mesh.cell_vol[c] / csr0.diag_value(c).max(1e-300);
            }
            let zero_phi = vec![0.0f64; self.mesh.n_faces()];
            let pm = assemble_pressure(&self.mesh, &self.patches, &self.rau, &zero_phi, &self.bnd_pf);
            let pcsr = pm.to_csr(&self.mesh);
            let mut p0 = vec![0.0f64; self.mesh.n_cells()];
            let pinfo = pcg(&pcsr, &pm.source, &mut p0, 1e-9, 1e-8, 5000, precond);
            self.p.data = p0;
            self.refresh_p_bnd();
            self.grad_p = grad_scalar(&self.mesh, &self.p);
            for c in 0..self.mesh.n_cells() {
                let r = self.rau[c];
                self.u.data[c] = [
                    -r * self.grad_p[c][0],
                    -r * self.grad_p[c][1],
                    -r * self.grad_p[c][2],
                ];
            }
            self.update_bcs();
            self.hbya = self.u.clone();
            self.update_hbya_bnd();
            let phi_hbya = hbya_flux(&self.mesh, &self.hbya);
            self.phi = rhie_chow_phi(&self.mesh, &self.rau, &phi_hbya, &self.p);
            self.grad_u = grad_vector(&self.mesh, &self.u);
            println!(
                "[init] Run-B potential-flow: pLin {} it, final {:.3e}, |U|max {:.4e} m/s, |p|max {:.4e}",
                pinfo.iters,
                pinfo.final_res,
                self.u
                    .data
                    .iter()
                    .map(|v| v[0].abs().max(v[1].abs()).max(v[2].abs()))
                    .fold(0.0f64, f64::max),
                self.p.data.iter().cloned().fold(0.0f64, |a, b| a.max(b.abs()))
            );
        }
        // ---- 结果稳定性早停（dP 稳定判据）----
        // 只换停车判据，不动物理：离散格式/边界条件/松弛系数/线性容差一律不动。
        // 判据（参数写死，见 DpStopConfig）：每 20 步采样 dP → 最近 5 个采样的均值为
        // dP_ref → 5 样本全部落在 |dP−dP_ref|/|dP_ref| < 0.2% 带内 + 已跑过 100 步 +
        // 最近采样全局连续性 < 1e-2 → 连续 2 轮满足即停。与 residualControl 并存，先到先停。
        //
        // 附加守卫（**只阻止误停，不放宽任何参数**）：入口压力必须不是 fixedValue。
        // Run-B 等压模式入口 p 为 fixedValue 80、出口 fixedValue 0 → dP 恒等于 96 Pa
        // （纯 BC 常数，与流场无关），判据在此模式下没有信息量，会在 120 步无条件误停。
        let dp_cfg = DpStopConfig::default();
        let dp_inlets: Vec<usize> = self
            .patches
            .iter()
            .enumerate()
            .filter(|(_, p)| p.name.starts_with("inlet"))
            .map(|(i, _)| i)
            .collect();
        let dp_outlet = self.patches.iter().position(|p| p.name == "outlet");
        let dp_inlet_fixed = dp_inlets.iter().any(|&i| self.patches[i].pres_fixed);
        // 判据模式（纯函数）：决定是否评估 + 横幅文案；关闭/不适用时横幅只给原因、不罗列参数
        let dp_mode = dp_stop_mode(
            self.dp_stop,
            std::env::var("FLOWSCOPE_DP_STOP").as_deref() == Ok("0"),
            dp_inlet_fixed,
            dp_inlets.len(),
            dp_outlet.is_some(),
        );
        let dp_enabled = dp_mode == DpStopMode::Enabled;
        let mut dp_samples: VecDeque<f64> = VecDeque::with_capacity(dp_cfg.window);
        let mut dp_confirm = 0usize;
        if verbose {
            println!("stop criterion : {}", dp_stop_banner(dp_mode, &dp_cfg));
        }
        if verbose {
            println!(
                "== FlowScope SIMPLE：{} | cells {} | faces {} (internal {}) | nu {:.4e} | maxIter {} ==",
                self.cfg.run,
                self.mesh.n_cells(),
                self.mesh.n_faces(),
                self.mesh.n_internal,
                nu,
                max_iter
            );
            println!("relax p {} / U {} | residualControl p {} U {} | linear p({}, {}) U({}, {})",
                alpha_p, alpha_u, self.cfg.params.residual_p, self.cfg.params.residual_u,
                self.cfg.params.p_tol, self.cfg.params.p_reltol,
                self.cfg.params.u_tol, self.cfg.params.u_reltol);
            println!(
                "linear preconditioner : {}（FLOWSCOPE_PRECOND=sgs|ic0|mic0）{}{}",
                precond.tag(),
                if precond == PrecondKind::Mic0 {
                    format!(" ω {:.3}", crate::linalg::mic_omega())
                } else {
                    String::new()
                },
                if precond.is_ic_like() && two_level_enabled() {
                    " + 聚合两层（FLOWSCOPE_TWO_LEVEL=1，常数模 deflation 自动关闭）"
                } else if precond.is_ic_like() && crate::linalg::deflate_enabled() {
                    " + 常数模 deflation"
                } else {
                    ""
                }
            );
        }
        for it in 1..=max_iter {
            self.iter = it;
            let n_cells = self.mesh.n_cells();
            // ⓪ Run-B 启动压力斜坡（默认关；见 apply_runb_p_ramp）
            self.apply_runb_p_ramp(it);
            self.update_bcs();
            self.grad_p = grad_scalar(&self.mesh, &self.p);
            // ① grad(U)（当前场）
            self.grad_u = grad_vector(&self.mesh, &self.u);
            // ② 组装松弛后动量矩阵 + CSR
            let m = assemble_momentum(
                &self.mesh,
                nu,
                alpha_u,
                &self.patches,
                &self.phi,
                &self.u,
                &self.grad_u,
                lu_dev,
            );
            let csr = m.to_csr(&self.mesh);
            // ③ 动量预测器：解松弛后动量方程 A'·U* = b' − V·∇p_old
            //    （OpenFOAM simpleFoam 的 solve(UEqn == -fvc::grad(p)) 同构；
            //     必须隐式求解——高 cell-Péclet 下纯 Jacobi 显式更新会发散）
            let mut ustar = self.u.clone();
            let mut mres = [0.0f64; 3];
            for comp in 0..3 {
                let mut b_eff = Vec::with_capacity(n_cells);
                for i in 0..n_cells {
                    b_eff.push(m.source[i][comp] - self.mesh.cell_vol[i] * self.grad_p[i][comp]);
                }
                let mut xs: Vec<f64> = self.u.data.iter().map(|v| v[comp]).collect();
                let info = sgs_solve(
                    &csr,
                    &b_eff,
                    &mut xs,
                    self.cfg.params.u_tol,
                    self.cfg.params.u_reltol,
                    50,
                );
                mres[comp] = info.init_res;
                if std::env::var("FLOWSCOPE_VERBOSE_ALL").is_ok() {
                    println!("  Usolve comp {}: init {:.3e} final {:.3e} sweeps {} conv {}", comp, info.init_res, info.final_res, info.iters, info.converged);
                }
                for i in 0..n_cells {
                    ustar.data[i][comp] = xs[i];
                }
            }
            self.u = ustar;
            self.update_bcs();
            // ④ HbyA = H/diag'（H = b' − Σ_nb A'_nb·U*_nb，U* 为动量方程解）
            let mut au = vec![[0.0f64; 3]; n_cells];
            for comp in 0..3 {
                let x: Vec<f64> = self.u.data.iter().map(|v| v[comp]).collect();
                let mut ax = vec![0.0f64; n_cells];
                csr.matvec(&x, &mut ax);
                for i in 0..n_cells {
                    au[i][comp] = ax[i];
                }
            }
            for i in 0..n_cells {
                let d = csr.diag_value(i);
                for comp in 0..3 {
                    self.hbya.data[i][comp] =
                        (m.source[i][comp] - au[i][comp] + d * self.u.data[i][comp]) / d;
                }
            }
            // ⑤ rAU = V/A'
            for c in 0..self.mesh.n_cells() {
                self.rau[c] = self.mesh.cell_vol[c] / csr.diag_value(c).max(1e-300);
            }
            // 诊断（FLOWSCOPE_TRACE_CELL=<id>）：逐迭代打印指定单元的动量/压力耦合量
            if let Ok(tc) = std::env::var("FLOWSCOPE_TRACE_CELL") {
                if let Ok(c) = tc.parse::<usize>() {
                    if c < n_cells {
                        let mut off = 0.0f64;
                        for f in self.mesh.cell_face_iter(c) {
                            if f < self.mesh.n_internal {
                                let nb = self.mesh.other_cell(f, c);
                                let w = if self.mesh.is_owner(f, c) { m.upper[f] } else { m.lower[f] };
                                off += w * self.u.data[nb][2];
                            }
                        }
                        println!(
                            "[trace {}] it {} U=({:.4},{:.4},{:.4}) HbyA=({:.4},{:.4},{:.4}) rAU {:.3e} diag {:.3e} b_z {:.3e} offmat_z {:.3e} gradp=({:.3e},{:.3e},{:.3e}) p {:.4}",
                            c, it,
                            self.u.data[c][0], self.u.data[c][1], self.u.data[c][2],
                            self.hbya.data[c][0], self.hbya.data[c][1], self.hbya.data[c][2],
                            self.rau[c], csr.diag_value(c), m.source[c][2], off,
                            self.grad_p[c][0], self.grad_p[c][1], self.grad_p[c][2], self.p.data[c]
                        );
                        let mut fl = String::new();
                        for f in self.mesh.cell_face_iter(c) {
                            let out = self.mesh.face_sf_out(f, c);
                            let q = self.phi[f] * if self.mesh.is_owner(f, c) { 1.0 } else { -1.0 };
                            fl.push_str(&format!("  f{} out={} phi_out={:.3e} |Sf| {:.3e} U_nb={:.3}\n",
                                f, if f < self.mesh.n_internal { "I" } else { "B" }, q, self.mesh.face_mag[f],
                                if f < self.mesh.n_internal { self.u.data[self.mesh.other_cell(f, c)][2] } else { self.u.bnd[f - self.mesh.n_internal][2] }));
                            let _ = out;
                        }
                        if std::env::var("FLOWSCOPE_TRACE_FACES").is_ok() {
                            print!("{}", fl);
                        }
                    }
                }
            }
            // ⑥ phiHbyA
            self.update_hbya_bnd();
            let mut phi_hbya = hbya_flux(&self.mesh, &self.hbya);
            // ⑥b 全局通量平衡（adjustPhi）：出口通量补足入口，压力方程只处理局部失衡
            adjust_phi(&self.mesh, &self.patches, &mut phi_hbya);
            // 诊断（FLOWSCOPE_DIAG_PATCHFLUX）：adjustPhi 前后的 patch 通量，
            // 用于量化"出口通量有多大比例来自 adjustPhi"（D-5 归因）
            if std::env::var("FLOWSCOPE_DIAG_PATCHFLUX").is_ok() {
                let mut line = format!("  [phiHbyA it {it}]");
                for (i, p) in self.patches.iter().enumerate() {
                    let q = crate::metrics::patch_flux_sum(&self.mesh, &phi_hbya, i);
                    line.push_str(&format!(" {}={:.4e}", p.name, q));
                }
                let mut uflux = 0.0f64;
                for f in 0..self.mesh.n_faces() {
                    let uf = self.u.face_value(&self.mesh, f);
                    uflux += uf[0] * self.mesh.face_sf[f][0]
                        + uf[1] * self.mesh.face_sf[f][1]
                        + uf[2] * self.mesh.face_sf[f][2];
                }
                line.push_str(&format!("  | sum(U*.Sf) over all faces = {uflux:+.4e}"));
                println!("{}", line);
            }
            if std::env::var("FLOWSCOPE_DIAG_DIV").is_ok() {
                let mut tops: Vec<(f64, usize)> = Vec::new();
                let mut sumabs = 0.0f64;
                for c in 0..n_cells {
                    let mut s = 0.0f64;
                    for f in self.mesh.cell_face_iter(c) {
                        s += if self.mesh.is_owner(f, c) { phi_hbya[f] } else { -phi_hbya[f] };
                    }
                    sumabs += s.abs();
                    tops.push((s.abs(), c));
                }
                tops.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap());
                println!("  [div] mean|div phiHbyA| {:.3e}  top:", sumabs / n_cells as f64);
                for (v, c) in tops.iter().take(5) {
                    println!("     cell {} |div| {:.3e} rAU {:.3e} p {:.3e}", c, v, self.rau[*c], self.p.data[*c]);
                }
            }
            // ⑦ 压力方程
            let pm = assemble_pressure(&self.mesh, &self.patches, &self.rau, &phi_hbya, &self.bnd_pf);
            let pcsr = pm.to_csr(&self.mesh);
            let p_old = self.p.data.clone();
            // §3.2 SPD/M-矩阵预检（首个压力矩阵，一次性；不做对称性空检查）
            if it == 1 && std::env::var("FLOWSCOPE_DIAG_PCSR").is_ok() {
                let c = matrix_precheck(&pcsr);
                println!(
                    "[spd-precheck] n {} nnz {} | diag [{:.3e}, {:.3e}] | max off-diag {:.3e}（正号 {} 个）| min row-sum {:.3e}（rel {:.3e}）",
                    c.n, c.nnz, c.min_diag, c.max_diag, c.max_offdiag, c.n_pos_offdiag,
                    c.min_row_sum, c.min_row_sum_rel
                );
                if let Ok(path) = std::env::var("FLOWSCOPE_DUMP_PCSR") {
                    match dump_csr(&pcsr, &path) {
                        Ok(()) => println!("[spd-precheck] CSR 已导出到 {path}"),
                        Err(e) => println!("[spd-precheck] CSR 导出失败：{e}"),
                    }
                    if let Ok(rhs_path) = std::env::var("FLOWSCOPE_DUMP_PB") {
                        match crate::linalg::dump_vec(&pm.source, &rhs_path) {
                            Ok(()) => println!("[spd-precheck] RHS 已导出到 {rhs_path}"),
                            Err(e) => println!("[spd-precheck] RHS 导出失败：{e}"),
                        }
                    }
                }
            }
            // §2.A 冻结矩阵等价性：同一 A/b/初值下 SGS 与 IC(0) 各解到 1e-10 后比较解
            if it <= 5 && std::env::var("FLOWSCOPE_PCG_AB").is_ok() {
                pcg_equiv_check(
                    &pcsr,
                    &pm.source,
                    &p_old,
                    p_cap.max(20000),
                    &format!("case it{it}"),
                );
            }
            let pinfo = pcg(
                &pcsr,
                &pm.source,
                &mut self.p.data,
                self.cfg.params.p_tol,
                self.cfg.params.p_reltol,
                p_cap,
                precond,
            );
            self.lin_p.push(pinfo);
            // 刷新零梯度压力边界面值（Rhie-Chow 边界修正归零）
            self.refresh_p_bnd();
            // ⑧ phi = phiHbyA − pEqn.flux()（用未松弛的完整压力解）
            self.phi = rhie_chow_phi(&self.mesh, &self.rau, &phi_hbya, &self.p);
            // ⑨ p 欠松弛
            for c in 0..self.mesh.n_cells() {
                self.p.data[c] = p_old[c] + alpha_p * (self.p.data[c] - p_old[c]);
            }
            // 松弛后再刷一次零梯度边界面值：保证 grad(p) 用的面值与松弛后的
            // 单元值一致（否则零梯度边界附近出现自相矛盾的梯度 → 虚拟大速度）
            self.refresh_p_bnd();
            // ⑩ U 校正 + BC 刷新
            self.grad_p = grad_scalar(&self.mesh, &self.p);
            for c in 0..self.mesh.n_cells() {
                let r = self.rau[c];
                self.u.data[c] = [
                    self.hbya.data[c][0] - r * self.grad_p[c][0],
                    self.hbya.data[c][1] - r * self.grad_p[c][1],
                    self.hbya.data[c][2] - r * self.grad_p[c][2],
                ];
            }
            self.update_bcs();
            // ⑪ 残差记录
            let (cl, cg) = self.continuity_errs();
            self.records.push(IterRecord {
                iter: it,
                ux: mres[0],
                uy: mres[1],
                uz: mres[2],
                p_res: pinfo.init_res,
                cont_local: cl,
                cont_global: cg,
            });
            if verbose && (it <= 3 || it % 100 == 0 || it == max_iter || std::env::var("FLOWSCOPE_VERBOSE_ALL").is_ok()) {
                let umax = self
                    .u
                    .data
                    .iter()
                    .map(|v| v[0].abs().max(v[1].abs()).max(v[2].abs()))
                    .fold(0.0f64, f64::max);
                let pmax = self.p.data.iter().cloned().fold(0.0f64, |a, b| a.max(b.abs()));
                let phimax = self.phi.iter().cloned().fold(0.0f64, |a, b| a.max(b.abs()));
                let hmax = self
                    .hbya
                    .data
                    .iter()
                    .map(|v| v[0].abs().max(v[1].abs()).max(v[2].abs()))
                    .fold(0.0f64, f64::max);
                println!(
                    "Time = {it}  Ux {:.3e} Uy {:.3e} Uz {:.3e}  p {:.3e}  cont local {:.3e} global {:.3e}  (pLin {} it, final {:.3e}, conv {}, brk {})",
                    mres[0], mres[1], mres[2], pinfo.init_res, cl, cg,
                    pinfo.iters, pinfo.final_res, pinfo.converged, pinfo.breakdown
                );
                println!(
                    "        |U|max {:.4e}  |p|max {:.4e}  |phi|max {:.4e}  |HbyA|max {:.4e}",
                    umax, pmax, phimax, hmax
                );
                // argmax 单元细查
                let mut bi = 0usize;
                let mut bv = 0.0f64;
                for (i, v) in self.u.data.iter().enumerate() {
                    let m = v[0].abs().max(v[1].abs()).max(v[2].abs());
                    if m > bv {
                        bv = m;
                        bi = i;
                    }
                }
                println!(
                    "        argmax cell {}: U = ({:.4e}, {:.4e}, {:.4e}) HbyA = ({:.4e}, {:.4e}, {:.4e}) rAU = {:.4e} gradp = ({:.4e}, {:.4e}, {:.4e}) p = {:.4e}",
                    bi,
                    self.u.data[bi][0], self.u.data[bi][1], self.u.data[bi][2],
                    self.hbya.data[bi][0], self.hbya.data[bi][1], self.hbya.data[bi][2],
                    self.rau[bi],
                    self.grad_p[bi][0], self.grad_p[bi][1], self.grad_p[bi][2],
                    self.p.data[bi]
                );
                // 过程量：契约 §11 口径 dP（Pa）——L1 对拍必须能看它随迭代的漂移
                let mut num = 0.0f64;
                let mut den = 0usize;
                for p in &self.patches {
                    if p.name.starts_with("inlet") {
                        for f in p.start..p.start + p.n_faces {
                            num += self.p.bnd[f - self.mesh.n_internal];
                        }
                        den += p.n_faces;
                    }
                }
                let p_in = if den > 0 { num / den as f64 } else { f64::NAN };
                println!("        dP(kin) {:.6e}  dP(Pa) {:.6e}", p_in, RHO_AIR * p_in);
            }
            // ⑪b dP 稳定性采样与早停判据（每 sample_every 步一次）
            if dp_enabled && it % dp_cfg.sample_every == 0 {
                let dp = dp_pa(&self.mesh, &self.p, &dp_inlets, dp_outlet.unwrap());
                dp_samples.push_back(dp);
                while dp_samples.len() > dp_cfg.window {
                    dp_samples.pop_front();
                }
                if verbose {
                    // 任务书要求：dP 采样从原来的 ~80/100 步加密到每 20 步并打印
                    println!(
                        "[dP-stop] iter {it}  dP = {dp:.6e} Pa  (samples {}/{})",
                        dp_samples.len(),
                        dp_cfg.window
                    );
                }
                if dp_samples.len() >= dp_cfg.window {
                    // 判定全部下沉到纯函数 dp_stop_decide：循环只做「取值 → 打印 → 赋值 → break」
                    let v = dp_stop_decide(dp_samples.make_contiguous(), it, cg, &dp_cfg, dp_confirm);
                    let band_pct = v.band_pct;
                    self.dp_band_pct = band_pct;
                    dp_confirm = v.confirm;
                    if verbose {
                        println!(
                            "[dP-stop] iter {it}  dP = {dp:.6e} Pa  dP_ref = {:.6e} Pa  band = {band_pct:.4}%  cont_global {cg:.3e}  confirm {}/{}{}",
                            v.dp_ref,
                            dp_confirm,
                            dp_cfg.confirm_rounds,
                            if v.stable { "  (stable)" } else { "" }
                        );
                    }
                    if v.stop {
                        self.converged = true;
                        self.stop_reason = "dp_stable".to_string();
                        self.stop_iter = it;
                        self.stop_detail = format!(
                            "dP 稳定早停：iter {it}，dP = {dp:.6} Pa，band = {band_pct:.4}%（{:.1}% 带 / {} 样本 / 最少 {} 步；residualControl 未双达标）",
                            dp_cfg.band_rel * 100.0,
                            dp_cfg.window,
                            dp_cfg.min_iter
                        );
                        println!(
                            "STOP: dP stable (<0.2% over 5 samples) at iter {it}, dP = {dp:.6} Pa, band = {band_pct:.4}%"
                        );
                        break;
                    }
                }
            }
            // ⑫ residualControl 双达标 → 早停
            if pinfo.init_res < self.cfg.params.residual_p
                && mres[0] < self.cfg.params.residual_u
                && mres[1] < self.cfg.params.residual_u
                && mres[2] < self.cfg.params.residual_u
            {
                self.converged = true;
                self.stop_reason = "residual".to_string();
                self.stop_iter = it;
                self.stop_detail = format!(
                    "SIMPLE solution converged：iter {it}，p 初残差 {:.3e} < {}，U 初残差 {:.3e}/{:.3e}/{:.3e} < {}（residualControl 双口径达标）",
                    pinfo.init_res, self.cfg.params.residual_p,
                    mres[0], mres[1], mres[2], self.cfg.params.residual_u
                );
                if verbose {
                    println!("{}", self.stop_detail);
                }
                break;
            }
            // ⑬ 周期写盘（controlDict writeInterval）
            if let Some(dir) = out_dir {
                if self.cfg.params.write_interval > 0 && it % self.cfg.params.write_interval == 0 {
                    self.write_snapshot(dir, it)?;
                }
            }
        }
        // 收尾写出：residualControl 双达标提前 break 时会跳过循环内写出（W6 v3 门实证：
        // case-026 在 ic0+deflation 下约 100 步提前收敛，write_interval=1500 时末态从未落盘），
        // 若末迭代未写过则补写一次——早停也是完成态，fields 必须存在。
        if let Some(dir) = out_dir {
            if self.cfg.params.write_interval > 0
                && self.iter % self.cfg.params.write_interval != 0
            {
                self.write_snapshot(dir, self.iter)?;
            }
        }
        if !self.converged {
            self.stop_reason = "endtime".to_string();
            self.stop_iter = self.iter;
            self.stop_detail = format!(
                "endTime 硬停：跑满 {} 步，residualControl 未双达标（末步 p 初残差 {:.3e}，U {:.3e}/{:.3e}/{:.3e}）",
                max_iter,
                self.records.last().map(|r| r.p_res).unwrap_or(f64::NAN),
                self.records.last().map(|r| r.ux).unwrap_or(f64::NAN),
                self.records.last().map(|r| r.uy).unwrap_or(f64::NAN),
                self.records.last().map(|r| r.uz).unwrap_or(f64::NAN)
            );
        }
        // W6 统计：pLin 全量序列 + 中位数 + 收敛/失稳/cap 命中计数 + IC(0) 开销
        if verbose && !self.lin_p.is_empty() {
            let mut iters: Vec<usize> = self.lin_p.iter().map(|i| i.iters).collect();
            iters.sort_unstable();
            let n = iters.len();
            let med = if n % 2 == 1 {
                iters[n / 2] as f64
            } else {
                0.5 * (iters[n / 2 - 1] + iters[n / 2]) as f64
            };
            let mean = iters.iter().sum::<usize>() as f64 / n as f64;
            let nconv = self.lin_p.iter().filter(|i| i.converged).count();
            let nbrk = self.lin_p.iter().filter(|i| i.breakdown).count();
            let cap = self.lin_p.iter().filter(|i| i.iters >= p_cap).count();
            println!(
                "[pLin-stats] precond {} n {} min {} median {:.1} mean {:.1} max {} | converged {}/{} breakdown {} cap_hits {} | two_level {}",
                precond.tag(),
                n,
                iters[0],
                med,
                mean,
                iters[n - 1],
                nconv,
                n,
                nbrk,
                cap,
                if two_level_enabled() { 1 } else { 0 }
            );
            if std::env::var("FLOWSCOPE_VERBOSE_ALL").is_ok() {
                let seq: Vec<String> = self.lin_p.iter().map(|i| i.iters.to_string()).collect();
                println!("[pLin-seq] {}", seq.join(" "));
            }
            let st = ic0_stats();
            if st.factors > 0 || st.failures > 0 {
                println!(
                    "[ic0-stats] factors {} shift_restarts {} failures {} factor_secs {:.3} mem_bytes {} ({:.2} MB)",
                    st.factors,
                    st.shift_restarts,
                    st.failures,
                    st.factor_secs,
                    st.mem_bytes,
                    st.mem_bytes as f64 / (1024.0 * 1024.0)
                );
            }
            // W7-M2：两层构建/应用耗时分解（验收要求「构建占比 ≤20%」可核算）
            let tst = two_level_stats();
            if tst.builds > 0 || tst.degraded > 0 {
                let build_secs = tst.agg_secs + tst.galerkin_secs + tst.coarse_factor_secs;
                println!(
                    "[two-level-stats] builds {} dirichlet_cells {} coarse_size {} agg_secs {:.3} galerkin_secs {:.3} coarse_factor_secs {:.3} coarse_apply_secs {:.3} coarse_iters {} degraded {} build_total_secs {:.3}",
                    tst.builds,
                    tst.dirichlet_cells,
                    tst.coarse_size,
                    tst.agg_secs,
                    tst.galerkin_secs,
                    tst.coarse_factor_secs,
                    tst.coarse_apply_secs,
                    tst.coarse_iters,
                    tst.degraded,
                    build_secs
                );
            }
        }
        Ok(())
    }

    /// 周期写出：VTK 快照 + controlDict 三个 flux 函数对象（phi 求和）
    pub fn write_snapshot(&self, dir: &Path, it: usize) -> Result<(), String> {
        std::fs::create_dir_all(dir)
            .map_err(|e| format!("创建 {} 失败: {e}", dir.display()))?;
        let path = dir.join(format!("fields_{it}.vtk"));
        vtk_write(&path, &self.mesh, &self.u, &self.p)?;
        for (i, p) in self.patches.iter().enumerate() {
            let q = patch_flux_sum(&self.mesh, &self.phi, i);
            println!(
                "Time = {it}  flux({:<8}) sum(phi) = {:.6e}  (patch {} faces)",
                p.name, q, p.n_faces
            );
        }
        Ok(())
    }

    /// 契约 §11 口径的指标汇总（L1 对拍用）
    pub fn contract_metrics(&self) -> String {
        let mut s = String::new();
        s.push_str(&format!("run mode            : {}\n", self.cfg.run));
        s.push_str(&format!("iterations          : {}\n", self.iter));
        s.push_str(&format!("stop reason         : {}\n", self.stop_detail));
        // 机器可读停车三元组（新增；上面那行人读文本逐字节不变）
        s.push_str(&format!("stop_reason         : {}\n", self.stop_reason));
        s.push_str(&format!("stop_iter           : {}\n", self.stop_iter));
        // dp_band_pct 单位 = **百分数数值**（0.1896 表示 0.19%）；判据未评估/不适用时为 NaN
        // （下游 code/pipeline/solver_backend.py 把 NaN 归一成 None 再写 metrics.json）
        s.push_str(&format!("dp_band_pct         : {:.6}\n", self.dp_band_pct));
        for (i, p) in self.patches.iter().enumerate() {
            let q = patch_flux_sum(&self.mesh, &self.phi, i);
            let area = patch_area(&self.mesh, i);
            s.push_str(&format!(
                "patch {:<8} : sum(phi) = {:.6e} m3/s   A = {:.6e} m2   p_mean(kin) = {:.6e}\n",
                p.name,
                q,
                area,
                patch_face_mean_p(&self.mesh, &self.p, i)
            ));
        }
        // dP（Pa）
        let inlets: Vec<usize> = self
            .patches
            .iter()
            .enumerate()
            .filter(|(_, p)| p.name.starts_with("inlet"))
            .map(|(i, _)| i)
            .collect();
        let outlet = self.patches.iter().position(|p| p.name == "outlet");
        if !inlets.is_empty() {
            if let Some(o) = outlet {
                let dp = dp_pa(&self.mesh, &self.p, &inlets, o);
                s.push_str(&format!("dP (rho*p_in - p_out) = {:.6} Pa\n", dp));
                let sp = flow_split(&self.mesh, &self.phi, &inlets);
                for (k, &i) in inlets.iter().enumerate() {
                    s.push_str(&format!(
                        "split {:<8} : {:.4}（流量占比）\n",
                        self.patches[i].name, sp[k]
                    ));
                }
            }
        }
        // WSS（契约 §11 一阶体素估计）
        if let Some(w) = self.patches.iter().position(|p| p.name == "walls") {
            let (wss, wst) = wall_shear_stress_ex(&self.mesh, &self.u, self.cfg.mu, w);
            let mean = wss.iter().sum::<f64>() / wss.len().max(1) as f64;
            let max = wss.iter().cloned().fold(0.0f64, f64::max);
            s.push_str(&format!(
                "WSS (2nd-order 3pt): mean {:.6e} Pa, max {:.6e} Pa ({} wall faces, {} 1st-order fallback)\n",
                mean, max, wst.total_faces, wst.fallback_faces
            ));
        }
        if let Some(r) = self.records.last() {
            s.push_str(&format!(
                "final residuals     : Ux {:.3e} Uy {:.3e} Uz {:.3e} p {:.3e}\n",
                r.ux, r.uy, r.uz, r.p_res
            ));
            s.push_str(&format!(
                "continuity (1/s)    : local {:.3e} global {:.3e}\n",
                r.cont_local, r.cont_global
            ));
        }
        s
    }
}

/// 结构化盒网格（6 patch：xMin/xMax/yMin/yMax/zMin/zMax；内部面前置）
/// 节点序按右手规则保证：内部面法向 owner→neighbour，边界面法向朝域外。
pub fn build_box_mesh(nx: usize, ny: usize, nz: usize, dx: f64, dy: f64, dz: f64) -> Mesh {
    assert!(nx >= 1 && ny >= 1 && nz >= 1, "盒网格维度必须 >= 1");
    let npx = nx + 1;
    let npy = ny + 1;
    let npz = nz + 1;
    let pid = |i: usize, j: usize, k: usize| (i + j * npx + k * npx * npy) as u32;
    let cid = |i: usize, j: usize, k: usize| (i + j * nx + k * nx * ny) as u32;
    let mut points: Vec<[f64; 3]> = Vec::with_capacity(npx * npy * npz);
    for k in 0..npz {
        for j in 0..npy {
            for i in 0..npx {
                points.push([i as f64 * dx, j as f64 * dy, k as f64 * dz]);
            }
        }
    }
    struct Tmp {
        nodes: [u32; 4],
        owner: u32,
        neigh: Option<u32>,
        patch: Option<usize>,
    }
    let mut tmp: Vec<Tmp> = Vec::new();
    for k in 0..nz {
        for j in 0..ny {
            for i in 0..nx {
                let c = cid(i, j, k);
                // +x 面（法向 +x）
                let f = [
                    pid(i + 1, j, k),
                    pid(i + 1, j + 1, k),
                    pid(i + 1, j + 1, k + 1),
                    pid(i + 1, j, k + 1),
                ];
                if i + 1 < nx {
                    tmp.push(Tmp {
                        nodes: f,
                        owner: c,
                        neigh: Some(cid(i + 1, j, k)),
                        patch: None,
                    });
                } else {
                    tmp.push(Tmp {
                        nodes: f,
                        owner: c,
                        neigh: None,
                        patch: Some(1), // xMax
                    });
                }
                // −x 面（法向 −x，仅边界面）
                if i == 0 {
                    tmp.push(Tmp {
                        nodes: [
                            pid(i, j, k + 1),
                            pid(i, j + 1, k + 1),
                            pid(i, j + 1, k),
                            pid(i, j, k),
                        ],
                        owner: c,
                        neigh: None,
                        patch: Some(0), // xMin
                    });
                }
                // +y 面（法向 +y）
                let f = [
                    pid(i, j + 1, k + 1),
                    pid(i + 1, j + 1, k + 1),
                    pid(i + 1, j + 1, k),
                    pid(i, j + 1, k),
                ];
                if j + 1 < ny {
                    tmp.push(Tmp {
                        nodes: f,
                        owner: c,
                        neigh: Some(cid(i, j + 1, k)),
                        patch: None,
                    });
                } else {
                    tmp.push(Tmp {
                        nodes: f,
                        owner: c,
                        neigh: None,
                        patch: Some(3), // yMax
                    });
                }
                if j == 0 {
                    tmp.push(Tmp {
                        nodes: [
                            pid(i, j, k),
                            pid(i + 1, j, k),
                            pid(i + 1, j, k + 1),
                            pid(i, j, k + 1),
                        ],
                        owner: c,
                        neigh: None,
                        patch: Some(2), // yMin
                    });
                }
                // +z 面（法向 +z）
                let f = [
                    pid(i, j, k + 1),
                    pid(i + 1, j, k + 1),
                    pid(i + 1, j + 1, k + 1),
                    pid(i, j + 1, k + 1),
                ];
                if k + 1 < nz {
                    tmp.push(Tmp {
                        nodes: f,
                        owner: c,
                        neigh: Some(cid(i, j, k + 1)),
                        patch: None,
                    });
                } else {
                    tmp.push(Tmp {
                        nodes: f,
                        owner: c,
                        neigh: None,
                        patch: Some(5), // zMax
                    });
                }
                if k == 0 {
                    tmp.push(Tmp {
                        nodes: [
                            pid(i, j + 1, k),
                            pid(i + 1, j + 1, k),
                            pid(i + 1, j, k),
                            pid(i, j, k),
                        ],
                        owner: c,
                        neigh: None,
                        patch: Some(4), // zMin
                    });
                }
            }
        }
    }
    // 分区：内部面（patch=None）前置，其后按 patch 0..5（稳定排序保生成序）
    let n_internal = tmp.iter().filter(|t| t.patch.is_none()).count();
    let mut order: Vec<usize> = (0..tmp.len()).collect();
    order.sort_by_key(|&idx| match tmp[idx].patch {
        None => 0usize,
        Some(p) => 1 + p,
    });
    let mut face_nodes: Vec<u32> = Vec::with_capacity(tmp.len() * 4);
    let mut face_start: Vec<u32> = Vec::with_capacity(tmp.len() + 1);
    let mut face_owner: Vec<u32> = Vec::with_capacity(tmp.len());
    let mut face_neigh: Vec<u32> = Vec::with_capacity(n_internal);
    face_start.push(0);
    let mut patch_counts = [0usize; 6];
    for &idx in &order {
        let t = &tmp[idx];
        face_nodes.extend_from_slice(&t.nodes);
        face_start.push(face_nodes.len() as u32);
        face_owner.push(t.owner);
        match t.neigh {
            Some(nb) => face_neigh.push(nb),
            None => patch_counts[t.patch.unwrap()] += 1,
        }
    }
    let names = ["xMin", "xMax", "yMin", "yMax", "zMin", "zMax"];
    let mut patch_start = [0usize; 6];
    let mut acc = n_internal;
    for p in 0..6 {
        patch_start[p] = acc;
        acc += patch_counts[p];
    }
    let patches: Vec<Patch> = (0..6)
        .map(|p| Patch {
            name: names[p].to_string(),
            ptype: "patch".to_string(),
            start: patch_start[p],
            n_faces: patch_counts[p],
        })
        .collect();
    Mesh::build(points, face_nodes, face_start, face_owner, face_neigh, patches)
        .expect("盒网格构建失败")
}

/// Poiseuille 门结果
#[derive(Debug, Clone)]
pub struct PoiseuilleResult {
    pub n_cells: usize,
    pub nx: usize,
    pub ny: usize,
    pub nz: usize,
    pub u_mean: f64,
    pub u_center_num: f64,
    pub u_center_exact: f64,
    pub u_center_rel_err: f64,
    pub dpdx_num: f64,
    pub dpdx_exact: f64,
    pub dpdx_rel_err: f64,
    pub dpdx_num_pa: f64,
    pub dpdx_exact_pa: f64,
    pub iterations: usize,
    pub converged: bool,
    pub stop_reason: String,
    pub gate_pass: bool,
    // W8：WSS 解析门（二阶三点重构，patch 面积加权均值 vs 6*mu*U/h）
    pub wss_mean_pa: f64,
    pub wss_exact_pa: f64,
    pub wss_rel_err: f64,
    pub wss_fallback_faces: usize,
    pub wss_total_faces: usize,
    pub wss_skip_faces: usize,
}

/// 截面体权平均压力（单元心 x 在 [(i+0.5−0.5)dx, (i+0.5+0.5)dx) 的全部单元）
fn cross_section_mean_p(mesh: &Mesh, p: &VolScalar, i_station: usize, nx: usize) -> f64 {
    let mut num = 0.0f64;
    let mut den = 0.0f64;
    for c in 0..mesh.n_cells() {
        let idx = c % nx; // cid(i,j,k) = i + j*nx + k*nx*ny → i = c % nx
        if idx == i_station {
            num += p.data[c] * mesh.cell_vol[c];
            den += mesh.cell_vol[c];
        }
    }
    if den > 0.0 {
        num / den
    } else {
        0.0
    }
}

/// Poiseuille 验证算例的边界条件（盒网格 6 patch）
pub fn poiseuille_bcs(q: f64) -> BoundaryConditions {
    BoundaryConditions {
        patches: vec![
            (
                "xMin".to_string(),
                PatchBC {
                    velocity: VelocityBC::FlowRateInlet { q },
                    pressure: PressureBC::ZeroGradient,
                },
            ),
            (
                "xMax".to_string(),
                PatchBC {
                    velocity: VelocityBC::ZeroGradient,
                    pressure: PressureBC::FixedValue(0.0),
                },
            ),
            (
                "yMin".to_string(),
                PatchBC {
                    velocity: VelocityBC::FixedValue([0.0, 0.0, 0.0]),
                    pressure: PressureBC::ZeroGradient,
                },
            ),
            (
                "yMax".to_string(),
                PatchBC {
                    velocity: VelocityBC::FixedValue([0.0, 0.0, 0.0]),
                    pressure: PressureBC::ZeroGradient,
                },
            ),
            (
                "zMin".to_string(),
                PatchBC {
                    velocity: VelocityBC::ZeroGradient,
                    pressure: PressureBC::ZeroGradient,
                },
            ),
            (
                "zMax".to_string(),
                PatchBC {
                    velocity: VelocityBC::ZeroGradient,
                    pressure: PressureBC::ZeroGradient,
                },
            ),
        ],
    }
}

/// 运行 Poiseuille 解析验证（W4 硬门）：
/// 平面渠道层流（z 向零梯度 = 对称，等价 2D），中心速度误差 <1%、压降梯度误差 <2%。
pub fn run_poiseuille(
    nx: usize,
    ny: usize,
    nz: usize,
    h: f64,
    l: f64,
    w: f64,
    u_mean: f64,
    max_iter: usize,
    verbose: bool,
) -> Result<PoiseuilleResult, String> {
    run_poiseuille_adv(nx, ny, nz, h, l, w, u_mean, max_iter, verbose, 0.3, 0.7, true)
}

/// 带松弛/对流开关的 Poiseuille（诊断用）
#[allow(clippy::too_many_arguments)]
pub fn run_poiseuille_adv(
    nx: usize,
    ny: usize,
    nz: usize,
    h: f64,
    l: f64,
    w: f64,
    u_mean: f64,
    max_iter: usize,
    verbose: bool,
    alpha_p: f64,
    alpha_u: f64,
    lu_dev: bool,
) -> Result<PoiseuilleResult, String> {
    assert!(ny % 2 == 1, "ny 必须为奇数（保证中心单元精确位于 y=H/2）");
    let dx = l / nx as f64;
    let dy = h / ny as f64;
    let dz = w / nz as f64;
    let mesh = build_box_mesh(nx, ny, nz, dx, dy, dz);
    let q = u_mean * h * w;
    let bcs = poiseuille_bcs(q);
    let mut params = SolverParams::default();
    params.max_iter = max_iter;
    // 门要收敛到底：收紧 residualControl（如实记录，不影响归档口径复刻）
    params.residual_p = 1e-10;
    params.residual_u = 1e-10;
    params.alpha_p = alpha_p;
    params.alpha_u = alpha_u;
    params.lu_deviation = lu_dev;
    let cfg = CaseConfig::synthetic(bcs, params);
    let mut solver = SimpleSolver::new(mesh, cfg)?;
    solver.run(None, None, verbose)?;
    // 测量站：充分发展区（入口发展段之后）
    let ix = (nx * 3) / 4;
    let jc = ny / 2;
    let c = ix + jc * nx; // k = 0
    if std::env::var("FLOWSCOPE_DIAG_PROFILE").is_ok() {
        let dyv = h / ny as f64;
        let mut prof = String::new();
        for j in 0..ny {
            prof.push_str(&format!("{:.5} ", solver.u.data[ix + j * nx][0]));
        }
        println!("[profile] station {} u_x(j): {}", ix, prof);
        let mut qint = 0.0f64;
        for j in 0..ny {
            qint += solver.u.data[ix + j * nx][0] * dyv;
        }
        println!("[profile] integral u_x dy = {:.6e} (target u_mean*H = {:.6e})", qint, u_mean * h);
        for pt in &solver.patches {
            let mut s = 0.0f64;
            for f in pt.start..pt.start + pt.n_faces {
                s += solver.phi[f];
            }
            println!("[flux] {:<5} sum(phi) = {:.6e}  nfaces {}", pt.name, s, pt.n_faces);
        }
        println!("[profile] max |u| overall = {:.6e}", solver.u.data.iter().map(|v| v[0].abs().max(v[1].abs()).max(v[2].abs())).fold(0.0, f64::max));
        let rel: Vec<usize> = vec![0, 5, 10, 25, 50, 75, 90]
            .into_iter()
            .chain([1usize, 2, 3, 5, 10].iter().map(|k| nx.saturating_sub(*k)))
            .collect();
        for &i in &rel {
            let ii = i.min(nx - 1);
            println!(
                "[p] i {:3}  p_center {:+.6e}  p_mean {:+.6e}  u_center {:+.6e}",
                ii,
                solver.p.data[ii + jc * nx],
                cross_section_mean_p(&solver.mesh, &solver.p, ii, nx),
                solver.u.data[ii + jc * nx][0]
            );
        }
        if let Some(pi) = solver.patches.iter().position(|q| q.name == "xMax") {
            let q = &solver.patches[pi];
            let ni = solver.mesh.n_internal;
            let vals: Vec<f64> = (0..3)
                .map(|k| solver.p.bnd[q.start + k - ni])
                .collect();
            println!("[p] xMax face p (first 3): {:?}", vals);
        }
    }
    let u_center_num = solver.u.data[c][0].abs();
    let u_center_exact = 1.5 * u_mean;
    let u_center_rel_err = (u_center_num / u_center_exact - 1.0).abs();
    // 压降梯度：两个发展段截面
    let i1 = (nx / 2).max(1);
    let i2 = nx - 1;
    let p1 = cross_section_mean_p(&solver.mesh, &solver.p, i1, nx);
    let p2 = cross_section_mean_p(&solver.mesh, &solver.p, i2, nx);
    let dpdx_num = (p1 - p2) / ((i2 - i1) as f64 * dx); // 运动学 (m/s2)
    let dpdx_exact = 12.0 * NU_AIRWAY * u_mean / (h * h); // 运动学
    let dpdx_rel_err = (dpdx_num / dpdx_exact - 1.0).abs();
    // W8：WSS 解析门——yMin/yMax 两墙 patch 面积加权平均 vs 6*mu*U/h（平面 Poiseuille 解析）
    let mut wss_num = 0.0f64;
    let mut wss_den = 0.0f64;
    let mut wss_fb = 0usize;
    let mut wss_tot = 0usize;
    // 仅取下游已发展段（x > 0.5L）：FlowRateInlet 为均流 plug，入口发展段
    // （Re~27 → Le~0.05·Re·h ≈ 2.7%L）近壁速度虚高，整patch 平均会被污染；
    // 已发展段才对应解析解 6*mu*U/h。
    let x_dev = 0.5 * l;
    let mut wss_skip = 0usize; // 入口段面数（不参与均值，单独报）
    for pname in ["yMin", "yMax"] {
        if let Some(w) = solver.patches.iter().position(|q| q.name == pname) {
            let (wss, st) = wall_shear_stress_ex(&solver.mesh, &solver.u, MU_AIR, w);
            wss_fb += st.fallback_faces;
            wss_tot += st.total_faces;
            let pt = &solver.patches[w];
            for (k, f) in (pt.start..pt.start + pt.n_faces).enumerate() {
                if solver.mesh.face_cf[f][0] < x_dev {
                    wss_skip += 1;
                    continue;
                }
                wss_num += wss[k] * solver.mesh.face_mag[f];
                wss_den += solver.mesh.face_mag[f];
            }
        }
    }
    let wss_mean_pa = if wss_den > 0.0 { wss_num / wss_den } else { 0.0 };
    let wss_exact_pa = 6.0 * MU_AIR * u_mean / h;
    let wss_rel_err = if wss_exact_pa > 0.0 {
        (wss_mean_pa / wss_exact_pa - 1.0).abs()
    } else {
        0.0
    };
    let gate_pass = u_center_rel_err < 0.01 && dpdx_rel_err < 0.02 && wss_rel_err < 0.02;
    Ok(PoiseuilleResult {
        n_cells: solver.mesh.n_cells(),
        nx,
        ny,
        nz,
        u_mean,
        u_center_num,
        u_center_exact,
        u_center_rel_err,
        dpdx_num,
        dpdx_exact,
        wss_mean_pa,
        wss_exact_pa,
        wss_rel_err,
        wss_fallback_faces: wss_fb,
        wss_total_faces: wss_tot,
        wss_skip_faces: wss_skip,
        dpdx_rel_err,
        dpdx_num_pa: RHO_AIR * dpdx_num,
        dpdx_exact_pa: RHO_AIR * dpdx_exact,
        iterations: solver.iter,
        converged: solver.converged,
        stop_reason: solver.stop_detail.clone(),
        gate_pass,
    })
}

/// 便捷：mu 常量再导出（供报告引用）
pub const MU: f64 = MU_AIR;



#[cfg(test)]
mod analytic_gate_tests {
    //! 解析门**断言**（#44 / 根因 RC-2）。
    //!
    //! 背景：`run_poiseuille_adv` 早就在算三条解析式（中心速度 1.5U、压降梯度 12νU/h²、
    //! WSS 6μU/h）并打印误差，`gate_pass` 也只是**返回值**——21 条 `cargo test` 里
    //! 没有任何一条调用它。于是"求解器改动悄悄改变流动量"这件事，测试拦不住。
    //! 本模块把它变成会红的断言。
    //!
    //! 配置依据（指挥官 2026-10-25 实测，非沿用 S-1 二进制上的旧数）：
    //! nx=100 / ny=41 / max_iter=4000 是同时满足"秒级"与"三项全过"的组合；
    //! ny=21 系 WSS 恒 >2.4%，nx=40 时压降梯度 2.07% 贴线。
    //! 渠道 Re = U·H/ν = 0.02×0.02/1.8e-5 ≈ 22 ⇒ 发展段 ≈ 22 mm ≪ L=500 mm，
    //! 全段已发展，Poiseuille 前提成立（与 #42 裁定的 L=200 mm 基准是两回事）。
    use super::*;

    /// 解析式**接线**校验：极小网格、极少迭代，只钉"三条 exact 是否等于手算常数"。
    /// 毫秒级 ⇒ 每次 `cargo test` 都跑。防的是"有人改了公式/常数而没人发现"，
    /// 不防收敛退化（那由下面的 release 门负责）。
    #[test]
    fn t_poiseuille_analytic_formulas_wired_correctly() {
        let (h, u) = (0.02f64, 0.02f64);
        let r = run_poiseuille(8, 9, 1, h, 0.5, 0.02, u, 5, false).expect("run_poiseuille 失败");
        let uc = 1.5 * u;
        let dpdx = 12.0 * NU_AIRWAY * u / (h * h);
        let wss = 6.0 * MU_AIR * u / h;
        assert!((r.u_center_exact - uc).abs() < 1e-15, "中心速度式变了：{}", r.u_center_exact);
        assert!((r.dpdx_exact - dpdx).abs() < 1e-15, "压降梯度式变了：{}", r.dpdx_exact);
        assert!((r.wss_exact_pa - wss).abs() < 1e-18, "WSS 式变了：{}", r.wss_exact_pa);
        assert!(
            (MU_AIR - RHO_AIR * NU_AIRWAY).abs() < 1e-24,
            "μ_eff 与 ρ·ν 不再自洽（物性口径漂移）"
        );
    }

    /// 三条解析判据的**收敛性**门。发版前必跑：`cargo test --release`。
    /// ignore 的原因是被测代价，不是可靠性：release 36 s / debug 187 s（本机实测）。
    #[test]
    #[ignore = "需 --release（实测 36 s；debug 187 s）；发版前必跑 cargo test --release"]
    fn t_poiseuille_analytic_three_criteria_hold() {
        let r = run_poiseuille(100, 41, 1, 0.02, 0.5, 0.02, 0.02, 4000, false)
            .expect("run_poiseuille 返回 Err");
        // 先钉"解析式本身非退化"，否则误差判据可能因分母为 0 而空过
        assert!(r.u_center_exact > 0.0, "中心速度解析值退化");
        assert!(r.dpdx_exact > 0.0, "压降梯度解析值退化");
        assert!(r.wss_exact_pa > 0.0, "WSS 解析值退化");
        assert!(r.iterations > 0, "未迭代，误差无意义");
        // 三条与 gate 同阈值的硬断言
        assert!(r.u_center_rel_err < 0.01, "中心速度误差 {:.4}% 超 1%", r.u_center_rel_err * 100.0);
        assert!(r.dpdx_rel_err < 0.02, "压降梯度误差 {:.4}% 超 2%", r.dpdx_rel_err * 100.0);
        assert!(r.wss_rel_err < 0.02, "WSS 误差 {:.4}% 超 2%", r.wss_rel_err * 100.0);
        assert!(r.gate_pass, "gate_pass=false，但上面三条 individually 应全过");
    }
}

#[cfg(test)]
mod dp_stop_tests {
    //! dP 稳定性停车判据的**行为**测试（审计 [16][17] 整改）。
    //!
    //! 覆盖原则：
    //! - 判据参数一律从 `DpStopConfig::default()` 取，测试只钉「行为」不改判据；
    //!   把 `<` 改成 `<=`、confirm 不重置、删掉 min_iter 门，下面任一用例都会红。
    //! - 日志行格式与字段契约（stop_reason/stop_iter/dp_band_pct 的解析）由
    //!   `tests/test_dp_stop.py` 负责；本模块**不做源码字符串 grep**。
    use super::*;

    /// 带内样本：均值 1000，最大偏差 0.05 → band 0.005% ≪ 0.2%
    const IN_BAND: [f64; 5] = [1000.0, 1000.05, 999.95, 1000.02, 999.98];
    /// 带外样本：均值 1004，最大偏差 8 → band ≈ 0.80% > 0.2%
    const OUT_BAND: [f64; 5] = [1000.0, 1008.0, 1000.0, 1004.0, 1008.0];
    /// 恰好落在带边界：均值 1000，最大偏差 2 → band_rel == 0.002（等于门限，不满足严格 `>`）
    const AT_BAND_EDGE: [f64; 5] = [998.0, 1002.0, 1000.0, 1000.0, 1000.0];

    fn cfg() -> DpStopConfig {
        DpStopConfig::default()
    }

    /// T0：判据参数钉死（语义化断言，取代原先的源码字符串 grep）
    #[test]
    fn t0_criterion_params_pinned() {
        let c = cfg();
        assert_eq!(c.sample_every, 20, "采样间隔：每 20 迭代");
        assert_eq!(c.window, 5, "样本窗：5 个样本");
        assert_eq!(c.band_rel, 0.002, "带：0.2%");
        assert_eq!(c.min_iter, 100, "最小迭代：100");
        assert_eq!(c.cont_global_max, 1e-2, "连续性全局余量上限：1e-2");
        assert_eq!(c.confirm_rounds, 2, "确认轮数：2");
    }

    /// T1 三道门：
    /// 带内 + iter=100 + cg=1e-3 → 稳定；同输入 iter=80 → 不稳定（最小迭代门）；
    /// 同输入 cg=0.1 → 不稳定（连续性门）；带外样本 → 不稳定（带门）。
    #[test]
    fn t1_three_gates() {
        let c = cfg();

        // 三道门全过：稳定，首次确认（confirm_rounds=2 → 尚不停车）
        let v = dp_stop_decide(&IN_BAND, 100, 1e-3, &c, 0);
        assert!(v.ready, "窗已满应 ready");
        assert_eq!(v.n_samples, c.window);
        assert!(v.stable, "带内 + iter=100 + cg=1e-3 应判稳定（band {:.4}%）", v.band_pct);
        assert!(v.band_pct < c.band_rel * 100.0);
        assert_eq!(v.confirm, 1, "首次稳定 → 确认计数 1");
        assert!(!v.stop, "confirm 1 < 2，不应停车");

        // 最小迭代门：iter=80 < min_iter=100 → 不稳定，且已累计的确认必须清零
        let v = dp_stop_decide(&IN_BAND, 80, 1e-3, &c, 1);
        assert!(!v.stable, "iter=80 未过最小迭代门，不得判稳定");
        assert_eq!(v.confirm, 0, "不稳定必须把确认计数清零");
        assert!(!v.stop);

        // 边界：iter 恰好 = min_iter → 门是「>=」，仍应稳定
        let v = dp_stop_decide(&IN_BAND, c.min_iter, 1e-3, &c, 0);
        assert!(v.stable, "iter == min_iter 属于门内（>=）");
        let v = dp_stop_decide(&IN_BAND, c.min_iter - 1, 1e-3, &c, 0);
        assert!(!v.stable, "iter == min_iter-1 属于门外");

        // 连续性门：cg=0.1 > 1e-2 → 不稳定（dP 再稳也不停车）
        let v = dp_stop_decide(&IN_BAND, 100, 0.1, &c, 1);
        assert!(!v.stable, "连续性 0.1 > 1e-2，不得判稳定");
        assert_eq!(v.confirm, 0, "连续性不达标也必须清零确认计数");

        // 带门：带外样本 → 不稳定
        let v = dp_stop_decide(&OUT_BAND, 140, 1e-3, &c, 1);
        assert!(!v.stable, "带外样本（band {:.4}%）不得判稳定", v.band_pct);
        assert!(v.band_pct > c.band_rel * 100.0);
        assert_eq!(v.confirm, 0);

        // 带边界严格性：band_rel 恰好 == 门限 → 不稳定（门是严格「<」）
        let v = dp_stop_decide(&AT_BAND_EDGE, 140, 1e-3, &c, 0);
        assert!(
            (v.band_rel - c.band_rel).abs() < 1e-15,
            "构造样本的 band_rel 应恰等于门限，实际 {}",
            v.band_rel
        );
        assert!(!v.stable, "band_rel == 门限时应判不稳定（严格小于）");

        // 窗未满：不评估，确认计数原样保留（不得被误清零、也不得误停车）
        let v = dp_stop_decide(&IN_BAND[..3], 60, 1e-3, &c, 1);
        assert!(!v.ready, "3 < window=5 应判窗未满");
        assert!(!v.stop);
        assert_eq!(v.confirm, 1, "窗未满不应改动确认计数");
    }

    /// T2 confirm 重置：序列「稳定 → 带外 → 稳定 → 稳定」→ 只在第 4 个评估窗（第 3 次
    /// 确认之后）停车；中间那次带外必须把计数清零，否则第 3 个窗口就会误停。
    #[test]
    fn t2_confirm_reset() {
        let c = cfg();
        let mut confirm = 0usize;
        let mut stops: Vec<usize> = Vec::new();
        let mut confirms: Vec<usize> = Vec::new();
        // 模拟 4 个评估窗（每 20 迭代一个采样窗，这里只喂窗口内容与迭代号）
        let windows: [(usize, &[f64], bool); 4] = [
            (100, &IN_BAND, true),
            (120, &OUT_BAND, false),
            (140, &IN_BAND, true),
            (160, &IN_BAND, true),
        ];
        for (it, samples, expect_stable) in windows {
            let v = dp_stop_decide(samples, it, 1e-3, &c, confirm);
            assert_eq!(v.stable, expect_stable, "iter {it} 稳定判定不符预期");
            confirm = v.confirm;
            confirms.push(v.confirm);
            if v.stop {
                stops.push(it);
            }
        }
        assert_eq!(
            confirms,
            vec![1, 0, 1, 2],
            "确认计数序列应为 稳定=1 → 带外清零 0 → 稳定重计 1 → 稳定 2"
        );
        assert_eq!(
            stops,
            vec![160],
            "只在第 4 个评估窗确认 2 次后停车；若中间未清零会在 iter 140 误停"
        );
        // 显式钉「中间那次带外把计数清零」这一环
        let v1 = dp_stop_decide(&IN_BAND, 100, 1e-3, &c, 0);
        let v2 = dp_stop_decide(&OUT_BAND, 120, 1e-3, &c, v1.confirm);
        assert_eq!((v1.confirm, v2.confirm), (1, 0), "带外必须清零");
        let v3 = dp_stop_decide(&IN_BAND, 140, 1e-3, &c, v2.confirm);
        assert_eq!(v3.confirm, 1, "清零后第 3 个窗口只得 1 次确认");
        assert!(!v3.stop, "清零后不得在第 3 个窗口停车");
        let v4 = dp_stop_decide(&IN_BAND, 160, 1e-3, &c, v3.confirm);
        assert_eq!(v4.confirm, 2);
        assert!(v4.stop, "第 2 次确认（连续两窗稳定）才停车");
    }

    /// 端到端用的 Run-A 直管边界条件（patch 名用判据契约名 inlet / outlet）
    fn duct_bcs(q: f64) -> BoundaryConditions {
        let wall = || PatchBC {
            velocity: VelocityBC::FixedValue([0.0, 0.0, 0.0]),
            pressure: PressureBC::ZeroGradient,
        };
        BoundaryConditions {
            patches: vec![
                (
                    "inlet".to_string(),
                    PatchBC {
                        velocity: VelocityBC::FlowRateInlet { q },
                        pressure: PressureBC::ZeroGradient,
                    },
                ),
                (
                    "outlet".to_string(),
                    PatchBC {
                        velocity: VelocityBC::ZeroGradient,
                        pressure: PressureBC::FixedValue(0.0),
                    },
                ),
                ("yMin".to_string(), wall()),
                ("yMax".to_string(), wall()),
                ("zMin".to_string(), wall()),
                ("zMax".to_string(), wall()),
            ],
        }
    }

    /// 造一个可跑的小直管 solver：`build_box_mesh` 的 patch 名是 xMin/xMax，
    /// 判据按名找 inlet*/outlet，这里改名为契约名（几何与网格不受影响）。
    fn duct_solver(dp_stop: bool, max_iter: usize) -> SimpleSolver {
        let (nx, ny, nz) = (20usize, 5usize, 1usize);
        let (h, l, w) = (0.01f64, 0.2f64, 0.01f64);
        let u_mean = 0.02f64;
        let mut mesh = build_box_mesh(nx, ny, nz, l / nx as f64, h / ny as f64, w / nz as f64);
        for p in mesh.patches.iter_mut() {
            if p.name == "xMin" {
                p.name = "inlet".to_string();
            } else if p.name == "xMax" {
                p.name = "outlet".to_string();
            }
        }
        let mut params = SolverParams::default();
        params.max_iter = max_iter;
        // 端到端只验 dP 判据与 endTime 兜底：把 residualControl 门收到实际不可达
        params.residual_p = 1e-12;
        params.residual_u = 1e-12;
        params.write_interval = 0;
        let mut solver = SimpleSolver::new(mesh, CaseConfig::synthetic(duct_bcs(u_mean * h * w), params))
            .expect("构造 solver 失败");
        solver.dp_stop = dp_stop;
        solver
    }

    /// 当前场态的 dP（与 contract_metrics / 判据同口径）
    fn duct_dp(s: &SimpleSolver) -> f64 {
        let inlets: Vec<usize> = s
            .patches
            .iter()
            .enumerate()
            .filter(|(_, p)| p.name.starts_with("inlet"))
            .map(|(i, _)| i)
            .collect();
        let outlet = s
            .patches
            .iter()
            .position(|p| p.name == "outlet")
            .expect("缺 outlet patch");
        dp_pa(&s.mesh, &s.p, &inlets, outlet)
    }

    /// T3 端到端（真跑）：判据开 → `stop_reason = dp_stable`、停车早于跑满、停车时 dP 与
    /// 跑满 1500 步的 dP 相对差 < 0.1%；判据关（等价 `--no-dp-stop`）→ `endtime` + 1500 步。
    #[test]
    fn t3_end_to_end_dp_stable_and_no_dp_stop() {
        std::env::remove_var("FLOWSCOPE_DP_STOP");
        let max_iter = 1500usize;
        let c = cfg();

        // (a) 判据开：应在 1500 步内因 dP 稳定停车
        let mut on = duct_solver(true, max_iter);
        on.run(None, None, false).expect("判据开：求解失败");
        assert_eq!(on.stop_reason, "dp_stable", "应因 dP 稳定停车，实际：{}", on.stop_detail);
        let stop_iter = on.stop_iter;
        assert!(
            stop_iter >= c.min_iter,
            "停车迭代 {stop_iter} 不应早于最小迭代 {}",
            c.min_iter
        );
        assert!(stop_iter < max_iter, "停车迭代 {stop_iter} 应早于跑满 {max_iter}");
        assert!(
            on.dp_band_pct < c.band_rel * 100.0,
            "停车时带的百分数数值 {:.4} 应 < {}",
            on.dp_band_pct,
            c.band_rel * 100.0
        );
        // 日志三字段（pipeline 契约：tests/test_dp_stop.py 解析同一格式）
        let log = on.contract_metrics();
        assert!(log.contains("\nstop_reason         : dp_stable\n"), "日志缺 dp_stable 三字段：{log}");
        assert!(
            log.contains(&format!("\nstop_iter           : {stop_iter}\n")),
            "日志 stop_iter 应为 {stop_iter}：{log}"
        );
        assert!(log.contains("\ndp_band_pct         : "), "日志缺 dp_band_pct：{log}");
        let dp_on = duct_dp(&on);

        // (b) 判据关（--no-dp-stop 同义）：必须 endTime 硬停 1500 步
        let mut off = duct_solver(false, max_iter);
        off.run(None, None, false).expect("判据关：求解失败");
        assert_eq!(off.stop_reason, "endtime", "关闭判据后应 endTime 硬停，实际：{}", off.stop_detail);
        assert_eq!(off.stop_iter, max_iter, "关闭判据后应跑满 {max_iter} 步");
        let off_log = off.contract_metrics();
        assert!(
            off_log.contains("\nstop_reason         : endtime\n"),
            "关闭判据的日志 stop_reason 应为 endtime：{off_log}"
        );
        let dp_off = duct_dp(&off);

        // (c) dP 判据的正当性：停车时的 dP 与跑满的 dP 相对差 < 0.1%
        let rel = ((dp_on - dp_off) / dp_off).abs();
        assert!(
            rel < 1e-3,
            "停车 dP {dp_on:.6e} 与跑满 dP {dp_off:.6e} 相对差 {:.4}% 应 < 0.1%",
            rel * 100.0
        );
    }

    /// 横幅：判据关闭 / 不适用时**不得**再罗列参数元组，只给一行原因
    #[test]
    fn t4_banner_off_does_not_list_params() {
        let c = cfg();
        // 生效时：必须带参数元组
        let on = dp_stop_banner(DpStopMode::Enabled, &c);
        for must in ["residualControl OR dP-stable", "0.2%", "最少 100 步", "连续 2 轮确认"] {
            assert!(on.contains(must), "生效横幅缺 {must}：{on}");
        }
        // 关闭 / 不适用时：明确一行原因，且不得出现任何参数数字
        let cases = [
            (DpStopMode::SwitchOff, dp_stop_mode(false, false, false, 1, true)),
            (DpStopMode::SwitchOff, dp_stop_mode(true, true, false, 1, true)),
            (DpStopMode::InletPressureFixed, dp_stop_mode(true, false, true, 2, true)),
            (DpStopMode::MissingPatches, dp_stop_mode(true, false, false, 0, true)),
            (DpStopMode::MissingPatches, dp_stop_mode(true, false, false, 2, false)),
        ];
        for (want, got) in cases {
            assert_eq!(want, got, "模式派生不符预期");
            let s = dp_stop_banner(got, &c);
            assert!(s.starts_with("residualControl only"), "应以 residualControl only 开头：{s}");
            for ban in ["样本", "0.2%", "最少 100", "连续 2 轮", "1e-2", "0.01"] {
                assert!(!s.contains(ban), "关闭/不适用横幅不得罗列参数（出现 {ban}）：{s}");
            }
        }
        // 只有四类全满足才进入 Enabled
        assert_eq!(dp_stop_mode(true, false, false, 1, true), DpStopMode::Enabled);
    }
}
