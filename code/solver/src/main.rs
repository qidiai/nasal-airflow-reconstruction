//! FlowScope 求解器 CLI
//!
//! 用法：
//!   flowscope check-mesh <caseDir>            读 polyMesh 并输出 checkMesh 口径统计
//!   flowscope case-info  <caseDir>            加载算例配置（constant/system/0）并核对契约
//!   flowscope run        <caseDir> [选项]     SIMPLE 求解（Run-A/Run-B 自动识别）
//!   flowscope poiseuille [选项]               内建解析验证（W4 硬门）

use std::path::Path;
use std::process::exit;
use std::time::Instant;

use flowscope_solver::simple::SimpleSolver;
use flowscope_solver::linalg::PrecondKind;
use flowscope_solver::{config::CaseConfig, meshio};

fn usage() {
    eprintln!(
        "用法:\n  \
         flowscope check-mesh <caseDir>\n  \
         flowscope case-info  <caseDir>\n  \
         flowscope run <caseDir> [--max-iter N] [--out DIR] [--quiet]\n  \
         flowscope poiseuille [--nx N --ny N --nz N --u-mean V --max-iter N]"
    );
}

/// 简易参数解析：--key value
fn arg_val(args: &[String], key: &str) -> Option<String> {
    args.iter()
        .position(|a| a == key)
        .and_then(|i| args.get(i + 1).cloned())
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 2 {
        usage();
        exit(2);
    }
    let cmd = args[1].as_str();
    match cmd {
        "check-mesh" => {
            if args.len() < 3 {
                usage();
                exit(2);
            }
            let t0 = Instant::now();
            let mesh = meshio::load_mesh(Path::new(&args[2])).unwrap_or_else(|e| {
                eprintln!("错误: {e}");
                exit(1);
            });
            print!("{}", mesh.check_report());
            eprintln!("（读取 + 几何计算耗时 {:.2}s）", t0.elapsed().as_secs_f64());
        }
        "case-info" => {
            if args.len() < 3 {
                usage();
                exit(2);
            }
            let cfg = CaseConfig::load(Path::new(&args[2])).unwrap_or_else(|e| {
                eprintln!("错误: {e}");
                exit(1);
            });
            cfg.print_report();
        }
        "run" => {
            if args.len() < 3 {
                usage();
                exit(2);
            }
            let quiet = args.iter().any(|a| a == "--quiet");
            let max_iter = arg_val(&args, "--max-iter").and_then(|v| v.parse::<usize>().ok());
            let out_dir = arg_val(&args, "--out").map(std::path::PathBuf::from);
            let p_cap = arg_val(&args, "--p-cap")
                .and_then(|v| v.parse().ok())
                .unwrap_or(3000usize);
            let alpha_p = arg_val(&args, "--alpha-p").and_then(|v| v.parse().ok());
            let alpha_u = arg_val(&args, "--alpha-u").and_then(|v| v.parse().ok());
            let write_every = arg_val(&args, "--write-every").and_then(|v| v.parse::<usize>().ok());
            let p_reltol = arg_val(&args, "--p-reltol").and_then(|v| v.parse::<f64>().ok());
            let init_csv = arg_val(&args, "--init-csv");
            let lu_dev = if args.iter().any(|a| a == "--no-lu") {
                Some(false)
            } else {
                None
            };
            let t0 = Instant::now();
            let mut solver = SimpleSolver::from_case_dir(Path::new(&args[2])).unwrap_or_else(|e| {
                eprintln!("错误: {e}");
                exit(1);
            });
            if let Some(path) = init_csv { solver.load_init_csv(Path::new(&path)).unwrap_or_else(|e| { eprintln!("错误: {e}"); exit(1); }); }
            if let Some(w) = write_every { solver.cfg.params.write_interval = w; }
            if let Some(rt) = p_reltol { solver.cfg.params.p_reltol = rt; solver.cfg.params.p_tol = 1e-9; }
            if let Err(e) =
                solver.run_adv(max_iter, out_dir.as_deref(), !quiet, p_cap, alpha_p, alpha_u, lu_dev)
            {
                eprintln!("错误: {e}");
                exit(1);
            }
            println!("---- 契约 §11 口径指标 ----");
            print!("{}", solver.contract_metrics());
            eprintln!("（求解耗时 {:.1}s）", t0.elapsed().as_secs_f64());
        }
        "poiseuille" => {
            let nx = arg_val(&args, "--nx").and_then(|v| v.parse().ok()).unwrap_or(200usize);
            let ny = arg_val(&args, "--ny").and_then(|v| v.parse().ok()).unwrap_or(21usize);
            let nz = arg_val(&args, "--nz").and_then(|v| v.parse().ok()).unwrap_or(1usize);
            let u_mean = arg_val(&args, "--u-mean")
                .and_then(|v| v.parse().ok())
                .unwrap_or(0.02f64);
            let max_iter = arg_val(&args, "--max-iter")
                .and_then(|v| v.parse().ok())
                .unwrap_or(20000usize);
            let h = 0.02f64; // 渠道高度 H (m)
            let l = 0.5f64; // 渠道长度 L (m)
            let w = 0.02f64; // z 向厚度（nz=1 时任意，零梯度=对称）
            let alpha_p = arg_val(&args, "--alpha-p")
                .and_then(|v| v.parse().ok())
                .unwrap_or(0.3f64);
            let alpha_u = arg_val(&args, "--alpha-u")
                .and_then(|v| v.parse().ok())
                .unwrap_or(0.7f64);
            let lu_dev = !args.iter().any(|a| a == "--no-lu");
            let t0 = Instant::now();
            let r = flowscope_solver::simple::run_poiseuille_adv(
                nx, ny, nz, h, l, w, u_mean, max_iter, true, alpha_p, alpha_u, lu_dev,
            )
            .unwrap_or_else(|e| {
                eprintln!("错误: {e}");
                exit(1);
            });
            println!("---- Poiseuille 解析验证（W4 硬门）----");
            println!(
                "mesh                : {} x {} x {} = {} cells（H={} m, L={} m, U_mean={} m/s）",
                r.nx, r.ny, r.nz, r.n_cells, h, l, r.u_mean
            );
            println!(
                "中心速度            : 数值 {:.8e} m/s vs 解析 {:.8e} m/s → 相对误差 {:.4}%（门 <1%）",
                r.u_center_num, r.u_center_exact, r.u_center_rel_err * 100.0
            );
            println!(
                "压降梯度 (kinematic): 数值 {:.8e} vs 解析 {:.8e} m/s² → 相对误差 {:.4}%（门 <2%）",
                r.dpdx_num, r.dpdx_exact, r.dpdx_rel_err * 100.0
            );
            println!(
                "压降梯度 (Pa/m)     : 数值 {:.8e} vs 解析 {:.8e}",
                r.dpdx_num_pa, r.dpdx_exact_pa
            );
            println!("迭代                : {} 步；{}", r.iterations, r.stop_reason);
            println!(
                "门判定              : {}",
                if r.gate_pass {
                    "PASS（中心速度 <1% 且 ΔP 梯度 <2%）"
                } else {
                    "FAIL —— 按任务书纪律：停止开发，写失败报告"
                }
            );
            eprintln!("（耗时 {:.1}s）", t0.elapsed().as_secs_f64());
            if !r.gate_pass {
                exit(4);
            }
        }
        "mesh-diag" => {
            use flowscope_solver::mesh::{dot, sub};
            if args.len() < 3 { usage(); exit(2); }
            let mesh = meshio::load_mesh(Path::new(&args[2])).unwrap_or_else(|e| { eprintln!("错误: {e}"); exit(1); });
            let mut kmin = f64::MAX; let mut kmax = f64::MIN; let mut kneg = 0usize;
            let mut dmin = f64::MAX; let mut dmax = 0.0f64;
            let mut lmin = f64::MAX; let mut lmax = f64::MIN;
            for f in 0..mesh.n_internal {
                let k = mesh.k_face(f);
                if k < kmin { kmin = k; } if k > kmax { kmax = k; } if k <= 0.0 { kneg += 1; }
                let o = mesh.face_owner[f] as usize; let n = mesh.face_neigh[f] as usize;
                let d = sub(mesh.cell_cc[n], mesh.cell_cc[o]);
                let dl = dot(d, d).sqrt();
                if dl < dmin { dmin = dl; } if dl > dmax { dmax = dl; }
                let lam = dot(sub(mesh.face_cf[f], mesh.cell_cc[o]), d) / dot(d, d);
                if lam < lmin { lmin = lam; } if lam > lmax { lmax = lam; }
            }
            let mut kbmin = f64::MAX; let mut kbmax = f64::MIN; let mut kbneg = 0usize;
            for f in mesh.n_internal..mesh.n_faces() {
                let kb = mesh.k_face_boundary(f);
                if kb < kbmin { kbmin = kb; } if kb > kbmax { kbmax = kb; } if kb <= 0.0 { kbneg += 1; }
            }
            let mut vmin = f64::MAX; let mut vmax = 0.0f64; let mut cmin = 0usize;
            for c in 0..mesh.n_cells() { let v = mesh.cell_vol[c]; if v < vmin { vmin = v; cmin = c; } if v > vmax { vmax = v; } }
            let mut nfmin = usize::MAX; let mut nfmax = 0usize;
            for c in 0..mesh.n_cells() { let nf = (mesh.cell_start[c+1]-mesh.cell_start[c]) as usize; if nf < nfmin { nfmin = nf; } if nf > nfmax { nfmax = nf; } }
            println!("internal faces      : {}  k_face min {:.6e} max {:.6e} neg {}", mesh.n_internal, kmin, kmax, kneg);
            println!("cell-centre dist    : min {:.6e} max {:.6e}  interp lam min {:.6} max {:.6}", dmin, dmax, lmin, lmax);
            println!("boundary k_b        : min {:.6e} max {:.6e} neg {} ({} faces)", kbmin, kbmax, kbneg, mesh.n_boundary_faces());
            println!("cell volume         : min {:.6e} (cell {}) max {:.6e}", vmin, cmin, vmax);
            println!("faces per cell      : min {} max {}", nfmin, nfmax);
            if let Some(c) = args.get(3).and_then(|s| s.parse::<usize>().ok()) {
                println!("---- cell {} ----", c);
                println!("cc ({:.8e}, {:.8e}, {:.8e})  V {:.8e}", mesh.cell_cc[c][0], mesh.cell_cc[c][1], mesh.cell_cc[c][2], mesh.cell_vol[c]);
                for f in mesh.cell_face_iter(c) {
                    let out = mesh.face_sf_out(f, c);
                    let sf = mesh.face_sf[f];
                    let nb = if f < mesh.n_internal { mesh.other_cell(f, c) } else { usize::MAX };
                    let dl = if nb != usize::MAX { dot(sub(mesh.cell_cc[nb], mesh.cell_cc[c]), sub(mesh.cell_cc[nb], mesh.cell_cc[c])).sqrt() } else { dot(sub(mesh.face_cf[f], mesh.cell_cc[c]), sub(mesh.face_cf[f], mesh.cell_cc[c])).sqrt() };
                    let k = if f < mesh.n_internal { mesh.k_face(f) } else { mesh.k_face_boundary(f) };
                    println!("  f {:8} owner {:8} nb {:8} |Sf| {:.6e} Sf_out ({:.4e},{:.4e},{:.4e}) |d| {:.6e} k {:.6e} phi0", f, mesh.face_owner[f], nb, mesh.face_mag[f], out[0], out[1], out[2], dl, k);
                }
            }
        }        "debug-box" => {
            // 盒网格体检：几何自洽性 + k_f 抽查
            let nx = arg_val(&args, "--nx").and_then(|v| v.parse().ok()).unwrap_or(20usize);
            let ny = arg_val(&args, "--ny").and_then(|v| v.parse().ok()).unwrap_or(11usize);
            let nz = arg_val(&args, "--nz").and_then(|v| v.parse().ok()).unwrap_or(1usize);
            let h = 0.02f64;
            let l = 0.5f64;
            let w = 0.02f64;
            let mesh = flowscope_solver::simple::build_box_mesh(
                nx,
                ny,
                nz,
                l / nx as f64,
                h / ny as f64,
                w / nz as f64,
            );
            print!("{}", mesh.check_report());
            let vtot: f64 = mesh.cell_vol.iter().sum();
            println!(
                "体积核对           : total {:.10e} vs 期望 {:.10e}（比值 {:.10}）",
                vtot,
                l * h * w,
                vtot / (l * h * w)
            );
            // k_f 抽查（前 5 个内部面）与 rAU 前提（动量对角 > 0）
            for f in 0..5usize.min(mesh.n_internal) {
                println!(
                    "k_face[{}]          : {:.6e}  Sf = ({:.3e}, {:.3e}, {:.3e})",
                    f,
                    mesh.k_face(f),
                    mesh.face_sf[f][0],
                    mesh.face_sf[f][1],
                    mesh.face_sf[f][2]
                );
            }
        }
        "debug-pcg" => {
            // 压力矩阵性质 + PCG 残差轨迹诊断
            use flowscope_solver::fields::{grad_vector, VolScalar, VolVector};
            use flowscope_solver::fvm::{
                assemble_momentum, assemble_pressure, bnd_pres_fixed_flags, compile_patches,
                hbya_flux,
            };
            use flowscope_solver::linalg::{bicgstab, pcg};
            let nx = arg_val(&args, "--nx").and_then(|v| v.parse().ok()).unwrap_or(20usize);
            let ny = arg_val(&args, "--ny").and_then(|v| v.parse().ok()).unwrap_or(11usize);
            let nz = arg_val(&args, "--nz").and_then(|v| v.parse().ok()).unwrap_or(1usize);
            let h = 0.02f64;
            let l = 0.5f64;
            let w = 0.02f64;
            let u_mean = 0.02f64;
            let mesh = flowscope_solver::simple::build_box_mesh(
                nx,
                ny,
                nz,
                l / nx as f64,
                h / ny as f64,
                w / nz as f64,
            );
            let bcs = flowscope_solver::simple::poiseuille_bcs(u_mean * h * w);
            let params = flowscope_solver::config::SolverParams::default();
            let cfg = flowscope_solver::config::CaseConfig::synthetic(bcs, params);
            let patches = compile_patches(&mesh, &cfg.bcs).unwrap();
            let bnd_pf = bnd_pres_fixed_flags(&mesh, &patches);
            let mut u = VolVector::zeros(&mesh);
            let _p = VolScalar::zeros(&mesh);
            let phi = vec![0.0f64; mesh.n_faces()];
            // BC 值
            let mut uu = u.clone();
            for pt in &patches {
                for f in pt.start..pt.start + pt.n_faces {
                    let bi = f - mesh.n_internal;
                    let c = mesh.face_owner[f] as usize;
                    uu.bnd[bi] = if pt.vel_fixed {
                        pt.vel_at(f)
                    } else {
                        uu.data[c]
                    };
                }
            }
            u = uu;
            let grad_u = grad_vector(&mesh, &u);
            let m = assemble_momentum(
                &mesh,
                cfg.nu,
                cfg.params.alpha_u,
                &patches,
                &phi,
                &u,
                &grad_u,
                true,
            );
            let csr = m.to_csr(&mesh);
            // HbyA = A^{-1} b（3 分量）
            let mut hbya = VolVector::zeros(&mesh);
            for comp in 0..3 {
                let b: Vec<f64> = m.source.iter().map(|s| s[comp]).collect();
                let mut x = vec![0.0f64; mesh.n_cells()];
                let info = bicgstab(&csr, &b, &mut x, 1e-10, 1e-3, 2000, true);
                println!(
                    "HbyA comp {comp}: init {:.3e} final {:.3e} iters {} breakdown {}",
                    info.init_res, info.final_res, info.iters, info.breakdown
                );
                for (i, v) in x.iter().enumerate() {
                    hbya.data[i][comp] = *v;
                }
            }
            let mut rau = vec![0.0f64; mesh.n_cells()];
            for c in 0..mesh.n_cells() {
                rau[c] = mesh.cell_vol[c] / csr.diag_value(c);
            }
            println!(
                "rAU: min {:.4e} max {:.4e}（负值个数 {}）",
                rau.iter().cloned().fold(f64::MAX, f64::min),
                rau.iter().cloned().fold(0.0f64, f64::max),
                rau.iter().filter(|&&v| v <= 0.0).count()
            );
            let dmin = (0..csr.n).map(|c| csr.diag_value(c)).fold(f64::MAX, f64::min);
            println!("momentum diag min  : {:.4e}", dmin);
            // HbyA 边界面值 + phiHbyA
            let mut hb = hbya.clone();
            for pt in &patches {
                for f in pt.start..pt.start + pt.n_faces {
                    let bi = f - mesh.n_internal;
                    let c = mesh.face_owner[f] as usize;
                    hb.bnd[bi] = if pt.vel_fixed {
                        pt.vel_at(f)
                    } else {
                        hb.data[c]
                    };
                }
            }
            let phi_hbya = hbya_flux(&mesh, &hb);
            let pm = assemble_pressure(&mesh, &patches, &rau, &phi_hbya, &bnd_pf);
            // 矩阵性质
            let pcsr = pm.to_csr(&mesh);
            let dmin = (0..pcsr.n).map(|c| pcsr.diag_value(c)).fold(f64::MAX, f64::min);
            let dmax = (0..pcsr.n).map(|c| pcsr.diag_value(c)).fold(0.0f64, f64::max);
            let bnorm: f64 = pm.source.iter().map(|x| x.abs()).sum::<f64>() / pcsr.n as f64;
            println!(
                "pressure diag      : min {:.4e} max {:.4e}；|b|_mean {:.4e}",
                dmin, dmax, bnorm
            );
            // 对称性抽查（转置检查代价高，抽查前 200 行）
            let mut asym = 0.0f64;
            for i in 0..pcsr.n.min(200) {
                let s = pcsr.row_ptr[i] as usize;
                let e = pcsr.row_ptr[i + 1] as usize;
                for k in s..e {
                    let j = pcsr.col[k] as usize;
                    if j == i {
                        continue;
                    }
                    // 找 (j,i)
                    let s2 = pcsr.row_ptr[j] as usize;
                    let e2 = pcsr.row_ptr[j + 1] as usize;
                    let mut found = None;
                    for k2 in s2..e2 {
                        if pcsr.col[k2] as usize == i {
                            found = Some(pcsr.val[k2]);
                        }
                    }
                    match found {
                        Some(v2) => asym = asym.max((pcsr.val[k] - v2).abs()),
                        None => asym = f64::MAX,
                    }
                }
            }
            println!("pressure symmetry  : max |A_ij − A_ji| = {:.4e}", asym);
            // RHS 尖峰与解量级
            let mut bmax = 0.0f64;
            let mut bmax_i = 0usize;
            for (i, v) in pm.source.iter().enumerate() {
                if v.abs() > bmax {
                    bmax = v.abs();
                    bmax_i = i;
                }
            }
            println!(
                "pressure |b|       : max {:.4e} at cell {}（cell 坐标 i={} j={}）",
                bmax,
                bmax_i,
                bmax_i % nx,
                bmax_i / nx
            );
            let mut x = vec![0.0f64; pcsr.n];
            let info = pcg(&pcsr, &pm.source, &mut x, 1e-6, 0.05, 300, PrecondKind::Sgs);
            let pmax_sol = x.iter().cloned().fold(0.0f64, |a, b| a.max(b.abs()));
            println!(
                "pcg(300 cap)       : init {:.4e} final {:.4e} iters {} conv {} breakdown {}",
                info.init_res, info.final_res, info.iters, info.converged, info.breakdown
            );
            println!("pressure sol |p|max: {:.4e}", pmax_sol);
            // 独立验证 A p − b
            let mut ax = vec![0.0f64; pcsr.n];
            pcsr.matvec(&x, &mut ax);
            let mut rn = 0.0f64;
            let mut bn = 0.0f64;
            for i in 0..pcsr.n {
                rn += (ax[i] - pm.source[i]).abs();
                bn += pm.source[i].abs();
            }
            println!(
                "独立验证 ||Ap−b||_1/||b||_1 = {:.4e}（|p| at inlet/outlet cells: {:.4e} / {:.4e}）",
                rn / bn.max(1e-300),
                x[nx / 2],
                x[nx - 1]
            );
        }
        _ => {
            usage();
            exit(2);
        }
    }
}




