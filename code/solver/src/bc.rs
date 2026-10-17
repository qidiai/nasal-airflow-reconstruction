//! 边界条件框架
//!
//! provenance：契约 §7（Run-A 定流量）与 §8（Run-B 等压）逐字段复刻。
//! - `flowRateInletVelocity`：OpenFOAM 用户手册 BC——patch 上均匀速度、法向入流、
//!   幅值 = volumetricFlowRate / patch 面积；方向取 patch 面积加权平均内法向
//!   （保证 Σ_f phi_f = −Q 精确成立，与契约 E15 归档实证同构）。
//! - `fixedValue uniform 80`：Run-B 双侧入口运动学压力（m²/s²）。
//! - `zeroGradient` / `fixedValue uniform (0 0 0)`（walls 无滑移）。

use crate::meshio::{dict_get, Dict};

/// 速度边界条件
#[derive(Debug, Clone)]
pub enum VelocityBC {
    /// 固定值（walls 无滑移 uniform (0 0 0)）
    FixedValue([f64; 3]),
    /// 零梯度（outlet、Run-B 入口）
    ZeroGradient,
    /// 定流量入口（Run-A）：q [m³/s]，patch 均匀法向速度，幅值 = q / A_patch
    FlowRateInlet { q: f64 },
}

/// 压力边界条件（运动学压力，m²/s²）
#[derive(Debug, Clone)]
pub enum PressureBC {
    FixedValue(f64),
    ZeroGradient,
}

#[derive(Debug, Clone)]
pub struct PatchBC {
    pub velocity: VelocityBC,
    pub pressure: PressureBC,
}

#[derive(Debug, Clone)]
pub struct BoundaryConditions {
    /// (patch 名, BC)，顺序同 polyMesh boundary
    pub patches: Vec<(String, PatchBC)>,
}

impl BoundaryConditions {
    pub fn get(&self, name: &str) -> Option<&PatchBC> {
        self.patches
            .iter()
            .find(|(n, _)| n == name)
            .map(|(_, bc)| bc)
    }

    pub fn names(&self) -> Vec<&str> {
        self.patches.iter().map(|(n, _)| n.as_str()).collect()
    }

    /// 从 0/U 与 0/p 的 boundaryField 子字典构建
    pub fn from_dicts(u: &Dict, p: &Dict) -> Result<Self, String> {
        let ubf = dict_get(u, "boundaryField")?.sub()?;
        let pbf = dict_get(p, "boundaryField")?.sub()?;
        let mut patches = Vec::new();
        for (name, e) in ubf {
            let d = e.sub()?;
            let btype = dict_get(d, "type")?.word()?.to_string();
            let velocity = match btype.as_str() {
                "fixedValue" => {
                    let v = dict_get(d, "value")?.vec3()?;
                    VelocityBC::FixedValue(v)
                }
                "zeroGradient" => VelocityBC::ZeroGradient,
                "flowRateInletVelocity" => {
                    let q = dict_get(d, "volumetricFlowRate")?.f64()?;
                    VelocityBC::FlowRateInlet { q }
                }
                other => {
                    return Err(format!(
                        "patch {name}: 不支持的 velocity BC 类型 '{other}'（清洁室只实现契约内类型）"
                    ))
                }
            };
            // 压力侧
            let pe = pbf
                .iter()
                .find(|(n, _)| n == name)
                .ok_or_else(|| format!("patch {name} 在 0/p boundaryField 中缺失"))?;
            let pd = pe.1.sub()?;
            let ptype = dict_get(pd, "type")?.word()?.to_string();
            let pressure = match ptype.as_str() {
                "fixedValue" => {
                    let v = dict_get(pd, "value")?.f64()?;
                    PressureBC::FixedValue(v)
                }
                "zeroGradient" => PressureBC::ZeroGradient,
                other => {
                    return Err(format!(
                        "patch {name}: 不支持的 pressure BC 类型 '{other}'"
                    ))
                }
            };
            patches.push((name.clone(), PatchBC { velocity, pressure }));
        }
        // 0/p 中多余的 patch 报错（防止漏读）
        for (name, _) in pbf {
            if !patches.iter().any(|(n, _)| n == name) {
                return Err(format!("patch {name} 在 0/U boundaryField 中缺失"));
            }
        }
        Ok(BoundaryConditions { patches })
    }

    /// Run 口径判定：任一 patch 为定流量入口 → Run-A；否则（等压 fixedValue）→ Run-B
    pub fn is_run_a(&self) -> bool {
        self.patches
            .iter()
            .any(|(_, bc)| matches!(bc.velocity, VelocityBC::FlowRateInlet { .. }))
    }
}
