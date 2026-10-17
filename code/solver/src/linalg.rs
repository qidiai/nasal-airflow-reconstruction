//! 稀疏线性代数：CSR 矩阵 + Krylov 迭代求解器
//!
//! provenance：Golub & Van Loan《Matrix Computations》ch.9-11（PCG / BiCGSTAB）；
//! 对称 Gauss-Seidel（SGS）预条件（Saad《Iterative Methods for Sparse Linear Systems》§4.2
//! 松弛型预条件子）。对标契约 §4 实证：p 方程 GAMG(GaussSeidel, tol 1e-6, relTol 0.05)、
//! U 方程 smoothSolver(GaussSeidel, tol 1e-5, relTol 0.01)。契约 §12 明确允许线性求解器
//! 内部实现不同——以"收敛到同等残差水平"为准，故此处用 PCG(SGS)/BiCGSTAB(SGS)。
//!
//! 残差归一化口径（对标 OpenFOAM gSum(cmptMag)/nCells）：
//! res = mean_i|r_i| / mean_i|b_i|。

use crate::mesh::Mesh;

/// CSR 稀疏矩阵（行内不排序：对角在前，其后按面序）
pub struct Csr {
    pub n: usize,
    pub row_ptr: Vec<u32>,
    pub col: Vec<u32>,
    pub val: Vec<f64>,
    pub diag_idx: Vec<u32>,
}

/// 求解结果（残差为归一化口径）
#[derive(Debug, Clone, Copy)]
pub struct LinSolveInfo {
    pub iters: usize,
    pub init_res: f64,
    pub final_res: f64,
    pub converged: bool,
    pub breakdown: bool,
}

impl Csr {
    /// 由 FV 矩阵（diag + 内部面 upper/lower 系数）构建 CSR。
    /// upper[f] = owner 行中 neighbour 列的系数；lower[f] = neighbour 行中 owner 列的系数。
    pub fn from_fv(mesh: &Mesh, diag: &[f64], upper: &[f64], lower: &[f64]) -> Csr {
        let n = mesh.n_cells();
        let mut row_len = vec![1u32; n];
        for f in 0..mesh.n_internal {
            row_len[mesh.face_owner[f] as usize] += 1;
            row_len[mesh.face_neigh[f] as usize] += 1;
        }
        let mut row_ptr = vec![0u32; n + 1];
        for c in 0..n {
            row_ptr[c + 1] = row_ptr[c] + row_len[c];
        }
        let nnz = row_ptr[n] as usize;
        let mut col = vec![0u32; nnz];
        let mut val = vec![0.0f64; nnz];
        let mut cursor = row_ptr.clone();
        let mut diag_idx = vec![0u32; n];
        for c in 0..n {
            let pos = cursor[c] as usize;
            col[pos] = c as u32;
            val[pos] = diag[c];
            diag_idx[c] = pos as u32;
            cursor[c] += 1;
        }
        for f in 0..mesh.n_internal {
            let o = mesh.face_owner[f] as usize;
            let nb = mesh.face_neigh[f] as usize;
            let p = cursor[o] as usize;
            col[p] = nb as u32;
            val[p] = upper[f];
            cursor[o] += 1;
            let p = cursor[nb] as usize;
            col[p] = o as u32;
            val[p] = lower[f];
            cursor[nb] += 1;
        }
        Csr {
            n,
            row_ptr,
            col,
            val,
            diag_idx,
        }
    }

    #[inline]
    pub fn diag_value(&self, i: usize) -> f64 {
        self.val[self.diag_idx[i] as usize]
    }

    pub fn matvec(&self, x: &[f64], y: &mut [f64]) {
        for i in 0..self.n {
            let s = self.row_ptr[i] as usize;
            let e = self.row_ptr[i + 1] as usize;
            let mut acc = 0.0f64;
            for k in s..e {
                acc += self.val[k] * x[self.col[k] as usize];
            }
            y[i] = acc;
        }
    }

    /// Gauss-Seidel 单扫（forward=true 前向；否则后向）。x 被就地更新。
    /// 注意：进入时先把 x 清零——保证本扫是**精确三角求解**（零初始猜测）：
    /// 前向扫只生效 j<i 项（j>i 乘 0），后向扫只生效 j>i 项。
    /// 这是 SGS 预条件子 M=(D+L)D^{-1}(D+U) 正确应用的前提；
    /// 若不清零，反向项会带入上次调用的残留值，预条件子不再 SPD，PCG 将发散。
    pub fn gs_sweep(&self, b: &[f64], x: &mut [f64], forward: bool) {
        let n = self.n;
        for v in x.iter_mut() {
            *v = 0.0;
        }
        if forward {
            for i in 0..n {
                x[i] = self.gs_row(i, b, x);
            }
        } else {
            for i in (0..n).rev() {
                x[i] = self.gs_row(i, b, x);
            }
        }
    }

    #[inline]
    fn gs_row(&self, i: usize, b: &[f64], x: &[f64]) -> f64 {
        let s = self.row_ptr[i] as usize;
        let e = self.row_ptr[i + 1] as usize;
        let mut acc = b[i];
        for k in s..e {
            let j = self.col[k] as usize;
            if j != i {
                acc -= self.val[k] * x[j];
            }
        }
        acc / self.val[self.diag_idx[i] as usize]
    }

    /// 对称 Gauss-Seidel 预条件应用：z ≈ M^{-1} r，M = (D+L)D^{-1}(D+U)
    pub fn sgs_apply(&self, r: &[f64], z: &mut [f64], work: &mut [f64]) {
        self.gs_sweep(r, work, true);
        for i in 0..self.n {
            work[i] *= self.diag_value(i);
        }
        self.gs_sweep(work, z, false);
    }
}

#[inline]
pub fn mean_abs(v: &[f64]) -> f64 {
    let s: f64 = v.iter().map(|x| x.abs()).sum();
    s / v.len().max(1) as f64
}

#[inline]
pub fn dot(a: &[f64], b: &[f64]) -> f64 {
    let mut s = 0.0f64;
    for i in 0..a.len() {
        s += a[i] * b[i];
    }
    s
}

/// PCG（可选 SGS 预条件）。收敛判据：res < max(tol, rel_tol * init_res)。
pub fn pcg(
    a: &Csr,
    b: &[f64],
    x: &mut [f64],
    tol: f64,
    rel_tol: f64,
    max_iter: usize,
    precond: bool,
) -> LinSolveInfo {
    let n = a.n;
    let mut r = vec![0.0f64; n];
    let mut z = vec![0.0f64; n];
    let mut p = vec![0.0f64; n];
    let mut ap = vec![0.0f64; n];
    let mut work = vec![0.0f64; n];
    a.matvec(x, &mut ap);
    for i in 0..n {
        r[i] = b[i] - ap[i];
    }
    let bnorm = mean_abs(b).max(1e-300);
    let init_res = mean_abs(&r) / bnorm;
    let target = (rel_tol * init_res).max(tol);
    if precond {
        a.sgs_apply(&r, &mut z, &mut work);
    } else {
        z.copy_from_slice(&r);
    }
    p.copy_from_slice(&z);
    let mut rho_old = dot(&r, &z);
    let mut res = init_res;
    let mut iters = 0usize;
    let mut breakdown = false;
    if res < target {
        return LinSolveInfo {
            iters: 0,
            init_res,
            final_res: res,
            converged: true,
            breakdown: false,
        };
    }
    for k in 0..max_iter {
        a.matvec(&p, &mut ap);
        let pap = dot(&p, &ap);
        if pap.abs() < 1e-300 {
            breakdown = true;
            break;
        }
        let alpha = rho_old / pap;
        for i in 0..n {
            x[i] += alpha * p[i];
            r[i] -= alpha * ap[i];
        }
        res = mean_abs(&r) / bnorm;
        iters = k + 1;
        if res < target {
            break;
        }
        if precond {
            a.sgs_apply(&r, &mut z, &mut work);
        } else {
            z.copy_from_slice(&r);
        }
        let rho_new = dot(&r, &z);
        if rho_old.abs() < 1e-300 {
            breakdown = true;
            break;
        }
        let beta = rho_new / rho_old;
        for i in 0..n {
            p[i] = z[i] + beta * p[i];
        }
        rho_old = rho_new;
    }
    LinSolveInfo {
        iters,
        init_res,
        final_res: res,
        converged: res < target,
        breakdown,
    }
}

/// 对称 Gauss-Seidel 平滑求解（对标 OpenFOAM smoothSolver 的 GaussSeidel smoother）：
/// 以 SGS 预条件子作为定常迭代 x ← x + M⁻¹(b−Ax)，逐扫更新真实残差。
/// 收敛判据与 [`pcg`] 一致：res < max(tol, rel_tol·init_res)。
pub fn sgs_solve(
    a: &Csr,
    b: &[f64],
    x: &mut [f64],
    tol: f64,
    rel_tol: f64,
    max_sweeps: usize,
) -> LinSolveInfo {
    let n = a.n;
    let mut r = vec![0.0f64; n];
    let mut z = vec![0.0f64; n];
    let mut work = vec![0.0f64; n];
    let mut ax = vec![0.0f64; n];
    a.matvec(x, &mut ax);
    for i in 0..n {
        r[i] = b[i] - ax[i];
    }
    let bnorm = mean_abs(b).max(1e-300);
    let init_res = mean_abs(&r) / bnorm;
    let target = (rel_tol * init_res).max(tol);
    let mut res = init_res;
    let mut sweeps = 0usize;
    if res < target {
        return LinSolveInfo { iters: 0, init_res, final_res: res, converged: true, breakdown: false };
    }
    for k in 0..max_sweeps {
        a.sgs_apply(&r, &mut z, &mut work);
        for i in 0..n {
            x[i] += z[i];
        }
        a.matvec(x, &mut ax);
        for i in 0..n {
            r[i] = b[i] - ax[i];
        }
        res = mean_abs(&r) / bnorm;
        sweeps = k + 1;
        if res < target {
            break;
        }
    }
    LinSolveInfo { iters: sweeps, init_res, final_res: res, converged: res < target, breakdown: false }
}

/// BiCGSTAB（左预条件，可选 SGS）。用于非对称动量矩阵（对标 smoothSolver）。
/// Van der Vorst (1992)；Saad §7.4。r 跟踪真实残差 b − Ax。
pub fn bicgstab(
    a: &Csr,
    b: &[f64],
    x: &mut [f64],
    tol: f64,
    rel_tol: f64,
    max_iter: usize,
    precond: bool,
) -> LinSolveInfo {
    let n = a.n;
    let mut r = vec![0.0f64; n];
    let mut r_hat = vec![0.0f64; n];
    let mut p = vec![0.0f64; n];
    let mut v = vec![0.0f64; n];
    let mut s = vec![0.0f64; n];
    let mut t = vec![0.0f64; n];
    let mut y = vec![0.0f64; n];
    let mut zs = vec![0.0f64; n];
    let mut work = vec![0.0f64; n];
    a.matvec(x, &mut v);
    for i in 0..n {
        r[i] = b[i] - v[i];
    }
    r_hat.copy_from_slice(&r);
    let bnorm = mean_abs(b).max(1e-300);
    let init_res = mean_abs(&r) / bnorm;
    let target = (rel_tol * init_res).max(tol);
    let mut res = init_res;
    let mut iters = 0usize;
    let mut breakdown = false;
    if res < target {
        return LinSolveInfo {
            iters: 0,
            init_res,
            final_res: res,
            converged: true,
            breakdown: false,
        };
    }
    let mut rho_old = 1.0f64;
    let mut alpha = 1.0f64;
    let mut omega = 1.0f64;
    for k in 0..max_iter {
        let rho = dot(&r_hat, &r);
        if rho.abs() < 1e-300 {
            breakdown = true;
            break;
        }
        if k == 0 {
            p.copy_from_slice(&r);
        } else {
            let beta = (rho / rho_old) * (alpha / omega);
            for i in 0..n {
                p[i] = r[i] + beta * (p[i] - omega * v[i]);
            }
        }
        if precond {
            a.sgs_apply(&p, &mut y, &mut work);
        } else {
            y.copy_from_slice(&p);
        }
        a.matvec(&y, &mut v);
        let rhv = dot(&r_hat, &v);
        if rhv.abs() < 1e-300 {
            breakdown = true;
            break;
        }
        alpha = rho / rhv;
        for i in 0..n {
            s[i] = r[i] - alpha * v[i];
        }
        res = mean_abs(&s) / bnorm;
        iters = k + 1;
        if res < target {
            for i in 0..n {
                x[i] += alpha * y[i];
            }
            break;
        }
        if precond {
            a.sgs_apply(&s, &mut zs, &mut work);
        } else {
            zs.copy_from_slice(&s);
        }
        a.matvec(&zs, &mut t);
        let tt = dot(&t, &t);
        if tt.abs() < 1e-300 {
            for i in 0..n {
                x[i] += alpha * y[i];
            }
            breakdown = true;
            break;
        }
        omega = dot(&t, &s) / tt;
        for i in 0..n {
            x[i] += alpha * y[i] + omega * zs[i];
            r[i] = s[i] - omega * t[i];
        }
        res = mean_abs(&r) / bnorm;
        if res < target {
            iters = k + 1;
            break;
        }
        if omega.abs() < 1e-300 {
            breakdown = true;
            break;
        }
        rho_old = rho;
    }
    LinSolveInfo {
        iters,
        init_res,
        final_res: res,
        converged: res < target,
        breakdown,
    }
}

