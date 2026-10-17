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

use std::path::Path;

use crate::bc::{BoundaryConditions, PatchBC, PressureBC, VelocityBC};
use crate::config::{CaseConfig, SolverParams};
use crate::fields::{grad_scalar, grad_vector, VolScalar, VolVector};
use crate::fvm::{
    adjust_phi, assemble_momentum, assemble_pressure, bnd_pres_fixed_flags, compile_patches,
    hbya_flux, rhie_chow_phi, FvVectorMatrix,
};
use crate::linalg::{pcg, sgs_solve, Csr, LinSolveInfo};
use crate::mesh::{dot, Mesh, Patch};
use crate::metrics::{
    dp_pa, flow_split, patch_area, patch_face_mean_p, patch_flux_sum, vtk_write,
    wall_shear_stress,
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

pub struct SimpleSolver {
    pub mesh: Mesh,
    pub cfg: CaseConfig,
    pub patches: Vec<crate::fvm::PatchCtx>,
    pub bnd_pf: Vec<bool>,
    pub u: VolVector,
    pub p: VolScalar,
    pub hbya: VolVector,
    pub rau: Vec<f64>,
    pub phi: Vec<f64>,
    pub grad_u: Vec<[[f64; 3]; 3]>,
    pub grad_p: Vec<[f64; 3]>,
    pub records: Vec<IterRecord>,
    pub lin_p: Vec<LinSolveInfo>,
    pub iter: usize,
    pub converged: bool,
    pub stop_reason: String,
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
        Ok(SimpleSolver {
            mesh,
            cfg,
            patches,
            bnd_pf,
            u,
            p,
            hbya,
            rau,
            phi,
            grad_u: Vec::new(),
            grad_p: Vec::new(),
            records: Vec::new(),
            lin_p: Vec::new(),
            iter: 0,
            converged: false,
            stop_reason: String::new(),
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
        }
        for it in 1..=max_iter {
            self.iter = it;
            let n_cells = self.mesh.n_cells();
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
            // ⑥ phiHbyA
            self.update_hbya_bnd();
            let mut phi_hbya = hbya_flux(&self.mesh, &self.hbya);
            // ⑥b 全局通量平衡（adjustPhi）：出口通量补足入口，压力方程只处理局部失衡
            adjust_phi(&self.mesh, &self.patches, &mut phi_hbya);
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
            let pinfo = pcg(
                &pcsr,
                &pm.source,
                &mut self.p.data,
                self.cfg.params.p_tol,
                self.cfg.params.p_reltol,
                p_cap,
                true,
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
                    "Time = {it}  Ux {:.3e} Uy {:.3e} Uz {:.3e}  p {:.3e}  cont local {:.3e} global {:.3e}  (pLin {} it, final {:.3e}, brk {})",
                    mres[0], mres[1], mres[2], pinfo.init_res, cl, cg,
                    pinfo.iters, pinfo.final_res, pinfo.breakdown
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
            }
            // ⑫ residualControl 双达标 → 早停
            if pinfo.init_res < self.cfg.params.residual_p
                && mres[0] < self.cfg.params.residual_u
                && mres[1] < self.cfg.params.residual_u
                && mres[2] < self.cfg.params.residual_u
            {
                self.converged = true;
                self.stop_reason = format!(
                    "SIMPLE solution converged：iter {it}，p 初残差 {:.3e} < {}，U 初残差 {:.3e}/{:.3e}/{:.3e} < {}（residualControl 双口径达标）",
                    pinfo.init_res, self.cfg.params.residual_p,
                    mres[0], mres[1], mres[2], self.cfg.params.residual_u
                );
                if verbose {
                    println!("{}", self.stop_reason);
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
        if !self.converged {
            self.stop_reason = format!(
                "endTime 硬停：跑满 {} 步，residualControl 未双达标（末步 p 初残差 {:.3e}，U {:.3e}/{:.3e}/{:.3e}）",
                max_iter,
                self.records.last().map(|r| r.p_res).unwrap_or(f64::NAN),
                self.records.last().map(|r| r.ux).unwrap_or(f64::NAN),
                self.records.last().map(|r| r.uy).unwrap_or(f64::NAN),
                self.records.last().map(|r| r.uz).unwrap_or(f64::NAN)
            );
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
        s.push_str(&format!("stop reason         : {}\n", self.stop_reason));
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
            let wss = wall_shear_stress(&self.mesh, &self.u, self.cfg.mu, w);
            let mean = wss.iter().sum::<f64>() / wss.len().max(1) as f64;
            let max = wss.iter().cloned().fold(0.0f64, f64::max);
            s.push_str(&format!(
                "WSS (1st-order voxel est): mean {:.6e} Pa, max {:.6e} Pa ({} wall faces)\n",
                mean, max, wss.len()
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
    let gate_pass = u_center_rel_err < 0.01 && dpdx_rel_err < 0.02;
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
        dpdx_rel_err,
        dpdx_num_pa: RHO_AIR * dpdx_num,
        dpdx_exact_pa: RHO_AIR * dpdx_exact,
        iterations: solver.iter,
        converged: solver.converged,
        stop_reason: solver.stop_reason.clone(),
        gate_pass,
    })
}

/// 便捷：mu 常量再导出（供报告引用）
pub const MU: f64 = MU_AIR;


