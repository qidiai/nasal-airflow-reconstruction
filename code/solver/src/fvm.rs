//! 离散算子与矩阵组装（FVM）
//!
//! provenance（清洁室，依据文献）：
//! - 对流 `div(phi,U) = bounded Gauss linearUpwind grad(U)`（契约 §5 红线）：
//!   隐式部分取 upwind 系数，高阶外插作显式延迟修正源（Versteeg & Malalasekera
//!   §5.9 "deferred correction"；Ferziger & Peric §8.2）；`bounded` 限示 = 面值限制在
//!   上下游单元值之间（TVD 型标量限示器，van Leer / limitedLinear 同族）。
//! - 扩散 `Gauss linear corrected`：隐式取正交分量 nu·k_f（k_f = S_f·Δ/|Δ|²），
//!   非正交分量以当前 cell 梯度显式修正一次（nNonOrthogonalCorrectors = 0，
//!   Versteeg & Malalasekera §7.4；Peric & Ferziger §9.3）。
//! - Rhie-Chow 压力速度耦合：phi_f = HbyA_f·Sf − rAU_f·k_f·(p_N−p_P)（Rhie & Chow 1983）。
//!   与经典 SIMPLE 预测速度插值代数等价（phi_f = U*_f·Sf）。
//! - SIMPLE 主循环：Patankar & Spalding（1972/1980）；欠松弛 p=0.3 / U=0.7（契约 §4）。

use crate::bc::{BoundaryConditions, PressureBC, VelocityBC};
use crate::fields::{VolScalar, VolVector};
use crate::linalg::Csr;
use crate::mesh::{dot, sub, Mesh};

/// 标量 FV 矩阵（组装态：对角 + 内部面上下三角）
#[derive(Debug, Clone)]
pub struct FvMatrix {
    pub diag: Vec<f64>,
    /// upper[f] = owner 行中 neighbour 列的系数
    pub upper: Vec<f64>,
    /// lower[f] = neighbour 行中 owner 列的系数
    pub lower: Vec<f64>,
    pub source: Vec<f64>,
}

impl FvMatrix {
    pub fn zeros(n: usize, n_internal: usize) -> Self {
        FvMatrix {
            diag: vec![0.0; n],
            upper: vec![0.0; n_internal],
            lower: vec![0.0; n_internal],
            source: vec![0.0; n],
        }
    }
    pub fn to_csr(&self, mesh: &Mesh) -> Csr {
        Csr::from_fv(mesh, &self.diag, &self.upper, &self.lower)
    }
}

/// 向量 FV 矩阵（3 分量共享系数矩阵）
#[derive(Debug, Clone)]
pub struct FvVectorMatrix {
    pub diag: Vec<f64>,
    pub upper: Vec<f64>,
    pub lower: Vec<f64>,
    pub source: Vec<[f64; 3]>,
}

impl FvVectorMatrix {
    pub fn zeros(n: usize, n_internal: usize) -> Self {
        FvVectorMatrix {
            diag: vec![0.0; n],
            upper: vec![0.0; n_internal],
            lower: vec![0.0; n_internal],
            source: vec![[0.0; 3]; n],
        }
    }
    pub fn to_csr(&self, mesh: &Mesh) -> Csr {
        Csr::from_fv(mesh, &self.diag, &self.upper, &self.lower)
    }
}

/// 编译后的 patch 组装上下文（边界值已解析）
#[derive(Debug, Clone)]
pub struct PatchCtx {
    pub name: String,
    pub start: usize,
    pub n_faces: usize,
    /// 速度固定值（FixedValue / FlowRateInlet）
    pub vel_fixed: bool,
    pub vel_value: [f64; 3],
    /// 逐面速度（flowRateInletVelocity：U_f = (Q/A)·n̂_f，逐面法向）。
    /// OpenFOAM 该 BC 用 patch.nf() 的**逐面**单位法向；对非平面入口
    /// （实测 pB inletL 面法向最大偏离均值 89°）不能用单一均值方向近似。
    pub vel_face: Option<Vec<[f64; 3]>>,
    /// 压力固定值
    pub pres_fixed: bool,
    pub pres_value: f64,
}

impl PatchCtx {
    #[inline]
    pub fn vel_at(&self, f: usize) -> [f64; 3] {
        match &self.vel_face {
            Some(v) => v[f - self.start],
            None => self.vel_value,
        }
    }
}

/// 编译 patch：解析 flowRateInletVelocity 的均匀入口速度
/// （OpenFOAM 用户手册 BC：patch 均匀速度、法向入流、幅值 = Q/A_patch；
/// 方向取面积加权平均内法向——保证 Σ_f phi_f = −Q 精确，与契约 E15 实证同构）
pub fn compile_patches(mesh: &Mesh, bcs: &BoundaryConditions) -> Result<Vec<PatchCtx>, String> {
    let mut out = Vec::with_capacity(mesh.patches.len());
    for p in &mesh.patches {
        let bc = bcs
            .get(&p.name)
            .ok_or_else(|| format!("mesh patch '{}' 在边界条件中缺失", p.name))?;
        let mut vel_face: Option<Vec<[f64; 3]>> = None;
        let (vel_fixed, vel_value) = match &bc.velocity {
            VelocityBC::FixedValue(v) => (true, *v),
            VelocityBC::FlowRateInlet { q } => {
                let mut area = 0.0f64;
                for f in p.start..p.start + p.n_faces {
                    area += mesh.face_mag[f];
                }
                if area <= 0.0 {
                    return Err(format!("patch {} 面积非正", p.name));
                }
                let mag = q / area;
                // 逐面单位内法向 n̂_f = −Sf/|Sf|（OpenFOAM patch.nf() 同构）
                let mut vf = Vec::with_capacity(p.n_faces);
                for f in p.start..p.start + p.n_faces {
                    let m = mesh.face_mag[f];
                    if m <= 0.0 {
                        return Err(format!("patch {} 第 {} 面面积非正", p.name, f));
                    }
                    let sf = mesh.face_sf[f];
                    vf.push([-sf[0] / m * mag, -sf[1] / m * mag, -sf[2] / m * mag]);
                }
                // 均值方向仅作记录/兜底（真正使用的是 vel_face）
                let mut s = [0.0f64; 3];
                for v in &vf {
                    s[0] += v[0];
                    s[1] += v[1];
                    s[2] += v[2];
                }
                let k = vf.len().max(1) as f64;
                vel_face = Some(vf);
                (true, [s[0] / k, s[1] / k, s[2] / k])
            }
            VelocityBC::ZeroGradient => (false, [0.0; 3]),
        };
        let (pres_fixed, pres_value) = match &bc.pressure {
            PressureBC::FixedValue(v) => (true, *v),
            PressureBC::ZeroGradient => (false, 0.0),
        };
        out.push(PatchCtx {
            name: p.name.clone(),
            start: p.start,
            n_faces: p.n_faces,
            vel_fixed,
            vel_value,
            vel_face,
            pres_fixed,
            pres_value,
        });
    }
    Ok(out)
}

/// 每个边界面是否压力固定（零梯度 → 无压力通量）
pub fn bnd_pres_fixed_flags(mesh: &Mesh, patches: &[PatchCtx]) -> Vec<bool> {
    let mut v = vec![false; mesh.n_boundary_faces()];
    for p in patches {
        if p.pres_fixed {
            for f in p.start..p.start + p.n_faces {
                v[f - mesh.n_internal] = true;
            }
        }
    }
    v
}

/// cell 心标量在内部面的 Gauss linear 插值
pub fn interp_face(mesh: &Mesh, data: &[f64], f: usize) -> f64 {
    let o = mesh.face_owner[f] as usize;
    let n = mesh.face_neigh[f] as usize;
    let d = sub(mesh.cell_cc[n], mesh.cell_cc[o]);
    let dd = dot(d, d);
    let lam = if dd > 0.0 {
        dot(sub(mesh.face_cf[f], mesh.cell_cc[o]), d) / dd
    } else {
        0.5
    };
    data[o] + lam * (data[n] - data[o])
}

/// 非正交修正：返回 nu·(Sf·corr)（逐分量），corr = ½(grad_P+grad_N) − Δ(Δ·½(grad_P+grad_N))/|Δ|²
fn nonorth_source(
    sf: [f64; 3],
    go: &[[f64; 3]; 3],
    gn: &[[f64; 3]; 3],
    delta: [f64; 3],
    nu: f64,
) -> [f64; 3] {
    let dd = dot(delta, delta);
    let mut out = [0.0f64; 3];
    for i in 0..3 {
        let ga = [
            0.5 * (go[i][0] + gn[i][0]),
            0.5 * (go[i][1] + gn[i][1]),
            0.5 * (go[i][2] + gn[i][2]),
        ];
        let proj = if dd > 0.0 { dot(delta, ga) / dd } else { 0.0 };
        let corr = [
            ga[0] - proj * delta[0],
            ga[1] - proj * delta[1],
            ga[2] - proj * delta[2],
        ];
        out[i] = nu * (sf[0] * corr[0] + sf[1] * corr[1] + sf[2] * corr[2]);
    }
    out
}

/// bounded linearUpwind 面值：U_f = U_c + θ·(C_f−C_c)·gradU_c（可选限示器）。
///
/// **契约真实性（第四棒更正）**：OpenFOAM 用户指南 §4.5.3 明确 `bounded` 不是限示器，
/// 而是把对流项按物质导数形式 ∂e/∂t + ∇·(Ue) − (∇·U)e 离散（多出 −(∇·U)e 项）；
/// `Gauss linearUpwind` 本身是**无界**二阶迎风偏置格式（指南原文："linearUpwind:
/// second order, upwind-biased, unbounded"）。因此本函数的默认行为是**纯外插、不限示**；
/// 第三棒加入的"夹到 [U_c,U_d]"限示器只是诊断用的保守变体，默认关闭
/// （`FLOWSCOPE_LU_LIMITER=clamp` 可复现旧行为）。
fn bounded_lu_face(
    mesh: &Mesh,
    u: &VolVector,
    grad_u: &[[[f64; 3]; 3]],
    f: usize,
    phi_f: f64,
) -> [f64; 3] {
    let o = mesh.face_owner[f] as usize;
    let n = mesh.face_neigh[f] as usize;
    let (c, d) = if phi_f >= 0.0 { (o, n) } else { (n, o) };
    let psi = sub(mesh.face_cf[f], mesh.cell_cc[c]);
    let g = &grad_u[c];
    let mut e = [0.0f64; 3];
    for i in 0..3 {
        e[i] = psi[0] * g[i][0] + psi[1] * g[i][1] + psi[2] * g[i][2];
    }
    let mut out = [0.0f64; 3];
    // 诊断开关（默认关）：绕过限示器 = 纯二阶迎风外插，用于量化"限示器耗散"对
    // 真实算例的代价（见看板 W5 诊断记录）。
    let unlimited = std::env::var("FLOWSCOPE_LU_UNLIMITED").is_ok();
    // 限示器（默认关，仅诊断；契约方案不含限示器，见上方文档注释）
    let clamp_on = std::env::var("FLOWSCOPE_LU_LIMITER")
        .map(|v| v == "clamp")
        .unwrap_or(false);
    for i in 0..3 {
        if unlimited || !clamp_on {
            out[i] = u.data[c][i] + e[i];
            continue;
        }
        let dd = u.data[d][i] - u.data[c][i];
        let theta = if dd.abs() < 1e-14 {
            // 两端分量相等：外插值必须为 0（否则制造新极值）
            if e[i].abs() < 1e-14 {
                1.0
            } else {
                0.0
            }
        } else {
            (e[i] / dd).clamp(0.0, 1.0)
        };
        out[i] = u.data[c][i] + theta * e[i];
    }
    out
}

/// 契约 §5 的 `bounded` 前缀（默认开）：OpenFOAM 用户指南 §4.5.3 定义——
/// 稳态下对流项按 `∇·(Ue) − (∇·U)e` 离散。它不是限示器；作用是维持有界性与
/// 收敛性（"helps maintain boundedness of the solution variable and promotes
/// better convergence"）。`FLOWSCOPE_BOUNDED=0` 可回退到第三棒的保守形式（诊断用）。
pub fn bounded_form() -> bool {
    std::env::var("FLOWSCOPE_BOUNDED").map(|v| v != "0").unwrap_or(true)
}

#[inline]
fn add3(a: [f64; 3], b: [f64; 3]) -> [f64; 3] {
    [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
}

#[inline]
fn scale3(a: [f64; 3], s: f64) -> [f64; 3] {
    [a[0] * s, a[1] * s, a[2] * s]
}

/// 组装动量矩阵（不含压力梯度；含方程松弛 alpha_u）
pub fn assemble_momentum(
    mesh: &Mesh,
    nu: f64,
    alpha_u: f64,
    patches: &[PatchCtx],
    phi: &[f64],
    u: &VolVector,
    grad_u: &[[[f64; 3]; 3]],
    lu_deviation: bool,
) -> FvVectorMatrix {
    let n = mesh.n_cells();
    let ni = mesh.n_internal;
    let mut m = FvVectorMatrix::zeros(n, ni);
    let bounded = bounded_form();
    // ---- 内部面 ----
    for f in 0..ni {
        let o = mesh.face_owner[f] as usize;
        let nb = mesh.face_neigh[f] as usize;
        let phi_f = phi[f];
        let sf = mesh.face_sf[f];
        // 扩散：正交分量隐式
        let d = nu * mesh.k_face(f);
        m.diag[o] += d;
        m.upper[f] += -d;
        m.diag[nb] += d;
        m.lower[f] += -d;
        // 非正交修正（显式）
        let delta = sub(mesh.cell_cc[nb], mesh.cell_cc[o]);
        let cf = nonorth_source(sf, &grad_u[o], &grad_u[nb], delta, nu);
        m.source[o] = add3(m.source[o], cf);
        m.source[nb] = add3(m.source[nb], scale3(cf, -1.0));
        // 对流（隐式 upwind + 二阶外插的显式延迟修正）
        //
        // 两种稳态形式（第四棒按用户指南 §4.5.3 更正）：
        //  · 保守形式（bounded=0）：C_P = Σ φ_f u_f —— 上风向单元持有隐式对流对角项；
        //  · bounded 形式（默认）  ：C_P = Σ φ_f u_f − u_P·Σ φ_f —— 下风向单元持有对角项，
        //    等价于对 ∇·(Ue) − (∇·U)e 做离散，是 OpenFOAM `bounded` 前缀的**文档定义**。
        // 两者在 Σφ→0 时同一不动点，但 bounded 形式的矩阵对角只含入流贡献，
        // 对流项不抬高对角 → 配合 α_U=0.7 的方程松弛后可容纳无界二阶外插
        // （这正是 OF 不开限示器也稳定的机制）。
        if phi_f != 0.0 {
            let u_f = if lu_deviation {
                bounded_lu_face(mesh, u, grad_u, f, phi_f)
            } else {
                if phi_f > 0.0 { u.data[o] } else { u.data[nb] }
            };
            // 符号约定：本文所有显式项按 A·u = b 记，b = −(显式 LHS 项)。
            // 高阶偏差 dev = u_f − u_upwind，其 RHS 贡献为 −φ_f·dev（行主元侧）。
            if phi_f > 0.0 {
                if bounded {
                    m.diag[nb] += phi_f;
                } else {
                    m.diag[o] += phi_f;
                }
                m.lower[f] += -phi_f;
                let dev = sub(u_f, u.data[o]);
                m.source[o] = add3(m.source[o], scale3(dev, -phi_f));
                m.source[nb] = add3(m.source[nb], scale3(dev, phi_f));
            } else {
                if bounded {
                    m.diag[o] += -phi_f;
                } else {
                    m.diag[nb] += -phi_f;
                }
                m.upper[f] += phi_f;
                let dev = sub(u_f, u.data[nb]);
                m.source[o] = add3(m.source[o], scale3(dev, -phi_f));
                m.source[nb] = add3(m.source[nb], scale3(dev, phi_f));
            }
        }
    }
    // ---- 边界面 ----
    for p in patches {
        for f in p.start..p.start + p.n_faces {
            let c = mesh.face_owner[f] as usize;
            let bi = f - ni;
            let sf = mesh.face_sf[f];
            let phi_f = phi[f];
            // 扩散（仅固定速度 patch；零梯度 → snGrad=0 无通量）
            if p.vel_fixed {
                let kb = mesh.k_face_boundary(f);
                let d = nu * kb;
                m.diag[c] += d;
                m.source[c] = add3(m.source[c], scale3(u.bnd[bi], d));
                let delta = sub(mesh.face_cf[f], mesh.cell_cc[c]);
                let cf = nonorth_source(sf, &grad_u[c], &grad_u[c], delta, nu);
                m.source[c] = add3(m.source[c], cf);
            }
            // 对流：C_P 边界面贡献 φ_f(u_f − u_P)
            if phi_f != 0.0 {
                let u_f = if p.vel_fixed { u.bnd[bi] } else { u.data[c] };
                if phi_f > 0.0 {
                    // 出流：u_f 由本单元/BC 给出；bounded 形式的 −u_PΣφ 使对角项归零
                    if !bounded {
                        m.diag[c] += phi_f;
                    }
                    m.source[c] = add3(m.source[c], scale3(sub(u_f, u.data[c]), phi_f));
                } else {
                    // 入流：上游 = 边界面值，已知项移到 RHS（LHS 的 +phi_f·u_b 取负）
                    if bounded {
                        // −u_P·Σφ 中该面的贡献：φ_f<0 → 对角 +(−φ_f)
                        m.diag[c] += -phi_f;
                    }
                    m.source[c] = add3(m.source[c], scale3(u_f, -phi_f));
                }
            }
        }
    }
    // ---- 方程松弛（alpha_u）：A' = A/α，b' = b + (1/α−1)·A·U_old ----
    if alpha_u < 1.0 {
        let f = 1.0 / alpha_u - 1.0;
        for c in 0..n {
            m.source[c] = add3(m.source[c], scale3(u.data[c], f * m.diag[c]));
            m.diag[c] /= alpha_u;
        }
    }
    m
}

/// HbyA 面通量（线性插值内部面；边界面用 HbyA 边界面值）
pub fn hbya_flux(mesh: &Mesh, hbya: &VolVector) -> Vec<f64> {
    let mut phi = vec![0.0f64; mesh.n_faces()];
    for f in 0..mesh.n_internal {
        let uf = hbya.face_value(mesh, f);
        phi[f] = dot(uf, mesh.face_sf[f]);
    }
    for f in mesh.n_internal..mesh.n_faces() {
        let ub = hbya.bnd[f - mesh.n_internal];
        phi[f] = dot(ub, mesh.face_sf[f]);
    }
    phi
}

/// 全局通量平衡（对标 OpenFOAM adjustPhi，SIMPLE 标准预处理）：
/// 在速度非固定、压力固定的 patch（出口）上均匀加一个常数，使
/// **Σ_所有边界面 phi = 0**。缺少此步时，压力方程被迫在首步
/// 用局部压差"造出"全部流量，会在缩颈处产生非物理射流种子。
///
/// 第四棒修正（B5）：旧实现只把"非可调面"的失衡摊到出口，**漏掉了出口自身的
/// phiHbyA 通量**——于是出口总通量被写成 (自身 + 入口)，压力方程再把它修正回来，
/// 等价于在出口附近人为压低 Δp ≈ 10 Pa（p_cell ≈ −9 kinematic），并使出口单元速度
/// 与面通量脱节（见 D-5）。正确做法是失衡按**全部边界面**求和。
pub fn adjust_phi(mesh: &Mesh, patches: &[PatchCtx], phi: &mut [f64]) {
    // 只有"压力固定 + 速度不固定"的 patch 才是真正的出口/可调面
    // （对称/零梯度 patch 两侧同号补偿，绝不能灌流通量——否则入口流量会从对称面漏走）
    let adjustable = |p: &PatchCtx| !p.vel_fixed && p.pres_fixed;
    let mut sum_all = 0.0f64;
    let mut n_adjust = 0usize;
    for p in patches {
        for f in p.start..p.start + p.n_faces {
            sum_all += phi[f];
            if adjustable(p) {
                n_adjust += 1;
            }
        }
    }
    if n_adjust > 0 && sum_all.abs() > 0.0 {
        let add = -sum_all / n_adjust as f64;
        for p in patches {
            if !adjustable(p) {
                continue;
            }
            for f in p.start..p.start + p.n_faces {
                phi[f] += add;
            }
        }
    }
    let _ = mesh;
}

/// 组装压力方程：laplacian(rAUf, p) == **−**div(phiHbyA)
///
/// 符号推导（Rhie & Chow 1983；Patankar & Spalding 压力修正方程）：
/// 边界面通量 phi_f = phiHbyA_f − rAU_f·k_f·(p_N − p_P)，连续性 Σ_f phi_f = 0 要求
/// Σ_f rAU_f·k_f·(p_P − p_other) = −Σ_f ±phiHbyA_f，即拉普拉斯项 = **负**的
/// HbyA 通量散度（与经典 SIMPLE 的 laplacian(rAU,p') = −div(u*) 同号）。
/// 边界面：固定压力 patch 贡献 rAU·k_b·(p_P − p_b)（p_b 项移源）；零梯度无通量。
pub fn assemble_pressure(
    mesh: &Mesh,
    patches: &[PatchCtx],
    rau: &[f64],
    phi_hbya: &[f64],
    bnd_pf: &[bool],
) -> FvMatrix {
    let n = mesh.n_cells();
    let ni = mesh.n_internal;
    let mut m = FvMatrix::zeros(n, ni);
    for f in 0..ni {
        let o = mesh.face_owner[f] as usize;
        let nb = mesh.face_neigh[f] as usize;
        let d = interp_face(mesh, rau, f) * mesh.k_face(f);
        m.diag[o] += d;
        m.upper[f] += -d;
        m.diag[nb] += d;
        m.lower[f] += -d;
        m.source[o] -= phi_hbya[f];
        m.source[nb] += phi_hbya[f];
    }
    for p in patches {
        for f in p.start..p.start + p.n_faces {
            let c = mesh.face_owner[f] as usize;
            let bi = f - ni;
            m.source[c] -= phi_hbya[f];
            if bnd_pf[bi] {
                let d = rau[c] * mesh.k_face_boundary(f);
                m.diag[c] += d;
                m.source[c] += d * p.pres_value;
            }
        }
    }
    m
}

/// Rhie-Chow 面通量：phi_f = phiHbyA_f − rAU_f·k_f·(p_N−p_P)
/// 边界面：phi = phiHbyA − rAU_P·k_b·(p_b−p_P)（零梯度 patch 的 p_b ≡ p_P → 修正为 0）
pub fn rhie_chow_phi(
    mesh: &Mesh,
    rau: &[f64],
    phi_hbya: &[f64],
    p: &VolScalar,
) -> Vec<f64> {
    let ni = mesh.n_internal;
    let mut phi = vec![0.0f64; mesh.n_faces()];
    for f in 0..ni {
        let o = mesh.face_owner[f] as usize;
        let nb = mesh.face_neigh[f] as usize;
        let d = interp_face(mesh, rau, f) * mesh.k_face(f) * (p.data[nb] - p.data[o]);
        phi[f] = phi_hbya[f] - d;
    }
    for f in ni..mesh.n_faces() {
        let c = mesh.face_owner[f] as usize;
        let bi = f - ni;
        let d = rau[c] * mesh.k_face_boundary(f) * (p.bnd[bi] - p.data[c]);
        phi[f] = phi_hbya[f] - d;
    }
    phi
}
