//! 后处理指标与 VTK 输出
//!
//! provenance：契约 §11 后处理口径——
//! - `p_mean = rho·Σ_f p_f/N_f`（入口 patch **面数平均**，非质量加权；M1C3/GLM 复算实证）
//! - `dP = p_in − p_out`（p_out = outlet fixedValue 0）
//! - WSS 一阶体素估计 `tau = mu·|(I−nnᵀ)U_i|/d_n`（报告原文自述 O(dx) 偏差）
//! - 面积 `A = Σ_f A_f`；流量 `Q = Σ_f |U_f·n_f|·A_f`
//! - VTK 几何单位 m、速度 m/s、p 为运动学压力（m²/s²）

use crate::fields::VolScalar;
use crate::mesh::Mesh;
use crate::{RHO_AIR};

/// patch 通量求和（Σ_f phi_f，正 = 出流）
pub fn patch_flux_sum(mesh: &Mesh, phi: &[f64], pidx: usize) -> f64 {
    let p = &mesh.patches[pidx];
    let mut s = 0.0f64;
    for f in p.start..p.start + p.n_faces {
        s += phi[f];
    }
    s
}

/// patch 面积（Σ_f A_f）
pub fn patch_area(mesh: &Mesh, pidx: usize) -> f64 {
    let p = &mesh.patches[pidx];
    let mut a = 0.0f64;
    for f in p.start..p.start + p.n_faces {
        a += mesh.face_mag[f];
    }
    a
}

/// 入口 patch 组的面数平均运动学压力：Σ_f p_f / N_f（契约 §11，面数平均）
pub fn patch_face_mean_p(mesh: &Mesh, p: &VolScalar, pidx: usize) -> f64 {
    let pt = &mesh.patches[pidx];
    let mut s = 0.0f64;
    for f in pt.start..pt.start + pt.n_faces {
        s += p.bnd[f - mesh.n_internal];
    }
    s / pt.n_faces.max(1) as f64
}

/// dP（Pa）：多入口按面数合并平均后减出口平均，再乘 rho
pub fn dp_pa(mesh: &Mesh, p: &VolScalar, inlets: &[usize], outlet: usize) -> f64 {
    let mut num = 0.0f64;
    let mut den = 0usize;
    for &i in inlets {
        let pt = &mesh.patches[i];
        for f in pt.start..pt.start + pt.n_faces {
            num += p.bnd[f - mesh.n_internal];
        }
        den += pt.n_faces;
    }
    let p_in = if den > 0 { num / den as f64 } else { 0.0 };
    let p_out = patch_face_mean_p(mesh, p, outlet);
    RHO_AIR * (p_in - p_out)
}

/// 分流比（入口流量占比，按 patch）
pub fn flow_split(mesh: &Mesh, phi: &[f64], inlets: &[usize]) -> Vec<f64> {
    let qs: Vec<f64> = inlets.iter().map(|&i| -patch_flux_sum(mesh, phi, i)).collect();
    let tot: f64 = qs.iter().sum();
    if tot.abs() < 1e-300 {
        vec![0.0; qs.len()]
    } else {
        qs.iter().map(|q| q / tot).collect()
    }
}

/// WSS 一阶体素估计（契约 §11）：tau = mu·|(I−nnᵀ)U_i|/d_n，返回每壁面一个值（Pa）
pub fn wall_shear_stress(mesh: &Mesh, u: &crate::fields::VolVector, mu: f64, walls: usize) -> Vec<f64> {
    let p = &mesh.patches[walls];
    let mut out = Vec::with_capacity(p.n_faces);
    for f in p.start..p.start + p.n_faces {
        let c = mesh.face_owner[f] as usize;
        let n = mesh.face_sf[f];
        let nn = (n[0] * n[0] + n[1] * n[1] + n[2] * n[2]).sqrt();
        if nn <= 0.0 || mesh.face_mag[f] <= 0.0 {
            out.push(0.0);
            continue;
        }
        let nhat = [n[0] / nn, n[1] / nn, n[2] / nn];
        let uc = u.data[c];
        let un = uc[0] * nhat[0] + uc[1] * nhat[1] + uc[2] * nhat[2];
        let tang = [uc[0] - un * nhat[0], uc[1] - un * nhat[1], uc[2] - un * nhat[2]];
        let mag = (tang[0] * tang[0] + tang[1] * tang[1] + tang[2] * tang[2]).sqrt();
        // d_n：单元心到壁面的**法向距离**。
        // 第四棒修正（B6）：旧实现用 V/(2A_f)（"半格"），只在**完整面**上成立；
        // 阶梯网格的壁面大量是部分面（sliver），V/(2A) 会给出最大 50 mm 的假距离
        // （实测中位数 22 mm），把 WSS 压低 15 倍。归档 metrics 的 dn_mm_median
        // = 0.488 与本网格的 |C_f − C_c| 中位数 0.4883 mm 逐位吻合 → 用真实距离。
        let dvec = crate::mesh::sub(mesh.face_cf[f], mesh.cell_cc[c]);
        let d_n = crate::mesh::dot(dvec, dvec).sqrt();
        out.push(mu * mag / d_n.max(1e-300));
    }
    out
}

/// 向量场 Pearson 相关（3n 分量拼接；用于 L2 对拍）
pub fn vector_correlation(a: &[[f64; 3]], b: &[[f64; 3]]) -> f64 {
    assert_eq!(a.len(), b.len(), "向量场长度不一致");
    let n = a.len() * 3;
    if n == 0 {
        return 0.0;
    }
    let mut ma = 0.0f64;
    let mut mb = 0.0f64;
    for i in 0..a.len() {
        ma += a[i][0] + a[i][1] + a[i][2];
        mb += b[i][0] + b[i][1] + b[i][2];
    }
    ma /= n as f64;
    mb /= n as f64;
    let mut cov = 0.0f64;
    let mut va = 0.0f64;
    let mut vb = 0.0f64;
    for i in 0..a.len() {
        for k in 0..3 {
            let da = a[i][k] - ma;
            let db = b[i][k] - mb;
            cov += da * db;
            va += da * da;
            vb += db * db;
        }
    }
    if va <= 0.0 || vb <= 0.0 {
        return 0.0;
    }
    cov / (va.sqrt() * vb.sqrt())
}

/// 写 legacy ASCII VTK（UNSTRUCTURED_GRID，VTK_POLYHEDRON 单元 + CELL_DATA U/p）
pub fn vtk_write(path: &std::path::Path, mesh: &Mesh, u: &crate::fields::VolVector, p: &VolScalar) -> Result<(), String> {
    use std::fmt::Write as _;
    use std::fs::File;
    use std::io::Write as _;
    let mut f = File::create(path).map_err(|e| format!("创建 {} 失败: {e}", path.display()))?;
    let mut s = String::new();
    writeln!(s, "# vtk DataFile Version 3.0").ok();
    writeln!(s, "FlowScope self-developed FVM solver (cell-centred U, p)").ok();
    writeln!(s, "ASCII").ok();
    writeln!(s, "DATASET UNSTRUCTURED_GRID").ok();
    // POINTS
    writeln!(s, "POINTS {} double", mesh.points.len()).ok();
    for pt in &mesh.points {
        writeln!(s, "{:.10e} {:.10e} {:.10e}", pt[0], pt[1], pt[2]).ok();
    }
    // CELLS（polyhedron：nfaces, (npts ids)... 每面）
    let n_cells = mesh.n_cells();
    let mut cell_list_len = 1usize; // 每 cell 一个 nfaces 计数
    for c in 0..n_cells {
        let ns = mesh.cell_start[c] as usize;
        let ne = mesh.cell_start[c + 1] as usize;
        cell_list_len += 1; // nfaces
        for &fc in &mesh.cell_faces[ns..ne] {
            let fc = fc as usize;
            let fs = mesh.face_start[fc] as usize;
            let fe = mesh.face_start[fc + 1] as usize;
            cell_list_len += 1 + (fe - fs);
        }
    }
    writeln!(s, "CELLS {} {}", n_cells, cell_list_len).ok();
    for c in 0..n_cells {
        let ns = mesh.cell_start[c] as usize;
        let ne = mesh.cell_start[c + 1] as usize;
        let faces = &mesh.cell_faces[ns..ne];
        write!(s, "{}", faces.len()).ok();
        for &fc in faces {
            let fc = fc as usize;
            let fs = mesh.face_start[fc] as usize;
            let fe = mesh.face_start[fc + 1] as usize;
            write!(s, " {}", fe - fs).ok();
            for k in fs..fe {
                write!(s, " {}", mesh.face_nodes[k]).ok();
            }
        }
        writeln!(s).ok();
    }
    writeln!(s, "CELL_TYPES {}", n_cells).ok();
    for c in 0..n_cells {
        write!(s, "42").ok(); // VTK_POLYHEDRON
        if (c + 1) % 20 == 0 {
            writeln!(s).ok();
        } else {
            write!(s, " ").ok();
        }
    }
    writeln!(s).ok();
    // CELL_DATA
    writeln!(s, "CELL_DATA {}", n_cells).ok();
    writeln!(s, "VECTORS U double").ok();
    for c in 0..n_cells {
        writeln!(s, "{:.10e} {:.10e} {:.10e}", u.data[c][0], u.data[c][1], u.data[c][2]).ok();
    }
    writeln!(s, "SCALARS p double 1").ok();
    writeln!(s, "LOOKUP_TABLE default").ok();
    for c in 0..n_cells {
        writeln!(s, "{:.10e}", p.data[c]).ok();
    }
    f.write_all(s.as_bytes())
        .map_err(|e| format!("写 {} 失败: {e}", path.display()))
}
