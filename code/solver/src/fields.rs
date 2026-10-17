//! 场数据结构与 Gauss linear 插值 / 梯度
//!
//! provenance：契约 §5 `gradSchemes default Gauss linear` 与 `interpolationSchemes default linear`。
//! - 面值插值：面心在 P→N 连线上的投影比 λ（Versteeg & Malalasekera §4.4 双线性/线性插值）
//! - 单元梯度：Gauss 定理离散 grad_c φ = (1/V_c)·Σ_f S_f·φ_f

use crate::mesh::{dot, sub, Mesh};

/// 体心标量场（含边界面值；bnd 索引 = 全局面号 − n_internal）
#[derive(Debug, Clone)]
pub struct VolScalar {
    pub data: Vec<f64>,
    pub bnd: Vec<f64>,
}

impl VolScalar {
    pub fn zeros(mesh: &Mesh) -> Self {
        VolScalar {
            data: vec![0.0; mesh.n_cells()],
            bnd: vec![0.0; mesh.n_boundary_faces()],
        }
    }

    /// Gauss linear 面值（内部面：质心线性插值；边界面：patch 值）
    #[inline]
    pub fn face_value(&self, mesh: &Mesh, f: usize) -> f64 {
        if f < mesh.n_internal {
            let o = mesh.face_owner[f] as usize;
            let n = mesh.face_neigh[f] as usize;
            let d = sub(mesh.cell_cc[n], mesh.cell_cc[o]);
            let dd = dot(d, d);
            let lam = if dd > 0.0 {
                dot(sub(mesh.face_cf[f], mesh.cell_cc[o]), d) / dd
            } else {
                0.5
            };
            self.data[o] + lam * (self.data[n] - self.data[o])
        } else {
            self.bnd[f - mesh.n_internal]
        }
    }
}

/// 体心向量场
#[derive(Debug, Clone)]
pub struct VolVector {
    pub data: Vec<[f64; 3]>,
    pub bnd: Vec<[f64; 3]>,
}

impl VolVector {
    pub fn zeros(mesh: &Mesh) -> Self {
        VolVector {
            data: vec![[0.0; 3]; mesh.n_cells()],
            bnd: vec![[0.0; 3]; mesh.n_boundary_faces()],
        }
    }

    #[inline]
    pub fn face_value(&self, mesh: &Mesh, f: usize) -> [f64; 3] {
        if f < mesh.n_internal {
            let o = mesh.face_owner[f] as usize;
            let n = mesh.face_neigh[f] as usize;
            let d = sub(mesh.cell_cc[n], mesh.cell_cc[o]);
            let dd = dot(d, d);
            let lam = if dd > 0.0 {
                dot(sub(mesh.face_cf[f], mesh.cell_cc[o]), d) / dd
            } else {
                0.5
            };
            let (a, b) = (self.data[o], self.data[n]);
            [
                a[0] + lam * (b[0] - a[0]),
                a[1] + lam * (b[1] - a[1]),
                a[2] + lam * (b[2] - a[2]),
            ]
        } else {
            self.bnd[f - mesh.n_internal]
        }
    }
}

/// Gauss linear 标量梯度（每单元一个向量）
pub fn grad_scalar(mesh: &Mesh, fld: &VolScalar) -> Vec<[f64; 3]> {
    let mut g = vec![[0.0f64; 3]; mesh.n_cells()];
    for c in 0..mesh.n_cells() {
        let mut acc = [0.0f64; 3];
        for f in mesh.cell_face_iter(c) {
            let sf = mesh.face_sf_out(f, c);
            let v = fld.face_value(mesh, f);
            acc[0] += sf[0] * v;
            acc[1] += sf[1] * v;
            acc[2] += sf[2] * v;
        }
        let inv = 1.0 / mesh.cell_vol[c].max(1e-300);
        g[c] = [acc[0] * inv, acc[1] * inv, acc[2] * inv];
    }
    g
}

/// Gauss linear 向量梯度：返回 grad[i][j] = ∂u_i/∂x_j（一次过面遍历累积 9 分量）
pub fn grad_vector(mesh: &Mesh, fld: &VolVector) -> Vec<[[f64; 3]; 3]> {
    let mut g = vec![[[0.0f64; 3]; 3]; mesh.n_cells()];
    for c in 0..mesh.n_cells() {
        let mut acc = [[0.0f64; 3]; 3];
        for f in mesh.cell_face_iter(c) {
            let sf = mesh.face_sf_out(f, c);
            let v = fld.face_value(mesh, f);
            for i in 0..3 {
                acc[i][0] += sf[0] * v[i];
                acc[i][1] += sf[1] * v[i];
                acc[i][2] += sf[2] * v[i];
            }
        }
        let inv = 1.0 / mesh.cell_vol[c].max(1e-300);
        for i in 0..3 {
            g[c][i] = [acc[i][0] * inv, acc[i][1] * inv, acc[i][2] * inv];
        }
    }
    g
}
