//! 网格数据结构与几何量计算
//!
//! provenance：OpenFOAM ascii polyMesh 数据格式（归档 mesh 文件，非实现源码）；
//! 几何量算法为标准多面体 FVM 几何：
//! - 面面积向量：Newell 法（对多边形顶点序按右手规则求和，与 OpenFOAM face::normal 同口径）
//! - 面心：多边形扇形三角化的面积加权重心
//! - 单元体积：散度定理 V = (1/3)·Σ_f C_f·S_f（平面 faces 下精确，与原点选取无关）
//! - 单元重心：面-单元心 tet 分解的体积加权平均（OpenFOAM cell::centre 同口径）
//! - k_f = S_f·Δ/|Δ|²（非正交 laplacian 的正交分量系数，Versteeg & Malalasekera §7.4）

/// patch 定义（对应 polyMesh/boundary 文件的一项）
#[derive(Debug, Clone)]
pub struct Patch {
    pub name: String,
    pub ptype: String,
    pub start: usize,
    pub n_faces: usize,
}

/// 有限体积网格（cell-centred）。
/// faces[0..n_internal] 为内部面（owner→neighbour 的 Sf 朝向），
/// faces[n_internal..] 为边界面（Sf 指向域外，属于某个 patch）。
#[derive(Debug, Clone)]
pub struct Mesh {
    pub points: Vec<[f64; 3]>,
    /// 扁平 CSR：face_nodes[face_start[f]..face_start[f+1]] 为第 f 个面的节点号
    pub face_nodes: Vec<u32>,
    pub face_start: Vec<u32>,
    pub face_owner: Vec<u32>,
    /// 边界面为 u32::MAX
    pub face_neigh: Vec<u32>,
    /// 面积向量（owner→neighbour 朝向；边界面指向域外）
    pub face_sf: Vec<[f64; 3]>,
    pub face_cf: Vec<[f64; 3]>,
    pub face_mag: Vec<f64>,
    pub n_internal: usize,
    /// 扁平 CSR：cell_faces[cell_start[c]..cell_start[c+1]] 为单元 c 的所有面
    pub cell_faces: Vec<u32>,
    pub cell_start: Vec<u32>,
    pub cell_cc: Vec<[f64; 3]>,
    pub cell_vol: Vec<f64>,
    pub patches: Vec<Patch>,
}

/// 边界面标记（face_neigh 中）
pub const BOUNDARY: u32 = u32::MAX;

#[inline]
pub fn sub(a: [f64; 3], b: [f64; 3]) -> [f64; 3] {
    [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
}

#[inline]
pub fn dot(a: [f64; 3], b: [f64; 3]) -> f64 {
    a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}

#[inline]
pub fn cross(a: [f64; 3], b: [f64; 3]) -> [f64; 3] {
    [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]
}

#[inline]
pub fn norm(a: [f64; 3]) -> f64 {
    dot(a, a).sqrt()
}

#[inline]
fn sf_out(face_owner: &[u32], face_sf: &[[f64; 3]], f: usize, c: usize) -> [f64; 3] {
    if face_owner[f] as usize == c {
        face_sf[f]
    } else {
        [-face_sf[f][0], -face_sf[f][1], -face_sf[f][2]]
    }
}

/// Newell 法面积向量：对节点序按右手规则累加（OpenFOAM face::normal 同口径）
pub fn newell_area(points: &[[f64; 3]], nodes: &[u32]) -> [f64; 3] {
    let mut n = [0.0f64; 3];
    let m = nodes.len();
    if m < 3 {
        return n;
    }
    for i in 0..m {
        let a = points[nodes[i] as usize];
        let b = points[nodes[(i + 1) % m] as usize];
        n[0] += 0.5 * (a[1] * b[2] - a[2] * b[1]);
        n[1] += 0.5 * (a[2] * b[0] - a[0] * b[2]);
        n[2] += 0.5 * (a[0] * b[1] - a[1] * b[0]);
    }
    n
}

/// 多边形扇形三角化的面积加权重心（平面 faces 下精确）
pub fn polygon_centroid(points: &[[f64; 3]], nodes: &[u32]) -> [f64; 3] {
    let m = nodes.len();
    if m < 3 {
        let mut c = [0.0f64; 3];
        for &nd in nodes {
            let p = points[nd as usize];
            c[0] += p[0];
            c[1] += p[1];
            c[2] += p[2];
        }
        let k = nodes.len().max(1) as f64;
        return [c[0] / k, c[1] / k, c[2] / k];
    }
    let p0 = points[nodes[0] as usize];
    let mut c = [0.0f64; 3];
    let mut a_sum = 0.0f64;
    for i in 1..m - 1 {
        let p1 = points[nodes[i] as usize];
        let p2 = points[nodes[i + 1] as usize];
        let cr = cross(sub(p1, p0), sub(p2, p0));
        let a = 0.5 * norm(cr);
        c[0] += a * (p0[0] + p1[0] + p2[0]) / 3.0;
        c[1] += a * (p0[1] + p1[1] + p2[1]) / 3.0;
        c[2] += a * (p0[2] + p1[2] + p2[2]) / 3.0;
        a_sum += a;
    }
    if a_sum > 0.0 {
        [c[0] / a_sum, c[1] / a_sum, c[2] / a_sum]
    } else {
        [p0[0], p0[1], p0[2]]
    }
}

impl Mesh {
    /// 由 polyMesh 原始数据构建完整几何网格。
    /// `face_neigh`：仅内部面有效（长度 = n_internal）；边界面在内部填 BOUNDARY。
    pub fn build(
        points: Vec<[f64; 3]>,
        face_nodes: Vec<u32>,
        face_start: Vec<u32>,
        face_owner: Vec<u32>,
        face_neigh: Vec<u32>,
        patches: Vec<Patch>,
    ) -> Result<Mesh, String> {
        let n_faces = face_owner.len();
        let n_internal = face_neigh.len();
        if n_faces < n_internal {
            return Err(format!(
                "polyMesh 不自洽：faces={n_faces} < internal={n_internal}"
            ));
        }
        if face_start.len() != n_faces + 1 {
            return Err(format!(
                "face_start 长度 {} != n_faces+1 {}",
                face_start.len(),
                n_faces + 1
            ));
        }
        let n_cells = face_owner
            .iter()
            .chain(face_neigh.iter())
            .map(|&x| x as usize + 1)
            .max()
            .unwrap_or(0);
        // 面几何
        let mut face_sf = vec![[0.0f64; 3]; n_faces];
        let mut face_cf = vec![[0.0f64; 3]; n_faces];
        let mut face_mag = vec![0.0f64; n_faces];
        for f in 0..n_faces {
            let s = face_start[f] as usize;
            let e = face_start[f + 1] as usize;
            let nodes = &face_nodes[s..e];
            let sf = newell_area(&points, nodes);
            face_sf[f] = sf;
            face_mag[f] = norm(sf);
            face_cf[f] = polygon_centroid(&points, nodes);
        }
        // 单元→面 CSR
        let mut cell_count = vec![0u32; n_cells + 1];
        for f in 0..n_faces {
            cell_count[face_owner[f] as usize + 1] += 1;
        }
        for f in 0..n_internal {
            cell_count[face_neigh[f] as usize + 1] += 1;
        }
        let mut cell_start = vec![0u32; n_cells + 1];
        for c in 0..n_cells {
            cell_start[c + 1] = cell_start[c] + cell_count[c + 1];
        }
        let mut cell_faces = vec![0u32; cell_start[n_cells] as usize];
        let mut cursor = cell_start.clone();
        for f in 0..n_faces {
            let o = face_owner[f] as usize;
            cell_faces[cursor[o] as usize] = f as u32;
            cursor[o] += 1;
        }
        for f in 0..n_internal {
            let n = face_neigh[f] as usize;
            cell_faces[cursor[n] as usize] = f as u32;
            cursor[n] += 1;
        }
        // 单元几何：体积（散度定理）+ tet 分解重心
        let mut cell_cc = vec![[0.0f64; 3]; n_cells];
        let mut cell_vol = vec![0.0f64; n_cells];
        for c in 0..n_cells {
            let (s0, s1) = (cell_start[c] as usize, cell_start[c + 1] as usize);
            let mut c0 = [0.0f64; 3];
            for &f in &cell_faces[s0..s1] {
                c0 = [
                    c0[0] + face_cf[f as usize][0],
                    c0[1] + face_cf[f as usize][1],
                    c0[2] + face_cf[f as usize][2],
                ];
            }
            let nf = (s1 - s0) as f64;
            c0 = [c0[0] / nf, c0[1] / nf, c0[2] / nf];
            // 体积：V = (1/3)·Σ_f (±S_f)·C_f（S 取相对本单元的外法向；平面 faces 下精确）
            let mut vol = 0.0f64;
            for &f in &cell_faces[s0..s1] {
                let f = f as usize;
                let s = sf_out(&face_owner, &face_sf, f, c);
                vol += dot(s, face_cf[f]);
            }
            vol /= 3.0;
            cell_vol[c] = vol.abs();
            // tet 分解重心（tet = 临时心 c0 + 面三角，顶点序取外法向）
            let mut csum = [0.0f64; 3];
            let mut vsum = 0.0f64;
            for &f in &cell_faces[s0..s1] {
                let f = f as usize;
                let outward = face_owner[f] as usize == c;
                let ns = face_start[f] as usize;
                let ne = face_start[f + 1] as usize;
                let nodes = &face_nodes[ns..ne];
                if nodes.len() < 3 {
                    continue;
                }
                for i in 1..nodes.len() - 1 {
                    let (mut a, mut b, cc) = (
                        points[nodes[i] as usize],
                        points[nodes[i + 1] as usize],
                        points[nodes[0] as usize],
                    );
                    if !outward {
                        std::mem::swap(&mut a, &mut b);
                    }
                    let vt = dot(cross(sub(a, c0), sub(b, c0)), sub(cc, c0)) / 6.0;
                    let vt = vt.abs();
                    let ct = [
                        (c0[0] + a[0] + b[0] + cc[0]) / 4.0,
                        (c0[1] + a[1] + b[1] + cc[1]) / 4.0,
                        (c0[2] + a[2] + b[2] + cc[2]) / 4.0,
                    ];
                    csum[0] += vt * ct[0];
                    csum[1] += vt * ct[1];
                    csum[2] += vt * ct[2];
                    vsum += vt;
                }
            }
            cell_cc[c] = if vsum > 0.0 {
                [csum[0] / vsum, csum[1] / vsum, csum[2] / vsum]
            } else {
                c0
            };
        }
        let mut face_neigh_full = vec![BOUNDARY; n_faces];
        for (i, &x) in face_neigh.iter().enumerate() {
            face_neigh_full[i] = x;
        }
        Ok(Mesh {
            points,
            face_nodes,
            face_start,
            face_owner,
            face_neigh: face_neigh_full,
            face_sf,
            face_cf,
            face_mag,
            n_internal,
            cell_faces,
            cell_start,
            cell_cc,
            cell_vol,
            patches,
        })
    }

    pub fn n_cells(&self) -> usize {
        self.cell_cc.len()
    }

    pub fn n_faces(&self) -> usize {
        self.face_owner.len()
    }

    pub fn n_boundary_faces(&self) -> usize {
        self.n_faces() - self.n_internal
    }

    pub fn patch_index(&self, name: &str) -> Option<usize> {
        self.patches.iter().position(|p| p.name == name)
    }

    /// 单元 c 的所有面（全局面号）
    pub fn cell_face_iter(&self, c: usize) -> impl Iterator<Item = usize> + '_ {
        let s = self.cell_start[c] as usize;
        let e = self.cell_start[c + 1] as usize;
        self.cell_faces[s..e].iter().map(|&f| f as usize)
    }

    /// 面 f 相对单元 c 是否 owner（Sf 即 c 的外法向）
    #[inline]
    pub fn is_owner(&self, f: usize, c: usize) -> bool {
        self.face_owner[f] as usize == c
    }

    /// 面 f 相对单元 c 的外法向面积向量
    #[inline]
    pub fn face_sf_out(&self, f: usize, c: usize) -> [f64; 3] {
        sf_out(&self.face_owner, &self.face_sf, f, c)
    }

    /// 内部面 f 的对侧单元
    #[inline]
    pub fn other_cell(&self, f: usize, c: usize) -> usize {
        if self.is_owner(f, c) {
            self.face_neigh[f] as usize
        } else {
            self.face_owner[f] as usize
        }
    }

    /// 内部面 f 的 laplacian 正交分量系数 k_f = S_f·Δ/|Δ|²（Δ = C_N − C_P）
    #[inline]
    pub fn k_face(&self, f: usize) -> f64 {
        let o = self.face_owner[f] as usize;
        let n = self.face_neigh[f] as usize;
        let d = sub(self.cell_cc[n], self.cell_cc[o]);
        dot(self.face_sf[f], d) / dot(d, d)
    }

    /// 边界面 f 相对其 owner 单元的正交系数 k_b = S_f·Δ_b/|Δ_b|²
    #[inline]
    pub fn k_face_boundary(&self, f: usize) -> f64 {
        let o = self.face_owner[f] as usize;
        let d = sub(self.face_cf[f], self.cell_cc[o]);
        let dd = dot(d, d);
        if dd > 0.0 {
            dot(self.face_sf[f], d) / dd
        } else {
            0.0
        }
    }

    /// 网格统计与 checkMesh 口径核对报告
    pub fn check_report(&self) -> String {
        let mut bb_min = [f64::MAX; 3];
        let mut bb_max = [f64::MIN; 3];
        for p in &self.points {
            for k in 0..3 {
                bb_min[k] = bb_min[k].min(p[k]);
                bb_max[k] = bb_max[k].max(p[k]);
            }
        }
        let vmin = self.cell_vol.iter().cloned().fold(f64::MAX, f64::min);
        let vmax = self.cell_vol.iter().cloned().fold(f64::MIN, f64::max);
        let vtot: f64 = self.cell_vol.iter().sum();
        // 最大非正交角：Sf 与 Δ 的夹角
        let mut max_nonorth = 0.0f64;
        for f in 0..self.n_internal {
            let o = self.face_owner[f] as usize;
            let n = self.face_neigh[f] as usize;
            let d = sub(self.cell_cc[n], self.cell_cc[o]);
            let c = dot(self.face_sf[f], d) / (norm(self.face_sf[f]) * norm(d) + 1e-300);
            let ang = c.clamp(-1.0, 1.0).acos().to_degrees();
            max_nonorth = max_nonorth.max(ang);
        }
        // 面闭合检查：Σ Sf ≈ 0（每单元）
        let mut max_closure = 0.0f64;
        let mut avg_mag = 0.0f64;
        for c in 0..self.n_cells() {
            let mut s = [0.0f64; 3];
            for f in self.cell_face_iter(c) {
                let sf = self.face_sf_out(f, c);
                s[0] += sf[0];
                s[1] += sf[1];
                s[2] += sf[2];
                avg_mag += norm(sf);
            }
            max_closure = max_closure.max(norm(s));
        }
        avg_mag /= self.n_faces().max(1) as f64;
        let mut out = String::new();
        out.push_str(&format!("points            : {}\n", self.points.len()));
        out.push_str(&format!("internal faces    : {}\n", self.n_internal));
        out.push_str(&format!("boundary faces    : {}\n", self.n_boundary_faces()));
        out.push_str(&format!("faces (total)     : {}\n", self.n_faces()));
        out.push_str(&format!("cells             : {}\n", self.n_cells()));
        out.push_str(&format!(
            "bounding box      : ({:.6e}, {:.6e}, {:.6e}) - ({:.6e}, {:.6e}, {:.6e})\n",
            bb_min[0], bb_min[1], bb_min[2], bb_max[0], bb_max[1], bb_max[2]
        ));
        out.push_str(&format!(
            "cell volume       : min {:.6e}  max {:.6e}  total {:.6e}\n",
            vmin, vmax, vtot
        ));
        out.push_str(&format!(
            "max non-orthogonality : {:.3} deg\n",
            max_nonorth
        ));
        out.push_str(&format!(
            "max face-closure |Sum Sf| : {:.3e} (avg |Sf| = {:.3e})\n",
            max_closure, avg_mag
        ));
        out.push_str("patches (mean normal = -ΣSf/|ΣSf|, max face-normal deviation):\n");
        for p in &self.patches {
            let mut s = [0.0f64; 3];
            for f in p.start..p.start + p.n_faces {
                s[0] += self.face_sf[f][0];
                s[1] += self.face_sf[f][1];
                s[2] += self.face_sf[f][2];
            }
            let sm = norm(s);
            if sm > 0.0 {
                let m = [-s[0] / sm, -s[1] / sm, -s[2] / sm];
                let mut maxang = 0.0f64;
                for f in p.start..p.start + p.n_faces {
                    let fm = self.face_mag[f];
                    if fm <= 0.0 { continue; }
                    let c = -(self.face_sf[f][0] * m[0] + self.face_sf[f][1] * m[1] + self.face_sf[f][2] * m[2]) / fm;
                    maxang = maxang.max(c.clamp(-1.0, 1.0).acos().to_degrees());
                }
                out.push_str(&format!(
                    "    {:<10} mean n = ({:+.4}, {:+.4}, {:+.4})  max dev {:.2} deg\n",
                    p.name, m[0], m[1], m[2], maxang
                ));
            }
        }
        for p in &self.patches {
            out.push_str(&format!(
                "    {:<10} type {:<8} nFaces {:<8} startFace {}\n",
                p.name, p.ptype, p.n_faces, p.start
            ));
        }
        let neg_vol = self.cell_vol.iter().filter(|&&v| v <= 0.0).count();
        // 连通性（union-find over internal faces）：孤立区域 = 压力方程零空间 → 求解必炸
        let n = self.n_cells();
        let mut parent: Vec<u32> = (0..n as u32).collect();
        fn find(parent: &mut [u32], mut x: u32) -> u32 {
            while parent[x as usize] != x {
                parent[x as usize] = parent[parent[x as usize] as usize];
                x = parent[x as usize];
            }
            x
        }
        for f in 0..self.n_internal {
            let a = find(&mut parent, self.face_owner[f]);
            let b = find(&mut parent, self.face_neigh[f]);
            if a != b {
                parent[a as usize] = b;
            }
        }
        let mut roots: Vec<u32> = (0..n as u32).map(|i| find(&mut parent, i)).collect();
        roots.sort_unstable();
        roots.dedup();
        let n_comp = roots.len();
        // 各连通区域规模（前 5 大）
        let mut sizes: Vec<usize> = roots
            .iter()
            .map(|&r| (0..n as u32).filter(|&i| find(&mut parent, i) == r).count())
            .collect();
        sizes.sort_unstable_by(|a, b| b.cmp(a));
        out.push_str(&format!("connected regions   : {}\n", n_comp));
        if n_comp > 1 {
            out.push_str(&format!(
                "region sizes (top5) : {:?}\n",
                &sizes[..sizes.len().min(5)]
            ));
            out.push_str("!! 警告：存在孤立单元区域——压力方程含零空间，SIMPLE 将失稳\n");
        }
        out.push_str(&format!(
            "mesh check        : {} (non-positive cells: {})\n",
            if neg_vol == 0 && n_comp == 1 {
                "Mesh OK"
            } else {
                "Mesh FAIL"
            },
            neg_vol
        ));
        out
    }
}
