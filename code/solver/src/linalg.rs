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
//!
//! W6 追加：压力 PCG 的 IC(0) 预条件子（pattern-based 不完全 Cholesky）。
//! provenance：Meijerink & van der Vorst 1977（Conjugate gradient type methods for
//! nonsymmetric and/or indefinite systems，IC(0) 对 M-矩阵无主元崩溃）、Saad
//! 《Iterative Methods for Sparse Linear Systems》§10.3.1（IC(0) 分解与行式 IKJ 实现）、
//! §10.3.2（对称 Jacobi 缩放改善条件数）；常数模两级加性修正见 Saad §13.2（deflation /
//! coarse-grid correction）。压力矩阵的对称性由 `fvm.rs assemble_pressure` 的单面系数
//! 结构性保证（upper[f] 与 lower[f] 写同一个 d），不需要延迟修正叙事。

use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::Instant;

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

    /// 返回行内列索引升序的副本，并重建 `diag_idx`（IC(0) 前置）。
    ///
    /// `from_fv` 产出的行序是「对角在前、其余按面序」，既非升序也不保证对角位置；
    /// IC(0) 的行式分解要求对行 i 与行 j 做列号归并（两者必须升序），故排序副本。
    /// 排序只在 IC(0) 路径使用，SGS 路径仍旧读原始矩阵——保证 A/B 的 sgs 臂与
    /// W5 基线逐位一致。
    ///
    /// 复杂度：每行插入排序，行宽 ≈ 7（7 点 stencil），实际 O(nnz·k) 且 k 为常数；
    /// 不必引入全局计数排序的额外临时数组。
    pub fn to_sorted(&self) -> Csr {
        let mut out = Csr {
            n: self.n,
            row_ptr: self.row_ptr.clone(),
            col: self.col.clone(),
            val: self.val.clone(),
            diag_idx: vec![0u32; self.n],
        };
        for i in 0..self.n {
            let s = self.row_ptr[i] as usize;
            let e = self.row_ptr[i + 1] as usize;
            for p in (s + 1)..e {
                let (c, v) = (out.col[p], out.val[p]);
                let mut q = p;
                while q > s && out.col[q - 1] > c {
                    out.col[q] = out.col[q - 1];
                    out.val[q] = out.val[q - 1];
                    q -= 1;
                }
                out.col[q] = c;
                out.val[q] = v;
            }
            for k in s..e {
                if out.col[k] as usize == i {
                    out.diag_idx[i] = k as u32;
                }
            }
        }
        out
    }
}

// ===========================================================================
// 预条件子选择（A/B 开关）与 IC(0) 实现
// ===========================================================================

/// 压力 PCG 预条件子类型。`FLOWSCOPE_PRECOND=sgs|ic0` 选择，未设或其它值 → sgs。
///
/// 两处 pcg 调用点（`simple.rs` 的 Run-B 位势流初始化与主循环压力方程）必须读同一开关，
/// 否则 A/B 对照会被初始化路径污染。默认值保持 sgs：四门全过后才在配置层翻 ic0。
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum PrecondKind {
    Sgs,
    Ic0,
}

impl PrecondKind {
    pub fn from_env() -> PrecondKind {
        match std::env::var("FLOWSCOPE_PRECOND")
            .map(|s| s.trim().to_ascii_lowercase())
            .as_deref()
        {
            Ok("ic0") | Ok("ic") | Ok("icc") | Ok("icholesky") => PrecondKind::Ic0,
            _ => PrecondKind::Sgs,
        }
    }

    pub fn tag(&self) -> &'static str {
        match self {
            PrecondKind::Sgs => "sgs",
            PrecondKind::Ic0 => "ic0",
        }
    }
}

/// 常数模 deflation 开关（`FLOWSCOPE_DEFLATE=1`，默认关）。仅对 IC(0) 生效。
///
/// 机理：压力矩阵的行和除 Dirichlet 锚定行外为 0，故 `1` 向量是**近零模**（唯一锚是
/// 出口 164 个 fixedValue 面）。IC(0) 对光滑长波模几乎无改善，而该模正是外层最慢模。
/// 加性两级修正 `z ← M_ic0^{-1} r + α·1`（α = Σr / (1ᵀA1)）是 SPD 加性项，不破坏
/// PCG 前提，且对近零模给出精确的粗网格解。
pub fn deflate_enabled() -> bool {
    std::env::var("FLOWSCOPE_DEFLATE").map(|v| v != "0").unwrap_or(false)
}

static IC0_FACTOR_COUNT: AtomicUsize = AtomicUsize::new(0);
static IC0_SHIFT_RESTARTS: AtomicUsize = AtomicUsize::new(0);
static IC0_FAILURES: AtomicUsize = AtomicUsize::new(0);
static IC0_FACTOR_MICROS: AtomicUsize = AtomicUsize::new(0);
static IC0_MEM_BYTES: AtomicUsize = AtomicUsize::new(0);

/// IC(0) 运行期统计（验收 §2.C 要求 shift 触发计数与分解开销）
#[derive(Debug, Clone, Copy)]
pub struct Ic0Stats {
    /// 成功完成的分解次数
    pub factors: usize,
    /// 因主元 ≤ τ 而**统一平移后重分解**的次数（目标 0）
    pub shift_restarts: usize,
    /// 分解彻底失败次数（此时 pcg 以 breakdown 返回，绝不回退 SGS）
    pub failures: usize,
    /// 累计分解耗时（秒）
    pub factor_secs: f64,
    /// 最近一次分解的内存占用（字节，含排序副本、L、Lᵀ、缩放向量）
    pub mem_bytes: usize,
}

pub fn ic0_reset_stats() {
    IC0_FACTOR_COUNT.store(0, Ordering::Relaxed);
    IC0_SHIFT_RESTARTS.store(0, Ordering::Relaxed);
    IC0_FAILURES.store(0, Ordering::Relaxed);
    IC0_FACTOR_MICROS.store(0, Ordering::Relaxed);
    IC0_MEM_BYTES.store(0, Ordering::Relaxed);
}

pub fn ic0_stats() -> Ic0Stats {
    Ic0Stats {
        factors: IC0_FACTOR_COUNT.load(Ordering::Relaxed),
        shift_restarts: IC0_SHIFT_RESTARTS.load(Ordering::Relaxed),
        failures: IC0_FAILURES.load(Ordering::Relaxed),
        factor_secs: IC0_FACTOR_MICROS.load(Ordering::Relaxed) as f64 * 1e-6,
        mem_bytes: IC0_MEM_BYTES.load(Ordering::Relaxed),
    }
}

/// 缩放过的主元下限（Jacobi 缩放后对角恒为 1，故 τ 直接是相对量）
const IC0_PIVOT_TAU: f64 = 1e-13;

/// IC(0) 分解结果：`A ≈ L Lᵀ`，L 只填 A 的下三角 pattern（含对角）。
///
/// 对称 Jacobi 缩放：解 `Â x̂ = b̂`，其中 `Â = D^{-1/2} A D^{-1/2}`、`D = diag(A)`。
/// 缩放把 rAU 80 倍变幅造成的行尺度差异压平（缩放后对角恒为 1）。
/// 缩放不改变解：`x = D^{-1/2} x̂`，回代末尾乘回 `D^{-1/2}`。
pub struct Ic0 {
    n: usize,
    /// L 的行指针（结构 = 排序后 A 的行结构）
    row_ptr: Vec<u32>,
    col: Vec<u32>,
    /// L 的值（严格下三角 + 对角；上三角位置恒 0 且不被读取）
    lval: Vec<f64>,
    diag_idx: Vec<u32>,
    /// 1 / L_ii
    inv_diag: Vec<f64>,
    /// Lᵀ 的行指针/列/值（仅严格上三角，即原 L 的严格下三角转置）
    lt_ptr: Vec<u32>,
    lt_col: Vec<u32>,
    lt_val: Vec<f64>,
    /// D^{-1/2}
    scale: Vec<f64>,
    /// 统一对角平移量（缩放空间，θ 从 0 开始，失败时 ×100 重试）
    shift: f64,
    /// 常数模 deflation 的粗网格分母 1ᵀA1（未缩放坐标，与 1 向量相容）
    coarse_den: f64,
    deflate: bool,
}

/// 分解单次尝试：失败（任一行主元 ≤ τ）返回 None。
fn ic0_factor_once(a: &Csr, scale: &[f64], shift: f64) -> Option<Vec<f64>> {
    let n = a.n;
    let mut lval = vec![0.0f64; a.val.len()];
    for i in 0..n {
        let s = a.row_ptr[i] as usize;
        let e = a.row_ptr[i + 1] as usize;
        let si = scale[i];
        // Â_ii = 1（Jacobi 缩放后）+ 统一平移
        let mut d = 1.0 + shift;
        let mut p = s;
        while p < e {
            let j = a.col[p] as usize;
            if j == i {
                p += 1;
                continue;
            }
            if j > i {
                break; // 行内升序：其后全是上三角，跳过（由行 j 负责）
            }
            // Â_ij
            let mut acc = a.val[p] * si * scale[j];
            // 归并 row_i 的 k<j（位置 s..p）与 row_j 的 k<j（位置 < diag_idx[j]）
            let mut pi = s;
            let mut pj = a.row_ptr[j] as usize;
            let pj_end = a.diag_idx[j] as usize;
            while pi < p && pj < pj_end {
                let ki = a.col[pi] as usize;
                let kj = a.col[pj] as usize;
                if ki == kj {
                    acc -= lval[pi] * lval[pj];
                    pi += 1;
                    pj += 1;
                } else if ki < kj {
                    pi += 1;
                } else {
                    pj += 1;
                }
            }
            let ljj = lval[pj_end];
            if !(ljj.abs() > 0.0) {
                return None;
            }
            let lij = acc / ljj;
            lval[p] = lij;
            d -= lij * lij;
            p += 1;
        }
        if !(d > IC0_PIVOT_TAU) {
            return None;
        }
        lval[a.diag_idx[i] as usize] = d.sqrt();
    }
    Some(lval)
}

impl Ic0 {
    /// 构建 IC(0) 因子。主元 ≤ τ 时**统一**平移全部对角后整体重分解
    /// （θ = 0, 1e-12, 1e-10, 1e-8, 1e-6）；绝不逐行回退、绝不回退 SGS
    /// —— 逐行混合 IC/对角会破坏预条件子的对称性，PCG 收敛理论失效。
    pub fn build(a: &Csr, deflate: bool) -> Result<Ic0, String> {
        let t0 = Instant::now();
        let n = a.n;
        let sorted = a.to_sorted();
        let mut scale = vec![0.0f64; n];
        for i in 0..n {
            let d = sorted.diag_value(i);
            if !(d > 0.0) || !d.is_finite() {
                IC0_FAILURES.fetch_add(1, Ordering::Relaxed);
                return Err(format!("第 {i} 行对角 {d:.3e} 非正（矩阵非 SPD）"));
            }
            scale[i] = 1.0 / d.sqrt();
        }

        let mut shift = 0.0f64;
        let mut lval: Option<Vec<f64>> = None;
        for attempt in 0..5 {
            if let Some(v) = ic0_factor_once(&sorted, &scale, shift) {
                lval = Some(v);
                break;
            }
            if attempt < 4 {
                IC0_SHIFT_RESTARTS.fetch_add(1, Ordering::Relaxed);
                shift = if attempt == 0 { 1e-12 } else { shift * 100.0 };
            }
        }
        let lval = match lval {
            Some(v) => v,
            None => {
                IC0_FAILURES.fetch_add(1, Ordering::Relaxed);
                return Err("IC(0) 在 5 档统一对角平移后仍有非正主元（矩阵非 M-矩阵/非 SPD）".into());
            }
        };
        IC0_FACTOR_COUNT.fetch_add(1, Ordering::Relaxed);

        // 1/L_ii
        let mut inv_diag = vec![0.0f64; n];
        for i in 0..n {
            let lii = lval[sorted.diag_idx[i] as usize];
            if lii.abs() < 1e-300 {
                IC0_FAILURES.fetch_add(1, Ordering::Relaxed);
                return Err(format!("第 {i} 行 L_ii ≈ 0"));
            }
            inv_diag[i] = 1.0 / lii;
        }

        // Lᵀ 的行结构：原 L 的 (i, j< i) 项 → Lᵀ 行的 (j, i)。计数排序 O(nnz)。
        let mut lt_len = vec![0u32; n];
        for i in 0..n {
            let (s, e) = (sorted.row_ptr[i] as usize, sorted.row_ptr[i + 1] as usize);
            for k in s..e {
                let j = sorted.col[k] as usize;
                if j < i {
                    lt_len[j] += 1;
                }
            }
        }
        let mut lt_ptr = vec![0u32; n + 1];
        for i in 0..n {
            lt_ptr[i + 1] = lt_ptr[i] + lt_len[i];
        }
        let lt_nnz = lt_ptr[n] as usize;
        let mut lt_col = vec![0u32; lt_nnz];
        let mut lt_val = vec![0.0f64; lt_nnz];
        let mut cursor = lt_ptr.clone();
        for i in 0..n {
            let (s, e) = (sorted.row_ptr[i] as usize, sorted.row_ptr[i + 1] as usize);
            for k in s..e {
                let j = sorted.col[k] as usize;
                if j < i {
                    // i 递增遍历 ⇒ 每行 Lᵀ 的列号天然升序
                    let q = cursor[j] as usize;
                    lt_col[q] = i as u32;
                    lt_val[q] = lval[k];
                    cursor[j] += 1;
                }
            }
        }

        // 常数模 deflation 的粗网格分母：1ᵀA1（未缩放坐标；A 对称，等于全部元素之和）
        let mut coarse_den = 0.0f64;
        if deflate {
            let mut row_sums = vec![0.0f64; n];
            for i in 0..n {
                let (s, e) = (a.row_ptr[i] as usize, a.row_ptr[i + 1] as usize);
                let mut rs = 0.0;
                for k in s..e {
                    rs += a.val[k];
                }
                row_sums[i] = rs;
            }
            coarse_den = row_sums.iter().sum();
            if !(coarse_den.abs() > 1e-300) {
                return Err(format!("1ᵀA1 = {coarse_den:.3e} 过小，无法做常数模修正"));
            }
        }

        let nnz = a.val.len();
        let mem_bytes = 2 * nnz * 8      // L 值 + Lᵀ 值
            + (nnz + lt_nnz) * 4         // L 列 + Lᵀ 列
            + 2 * (n + 1) * 4            // 两套行指针
            + (n * 8) * 2                // scale + inv_diag
            + n * 4;                     // diag_idx
        IC0_MEM_BYTES.store(mem_bytes, Ordering::Relaxed);
        IC0_FACTOR_MICROS.fetch_add(t0.elapsed().as_micros() as usize, Ordering::Relaxed);

        Ok(Ic0 {
            n,
            row_ptr: sorted.row_ptr.clone(),
            col: sorted.col.clone(),
            lval,
            diag_idx: sorted.diag_idx.clone(),
            inv_diag,
            lt_ptr,
            lt_col,
            lt_val,
            scale,
            shift,
            coarse_den,
            deflate,
        })
    }

    pub fn shift(&self) -> f64 {
        self.shift
    }

    pub fn mem_bytes(&self) -> usize {
        IC0_MEM_BYTES.load(Ordering::Relaxed)
    }

    /// z ≈ M⁻¹ r，M = L Lᵀ ≈ Â = D^{-1/2} A D^{-1/2}
    pub fn apply(&self, r: &[f64], z: &mut [f64], work: &mut [f64]) {
        // 前代：L y = D^{-1/2} r
        for i in 0..self.n {
            let s = self.row_ptr[i] as usize;
            let e = self.row_ptr[i + 1] as usize;
            let mut acc = r[i] * self.scale[i];
            for k in s..e {
                let j = self.col[k] as usize;
                if j >= i {
                    break; // 升序：下三角在前
                }
                acc -= self.lval[k] * work[j];
            }
            work[i] = acc * self.inv_diag[i];
        }
        // 回代：Lᵀ u = y（u 是中间量，绝不提前乘 D^{-1/2}），
        // 全部回代完成后再统一乘回 D^{-1/2} 得到 z = D^{-1/2} u。
        for i in (0..self.n).rev() {
            let s = self.lt_ptr[i] as usize;
            let e = self.lt_ptr[i + 1] as usize;
            let mut acc = work[i];
            for k in s..e {
                acc -= self.lt_val[k] * z[self.lt_col[k] as usize];
            }
            z[i] = acc * self.inv_diag[i];
        }
        for i in 0..self.n {
            z[i] *= self.scale[i];
        }
        // 常数模加性粗网格修正：z += α·1，α = Σr / (1ᵀA1)
        if self.deflate {
            let mut sum = 0.0f64;
            for v in r.iter() {
                sum += *v;
            }
            let alpha = sum / self.coarse_den;
            for v in z.iter_mut() {
                *v += alpha;
            }
        }
    }
}

// ===========================================================================
// 预检（SPD / M-矩阵）与 CSR 导出
// ===========================================================================

/// 压力矩阵体检结果（§3.2：SPD/M-矩阵预检）。
///
/// 对称性不再单独检查：`assemble_pressure` 对同一面系数 d 同时写 upper/lower，
/// 结构性对称是构造保证（查它恒等于 0，不能防范任何东西）。
/// 真正需要的四项：对角正、非对角非正（M-矩阵）、行和（对角占优余量）、nnz。
#[derive(Debug, Clone, Copy)]
pub struct MatrixCheck {
    pub n: usize,
    pub nnz: usize,
    pub min_diag: f64,
    pub max_diag: f64,
    pub max_offdiag: f64,
    pub n_pos_offdiag: usize,
    pub min_row_sum: f64,
    pub min_row_sum_rel: f64,
}

pub fn matrix_precheck(a: &Csr) -> MatrixCheck {
    let mut min_diag = f64::INFINITY;
    let mut max_diag = f64::NEG_INFINITY;
    let mut max_offdiag = f64::NEG_INFINITY;
    let mut n_pos_offdiag = 0usize;
    let mut min_row_sum = f64::INFINITY;
    let mut min_row_sum_rel = f64::INFINITY;
    for i in 0..a.n {
        let s = a.row_ptr[i] as usize;
        let e = a.row_ptr[i + 1] as usize;
        let mut row_sum = 0.0f64;
        let mut d = 0.0f64;
        for k in s..e {
            let v = a.val[k];
            row_sum += v;
            if a.col[k] as usize == i {
                d = v;
            } else if v > max_offdiag {
                max_offdiag = v;
            }
            if a.col[k] as usize != i && v > 0.0 {
                n_pos_offdiag += 1;
            }
        }
        min_diag = min_diag.min(d);
        max_diag = max_diag.max(d);
        min_row_sum = min_row_sum.min(row_sum);
        if d.abs() > 0.0 {
            min_row_sum_rel = min_row_sum_rel.min(row_sum / d.abs());
        }
    }
    MatrixCheck {
        n: a.n,
        nnz: a.val.len(),
        min_diag,
        max_diag,
        max_offdiag,
        n_pos_offdiag,
        min_row_sum,
        min_row_sum_rel,
    }
}

/// 一次性导出 CSR（`FLOWSCOPE_DUMP_PCSR=<path>`，调试用，不进常驻输出）。
/// 文本格式：首行 `FlowScopeCSR 1`、次行 `n nnz`，随后每行 `i j val`（17 位有效数字）。
pub fn dump_csr(a: &Csr, path: &str) -> std::io::Result<()> {
    use std::io::Write;
    let f = std::fs::File::create(path)?;
    let mut w = std::io::BufWriter::new(f);
    writeln!(w, "FlowScopeCSR 1")?;
    writeln!(w, "{} {}", a.n, a.val.len())?;
    for i in 0..a.n {
        let s = a.row_ptr[i] as usize;
        let e = a.row_ptr[i + 1] as usize;
        for k in s..e {
            writeln!(w, "{} {} {:.17e}", i, a.col[k], a.val[k])?;
        }
    }
    w.flush()
}

/// RHS 向量落盘（与 `dump_csr` 配套的离线 A/B 取证：同 A/b 下 SGS 与 IC(0) 解到 1e-10 比对）。
pub fn dump_vec(v: &[f64], path: &str) -> std::io::Result<()> {
    use std::io::Write;
    let f = std::fs::File::create(path)?;
    let mut w = std::io::BufWriter::new(f);
    writeln!(w, "FlowScopeVec 1")?;
    writeln!(w, "{}", v.len())?;
    for x in v.iter() {
        writeln!(w, "{:.17e}", x)?;
    }
    w.flush()
}

/// 冻结矩阵等价性检查（验收 §2.A）：同一 A、b、初值，SGS-PCG 与 IC(0)-PCG 各解到
/// 相对线性残差 1e-10，打印两侧迭代/终残差/收敛状态与 ‖x_ic0 − x_sgs‖/‖x_sgs‖。
///
/// 该检查把「预条件子实现正确性」与「SIMPLE 外层轨迹」解耦——不受外层未收敛态的干扰。
pub fn pcg_equiv_check(a: &Csr, b: &[f64], x0: &[f64], max_iter: usize, tag: &str) {
    let mut xs = x0.to_vec();
    let mut xi = x0.to_vec();
    let s = pcg(a, b, &mut xs, 0.0, 1e-10, max_iter, PrecondKind::Sgs);
    let i = pcg(a, b, &mut xi, 0.0, 1e-10, max_iter, PrecondKind::Ic0);
    let mut num = 0.0f64;
    let mut den = 0.0f64;
    for (p, q) in xs.iter().zip(xi.iter()) {
        num += (p - q) * (p - q);
        den += p * p;
    }
    let rel = num.sqrt() / den.sqrt().max(1e-300);
    println!(
        "[ab-check {tag}] sgs(it {} res {:.2e} conv {}) ic0(it {} res {:.2e} conv {}) rel_diff {:.3e}",
        s.iters, s.final_res, s.converged, i.iters, i.final_res, i.converged, rel
    );
    let st = ic0_stats();
    if st.shift_restarts > 0 || st.failures > 0 {
        println!(
            "[ab-check {tag}] IC(0) 异常：shift_restarts {} failures {}",
            st.shift_restarts, st.failures
        );
    }
}

/// 预条件子应用分派（保持 SGS 路径与 W5 基线逐位一致）
#[inline]
fn apply_precond(
    a: &Csr,
    ic0: Option<&Ic0>,
    kind: PrecondKind,
    r: &[f64],
    z: &mut [f64],
    work: &mut [f64],
) {
    if let Some(f) = ic0 {
        f.apply(r, z, work);
    } else if kind == PrecondKind::Sgs {
        a.sgs_apply(r, z, work);
    } else {
        z.copy_from_slice(r);
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

/// PCG（SGS 或 IC(0) 预条件）。收敛判据：res < max(tol, rel_tol * init_res)。
///
/// IC(0) 每次调用重新分解（矩阵每外层迭代都变）——分解是 O(nnz) 级，远小于数百次
/// 迭代的 O(nnz) 开销。分解失败时以 `breakdown=true` 返回并**不回退 SGS**
/// （回退会静默改变 A/B 口径；SPD 前提下 IC(0) 有 Meijerink–van der Vorst 保证）。
pub fn pcg(
    a: &Csr,
    b: &[f64],
    x: &mut [f64],
    tol: f64,
    rel_tol: f64,
    max_iter: usize,
    precond: PrecondKind,
) -> LinSolveInfo {
    let n = a.n;
    let ic0 = if precond == PrecondKind::Ic0 {
        match Ic0::build(a, deflate_enabled()) {
            Ok(f) => Some(f),
            Err(e) => {
                eprintln!("[pcg] IC(0) 分解失败（按纪律不回退 SGS）：{e}");
                let bnorm = mean_abs(b).max(1e-300);
                let mut ax = vec![0.0f64; n];
                a.matvec(x, &mut ax);
                let mut r0 = 0.0f64;
                for i in 0..n {
                    r0 += (b[i] - ax[i]).abs();
                }
                let init_res = r0 / n as f64 / bnorm;
                return LinSolveInfo {
                    iters: 0,
                    init_res,
                    final_res: init_res,
                    converged: false,
                    breakdown: true,
                };
            }
        }
    } else {
        None
    };
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
    apply_precond(a, ic0.as_ref(), precond, &r, &mut z, &mut work);
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
        apply_precond(a, ic0.as_ref(), precond, &r, &mut z, &mut work);
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


// ===========================================================================
// W6 调试用单元隔离测试
// ===========================================================================
#[cfg(test)]
mod tests {
    use super::*;

    /// 由稠密矩阵构造 CSR（行内升序，含显式零则跳过）
    fn csr_from_dense(d: &[Vec<f64>]) -> Csr {
        let n = d.len();
        let mut row_ptr = vec![0u32; n + 1];
        let mut col = Vec::new();
        let mut val = Vec::new();
        let mut diag_idx = vec![0u32; n];
        for i in 0..n {
            for j in 0..n {
                if d[i][j] != 0.0 {
                    if j == i {
                        diag_idx[i] = val.len() as u32;
                    }
                    col.push(j as u32);
                    val.push(d[i][j]);
                }
            }
            row_ptr[i + 1] = val.len() as u32;
        }
        Csr { n, row_ptr, col, val, diag_idx }
    }

    fn laplace_1d(n: usize) -> Vec<Vec<f64>> {
        let mut a = vec![vec![0.0f64; n]; n];
        for i in 0..n {
            a[i][i] = 2.0;
            if i > 0 { a[i][i - 1] = -1.0; }
            if i + 1 < n { a[i][i + 1] = -1.0; }
        }
        a
    }

    fn poisson_2d(nx: usize, ny: usize) -> Vec<Vec<f64>> {
        let n = nx * ny;
        let mut a = vec![vec![0.0f64; n]; n];
        let id = |x: usize, y: usize| y * nx + x;
        for y in 0..ny {
            for x in 0..nx {
                let i = id(x, y);
                a[i][i] = 4.0;
                if x > 0 { a[i][id(x - 1, y)] = -1.0; }
                if x + 1 < nx { a[i][id(x + 1, y)] = -1.0; }
                if y > 0 { a[i][id(x, y - 1)] = -1.0; }
                if y + 1 < ny { a[i][id(x, y + 1)] = -1.0; }
            }
        }
        a
    }

    /// 稠密高斯消元（部分主元），返回 x = A^{-1} b
    fn dense_solve(a: &[Vec<f64>], b: &[f64]) -> Vec<f64> {
        let n = b.len();
        let mut m: Vec<Vec<f64>> = a.iter().map(|r| r.clone()).collect();
        let mut x = b.to_vec();
        for k in 0..n {
            let mut piv = k;
            for i in (k + 1)..n {
                if m[i][k].abs() > m[piv][k].abs() { piv = i; }
            }
            m.swap(k, piv);
            x.swap(k, piv);
            let d = m[k][k];
            for j in k..n { m[k][j] /= d; }
            x[k] /= d;
            for i in 0..n {
                if i != k && m[i][k] != 0.0 {
                    let f = m[i][k];
                    for j in k..n { m[i][j] -= f * m[k][j]; }
                    x[i] -= f * x[k];
                }
            }
        }
        x
    }

    fn l_entry(f: &Ic0, i: usize, j: usize) -> f64 {
        if j > i { return 0.0; }
        let (s, e) = (f.row_ptr[i] as usize, f.row_ptr[i + 1] as usize);
        for k in s..e {
            let c = f.col[k] as usize;
            if c == j { return f.lval[k]; }
            if c > j { break; }
        }
        0.0
    }

    #[test]
    fn t1_factor_no_nan_and_llt_matches() {
        for &n in &[5usize, 10, 50] {
            let a = csr_from_dense(&laplace_1d(n));
            let f = Ic0::build(&a, false).expect("build ok");
            let mut maxdiff = 0.0f64;
            let mut min_diag = f64::INFINITY;
            let mut all_finite = true;
            for v in f.lval.iter() {
                all_finite &= v.is_finite();
            }
            for i in 0..n {
                let s = f.row_ptr[i] as usize;
                let e = f.row_ptr[i + 1] as usize;
                for k in s..e {
                    let j = f.col[k] as usize;
                    let mut m = 0.0;
                    for kk in 0..=i.min(j) {
                        m += l_entry(&f, i, kk) * l_entry(&f, j, kk);
                    }
                    let ahat = a.val[k] * f.scale[i] * f.scale[j];
                    maxdiff = maxdiff.max((m - ahat).abs());
                }
                min_diag = min_diag.min(l_entry(&f, i, i));
            }
            println!("t1 n={n} llT maxdiff {maxdiff:.3e} min diag(L) {min_diag:.3e}");
            assert!(maxdiff < 1e-10, "L L^T != Ahat, maxdiff {maxdiff}");
            assert!(all_finite, "L 含 NaN/Inf");
            assert!(min_diag > 0.0, "L 对角非正");
        }
    }

    #[test]
    fn t2_apply_is_inverse() {
        for &n in &[10usize, 40] {
            let a = csr_from_dense(&laplace_1d(n));
            let f = Ic0::build(&a, false).expect("build ok");
            let mut work = vec![0.0f64; n];
            let mut z = vec![0.0f64; n];
            let mut worst = 0.0f64;
            for p in 0..n {
                let mut r = vec![0.0f64; n];
                r[p] = 1.0;
                f.apply(&r, &mut z, &mut work);
                let exact = dense_solve(&laplace_1d(n), &r);
                let mut num = 0.0;
                let mut den = 0.0;
                for i in 0..n {
                    num += (z[i] - exact[i]) * (z[i] - exact[i]);
                    den += exact[i] * exact[i];
                }
                worst = worst.max((num / den).sqrt());
            }
            println!("t2 n={n} worst rel err of M^-1 e_i vs A^-1 e_i: {worst:.3e}");
            assert!(worst < 1e-6, "precond apply wrong, rel err {worst}");
        }
    }

    #[test]
    fn t3_pcg_direct_residual() {
        for &(nx, ny) in &[(10usize, 10usize), (20, 20)] {
            let dense = poisson_2d(nx, ny);
            let a = csr_from_dense(&dense);
            let n = a.n;
            let b: Vec<f64> = (0..n).map(|i| ((i * 37 % 101) as f64) - 50.0).collect();
            let x0 = vec![0.0f64; n];
            for kind in [PrecondKind::Sgs, PrecondKind::Ic0] {
                let mut x = x0.clone();
                let info = pcg(&a, &b, &mut x, 0.0, 1e-10, 3000, kind);
                let mut ax = vec![0.0f64; n];
                a.matvec(&x, &mut ax);
                let mut num = 0.0;
                let mut den = 0.0;
                for i in 0..n {
                    num += (ax[i] - b[i]).abs();
                    den += b[i].abs();
                }
                let direct = num / den;
                println!(
                    "t3 {:?} n={n} iters {} reported {:.3e} conv {} breakdown {} | direct relres {:.3e}",
                    kind, info.iters, info.final_res, info.converged, info.breakdown, direct
                );
                assert!(direct < 1e-8, "{:?} direct residual too large: {direct}", kind);
            }
        }
    }
}
