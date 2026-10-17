//! 算例配置加载：constant/ + system/ + 0/ 全量读取，契约字段断言
//!
//! provenance：契约 §3（物性）、§4（fvSolution）、§5（fvSchemes）、§6（controlDict）、
//! §7/§8（BC）。读取的是归档算例配置文件；与契约不符处记入 notes 如实上报（不静默修改）。

use std::path::{Path, PathBuf};

use crate::bc::BoundaryConditions;
use crate::meshio::{dict_get, parse_foam_file};

/// 运行口径
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RunMode {
    /// Run-A：定流量入口（flowRateInletVelocity），出口 p fixedValue 0
    RunA,
    /// Run-B：等压入口（p fixedValue 80），速度全 zeroGradient
    RunB,
}

impl std::fmt::Display for RunMode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            RunMode::RunA => write!(f, "Run-A(定流量)"),
            RunMode::RunB => write!(f, "Run-B(等压)"),
        }
    }
}

/// 线性求解器与 SIMPLE 参数（契约 §4 实证值）
#[derive(Debug, Clone)]
pub struct SolverParams {
    pub p_tol: f64,
    pub p_reltol: f64,
    pub u_tol: f64,
    pub u_reltol: f64,
    pub residual_p: f64,
    pub residual_u: f64,
    pub alpha_p: f64,
    pub alpha_u: f64,
    pub n_nonortho: usize,
    pub max_iter: usize,
    pub write_interval: usize,
    /// 诊断开关：linearUpwind 高阶外插偏差（false = 纯 upwind）
    pub lu_deviation: bool,
}

impl Default for SolverParams {
    fn default() -> Self {
        // 契约 §4/§6 实证值（与归档 fvSolution/controlDict 逐字段一致）
        SolverParams {
            p_tol: 1e-6,
            p_reltol: 0.05,
            u_tol: 1e-5,
            u_reltol: 0.01,
            residual_p: 1e-4,
            residual_u: 1e-4,
            alpha_p: 0.3,
            alpha_u: 0.7,
            n_nonortho: 0,
            max_iter: 1500,
            write_interval: 500,
            lu_deviation: true,
        }
    }
}

#[derive(Debug, Clone)]
pub struct CaseConfig {
    pub case_dir: PathBuf,
    pub nu: f64,
    pub rho: f64,
    pub mu: f64,
    pub run: RunMode,
    pub bcs: BoundaryConditions,
    pub params: SolverParams,
    /// 契约核对备注（不符项如实记录，不静默吞掉）
    pub notes: Vec<String>,
}

impl CaseConfig {
    /// 从算例目录加载全部配置。契约未覆盖行为以归档文件为唯一裁决源。
    pub fn load(case_dir: &Path) -> Result<Self, String> {
        let mut notes: Vec<String> = Vec::new();
        // ---- constant/transportProperties ----
        let tp = parse_foam_file(&case_dir.join("constant").join("transportProperties"))?;
        let nu = dict_get(&tp, "nu")?.f64()?;
        if (nu - 1.800e-05).abs() > 1e-12 {
            notes.push(format!(
                "契约钉住 nu=1.800e-05，归档实际 {nu:.6e} —— 以归档为准"
            ));
        }
        // ---- constant/turbulenceProperties ----
        let tb = parse_foam_file(
            &case_dir
                .join("constant")
                .join("turbulenceProperties"),
        )?;
        match dict_get(&tb, "simulationType") {
            Ok(e) => {
                let s = e.word()?;
                if s != "laminar" {
                    notes.push(format!("契约钉住 laminar，归档 simulationType={s}"));
                }
            }
            Err(_) => notes.push("constant/turbulenceProperties 无 simulationType".into()),
        }
        let rho = 1.2f64; // 契约 §11 后处理口径
        let mu = rho * nu;
        // ---- system/fvSolution ----
        let mut params = SolverParams::default();
        let fs = parse_foam_file(&case_dir.join("system").join("fvSolution"))?;
        if let Ok(e) = dict_get(&fs, "solvers.p.tolerance") {
            params.p_tol = e.f64()?;
        }
        if let Ok(e) = dict_get(&fs, "solvers.p.relTol") {
            params.p_reltol = e.f64()?;
        }
        if let Ok(e) = dict_get(&fs, "solvers.U.tolerance") {
            params.u_tol = e.f64()?;
        }
        if let Ok(e) = dict_get(&fs, "solvers.U.relTol") {
            params.u_reltol = e.f64()?;
        }
        match dict_get(&fs, "SIMPLE.residualControl.p") {
            Ok(e) => params.residual_p = e.f64()?,
            Err(_) => notes.push("fvSolution 无 SIMPLE.residualControl.p（默认 1e-4）".into()),
        }
        match dict_get(&fs, "SIMPLE.residualControl.U") {
            Ok(e) => params.residual_u = e.f64()?,
            Err(_) => notes.push("fvSolution 无 SIMPLE.residualControl.U（默认 1e-4）".into()),
        }
        if (params.residual_p - 1e-4).abs() > 1e-12 || (params.residual_u - 1e-4).abs() > 1e-12 {
            notes.push(format!(
                "契约红线 residualControl p/U = 1e-4/1e-4，归档 p={} U={}",
                params.residual_p, params.residual_u
            ));
        }
        match dict_get(&fs, "relaxationFactors.fields.p") {
            Ok(e) => params.alpha_p = e.f64()?,
            Err(_) => notes.push("fvSolution 无 relaxationFactors.fields.p（默认 0.3）".into()),
        }
        match dict_get(&fs, "relaxationFactors.equations.U") {
            Ok(e) => params.alpha_u = e.f64()?,
            Err(_) => notes.push("fvSolution 无 relaxationFactors.equations.U（默认 0.7）".into()),
        }
        match dict_get(&fs, "SIMPLE.nNonOrthogonalCorrectors") {
            Ok(e) => params.n_nonortho = e.usize()?,
            Err(_) => notes.push("fvSolution 无 nNonOrthogonalCorrectors（默认 0）".into()),
        }
        // ---- system/controlDict ----
        let cd = parse_foam_file(&case_dir.join("system").join("controlDict"))?;
        match dict_get(&cd, "endTime") {
            Ok(e) => params.max_iter = e.usize()?,
            Err(_) => notes.push("controlDict 无 endTime（默认 1500）".into()),
        }
        match dict_get(&cd, "writeInterval") {
            Ok(e) => params.write_interval = e.usize()?,
            Err(_) => notes.push("controlDict 无 writeInterval（默认 500）".into()),
        }
        // ---- system/fvSchemes（契约红线核对）----
        let sc = parse_foam_file(&case_dir.join("system").join("fvSchemes"))?;
        match dict_get(&sc, "divSchemes.div(phi,U)") {
            Ok(e) => {
                let s = e.word()?;
                if !s.contains("bounded") || !s.contains("linearUpwind") {
                    notes.push(format!(
                        "契约红线 div(phi,U)=bounded Gauss linearUpwind grad(U)，归档为 '{s}'"
                    ));
                }
            }
            Err(_) => notes.push("fvSchemes 无 div(phi,U)".into()),
        }
        match dict_get(&sc, "laplacianSchemes.default") {
            Ok(e) => {
                let s = e.word()?;
                if s != "Gauss linear corrected" {
                    notes.push(format!("契约钉住 laplacian=Gauss linear corrected，归档 '{s}'"));
                }
            }
            Err(_) => notes.push("fvSchemes 无 laplacianSchemes.default".into()),
        }
        match dict_get(&sc, "snGradSchemes.default") {
            Ok(e) => {
                let s = e.word()?;
                if s != "corrected" {
                    notes.push(format!("契约钉住 snGrad=corrected，归档 '{s}'"));
                }
            }
            Err(_) => notes.push("fvSchemes 无 snGradSchemes.default".into()),
        }
        match dict_get(&sc, "ddtSchemes.default") {
            Ok(e) => {
                let s = e.word()?;
                if s != "steadyState" {
                    notes.push(format!("契约钉住 ddt=steadyState，归档 '{s}'"));
                }
            }
            Err(_) => notes.push("fvSchemes 无 ddtSchemes.default".into()),
        }
        // ---- 0/U 与 0/p ----
        let u = parse_foam_file(&case_dir.join("0").join("U"))?;
        let p = parse_foam_file(&case_dir.join("0").join("p"))?;
        let bcs = BoundaryConditions::from_dicts(&u, &p)?;
        let run = if bcs.is_run_a() {
            RunMode::RunA
        } else {
            RunMode::RunB
        };
        // Run-B 口径核对：入口 patch（inlet*）应为 fixedValue 80
        if run == RunMode::RunB {
            for (name, bc) in &bcs.patches {
                if name.starts_with("inlet") {
                    if let crate::bc::PressureBC::FixedValue(v) = bc.pressure {
                        if (v - 80.0).abs() > 1e-9 {
                            notes.push(format!("Run-B 入口 {name} fixedValue {v} != 契约 80"));
                        }
                    }
                }
            }
        }
        Ok(CaseConfig {
            case_dir: case_dir.to_path_buf(),
            nu,
            rho,
            mu,
            run,
            bcs,
            params,
            notes,
        })
    }

    /// 合成算例（解析验证用，不从归档文件加载）
    pub fn synthetic(bcs: BoundaryConditions, params: SolverParams) -> Self {
        CaseConfig {
            case_dir: PathBuf::from("<synthetic>"),
            nu: crate::NU_AIRWAY,
            rho: crate::RHO_AIR,
            mu: crate::MU_AIR,
            run: RunMode::RunA,
            bcs,
            params,
            notes: vec!["合成算例（Poiseuille 解析验证用，非归档 case）".into()],
        }
    }

    pub fn print_report(&self) {
        println!("== FlowScope 算例配置 ==");
        println!("case dir : {}", self.case_dir.display());
        println!("run mode : {}", self.run);
        println!("nu       : {:.6e} m2/s（laminar Newtonian）", self.nu);
        println!(
            "rho/mu   : {:.3} kg/m3 / {:.6e} Pa·s（仅后处理口径）",
            self.rho, self.mu
        );
        println!("SIMPLE   : maxIter {}  writeInterval {}", self.params.max_iter, self.params.write_interval);
        println!(
            "relax    : p {}  U {}   residualControl p {} U {}",
            self.params.alpha_p, self.params.alpha_u, self.params.residual_p, self.params.residual_u
        );
        println!(
            "linear   : p tol {} relTol {}   U tol {} relTol {}   nNonOrtho {}",
            self.params.p_tol,
            self.params.p_reltol,
            self.params.u_tol,
            self.params.u_reltol,
            self.params.n_nonortho
        );
        println!("boundary :");
        for (name, bc) in &self.bcs.patches {
            println!(
                "    {:<8} U = {:<28} p = {}",
                name,
                format!("{:?}", bc.velocity),
                format!("{:?}", bc.pressure)
            );
        }
        if self.notes.is_empty() {
            println!("契约核对 : 全部字段与 numerical-contract.md v1.0 一致");
        } else {
            println!("契约核对 : {} 条备注（如实记录）", self.notes.len());
            for n in &self.notes {
                println!("    ! {n}");
            }
        }
    }
}
